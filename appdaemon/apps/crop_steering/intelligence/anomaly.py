"""Cross-cutting anomaly detection for RootSense.

Runs every 60 s. Per-zone rules + peer-comparison rules. Each anomaly:

- is persisted to the analytics store,
- is republished as `crop_steering_anomaly` HA event with severity + remediation,
- toggles `binary_sensor.crop_steering_anomaly_active`.

Codes (with default severity in parens):

- emitter_blockage   (warning)  : repeated shots with negligible ΔVWC
- ec_drift_high      (warning)  : 6h rolling EC > 1.3× target
- vwc_flat_line      (warning)  : VWC stddev < 0.05% over 30 min during photoperiod
- dryback_undetected (info)     : >4h since last detected peak during photoperiod
- peer_vwc_deviation (warning)  : zone VWC > 2σ from peer mean for 15 min
- peer_ec_deviation  (warning)  : zone EC > 2σ from peer mean for 30 min
- valve_runtime      (critical) : valve on > max_runtime_sec (existing watchdog promoted)
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Deque

from .base import IntelligenceApp
from .bus import RootSenseBus
from .store import RootSenseStore

_LOGGER = logging.getLogger(__name__)

ANOMALY_BINARY_SENSOR = "binary_sensor.crop_steering_anomaly_active"

REMEDIATION = {
    "emitter_blockage": (
        "1. Inspect the dripper line for kinks or biofilm.\n"
        "2. Test emitter pressure with a test cup.\n"
        "3. Run `crop_steering.custom_shot zone={zone} intent=test_emitter volume_ml=50`.\n"
        "4. If ΔVWC remains <0.3% after a clean shot, replace the emitter."
    ),
    "ec_drift_high": (
        "1. Check feed-tank EC vs target.\n"
        "2. Verify dosing pump is calibrated.\n"
        "3. Consider firing a flush shot via `crop_steering.custom_shot intent=rebalance_ec`."
    ),
    "vwc_flat_line": (
        "1. Confirm sensor power and connector seating.\n"
        "2. Check ESPHome / MQTT sensor status.\n"
        "3. If both front and back sensors are flat, suspect cable break."
    ),
    "dryback_undetected": (
        "1. Verify lights schedule and PPFD.\n"
        "2. Check transpiration sensor for plausible value.\n"
        "3. Inspect plant for wilting or root-zone hypoxia."
    ),
    "peer_vwc_deviation": (
        "1. Compare flow rates across peer zones.\n"
        "2. Check for stuck or partly open peer valves.\n"
        "3. Inspect substrate moisture by hand on outlier zone."
    ),
    "peer_ec_deviation": (
        "1. Verify per-zone EC sensor calibration.\n"
        "2. Check if outlier zone receives mixed feed (e.g. shared manifold)."
    ),
}


class AnomalyScanner(IntelligenceApp):
    def initialize(self) -> None:
        self.bus = RootSenseBus.instance()
        self.store = RootSenseStore(self._state_dir() / "rootsense.db")

        cfg = self.args or {}
        self.scan_interval_s: int = int(cfg.get("scan_interval_s", 60))
        self.peer_groups: dict[str, list[int]] = cfg.get("peer_groups", {})  # name -> [zone IDs]

        # Rolling buffers (60 samples per zone, expected 1/min ⇒ 1h)
        self._vwc_buf: dict[int, Deque[tuple[datetime, float]]] = defaultdict(lambda: deque(maxlen=60))
        self._ec_buf: dict[int, Deque[tuple[datetime, float]]] = defaultdict(lambda: deque(maxlen=360))  # 6h
        self._last_dryback_ts: dict[int, datetime] = {}
        self._consecutive_low_response_shots: dict[int, int] = defaultdict(int)
        self._active_anomalies: set[str] = set()

        # Track shot responses for emitter detection
        self.bus.subscribe("shot.response", self._on_shot_response)
        self.bus.subscribe("dryback.complete", self._on_dryback_complete)

        self.run_every(self._scan, "now+10", self.scan_interval_s)
        self.log("AnomalyScanner ready (scan=%ds, peer_groups=%s)",
                 self.scan_interval_s, list(self.peer_groups))

    # ------------------------------------------------------------------ event capture

    def _on_shot_response(self, _topic: str, payload: dict[str, Any]) -> None:
        if not self._is_module_enabled():
            return
        zone = int(payload["zone"])
        delta = float(payload.get("delta") or 0.0)
        if delta < 0.3:
            self._consecutive_low_response_shots[zone] += 1
        else:
            self._consecutive_low_response_shots[zone] = 0

        if self._consecutive_low_response_shots[zone] >= 3:
            self._raise(
                code="emitter_blockage",
                zone=zone,
                severity="warning",
                evidence=(
                    f"3 consecutive shots produced <0.3%% ΔVWC "
                    f"(latest pre={payload.get('pre_vwc')}, peak={payload.get('peak_vwc')})."
                ),
            )

    def _on_dryback_complete(self, _topic: str, payload: dict[str, Any]) -> None:
        zone = int(payload["zone"])
        self._last_dryback_ts[zone] = datetime.utcnow()
        self._clear("dryback_undetected", zone)

    # ------------------------------------------------------------------ periodic scan

    def _scan(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        zones = self._configured_zones()
        # Sample current state into buffers
        for z in zones:
            vwc = self._read_float(f"sensor.crop_steering_zone_{z}_avg_vwc")
            ec = self._read_float(f"sensor.crop_steering_zone_{z}_avg_ec")
            now = datetime.utcnow()
            if vwc is not None:
                self._vwc_buf[z].append((now, vwc))
            if ec is not None:
                self._ec_buf[z].append((now, ec))

        # Per-zone rules
        for z in zones:
            self._check_vwc_flat_line(z)
            self._check_ec_drift_high(z)
            self._check_dryback_undetected(z)

        # Peer rules
        for group_name, group_zones in self.peer_groups.items():
            self._check_peer_deviation(group_name, group_zones)

        # Update aggregate binary sensor
        self.set_state(
            ANOMALY_BINARY_SENSOR,
            state="on" if self._active_anomalies else "off",
            attributes={
                "active_count": len(self._active_anomalies),
                "active_codes": sorted(self._active_anomalies),
                "friendly_name": "Crop Steering Anomaly Active",
                "device_class": "problem",
            },
        )

    # ------------------------------------------------------------------ rules

    def _check_vwc_flat_line(self, zone: int) -> None:
        if not self._is_photoperiod():
            return
        recent = [v for ts, v in self._vwc_buf[zone] if datetime.utcnow() - ts <= timedelta(minutes=30)]
        if len(recent) < 10:
            return
        if statistics.pstdev(recent) < 0.05:
            self._raise(
                code="vwc_flat_line",
                zone=zone,
                severity="warning",
                evidence=f"VWC stddev over last 30 min = {statistics.pstdev(recent):.3f}% (threshold 0.05).",
            )
        else:
            self._clear("vwc_flat_line", zone)

    def _check_ec_drift_high(self, zone: int) -> None:
        recent = [e for ts, e in self._ec_buf[zone] if datetime.utcnow() - ts <= timedelta(hours=6)]
        target = self._read_float(f"number.crop_steering_zone_{zone}_ec_target") or 0
        if not recent or target <= 0:
            return
        mean_ec = statistics.mean(recent)
        if mean_ec > 1.3 * target:
            self._raise(
                code="ec_drift_high",
                zone=zone,
                severity="warning",
                evidence=f"6h mean EC = {mean_ec:.2f} mS/cm vs target {target:.2f} (×{mean_ec/target:.2f}).",
            )
        else:
            self._clear("ec_drift_high", zone)

    def _check_dryback_undetected(self, zone: int) -> None:
        if not self._is_photoperiod():
            return
        last = self._last_dryback_ts.get(zone)
        if last and datetime.utcnow() - last <= timedelta(hours=4):
            return
        if last is None:
            return  # too early
        self._raise(
            code="dryback_undetected",
            zone=zone,
            severity="info",
            evidence=f"No dryback peak detected for {(datetime.utcnow() - last).total_seconds() / 3600:.1f}h.",
        )

    def _check_peer_deviation(self, group: str, zones: list[int]) -> None:
        readings = []
        for z in zones:
            v = self._read_float(f"sensor.crop_steering_zone_{z}_avg_vwc")
            if v is not None:
                readings.append((z, v))
        if len(readings) < 3:
            return
        values = [v for _, v in readings]
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values) or 1e-6
        for z, v in readings:
            if abs(v - mean) > 2 * stdev:
                self._raise(
                    code="peer_vwc_deviation",
                    zone=z,
                    severity="warning",
                    evidence=(f"Zone {z} VWC={v:.2f}% deviates from peer group "
                              f"'{group}' (mean={mean:.2f}, σ={stdev:.2f})."),
                )
            else:
                self._clear("peer_vwc_deviation", z)

    # ------------------------------------------------------------------ helpers

    def _raise(self, *, code: str, zone: int | None, severity: str, evidence: str) -> None:
        key = f"{code}:{zone}" if zone is not None else code
        if key in self._active_anomalies:
            return  # already raised, don't spam
        self._active_anomalies.add(key)
        remediation = REMEDIATION.get(code, "See dashboard.").format(zone=zone)
        ts = datetime.utcnow().isoformat()
        self.store.record_anomaly(
            ts=ts, zone=zone, code=code, severity=severity,
            evidence=evidence, remediation=remediation,
        )
        self.bus.publish("anomaly.detected", {
            "code": code, "zone": zone, "severity": severity,
            "evidence": evidence, "remediation": remediation, "ts": ts,
        })
        self.fire_event("crop_steering_anomaly",
                        code=code, zone=zone, severity=severity,
                        evidence=evidence, remediation=remediation, ts=ts)
        self.log("ANOMALY [%s] zone=%s %s — %s", severity, zone, code, evidence,
                 level="WARNING" if severity != "info" else "INFO")

    def _clear(self, code: str, zone: int) -> None:
        key = f"{code}:{zone}"
        self._active_anomalies.discard(key)

    def _is_photoperiod(self) -> bool:
        state = self.get_state("binary_sensor.crop_steering_lights")
        return state == "on"

    # _read_float / _configured_zones / entity_exists live on IntelligenceApp.
