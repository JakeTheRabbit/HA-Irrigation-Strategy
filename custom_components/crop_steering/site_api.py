"""The site store and its services: supply_get and supply_save (G1: pump capacity, exclusive groups),
and the presets every client shares with preset_list/save/delete/apply and copy_config (G10).

One store for the whole site (crop_steering.site), set up with the first room; each room after it
only joins, and the store, the sensor and the services stay while any room is loaded. Reading is
open to any signed-in user; a save needs an administrator.

sensor.crop_steering_supply_config is what the controller app reads: its state is the revision and
its attributes the pumps, the groups, the meters and each active zone's demand in L/h. It exists
only once a supply has been saved, so a site that never saved one reads exactly as before.
Nothing here switches, presses or sets any hardware. A preset apply or a copy writes the rooms'
own numbers, each read back (presets.py); presets keep their own revision, apart from the supply's.

Threshold alert rules (G6, alert_rules.py) live here too, with their own revision: alert_rule_set and
alert_rule_delete for an administrator, alert_rule_list, alert_rule_preview and alert_rule_test for any
signed-in user (a test that sends a push needs an administrator). RuleEvaluator reads each rule's
source, runs its lifecycle and raises alert.raised / alert.cleared with a push routed by the rule's
own kind; binary_sensor.crop_steering_rule_<id> shows it. A site with no rules watches nothing.
Rules only notify: nothing they do touches irrigation.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from . import alert_rules, presets, site_store
from .admin import async_require_admin
from .api_v2 import StaleRevision, Unavailable
from .const import DOMAIN
from .generated.guards import zone_demand_lph
from .generated.ids import new_id
from .journal_api import HUB, attribution, note
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = (
    "supply_get",
    "supply_save",
    "preset_list",
    "preset_save",
    "preset_delete",
    "preset_apply",
    "copy_config",
    "alert_rule_set",
    "alert_rule_delete",
    "alert_rule_test",
    "alert_rule_preview",
    "alert_rule_list",
)
# alert_rule_test is not one: with send it pushes, so it is OPTIONAL like a write.
READS = (
    "supply_get",
    "preset_list",
    "alert_rule_preview",
    "alert_rule_list",
)
SENSOR = f"sensor.{DOMAIN}_supply_config"
# The rules of the site changed (binary_sensor.py adds and removes its entities), and one rule's state.
RULES_CHANGED = f"{DOMAIN}_rules_changed"
SENSORS = "_rule_sensors"  # {entry_id: binary_sensor.RuleSensors}
RULE_STATE = f"{DOMAIN}_rule_state_{{}}"
TICK = timedelta(seconds=60)
SINCE_EVER = "1970-01-01T00:00:00+00:00"
MAX_HOURS = 168  # a replay or a preview looks back at most a week
STORAGE_KEY = f"{DOMAIN}.site"
SIZING_KEYS = ("plant_count", "drippers_per_plant", "dripper_flow_rate")


class SiteStore:
    def __init__(self, hass, store=None):
        self.hass = hass
        self._store = store
        self._lock = asyncio.Lock()
        self.document = site_store.empty()
        self.error = None
        self.warnings = []

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(self.hass, 1, STORAGE_KEY)
            value = await self._store.async_load()
            if value is not None:
                self.document, self.warnings = site_store.load(value)
                for warning in self.warnings:
                    _LOGGER.warning(
                        "Crop Steering site store: stored %s could not be read and reads as empty "
                        "until a save replaces it: %s",
                        warning["section"],
                        warning["error"],
                    )
        except Exception as error:
            # The supply then reads as not set up; a save is refused, so the file is never overwritten.
            self.error = (
                "The stored site settings could not be loaded; they have not been "
                f"overwritten: {error}"
            )
            _LOGGER.error("Crop Steering site store: %s", self.error)

    def rooms(self, skip=None) -> list[dict]:
        """Every active room's pump and each active zone's demand in L/h (not the room of the
        config entry `skip`, which is going away)."""
        from .setup_api import effective, setup_sizing

        rooms = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            data = effective(entry)
            if entry.entry_id == skip or not data.get("active", True):
                continue
            zones = {}
            for zone in range(1, int(data.get("num_zones", 1)) + 1):
                cfg = (
                    data.get("zones", {}).get(str(zone))
                    or data.get("zones", {}).get(zone)
                    or {}
                )
                if not cfg.get("active", True):
                    continue
                size = {
                    key: setup_sizing(self.hass, data, cfg, zone, key)
                    for key in SIZING_KEYS
                }
                zones[zone] = zone_demand_lph(**size)
            rooms.append(
                {
                    "room_id": "room:" + room_prefix(entry),
                    "pump": data.get("hardware", {}).get("pump_switch", ""),
                    "zones": zones,
                }
            )
        return rooms

    async def check(self, section: dict) -> dict:
        """The capacity check, worked out off the event loop (the rooms are read on it)."""
        return await self.hass.async_add_executor_job(
            site_store.capacity_check,
            section["irrigation_pumps"],
            self.rooms(),
            section["zone_groups"],
        )

    async def response(self) -> dict:
        section = site_store.supply_of(self.document)
        return {
            "revision": self.document["revision"],
            **deepcopy(section),
            "capacity_check": await self.check(section),
            "warnings": deepcopy(self.warnings),
            "error": self.error,
        }

    def publish(self, skip=None):
        """sensor.crop_steering_supply_config: absent until a supply is saved, unavailable while the
        stored settings cannot be read (the controller then runs as it did before)."""
        if self.error:
            self.hass.states.async_set(SENSOR, "unavailable", {"error": self.error})
            return
        if not self.document["revision"]:
            self.hass.states.async_remove(SENSOR)
            return
        demand = {}
        for room in self.rooms(skip):
            if room["zones"]:
                demand[room["room_id"]] = {
                    str(zone): lph for zone, lph in sorted(room["zones"].items())
                }
        document = self.document
        self.hass.states.async_set(
            SENSOR,
            str(document["revision"]),
            {
                "friendly_name": "Crop Steering supply",
                "irrigation_pumps": deepcopy(document["irrigation_pumps"]),
                "zone_groups": deepcopy(document["zone_groups"]),
                "zone_meters": deepcopy(document["zone_meters"]),
                "zone_demand_lph": demand,
            },
        )

    def _new_section(self, data) -> dict:
        section = deepcopy(site_store.supply_of(self.document))
        section["irrigation_pumps"] = site_store.clean_pumps(data["irrigation_pumps"])
        if "water_sources" in data:
            section["water_sources"] = site_store.clean_sources(data["water_sources"])
        if "zone_groups" in data:
            section["zone_groups"] = site_store.clean_groups(data["zone_groups"])
        if "zone_meters" in data:
            section["zone_meters"] = site_store.clean_meters(data["zone_meters"])
        return section

    async def save(self, data, who=None) -> dict:
        from .setup_api import setup_diff

        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            if data["expected_revision"] != self.document["revision"]:
                raise StaleRevision(
                    "Supply settings changed elsewhere. Reload before saving.",
                    self.document["revision"],
                )
            unread = [
                w["section"]
                for w in self.warnings
                if w["section"] != "irrigation_pumps" and w["section"] not in data
            ]
            if unread:
                raise ValueError(
                    f"The stored {', '.join(unread)} could not be read and would be lost. "
                    "Send that section in this save to replace it."
                )
            old = deepcopy(site_store.supply_of(self.document))
            new = self._new_section(data)
            check = await self.check(new)
            diff = setup_diff(old, new)
            if data.get("preview"):
                # Shown, not refused: the caller draws the sentence and the suggested count.
                return {"diff": diff, "capacity_check": check}
            site_store.refuse_over_capacity(check)
            document = {
                **self.document,
                **new,
                "revision": self.document["revision"] + 1,
            }
            await self._store.async_save(deepcopy(document))
            self.document = document
            self.warnings = [
                w
                for w in self.warnings
                if w["section"] != "irrigation_pumps" and w["section"] not in data
            ]
            self.publish()
            self._journal(old, new, diff, who)
            result = await self.response()
            published = self.hass.states.get(SENSOR)
            result["readback"] = {
                "status": (
                    "ok"
                    if published is not None
                    and published.state == str(document["revision"])
                    else "mismatch"
                ),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "entity_id": SENSOR,
            }
            return result

    # ------------------------------------------------------------------ presets (G10)
    def presets_response(self) -> dict:
        return {
            "revision": self.document["presets_revision"],
            "presets": [
                deepcopy(p) for p in self.document["presets"] if not p.get("deleted_at")
            ],
            "error": self.error,
        }

    def preset(self, preset_id) -> dict:
        for preset in self.document["presets"]:
            if preset.get("id") == preset_id and not preset.get("deleted_at"):
                return deepcopy(preset)
        raise ValueError(f"No preset {preset_id}")

    async def save_preset(self, data, values, who=None) -> dict:
        """A new preset of `values` ({section: {key: value}}, captured from data["from"])."""
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 60:
            raise ValueError("A preset needs a name of up to 60 characters")
        scope = data.get("scope")
        if scope not in presets.SCOPES:
            raise ValueError("scope must be targets, timers or all")
        source = presets.ref(data.get("from"))
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        who = who or {}
        preset = {
            "id": new_id(),
            "name": name,
            "scope": scope,
            "sections": list(presets.SCOPES[scope]),
            "from": source,
            "values": deepcopy(values),
            "created_at": stamp,
            "updated_at": stamp,
            "deleted_at": None,
            "by": {"actor": who.get("actor"), "user_id": who.get("user_id")},
        }

        def change(stored):
            stored.append(preset)
            return deepcopy(preset)

        result, revision = await self._save_presets(
            data["expected_revision"], change, who, source["room_id"]
        )
        return {"preset": result, "revision": revision}

    async def delete_preset(self, data, who=None) -> dict:
        """Soft: the preset leaves the list and stays in the store with deleted_at."""
        source = self.preset(data["id"]).get("from")
        if not isinstance(source, dict) or not isinstance(source.get("room_id"), str):
            raise ValueError(f"Preset {data['id']} has no source room")
        room_id = source["room_id"]

        def change(stored):
            for preset in stored:
                if preset.get("id") == data["id"] and not preset.get("deleted_at"):
                    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    preset.update(deleted_at=stamp, updated_at=stamp)
                    return deepcopy(preset)
            raise ValueError(f"No preset {data['id']}")

        result, revision = await self._save_presets(
            data["expected_revision"], change, who, room_id
        )
        return {"preset": result, "revision": revision}

    async def _save_presets(self, expected_revision, change, who, room_id):
        """Change a copy of the presets, save, and journal config.changed (never failing the save)."""
        from .setup_api import setup_diff

        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            if expected_revision != self.document["presets_revision"]:
                raise StaleRevision(
                    "Presets changed elsewhere. Reload before saving.",
                    self.document["presets_revision"],
                )
            old = deepcopy(self.document["presets"])
            stored = deepcopy(old)
            result = change(stored)
            document = {
                **self.document,
                "presets": stored,
                "presets_revision": self.document["presets_revision"] + 1,
            }
            await self._store.async_save(deepcopy(document))
            self.document = document
        who = who or {}
        note(
            self.hass,
            room_id,
            "config.changed",
            actor=who.get("actor", "system"),
            detail=who.get("detail"),
            user_id=who.get("user_id"),
            client=who.get("client"),
            correlation=(
                {"causation_id": who["causation_id"]}
                if who.get("causation_id")
                else None
            ),
            data={
                "store": "site",
                "section": "presets",
                "old": old,
                "new": deepcopy(stored),
                "diff": setup_diff(old, stored),
            },
        )
        return result, document["presets_revision"]

    # ------------------------------------------------------------------ alert rules (G6)
    def rules(self, room_id=None) -> list[dict]:
        """The threshold rules, of one room or of every room."""
        return [
            deepcopy(rule)
            for rule in self.document["alert_rules"]
            if isinstance(rule, dict)
            and rule.get("kind") == "threshold"
            and (room_id is None or rule.get("room_id") == room_id)
        ]

    def rule(self, rule_id) -> dict:
        for rule in self.rules():
            if rule.get("id") == rule_id:
                return rule
        raise ValueError(f"No alert rule {rule_id}")

    async def save_rule(self, data, who=None) -> dict:
        """A new rule, or a change to one (the rule names its id)."""
        rule_id = data["rule"].get("id") if isinstance(data["rule"], dict) else None
        if rule_id is not None:
            self.rule(rule_id)
        rule = alert_rules.validate_rule(data["rule"], rule_id)
        presets._entry(self.hass, room_id=rule["room_id"])  # a room this site has

        def change(stored):
            for i, row in enumerate(stored):
                if isinstance(row, dict) and row.get("id") == rule["id"]:
                    stored[i] = rule
                    return
            stored.append(rule)

        revision = await self._save_alert_rules(
            data["expected_revision"], change, who, rule["room_id"]
        )
        sentence = rule_sentence(self.hass, rule)
        return {
            "rule": {**deepcopy(rule), "summary_sentence": sentence},
            "summary_sentence": sentence,
            "revision": revision,
        }

    async def delete_rule(self, data, who=None) -> dict:
        rule = self.rule(data["id"])

        def change(stored):
            stored[:] = [
                row
                for row in stored
                if not (isinstance(row, dict) and row.get("id") == rule["id"])
            ]

        revision = await self._save_alert_rules(
            data["expected_revision"], change, who, rule["room_id"]
        )
        return {"id": rule["id"], "revision": revision}

    async def _save_alert_rules(self, expected_revision, change, who, room_id):
        """Change a copy of the rules, save, journal config.changed (never failing the save), and tell
        the evaluator and the binary sensors."""
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        from .setup_api import setup_diff

        async with self._lock:
            if self.error:
                raise Unavailable(self.error)
            if expected_revision != self.document["alert_rules_revision"]:
                raise StaleRevision(
                    "Alert rules changed elsewhere. Reload before saving.",
                    self.document["alert_rules_revision"],
                )
            old = deepcopy(self.document["alert_rules"])
            stored = deepcopy(old)
            change(stored)
            document = {
                **self.document,
                "alert_rules": stored,
                "alert_rules_revision": self.document["alert_rules_revision"] + 1,
            }
            await self._store.async_save(deepcopy(document))
            self.document = document
        who = who or {}
        note(
            self.hass,
            room_id,
            "config.changed",
            actor=who.get("actor", "system"),
            detail=who.get("detail"),
            user_id=who.get("user_id"),
            client=who.get("client"),
            correlation=(
                {"causation_id": who["causation_id"]}
                if who.get("causation_id")
                else None
            ),
            data={
                "store": "site",
                "section": "alert_rules",
                "old": old,
                "new": deepcopy(stored),
                "diff": setup_diff(old, stored),
            },
        )
        evaluator = getattr(self, "alerts", None)
        if evaluator is not None:
            evaluator.refresh()
        # Every room's removals first, then every room's additions: a rule moved to another room
        # leaves its old room before the new one adds it under the same unique_id.
        rooms = list(self.hass.data.get(DOMAIN, {}).get(SENSORS, {}).values())
        for sensors in rooms:
            await sensors.remove_gone()
        loaded = self.hass.data.get(DOMAIN, {}).get(SENSORS, {})
        for sensors in rooms:
            # A room whose entry unloaded during the awaits above has left the managers: skip it.
            if any(m is sensors for m in loaded.values()):
                sensors.add_new()
        async_dispatcher_send(self.hass, RULES_CHANGED)
        return document["alert_rules_revision"]

    def _journal(self, old, new, diff, who):
        """config.changed with the whole section before and after, once in the journal of every room
        whose pump or zone is in the old or the new section (all sharing one causation_id so a fold
        can count the change once); the first room when none is. Never fails or delays the save.
        """
        try:
            if not diff:
                return
            rooms = self.rooms()
            pumps = {p["entity_id"] for s in (old, new) for p in s["irrigation_pumps"]}
            named = {
                room_id
                for s in (old, new)
                for key in ("zone_groups", "zone_meters")
                for room_id in s[key]
            }
            ids = sorted(
                r["room_id"]
                for r in rooms
                if r["pump"] in pumps or r["room_id"] in named
            )
            if not ids and rooms:
                ids = [min(r["room_id"] for r in rooms)]
            who = who or {}
            shared = who.get("causation_id") or new_id()
            for room_id in ids:
                note(
                    self.hass,
                    room_id,
                    "config.changed",
                    actor=who.get("actor", "system"),
                    detail=who.get("detail"),
                    user_id=who.get("user_id"),
                    client=who.get("client"),
                    correlation={"causation_id": shared},
                    data={
                        "store": "site",
                        "section": "supply",
                        "old": old,
                        "new": new,
                        "diff": diff,
                    },
                )
        except Exception as error:
            _LOGGER.debug("Supply change not journaled: %s", error)


def _room_name(hass, rule) -> str | None:
    try:
        entry = presets._entry(hass, room_id=rule["room_id"])
    except ValueError:
        return None
    from .setup_api import effective

    return effective(entry).get("room_name") or None


def _thing_name(hass, rule) -> str | None:
    """The stock tank's name from the stock store, or the probe's friendly name."""
    if rule["source"] == "probe.silence_s":
        state = hass.states.get(rule["entity_id"])
        return (getattr(state, "attributes", None) or {}).get("friendly_name")
    if rule["source"] in alert_rules.STOCK_SOURCES:
        from .stock_api import resolve_stock

        try:
            tanks = resolve_stock(hass, rule["room_id"]).data["tanks"]
        except ValueError:
            return None
        tank = next((t for t in tanks if t.get("id") == rule["tank_id"]), None)
        return (tank or {}).get("name") or None
    return None


def rule_title(hass, rule) -> str:
    """The rule's short name with the room's and the tank's or probe's names: "F2 tank level below 30%"."""
    return alert_rules.title(rule, _room_name(hass, rule), _thing_name(hass, rule))


def rule_sentence(hass, rule) -> str:
    return alert_rules.summary_sentence(
        rule, _room_name(hass, rule), _thing_name(hass, rule)
    )


def _number(state):
    try:
        value = float(state.state)
    except (AttributeError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _local(at):
    from homeassistant.util import dt as dt_util

    as_local = getattr(dt_util, "as_local", None)
    return as_local(at) if as_local is not None else at


def _local_now():
    from homeassistant.util import dt as dt_util

    return dt_util.now()


class RuleEvaluator:
    """Runs every threshold rule of the site (alert_rules.step) on its source's value: when a watched
    entity changes, when the stock changes, and every minute (ages grow with no change). The state of
    each rule lives in memory, so a restart arms them again and a rule still breaching fires again
    after its min_duration_s. Only reads and notifies."""

    def __init__(self, hass, site):
        self.hass, self.site = hass, site
        self.states = {}  # rule id -> alert_rules.step state
        self._reported = {}  # probe entity -> its last numeric report
        self._looked = (
            set()
        )  # probes the recorder was asked about this run (asked once)
        self._seeding = None  # the seed_reports task, cancelled by stop()
        self._running = False
        self._watching = ()
        self._unwatch = None
        self._unsubs = []
        self._now = _local_now

    # ------------------------------------------------------------------ sources
    def lights(self, room_id) -> tuple[float, float]:
        """The room's lights-on and lights-off hours: its numbers, else what setup saved."""
        from .setup_api import effective

        px = room_id[len("room:") :]
        try:
            config = effective(presets._entry(self.hass, room_id=room_id))
        except ValueError:
            config = {}
        out = []
        for key, default in (("lights_on_hour", 12), ("lights_off_hour", 0)):
            hour = _number(self.hass.states.get(f"number.{DOMAIN}_{px}{key}"))
            if hour is None or not 0 <= hour < 24:
                hour = float(config.get(key, default))
            out.append(hour)
        return out[0], out[1]

    def _descriptor(self, px) -> dict:
        state = self.hass.states.get(f"sensor.{DOMAIN}_{px}engine_config")
        return dict(getattr(state, "attributes", None) or {})

    def entities(self, rule) -> list[str]:
        """The entities the rule's value is read from (the stock sensor for a stock tank)."""
        source, px = rule["source"], rule["room_id"][len("room:") :]
        zones = rule.get("zones") or []
        if source in ("zone.vwc", "zone.ec"):
            metric = source.split(".")[1]
            return [f"sensor.{DOMAIN}_{px}{metric}_zone_{z}" for z in zones]
        if source == "zone.flow_ratio":
            return [f"sensor.{DOMAIN}_{px}zone_{z}_flow_ratio" for z in zones]
        if source == "zone.temperature":
            mapped = self._descriptor(px).get("substrate_temperature_sensors") or {}
            return [mapped[str(z)] for z in zones if mapped.get(str(z))]
        if source in ("feed.ph", "feed.ec"):
            probe = source.replace(".", "_")
            corrected = f"sensor.{DOMAIN}_{px}{probe}_corrected"
            state = self.hass.states.get(corrected)
            if state is not None and state.attributes.get("applied") is True:
                return [corrected]
            raw = self._descriptor(px).get(f"{probe}_sensor")
            return [raw] if raw else []
        if source == "tank.level":
            return [f"sensor.{DOMAIN}_{px}tank_level"]
        if source == "controller.heartbeat":
            return [f"sensor.{DOMAIN}_{px}ai_heartbeat"]
        if source == "probe.silence_s":
            return [rule["entity_id"]]
        return [f"sensor.{DOMAIN}_{px}stock_low"]

    def value(self, rule, now) -> float | None:
        """The source's value now, in its canonical unit; None when it cannot be read."""
        source = rule["source"]
        if source in alert_rules.STOCK_SOURCES:
            return self._stock(rule)
        entities = self.entities(rule)
        if source == "controller.heartbeat":
            state = self.hass.states.get(entities[0])
            if state is None or state.state in ("unavailable", "unknown"):
                return None
            return (now - state.last_updated).total_seconds()
        if source == "probe.silence_s":
            return self._silence(rule["entity_id"], now)
        scale = 100 if source == "zone.flow_ratio" else 1
        values = [_number(self.hass.states.get(e)) for e in entities]
        values = [v * scale for v in values if v is not None]
        if not values:
            return None
        return min(values) if rule["op"] == "below" else max(values)

    def _silence(self, entity_id, now):
        """Seconds since the probe's last numeric report; unavailable counts as silent since then."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        if _number(state) is not None:
            at = getattr(state, "last_reported", None) or state.last_updated
            self._reported[entity_id] = at
        else:
            # Since its last numeric report. After a restart with nothing remembered yet, the
            # recorder's newest numeric report (seed_reports) is the start; until it is read, or with
            # no recorder, the time the probe went unavailable is, so the clock starts again then.
            at = self._reported.get(entity_id) or state.last_changed
        return None if at is None else (now - at).total_seconds()

    async def seed_reports(self, entity_ids):
        """The recorder's newest numeric report of each silent probe not yet remembered (after a
        restart), then its rules evaluated again."""
        if "recorder" not in self.hass.config.components:
            return
        from homeassistant.components.recorder import get_instance, history

        for entity_id in entity_ids:
            self._looked.add(entity_id)
            try:
                found = await get_instance(self.hass).async_add_executor_job(
                    history.get_last_state_changes, self.hass, 20, entity_id
                )
            except Exception as error:  # the silence then counts from last_changed
                _LOGGER.debug("Probe %s: no recorded report: %s", entity_id, error)
                continue
            if not self._running:
                return  # stopped meanwhile (the last room unloaded): evaluate nothing
            numeric = [s for s in found.get(entity_id, []) if _number(s) is not None]
            if numeric and entity_id not in self._reported:
                newest = max(numeric, key=lambda s: s.last_updated)
                self._reported[entity_id] = (
                    getattr(newest, "last_reported", None) or newest.last_updated
                )
        if not self._running:
            return
        for rule in self.site.rules():
            if rule.get("entity_id") in entity_ids:
                self.evaluate(rule)

    def _stock(self, rule):
        from .stock_api import resolve_stock

        try:
            manager = resolve_stock(self.hass, rule["room_id"])
        except ValueError:
            return None
        if manager.error:
            return None
        tank = next(
            (t for t in manager.data["tanks"] if t.get("id") == rule["tank_id"]), None
        )
        return _tank_value(tank, rule["source"])

    def muted(self, rule) -> bool:
        """The room is muted, and the rule is not routed to emergencies (those are never held)."""
        if rule.get("routing") == "emergency":
            return False
        notifier = self.hass.data.get(DOMAIN, {}).get("_notify")
        if notifier is None or notifier.error:
            return False
        return notifier.muted(rule["room_id"][len("room:") :])

    # ------------------------------------------------------------------ evaluating
    def evaluate(self, rule, now=None):
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        now = now or self._now()
        before = self.states.get(rule["id"], {})
        value = self.value(rule, now)
        state, event = alert_rules.step(
            before,
            value,
            now,
            rule,
            self.lights(rule["room_id"]),
            self.muted(rule),
        )
        self.states[rule["id"]] = state
        if event is not None:
            self._announce(rule, event, value)
        if state.get("state") != before.get("state"):
            async_dispatcher_send(self.hass, RULE_STATE.format(rule["id"]))

    def evaluate_all(self, now=None):
        now = now or self._now()
        for rule in self.site.rules():
            try:
                self.evaluate(rule, now)
            except Exception as error:  # one rule never stops the others
                _LOGGER.warning(
                    "Alert rule %s not evaluated: %s", rule.get("id"), error
                )

    def title(self, rule) -> str:
        return rule_title(self.hass, rule)

    def _announce(self, rule, event, value):
        """alert.raised / alert.cleared in the room's journal; a raise is pushed too."""
        zones = rule.get("zones") or []
        note(
            self.hass,
            rule["room_id"],
            f"alert.{event}",
            zone=zones[0] if len(zones) == 1 else None,
            actor="system",
            detail=f"rule {rule['id']}",
            data={
                "rule_id": rule["id"],
                "value": value,
                "threshold": rule["threshold"],
                "title": self.title(rule),
            },
        )
        if event == "raised":
            self.hass.async_create_task(self.push(rule, value))

    def push_data(self, rule, title, message) -> dict:
        """A Notifier.send push, routed by the rule's own kind; an emergency one is urgent (never
        held by a mute, a digest or quiet hours)."""
        return {
            "key": f"rule_{rule['id']}",
            "title": title,
            "message": message,
            "room": rule["room_id"][len("room:") :],
            "kinds": [rule.get("routing", "sensors")],
            "urgent": rule.get("routing") == "emergency",
        }

    async def push(self, rule, value, test=False) -> list[dict]:
        """One push for the rule -> [{service, ok, error}]."""
        notifier = self.hass.data.get(DOMAIN, {}).get("_notify")
        if notifier is None:
            return [
                {"service": None, "ok": False, "error": "Notifications are not set up"}
            ]
        sentence = rule_sentence(self.hass, rule)
        title = ("Test: " if test else "") + self.title(rule)
        message = sentence
        if value is not None:
            message = (
                f"{alert_rules.first_upper(alert_rules.label(rule, _thing_name(self.hass, rule)))} is "
                f"{alert_rules.amount(value, rule['unit'])}. {sentence}"
            )
        try:
            answer = await notifier.send(self.push_data(rule, title, message))
        except Exception as error:  # a push never stops a rule
            _LOGGER.warning("Alert rule %s not pushed: %s", rule["id"], error)
            return [{"service": None, "ok": False, "error": str(error)}]
        return delivery(answer)

    # ------------------------------------------------------------------ watching
    def refresh(self):
        """Watch the sources of today's rules (nothing at all when there are none) and evaluate."""
        self.stop()
        known = {rule["id"] for rule in self.site.rules()}
        for rule_id in set(self.states) - known:
            del self.states[rule_id]
        if not known:
            return
        self._running = True
        from homeassistant.core import callback
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from homeassistant.helpers.event import async_track_time_interval

        from .stock_api import SIGNAL as STOCK_SIGNAL

        @callback
        def tick(_now):
            self._watch()
            self.evaluate_all()

        @callback
        def stock_changed(*_):
            for rule in self.site.rules():
                if rule["source"] in alert_rules.STOCK_SOURCES:
                    self.evaluate(rule)

        self._unsubs.append(async_track_time_interval(self.hass, tick, TICK))
        for entry_id in self.hass.data.get(DOMAIN, {}).get("_stock", {}):
            self._unsubs.append(
                async_dispatcher_connect(
                    self.hass, f"{STOCK_SIGNAL}_{entry_id}", stock_changed
                )
            )
        self._watch(force=True)
        self.evaluate_all()
        silent = [
            rule["entity_id"]
            for rule in self.site.rules()
            if rule["source"] == "probe.silence_s"
            and rule["entity_id"] not in self._reported
            and rule["entity_id"] not in self._looked
            and self.hass.states.get(rule["entity_id"]) is not None
        ]
        if silent and "recorder" in self.hass.config.components:
            self._seeding = self.hass.async_create_task(
                self.seed_reports(sorted(set(silent)))
            )

    def _watch(self, force=False):
        """Follow the entities the active rules read (they may move: a feed calibration applied)."""
        wanted = tuple(
            sorted(
                {
                    entity
                    for rule in self.site.rules()
                    if rule.get("active", True)
                    for entity in self.entities(rule)
                }
            )
        )
        if wanted == self._watching and not force:
            return
        if self._unwatch is not None:
            self._unwatch()
        self._unwatch, self._watching = None, wanted
        if not wanted:
            return
        from homeassistant.core import callback
        from homeassistant.helpers.event import async_track_state_change_event

        @callback
        def changed(event):
            entity = event.data.get("entity_id")
            for rule in self.site.rules():
                if entity in self.entities(rule):
                    self.evaluate(rule)

        self._unwatch = async_track_state_change_event(self.hass, list(wanted), changed)

    def stop(self):
        self._running = False
        if self._seeding is not None and not self._seeding.done():
            self._seeding.cancel()
        self._seeding = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        if self._unwatch is not None:
            self._unwatch()
        self._unwatch, self._watching = None, ()

    # ------------------------------------------------------------------ answers
    async def last_fired(self, room_ids) -> dict:
        """{rule id: ts of its newest alert.raised} from each room's journal."""
        hub = self.hass.data.get(DOMAIN, {}).get(HUB)
        out = {}
        if (
            hub is None
            or getattr(hub, "failed", False)
            or getattr(hub, "closed", False)
        ):
            return out
        for room_id in sorted(set(room_ids)):
            try:
                page = await hub.query(
                    room_id=room_id,
                    since=SINCE_EVER,
                    kinds=["alert.raised"],
                    order="desc",
                    limit=500,
                )
            except Exception as error:  # the list still answers without it
                _LOGGER.debug("Alert rules: journal not read: %s", error)
                continue
            for event in page.get("events", []):
                rule_id = (event.get("data") or {}).get("rule_id")
                if rule_id and rule_id not in out:
                    out[rule_id] = event.get("ts")
        return out

    async def listing(self, room_id=None) -> dict:
        rules = self.site.rules(room_id)
        fired = await self.last_fired(r["room_id"] for r in rules)
        now = self._now()
        out = []
        for rule in rules:
            state = self.states.get(rule["id"], {})
            current = state.get("state") or (
                "armed" if rule.get("active", True) else "draft"
            )
            out.append(
                {
                    **rule,
                    "summary_sentence": rule_sentence(self.hass, rule),
                    "state": current,
                    "last_fired": fired.get(rule["id"]),
                    "firing_since": (
                        state["fired_at"].isoformat()
                        if current in alert_rules.ON
                        else None
                    ),
                    "current_value": self.value(rule, now),
                    "unit": rule["unit"],
                }
            )
        # The revision alert_rule_set takes as expected_revision (site-wide, whatever room is asked).
        return {"rules": out, "revision": self.site.document["alert_rules_revision"]}

    async def history(self, rule, hours) -> list:
        """The rule's value over the last `hours` from the recorder: [(local time, value)]."""
        now = self._now()
        start = now - timedelta(hours=hours)
        entities = self.entities(rule)
        if not entities or "recorder" not in self.hass.config.components:
            return []
        from homeassistant.components.recorder import get_instance, history

        stock = rule["source"] in alert_rules.STOCK_SOURCES
        found = await get_instance(self.hass).async_add_executor_job(
            functools.partial(
                history.get_significant_states,
                self.hass,
                start,
                now,
                entities,
                significant_changes_only=False,
                no_attributes=not stock,
            )
        )
        return series(rule, found, entities, start, now)

    async def replay(self, rule, hours) -> dict:
        samples = await self.history(rule, hours)
        return alert_rules.replay(
            samples,
            rule,
            self.lights(rule["room_id"]),
            hours=hours,
            end=self._now(),
        )


