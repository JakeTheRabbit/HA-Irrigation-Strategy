"""Pillar 2 — Adaptive Irrigation Intelligence.

Cultivator-intent control, dynamic shot planning, continuous optimisation.

Three internal sub-systems:

- IntentResolver — interpolates cultivar profile parameters from a single
  intent number (-100 = generative, +100 = vegetative) and republishes them
  to the existing crop-steering number entities.
- ShotPlanner   — computes shot volume for the next P1/P2 shot from observed
  field capacity, dryback velocity, and intent.
- OptimisationLoop — Thompson-sampling bandit (numpy only) that nudges
  shot-size and inter-shot interval to maximise a reward function balancing
  dryback-target hit rate vs runoff EC error.

This file is a runnable AppDaemon app. Hardware is never touched directly;
all shot decisions are emitted as `crop_steering.custom_shot` service calls
which the orchestration coordinator then arbitrates.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from .base import IntelligenceApp
from .bus import RootSenseBus
from .store import RootSenseStore

_LOGGER = logging.getLogger(__name__)

INTENT_ENTITY = "number.crop_steering_steering_intent"


# ---------------------------------------------------------------------------
# Endpoint profiles
# ---------------------------------------------------------------------------
# Two anchor profiles. Every controller parameter is a linear interpolation
# between them, parameterised by the cultivator-intent slider.
#
# DRYBACK SEMANTIC: "p0_dryback_drop_pct" is the percentage *drop* from peak
# VWC that ends P0 — NOT the VWC value to dry down to. Matches the existing
# master_crop_steering_app exit predicate (`dryback_percent >= dryback_target`
# where dryback_percent = peak - current).
#
# Numeric defaults below are only used if the corresponding HA number entity
# is missing. Normal operation reads:
#   number.crop_steering_veg_p0_dryback_drop_pct   (vegetative endpoint)
#   number.crop_steering_gen_p0_dryback_drop_pct   (generative endpoint)
# so the operator can change either value any time from the UI.
GENERATIVE_PROFILE = {
    "p1_target_vwc": 60.0,
    "p2_vwc_threshold": 55.0,
    "p0_dryback_drop_pct": 22.0,   # mirrors DEFAULT_GEN_P0_DRYBACK_DROP_PCT
    "shot_size_pct": 4.0,
    "ec_target_flush": 3.0,
}
VEGETATIVE_PROFILE = {
    "p1_target_vwc": 70.0,
    "p2_vwc_threshold": 62.0,
    "p0_dryback_drop_pct": 12.0,   # mirrors DEFAULT_VEG_P0_DRYBACK_DROP_PCT
    "shot_size_pct": 6.0,
    "ec_target_flush": 1.8,
}

# HA number entities the cultivator edits. The IntentResolver reads from them
# every tick — so changing a slider in the UI propagates immediately.
ENTITY_VEG_DRYBACK_DROP = "number.crop_steering_veg_p0_dryback_drop_pct"
ENTITY_GEN_DRYBACK_DROP = "number.crop_steering_gen_p0_dryback_drop_pct"

# Read-only sensor that surfaces the interpolated current target. Dashboards
# and the phase state machine can subscribe to either this sensor or to the
# `number.crop_steering_p0_dryback_drop_percent` entity it maps to via
# PARAM_TO_ENTITY below.
SENSOR_CURRENT_DRYBACK_DROP = "sensor.crop_steering_p0_dryback_drop_pct_current"

# Per-parameter HA number entity that the resolver *writes back* to.
# `p0_dryback_drop_pct` is the interpolated target consumed by the phase
# state machine; the two endpoint sliders above are inputs, not outputs.
PARAM_TO_ENTITY = {
    "p1_target_vwc":          "number.crop_steering_p1_target_vwc",
    "p2_vwc_threshold":       "number.crop_steering_p2_vwc_threshold",
    # NB: integration entity is named ..._drop_percent (not _pct) — keep the
    # external name stable so legacy automations / dashboards don't break.
    "p0_dryback_drop_pct":    "number.crop_steering_p0_dryback_drop_percent",
    "shot_size_pct":          "number.crop_steering_p1_initial_shot_size",
    "ec_target_flush":        "number.crop_steering_ec_target_flush",
}


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass
class Posterior:
    """Normal-gamma posterior for a single zone's reward distribution."""
    mu: float = 0.0
    kappa: float = 1.0
    alpha: float = 2.0
    beta: float = 1.0

    def update(self, observation: float) -> None:
        kappa1 = self.kappa + 1
        mu1 = (self.kappa * self.mu + observation) / kappa1
        alpha1 = self.alpha + 0.5
        beta1 = self.beta + (self.kappa * (observation - self.mu) ** 2) / (2 * kappa1)
        self.mu, self.kappa, self.alpha, self.beta = mu1, kappa1, alpha1, beta1

    def sample(self, rng) -> float:
        # Thompson sample: tau ~ Gamma(alpha, beta), then mu ~ N(mu, 1/(kappa*tau))
        tau = rng.gamma(self.alpha, 1.0 / self.beta)
        sigma = 1.0 / math.sqrt(self.kappa * max(tau, 1e-9))
        return float(rng.normal(self.mu, sigma))


