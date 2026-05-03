"""LLM advisor package — RootSense Phase L0+.

Five-phase rollout (per docs/upgrade/LLM_HEALTHCHECK_PLAN.md):
  L0  Report only       — build + publish 15-min compact JSON. No LLM call. (THIS COMMIT)
  L1  Triage rules      — log "would call now because X" without calling.
  L2  Heartbeat advisor — Tier 1 (Haiku/local) read-only.
  L3  Action proposals  — orchestrator gates JSON proposals.
  L4  Multi-tier        — Sonnet/Opus escalation.

L0 deliverable: `report_builder.py` produces a compact ~300-token JSON
snapshot of the room every 15 min. Published as a sensor and as a bus
event. The LLM call is intentionally absent so operators can review the
report content for a few weeks before any tokens are spent.
"""
from __future__ import annotations

LLM_VERSION = "0.1.0-dev"

__all__ = ["report_builder"]
