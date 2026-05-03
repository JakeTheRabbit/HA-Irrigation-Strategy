# RootSense — Frontier-LLM Health Check (Plan)

> **Status:** plan — not implemented. Targets RootSense v3.3 (per
> `ROOTSENSE_v3_PLAN.md` §6 Future Roadmap), with implementation
> patterns inherited from `LLM_ADVISOR_NOTES.md`.

This document explains how to bolt an occasional frontier-LLM advisor
onto the RootSense pipeline without burning tokens. The user's
constraint is "minimise token use"; the headline answer is **don't
call the LLM unless rule-based logic flags a situation worth a second
opinion, and when you do call it, send compact deltas instead of full
state**.

## Architecture in one diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  AppDaemon — RootSense pillars                                   │
│                                                                  │
│  root_zone   adaptive   agronomic   anomaly   orchestrator       │
│      │           │          │          │           │             │
│      └───────────┴──────────┴──────────┴───────────┘             │
│                            │                                     │
│                            ▼                                     │
│                   ┌─────────────────┐                            │
│                   │  ReportBuilder  │  every 15-30 min           │
│                   │  (rolling 1h    │                            │
│                   │   compact JSON) │                            │
│                   └────────┬────────┘                            │
│                            │                                     │
│           ┌────────────────┼─────────────────┐                   │
│           │                │                 │                   │
│           ▼                ▼                 ▼                   │
│   ┌────────────┐    ┌────────────┐    ┌────────────┐             │
│   │  Triage    │    │ Bus event  │    │  HA sensor │             │
│   │  rules     │    │ rootsense_ │    │  with last │             │
│   │  (local)   │    │ report     │    │  report    │             │
│   └─────┬──────┘    └────────────┘    └────────────┘             │
│         │                                                        │
│         │  call_llm = True only if:                              │
│         │   - severity ≥ warning, OR                             │
│         │   - 24h since last call, OR                            │
│         │   - trend score above threshold                        │
│         ▼                                                        │
│   ┌─────────────────────┐                                        │
│   │  LLMAdvisor app     │   ───── Claude / Ollama / OpenAI ──┐   │
│   │  (sends delta-only  │                                    │   │
│   │   compact prompt    │   ◄─── JSON tool call back ────────┘   │
│   │   + cached context) │                                        │
│   └─────────────────────┘                                        │
│         │                                                        │
│         │  proposes: { intent_delta, anomaly_explain, advisory } │
│         ▼                                                        │
│  IrrigationOrchestrator (existing safety gates)                  │
└──────────────────────────────────────────────────────────────────┘
```

The LLM is **always advisory**. It cannot reach hardware. It produces
JSON proposals; the existing orchestrator validates and routes them
through the same safety gates as a rule-based proposal.

## Token-minimisation playbook

Token cost = `(input × cost_in) + (output × cost_out)`. We attack both.

### 1. Don't call the LLM most of the time

A local triage rule decides whether the report warrants an LLM call:

| Signal | Triage rule | Action |
|---|---|---|
| Active anomaly with severity ≥ warning | always call | high priority |
| Dryback velocity outside ±2σ of cultivar baseline | call | medium |
| EC stack index trending past threshold | call | medium |
| FC observation confidence newly crossed 0.8 | call once | low |
| 24 h since last call | call (heartbeat) | low |
| None of the above | skip | — |

This keeps daily call count to typically **2–6**, not 48–96.

### 2. Cached system context

The Anthropic API supports prompt caching with a 5-minute TTL — system
prompt + tool definitions + recipe schema are cached at ~10× cheaper
read rate. We exploit this:

```
[system, cached]   = ~1500 tokens, billed at cache-read rate
                       contains: role, JSON schema, safety contract,
                       recipe template, tool signatures
