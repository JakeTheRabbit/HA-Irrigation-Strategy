# LLM Advisor — salvage notes from `llm-integration`

> **Status:** archived for future reference. Do not import these modules
> directly — they target the pre-RootSense v2.x architecture and several
> external dependencies (specifically GPT-5 model names and 2025 pricing)
> are already stale.
>
> **How to find the source:** `git checkout archive/llm-integration-v0.1`
> or browse the tag on GitHub. The original branch was deleted on
> 2026-04-26 to keep the active branch list clean.

The `llm-integration` branch (~3,200 lines of LLM-specific Python plus
heavy README churn) was an exploratory cloud-LLM advisor for the v2.x
controller. It is being archived rather than merged because:

1. The pillar refactor in RootSense v3.0 makes the existing
   `appdaemon/apps/crop_steering/llm/llm_enhanced_app.py` mostly
   incompatible with the new architecture — it would need a near-total
   rewrite against `IntelligenceApp` and the orchestration coordinator.
2. The GPT-5-specific config, prompts, and prices are already out of
   date.
3. The branch was cloud-LLM only. RootSense v3.0 explicitly promises
   "fully local, no external egress". Future LLM advisor work needs an
   opt-in switch with that contract preserved.
4. 13 of the 25 commits are README/docs churn that would conflict
   heavily with the cleaned-up docs on `main`.

The **architectural ideas** below, however, are sound and should inform
RootSense v3.3 ("Local LLM Advisor") when that phase comes around.

---

## 1. LLM-as-advisor with rule-based fallback

**Where it lives:** `custom_components/crop_steering/llm/decision_engine.py`
in the archive tag — see `_get_rule_based_decision()` (line 417) and
`_get_rule_based_phase_decision()` (line 516).

The pattern: every LLM call is wrapped by a deterministic rule-based
decision function that runs first to compute a baseline, then the LLM
is asked to *agree, disagree, or refine*. If the LLM is unavailable,
times out, returns malformed JSON, or produces a decision the
`_validate_llm_decision()` step rejects, the rule-based answer is used
verbatim. The LLM is never the only source of truth.

For RootSense v3.3, this maps directly onto:

- `intelligence/orchestration.py` Coordinator already arbitrates between
  pillar proposals — add an "advisor" pillar that proposes shots, and
  let the Coordinator's existing safety gates be the validator.
- The bandit posterior in `adaptive_irrigation.OptimisationLoop` already
  produces a deterministic baseline; an LLM advisor would compete with
  it under a small probability budget.

## 2. Provider abstraction (Claude / OpenAI / local)

**Where it lives:** `custom_components/crop_steering/llm/client.py` —
`LLMClient` (ABC), `ClaudeClient`, `OpenAIClient`, `LLMClientFactory`,
and `ResilientLLMClient` for retry/backoff.

Worth keeping the shape of, but for v3.3 the priority should be a
**local** client (Ollama, LM Studio, llama.cpp HTTP server). The
factory pattern is right — just add `LocalClient` as the default and
demote cloud providers to opt-in.

`LLMResponse` and `LLMConfig` dataclasses are reusable as-is.

## 3. Cost optimizer + budget config

**Where it lives:**
`custom_components/crop_steering/llm/cost_optimizer.py` — `BudgetConfig`,
`UsageRecord`, `UsageStats`, `CostOptimizer` with daily/monthly windows.

Genuinely useful even if RootSense v3.3 ships local-only — replace
"dollars" with "tokens" or "wall-clock GPU seconds" and the same
structure works. The `CostTier` enum and `get_cost_optimization_recommendation()`
method are the parts to lift.

## 4. Prompt-type taxonomy

**Where it lives:** `custom_components/crop_steering/llm/prompts.py` —
`PromptType` enum:

- `IRRIGATION_DECISION`
- `PHASE_TRANSITION`
- `TROUBLESHOOTING`
- `OPTIMIZATION`
- `EMERGENCY_ANALYSIS`
- `SENSOR_VALIDATION`
- `GROWTH_ANALYSIS`

Plus `PromptComplexity` levels for routing cheap requests to small
models and expensive ones to bigger models.

The taxonomy is the contribution; the actual templates inside are
GPT-5-tuned and would need rewriting. Several entries (`TROUBLESHOOTING`,
`SENSOR_VALIDATION`, `EMERGENCY_ANALYSIS`) line up exactly with
RootSense's anomaly scanner output and would be the most natural first
LLM hookup — turn an `anomaly.detected` event payload into a
`TROUBLESHOOTING` prompt and let the advisor draft remediation prose.

## 5. Decision validator before hardware action

**Where it lives:** `decision_engine.py:377` — `_validate_llm_decision()`
checks the LLM's proposed action against safety thresholds (max shot
size, min interval, EC ceiling, VWC bounds) and rejects if violated.

This is non-negotiable for any future LLM advisor and should be a hard
contract: the LLM cannot reach hardware. It produces a `dict`,
`IrrigationOrchestrator` validates and routes it through the same gates
as a rule-based proposal. RootSense already has the gates; v3.3 just
needs a "shot-proposal validator" hook that accepts proposals tagged
`origin=llm`.

---

## What's *not* worth carrying forward

- `gpt5_config.py` — model and pricing specifics are stale.
- The 13 README/docs commits — main has since been cleaned up
  thoroughly, those rewrites are obsolete.
- `appdaemon/apps/crop_steering/llm/llm_enhanced_app.py` — wires into
  the old monolithic `master_crop_steering_app`; replace, don't port.
- The GPT-5-specific prompt templates inside `prompts.py` — keep the
  enum and overall structure, rewrite the bodies.

---

## Roadmap pointer

This work corresponds to **RootSense v3.3 — Local LLM Advisor** in
`docs/upgrade/ROOTSENSE_v3_PLAN.md` §6 Future Roadmap. When that phase
opens, start by re-reading these notes and the archive tag, *not* by
reviving the branch.