def _tank_value(tank, source):
    if not tank:
        return None
    if source == "stock.litres":
        return float(tank["level_l"])
    if not tank.get("capacity_l"):
        return None
    return tank["level_l"] / tank["capacity_l"] * 100


def series(rule, found, entities, start, end) -> list:
    """Recorded states ({entity: [State]}) as the rule's (local time, value) samples."""
    source = rule["source"]
    if source in alert_rules.AGE_SOURCES:
        states = found.get(entities[0], [])
        if source == "probe.silence_s":
            states = [s for s in states if _number(s) is not None]
        else:
            states = [s for s in states if s.state not in ("unavailable", "unknown")]
        reports = [_local(s.last_updated) for s in states]
        return alert_rules.age_samples(reports, _local(start), _local(end))
    if source in alert_rules.STOCK_SOURCES:
        out = []
        for state in found.get(entities[0], []):
            tanks = state.attributes.get("tanks") or []
            tank = next((t for t in tanks if t.get("id") == rule["tank_id"]), None)
            out.append((_local(state.last_updated), _tank_value(tank, source)))
        return out
    scale = 100 if source == "zone.flow_ratio" else 1
    each = []
    for entity in entities:
        rows = []
        for state in found.get(entity, []):
            value = _number(state)
            rows.append(
                (_local(state.last_updated), None if value is None else value * scale)
            )
        each.append(rows)
    return alert_rules.merge_worst(each, rule["op"])