[user, fresh]      = ~300 tokens delta-only report
[output, fresh]    = ~150 tokens JSON proposal
```

Effective per-call cost on Claude Sonnet 4.6 with prompt caching:
**~$0.003** (vs. ~$0.015 without caching). Heartbeat-only at 6 calls/day
≈ **$0.55/month**. Anomaly-driven calls add maybe another $0.20/month.

### 3. Compact JSON, not prose

The 15-min report is a single JSON object. The LLM doesn't need
full state — only what's changed and what the rule layer has already
classified. A complete report is ~300 input tokens:

```json
{
  "ts": "2026-04-26T15:30:00Z",
  "phase": "P2",
  "intent": 0,
  "zones": {
    "1": { "vwc": 58.4, "ec": 4.1, "dryback_h": 0.8, "fc": 68.5,
           "anomalies": [] },
    "2": { "vwc": 56.9, "ec": 5.2, "dryback_h": 1.3, "fc": 70.0,
           "anomalies": ["ec_drift_high"] },
    "3": { "vwc": 59.1, "ec": 4.0, "dryback_h": 0.9, "fc": 69.0,
           "anomalies": [] }
  },
  "deltas_vs_15m_ago": {
    "2.ec": "+0.3",
    "2.dryback_h": "-0.2"
  },
  "triage": "anomaly:ec_drift_high:zone=2"
}
```

Versus a 1500-token narrative report — 5× cheaper input, 5× faster.

### 4. Tiered model routing

| Tier | Model | When |
|---|---|---|
| 1 | Claude Haiku 4 (or local Llama 3.1 8B) | Heartbeat / low-severity |
| 2 | Claude Sonnet 4.6 | Anomaly explanation, intent recommendations |
| 3 | Claude Opus 4.6 | Multi-zone correlation, recipe edits |

Tier 1 handles ~80% of calls. Escalation gates: if Haiku returns
"needs more context" or low confidence, the call is repeated at Tier 2.
A monthly token budget caps the total spend.

### 5. Response is JSON-schema'd

The LLM must return a fixed-shape object. No prose, no preamble. We
prompt it with the JSON Schema and use the response_format API
parameter. Output stays at ~150 tokens regardless of how chatty the
underlying model wants to be.

```json
{
  "summary": "Zone 2 EC drifting up; recommend small flush.",
  "actions": [
    {
      "type": "intent_change",
      "delta": -5,
      "reason": "Slight generative bias to encourage stack-flushing dryback.",
      "confidence": 0.7
    },
    {
      "type": "custom_shot_proposal",
      "zone": 2,
      "intent": "rebalance_ec",
      "volume_ml": 200,
      "confidence": 0.8
    }
  ],
  "needs_human_review": false
}
```

The orchestrator's existing safety gates validate every action before
it's enacted.

## Implementation outline

### New AppDaemon apps

```
appdaemon/apps/crop_steering/intelligence/llm/
├── __init__.py
├── report_builder.py        # rolling 15-min compact JSON, fires bus event
├── triage.py                # local rules: should we call the LLM?
├── advisor.py               # the actual LLM call (provider-abstracted)
├── client.py                # Claude / OpenAI / Ollama clients (lifted
│                            #   from archive/llm-integration-v0.1)
└── budget.py                # daily/monthly token + spend caps
```

### New HA entities

- `sensor.crop_steering_rootsense_report_latest` — JSON in attributes,
  short status string in state ("ok" / "warning" / "anomaly").
- `sensor.crop_steering_llm_calls_today` — counter (matters for budget UI).
- `sensor.crop_steering_llm_spend_today` — USD estimate.
- `switch.crop_steering_llm_advisor_enabled` — module gate.
- `select.crop_steering_llm_provider` — "claude_haiku" / "claude_sonnet" /
  "ollama_local" / "off".
- `number.crop_steering_llm_max_daily_usd` — operator-set ceiling.
- `binary_sensor.crop_steering_llm_budget_exhausted` — fail-safe.

### New HA service

```yaml
service: crop_steering.llm_advisor_request
data:
  reason: "operator_curiosity"   # or "anomaly", "scheduled"
  context_extra: "Plant 3 wilting since 14:00"   # optional free text
```

Forces an LLM call outside the normal triage cadence. Useful when an
operator notices something the rules didn't catch.

### New HA event

```
crop_steering_llm_advisory
  payload: {summary, actions: [...], needs_human_review, model, tokens, cost}
```

Operator's notification automation picks this up and routes to phone,
Slack, etc. via blueprint (similar pattern to `rootsense_anomaly_handler`).

## Safety contract

The LLM **cannot**:

- Call HA services directly. It returns JSON proposals only.
- Override anomaly suppression. The orchestrator still skips suppressed zones.
- Exceed any guardrail (max shot size, min interval, EC ceiling, VWC bounds).
- Modify entity registries, settings, or scheduled tasks.

The LLM **can**:

- Suggest intent slider changes (operator confirms or the orchestrator
  applies if `confidence > 0.85` and `|delta| ≤ 10`).
- Propose `custom_shot` calls (gated like any other shot).
- Annotate anomaly events with plain-language explanations.
- Recommend recipe edits (proposed in the run report; never auto-applied).

## Rollout phases

1. **Phase L0 — Report only.** Build `report_builder.py`, publish
   sensor + bus event, no LLM call. Operator sees the JSON they'll
   later send. ~1 week shadow.
2. **Phase L1 — Triage rules.** Add `triage.py`, log "would call LLM
   now because X" without actually calling. Tunes the gate before any
   real spend.
3. **Phase L2 — Heartbeat advisor.** Wire `advisor.py` with Tier 1
   (Haiku/local). Output read-only — surfaces in dashboard, never
   issues actions.
4. **Phase L3 — Action proposals.** Allow the LLM to propose
   `intent_change` and `custom_shot`. Orchestrator gates them; require
   `needs_human_review = false` AND confidence threshold AND under
   cooldown.
5. **Phase L4 — Multi-tier routing + escalation.** Sonnet for hard
   cases; Opus for cross-zone/cross-room correlation.

Total expected effort: ~2-3 sessions of focused work post-Phase 4 of
RootSense.
