"""Two-point calibrations of a room's feed-water pH and EC probes, the one applied, and when each is due.

The grower puts the probe in two reference solutions and records what it read in each. From those
two points this works out the probe's slope (100 % reads every step true) and its offset at the
anchor (pH 7, or EC 0), and whether the probe passes, is drifting or fails. Stored per room in a
store of its own; a room without one simply has no history yet. Reading is open to any signed-in
user; recording, and every wizard step that changes something, needs an administrator.

`calibration_record` only judges the probe: its record is never applied. The wizard (G2:
calibration_start, _capture, _status, _commit, _revert, _abandon) watches the raw probe while the
probe stands in each solution, captures a point only once the reading has held still for 30 s, and
on commit APPLIES a pass or drifting result: the room's sensor.crop_steering_<px>feed_ph_corrected /
feed_ec_corrected then read `correct(raw)`, and the engine_config descriptor carries the same
correction as `feed_calibration` (gain, bias) for the controller. A fail is kept, never applied. The
raw sensors are never touched, and nothing here switches any hardware: while a session is open the
dosing descriptor carries `calibrating`, and the controller holds batches and pH correction on it.

Sessions live in memory and end 30 min after their last capture (a status read does not count).

The same store holds each moisture probe's own offset and curve (G9, `probe_user_offsets`
{entity_id: {offset, curve, at, by}}, absent = none; see probe_offsets.py). `probe_offset_set` changes
one of them, checked and read back, with `preview` showing the effect and writing nothing. The zone
sensor applies them before it fuses its probes; a probe with one also gets sensor.<probe>_corrected.
A record made from this release on is due 30 days after it (`due_days`): the room's
binary_sensor.crop_steering_<px>calibration_due and a Repairs card (CS-612) say so. A record from
before has no `due_days` and never goes due (ruling R6).
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
import math
from uuid import uuid4

from .admin import async_require_admin
from .api_v2 import StaleRevision, Unavailable
from .const import DOMAIN, REPAIRS_DOCS_URL
from .calculations import fuse_probes
from .const import PROBE_FAR, PROBE_RANGE, PROBE_STALE_SECONDS
from .generated.ids import new_id
from .health import _iid
from .journal_api import attribution, note
from .probe_offsets import CURVES, CURVE_WARNING, OFFSET_LIMIT, is_permittivity, read
from .room import room_prefix
from .units import accepted, normalise

_LOGGER = logging.getLogger(__name__)

SERVICES = (
    "calibration_get",
    "calibration_record",
    "calibration_start",
    "calibration_capture",
    "calibration_status",
    "calibration_commit",
    "calibration_revert",
    "calibration_abandon",
    "probe_offset_set",
)
# Open to any signed-in user; every other service needs an administrator.
READS = ("calibration_get", "calibration_status")
HISTORY = 100
# probe -> (kind, the room setting that names its sensor)
PROBES = {"feed_ph": ("ph", "feed_ph_sensor"), "feed_ec": ("ec", "feed_ec_sensor")}
# kind -> readable range, smallest gap between the two references, anchor, offset pass / drifting
KINDS = {
    "ph": {"range": (0.0, 14.0), "spread": 1.0, "anchor": 7.0, "offset": (0.1, 0.3)},
    "ec": {"range": (0.0, 20.0), "spread": 0.5, "anchor": 0.0, "offset": (0.1, 0.3)},
}
SLOPE_PASS, SLOPE_DRIFTING = (95.0, 105.0), (90.0, 110.0)
NAMES = {"ph": "pH", "ec": "EC"}
SOLUTIONS = {"ph": (7.0, 4.0), "ec": (1.413, 2.77)}
WINDOW_S = 30
SESSION_IDLE = timedelta(minutes=30)
SILENT = timedelta(seconds=120)
DUE_DAYS = 30
EXPIRED = "Calibration session expired. Start again."
SIGNAL = f"{DOMAIN}_calibration_changed"
ISSUE = "calibration_due"
OFFSETS_ISSUE = "probe_offsets_unreadable"
CURVE_NEEDS_PERMITTIVITY = (
    "A curve applies only to a probe that reports permittivity (unit \u03b5, permittivity or "
    "dielectric). This probe reports {unit}."
)
CURVE_ON_PERCENT = (
    "This probe already converts to moisture. A curve only applies to raw readings."
)


def _number(value, low, high, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"{label} must be a number from {low:g} to {high:g}")
    return float(value)


def evaluate(kind, points):
    """PURE. The slope (%), the offset at the anchor and the verdict from two points, each the
    reference solution's value and what the probe read in it."""
    spec = KINDS[kind]
    if not isinstance(points, list) or len(points) != 2:
        raise ValueError("A two-point calibration needs exactly two points")
    clean = []
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("Invalid calibration point")
        clean.append(
            {
                "reference": _number(
                    point.get("reference"), *spec["range"], "Reference"
                ),
                "reading": _number(point.get("reading"), *spec["range"], "Reading"),
            }
        )
    (ref1, read1), (ref2, read2) = ((p["reference"], p["reading"]) for p in clean)
    if abs(ref2 - ref1) < spec["spread"]:
        raise ValueError(
            f"The two reference solutions must be at least {spec['spread']:g} apart"
        )
    slope = (read2 - read1) / (ref2 - ref1)
    slope_pct = round(slope * 100, 1)
    offset = round(read1 + slope * (spec["anchor"] - ref1) - spec["anchor"], 3)
    good, drifting = spec["offset"]
    if SLOPE_PASS[0] <= slope_pct <= SLOPE_PASS[1] and abs(offset) <= good:
        verdict = "pass"
    elif (
        SLOPE_DRIFTING[0] <= slope_pct <= SLOPE_DRIFTING[1] and abs(offset) <= drifting
    ):
        verdict = "drifting"
    else:
        verdict = "fail"
    return {
        "points": clean,
        "slope_pct": slope_pct,
        "offset": offset,
        "verdict": verdict,
    }


def correct(raw: float, slope_pct: float, offset: float, anchor: float) -> float:
    """PURE. What a probe with this slope and offset reads as `raw`, corrected."""
    return anchor + (raw - anchor - offset) / (slope_pct / 100)


