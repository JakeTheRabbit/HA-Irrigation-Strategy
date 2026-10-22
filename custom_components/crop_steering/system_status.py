"""System status (G17): system_status_get and sensor.crop_steering_system_health.

status() reads, for every loaded room, the entities its setup maps (the zones' VWC, EC and root-zone
temperature probes and valves, the pump, the main line, the feed probes, the tank sensors and the
zones' flow meters from the site store), each online or not, and the controller's heartbeat.

- An entity is ok when it is not unknown/unavailable. A probe (probe_* and feed_probe) must also have
  reported within max(180 s, 3 x its own median report interval over the last hour), so a probe that
  reports every 5 min is not called silent. The intervals come from the recorder, read in the
  executor on the owner's 5-min tick; with no recorder every probe has the 180 s floor. Everything
  else (valves, pump, main line, tank sensors, flow meters) is ok while available.
- The controller of a room is running while its heartbeat is younger than 10 min and not dead (the
  rule of health.py's engine_offline); the site's controller is the best of the rooms'.
- Each room's heartbeat keeps its last 120 beats in memory (Ring), from a state listener on its
  ai_heartbeat; a gap above 2 x 60 s inserts a missed beat.

ONE sensor for the whole site, published by the room that loaded first (Tracker.owner) on its 5-min
health tick and whenever a room joins or leaves; when that room unloads, the next one owns it. The
last room unloading removes the sensor and the service. Nothing here touches irrigation.
"""

from __future__ import annotations

import functools
import logging
import statistics
from collections import deque
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from .alerts_inbox import sensor_id as alerts_sensor_id
from .const import DOMAIN
from .health import _DEAD, _STALE_MIN
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

KINDS = (
    "probe_vwc",
    "probe_ec",
    "probe_temp",
    "valve",
    "pump",
    "main_line",
    "feed_probe",
    "tank",
    "flow_meter",
)
PROBES = frozenset({"probe_vwc", "probe_ec", "probe_temp", "feed_probe"})
OFF = ("unknown", "unavailable")
TANK_KEYS = (
    "water_level_sensor",
    "tank_distance_sensor",
    "tank_low_float",
    "tank_temperature_sensor",
    "tank_ec_sensor",
    "tank_ph_sensor",
)
FLOOR_S = 180
INTERVAL_S = 60
RING_SIZE = 120
UPTIME_TTL = timedelta(hours=1)
RANK = {"absent": 0, "stale": 1, "running": 2}
SENSOR = f"sensor.{DOMAIN}_system_health"
SERVICE = "system_status_get"
TRACKER = "_system_status"


def heartbeat_id(prefix: str) -> str:
    return f"sensor.{DOMAIN}_{prefix}ai_heartbeat"


# ------------------------------------------------------------------ pure parts
def mapped(cfg: dict, meters: dict | None = None) -> list[tuple]:
    """[(kind, entity_id, zone)] the room config maps, in KINDS order (zone order within a kind),
    each entity once."""
    zones = cfg.get("zones") or {}
    hw = cfg.get("hardware") or {}
    rows = []
    for z in range(1, int(cfg.get("num_zones", len(zones) or 1)) + 1):
        zc = zones.get(str(z)) or zones.get(z) or {}
        for kind, many, pair in (
            ("probe_vwc", "vwc_sensors", ("vwc_front", "vwc_back")),
            ("probe_ec", "ec_sensors", ("ec_front", "ec_back")),
        ):
            for entity in list(zc.get(many) or []) or [
                zc[k] for k in pair if zc.get(k)
            ]:
                rows.append((kind, entity, z))
        if zc.get("substrate_temperature_sensor"):
            rows.append(("probe_temp", zc["substrate_temperature_sensor"], z))
        if zc.get("zone_switch"):
            rows.append(("valve", zc["zone_switch"], z))
    for kind, key in (
        ("pump", "pump_switch"),
        ("main_line", "main_line_switch"),
        ("feed_probe", "feed_ec_sensor"),
        ("feed_probe", "feed_ph_sensor"),
        *(("tank", key) for key in TANK_KEYS),
    ):
        if hw.get(key):
            rows.append((kind, hw[key], None))
    for zone, entity in sorted((meters or {}).items(), key=lambda kv: int(kv[0])):
        rows.append(("flow_meter", entity, int(zone)))
    seen, out = set(), []
    for row in sorted(rows, key=lambda r: KINDS.index(r[0])):
        if row[1] and row[1] not in seen:
            seen.add(row[1])
            out.append(row)
    return out


def median_interval(times) -> float | None:
    """The median of the gaps between consecutive report times, in seconds; None with fewer than two."""
    times = sorted(times)
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    return float(statistics.median(gaps)) if gaps else None