def delivery(answer) -> list[dict]:
    """A Notifier.send answer as [{service, ok, error}], one row per phone where it can say."""
    rows = [
        {"service": s, "ok": True, "error": None} for s in answer.get("sent_to", [])
    ]
    rows += [
        {
            "service": s,
            "ok": False,
            "error": "held for the phone's digest or quiet hours",
        }
        for s in answer.get("held", [])
    ]
    if answer.get("muted"):
        rows.append({"service": None, "ok": False, "error": "The room is muted"})
    for part in (answer.get("error") or "").split("; "):
        if not part:
            continue
        service, _, error = part.partition(": ")
        if service.startswith("notify.") and error:
            rows.append({"service": service, "ok": False, "error": error})
        else:
            rows.append({"service": None, "ok": False, "error": part})
    return rows


def _not_delivered(call, result):
    """API v2: alert_rule_test with send: a phone that did not get the test push."""
    from .api_v2 import failure

    failed = [row for row in result.get("delivery") or () if not row.get("ok")]
    if not failed:
        return None
    return failure(
        "unavailable",
        "; ".join(f"{row['service'] or 'push'}: {row['error']}" for row in failed),
    )


async def _alert_rule(hass, site, call) -> dict:
    """The alert rule services. A list, a preview and a test that sends nothing are open to any
    signed-in user; a save, a delete and a test push need an administrator."""
    args, alerts = call.data, site.alerts
    if call.service in ("alert_rule_set", "alert_rule_delete") or args.get("send"):
        await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
    if call.service == "alert_rule_list":
        return await alerts.listing(args.get("room_id"))
    if call.service == "alert_rule_set":
        return await site.save_rule(args, attribution(hass, call))
    if call.service == "alert_rule_delete":
        return await site.delete_rule(args, attribution(hass, call))
    hours = float(args.get("hours", 24))
    if call.service == "alert_rule_preview":
        rule = alert_rules.validate_rule(args["rule"], "draft")
        sentence = rule_sentence(hass, rule)
        return {"summary_sentence": sentence, **await alerts.replay(rule, hours)}
    if ("id" in args) == ("rule" in args):
        raise ValueError(f"{DOMAIN}.alert_rule_test needs either id or rule")
    if "id" in args:
        rule = site.rule(args["id"])
    else:
        rule = alert_rules.validate_rule(args["rule"], args["rule"].get("id"))
    out = {
        "summary_sentence": rule_sentence(hass, rule),
        "replay": await alerts.replay(rule, hours),
    }
    if args.get("send"):
        out["delivery"] = await alerts.push(
            rule, alerts.value(rule, alerts._now()), test=True
        )
    return out