def gain_bias(slope_pct: float, offset: float, anchor: float) -> tuple[float, float]:
    """PURE. The same correction as `raw * gain + bias` (engine_config `feed_calibration`)."""
    gain = 100 / slope_pct
    return gain, anchor - (anchor + offset) * gain


def _steady(kind, values) -> bool:
    """pH moved less than 0.02; EC less than 1 % of its mean (a reading that did not move at all is steady)."""
    span = max(values) - min(values)
    limit = 0.02 if kind == "ph" else 0.01 * abs(sum(values) / len(values))
    return span < limit or span == 0


def stable(
    samples: list[tuple[float, float]], kind: str, window_s: int = WINDOW_S
) -> tuple[bool, float]:
    """PURE. Whether the reading held still over the last `window_s` seconds, and how far it moved in
    them. `samples`: (epoch s, value), oldest first, the last one the reading now. A probe reports a
    change, not a still value, so the reading before the window counts from the window's start. Not
    steady until the samples reach back a whole window."""
    if not samples:
        return False, 0.0
    start = samples[-1][0] - window_s
    held = [v for t, v in samples if t <= start][-1:]
    values = held + [v for t, v in samples if t > start]
    return bool(held) and _steady(kind, values), max(values) - min(values)


def steady_for(samples: list[tuple[float, float]], kind: str) -> float:
    """PURE. How many seconds back from the last sample the reading has stayed steady."""
    if not samples:
        return 0.0
    end = since = samples[-1][0]
    values = []
    for t, value in reversed(samples):
        values.append(value)
        if not _steady(kind, values):
            break
        since = t
    return end - since