def uptime_pct(states, start, end) -> float | None:
    """The share of [start, end] in %, unrounded, that `states` (oldest first, each with state and
    last_changed) spend neither unknown nor unavailable. Time before the first state counts as down.
    """
    total = (end - start).total_seconds()
    if total <= 0:
        return None
    up = 0.0
    for i, state in enumerate(states):
        begin = max(state.last_changed, start)
        until = min(states[i + 1].last_changed if i + 1 < len(states) else end, end)
        if state.state not in OFF and until > begin:
            up += (until - begin).total_seconds()
    return up / total * 100


class Ring:
    """A room's last RING_SIZE heartbeats: {at, missed, readback_ms}."""

    def __init__(self):
        self.beats = deque(maxlen=RING_SIZE)

    def add(self, at, readback_ms=None) -> None:
        if self.beats:
            last = self.beats[-1]["at"]
            if at <= last:
                return
            if (at - last).total_seconds() > 2 * INTERVAL_S:
                self.beats.append(
                    {
                        "at": last + timedelta(seconds=INTERVAL_S),
                        "missed": True,
                        "readback_ms": None,
                    }
                )
        self.beats.append({"at": at, "missed": False, "readback_ms": readback_ms})

    def add_state(self, state) -> None:
        if str(state.state).lower() not in _DEAD:
            self.add(state.last_updated, (state.attributes or {}).get("readback_ms"))

    def rows(self) -> list[dict]:
        return [{**beat, "at": beat["at"].isoformat()} for beat in self.beats]


# ------------------------------------------------------------------ reading Home Assistant
def _rooms(hass):
    """(entry, prefix, room config) of each loaded room, in entry order (not one that is unloading)."""
    data = hass.data.get(DOMAIN, {})
    tracker = data.get(TRACKER)
    for entry in hass.config_entries.async_entries(DOMAIN):
        cfg = data.get(entry.entry_id)
        if not isinstance(cfg, dict):
            continue
        if tracker is not None and entry.entry_id not in tracker.entries:
            continue
        yield entry, room_prefix(entry), cfg


def _meters(hass, room_id) -> dict:
    site = hass.data.get(DOMAIN, {}).get("_site")
    document = getattr(site, "document", None) or {}
    return (document.get("zone_meters") or {}).get(room_id) or {}


def _entity(hass, kind, entity_id, zone, now, tracker) -> dict:
    state = hass.states.get(entity_id)
    cached = tracker.uptime.get(entity_id) if tracker is not None else None
    row = {
        "entity_id": entity_id,
        "kind": kind,
        "name": entity_id,
        "zone": zone,
        "last_seen": None,
        "last_change": None,
        "ok": False,
        "uptime_7d_pct": cached[1] if cached else None,
    }
    if state is None:
        return row
    seen = getattr(state, "last_reported", None) or state.last_updated
    ok = state.state not in OFF
    if ok and kind in PROBES:
        median = (tracker.medians.get(entity_id) if tracker is not None else None) or 0
        ok = (now - seen).total_seconds() <= max(FLOOR_S, 3 * median)
    row.update(
        name=(state.attributes or {}).get("friendly_name") or entity_id,
        last_seen=seen.isoformat() if seen else None,
        last_change=state.last_changed.isoformat() if state.last_changed else None,
        ok=ok,
    )
    return row


def _heartbeat(hass, prefix, now, ring) -> dict:
    state = hass.states.get(heartbeat_id(prefix))
    out = {
        "last_beat": None,
        "age_s": None,
        "controller": "absent",
        "beats": ring.rows() if ring is not None else [],
        "interval_s": INTERVAL_S,
    }
    if state is None:
        return out
    age = (now - state.last_updated).total_seconds()
    dead = str(state.state).lower() in _DEAD
    out.update(
        last_beat=state.last_updated.isoformat(),
        age_s=age,
        controller="stale" if dead or age > _STALE_MIN * 60 else "running",
    )
    return out


def _ai(hass, prefix) -> dict | None:
    state = hass.states.get(f"sensor.{DOMAIN}_{prefix}jev")
    if state is None:
        return None
    attrs = state.attributes or {}
    calls, budget = attrs.get("calls_today"), attrs.get("daily_budget")
    numbers = all(isinstance(v, (int, float)) for v in (calls, budget))
    return {
        "calls_today": calls,
        "daily_budget": budget,
        "pct_used": calls / budget * 100 if numbers and budget else None,
        "model": attrs.get("model"),
    }


def _count(state) -> int | None:
    try:
        return int(state.state)
    except (AttributeError, TypeError, ValueError):
        return None


def _pct(rows) -> float | None:
    return sum(r["ok"] for r in rows) / len(rows) * 100 if rows else None