class AdaptiveIrrigation(IntelligenceApp):
    def initialize(self) -> None:
        self.bus = RootSenseBus.instance()
        self.store = RootSenseStore(self._state_dir() / "rootsense.db")
        try:
            import numpy as np
            self._rng = np.random.default_rng()
        except ImportError:
            self._rng = None
            self.log("numpy not available — optimisation loop will degrade to greedy", level="WARNING")

        self._posteriors: dict[int, Posterior] = {}

        # Re-publish derived parameters whenever intent changes
        self.listen_state(self._on_intent_changed, INTENT_ENTITY)
        # Update reward whenever a dryback completes
        self.bus.subscribe("dryback.complete", self._on_dryback_complete)

        # Initial publish so derived params are correct on startup
        self.run_in(self._publish_intent_derived_params, 5)

        self.log("AdaptiveIrrigation ready")

    # ------------------------------------------------------------------ Intent

    def _on_intent_changed(self, _entity, _attr, _old, _new, _kwargs) -> None:
        if not self._is_module_enabled():
            return
        self._publish_intent_derived_params({})

    def _publish_intent_derived_params(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        intent = self._read_intent()
        t = (intent + 100.0) / 200.0  # 0 = pure generative, 1 = pure vegetative

        # Resolve current endpoints. Dryback endpoints are read live from the
        # two operator-facing sliders; everything else falls back to the
        # static profile dicts. This is what makes "% dries back BY" fully
        # configurable — neither endpoint nor interpolated value is hardcoded.
        gen_endpoint = dict(GENERATIVE_PROFILE)
        veg_endpoint = dict(VEGETATIVE_PROFILE)
        gen_endpoint["p0_dryback_drop_pct"] = self._read_float(
            ENTITY_GEN_DRYBACK_DROP, default=GENERATIVE_PROFILE["p0_dryback_drop_pct"],
        )
        veg_endpoint["p0_dryback_drop_pct"] = self._read_float(
            ENTITY_VEG_DRYBACK_DROP, default=VEGETATIVE_PROFILE["p0_dryback_drop_pct"],
        )

        derived = {
            k: round(lerp(gen_endpoint[k], veg_endpoint[k], t), 2)
            for k in gen_endpoint
        }
        for param, value in derived.items():
            entity = PARAM_TO_ENTITY.get(param)
            if entity and self.entity_exists(entity):
                self.call_service("number/set_value", entity_id=entity, value=value)

        # Drive the derived steering-mode select for dashboards.
        self._publish_derived_mode(intent)

        # Surface the interpolated dryback as a sensor as well, so dashboards
        # can show "current P0 dryback target = 17.4% drop" without having to
        # subscribe to events.
        self.set_state(
            "sensor.crop_steering_p0_dryback_drop_pct_current",
            state=derived["p0_dryback_drop_pct"],
            attributes={
                "veg_endpoint": veg_endpoint["p0_dryback_drop_pct"],
                "gen_endpoint": gen_endpoint["p0_dryback_drop_pct"],
                "intent": intent,
                "semantic": "percentage point drop from peak VWC",
                "unit_of_measurement": "%",
                "friendly_name": "P0 dryback target (drop %)",
                "icon": "mdi:water-minus",
            },
        )

        self.bus.publish("intent.changed", {"intent": intent, "derived": derived})
        self.log("Intent=%s → %s", intent, derived)

    def _publish_derived_mode(self, intent: float) -> None:
        """Bucket the intent slider into a 5-point select."""
        if intent <= -60:
            label = "Generative"
        elif intent <= -20:
            label = "Mixed-generative"
        elif intent < 20:
            label = "Balanced"
        elif intent < 60:
            label = "Mixed-vegetative"
        else:
            label = "Vegetative"
        self.call_service(
            "select/select_option",
            entity_id="select.crop_steering_steering_mode_derived",
            option=label,
        )

    def _read_intent(self) -> float:
        try:
            return float(self.get_state(INTENT_ENTITY))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

    # _read_float lives on IntelligenceApp.

    # ------------------------------------------------------------------ ShotPlanner

    def plan_shot(self, zone: int, current_vwc: float, target_vwc: float,
                  field_capacity_pct: float, substrate_volume_l: float) -> dict[str, Any]:
        """Compute the next shot for a given zone.

        Returns a payload suitable for the `crop_steering.custom_shot` service.
        Bounded by hard guardrails.
        """
        intent = self._read_intent()
        deficit_pct = max(0.0, target_vwc - current_vwc)

        # Base volume: water needed to lift VWC from current to target,
        # assuming 1% VWC == 1% of substrate volume in mL.
        base_ml = deficit_pct * substrate_volume_l * 10.0  # 1% of 1 L = 10 mL

        # Intent bias: vegetative → +20% volume, generative → -20%
        intent_bias = 1.0 + (intent / 500.0)
        ml = base_ml * intent_bias

        # Bandit nudge
        if self._rng is not None:
            posterior = self._posteriors.setdefault(zone, self._load_posterior(zone))
            nudge = posterior.sample(self._rng)
            ml *= max(0.5, min(1.5, 1.0 + nudge / 10.0))

        # Hard guardrail: never more than 2× field capacity
        max_ml = field_capacity_pct * substrate_volume_l * 20.0  # 2× FC volume
        ml = max(50.0, min(ml, max_ml))

        return {
            "target_zone": zone,
            "intent": "planned",
            "volume_ml": round(ml, 1),
            "tag": f"adaptive:intent={intent:+g}",
        }

    # ------------------------------------------------------------------ OptimisationLoop

    def _on_dryback_complete(self, _topic: str, payload: dict[str, Any]) -> None:
        if self._rng is None or not self._is_module_enabled():
            return
        zone = int(payload.get("zone", 0))
        target = self._read_target_dryback(zone)
        observed = float(payload.get("pct", 0.0))
        ec_error = abs(float(payload.get("ec_runoff", 0)) - float(payload.get("ec_feed_target", 0)))
        reward = -(abs(observed - target)) - 0.5 * ec_error

        posterior = self._posteriors.setdefault(zone, self._load_posterior(zone))
        posterior.update(reward)
        self.store.upsert_posterior(zone, posterior.__dict__)
        self.log("Zone %s reward=%.3f → posterior μ=%.3f", zone, reward, posterior.mu)

    def _load_posterior(self, zone: int) -> Posterior:
        loaded = self.store.load_posterior(zone)
        if not loaded:
            return Posterior()
        return Posterior(**loaded)

    def _read_target_dryback(self, zone: int) -> float:
        try:
            return float(self.get_state(f"number.crop_steering_zone_{zone}_dryback_target"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 50.0

    # entity_exists lives on IntelligenceApp.
