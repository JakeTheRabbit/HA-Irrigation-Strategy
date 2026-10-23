"""The upgrade to 3.18: carry an existing room's settings into the new features without changing
how it waters (.superpowers/sdd/2026-10-22-parity-backend/migration-spec.md, docs/UPGRADING.md).

One ledger for the site (Store `crop_steering.migration`). Each step is `name:vN` and runs once per
room: a step that is done never runs again, a step that raised runs again at the next start. Every
step also checks its own target ("only when nothing is there yet"), so running it again after the
ledger is lost writes nothing. A room set up just now (`fresh`) gets every step marked `fresh` and
no report.

What a step may write (hard rules H1-H6 of the spec): a setting whose effect on watering and dosing
is "as before", display-only data, or stored rows that do nothing until someone turns them on. It
never enables a supply, a timer program, an alert rule or a calibration, and it never writes to an
old store (recipe, notify, calibration, dosing, setpoint log). Every value it writes is journaled as
`config.changed` with actor `system` and detail `migration:<step>` (the journal's actors are fixed)
and is listed in the room's Upgrade report. Whatever it cannot carry without guessing is listed under
"Needs you", with the page to open and the section of docs/UPGRADING.md to read.

The report is answered by `crop_steering.migration_report {room_id}` and raised as one Repairs card
per room (`upgrade_report_3_18`) while it lists something that needs the grower, until it is marked
as read.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timezone

from .const import DEFAULT_RECIPE, DOMAIN, RECIPE_STAGES
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}.migration"
RELEASE = "3.18.0"
ISSUE = "upgrade_report_3_18"
SIGNAL = f"{DOMAIN}_migration_changed"
DOC = "docs/UPGRADING.md"
DETAIL = "migration"
# The feed EC (mS/cm) controller 3.17.0 and before assumed when nothing measured or declared one.
LEGACY_FEED_EC = 3.0
PRESET_NAME_MAX = 60
SECTIONS = ("targets", "phase_timing", "water_limits")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty() -> dict:
    return {
        "schema_version": 1,
        "release": RELEASE,
        "site": {"steps": {}},
        "rooms": {},
        "acknowledged": {},
    }


def row(id_, title, status, detail, page, anchor) -> dict:
    return {
        "id": id_,
        "title": title,
        "status": status,
        "detail": detail,
        "page": page,
        "doc": f"{DOC}#{anchor}",
    }


def put(report: dict, item: dict) -> None:
    """Add a report row, replacing the row with the same id (in either list)."""
    for key in ("carried", "needs_you"):
        report[key] = [r for r in report[key] if r.get("id") != item["id"]]
    report["needs_you" if item["status"] == "needs_you" else "carried"].append(item)


# ---------------------------------------------------------------------- pure
def recipe_presets(
    recipe, room_name: str, room_id: str
) -> tuple[list[dict], list[str]]:
    """The presets an old recipe store carries: one per stage that differs from its default, with
    every key in a preset section. -> (preset rows without id or dates, keys no section holds).
    """
    from . import presets

    stages = (recipe or {}).get("stages") if isinstance(recipe, dict) else None
    if not isinstance(stages, dict):
        return [], []
    out, unmapped = [], []
    known = {key for section in SECTIONS for key in presets.SECTIONS[section]}
    for stage in RECIPE_STAGES:
        values = stages.get(stage)
        if not isinstance(values, dict) or not values:
            continue
        if values == DEFAULT_RECIPE["stages"].get(stage):
            continue
        unmapped += [k for k in values if k not in known and k not in unmapped]
        captured = presets.capture(values, SECTIONS)
        captured = {s: v for s, v in captured.items() if v}
        if not captured:
            continue
        suffix = f" – {stage} (from 3.17 recipe)"
        out.append(
            {
                "name": room_name[: PRESET_NAME_MAX - len(suffix)] + suffix,
                "scope": "all",
                "sections": list(captured),
                "from": {"room_id": room_id},
                "values": captured,
                "stage": stage,
            }
        )
    return out, unmapped


def published_fallback(ledger_room: dict | None, feed_ec_sensor) -> float | None:
    """The legacy feed EC the room's descriptor publishes: only while the ledger holds one and the room
    maps no feed EC probe."""
    if feed_ec_sensor or not isinstance(ledger_room, dict):
        return None
    value = ledger_room.get("legacy_feed_ec_fallback")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ---------------------------------------------------------------------- the ledger
class Ledger:
    def __init__(self, hass, store=None):
        self.hass = hass
        self._store = store
        self.lock = asyncio.Lock()
        self.document = empty()
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(self.hass, 1, STORAGE_KEY)
            value = await self._store.async_load()
            if isinstance(value, dict):
                self.document = {**empty(), **deepcopy(value)}
        except (
            Exception
        ) as error:  # the room still loads; nothing is migrated this start
            self.error = str(error)
            _LOGGER.error("Crop Steering upgrade ledger could not be loaded: %s", error)

    def room(self, entry_id: str) -> dict:
        room = self.document["rooms"].setdefault(entry_id, {})
        room.setdefault("steps", {})
        room.setdefault("report", {"carried": [], "needs_you": []})
        return room

    def report(self, entry_id: str) -> dict:
        room = self.document["rooms"].get(entry_id) or {}
        return deepcopy(room.get("report") or {"carried": [], "needs_you": []})

    async def save(self):
        await self._store.async_save(deepcopy(self.document))


def ledger_of(hass) -> Ledger | None:
    return hass.data.get(DOMAIN, {}).get("_migration")


def fallback_for(hass, entry) -> float | None:
    """What sensor.crop_steering_<prefix>engine_config publishes as `legacy_feed_ec_fallback`."""
    ledger = ledger_of(hass)
    if ledger is None:
        return None
    from .setup_api import effective

    hardware = effective(entry).get("hardware") or {}
    return published_fallback(
        ledger.document["rooms"].get(entry.entry_id), hardware.get("feed_ec_sensor")
    )


# ---------------------------------------------------------------------- the steps
def _journal(hass, entry, step, store, section, old, new):
    from .journal_api import note
    from .setup_api import setup_diff

    note(
        hass,
        "room:" + room_prefix(entry),
        "config.changed",
        actor="system",
        detail=f"{DETAIL}:{step}",
        data={
            "store": store,
            "section": section,
            "old": deepcopy(old),
            "new": deepcopy(new),
            "diff": setup_diff({section: old}, {section: new}),
            "step": step,
        },
    )


def _room_name(entry) -> str:
    from .setup_api import effective

    data = effective(entry)
    return str(data.get("room_name") or data.get("name") or entry.title or "Room")


def _zones(entry) -> list[int]:
    from .setup_api import effective

    data = effective(entry)
    return list(range(1, int(data.get("num_zones", 1) or 1) + 1))


async def step_supply(hass, entry, room) -> list[dict]:
    """M1: never saved (a saved supply makes rooms that share a pump take turns). The hardware found is
    listed for the grower."""
    from .setup_api import effective

    hardware = effective(entry).get("hardware") or {}
    pump, main = (
        hardware.get("pump_switch") or "",
        hardware.get("main_line_switch") or "",
    )
    if not pump and not main:
        return []
    shared = []
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id and pump:
            if (effective(other).get("hardware") or {}).get("pump_switch") == pump:
                shared.append(_room_name(other))
    found = " and ".join(
        part
        for part in (
            (
                f"pump {pump}"
                + (f" (also feeds {', '.join(shared)})" if shared else "")
                if pump
                else ""
            ),
            f"main line {main}" if main else "",
        )
        if part
    )
    return [
        row(
            "supply.pumps",
            "Irrigation supply",
            "needs_you",
            f"We found {found}. Enter its maximum flow, how many zones it may feed at once and any "
            "flow meter, then Save. Until you save, watering works as before.",
            "#/equipment/setup",
            "supply",
        )
    ]


async def step_irrigation_mode(hass, entry, room) -> list[dict]:
    """M3: a new zone select starts at steering, the controller's own default. Nothing is written: a
    select that reads unknown holds a mode this version cannot read (select.py), and is left for
    the grower."""
    prefix, zones = room_prefix(entry), _zones(entry)
    unknown = []
    for zone in zones:
        state = hass.states.get(f"select.{DOMAIN}_{prefix}zone_{zone}_irrigation_mode")
        if state is not None and state.state not in ("steering", "timer", "off"):
            unknown.append(zone)
    if unknown:
        return [
            row(
                "irrigation.mode",
                "Irrigation mode",
                "needs_you",
                f"Zone(s) {', '.join(map(str, unknown))} show no irrigation mode. Pick Steering to "
                "keep watering them as before.",
                "#/zones",
                "irrigation-mode",
            )
        ]
    return [
        row(
            "irrigation.mode",
            "Irrigation mode",
            "carried",
            f"Every zone waters by Steering, as before ({len(zones)} zones).",
            "#/zones",
            "irrigation-mode",
        )
    ]


def _site(hass):
    return hass.data.get(DOMAIN, {}).get("_site")


def _has_preset(site, room_id, detail) -> bool:
    """A preset this step made for the room, deleted ones included (a deleted one is never made again)."""
    return any(
        isinstance(p, dict)
        and (p.get("from") or {}).get("room_id") == room_id
        and (p.get("by") or {}).get("detail") == detail
        for p in site.document["presets"]
    )


async def _add_presets(hass, entry, step, rows):
    """Store presets made by the migration (never applied) and journal the one save."""
    from .generated.ids import new_id

    site = _site(hass)
    stamp = _now()
    detail = f"{DETAIL}:{step}"
    made = [
        {
            "id": new_id(),
            "name": r["name"],
            "scope": r["scope"],
            "sections": list(r["sections"]),
            "from": dict(r["from"]),
            "values": deepcopy(r["values"]),
            "created_at": stamp,
            "updated_at": stamp,
            "deleted_at": None,
            "by": {"actor": "system", "user_id": None, "detail": detail},
        }
        for r in rows
    ]

    def change(stored):
        stored.extend(deepcopy(made))
        return made

    await site._save_presets(
        site.document["presets_revision"],
        change,
        {"actor": "system", "detail": detail},
        "room:" + room_prefix(entry),
    )
    return made


async def step_recipe_presets(hass, entry, room) -> list[dict]:
    """M5: each edited stage of the room's old recipe store, copied as a preset. The recipe store is
    read, never changed."""
    site = _site(hass)
    if site is None or site.error:
        raise RuntimeError("the site store is not loaded")
    room_id = "room:" + room_prefix(entry)
    detail = f"{DETAIL}:recipe_presets"
    manager = hass.data.get(DOMAIN, {}).get("_recipe", {}).get(entry.entry_id)
    recipe = getattr(manager, "recipe", None)
    rows, unmapped = recipe_presets(recipe, _room_name(entry), room_id)
    out = []
    if unmapped:
        out.append(
            row(
                "presets.recipe_keys",
                "Recipe settings not copied",
                "needs_you",
                f"These recipe settings have no place in a preset: {', '.join(unmapped)}. Set them "
                "on the room's settings if you use them.",
                "#/plan/presets",
                "presets",
            )
        )
    if not rows or _has_preset(site, room_id, detail):
        return out
    await _add_presets(hass, entry, "recipe_presets", rows)
    stages = ", ".join(r["stage"] for r in rows)
    out.append(
        row(
            "presets.recipe",
            "Recipe stages",
            "carried",
            f"Your recipe stages {stages} were copied as presets. Nothing was applied.",
            "#/plan/presets",
            "presets",
        )
    )
    return out


async def step_snapshot_preset(hass, entry, room) -> list[dict]:
    """M6, once Home Assistant has started: a preset of the room's settings as they are now, a point
    to go back to. Skipped (needs you) when any of them cannot be read."""
    from . import presets

    site = _site(hass)
    if site is None or site.error:
        raise RuntimeError("the site store is not loaded")
    room_id = "room:" + room_prefix(entry)
    detail = f"{DETAIL}:snapshot_preset"
    if _has_preset(site, room_id, detail):
        return []
    sections = [*SECTIONS, "timers"]
    values, skipped = presets.read_source(hass, {"room_id": room_id}, sections)
    if skipped:
        return [
            row(
                "presets.snapshot",
                "Rollback preset",
                "needs_you",
                "Some settings could not be read at the update, so no preset of your settings was "
                "saved. Save one yourself under Presets before you change anything.",
                "#/plan/presets",
                "presets",
            )
        ]
    suffix = " – before 3.18 update"
    name = _room_name(entry)[: PRESET_NAME_MAX - len(suffix)] + suffix
    await _add_presets(
        hass,
        entry,
        "snapshot_preset",
        [
            {
                "name": name,
                "scope": "all",
                "sections": sections,
                "from": {"room_id": room_id},
                "values": values,
            }
        ],
    )
    return [
        row(
            "presets.snapshot",
            "Rollback preset",
            "carried",
            "A preset of your current settings was saved as a point to go back to. Nothing was applied.",
            "#/plan/presets",
            "presets",
        )
    ]


async def step_alerts(hass, entry, room) -> list[dict]:
    """M7: no alert rule is made."""
    return [
        row(
            "alerts.rules",
            "Alert rules",
            "needs_you",
            "No custom alert rules yet. Your pH and EC limits still stop watering as before.",
            "#/alerts/rules",
            "alerts",
        )
    ]


async def step_display_units(hass, entry, room) -> list[dict]:
    """M8: temperatures in °F when Home Assistant uses °F and the room has not chosen."""
    from homeassistant.const import UnitOfTemperature
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from .display import SIGNAL as DISPLAY_SIGNAL

    manager = hass.data.get(DOMAIN, {}).get("_display", {}).get(entry.entry_id)
    if manager is None or manager.error:
        raise RuntimeError("the display options are not loaded")
    imperial = hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
    out = [
        row(
            "units.ec",
            "EC unit",
            "needs_you",
            "EC is shown in mS/cm. If you work in ppm, pick the 500 or 700 scale.",
            "#/settings/display",
            "units",
        )
    ]
    if imperial:
        out.append(
            row(
                "units.clock",
                "Clock",
                "needs_you",
                "Times are shown on a 24-hour clock. Pick 12-hour if you prefer it.",
                "#/settings/display",
                "units",
            )
        )
    if not imperial or "temp_unit" in manager.document["options"]:
        return out
    async with manager._lock:
        old = deepcopy(manager.document)
        new = {
            "revision": old["revision"] + 1,
            "options": {**old["options"], "temp_unit": "F"},
        }
        await manager._store.async_save(deepcopy(new))
        manager.document = new
    async_dispatcher_send(hass, f"{DISPLAY_SIGNAL}_{entry.entry_id}")
    _journal(
        hass,
        entry,
        "display_units",
        "display",
        "options",
        old["options"],
        new["options"],
    )
    out.append(
        row(
            "units.temperature",
            "Temperature unit",
            "carried",
            "Temperatures are shown in °F, as Home Assistant uses.",
            "#/settings/display",
            "units",
        )
    )
    return out


async def step_notify(hass, entry, room) -> list[dict]:
    """M10: the recipients are kept as they are; quiet hours are new and off."""
    notifier = hass.data.get(DOMAIN, {}).get("_notify")
    rows = len(getattr(notifier, "data", {}).get("recipients") or []) if notifier else 0
    out = [
        row(
            "notify.quiet_hours",
            "Quiet hours",
            "needs_you",
            "Quiet hours are new and off for everyone.",
            "#/settings/notifications",
            "quiet-hours",
        )
    ]
    if rows:
        out.insert(
            0,
            row(
                "notify.recipients",
                "Notifications",
                "carried",
                f"{rows} notification recipient(s) kept as they were.",
                "#/settings/notifications",
                "quiet-hours",
            ),
        )
    return out


async def step_feed_calibration(hass, entry, room) -> list[dict]:
    """M11: an old calibration check is never applied; each mapped feed probe reads raw, as before."""
    from .setup_api import effective

    hardware = effective(entry).get("hardware") or {}
    out = []
    for key, what in (("feed_ph_sensor", "pH"), ("feed_ec_sensor", "EC")):
        probe = hardware.get(key)
        if probe:
            out.append(
                row(
                    f"calibration.feed_{what.lower()}",
                    f"Feed {what} probe",
                    "needs_you",
                    f"Feed {what} probe {probe} reads raw, as before. Run the 2-point calibration "
                    "to correct it.",
                    "#/equipment/calibration",
                    "feed-calibration",
                )
            )
    return out


async def step_dosing_pumps(hass, entry, room) -> list[dict]:
    """M13: the dosing store is read, never changed. A pH pump keeps its pH role; every other pump is
    listed for its solution and calibration."""
    manager = hass.data.get(DOMAIN, {}).get("_dosing", {}).get(entry.entry_id)
    if manager is None or manager.error:
        return []
    out = []
    ph = [p for p in manager.data["pumps"] if p.get("ph_role")]
    if ph:
        out.append(
            row(
                "dosing.ph_pumps",
                "pH pumps",
                "carried",
                f"{len(ph)} pH up/down pump(s) keep their pH role.",
                "#/dosing/pumps",
                "dosing-pumps",
            )
        )
    for pump in manager.data["pumps"]:
        if pump.get("ph_role") or pump.get("solution_type"):
            continue
        out.append(
            row(
                f"dosing.pump.{pump.get('id')}",
                f"Dosing pump {pump.get('name') or pump.get('id')}",
                "needs_you",
                f"Pump {pump.get('name') or pump.get('id')}: pick its solution and run a pump "
                "calibration. It still doses from its flow sensor until then.",
                "#/dosing/pumps",
                "dosing-pumps",
            )
        )
    return out


async def step_feed_ec_fallback(hass, entry, room) -> list[dict]:
    """M15: a room with no feed EC probe and no recipe feed EC keeps the 3.0 mS/cm controller 3.17.0
    assumed, so its EC flushes and holds work as before."""
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from .setup_api import effective

    hardware = effective(entry).get("hardware") or {}
    if hardware.get("feed_ec_sensor"):
        return []
    dosing = hass.states.get(f"sensor.{DOMAIN}_{room_prefix(entry)}dosing_config")
    feed = (getattr(dosing, "attributes", None) or {}).get("feed")
    try:
        declared = float(feed.get("ec"))
    except (AttributeError, TypeError, ValueError):
        declared = None
    if declared is not None and 0.1 <= declared <= 10:
        return []
    if room.get("legacy_feed_ec_fallback") is None:
        room["legacy_feed_ec_fallback"] = LEGACY_FEED_EC
        _journal(
            hass,
            entry,
            "feed_ec_fallback",
            "migration",
            "legacy_feed_ec_fallback",
            None,
            LEGACY_FEED_EC,
        )
        async_dispatcher_send(hass, f"{SIGNAL}_{entry.entry_id}")
    return [
        row(
            "feed.ec_fallback",
            "Feed EC",
            "needs_you",
            "No feed EC probe: the old 3.0 mS/cm assumption is kept so flushing works as before. Map "
            "a feed EC probe or set a recipe feed EC.",
            "#/dosing/feed",
            "feed-ec-fallback",
        )
    ]


async def step_new_panels(hass, entry, room) -> list[dict]:
    """M17 and M19: dashboards and the new panels are made by the grower, never adopted."""
    return [
        row(
            "panels.new",
            "New panels and dashboards",
            "needs_you",
            "Camera, CO2 and light-level panels are new: map them in Setup. New dashboards can be "
            "made from Settings.",
            "#/equipment/setup",
            "new-panels",
        )
    ]


async def step_retired_entities(hass, entry, room) -> list[dict]:
    """M20, once Home Assistant has started: the retired entities an automation or script still uses
    (deprecation.py raises the card; it is pointed at here)."""
    from homeassistant.helpers import issue_registry as ir

    from .deprecation import ISSUE as RETIRED, check_in_use
    from .health import _iid

    check_in_use(hass, entry)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, _iid(RETIRED, entry.data.get("room_slug", "default"))
    )
    if issue is None:
        return []
    return [
        row(
            "entities.retired",
            "Retired entities in use",
            "needs_you",
            "An automation or script uses an entity that is retired. Settings > Repairs names each one.",
            "#/settings/system",
            "retired-entities",
        )
    ]


# At setup, once the room's entities exist, then once Home Assistant has started.
SETUP_STEPS = (
    ("supply:v1", step_supply),
    ("irrigation_mode:v1", step_irrigation_mode),
    ("recipe_presets:v1", step_recipe_presets),
    ("alerts:v1", step_alerts),
    ("display_units:v1", step_display_units),
    ("notify:v1", step_notify),
    ("feed_calibration:v1", step_feed_calibration),
    ("dosing_pumps:v1", step_dosing_pumps),
    ("feed_ec_fallback:v1", step_feed_ec_fallback),
    ("new_panels:v1", step_new_panels),
)
STARTED_STEPS = (
    ("snapshot_preset:v1", step_snapshot_preset),
    ("retired_entities:v1", step_retired_entities),
)


# ---------------------------------------------------------------------- running them
async def _run(hass, ledger, entry, steps) -> None:
    room = ledger.room(entry.entry_id)
    for name, step in steps:
        done = room["steps"].get(name)
        if done and done.get("result") != "error":
            continue
        try:
            rows = await step(hass, entry, room)
            for item in rows:
                put(room["report"], item)
            result = "done" if rows else "skipped"
            room["steps"][name] = {"at": _now(), "result": result, "error": None}
        except Exception as error:  # noqa: BLE001 - a step never stops the room
            _LOGGER.warning("Crop Steering upgrade step %s failed: %s", name, error)
            room["steps"][name] = {"at": _now(), "result": "error", "error": str(error)}
    await ledger.save()


def raise_card(hass, entry) -> None:
    """The room's Upgrade report card: up while the report lists something that needs the grower and
    nobody has marked it as read."""
    from homeassistant.helpers import issue_registry as ir

    from .health import _iid, _issue

    ledger = ledger_of(hass)
    if ledger is None:
        return
    report = ledger.report(entry.entry_id)
    ack = entry.entry_id in ledger.document["acknowledged"]
    _issue(
        hass,
        bool(report["needs_you"]) and not ack,
        _iid(ISSUE, entry.data.get("room_slug", "default")),
        ir.IssueSeverity.WARNING,
        {
            "carried": str(len(report["carried"])),
            "needs_you": str(len(report["needs_you"])),
        },
        fix={"entry_id": entry.entry_id, "kind": ISSUE},
    )


async def acknowledge(hass, entry_id: str) -> None:
    ledger = ledger_of(hass)
    if ledger is None:
        return
    async with ledger.lock:
        ledger.document["acknowledged"][entry_id] = _now()
        await ledger.save()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            raise_card(hass, entry)


async def async_setup_migration(hass) -> Ledger:
    """The site's ledger and the migration_report service, once."""
    data = hass.data.setdefault(DOMAIN, {})
    if "_migration" in data:
        return data["_migration"]
    ledger = data["_migration"] = Ledger(hass)
    await ledger.async_init()

    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    from .api_v2 import fields, wrap

    async def handle(call):
        room_id = call.data["room_id"]
        matches = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if "room:" + room_prefix(e) == room_id
        ]
        if len(matches) != 1:
            raise HomeAssistantError(f"Room {room_id} is unknown or ambiguous")
        entry_id = matches[0].entry_id
        return {
            "schema_version": 1,
            "release": RELEASE,
            "room_id": room_id,
            "acknowledged": ledger.document["acknowledged"].get(entry_id),
            **ledger.report(entry_id),
        }

    hass.services.async_register(
        DOMAIN,
        "migration_report",
        wrap(handle),
        schema=vol.Schema(fields({vol.Required("room_id"): str})),
        supports_response=SupportsResponse.ONLY,
    )
    return ledger