def status(hass, now, card=None) -> dict:
    """The site's status now. `card`: the dashboard card's ?v= (card_version(), async)."""
    from homeassistant import const as ha_const

    tracker = hass.data.get(DOMAIN, {}).get(TRACKER)
    rooms, ai, every = [], None, []
    best = (-1, None)  # (rank, addon version) of the best room's controller
    for _entry, prefix, cfg in _rooms(hass):
        room_id = "room:" + prefix
        rows = [
            _entity(hass, kind, entity, zone, now, tracker)
            for kind, entity, zone in mapped(cfg, _meters(hass, room_id))
        ]
        every += rows
        ring = tracker.rings.get(room_id) if tracker is not None else None
        beat = _heartbeat(hass, prefix, now, ring)
        rank = RANK[beat["controller"]]
        if rank > best[0]:
            state = hass.states.get(heartbeat_id(prefix))
            best = (
                rank,
                (getattr(state, "attributes", None) or {}).get("controller_version"),
            )
        if ai is None:
            ai = _ai(hass, prefix)
        rooms.append(
            {
                "room_id": room_id,
                "entities": rows,
                "groups": [
                    {"kind": kind, "entities": [r for r in rows if r["kind"] == kind]}
                    for kind in KINDS
                    if any(r["kind"] == kind for r in rows)
                ],
                "pct_online": _pct(rows),
                "alerts_open": _count(hass.states.get(alerts_sensor_id(room_id))),
                "controller": beat["controller"],
                "heartbeat": beat,
            }
        )
    controller = next((c for c, r in RANK.items() if r == best[0]), "absent")
    return {
        "controller": controller,
        "addon_version": best[1],
        "pct_online": _pct(every),
        "rooms": rooms,
        "ha_version": getattr(ha_const, "__version__", None),
        "ai": ai,
        "card_version": card,
    }


async def card_version(hass) -> str | None:
    """The ?v= of the registered Lovelace resource whose URL contains crop_steering; None when there is
    none or the resources cannot be read."""
    from .dashboards import lovelace_part

    resources = lovelace_part(hass, "resources")
    if resources is None:
        return None
    try:
        await resources.async_get_info()  # a storage collection loads on first use
        items = list(resources.async_items() or [])
    except Exception as error:  # the card version is then unknown, never an error
        _LOGGER.debug("Lovelace resources not read: %s", error)
        return None
    for item in items:
        url = str((item or {}).get("url", ""))
        if "crop_steering" in url:
            found = parse_qs(urlsplit(url).query).get("v")
            return found[0] if found else None
    return None