def _rows_refused(call, result):
    """API v2: an apply or copy whose target refused a value. The other values are written; every
    row is in `data.applied`. A timer the source has none of (`missing`) was never written, so it
    refuses nothing; it stays in `data.missing`."""
    from .api_v2 import failure

    refused = [
        row
        for row in result.get("applied") or ()
        if row.get("readback") == "refused" and not row.get("missing")
    ]
    if not refused:
        return None
    return failure(
        "guard_refused",
        "Not applied: "
        + "; ".join(f"{row['key']}: {row.get('error')}" for row in refused),
    )


async def async_setup_site(hass, entry) -> None:
    """Once for the site, with the first room that sets up; each room after it only joins (and
    publishes again, as its sizing may have changed)."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .api_v2 import fields, wrap

    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault("_site_entries", set()).add(entry.entry_id)
    if "_site" in data:
        data["_site"].publish()
        data["_site"].alerts.refresh()  # the joining room's stock tanks
        return
    site = data["_site"] = SiteStore(hass)
    await site.async_init()
    site.publish()
    site.alerts = RuleEvaluator(hass, site)
    site.alerts.refresh()

    async def handle(call):
        args = call.data
        try:
            if call.service == "supply_get":
                return await site.response()
            if call.service == "preset_list":
                return site.presets_response()
            if call.service.startswith("alert_rule_"):
                return await _alert_rule(hass, site, call)
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
            who = attribution(hass, call)
            if call.service == "supply_save":
                return await site.save(args, who)
            if call.service == "preset_save":
                sections = presets.SCOPES.get(args["scope"], ())
                if (
                    "values" in args
                ):  # given, not read: a grow plan imported from a browser
                    values, skipped = presets.given_values(args["values"], sections), []
                else:
                    values, skipped = presets.read_source(hass, args["from"], sections)
                saved = await site.save_preset(args, values, who)
                return {**saved, "skipped": skipped}
            if call.service == "preset_delete":
                return await site.delete_preset(args, who)
            preview = args.get("preview", False)
            if call.service == "preset_apply":
                preset = site.preset(args["preset_id"])
                detail = f"preset {preset['name']}"
                return await presets.apply(
                    hass,
                    preset["values"],
                    args["to"],
                    preview,
                    {**who, "detail": detail},
                )
            sections = list(args["sections"])
            if not sections or not set(sections) <= set(presets.SECTIONS):
                raise ValueError(
                    "sections must name one or more of " + ", ".join(presets.SECTIONS)
                )
            source = presets.ref(args["from"])
            wanted, skipped = presets.read_source(hass, source, sections)
            detail = "copy from " + source["room_id"]
            if "zone" in source:
                detail += f" zone {source['zone']}"
            copied = await presets.apply(
                hass, wanted, args["to"], preview, {**who, "detail": detail}
            )
            return {**copied, "skipped": skipped}
        except (ValueError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    whole = vol.All(int, vol.Range(min=0))
    hours = vol.All(vol.Coerce(float), vol.Range(min=1, max=MAX_HOURS))
    common = {
        vol.Optional("client"): vol.In(["mcp", "aigrow"]),
        vol.Optional("proposal_token"): str,
    }
    schemas = {
        "supply_get": {},
        "supply_save": {
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("irrigation_pumps"): list,
            vol.Optional("water_sources"): list,
            vol.Optional("zone_groups"): dict,
            vol.Optional("zone_meters"): dict,
            vol.Optional("preview"): bool,
            vol.Optional("client"): vol.In(["mcp", "aigrow"]),
            vol.Optional("proposal_token"): str,
        },
        "preset_list": {},
        "preset_save": {
            vol.Required("name"): str,
            vol.Required("scope"): vol.In(list(presets.SCOPES)),
            vol.Required("from"): dict,
            vol.Required("expected_revision"): whole,
            vol.Optional("values"): dict,
            **common,
        },
        "preset_delete": {
            vol.Required("id"): str,
            vol.Required("expected_revision"): whole,
            **common,
        },
        "preset_apply": {
            vol.Required("preset_id"): str,
            vol.Required("to"): [dict],
            vol.Optional("preview"): bool,
            **common,
        },
        "copy_config": {
            vol.Required("from"): dict,
            vol.Required("to"): [dict],
            vol.Required("sections"): [vol.In(list(presets.SECTIONS))],
            vol.Optional("preview"): bool,
            **common,
        },
        "alert_rule_set": {
            vol.Required("expected_revision"): whole,
            vol.Required("rule"): dict,
            **common,
        },
        "alert_rule_delete": {
            vol.Required("id"): str,
            vol.Required("expected_revision"): whole,
            **common,
        },
        "alert_rule_test": {
            vol.Optional("id"): str,
            vol.Optional("rule"): dict,
            vol.Optional("hours", default=24): hours,
            vol.Optional("send", default=False): bool,
        },
        "alert_rule_preview": {
            vol.Required("rule"): dict,
            vol.Optional("hours", default=24): hours,
        },
        "alert_rule_list": {vol.Optional("room_id"): str},
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            wrap(
                handle,
                error_of={
                    "preset_apply": _rows_refused,
                    "copy_config": _rows_refused,
                    "alert_rule_test": _not_delivered,
                },
            ),
            schema=vol.Schema(fields(schemas[service])),
            supports_response=(
                SupportsResponse.ONLY if service in READS else SupportsResponse.OPTIONAL
            ),
        )


async def async_unload_site(hass, entry) -> None:
    """The site store goes with the last room: its services and its sensor."""
    data = hass.data.get(DOMAIN, {})
    entries = data.get("_site_entries", set())
    entries.discard(entry.entry_id)
    site = data["_site"] if entries else data.pop("_site", None)
    if site is None:
        return
    if entries:
        site.publish(skip=entry.entry_id)
        site.alerts.refresh()
        return
    site.alerts.stop()
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
    hass.states.async_remove(SENSOR)