async def async_migrate_room(hass, entry, fresh: bool) -> None:
    """The room's steps: now (its entities exist), and its last steps once Home Assistant has
    started. Never raises."""
    from homeassistant.helpers.start import async_at_started

    try:
        ledger = await async_setup_migration(hass)
        if ledger.error:
            return
        async with ledger.lock:
            room = ledger.room(entry.entry_id)
            if fresh:
                for name, _step in (*SETUP_STEPS, *STARTED_STEPS):
                    room["steps"].setdefault(
                        name, {"at": _now(), "result": "fresh", "error": None}
                    )
                await ledger.save()
                return
            await _run(hass, ledger, entry, SETUP_STEPS)
        raise_card(hass, entry)
    except Exception as error:  # noqa: BLE001 - never block setup on the upgrade
        _LOGGER.warning("Crop Steering upgrade did not run: %s", error)
        return

    async def started(_hass):
        try:
            async with ledger.lock:
                await _run(hass, ledger, entry, STARTED_STEPS)
            raise_card(hass, entry)
        except Exception as error:  # noqa: BLE001
            _LOGGER.warning("Crop Steering upgrade did not finish: %s", error)

    entry.async_on_unload(async_at_started(hass, started))


async def note_history(hass, entry, added: int) -> None:
    """M14: the journal backfill (journal_api.async_backfill_room) brought `added` earlier records into
    History. Listed once; never raises."""
    try:
        ledger = await async_setup_migration(hass)
        if ledger.error:
            return
        async with ledger.lock:
            room = ledger.room(entry.entry_id)
            if any(r.get("id") == "history.import" for r in room["report"]["carried"]):
                return
            put(
                room["report"],
                row(
                    "history.import",
                    "History",
                    "carried",
                    f"History imported: {added} earlier setting changes, stock moves, calibrations "
                    "and overlays.",
                    "#/history",
                    "history",
                ),
            )
            await ledger.save()
    except Exception as error:  # noqa: BLE001
        _LOGGER.warning("Crop Steering upgrade report: history not noted: %s", error)


async def async_unload_migration(hass) -> None:
    """With the last room."""
    if hass.data.get(DOMAIN, {}).pop("_migration", None) is not None:
        hass.services.async_remove(DOMAIN, "migration_report")
