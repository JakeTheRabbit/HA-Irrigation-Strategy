"""Timer programs (G7): each room's store of watering timers, its services and timers_config.

One store per room (crop_steering.timers.<entry_id>, {revision, programs, skips}), published as
sensor.crop_steering_<prefix>timers_config: its state is the revision, its attributes the active
programs and the skips still in force. The controller app runs the programs for the zones whose
"Watering by" select reads timer; nothing here switches, presses or sets any hardware.

A program is checked and projected only through generated/timers.py (the engine's own code), a
zone belongs to one active program at most, a delete is soft (active false, deleted_at) and a skip
covers one planned shot of a zone for 15 minutes from its time and is pruned 24 h after it. Every
save journals config.changed {store: "timers", section, old, new, diff}.

A room with no store publishes no programs. A store that cannot be read publishes unavailable (the
controller then keeps what it last knew) and is never saved over.
"""

from __future__ import annotations

import asyncio
import logging
import math
from copy import deepcopy
from datetime import datetime, timedelta

from .admin import async_require_admin
from .const import DOMAIN
from .generated import timers
from .generated.ids import new_id
from .journal_api import attribution, note
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = (
    "timer_program_set",
    "timer_program_delete",
    "timer_program_preview",
    "timer_program_list",
    "timer_skip",
)
READS = ("timer_program_preview", "timer_program_list")
# What a stored program keeps: what timers.validate reads, its name, and when it was made, changed
# and deleted. Anything else a caller sends (a listed program's next_at, say) is not stored.
FIELDS = (
    "id",
    "name",
    "type",
    "zones",
    "duration_s",
    "active",
    "window",
    "sync_time",
    "interval_min",
    "frequency_per_day",
    "start_at",
    "created_at",
    "updated_at",
    "deleted_at",
)
SKIP_LENGTH = timedelta(minutes=15)
SKIP_KEPT = timedelta(hours=24)
PREVIEW_HOURS = 24
MAX_PREVIEW_HOURS = 48
NEXT_WITHIN = timedelta(days=8)


def _now():
    from homeassistant.util import dt as dt_util

    return dt_util.now()


def _instant(value) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        raise ValueError(
            f"Time must be an ISO date and time such as 2026-10-22T08:00:00+13:00, got {value!r}"
        ) from None


def _stored_program(value) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise ValueError("a stored program has no id")
    program = timers.validate(value)
    return {key: program[key] for key in FIELDS if key in program}


def _stored_skip(value) -> dict | None:
    """A stored skip, or None (logged) for one that is not a zone with two times that carry an offset:
    a skip only ever covers one shot, so dropping a broken one never loses a program."""
    try:
        if not isinstance(value, dict) or type(value.get("zone")) is not int:
            raise ValueError("it has no zone")
        for key in ("at", "until"):
            if _instant(value.get(key)).tzinfo is None:
                raise ValueError(f"its {key} has no offset")
    except ValueError as error:
        _LOGGER.warning(
            "Crop Steering timers: stored skip %r dropped: %s", value, error
        )
        return None
    return dict(value)


def load(value) -> dict:
    """A stored document, or ValueError when any of it cannot be read (it is then never saved over)."""
    if not isinstance(value, dict) or type(value.get("revision")) is not int:
        raise ValueError("Invalid stored revision")
    programs, skips = value.get("programs", []), value.get("skips", [])
    if not isinstance(programs, list) or not isinstance(skips, list):
        raise ValueError("programs and skips must be lists")
    return {
        "revision": max(value["revision"], 0),
        "programs": [_stored_program(p) for p in programs],
        "skips": [s for s in map(_stored_skip, skips) if s is not None],
    }


def _shown(program) -> bool:
    return program["active"] and not program.get("deleted_at")