def _stored_offsets(value) -> dict:
    """The stored `probe_user_offsets` (absent = none), or ValueError: a value that is not understood
    is never loaded half way and then saved over."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Invalid stored probe offsets")
    for entity_id, entry in value.items():
        if not isinstance(entity_id, str) or not isinstance(entry, dict):
            raise ValueError("Invalid stored probe offsets")
        _number(entry.get("offset", 0.0), -OFFSET_LIMIT, OFFSET_LIMIT, "Offset")
        if entry.get("curve") is not None and entry["curve"] not in CURVES:
            raise ValueError("Invalid stored probe offsets")
    return deepcopy(value)


def _trim(records) -> list:
    """The newest HISTORY records, and any applied one older than those (a correction in force is never
    dropped by the history limit)."""
    return [*records[:HISTORY], *(r for r in records[HISTORY:] if r.get("applied"))]


def event_data(record, **extra) -> dict:
    """The data of a calibration event: one shape for a check, whichever path recorded it."""
    return {
        "applied": bool(record.get("applied", False)),
        "record_id": record.get("id"),
        "probe": record.get("probe"),
        "kind": record.get("kind"),
        "entity_id": record.get("entity_id"),
        "slope_pct": record.get("slope_pct"),
        "offset": record.get("offset"),
        "verdict": record.get("verdict"),
        "points": record.get("points"),
        "note": record.get("note", ""),
        **extra,
    }


def _utcnow():
    return datetime.now(timezone.utc)


def _track(hass, entity_id, on_reading):
    """Call on_reading(state, last_changed) on each state change of `entity_id`. -> unsubscribe."""
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event

    @callback
    def changed(event):
        new = event.data.get("new_state")
        if new is not None:
            on_reading(new.state, new.last_changed)

    return async_track_state_change_event(hass, [entity_id], changed)


def _later(hass, seconds, action):
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_call_later

    @callback
    def fire(now):
        action(now)

    return async_call_later(hass, seconds, fire)


def _send(hass, signal):
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    async_dispatcher_send(hass, signal)


def _number_or_none(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class CalibrationStore:
    def __init__(self, hass, entry, store=None, now=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        slug = (getattr(entry, "data", None) or {}).get("room_slug", "default")
        self.issue_id = _iid(ISSUE, slug)
        self.offsets_issue_id = _iid(OFFSETS_ISSUE, slug)
        self.due_sensor = f"binary_sensor.{DOMAIN}_{self.prefix}calibration_due"
        self._store = store
        self._now = now or _utcnow
        self._lock = asyncio.Lock()
        self._timer = None
        self.document = {"revision": 0, "records": [], "probe_user_offsets": {}}
        self._corrected = {}  # probe entity_id -> unsubscribe of its raw sensor
        self.sessions = {}
        self.error = None
        # The probe offsets section is judged on its own: when it cannot be read the feed calibration
        # stays applied, and when the records cannot be read the offsets still apply.
        self.offsets_error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.calibration.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                if not isinstance(value, dict):
                    raise ValueError("Invalid stored calibration history")
                try:
                    if (
                        type(value.get("revision")) is not int
                        or value["revision"] < 0
                        or not isinstance(value.get("records"), list)
                    ):
                        raise ValueError("Invalid stored calibration history")
                    self.document["revision"] = value["revision"]
                    self.document["records"] = _trim(value["records"])
                except Exception as error:
                    self.error = f"Stored calibration history could not be loaded; it has not been overwritten: {error}"
                try:
                    self.document["probe_user_offsets"] = _stored_offsets(
                        value.get("probe_user_offsets")
                    )
                except Exception as error:
                    # Kept as stored, so a save of the records carries it through untouched.
                    self.document["probe_user_offsets"] = deepcopy(
                        value.get("probe_user_offsets")
                    )
                    self._offsets_unreadable(error)
        except Exception as error:
            self.error = f"Stored calibration history could not be loaded; it has not been overwritten: {error}"
            self._offsets_unreadable(error)

    def _offsets_unreadable(self, error):
        self.offsets_error = (
            "The stored probe offsets could not be read; they have not been overwritten "
            f"and the probes read without them: {error}"
        )
        _LOGGER.error("%s: %s", self.room_id, self.offsets_error)

    # ------------------------------------------------------------------ reading
    def _descriptor(self) -> dict:
        state = self.hass.states.get(f"sensor.{DOMAIN}_{self.prefix}engine_config")
        return dict(state.attributes) if state else {}

    def sensors(self):
        """Each feed probe's sensor as the room's setup names it now, or None."""
        attributes = self._descriptor()
        return {
            probe: attributes.get(key) or None for probe, (_kind, key) in PROBES.items()
        }

    def _reading(self, entity_id):
        """(value, when it last reported), or (None, None) when the sensor has no number."""
        state = self.hass.states.get(entity_id) if entity_id else None
        value = _number_or_none(getattr(state, "state", None))
        if value is None:
            return None, None
        return value, getattr(state, "last_reported", None) or getattr(
            state, "last_updated", None
        )

    def response(self):
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            **deepcopy(self.document),
            "sensors": self.sensors(),
            "error": self.error,
            "offsets_error": self.offsets_error,
            "max_records": HISTORY,
        }

    def applied(self, probe):
        """The probe's applied record, or None. A calibration of another sensor than the one the room's
        setup names now is not applied to it."""
        source = self.sensors()[probe]
        return next(
            (
                r
                for r in self.document["records"]
                if r.get("probe") == probe
                and r.get("applied")
                and r.get("entity_id") == source
            ),
            None,
        )

    def feed_calibration(self) -> dict:
        """engine_config `feed_calibration`: {kind: {gain, bias, calibrated_at}}, applied ones only."""
        out = {}
        for probe, (kind, _key) in PROBES.items():
            record = self.applied(probe)
            if record is not None:
                gain, bias = gain_bias(
                    record["slope_pct"], record["offset"], KINDS[kind]["anchor"]
                )
                out[kind] = {
                    "gain": gain,
                    "bias": bias,
                    "calibrated_at": record["at"],
                }
        return out

    def corrected(self, probe):
        """sensor.crop_steering_<px><probe>_corrected as (value, attributes): the raw reading corrected
        by the applied calibration, or None when none is applied or the raw sensor has no number.
        """
        kind = PROBES[probe][0]
        source = self.sensors()[probe]
        record = self.applied(probe)
        attributes = {
            "source": source,
            "applied": record is not None,
            "slope_pct": None,
            "offset": None,
            "gain": None,
            "bias": None,
            "calibrated_at": None,
        }
        if record is None:
            return None, attributes
        anchor = KINDS[kind]["anchor"]
        gain, bias = gain_bias(record["slope_pct"], record["offset"], anchor)
        attributes.update(
            slope_pct=record["slope_pct"],
            offset=record["offset"],
            gain=gain,
            bias=bias,
            calibrated_at=record["at"],
        )
        raw, _ = self._reading(source)
        if raw is None:
            return None, attributes
        return (
            round(correct(raw, record["slope_pct"], record["offset"], anchor), 3),
            attributes,
        )

    # ------------------------------------------------------------------ probe offsets and curves (G9)
    def user_corrections(self) -> dict:
        """{probe entity_id: (offset, curve)} for the zone sensors to apply; none while the store is
        unreadable (a probe then reads as it did before, and says so: see `affected_probes`).
        """
        if self.offsets_error:
            return {}
        return {
            entity_id: (float(entry.get("offset", 0.0)), entry.get("curve"))
            for entity_id, entry in self.document["probe_user_offsets"].items()
        }

    def affected_probes(self) -> set:
        """The room's moisture probes that read without their offsets because the stored offsets cannot be
        read: the ones the stored section names, or every moisture probe when it names none it can.
        """
        if not self.offsets_error:
            return set()
        room = set(self._vwc_zones())
        stored = self.document["probe_user_offsets"]
        named = room & set(stored) if isinstance(stored, dict) else set()
        return named or room

    def publish_offsets_issue(self):
        """The loud side of an unreadable offsets section: a Repairs card naming the probes that now read
        without their offsets. Cleared when the section reads again."""
        from homeassistant.helpers import issue_registry as ir

        if not self.offsets_error:
            ir.async_delete_issue(self.hass, DOMAIN, self.offsets_issue_id)
            return
        probes = sorted(self.affected_probes())
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.offsets_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=OFFSETS_ISSUE,
            translation_placeholders={
                "room": self.room_id,
                "probes": "\n".join(f"- {probe}" for probe in probes)
                or "- (the room's moisture probes)",
            },
            learn_more_url=REPAIRS_DOCS_URL,
        )

    def _zones(self) -> dict:
        """The room's zones as its setup holds them (zone number as a string, or an int)."""
        data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id) or {}
        return data.get("zones") or {}

    @staticmethod
    def _zone_probes(zone) -> list:
        sensors = list(zone.get("vwc_sensors") or [])
        if not sensors:
            sensors = [zone[k] for k in ("vwc_front", "vwc_back") if zone.get(k)]
        return sensors

    def _vwc_zones(self) -> dict:
        """{probe entity_id: zone key} for every moisture probe the room's zones name (the first zone
        that names it)."""
        out = {}
        for key, zone in self._zones().items():
            for entity_id in self._zone_probes(zone):
                out.setdefault(entity_id, key)
        return out

    def _raw(self, entity_id):
        """(the probe's number or None, its unit)."""
        state = self.hass.states.get(entity_id)
        unit = (getattr(state, "attributes", None) or {}).get("unit_of_measurement")
        return _number_or_none(getattr(state, "state", None)), unit

    def corrected_value(self, entity_id, fix):
        """(the probe's reading before its offset and curve, with them) under `fix` = (offset, curve), or
        (None, None) while the probe has no usable number."""
        raw, unit = self._raw(entity_id)
        if raw is None:
            return None, None
        base, value, _aside = read(raw, unit, fix[0], fix[1], entity_id)
        return base, value

    @staticmethod
    def _corrected_id(entity_id) -> str:
        return f"sensor.{entity_id.split('.', 1)[-1]}_corrected"

    def _publish_corrected(self, entity_id):
        """sensor.<probe>_corrected: the probe's reading under its offset and curve. It follows the raw
        sensor and is unavailable while the raw sensor is: nothing old is ever shown in its place.
        """
        entry = self.document["probe_user_offsets"].get(entity_id)
        if entry is None or self.offsets_error:
            self.hass.states.async_remove(self._corrected_id(entity_id))
            return
        fix = (float(entry.get("offset", 0.0)), entry.get("curve"))
        base, value = self.corrected_value(entity_id, fix)
        raw_state = self.hass.states.get(entity_id)
        self.hass.states.async_set(
            self._corrected_id(entity_id),
            "unavailable" if value is None else str(round(value, 3)),
            {
                "friendly_name": f"{entity_id.split('.', 1)[-1]} corrected",
                "unit_of_measurement": "%",
                "room_id": self.room_id,
                "source": entity_id,
                "raw": base,
                "offset": fix[0],
                "curve": fix[1],
                "set_at": entry.get("at"),
                "restored": bool(
                    (getattr(raw_state, "attributes", None) or {}).get("restored")
                ),
            },
        )

    def sync_corrected(self):
        """Publish a corrected sensor for each probe with an offset or curve and none for the rest."""
        wanted = (
            set() if self.offsets_error else set(self.document["probe_user_offsets"])
        )
        for entity_id in [e for e in self._corrected if e not in wanted]:
            self._corrected.pop(entity_id)()
            self.hass.states.async_remove(self._corrected_id(entity_id))
        for entity_id in wanted:
            if entity_id not in self._corrected:
                self._corrected[entity_id] = _track(
                    self.hass,
                    entity_id,
                    lambda _text, _at, e=entity_id: self._publish_corrected(e),
                )
            self._publish_corrected(entity_id)

    def _fused(self, entity_id, fix):
        """What the probe's zone would read with `fix` on this probe and every other probe as it is now,
        or None, and why each probe it leaves out is left out. An estimate: it mirrors the zone
        sensor's fusion without its learned memory of the probes.
        """
        key = self._vwc_zones().get(entity_id)
        zone = self._zones().get(key) or {}
        sensors = self._zone_probes(zone)
        unused = set(zone.get("vwc_unused") or ()) & set(sensors)
        if unused == set(sensors):
            unused = set()
        fixes = {**self.user_corrections(), entity_id: fix}
        readings = []
        for probe in sensors:
            if probe in unused:
                continue
            offset, curve = fixes.get(probe, (0.0, None))
            raw, unit = self._raw(probe)
            value = age = None
            if raw is not None:
                _base, value, _aside = read(raw, unit, offset, curve, probe)
                state = self.hass.states.get(probe)
                stamp = getattr(state, "last_reported", None) or getattr(
                    state, "last_updated", None
                )
                if stamp is not None:
                    age = (self._now() - stamp).total_seconds()
            readings.append((probe, value, age))
        method = self.hass.states.get(
            f"select.{DOMAIN}_{self.prefix}zone_{key}_vwc_method"
        )
        value, detail = fuse_probes(
            readings,
            {},
            *PROBE_RANGE["vwc"],
            PROBE_STALE_SECONDS,
            method.state if method is not None else "Median",
            PROBE_FAR["vwc"],
        )
        return value, dict(detail["excluded"])

    async def probe_offset_set(self, data, who=None) -> dict:
        """Set one moisture probe's offset and/or curve, or (match_handheld) the offset that makes it read
        what a handheld meter reads. `preview` answers with the effect and saves, publishes and journals
        nothing. A write is checked against the revision, bounded, saved, read back and journaled.
        """
        entity_id = data.get("entity_id")
        preview = bool(data.get("preview"))
        if self.error or self.offsets_error:
            raise Unavailable(self.error or self.offsets_error)
        if entity_id not in self._vwc_zones():
            raise ValueError("That is not a moisture probe of this room")
        if not any(k in data for k in ("offset", "curve", "match_handheld")):
            raise ValueError("Give an offset, a curve or a handheld reading to match")
        if "match_handheld" in data and "offset" in data:
            raise ValueError("Give an offset or a handheld reading to match, not both")
        async with self._lock:
            if self.error or self.offsets_error:
                raise Unavailable(self.error or self.offsets_error)
            if (
                not preview
                and data.get("expected_revision") != self.document["revision"]
            ):
                raise StaleRevision(
                    "Calibration history changed elsewhere. Reload before saving.",
                    self.document["revision"],
                )
            section = self.document["probe_user_offsets"]
            old_entry = section.get(entity_id) or {}
            old_fix = (float(old_entry.get("offset", 0.0)), old_entry.get("curve"))
            offset, curve = old_fix
            if "curve" in data:
                curve = data["curve"]
                if curve in (None, "none"):
                    curve = None
                elif curve not in CURVES:
                    raise ValueError(
                        "The curve must be one of: " + ", ".join(sorted(CURVES))
                    )
            if curve is not None:
                unit = self._raw(entity_id)[1]
                if normalise(unit) in accepted("vwc"):
                    raise ValueError(CURVE_ON_PERCENT)
                if not is_permittivity(unit):
                    raise ValueError(
                        CURVE_NEEDS_PERMITTIVITY.format(
                            unit=repr(unit) if unit else "no unit"
                        )
                    )
            if "offset" in data:
                offset = _number(data["offset"], -OFFSET_LIMIT, OFFSET_LIMIT, "Offset")
            if "match_handheld" in data:
                handheld = _number(
                    data["match_handheld"], *PROBE_RANGE["vwc"], "Handheld"
                )
                raw, unit = self._raw(entity_id)
                bare = None
                if raw is not None:
                    _base, bare, _aside = read(raw, unit, 0.0, curve, entity_id)
                if bare is None:
                    raise ValueError("The probe has no reading to match")
                offset = round(handheld - bare, 3)
                if abs(offset) > OFFSET_LIMIT:
                    raise ValueError(
                        f"The probe reads {bare:g} and the handheld {handheld:g}: "
                        f"{abs(offset):g} apart, more than the {OFFSET_LIMIT:g} an offset may be"
                    )
            fix = (offset, curve)
            _base, corrected = self.corrected_value(entity_id, fix)
            low, high = PROBE_RANGE["vwc"]
            if corrected is not None and not low <= corrected <= high:
                raise ValueError(
                    f"The probe would read {corrected:g}, outside {low:g} to {high:g}"
                )
            new_section = deepcopy(section)
            if offset == 0.0 and curve is None:
                new_section.pop(entity_id, None)
            else:
                new_section[entity_id] = {
                    "offset": offset,
                    "curve": curve,
                    "at": self._now().isoformat(),
                    "by": (who or {}).get("user_id") or (who or {}).get("actor"),
                }
            from .setup_api import setup_diff

            diff = setup_diff(section, new_section)
            fused_before, _was = self._fused(entity_id, old_fix)
            fused_after, excluded = self._fused(entity_id, fix)
            out = {
                "offset": offset,
                "curve": curve,
                "corrected_now": None if corrected is None else round(corrected, 3),
                "fused_before": fused_before,
                "fused_after": fused_after,
                "excluded_after": excluded,
            }
            if curve is not None:
                out["warning"] = CURVE_WARNING
            if preview:
                return {**out, "preview": True, "diff": diff}
            document = {
                **self.document,
                "revision": self.document["revision"] + 1,
                "probe_user_offsets": new_section,
            }
            await self._store.async_save(deepcopy(document))
            stored = await self._store.async_load()
            if ((stored or {}).get("probe_user_offsets") or {}).get(
                entity_id
            ) != new_section.get(entity_id):
                try:  # put back what was there, so the store and the room agree again
                    await self._store.async_save(deepcopy(self.document))
                except Exception as error:
                    _LOGGER.error("Probe offsets could not be put back: %s", error)
                raise ValueError(
                    "The probe offset did not read back from storage. It was not applied."
                )
            self.document = document
        self.sync_corrected()
        _send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")
        self._journal(
            "config.changed",
            who,
            {
                "store": "calibration",
                "section": "probe_user_offsets",
                "old": deepcopy(section),
                "new": deepcopy(new_section),
                "diff": diff,
            },
        )
        return {**out, "revision": document["revision"]}

    def due(self) -> dict:
        """{probe: due date} for each probe whose newest record that did not fail is past its due date (a
        failed calibration does not reset the clock). A record without `due_days` (from before this
        release) never goes due (ruling R6)."""
        out, now = {}, self._now()
        for probe in PROBES:
            latest = next(
                (
                    r
                    for r in self.document["records"]
                    if r.get("probe") == probe and r.get("verdict") != "fail"
                ),
                None,
            )
            try:
                days = latest["due_days"]
                at = datetime.fromisoformat(latest["at"])
                due_at = at + timedelta(days=days)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if now >= due_at:
                out[probe] = due_at.isoformat()
        return out

    def publish_due(self):
        """binary_sensor.crop_steering_<px>calibration_due and the room's CS-612 Repairs card."""
        from homeassistant.helpers import issue_registry as ir

        due = {} if self.error else self.due()
        self.hass.states.async_set(
            self.due_sensor,
            "unavailable" if self.error else ("on" if due else "off"),
            {
                "friendly_name": "Feed probe calibration due",
                "room_id": self.room_id,
                "probes": sorted(due),
                "due_at": due,
            },
        )
        if not due:
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE,
            translation_placeholders={
                "probes": "\n".join(
                    f"- The feed {NAMES[PROBES[probe][0]]} probe: due since {at[:10]}"
                    for probe, at in sorted(due.items())
                ),
            },
            learn_more_url=REPAIRS_DOCS_URL,
        )

    def listen(self):
        """Publish the due flag now and every hour (a record goes due by the clock alone). -> unsubscribe."""
        from homeassistant.core import callback
        from homeassistant.helpers.event import async_track_time_interval

        @callback
        def hourly(_now):
            self.publish_due()

        self.publish_due()
        self.publish_offsets_issue()
        self.sync_corrected()
        return async_track_time_interval(self.hass, hourly, timedelta(hours=1))

    def calibrating(self):
        """The dosing descriptor's `calibrating` while a session is open, else None: a probe session
        ({probe, session_id, until}) or a pump's calibration ({pump, session_id, until}). Either holds the
        room's dosing."""
        now = self._now()
        for session in self.sessions.values():
            until = session["active"] + SESSION_IDLE
            if now < until:
                kind = "pump" if "pump" in session else "probe"
                return {
                    kind: session[kind],
                    "session_id": session["id"],
                    "until": until.isoformat(),
                }
        return None

    def probe_open(self) -> bool:
        """Whether a feed probe session is open (a pump's own calibration is not one)."""
        self.expire()
        return any("probe" in session for session in self.sessions.values())

    def pump_holding(self) -> dict | None:
        """The open pump calibration session as {pump, session_id, until}, or None."""
        self.expire()
        for session in self.sessions.values():
            if "pump" in session:
                return {
                    "pump": session["pump"],
                    "session_id": session["id"],
                    "until": (session["active"] + SESSION_IDLE).isoformat(),
                }
        return None

    # ------------------------------------------------------------------ sessions
    def _changed(self):
        """The applied calibrations may have changed: the corrected sensors and engine_config follow."""
        _send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")
        self.publish_due()

    def _dosing_changed(self):
        from .dosing_api import SIGNAL as DOSING_SIGNAL

        _send(self.hass, f"{DOSING_SIGNAL}_{self.entry.entry_id}")

    def _close(self, session_id=None) -> bool:
        """End one session (or every one); the dosing descriptor drops `calibrating`."""
        ids = list(self.sessions) if session_id is None else [session_id]
        closed = False
        for sid in ids:
            session = self.sessions.pop(sid, None)
            if session is not None:
                closed = True
                if session["unsub"]:
                    session["unsub"]()
        if closed:
            if not self.sessions and self._timer:
                self._timer()
                self._timer = None
            self._dosing_changed()
        return closed

    def expire(self, _now=None):
        """End every session idle for 30 min."""
        now = self._now()
        for sid in [
            sid for sid, s in self.sessions.items() if now >= s["active"] + SESSION_IDLE
        ]:
            self._close(sid)

    def _touch(self, session):
        """Activity: the 30 min start again, and the dosing descriptor's `calibrating.until` with them."""
        session["active"] = self._now()
        if self._timer:
            self._timer()
        self._timer = _later(self.hass, SESSION_IDLE.total_seconds() + 1, self.expire)
        self._dosing_changed()

    def session(self, session_id, pump=False):
        """An open probe session (or, with `pump`, a pump's calibration session), else EXPIRED."""
        self.expire()
        session = self.sessions.get(session_id)
        if session is None or ("pump" in session) != pump:
            raise ValueError(EXPIRED)
        return session

    def _close_kind(self, pump: bool):
        """End every probe session, or every pump session: one of each kind per room."""
        for sid in [sid for sid, s in self.sessions.items() if ("pump" in s) == pump]:
            self._close(sid)

    # ------------------------------------------------------------------ pump sessions (G3)
    # A pump's calibration is the same session with one point: pump_calibrate opens it with the request it
    # leaves for the controller, the controller's report of that request gives the seconds the pump ran,
    # and pump_calibration_commit (dosing_api.py) turns the mL measured into the pump's flow.
    def pump_open(self, pump, request_id, seconds) -> dict:
        self._close_kind(pump=True)
        now = self._now()
        session = {
            "id": new_id(),
            "pump": pump,
            "request_id": request_id,
            "seconds": seconds,
            "ran_s": None,
            "result": None,
            "at": now,
            "reported_at": None,
            "active": now,
            "unsub": None,
        }
        self.sessions[session["id"]] = session
        self._touch(session)
        return session

    def pump_close(self, session_id=None, request_id=None) -> bool:
        """End a pump's calibration session, by its id or by the request it left."""
        for sid, session in list(self.sessions.items()):
            if "pump" in session and (
                sid == session_id
                or (request_id is not None and session["request_id"] == request_id)
            ):
                return self._close(sid)
        return False

    def pump_reported(self, request_id, ran_s, result) -> bool:
        """The controller reported the run of `request_id`: its seconds and result go into the session
        (once). Restarts the 30 min, so the grower has time to read the jug."""
        for session in self.sessions.values():
            if session.get("request_id") == request_id and session["ran_s"] is None:
                session.update(ran_s=ran_s, result=result, reported_at=self._now())
                self._touch(session)
                return True
        return False

    def pump_view(self, pump) -> dict | None:
        """The open calibration session of `pump`, as dosing_get shows it, or None."""
        self.expire()
        for session in self.sessions.values():
            if session.get("pump") == pump:
                return {
                    "session_id": session["id"],
                    "request_id": session["request_id"],
                    "seconds": session["seconds"],
                    "ran_s": session["ran_s"],
                    "result": session["result"],
                    "expires_at": (session["active"] + SESSION_IDLE).isoformat(),
                }
        return None

    def pump_run(self, pump, since, end) -> bool:
        """Whether a run of `pump` from `since` to `end` overlaps its open calibration: from the request
        until the controller reported it. Such a run went into a measuring jug, not to the tank.
        """
        return any(
            session.get("pump") == pump
            and session["at"] <= end
            and (session["reported_at"] is None or session["reported_at"] >= since)
            for session in self.sessions.values()
        )

    def _silent(self, kind):
        return f"No reading from the feed {NAMES[kind]} probe for 2 min. Check it's plugged in."

    def _observe(self, session, text, at):
        value = _number_or_none(text)
        if (
            value is None
        ):  # unavailable: steady again only after a whole window of readings
            session["samples"] = []
            return
        stamp = (at or self._now()).timestamp()
        keep = stamp - 10 * WINDOW_S
        older = [s for s in session["samples"] if s[0] <= keep][-1:]
        session["samples"] = [
            *older,
            *(s for s in session["samples"] if s[0] > keep),
            (stamp, value),
        ]

    def _measure(self, session) -> dict:
        kind = session["kind"]
        raw, _ = self._reading(session["entity_id"])
        if raw is None:
            return {
                "reading": None,
                "raw": None,
                "stable": False,
                "drift": None,
                "stable_s": 0,
            }
        samples = [*session["samples"], (self._now().timestamp(), raw)]
        steady, drift = stable(samples, kind)
        shown = raw
        record = self.applied(session["probe"])
        if (
            record is not None
        ):  # what the room shows today, under the calibration in force
            shown = round(
                correct(
                    raw, record["slope_pct"], record["offset"], KINDS[kind]["anchor"]
                ),
                3,
            )
        return {
            "reading": shown,
            "raw": raw,
            "stable": steady,
            "drift": round(drift, 4),
            "stable_s": int(steady_for(samples, kind)),
        }

    def _solutions(self, kind, solutions):
        if solutions is None:
            return list(SOLUTIONS[kind])
        spec = KINDS[kind]
        if not isinstance(solutions, list) or len(solutions) != 2:
            raise ValueError("Give exactly two reference solutions")
        refs = [_number(s, *spec["range"], "Reference") for s in solutions]
        if abs(refs[0] - refs[1]) < spec["spread"]:
            raise ValueError(
                f"The two reference solutions must be at least {spec['spread']:g} apart"
            )
        return refs

    async def start(self, probe, solutions=None, who=None) -> dict:
        if self.error:
            raise Unavailable(self.error)
        if probe not in PROBES:
            raise ValueError("Calibrate the feed-water pH or EC probe")
        kind, key = PROBES[probe]
        attributes = self._descriptor()
        entity = attributes.get(key) or None
        if entity is None:
            raise ValueError(f"The room has no feed {NAMES[kind]} probe set up")
        refs = self._solutions(kind, solutions)
        raw, reported = self._reading(entity)
        now = self._now()
        if raw is None or reported is None or now - reported > SILENT:
            raise ValueError(self._silent(kind))
        self._close_kind(
            pump=False
        )  # one session per room: a new start replaces the last
        state = self.hass.states.get(entity)
        since = getattr(state, "last_changed", None) or reported
        session = {
            "id": new_id(),
            "probe": probe,
            "kind": kind,
            "entity_id": entity,
            "temperature_entity_id": attributes.get("tank_temperature_sensor") or None,
            "solutions": refs,
            "points": [None, None],
            "samples": [(since.timestamp(), raw)],
            "active": now,
            "unsub": None,
        }
        self.sessions[session["id"]] = session
        session["unsub"] = _track(
            self.hass,
            entity,
            lambda text, at: self._observe(session, text, at),
        )
        self._touch(session)
        until = (session["active"] + SESSION_IDLE).isoformat()
        self._journal(
            "calibration.started",
            who,
            {
                "session_id": session["id"],
                "probe": probe,
                "kind": kind,
                "entity_id": entity,
                "temperature_entity_id": session["temperature_entity_id"],
                "solutions": refs,
                "until": until,
            },
        )
        return {
            "session_id": session["id"],
            "room_id": self.room_id,
            "probe": probe,
            "kind": kind,
            "solutions": refs,
            "raw_entity_id": entity,
            "temperature_entity_id": session["temperature_entity_id"],
            "dosing_paused": True,
            "expires_at": until,
        }

    async def capture(self, session_id, point, force=False, who=None) -> dict:
        session = self.session(session_id)
        if point not in (0, 1) or isinstance(point, bool):
            raise ValueError("point must be 0 or 1")
        measured = self._measure(session)
        if measured["raw"] is None:
            raise ValueError(self._silent(session["kind"]))
        self._touch(session)
        if not measured["stable"] and not force:
            return measured
        session["points"][point] = {
            "reference": session["solutions"][point],
            "reading": measured["raw"],
            "stable_s": measured["stable_s"],
            "forced": not measured["stable"],
        }
        self._journal(
            "calibration.captured",
            who,
            event_data(
                {
                    "probe": session["probe"],
                    "kind": session["kind"],
                    "entity_id": session["entity_id"],
                    "points": [deepcopy(p) for p in session["points"] if p],
                },
                session_id=session["id"],
                point=point,
                stable=measured["stable"],
                drift=measured["drift"],
            ),
        )
        return measured

    def status(self, session_id) -> dict:
        """Read only: never stores a point and never restarts the 30 min."""
        session = self.session(session_id)
        return {
            **self._measure(session),
            "points_captured": sum(p is not None for p in session["points"]),
            "expires_at": (session["active"] + SESSION_IDLE).isoformat(),
        }

    async def commit(self, session_id, who=None) -> dict:
        session = self.session(session_id)
        if None in session["points"]:
            raise ValueError("Capture both points before applying the calibration")
        who = who or {}
        async with self._lock:
            if (
                session_id not in self.sessions
            ):  # committed (or ended) while this call waited
                raise ValueError(EXPIRED)
            if self.error:
                raise Unavailable(self.error)
            result = evaluate(
                session["kind"],
                [
                    {"reference": p["reference"], "reading": p["reading"]}
                    for p in session["points"]
                ],
            )
            applied = result["verdict"] != "fail"
            record = {
                "id": uuid4().hex,
                "probe": session["probe"],
                "kind": session["kind"],
                "entity_id": session["entity_id"],
                "at": self._now().isoformat(),
                **result,
                "points": [
                    {**clean, "stable_s": p["stable_s"], "forced": p["forced"]}
                    for clean, p in zip(result["points"], session["points"])
                ],
                "note": "",
                "applied": applied,
                "committed_by": who.get("user_id"),
                "due_days": DUE_DAYS,
                "superseded_by": None,
                "session_id": session["id"],
            }
            records = deepcopy(self.document["records"])
            superseded = None
            if applied:
                for old in records:
                    if old.get("probe") == record["probe"] and old.get("applied"):
                        old["applied"], old["superseded_by"] = False, record["id"]
                        superseded = superseded or old.get("id")
            document = {
                **self.document,
                "revision": self.document["revision"] + 1,
                "records": _trim([record, *records]),
            }
            await self._store.async_save(document)
            self.document = document
        self._close(session_id)
        self._changed()
        self._journal(
            "calibration.committed",
            who,
            event_data(
                record, session_id=session["id"], superseded_record_id=superseded
            ),
        )
        if not applied:
            raise ValueError(
                f"The probe failed calibration (response {record['slope_pct']:g} %, offset "
                f"{record['offset']:g}). It is recorded but not applied: clean or replace the "
                "probe and calibrate it again."
            )
        return {
            "record_id": record["id"],
            "revision": document["revision"],
            "slope_pct": record["slope_pct"],
            "offset": record["offset"],
            "verdict": record["verdict"],
            "applied": True,
        }

    async def revert(self, probe, who=None) -> dict:
        """Take the applied calibration off the probe and put back the one it replaced, or none."""
        if probe not in PROBES:
            raise ValueError("Calibrate the feed-water pH or EC probe")
        kind = PROBES[probe][0]
        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            records = deepcopy(self.document["records"])
            current = next(
                (r for r in records if r.get("probe") == probe and r.get("applied")),
                None,
            )
            if current is None:
                raise ValueError(
                    f"No applied calibration of the feed {NAMES[kind]} probe to put back"
                )
            current["applied"] = False
            current["reverted_at"] = self._now().isoformat()
            previous = next(
                (r for r in records if r.get("superseded_by") == current.get("id")),
                None,
            )
            if previous is not None:
                previous["applied"], previous["superseded_by"] = True, None
            document = {
                **self.document,
                "revision": self.document["revision"] + 1,
                "records": records,
            }
            await self._store.async_save(document)
            self.document = document
        self._close_kind(pump=False)
        self._changed()
        out = {
            "probe": probe,
            "revision": document["revision"],
            "reverted_record_id": current.get("id"),
            "record_id": previous.get("id") if previous else None,
            "applied": previous is not None,
        }
        self._journal(
            "calibration.reverted",
            who,
            {"kind": kind, "entity_id": current.get("entity_id"), **out},
        )
        return out

    def abandon(self, session_id) -> dict:
        # A probe session or a pump's calibration session (which releases its hold on the room's
        # dosing early); unknown or expired: refused like every other session step.
        self.expire()
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError(EXPIRED)
        if "pump" in session and session["ran_s"] is None:
            # Its run may still start: the hold stays until pump_stop ends it or it is reported.
            raise ValueError(
                "The pump's calibration run has not been reported yet: stop the pump first"
            )
        return {"abandoned": self._close(session_id)}

    def _journal(self, kind, who, data):
        """Never fails or delays the change."""
        try:
            who = who or {}
            note(
                self.hass,
                self.room_id,
                kind,
                actor=who.get("actor", "system"),
                user_id=who.get("user_id"),
                client=who.get("client"),
                data=data,
            )
        except Exception as err:
            _LOGGER.debug("Calibration journal event not recorded: %s", err)

    async def record(self, data, who=None):
        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            if data.get("expected_revision") != self.document["revision"]:
                raise StaleRevision(
                    "Calibration history changed elsewhere. Reload before saving.",
                    self.document["revision"],
                )
            probe = data.get("probe")
            if probe not in PROBES:
                raise ValueError("Calibrate the feed-water pH or EC probe")
            text = (data.get("note") or "").strip()
            if len(text) > 200:
                raise ValueError("A note holds at most 200 characters")
            kind = PROBES[probe][0]
            record = {
                "id": uuid4().hex,
                "probe": probe,
                "kind": kind,
                "entity_id": self.sensors()[probe],
                "at": self._now().isoformat(),
                **evaluate(kind, data.get("points")),
                "note": text,
                # A check only judges the probe: it is never applied.
                "applied": False,
                "committed_by": (who or {}).get("user_id"),
                "due_days": DUE_DAYS,
                "superseded_by": None,
            }
            document = {
                **self.document,
                "revision": self.document["revision"] + 1,
                "records": _trim([record, *self.document["records"]]),
            }
            await self._store.async_save(document)
            self.document = document
        self.publish_due()
        return self.response()


