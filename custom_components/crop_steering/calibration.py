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
from .const import DOMAIN, REPAIRS_DOCS_URL
from .generated.ids import new_id
from .health import _iid
from .journal_api import attribution, note
from .room import room_prefix

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
        self.due_sensor = f"binary_sensor.{DOMAIN}_{self.prefix}calibration_due"
        self._store = store
        self._now = now or _utcnow
        self._lock = asyncio.Lock()
        self._timer = None
        self.document = {"revision": 0, "records": []}
        self.sessions = {}
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.calibration.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                if (
                    not isinstance(value, dict)
                    or type(value.get("revision")) is not int
                    or value["revision"] < 0
                    or not isinstance(value.get("records"), list)
                ):
                    raise ValueError("Invalid stored calibration history")
                self.document = {
                    "revision": value["revision"],
                    "records": _trim(value["records"]),
                }
        except Exception as error:
            self.error = f"Stored calibration history could not be loaded; it has not been overwritten: {error}"

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
        return async_track_time_interval(self.hass, hourly, timedelta(hours=1))

    def calibrating(self):
        """The dosing descriptor's `calibrating` while a session is open, else None."""
        now = self._now()
        for session in self.sessions.values():
            until = session["active"] + SESSION_IDLE
            if now < until:
                return {
                    "probe": session["probe"],
                    "session_id": session["id"],
                    "until": until.isoformat(),
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

    def session(self, session_id):
        self.expire()
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError(EXPIRED)
        return session

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
            raise ValueError(self.error)
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
        self._close()  # one session per room: a new start replaces the last
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
                raise ValueError(self.error)
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
                raise ValueError(self.error)
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
                "revision": self.document["revision"] + 1,
                "records": records,
            }
            await self._store.async_save(document)
            self.document = document
        self._close()
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
        self.session(
            session_id
        )  # unknown or expired: refused like every other session step
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
                raise ValueError(self.error)
            if data.get("expected_revision") != self.document["revision"]:
                raise ValueError(
                    "Calibration history changed elsewhere. Reload before saving."
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
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
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
        if manager._timer:
            manager._timer()
            manager._timer = None
        hass.states.async_remove(manager.due_sensor)
        ir.async_delete_issue(hass, DOMAIN, manager.issue_id)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