class TimerPrograms:
    def __init__(self, hass, entry, store=None, now=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self.sensor = f"sensor.{DOMAIN}_{self.prefix}timers_config"
        self._store = store
        self._now = now or _now
        self._lock = asyncio.Lock()
        self.document = {"revision": 0, "programs": [], "skips": []}
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.timers.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                self.document = load(value)
        except Exception as error:
            self.error = (
                "The stored timer programs could not be read; they have not been "
                f"overwritten: {error}"
            )
            _LOGGER.error("Crop Steering timers %s: %s", self.room_id, self.error)

    # ------------------------------------------------------------------ reading
    def _config(self) -> dict:
        return {**(self.entry.data or {}), **(self.entry.options or {})}

    def lights(self) -> tuple[float, float]:
        """The room's lights-on and lights-off hours: its numbers, else what setup saved."""
        config, out = self._config(), []
        for key, default in (("lights_on_hour", 12), ("lights_off_hour", 0)):
            state = self.hass.states.get(f"number.{DOMAIN}_{self.prefix}{key}")
            try:
                hour = float(state.state)
                if not (math.isfinite(hour) and 0 <= hour < 24):
                    raise ValueError
            except (AttributeError, TypeError, ValueError):
                hour = float(config.get(key, default))
            out.append(hour)
        return out[0], out[1]

    def _project(self, program, hours) -> list[dict]:
        start = self._now()
        return [
            {
                "zone": shot.zone,
                "at": shot.at.isoformat(),
                "duration_s": shot.duration_s,
            }
            for shot in timers.project(
                program, self.lights(), start, start + timedelta(hours=hours)
            )
        ]

    def _skips_in_force(self) -> list[dict]:
        now = self._now()
        return [
            s for s in self.document["skips"] if _instant(s["at"]) + SKIP_KEPT > now
        ]

    def programs(self) -> list[dict]:
        return [
            deepcopy(p) for p in self.document["programs"] if not p.get("deleted_at")
        ]

    def listed(self) -> list[dict]:
        """The room's programs as timer_program_list shows them."""
        out = []
        for program in self.programs():
            start, error = self._now(), None
            try:
                shots = timers.project(
                    program, self.lights(), start, start + NEXT_WITHIN
                )
            except Exception as failed:  # named on this program; the others still list
                shots, error = [], f"Its next shot could not be worked out: {failed}"
                _LOGGER.warning(
                    "Crop Steering timers %s: %s %s", self.room_id, program["id"], error
                )
            out.append(
                {
                    **program,
                    "room_id": self.room_id,
                    "next_at": shots[0].at.isoformat() if shots else None,
                    "error": error,
                    "zones_in_timer_mode": [
                        zone
                        for zone in program["zones"]
                        if getattr(
                            self.hass.states.get(
                                f"select.{DOMAIN}_{self.prefix}zone_{zone}_irrigation_mode"
                            ),
                            "state",
                            None,
                        )
                        == "timer"
                    ],
                }
            )
        return out

    def preview(self, program, hours=PREVIEW_HOURS) -> dict:
        if (
            type(hours) not in (int, float)
            or not math.isfinite(hours)
            or not 1 <= hours <= MAX_PREVIEW_HOURS
        ):
            raise ValueError(f"hours must be from 1 to {MAX_PREVIEW_HOURS}")
        if not isinstance(program, dict):
            raise ValueError("program must be an object")
        checked = self._check(program)
        shots = self._project(checked, hours)
        return {
            "preview": shots,
            "shots": len(shots),
            "total_s": sum(s["duration_s"] for s in shots),
        }

    def publish(self):
        """sensor.crop_steering_<prefix>timers_config: the revision, the active programs and the
        skips in force; unavailable while the store cannot be read."""
        if self.error:
            self.hass.states.async_set(
                self.sensor, "unavailable", {"error": self.error}
            )
            return
        revision = self.document["revision"]
        self.hass.states.async_set(
            self.sensor,
            str(revision),
            {
                "friendly_name": "Crop Steering timer programs",
                "room_id": self.room_id,
                "revision": revision,
                "programs": [
                    deepcopy(p) for p in self.document["programs"] if _shown(p)
                ],
                "skips": [
                    {key: s[key] for key in ("zone", "at", "until")}
                    for s in self._skips_in_force()
                ],
            },
        )

    # ------------------------------------------------------------------ checking
    def _zone(self, zone) -> int:
        count = int(self._config().get("num_zones", 1))
        if type(zone) is not int or not 1 <= zone <= count:
            raise ValueError(f"Zone {zone} is not in this room")
        return zone

    def _check(self, program) -> dict:
        """The program as it would be stored (validated with the room's lights), or ValueError."""
        checked = timers.validate(program, self.lights())
        for zone in checked["zones"]:
            self._zone(zone)
        out = {key: checked[key] for key in FIELDS if key in checked}
        out["name"] = str(program.get("name") or "").strip() or "Timer"
        return out

    @staticmethod
    def _refuse_shared_zones(programs):
        """A zone in two active programs: 'Zone 3 is already in timer <the earlier one>'."""
        owner = {}
        for program in programs:
            if not _shown(program):
                continue
            for zone in program["zones"]:
                if zone in owner:
                    raise ValueError(
                        f"Zone {zone} is already in timer '{owner[zone]['name']}'"
                    )
                owner[zone] = program

    # ------------------------------------------------------------------ writing
    async def _save(self, expected_revision, section, change, who):
        """Change a copy of the document with `change` (-> its result), save it, publish, journal."""
        from .setup_api import setup_diff

        async with self._lock:
            if self.error:
                raise ValueError(self.error)
            if expected_revision != self.document["revision"]:
                raise ValueError(
                    "Timer programs changed elsewhere. Reload before saving."
                )
            document = deepcopy(self.document)
            result = change(document)
            now = self._now()
            document["skips"] = [
                s for s in document["skips"] if _instant(s["at"]) + SKIP_KEPT > now
            ]
            document["revision"] += 1
            key = "programs" if section == "programs" else "skips"
            old, new = deepcopy(self.document[key]), deepcopy(document[key])
            await self._store.async_save(deepcopy(document))
            self.document = document
            self.publish()
            self._journal(section, old, new, setup_diff(old, new), who)
            return result, document["revision"]

    def _journal(self, section, old, new, diff, who):
        """Never fails or delays the save."""
        try:
            who = who or {}
            note(
                self.hass,
                self.room_id,
                "config.changed",
                actor=who.get("actor", "system"),
                user_id=who.get("user_id"),
                client=who.get("client"),
                data={
                    "store": "timers",
                    "section": section,
                    "old": old,
                    "new": new,
                    "diff": diff,
                },
            )
        except Exception as error:
            _LOGGER.debug("Timer change not journaled: %s", error)

    def _put(self, programs, program, stamp) -> dict:
        """`program` checked and written into `programs` (a new one gets an id), or ValueError."""
        checked = self._check(program)
        pid = program.get("id")
        found = next(
            (
                i
                for i, p in enumerate(programs)
                if p["id"] == pid and not p.get("deleted_at")
            ),
            None,
        )
        if pid is not None and found is None:
            raise ValueError(f"No timer program {pid} in this room")
        if found is None:
            checked.update(id=new_id(), created_at=stamp, updated_at=stamp)
            checked.pop("deleted_at", None)
            programs.append(checked)
        else:
            checked.update(
                id=pid, created_at=programs[found].get("created_at"), updated_at=stamp
            )
            checked.pop("deleted_at", None)
            programs[found] = checked
        return checked

    async def set_program(self, expected_revision, program, who=None) -> dict:
        if not isinstance(program, dict):
            raise ValueError("program must be an object")

        def change(document):
            programs = document["programs"]
            checked = self._put(programs, program, self._now().isoformat())
            # the program being saved last, so the message names the program that has the zone
            self._refuse_shared_zones(
                [*(p for p in programs if p is not checked), checked]
            )
            return checked

        checked, revision = await self._save(expected_revision, "programs", change, who)
        return {
            "program": deepcopy(checked),
            "revision": revision,
            "preview": self._project(checked, PREVIEW_HOURS),
        }

    async def set_programs(self, expected_revision, programs, who=None) -> dict:
        """Replace the room's programs with `programs` (Task 22's presets). One left out is
        soft-deleted."""
        if not isinstance(programs, list) or not all(
            isinstance(p, dict) for p in programs
        ):
            raise ValueError("programs must be a list of objects")

        def change(document):
            stored, stamp = document["programs"], self._now().isoformat()
            kept = []
            for program in programs:
                kept.append(self._put(stored, program, stamp)["id"])
            for program in stored:
                if program["id"] not in kept and not program.get("deleted_at"):
                    program.update(active=False, deleted_at=stamp, updated_at=stamp)
            self._refuse_shared_zones(stored)
            return [deepcopy(p) for p in stored if not p.get("deleted_at")]

        result, revision = await self._save(expected_revision, "programs", change, who)
        return {"programs": result, "revision": revision}

    async def delete_program(self, expected_revision, pid, who=None) -> dict:
        def change(document):
            for program in document["programs"]:
                if program["id"] == pid and not program.get("deleted_at"):
                    stamp = self._now().isoformat()
                    program.update(active=False, deleted_at=stamp, updated_at=stamp)
                    return deepcopy(program)
            raise ValueError(f"No timer program {pid} in this room")

        program, revision = await self._save(expected_revision, "programs", change, who)
        return {"program": program, "revision": revision}

    async def skip(self, expected_revision, zone, at, who=None) -> dict:
        self._zone(zone)
        when = _instant(at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=self._now().tzinfo)
        if when + SKIP_KEPT <= self._now():
            raise ValueError("That time is more than 24 h ago")
        if when > self._now() + timedelta(hours=MAX_PREVIEW_HOURS):
            raise ValueError(f"That time is more than {MAX_PREVIEW_HOURS} h ahead")
        who = who or {}
        skip = {
            "zone": zone,
            "at": when.isoformat(),
            "until": (when + SKIP_LENGTH).isoformat(),
        }

        def change(document):
            document["skips"] = [
                s
                for s in document["skips"]
                if not (s["zone"] == zone and _instant(s["at"]) == when)
            ]
            document["skips"].append(
                {
                    **skip,
                    "by": {"actor": who.get("actor"), "user_id": who.get("user_id")},
                }
            )
            return dict(skip)

        result, revision = await self._save(expected_revision, "skip", change, who)
        return {"skip": result, "revision": revision}


# ---------------------------------------------------------------------- rooms and services
def _rooms(hass) -> dict:
    return hass.data.get(DOMAIN, {}).get("_timers", {})


def resolve(hass, room_id) -> TimerPrograms:
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [room for room in _rooms(hass).values() if room.room_id == room_id]
    if len(matches) != 1:
        raise ValueError("Room is unknown or ambiguous")
    return matches[0]


def list_programs(hass, room_id=None) -> dict:
    """One room's programs and revision, or (no room_id) every room's, each program with its room_id."""
    if room_id is not None:
        room = resolve(hass, room_id)
        return {
            "programs": room.listed(),
            "revision": room.document["revision"],
            "error": room.error,
        }
    rooms = sorted(_rooms(hass).values(), key=lambda r: r.room_id)
    return {
        "programs": [p for room in rooms for p in room.listed()],
        "revision": None,
        "revisions": {room.room_id: room.document["revision"] for room in rooms},
        "errors": {room.room_id: room.error for room in rooms if room.error},
    }


def get_programs(hass, entry_id) -> list[dict]:
    """The room's programs that are not deleted (Task 22)."""
    return _rooms(hass)[entry_id].programs()


async def set_programs(
    hass, entry_id, programs: list[dict], expected_revision: int, actor: dict
) -> dict:
    """Replace the room's programs (Task 22). `actor`: {actor, user_id, client} for the journal."""
    return await _rooms(hass)[entry_id].set_programs(expected_revision, programs, actor)


async def async_setup_timers(hass, entry) -> None:
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    room = TimerPrograms(hass, entry)
    await room.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_timers", {})[entry.entry_id] = room
    room.publish()

    async def handle(call):
        data = call.data
        try:
            if call.service == "timer_program_list":
                return list_programs(hass, data.get("room_id"))
            target = resolve(hass, data["room_id"])
            if call.service == "timer_program_preview":
                return target.preview(data["program"], data.get("hours", PREVIEW_HOURS))
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
            who = attribution(hass, call)
            revision = data["expected_revision"]
            if call.service == "timer_program_set":
                return await target.set_program(revision, data["program"], who)
            if call.service == "timer_program_delete":
                return await target.delete_program(revision, data["id"], who)
            return await target.skip(revision, data["zone"], data["at"], who)
        except (ValueError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    room_id = vol.Required("room_id")
    revision = vol.Required("expected_revision")
    whole = vol.All(int, vol.Range(min=0))
    common = {
        vol.Optional("client"): vol.In(["mcp", "aigrow"]),
        vol.Optional("proposal_token"): str,
    }
    schemas = {
        "timer_program_set": {
            room_id: str,
            revision: whole,
            vol.Required("program"): dict,
            **common,
        },
        "timer_program_delete": {
            room_id: str,
            revision: whole,
            vol.Required("id"): str,
            **common,
        },
        "timer_program_preview": {
            room_id: str,
            vol.Required("program"): dict,
            vol.Optional("hours"): vol.All(
                vol.Coerce(float),
                vol.Range(min=1, max=MAX_PREVIEW_HOURS),
            ),
        },
        "timer_program_list": {vol.Optional("room_id"): str},
        "timer_skip": {
            room_id: str,
            revision: whole,
            vol.Required("zone"): vol.All(int, vol.Range(min=1)),
            vol.Required("at"): str,
            **common,
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
            supports_response=(
                SupportsResponse.ONLY if service in READS else SupportsResponse.OPTIONAL
            ),
        )


async def async_unload_timers(hass, entry) -> None:
    rooms = _rooms(hass)
    room = rooms.pop(entry.entry_id, None)
    if room is not None:
        hass.states.async_remove(room.sensor)
    if not rooms:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