def journal_record(hass, room_id, response, call):
    """A check was recorded -> `calibration.captured`. It only judges the probe: nothing is applied to it."""
    try:
        record = response["records"][0]
        who = attribution(hass, call)
        note(
            hass,
            room_id,
            "calibration.captured",
            actor=who["actor"],
            user_id=who["user_id"],
            client=who["client"],
            data=event_data(record),
        )
    except Exception as err:  # the record stands whatever the journal does
        _LOGGER.debug("Calibration journal event not recorded: %s", err)


def _managers(hass) -> dict:
    return hass.data.get(DOMAIN, {}).get("_calibration", {})


def resolve_calibration(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager for manager in _managers(hass).values() if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Calibration room is unknown or ambiguous")
    return matches[0]


def resolve_session(hass, session_id):
    """The room that holds an open session, or ValueError(EXPIRED)."""
    for manager in _managers(hass).values():
        manager.expire()
        if session_id in manager.sessions:
            return manager
    raise ValueError(EXPIRED)


async def async_setup_calibration(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .api_v2 import fields, wrap

    manager = CalibrationStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_calibration", {})[
        entry.entry_id
    ] = manager
    unsubscribe = manager.listen()
    if unsubscribe:
        entry.async_on_unload(unsubscribe)

    async def handle(call):
        if call.service not in READS:
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        data = call.data
        try:
            service = call.service
            if service == "calibration_status":
                return resolve_session(hass, data["session_id"]).status(
                    data["session_id"]
                )
            if service in ("calibration_capture", "calibration_commit"):
                target = resolve_session(hass, data["session_id"])
                who = attribution(hass, call)
                if service == "calibration_commit":
                    return await target.commit(data["session_id"], who)
                return await target.capture(
                    data["session_id"], data["point"], data.get("force", False), who
                )
            if service == "calibration_abandon":
                return resolve_session(hass, data["session_id"]).abandon(
                    data["session_id"]
                )
            target = resolve_calibration(hass, data["room_id"])
            if service == "calibration_get":
                return target.response()
            who = attribution(hass, call)
            if service == "calibration_start":
                return await target.start(data["probe"], data.get("solutions"), who)
            if service == "calibration_revert":
                return await target.revert(data["probe"], who)
            if service == "probe_offset_set":
                return await target.probe_offset_set(data, who)
            response = await target.record(data, who)
            journal_record(hass, data["room_id"], response, call)
            return response
        except (ValueError, KeyError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    room_id = {vol.Required("room_id"): str}
    session_id = {vol.Required("session_id"): str}
    probe = vol.Required("probe")
    schemas = {
        "calibration_get": room_id,
        "calibration_record": {
            **room_id,
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            probe: str,
            vol.Required("points"): list,
            vol.Optional("note"): str,
        },
        "calibration_start": {
            **room_id,
            probe: vol.In(list(PROBES)),
            vol.Optional("solutions"): list,
        },
        "calibration_capture": {
            **session_id,
            vol.Required("point"): vol.In([0, 1]),
            vol.Optional("force"): bool,
        },
        "calibration_status": session_id,
        "calibration_commit": session_id,
        "calibration_revert": {**room_id, probe: vol.In(list(PROBES))},
        "calibration_abandon": session_id,
        "probe_offset_set": {
            **room_id,
            vol.Required("entity_id"): str,
            vol.Optional("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Optional("offset"): vol.Coerce(float),
            vol.Optional("curve"): str,
            vol.Optional("match_handheld"): vol.Coerce(float),
            vol.Optional("preview"): bool,
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            wrap(handle),
            schema=vol.Schema(fields(schemas[service])),
            # calibration_record answers only, as it always did.
            supports_response=(
                SupportsResponse.ONLY
                if service in (*READS, "calibration_record")
                else SupportsResponse.OPTIONAL
            ),
        )


async def async_unload_calibration(hass, entry):
    from homeassistant.helpers import issue_registry as ir

    managers = _managers(hass)
    manager = managers.pop(entry.entry_id, None)
    if manager is not None:
        manager._close()
        for entity_id, unsubscribe in manager._corrected.items():
            unsubscribe()
            hass.states.async_remove(manager._corrected_id(entity_id))
        manager._corrected.clear()
        if manager._timer:
            manager._timer()
            manager._timer = None
        hass.states.async_remove(manager.due_sensor)
        ir.async_delete_issue(hass, DOMAIN, manager.issue_id)
        ir.async_delete_issue(hass, DOMAIN, manager.offsets_issue_id)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