# ------------------------------------------------------------------ the tracker
class Tracker:
    """The site's heartbeat rings, recorder caches and the system_health sensor."""

    def __init__(self, hass):
        self.hass = hass
        self.entries: dict[str, str] = (
            {}
        )  # entry_id -> room_id, in the order the rooms loaded
        self.rings: dict[str, Ring] = {}
        self.medians: dict[str, float | None] = {}
        self.medians_at = None
        self.uptime: dict[str, tuple] = {}  # entity_id -> (read at, %)
        self._unsubs: dict = {}
        self._no_recorder_said = False

    @property
    def owner(self) -> str | None:
        """The entry that publishes the sensor: the first loaded that is still loaded."""
        return next(iter(self.entries), None)

    def ring(self, room_id) -> Ring:
        return self.rings.setdefault(room_id, Ring())

    def join(self, entry) -> None:
        from homeassistant.core import callback
        from homeassistant.helpers.event import async_track_state_change_event

        prefix = room_prefix(entry)
        room_id = "room:" + prefix
        self.entries[entry.entry_id] = room_id
        ring = self.ring(room_id)
        current = self.hass.states.get(heartbeat_id(prefix))
        if current is not None:
            ring.add_state(current)
        if entry.entry_id not in self._unsubs:

            @callback
            def beat(event):
                new = event.data.get("new_state")
                if new is not None:
                    ring.add_state(new)

            self._unsubs[entry.entry_id] = async_track_state_change_event(
                self.hass, [heartbeat_id(prefix)], beat
            )
        self.publish()

    def leave(self, entry) -> None:
        unsub = self._unsubs.pop(entry.entry_id, None)
        if unsub is not None:
            unsub()
        room_id = self.entries.pop(entry.entry_id, None)
        if room_id not in self.entries.values():
            self.rings.pop(room_id, None)
        if self.entries:
            self.publish()
        else:
            self.hass.states.async_remove(SENSOR)

    def publish(self) -> None:
        from homeassistant.util import dt as dt_util

        out = status(self.hass, dt_util.utcnow())
        silent = sorted(
            {
                e["entity_id"]
                for room in out["rooms"]
                for e in room["entities"]
                if not e["ok"]
            }
        )
        pct = out["pct_online"]
        self.hass.states.async_set(
            SENSOR,
            "unknown" if pct is None else str(pct),
            {
                "friendly_name": "Crop Steering system health",
                "unit_of_measurement": "%",
                "pct_online": pct,
                "silent": silent,
                "controller": out["controller"],
                "addon_version": out["addon_version"],
            },
        )

    async def async_tick(self, entry_id) -> None:
        """The 5-min health tick of a room: only the owner's refreshes and publishes."""
        if entry_id != self.owner:
            return
        await self.refresh_medians()
        if self.entries:
            self.publish()

    def _rows(self, kinds=None) -> list[str]:
        return sorted(
            {
                entity
                for _entry, prefix, cfg in _rooms(self.hass)
                for kind, entity, _zone in mapped(
                    cfg, _meters(self.hass, "room:" + prefix)
                )
                if kinds is None or kind in kinds
            }
        )

    def _recorder(self) -> bool:
        if "recorder" in self.hass.config.components:
            return True
        if not self._no_recorder_said:
            self._no_recorder_said = True
            _LOGGER.info(
                "System status: no recorder, so every probe is silent after %d s and 7-day uptime is "
                "not known",
                FLOOR_S,
            )
        return False

    async def refresh_medians(self) -> None:
        """Each probe's median report interval over the last hour, read in the executor."""
        from homeassistant.util import dt as dt_util

        if not self._recorder():
            return
        probes = self._rows(PROBES)
        now = dt_util.utcnow()
        if probes:
            from homeassistant.components.recorder import get_instance, history

            try:
                found = await get_instance(self.hass).async_add_executor_job(
                    functools.partial(
                        history.get_significant_states,
                        self.hass,
                        now - timedelta(hours=1),
                        now,
                        probes,
                        significant_changes_only=False,
                        no_attributes=True,
                        include_start_time_state=False,
                    )
                )
            except Exception as error:  # the 180 s floor then holds
                _LOGGER.debug("System status: report intervals not read: %s", error)
                return
            self.medians = {
                entity: median_interval(s.last_updated for s in found.get(entity, []))
                for entity in probes
            }
        self.medians_at = now

    async def refresh_uptime(self, now) -> None:
        """uptime_7d of each mapped entity not read in the last hour, in the executor."""
        if not self._recorder():
            return
        due = [
            entity
            for entity in self._rows()
            if entity not in self.uptime or now - self.uptime[entity][0] >= UPTIME_TTL
        ]
        if not due:
            return
        from homeassistant.components.recorder import get_instance, history

        start = now - timedelta(days=7)

        def read():
            out = {}
            for entity in due:
                found = history.state_changes_during_period(
                    self.hass,
                    start,
                    now,
                    entity,
                    no_attributes=True,
                    include_start_time_state=True,
                )
                out[entity] = uptime_pct(found.get(entity, []), start, now)
            return out

        try:
            read_now = await get_instance(self.hass).async_add_executor_job(read)
        except Exception as error:  # uptime then stays as it was (None at first)
            _LOGGER.debug("System status: uptime not read: %s", error)
            return
        for entity, pct in read_now.items():
            self.uptime[entity] = (now, pct)


async def answer(hass) -> dict:
    """system_status_get: status() with fresh recorder caches and the card version."""
    from homeassistant.util import dt as dt_util

    now = dt_util.utcnow()
    tracker = hass.data.get(DOMAIN, {}).get(TRACKER)
    if tracker is not None:
        if tracker.medians_at is None:
            await tracker.refresh_medians()
        await tracker.refresh_uptime(now)
    return status(hass, now, card=await card_version(hass))


# ------------------------------------------------------------------ setup
def async_setup_system_status(hass, entry) -> None:
    """The first room creates the tracker and the service; every room joins."""
    data = hass.data.setdefault(DOMAIN, {})
    tracker = data.get(TRACKER)
    if tracker is None:
        import voluptuous as vol
        from homeassistant.core import SupportsResponse

        from .api_v2 import fields, wrap

        tracker = data[TRACKER] = Tracker(hass)

        async def handle(call):
            return await answer(hass)

        hass.services.async_register(
            DOMAIN,
            SERVICE,
            wrap(handle),
            schema=vol.Schema(fields({})),
            supports_response=SupportsResponse.ONLY,
        )
    tracker.join(entry)


def tick(hass, entry) -> None:
    """A room's 5-min health tick (__init__.py): the owner refreshes and publishes, in a task."""
    tracker = hass.data.get(DOMAIN, {}).get(TRACKER)
    if tracker is not None and tracker.owner == entry.entry_id:
        hass.async_create_task(tracker.async_tick(entry.entry_id))


def async_unload_system_status(hass, entry) -> None:
    """A room leaves; the last one takes the sensor, the listeners and the service away."""
    data = hass.data.get(DOMAIN, {})
    tracker = data.get(TRACKER)
    if tracker is None:
        return
    tracker.leave(entry)
    if not tracker.entries:
        data.pop(TRACKER, None)
        hass.services.async_remove(DOMAIN, SERVICE)
