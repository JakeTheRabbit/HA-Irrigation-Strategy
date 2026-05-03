"""Pillar 1 — Root Zone Intelligence.

Substrate analytics, automated field-capacity detection, dryback tracking.

This file is a runnable AppDaemon app. It registers with the master app via
`RootSenseBus`, listens for shot events, and publishes:

- `sensor.crop_steering_zone_{n}_field_capacity_observed`
- `sensor.crop_steering_zone_{n}_dryback_velocity_pct_per_hr`
- `sensor.crop_steering_zone_{n}_substrate_porosity_estimate_ml_per_pct`
- `sensor.crop_steering_zone_{n}_ec_stack_index`

Plus events:
- `crop_steering_dryback_complete`
- `crop_steering_field_capacity_observed`

Behaviour summary (see ROOTSENSE_v3_PLAN.md §3 Phase 1 for full design):

1. On every `crop_steering_irrigation_shot` event, snapshot pre-shot VWC.
2. Wait `shot_response_window_sec` (default 600 s) and capture the post-shot
   peak VWC for that zone.
3. If two successive shots produce <0.5 % additional rise, declare the zone
   saturated; the peak becomes a candidate FC observation.
4. Maintain an EWMA per (zone, cultivar). Confidence ≥ 0.8 ⇒ controller uses
   observed FC instead of the static `DEFAULT_FIELD_CAPACITY`.
5. Independently, sample VWC + EC every 60 s into a per-zone rolling buffer
   used to detect dryback episodes (peak → valley) locally and publish the
   three derived analytics sensors.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Deque

from .base import IntelligenceApp
from .bus import RootSenseBus
from .store import RootSenseStore

_LOGGER = logging.getLogger(__name__)

DEFAULT_RESPONSE_WINDOW_SEC = 600
DEFAULT_SATURATION_DELTA_PCT = 0.5      # < this rise on consecutive shots ⇒ saturated
DEFAULT_FC_EWMA_ALPHA = 0.25
DEFAULT_FC_CONFIDENCE_THRESHOLD = 0.8
DEFAULT_SAMPLE_INTERVAL_SEC = 60
DEFAULT_BUFFER_HOURS = 24
DEFAULT_DRYBACK_MIN_DROP_PCT = 1.0      # ignore micro-fluctuations
DEFAULT_DRYBACK_MIN_DURATION_MIN = 15   # peak must hold for at least this long


@dataclass
class ShotResponse:
    zone: int
    pre_vwc: float
    fired_at: datetime
    pre_ec: float | None = None
    volume_ml: float | None = None
    peak_vwc: float | None = None
    peak_at: datetime | None = None

    @property
    def delta_vwc(self) -> float | None:
        return None if self.peak_vwc is None else self.peak_vwc - self.pre_vwc


@dataclass
class FieldCapacityState:
    fc_pct: float = 0.0
    confidence: float = 0.0
    sample_count: int = 0
    history: Deque[float] = field(default_factory=lambda: deque(maxlen=20))


@dataclass
class DrybackTracker:
    """Per-zone running peak/valley tracker.

    A peak is a local max in the VWC buffer. We then track valley (the
    minimum since the peak) and emit a `DrybackEpisode` when a *new* peak
    starts forming, i.e. VWC rises again from the valley by at least
    DEFAULT_DRYBACK_MIN_DROP_PCT.
    """
    peak_ts: datetime | None = None
    peak_vwc: float | None = None
    peak_ec: float | None = None
    valley_ts: datetime | None = None
    valley_vwc: float | None = None
    valley_ec: float | None = None


class RootZoneIntelligence(IntelligenceApp):
    """AppDaemon entry point."""

    def initialize(self) -> None:  # noqa: D401 — AppDaemon contract
        self.bus = RootSenseBus.instance()
        self.store = RootSenseStore(self._state_dir() / "rootsense.db")

        cfg = self.args or {}
        self.response_window_sec: int = int(cfg.get("response_window_sec", DEFAULT_RESPONSE_WINDOW_SEC))
        self.saturation_delta_pct: float = float(cfg.get("saturation_delta_pct", DEFAULT_SATURATION_DELTA_PCT))
        self.fc_alpha: float = float(cfg.get("fc_ewma_alpha", DEFAULT_FC_EWMA_ALPHA))
        self.fc_confidence_threshold: float = float(
            cfg.get("fc_confidence_threshold", DEFAULT_FC_CONFIDENCE_THRESHOLD)
        )
        self.sample_interval_sec: int = int(cfg.get("sample_interval_sec", DEFAULT_SAMPLE_INTERVAL_SEC))
        self.buffer_hours: int = int(cfg.get("buffer_hours", DEFAULT_BUFFER_HOURS))
        self.dryback_min_drop_pct: float = float(cfg.get("dryback_min_drop_pct", DEFAULT_DRYBACK_MIN_DROP_PCT))
        self.dryback_min_duration_min: float = float(
            cfg.get("dryback_min_duration_min", DEFAULT_DRYBACK_MIN_DURATION_MIN)
        )

        # Buffer length: one sample per `sample_interval_sec`, kept for `buffer_hours`.
        buf_len = max(60, int(self.buffer_hours * 3600 / self.sample_interval_sec))
        self._vwc_buf: dict[int, Deque[tuple[datetime, float]]] = defaultdict(lambda: deque(maxlen=buf_len))
        self._ec_buf: dict[int, Deque[tuple[datetime, float]]] = defaultdict(lambda: deque(maxlen=buf_len))

        self._pending: dict[int, ShotResponse] = {}
        self._fc: dict[int, FieldCapacityState] = defaultdict(FieldCapacityState)
        self._dryback: dict[int, DrybackTracker] = defaultdict(DrybackTracker)

        # Bridge HA event bus into RootSenseBus
        self.listen_event(self._on_shot_fired, "crop_steering_irrigation_shot")

        # Sample sensors and publish derived metrics every minute (default).
        self.run_every(self._tick, "now+30", self.sample_interval_sec)

        # Daily prune
        self.run_daily(self._daily_prune, "03:30:00")

        self.log(
            "RootZoneIntelligence ready (window=%ds sat-Δ=%.2f%% sample=%ds buf=%dh)",
            self.response_window_sec,
            self.saturation_delta_pct,
            self.sample_interval_sec,
            self.buffer_hours,
        )

    # ------------------------------------------------------------------ tick

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        now = datetime.utcnow()
        for zone in self._configured_zones():
            vwc = self._read_zone_vwc(zone)
            ec = self._read_float(f"sensor.crop_steering_zone_{zone}_avg_ec")
            if vwc is not None:
                self._vwc_buf[zone].append((now, vwc))
                self._step_dryback_tracker(zone, now, vwc, ec)
            if ec is not None:
                self._ec_buf[zone].append((now, ec))

            self._publish_dryback_velocity(zone)
            self._publish_porosity_estimate(zone)
            self._publish_ec_stack_index(zone)

    # ------------------------------------------------------------------ shot lifecycle

    def _on_shot_fired(self, event_name: str, data: dict[str, Any], _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        zone = int(data.get("zone", 0))
        if zone <= 0:
            return
        pre_vwc = self._read_zone_vwc(zone)
        if pre_vwc is None:
            self.log("Skipping shot response capture for zone %s: VWC unavailable", zone)
            return
        self._pending[zone] = ShotResponse(
            zone=zone,
            pre_vwc=pre_vwc,
            pre_ec=self._read_float(f"sensor.crop_steering_zone_{zone}_avg_ec"),
            fired_at=datetime.utcnow(),
            volume_ml=data.get("volume_ml"),
        )
        self.run_in(self._capture_peak, self.response_window_sec, zone=zone)

    def _capture_peak(self, kwargs: dict[str, Any]) -> None:
        zone = kwargs["zone"]
        record = self._pending.pop(zone, None)
        if record is None:
            return
        peak_vwc = self._peak_vwc_in_buffer_since(zone, record.fired_at)
        if peak_vwc is None:
            return
        record.peak_vwc = peak_vwc
        record.peak_at = datetime.utcnow()

        self.bus.publish("shot.response", {
            "zone": zone,
            "pre_vwc": record.pre_vwc,
            "peak_vwc": peak_vwc,
            "delta": record.delta_vwc,
            "volume_ml": record.volume_ml,
            "fired_at": record.fired_at.isoformat(),
        })

        # Persist the response for porosity estimation.
        self.store.record_shot(
            ts=record.fired_at.isoformat(),
            zone=zone,
            shot_type="response",
            volume_ml=record.volume_ml,
            vwc_before=record.pre_vwc,
            vwc_peak=peak_vwc,
            ec_feed=record.pre_ec,
        )

        self._update_field_capacity(record)

    # ------------------------------------------------------------------ field capacity

    def _update_field_capacity(self, record: ShotResponse) -> None:
        zone = record.zone
        fc = self._fc[zone]
        fc.history.append(record.peak_vwc or 0.0)

        if len(fc.history) < 2:
            return
        last_two = list(fc.history)[-2:]
        rise_between_shots = last_two[1] - last_two[0]
        if rise_between_shots > self.saturation_delta_pct:
            return  # not yet saturated

        observed_fc = last_two[1]
        # EWMA
        if fc.sample_count == 0:
            fc.fc_pct = observed_fc
        else:
            fc.fc_pct = self.fc_alpha * observed_fc + (1 - self.fc_alpha) * fc.fc_pct
        fc.sample_count += 1
        fc.confidence = min(1.0, fc.sample_count / 5.0)

        cultivar = self._read_zone_cultivar(zone)
        self.store.record_field_capacity(
            ts=datetime.utcnow().isoformat(),
            zone=zone,
            cultivar=cultivar,
            fc_pct=fc.fc_pct,
            confidence=fc.confidence,
            sample_count=fc.sample_count,
        )

        self._publish_fc_sensor(zone, fc)
        self.bus.publish("field_capacity.observed", {
            "zone": zone,
            "fc_pct": fc.fc_pct,
            "confidence": fc.confidence,
            "sample_count": fc.sample_count,
            "cultivar": cultivar,
        })
        self.fire_event("crop_steering_field_capacity_observed", **{
            "zone": zone,
            "fc_pct": round(fc.fc_pct, 2),
            "confidence": round(fc.confidence, 2),
        })

    def _publish_fc_sensor(self, zone: int, fc: FieldCapacityState) -> None:
        self.set_state(
            f"sensor.crop_steering_zone_{zone}_field_capacity_observed",
            state=round(fc.fc_pct, 2),
            attributes={
                "confidence": round(fc.confidence, 3),
                "sample_count": fc.sample_count,
                "unit_of_measurement": "%",
                "friendly_name": f"Zone {zone} Observed Field Capacity",
                "icon": "mdi:water-percent",
            },
        )

    # ------------------------------------------------------------------ dryback episodes

    def _step_dryback_tracker(self, zone: int, now: datetime, vwc: float, ec: float | None) -> None:
        """Update the per-zone peak/valley tracker with the latest sample.

        State machine:
          1. Initial: no peak yet → first sample becomes a candidate peak.
          2. Tracking peak: each higher VWC raises the peak.
          3. Once VWC has dropped from peak by >= dryback_min_drop_pct, we
             leave "rising" and start tracking valley.
          4. Each lower VWC lowers the valley.
          5. When VWC rises from valley by >= dryback_min_drop_pct AND the
             peak-to-now duration is >= dryback_min_duration_min, we emit a
             DrybackEpisode and reset (the new sample becomes the next peak
             candidate).
        """
        t = self._dryback[zone]

        if t.peak_vwc is None or vwc > t.peak_vwc:
            # Either fresh start or new (higher) peak found.
            t.peak_ts, t.peak_vwc, t.peak_ec = now, vwc, ec
            t.valley_ts, t.valley_vwc, t.valley_ec = None, None, None
            return

        # We are currently in a dryback (post-peak). Track the running valley.
        if t.valley_vwc is None or vwc < t.valley_vwc:
            t.valley_ts, t.valley_vwc, t.valley_ec = now, vwc, ec

        # Rebound check: have we risen far enough from the valley to call the
        # episode done?
        if t.valley_vwc is not None and vwc - t.valley_vwc >= self.dryback_min_drop_pct:
            if t.peak_ts and t.valley_ts:
                duration_min = (t.valley_ts - t.peak_ts).total_seconds() / 60.0
                drop_pct = (t.peak_vwc or 0.0) - t.valley_vwc
                if duration_min >= self.dryback_min_duration_min and drop_pct >= self.dryback_min_drop_pct:
                    self._emit_dryback_episode(zone, t)
            # Reset and start a new peak candidate at the current sample.
            t.peak_ts, t.peak_vwc, t.peak_ec = now, vwc, ec
            t.valley_ts, t.valley_vwc, t.valley_ec = None, None, None

    def _emit_dryback_episode(self, zone: int, t: DrybackTracker) -> None:
        peak_vwc = t.peak_vwc or 0.0
        valley_vwc = t.valley_vwc or 0.0
        duration_min = ((t.valley_ts or datetime.utcnow()) - (t.peak_ts or datetime.utcnow())).total_seconds() / 60.0
        drop_pct = peak_vwc - valley_vwc
        slope = (drop_pct / duration_min * 60.0) if duration_min > 0 else 0.0
        phase = self.get_state("select.crop_steering_irrigation_phase") or "unknown"
        payload = {
            "zone": zone,
            "peak_ts": (t.peak_ts or datetime.utcnow()).isoformat(),
            "valley_ts": (t.valley_ts or datetime.utcnow()).isoformat(),
            "peak_vwc": round(peak_vwc, 2),
            "valley_vwc": round(valley_vwc, 2),
            "pct": round(drop_pct, 2),
            "duration_min": round(duration_min, 1),
            "slope_pct_h": round(slope, 3),
            "phase": phase,
            "ec_at_peak": t.peak_ec,
            "ec_at_valley": t.valley_ec,
        }
        self.store.record_dryback_episode(**payload)
        self.bus.publish("dryback.complete", payload)
        self.fire_event("crop_steering_dryback_complete", **payload)
        self.log(
            "Zone %s dryback complete: %.1f%% drop over %.1fmin (%.2f%%/h) phase=%s",
            zone, drop_pct, duration_min, slope, phase,
        )

    # ------------------------------------------------------------------ derived sensors

    def _publish_dryback_velocity(self, zone: int) -> None:
        """Expose recent dryback velocity (%/h) as a sensor.

        Computed from the last hour of the VWC buffer: slope of a simple
        linear fit between (oldest, current) within the buffer window. We
        intentionally keep this naive — the real episode boundaries come
        from `_step_dryback_tracker` above; this sensor is a smoothed
        live-rate indicator for dashboards and the OptimisationLoop reward.
        """
        buf = list(self._vwc_buf[zone])
        if len(buf) < 5:
            return
        cutoff = datetime.utcnow() - timedelta(hours=1)
        recent = [(ts, v) for ts, v in buf if ts >= cutoff]
        if len(recent) < 5:
            return
        first_ts, first_v = recent[0]
        last_ts, last_v = recent[-1]
        delta_h = (last_ts - first_ts).total_seconds() / 3600.0
        if delta_h <= 0:
            return
        slope_pct_per_hr = (last_v - first_v) / delta_h  # negative = drying
        self.set_state(
            f"sensor.crop_steering_zone_{zone}_dryback_velocity_pct_per_hr",
            state=round(-slope_pct_per_hr, 3),  # report as positive when drying
            attributes={
                "sample_count": len(recent),
                "window_hours": 1,
                "raw_slope_pct_per_hr": round(slope_pct_per_hr, 3),
                "unit_of_measurement": "%/h",
                "friendly_name": f"Zone {zone} dryback velocity",
                "icon": "mdi:speedometer-slow",
                "state_class": "measurement",
            },
        )

    def _publish_porosity_estimate(self, zone: int) -> None:
        """ΔVWC per mL applied across the last 24h of stored shots.

        A higher value means a small shot moves VWC further — a proxy for
        substrate porosity / effective volume. Used by ShotPlanner in
        Phase 2.
        """
        recent_shots = self.store.recent_shots(zone, hours=24)
        usable = [
            s for s in recent_shots
            if s.get("volume_ml") and s.get("vwc_before") is not None and s.get("vwc_peak") is not None
        ]
        if not usable:
            return
        ratios = []
        for s in usable:
            vol = float(s["volume_ml"])
            delta = float(s["vwc_peak"]) - float(s["vwc_before"])
            if vol > 0 and delta > 0:
                ratios.append(delta / vol)  # %VWC per mL
        if not ratios:
            return
        ratios.sort()
        median = ratios[len(ratios) // 2]
        self.set_state(
            f"sensor.crop_steering_zone_{zone}_substrate_porosity_estimate_ml_per_pct",
            state=round(1.0 / median if median > 0 else 0.0, 2),
            attributes={
                "sample_count": len(ratios),
                "median_pct_vwc_per_ml": round(median, 4),
                "window_hours": 24,
                "unit_of_measurement": "mL/%VWC",
                "friendly_name": f"Zone {zone} substrate porosity",
                "icon": "mdi:dots-grid",
                "state_class": "measurement",
            },
        )

    def _publish_ec_stack_index(self, zone: int) -> None:
        """Cumulative EC drift index over the last 6 hours.

        Sum of (EC[t] - EC[t-1]) clipped to positive values, integrated across
        the buffer window. A monotonically rising EC stack indicates salt
        accumulation — the OptimisationLoop and AnomalyScanner both watch
        this for flush triggers.
        """
        buf = list(self._ec_buf[zone])
        if len(buf) < 5:
            return
        cutoff = datetime.utcnow() - timedelta(hours=6)
        recent = [(ts, v) for ts, v in buf if ts >= cutoff]
        if len(recent) < 5:
            return
        stack = 0.0
        for (_, prev), (_, curr) in zip(recent, recent[1:]):
            delta = curr - prev
            if delta > 0:
                stack += delta
        self.set_state(
            f"sensor.crop_steering_zone_{zone}_ec_stack_index",
            state=round(stack, 3),
            attributes={
                "sample_count": len(recent),
                "window_hours": 6,
                "unit_of_measurement": "mS/cm",
                "friendly_name": f"Zone {zone} EC stack index",
                "icon": "mdi:layers-triple-outline",
                "state_class": "measurement",
            },
        )

    # ------------------------------------------------------------------ helpers

    def _read_zone_vwc(self, zone: int) -> float | None:
        return self._read_float(f"sensor.crop_steering_zone_{zone}_avg_vwc")

    def _peak_vwc_in_buffer_since(self, zone: int, since: datetime) -> float | None:
        buf = self._vwc_buf[zone]
        candidates = [v for ts, v in buf if ts >= since]
        if candidates:
            return max(candidates)
        return self._read_zone_vwc(zone)

    def _read_zone_cultivar(self, zone: int) -> str | None:
        return self.get_state(f"select.crop_steering_zone_{zone}_crop_type")  # type: ignore[return-value]

    def _daily_prune(self, _kwargs: Any) -> None:
        try:
            self.store.prune()
        except Exception:  # noqa: BLE001
            self.log("Daily prune failed", level="ERROR")
