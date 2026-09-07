"""Durable room-local strategy authoring and explicitly armed daily activation.

The integration publishes one coherent parameter snapshot. The controller opts
into that versioned snapshot; no recipe service or individual number is changed.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
from datetime import date, datetime, time, timedelta, timezone

from .const import DOMAIN
from .room import room_prefix
from .strategy_model import (
    ENGINE_BOUNDS,
    MODE_KEYS,
    PARAMETERS,
    REQUIRED_PARAMETERS,
    SCHEMA_VERSION,
    hydraulic_preview,
    normalize_plan,
    preview_zone,
)

_LOGGER = logging.getLogger(__name__)


def _now():
    try:
        from homeassistant.util import dt as dt_util

        return dt_util.now()
    except ImportError:
        return datetime.now(timezone.utc)


def _number(state):
    try:
        value = float(state.state)
        return value if math.isfinite(value) else None
    except (AttributeError, TypeError, ValueError):
        return None


def _age(state, now):
    try:
        updated = state.last_updated
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        return (now - updated).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return float("inf")


class StrategyManager:
    """Per-entry persistent document, coherent snapshots and guarded scheduler."""

    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = f"room:{self.prefix}"
        self.entity_id = f"sensor.{DOMAIN}_{self.prefix}strategy_plan"
        self._store = store
        self._lock = asyncio.Lock()
        self._unsubscribe = None
        self.document = self._fresh_document()

    def _fresh_document(self):
        return {
            "storage_version": 1,
            "revision": 0,
            "status": "draft",
            "plan": None,
            "active": {"grow_day": None, "zones": []},
            "error": None,
            "armed_after": None,
            "disarm_after": None,
            "release_legacy": False,
        }

    def _config(self):
        return self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})

    def zone_ids(self):
        config = self._config()
        zones = config.get("zones") or {}
        return [
            z
            for z in range(1, int(config.get("num_zones", 1)) + 1)
            if (zones.get(str(z), zones.get(z, {})) or {}).get("active", True)
        ]

    def _state(self, suffix, domain="sensor"):
        return self.hass.states.get(f"{domain}.{DOMAIN}_{self.prefix}{suffix}")

    def _native_number(self, zone, key):
        for suffix in (f"zone_{zone}_{key}", key):
            state = self._state(suffix, "number")
            if _number(state) is not None:
                return state
        return None

    def catalog(self):
        result = {}
        for zone in self.zone_ids():
            mode = self._state(f"zone_{zone}_steering_mode", "select") or self._state(
                "steering_mode", "select"
            )
            gen = getattr(mode, "state", "").lower().startswith("gen")
            row = {}
            for key in PARAMETERS:
                native_keys = MODE_KEYS.get(key, (key,))
                states = [self._native_number(zone, native) for native in native_keys]
                readable = [state for state in states if state is not None]
                if not readable:
                    continue
                try:
                    minimum = max(float(state.attributes["min"]) for state in readable)
                    maximum = min(float(state.attributes["max"]) for state in readable)
                    minimum = max(minimum, ENGINE_BOUNDS[key][0])
                    maximum = min(maximum, ENGINE_BOUNDS[key][1])
                    step = max(float(state.attributes["step"]) for state in readable)
                    if (
                        not all(math.isfinite(v) for v in (minimum, maximum, step))
                        or minimum > maximum
                        or step <= 0
                    ):
                        continue
                except (KeyError, TypeError, ValueError):
                    continue
                selected = states[1 if gen and len(states) > 1 else 0]
                row[key] = {
                    "value": _number(selected),
                    "min": minimum,
                    "max": maximum,
                    "step": step,
                    "unit": (
                        "% of peak"
                        if key == "dryback_target"
                        else readable[0].attributes.get("unit_of_measurement", "")
                    ),
                    "entity_ids": [state.entity_id for state in readable],
                }
            result[zone] = row
        return result

    def _seed_plan(self, now):
        profiles, zones = [], []
        catalog = self.catalog()
        for zone in self.zone_ids():
            values = {
                key: field["value"]
                for key, field in catalog.get(zone, {}).items()
                if field["value"] is not None
            }
            if not set(REQUIRED_PARAMETERS) <= set(values):
                values = {}  # Never invent grower endpoints from missing configuration.
            pid = f"zone-{zone}-current"
            profiles.append(
                {
                    "id": pid,
                    "name": f"Zone {zone} current values — configure endpoints",
                    "vegetative": dict(values),
                    "generative": dict(values),
                }
            )
            zones.append(
                {
                    "zone_id": zone,
                    "start_date": now.date().isoformat(),
                    "schedule": [
                        {"start_day": 1, "end_day": 84, "profile_id": pid, "bias": 50}
                    ],
                }
            )
        return {"schema_version": SCHEMA_VERSION, "profiles": profiles, "zones": zones}

    async def async_init(self):
        if self._store is None:
            try:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}_strategy_{self.entry.entry_id}"
                )
            except ImportError:
                pass
        try:
            loaded = await self._store.async_load() if self._store else None
            if loaded:
                if not isinstance(loaded, dict) or loaded.get("storage_version") != 1:
                    raise ValueError("Unsupported or corrupt strategy storage")
                self.document.update(copy.deepcopy(loaded))
                if self.document["status"] not in (
                    "draft",
                    "armed",
                    "active",
                    "disarming",
                    "error",
                ):
                    raise ValueError("Invalid stored strategy status")
                if (
                    type(self.document["revision"]) is not int
                    or self.document["revision"] < 0
                    or not isinstance(self.document["active"], dict)
                    or not isinstance(self.document["active"].get("zones"), list)
                    or (
                        self.document["plan"] is not None
                        and not isinstance(self.document["plan"], dict)
                    )
                ):
                    raise ValueError("Malformed stored strategy document")
                for field in ("armed_after", "disarm_after"):
                    if self.document.get(field):
                        datetime.fromisoformat(self.document[field])
                if self.document["status"] == "disarming" and not self.document.get(
                    "disarm_after"
                ):
                    self.document["disarm_after"] = (
                        self._boundary(_now()) + timedelta(days=1)
                    ).isoformat()
        except Exception as error:
            self.document = self._fresh_document()
            self.document["status"] = "error"
            self.document["error"] = str(error)
        if self.document["plan"] is None:
            self.document["plan"] = self._seed_plan(_now())
        if self.document["status"] in ("active", "disarming"):
            try:
                if (
                    self.document["active"].get("grow_day")
                    != self._boundary(_now()).date().isoformat()
                ):
                    raise ValueError(
                        "Lights-on boundary was missed; schedule held until the next boundary"
                    )
            except ValueError as error:
                self.document["status"] = "error"
                self.document["error"] = str(error)
        self._publish(_now())
        return self

    def controller_supported(self, now):
        heartbeat = self._state("ai_heartbeat")
        return bool(
            heartbeat
            and heartbeat.attributes.get("strategy_snapshot_version") == 1
            and -60 <= _age(heartbeat, now) <= 180
        )

    def response(self, now=None):
        now = now or _now()
        return {
            "room_id": self.room_id,
            "revision": self.document["revision"],
            "status": self.document["status"],
            "plan": copy.deepcopy(self.document["plan"]),
            "active": copy.deepcopy(self.document["active"]),
            "error": self.document["error"],
            "capabilities": {
                "strategy_snapshot_version": 1,
                "controller_supported": self.controller_supported(now),
            },
            "catalog": self.catalog(),
            "armed_after": self.document.get("armed_after"),
            "disarm_after": self.document.get("disarm_after"),
            "disarm_policy": "Return to legacy setpoints at the next lights-on boundary; no hardware flag is enabled.",
        }

    def _sizing(self, zone):
        fields = {
            "substrate_l_per_plant": "substrate_volume",
            "plant_count": "plant_count",
            "drippers_per_plant": "drippers_per_plant",
            "dripper_flow_lph": "dripper_flow_rate",
        }
        values = {
            name: _number(self._native_number(zone, key))
            for name, key in fields.items()
        }
        values["max_shot_duration"] = _number(
            self._state("max_shot_duration", "number")
        )
        return values

    def preview(self, plan=None, grow_day=None):
        catalog = self.catalog()
        plan = normalize_plan(plan or self.document["plan"], self.zone_ids(), catalog)
        day = grow_day or _now().date().isoformat()
        date.fromisoformat(day)
        zones = []
        for assignment in plan["zones"]:
            row = preview_zone(
                plan, assignment["zone_id"], day, catalog.get(assignment["zone_id"])
            )
            row["errors"] = []
            try:
                row["hydraulics"] = hydraulic_preview(
                    self._sizing(row["zone_id"]), row["parameters"]
                )
            except ValueError as error:
                row["hydraulics"] = None
                row["errors"].append(str(error))
            zones.append(row)
        return {"date": day, "zones": zones}

    async def _persist(self):
        if self._store is None:
            raise RuntimeError("Strategy storage is unavailable")
        await self._store.async_save(copy.deepcopy(self.document))

    async def save(self, plan, expected_revision):
        async with self._lock:
            if expected_revision != self.document["revision"]:
                raise ValueError("Strategy revision changed; reload before saving")
            if self.document["status"] != "draft":
                raise ValueError(
                    "Disarm the strategy and wait for the next boundary before replacing it"
                )
            normalized = normalize_plan(plan, self.zone_ids(), self.catalog())
            prior = copy.deepcopy(self.document)
            self.document.update(
                plan=normalized,
                revision=prior["revision"] + 1,
                error=None,
                release_legacy=False,
            )
            try:
                await self._persist()
            except Exception:
                self.document = prior
                raise
            self._publish(_now())
            return self.response()

    def _boundary(self, now):
        hour = _number(self._state("lights_on_hour", "number"))
        if hour is None or not 0 <= hour < 24:
            raise ValueError("Readable room lights_on_hour is required")
        seconds = int(hour * 3600)
        boundary = datetime.combine(now.date(), time(), tzinfo=now.tzinfo) + timedelta(
            seconds=seconds
        )
        if now < boundary:
            boundary -= timedelta(days=1)
        return boundary

    def _readiness(self, now, zone_ids):
        if not self.controller_supported(now):
            raise ValueError(
                "A fresh controller heartbeat with strategy_snapshot_version=1 is required"
            )
        heartbeat = self._state("ai_heartbeat")
        flag = heartbeat.attributes.get("enable_flag")
        flag_state = self.hass.states.get(flag) if isinstance(flag, str) else None
        if getattr(flag_state, "state", None) not in ("on", "off"):
            raise ValueError("The current room engine flag is unreadable")
        for zone in zone_ids:
            enabled = self._state(f"zone_{zone}_enabled", "switch")
            if getattr(enabled, "state", None) not in ("on", "off"):
                raise ValueError(f"Zone {zone} enable configuration is unreadable")
            for metric in ("vwc", "ec"):
                state = self._state(f"{metric}_zone_{zone}") or self._state(
                    f"zone_{zone}_{metric}"
                )
                if _number(state) is None or not -60 <= _age(state, now) <= 1200:
                    raise ValueError(
                        f"Zone {zone} {metric.upper()} is unavailable or stale"
                    )

    async def activate(self, expected_revision, now=None):
        now = now or _now()
        async with self._lock:
            if expected_revision != self.document["revision"]:
                raise ValueError("Strategy revision changed; reload before activating")
            if self.document["status"] != "draft":
                raise ValueError("Only a saved draft can be armed")
            preview = self.preview()
            self._readiness(now, [row["zone_id"] for row in preview["zones"]])
            if any(row["errors"] for row in preview["zones"]):
                raise ValueError(
                    "Resolve hydraulic configuration errors before activation"
                )
            prior = copy.deepcopy(self.document)
            self.document.update(
                status="armed",
                error=None,
                release_legacy=False,
                armed_after=(self._boundary(now) + timedelta(days=1)).isoformat(),
            )
            try:
                await self._persist()
            except Exception:
                self.document = prior
                raise
            self._publish(now)
            return self.response(now)

    async def disarm(self, now=None):
        now = now or _now()
        async with self._lock:
            prior = copy.deepcopy(self.document)
            if self.document["active"]["zones"] or self.document["status"] == "error":
                self.document.update(
                    status="disarming",
                    error=None,
                    disarm_after=self.document.get("disarm_after")
                    or (self._boundary(now) + timedelta(days=1)).isoformat(),
                )
            else:
                self.document.update(
                    status="draft",
                    armed_after=None,
                    disarm_after=None,
                    error=None,
                    release_legacy=True,
                )
            try:
                await self._persist()
            except Exception:
                self.document = prior
                raise
            self._publish(now)
            return self.response(now)

    async def tick(self, now=None):
        now = now or _now()
        async with self._lock:
            status = self.document["status"]
            if status == "draft":
                self._publish(now)
                return
            try:
                boundary = self._boundary(now)
                day = boundary.date().isoformat()
                near_boundary = 0 <= (now - boundary).total_seconds() <= 120
                if self.document.get("disarm_after"):
                    target = datetime.fromisoformat(self.document["disarm_after"])
                    if near_boundary and now >= target:
                        self.document.update(
                            status="draft",
                            active={"grow_day": None, "zones": []},
                            armed_after=None,
                            disarm_after=None,
                            error=None,
                            release_legacy=True,
                        )
                        await self._persist()
                    elif self.document["active"].get("grow_day") != day:
                        self.document.update(
                            status="error",
                            error="Disarm boundary was missed; holding until the next boundary",
                        )
                        await self._persist()
                elif status in ("armed", "active", "error"):
                    assigned = {
                        zone["zone_id"]
                        for zone in self.document["plan"].get("zones", [])
                    }
                    if (
                        assigned != set(self.zone_ids())
                        or self._config().get("active", True) is False
                    ):
                        raise ValueError(
                            "Strategy zones do not match room setup; disarm and reconcile the draft"
                        )
                    armed_after = self.document.get("armed_after")
                    # An error/reload must never invent an activation that was
                    # not explicitly armed and successfully stored by the user.
                    eligible = bool(armed_after) and now >= datetime.fromisoformat(
                        armed_after
                    )
                    if (
                        near_boundary
                        and eligible
                        and self.document["active"]["grow_day"] != day
                    ):
                        preview = self.preview(grow_day=day)
                        self._readiness(
                            now, [row["zone_id"] for row in preview["zones"]]
                        )
                        if any(row["errors"] for row in preview["zones"]):
                            raise ValueError(
                                "Hydraulic preview failed; scheduled activation held"
                            )
                        self.document.update(
                            status="active",
                            active={"grow_day": day, "zones": preview["zones"]},
                            error=None,
                        )
                        await self._persist()
                    elif (
                        status == "active"
                        and self.document["active"]["grow_day"] != day
                    ):
                        raise ValueError(
                            "Lights-on boundary was missed; schedule held until the next boundary"
                        )
            except Exception as error:
                self.document["error"] = str(error)
                self.document["status"] = "error"
                await self._persist()
            self._publish(now)

    def _publish(self, now):
        status = self.document["status"]
        active = self.document["active"]
        enabled = bool(active["zones"]) or status in ("active", "disarming", "error")
        attributes = {
            "friendly_name": "Grow strategy plan",
            "room_id": self.room_id,
            "snapshot_version": 1,
            "revision": self.document["revision"],
            "enabled": enabled,
            "release_legacy": self.document.get("release_legacy", False),
            "updated_at": now.isoformat(),
            "valid_until": (now + timedelta(seconds=180)).isoformat(),
            "grow_day": active["grow_day"],
            "zones": copy.deepcopy(active["zones"]),
            "managed_zone_ids": [
                zone["zone_id"]
                for zone in (self.document.get("plan") or {}).get("zones", [])
            ],
            "error": self.document["error"],
            "status": status,
        }
        self.hass.states.async_set(self.entity_id, status, attributes)


async def async_setup_strategy(hass, entry):
    """Lifecycle hook called after number/select platforms are loaded."""
    manager = await StrategyManager(hass, entry).async_init()
    hass.data[DOMAIN].setdefault("_strategy", {})[entry.entry_id] = manager
    from homeassistant.helpers.event import async_track_time_interval

    async def local_tick(_utc_event_time):
        # HA time-interval callbacks carry UTC. Photoperiod hours are HA-local.
        await manager.tick()

    manager._unsubscribe = async_track_time_interval(
        hass, local_tick, timedelta(seconds=60)
    )
    from .strategy_api import async_setup_strategy_services

    await async_setup_strategy_services(hass)


async def async_unload_strategy(hass, entry):
    manager = hass.data.get(DOMAIN, {}).get("_strategy", {}).pop(entry.entry_id, None)
    if manager and manager._unsubscribe:
        manager._unsubscribe()
    if not hass.data.get(DOMAIN, {}).get("_strategy"):
        from .strategy_api import async_unload_strategy_services

        await async_unload_strategy_services(hass)
