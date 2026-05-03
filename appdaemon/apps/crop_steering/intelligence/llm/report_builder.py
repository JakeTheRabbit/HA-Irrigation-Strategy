"""L0 Report Builder — compact JSON snapshot every 15 min.

NO LLM call. This is the shadow phase: produce the artefact that a
future LLM advisor would consume, expose it for operator review, and
let it run for a few weeks so the schema and triage tags get a real-
world shakedown before any tokens are spent.

Schema (target ~300 input tokens — verify with a tokeniser when L1 lands):

  {
    "ts": "2026-04-26T15:30:00Z",
    "phase": "P2",                              ← crop steering phase
    "intent": 0,                                ← cultivator slider
    "recipe_phase": "Mid flower (week 3-5)",    ← climate recipe
    "recipe_day": 28,
    "climate": {
      "temp_c": 26.5, "temp_target": 26.0, "temp_status": "near_target",
      "rh_pct": 56, "rh_target": 55,
      "leaf_vpd_kpa": 1.14, "leaf_vpd_target": 1.20,
      "co2_ppm": 1280, "co2_target": 1300,
      "dli_today_mol": 16.2, "dli_predicted_mol": 37.4,
      "lights_on": true
    },
    "substrate": {
      "1": {"vwc": 58.4, "ec": 4.1, "dryback_h": 0.8, "fc": 68.5},
      "2": {"vwc": 56.9, "ec": 5.2, "dryback_h": 1.3, "fc": 70.0}
    },
    "deltas_15m_ago": {
      "climate.rh_pct": "+2",
      "substrate.2.ec": "+0.3"
    },
    "active_anomalies": ["ec_drift_high:zone=2"],
    "triage": "anomaly:ec_drift_high"
  }

Status flags (`*_status`) are computed locally:
  - "on_target" : within ±0.5 × tolerance
  - "near_target": within tolerance
  - "off_target": outside tolerance

The triage tag is the local rule engine's verdict on whether an LLM
call would be warranted (always logged in L0; only acted on in L1+).

  - "ok"                         : no concerns
  - "anomaly:<code>"             : an anomaly is active
  - "drift:<metric>"             : metric persistently off-target
  - "heartbeat"                  : 24 h since last triage tag

Published as:
  sensor.crop_steering_rootsense_report_latest
    state = triage tag (string)
    attributes = full JSON above + last_built_ts
  bus event "report.ready"        — payload = full JSON
  HA event "crop_steering_rootsense_report"   — same payload

A second sensor `sensor.crop_steering_rootsense_report_size_tokens`
estimates token count via len(json) / 4 (rough but close enough for
budget alerts in L1+).
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque

from ..base import IntelligenceApp
from ..bus import RootSenseBus
from ..store import RootSenseStore
from ..climate.hardware import HardwareCalibration, load_hardware_calibration

_LOGGER = logging.getLogger(__name__)

DEFAULT_INTERVAL_MIN = 15

# Tolerances used for status classification when the recipe doesn't
# declare them. Conservative — operators tighten via recipe.
DEFAULT_TOLERANCE = {
    "temp_c": 1.0,
    "rh_pct": 5.0,
    "vpd_kpa": 0.15,
    "leaf_vpd_kpa": 0.15,
    "co2_ppm": 100.0,
}


def classify_status(value: float, target: float, tolerance: float) -> str:
    """Bucket a measurement vs target into one of three labels."""
    err = abs(value - target)
    if err <= 0.5 * tolerance:
        return "on_target"
    if err <= tolerance:
        return "near_target"
    return "off_target"


def compute_deltas(prev: dict[str, Any], current: dict[str, Any],
                   *, threshold: float = 1.0) -> dict[str, str]:
    """Return signed string deltas for keys that changed by ≥ threshold.

    Keys are dotted paths like 'climate.temp_c' or 'substrate.2.ec'.
    Threshold is in the metric's native unit. Below threshold = noise.
    """
    out: dict[str, str] = {}
    _walk_deltas(prev, current, prefix="", threshold=threshold, out=out)
    return out


def _walk_deltas(a: dict[str, Any], b: dict[str, Any], *,
                 prefix: str, threshold: float, out: dict[str, str]) -> None:
    for key, b_val in b.items():
        a_val = a.get(key)
        path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(b_val, dict) and isinstance(a_val, dict):
            _walk_deltas(a_val, b_val, prefix=path, threshold=threshold, out=out)
            continue
        if not isinstance(b_val, (int, float)) or not isinstance(a_val, (int, float)):
            continue
        diff = b_val - a_val
        if abs(diff) >= threshold:
            out[path] = f"{diff:+.2f}".rstrip("0").rstrip(".") or "+0"


def compute_triage(snapshot: dict[str, Any], active_anomalies: set[str],
                   last_triage_at: datetime | None,
                   now: datetime) -> str:
    """Return a string triage tag. Local rule engine only — no LLM."""
    if active_anomalies:
        # Pick the highest-severity / longest-active anomaly
        sample = sorted(active_anomalies)[0]
        return f"anomaly:{sample}"

    # Drift detection: any climate metric persistently off_target
    climate = snapshot.get("climate", {})
    for k, v in climate.items():
        if k.endswith("_status") and v == "off_target":
            metric = k.replace("_status", "")
            return f"drift:{metric}"

    # Heartbeat
    if last_triage_at is None:
        return "heartbeat"
    if (now - last_triage_at) >= timedelta(hours=24):
        return "heartbeat"

    return "ok"


def estimate_tokens(payload: dict[str, Any]) -> int:
    """Rough token count: json length / 4. Good enough for budget alerts."""
    s = json.dumps(payload, separators=(",", ":"))
    return len(s) // 4


# ─────────────────────────────────────────────────────────────────────
# AppDaemon app
# ─────────────────────────────────────────────────────────────────────


class RootSenseReportBuilder(IntelligenceApp):
    """Builds and publishes the L0 report on a fixed cadence."""

    def initialize(self) -> None:  # noqa: D401
        self.bus = RootSenseBus.instance()
        self.store = RootSenseStore(self._state_dir() / "rootsense.db")

        cfg = self.args or {}
        interval_min = int(cfg.get("interval_minutes", DEFAULT_INTERVAL_MIN))
        self.delta_threshold = float(cfg.get("delta_threshold", 1.0))

        # Hardware calibration is the source of truth for sensor entity names
        try:
            hardware_path = Path(cfg.get(
                "hardware_file",
                str(Path(self.app_dir) / "crop_steering" / "intelligence" / "climate" / "hardware_f1.yaml"),
            ))
            self.hw: HardwareCalibration | None = load_hardware_calibration(hardware_path)
        except Exception as e:  # noqa: BLE001
            self.log("RootSenseReportBuilder: hw load failed: %s — degraded", e, level="WARNING")
            self.hw = None

        # Rolling history of the last few snapshots — used for delta computation
        self._history: Deque[dict[str, Any]] = deque(maxlen=8)
        self._active_anomalies: set[str] = set()
        self._last_triage_at: datetime | None = None

        # Anomaly tracking from the bus
        self.bus.subscribe("anomaly.detected", self._on_anomaly)

        # Schedule the report tick
        self.run_every(self._tick, "now+30", interval_min * 60)

        self.log("RootSenseReportBuilder ready (interval=%dmin, delta_threshold=%g)",
                 interval_min, self.delta_threshold)

    # ------------------------------------------------------------------ tick

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        try:
            payload = self.build_report(now=datetime.utcnow())
        except Exception as e:  # noqa: BLE001
            self.log("Report build failed: %s", e, level="ERROR")
            return

        self._publish(payload)
        self._history.append(payload)
        if payload.get("triage", "ok") != "ok":
            self._last_triage_at = datetime.utcnow()

    # ------------------------------------------------------------------ public for tests

    def build_report(self, *, now: datetime,
                     state_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build the report payload. `state_overrides` lets tests inject
        synthetic HA state so we don't need a running AppDaemon."""
        get = state_overrides.get if state_overrides else self.get_state

        climate = self._build_climate(get)
        substrate = self._build_substrate(get)
        snapshot: dict[str, Any] = {
            "ts": now.isoformat(),
            "phase": str(get("select.crop_steering_irrigation_phase") or "unknown"),
            "intent": _to_float(get("number.crop_steering_steering_intent"), default=0.0),
            "recipe_phase": str(get("sensor.climate_recipe_active_phase") or "unknown"),
            "recipe_day": _to_int(get("number.crop_steering_climate_grow_day_offset"), default=0),
            "climate": climate,
            "substrate": substrate,
        }

        # Deltas vs the report from ~15 min ago (if we have one)
        if self._history:
            prev = self._history[-1]
            snapshot["deltas_15m_ago"] = compute_deltas(prev, snapshot,
                                                         threshold=self.delta_threshold)
        else:
            snapshot["deltas_15m_ago"] = {}

        # Anomalies + triage
        snapshot["active_anomalies"] = sorted(self._active_anomalies)
        snapshot["triage"] = compute_triage(
            snapshot, self._active_anomalies, self._last_triage_at, now,
        )
        snapshot["estimated_tokens"] = estimate_tokens(snapshot)
        return snapshot

    # ------------------------------------------------------------------ builders

    def _build_climate(self, get) -> dict[str, Any]:
        s = self.hw.sensors if self.hw else None
        climate: dict[str, Any] = {}

        temp = _to_float(get(s.temp_primary) if s else None)
        rh = _to_float(get(s.rh_primary) if s else None)
        co2 = _to_float(get(s.co2) if s else None)
        leaf_vpd = _to_float(get("sensor.climate_leaf_vpd_kpa"))
        air_vpd = _to_float(get(s.vpd) if s else None)
        lights = str(get(s.lights_on) if s else "off").lower() == "on"

        # Targets
        is_day = lights
        temp_target = _to_float(get(
            f"sensor.climate_target_{'day' if is_day else 'night'}_temp_c"
        ))
        rh_target = _to_float(get(
            f"sensor.climate_target_{'day' if is_day else 'night'}_rh_pct"
        ))
        leaf_vpd_target = _to_float(get("sensor.climate_target_leaf_vpd_kpa"))
        co2_target = _to_float(get("sensor.climate_target_co2_ppm"))

        if temp is not None:
            climate["temp_c"] = round(temp, 2)
        if rh is not None:
            climate["rh_pct"] = round(rh, 1)
        if leaf_vpd is not None:
            climate["leaf_vpd_kpa"] = round(leaf_vpd, 3)
        if air_vpd is not None:
            climate["air_vpd_kpa"] = round(air_vpd, 3)
        if co2 is not None:
            climate["co2_ppm"] = round(co2, 0)
        climate["lights_on"] = lights

        # DLI
        dli_today = _to_float(get("sensor.climate_dli_today_mol"))
        dli_pred = _to_float(get("sensor.climate_dli_predicted_mol"))
        if dli_today is not None:
            climate["dli_today_mol"] = round(dli_today, 2)
        if dli_pred is not None:
            climate["dli_predicted_mol"] = round(dli_pred, 2)

        # Targets + status
        if temp is not None and temp_target is not None:
            climate["temp_target"] = round(temp_target, 2)
            climate["temp_status"] = classify_status(temp, temp_target,
                                                     DEFAULT_TOLERANCE["temp_c"])
        if rh is not None and rh_target is not None:
            climate["rh_target"] = round(rh_target, 1)
            climate["rh_status"] = classify_status(rh, rh_target,
                                                   DEFAULT_TOLERANCE["rh_pct"])
        if leaf_vpd is not None and leaf_vpd_target is not None:
            climate["leaf_vpd_target"] = round(leaf_vpd_target, 3)
            climate["leaf_vpd_status"] = classify_status(leaf_vpd, leaf_vpd_target,
                                                          DEFAULT_TOLERANCE["leaf_vpd_kpa"])
        if co2 is not None and co2_target is not None:
            climate["co2_target"] = round(co2_target, 0)
            climate["co2_status"] = classify_status(co2, co2_target,
                                                    DEFAULT_TOLERANCE["co2_ppm"])

        return climate

    def _build_substrate(self, get) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for n in range(1, 25):
            vwc = _to_float(get(f"sensor.crop_steering_zone_{n}_avg_vwc"))
            if vwc is None:
                continue
            ec = _to_float(get(f"sensor.crop_steering_zone_{n}_avg_ec"))
            db_v = _to_float(get(f"sensor.crop_steering_zone_{n}_dryback_velocity_pct_per_hr"))
            fc = _to_float(get(f"sensor.crop_steering_zone_{n}_field_capacity_observed"))
            entry: dict[str, Any] = {"vwc": round(vwc, 2)}
            if ec is not None:
                entry["ec"] = round(ec, 2)
            if db_v is not None:
                entry["dryback_h"] = round(db_v, 2)
            if fc is not None:
                entry["fc"] = round(fc, 1)
            out[str(n)] = entry
        return out

    # ------------------------------------------------------------------ publishing

    def _publish(self, payload: dict[str, Any]) -> None:
        triage = str(payload.get("triage", "ok"))
        # Sensor: state = triage tag, attributes = full JSON
        self.set_state(
            "sensor.crop_steering_rootsense_report_latest",
            state=triage,
            attributes={
                "report": payload,
                "estimated_tokens": payload.get("estimated_tokens", 0),
                "last_built_ts": payload.get("ts"),
                "icon": "mdi:file-document-outline",
                "friendly_name": "RootSense L0 report (latest)",
            },
        )
        self.set_state(
            "sensor.crop_steering_rootsense_report_size_tokens",
            state=payload.get("estimated_tokens", 0),
            attributes={
                "unit_of_measurement": "tokens",
                "icon": "mdi:counter",
                "friendly_name": "RootSense L0 report size (estimated)",
                "state_class": "measurement",
            },
        )

        self.bus.publish("report.ready", payload)
        self.fire_event("crop_steering_rootsense_report", **{
            "triage": triage,
            "estimated_tokens": payload.get("estimated_tokens"),
            "ts": payload.get("ts"),
            # Full payload too — listeners that don't care can ignore
            "report": payload,
        })

    # ------------------------------------------------------------------ event handlers

    def _on_anomaly(self, _topic: str, payload: dict[str, Any]) -> None:
        code = payload.get("code")
        if not code:
            return
        zone = payload.get("zone")
        key = f"{code}:zone={zone}" if zone else code
        self._active_anomalies.add(key)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _to_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: int = 0) -> int:
    f = _to_float(v)
    return int(f) if f is not None else default
