"""Is a new room ready to switch on? The setup wizard's live checks, and its saved draft.

A room set up from this release on starts with a `commissioning` draft in its entry; the dashboard's
setup wizard walks it (valves, probes, sizing, a test shot a person watched) and marks it done. A room
from before has no draft and is commissioned already: it never sees the wizard.

Three checks are about safety and hold the wizard's Switch on until they pass: every active zone's
valve mapped and reading OFF (with the pump and main line), its probes reporting in a usable unit, and a
test shot the controller ran and a person saw water from. The rest only warn: sizing still on the
generic defaults until someone confirms it (never required, so a fresh install can still run), the
controller not reporting, and lights hours that cannot be right. Nothing here locks the room's engine
switch, and nothing here is part of the setup the controller adopts: saving the draft does not change
the setup revision.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math

from . import units
from .setup_api import (
    SIZING,
    _off_blocker,
    _selected,
    effective,
    hardware_entities,
    setup_sizing,
)
from .generated.defaults import SIZING_DEFAULTS

PROBE_FRESH = timedelta(
    minutes=10
)  # a mapped probe that has said nothing for longer is not reporting


def _numeric(state):
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _time(value):
    if not isinstance(value, str) or value in ("", "unknown", "unavailable"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _probe_problem(hass, zone, kind, eid, now):
    state = hass.states.get(eid)
    if state is None:
        return f"Zone {zone}: {eid} does not exist"
    value = _numeric(state)
    if value is None:
        return f"Zone {zone}: {eid} is not reporting a number"
    reported = getattr(state, "last_reported", None) or getattr(
        state, "last_updated", None
    )
    if reported is not None and now - reported > PROBE_FRESH:
        return f"Zone {zone}: {eid} has not reported in the last 10 minutes"
    unit = state.attributes.get("unit_of_measurement")
    reading, set_aside = units.to_native(kind, unit, value)
    if reading is None or set_aside:
        return f"Zone {zone}: {eid} reports in {unit or 'no unit'!r}, which can't be read as {kind.upper()}"
    return None


def _check(check_id, step, blocking, problems):
    return {
        "id": check_id,
        "step": step,
        "ok": not problems,
        "blocking": blocking,
        "problems": problems,
    }


def readiness(hass, entry):
    """The room's wizard checks. `commissioned` rooms (every room from before) never see the wizard."""
    data = effective(entry)
    draft = data.get("commissioning")
    commissioned = not isinstance(draft, dict) or draft.get("done") is True
    draft = draft if isinstance(draft, dict) else {}
    seen = draft.get("water_seen") if isinstance(draft.get("water_seen"), dict) else {}
    prefix = data.get("room_prefix", "")
    now = datetime.now(timezone.utc)
    zones = {
        int(z): cfg
        for z, cfg in (data.get("zones") or {}).items()
        if (cfg or {}).get("active", True)
    }

    beat = hass.states.get(f"sensor.crop_steering_{prefix}ai_heartbeat")
    controller = (
        []
        if beat is not None and beat.state not in ("unknown", "unavailable")
        else ["The controller app has not reported for this room yet"]
    )

    hours = [
        (
            _numeric(state)
            if (state := hass.states.get(f"number.crop_steering_{prefix}{key}"))
            else None
        )
        for key in ("lights_on_hour", "lights_off_hour")
    ]
    room = (
        ["Set the lights-on and lights-off hours"]
        if None in hours
        else (
            ["Lights-on and lights-off are the same hour"]
            if hours[0] == hours[1]
            else []
        )
    )

    valves = [
        f"Zone {z}: select a valve"
        for z, cfg in sorted(zones.items())
        if not cfg.get("zone_switch")
    ]
    valves += [
        b for eid in sorted(hardware_entities(data)) if (b := _off_blocker(hass, eid))
    ]

    probes = []
    for z, cfg in sorted(zones.items()):
        mapped = cfg.get("vwc_sensors") or [
            cfg[k] for k in ("vwc_front", "vwc_back") if cfg.get(k)
        ]
        if not mapped:
            probes.append(f"Zone {z}: map a moisture probe")
        for kind in ("vwc", "ec"):
            for eid in cfg.get(f"{kind}_sensors") or [
                cfg[k] for k in (f"{kind}_front", f"{kind}_back") if cfg.get(k)
            ]:
                if problem := _probe_problem(hass, z, kind, eid, now):
                    probes.append(problem)

    generic = sorted(
        {
            key
            for z, cfg in zones.items()
            for key in SIZING
            if setup_sizing(hass, data, cfg, z, key) == SIZING_DEFAULTS[key]
        }
    )
    sizing = (
        [
            f"Sizing still on the generic defaults ({', '.join(generic)}): check and confirm it"
        ]
        if generic and draft.get("sizing_confirmed") is not True
        else []
    )

    shots = []
    for z in sorted(zones):
        pressed = hass.states.get(f"button.crop_steering_{prefix}zone_{z}_test_shot")
        at = _time(pressed.state) if pressed else None
        if at is None:
            shots.append(f"Zone {z}: run a test shot")
            continue
        last = hass.states.get(
            f"sensor.crop_steering_{prefix}zone_{z}_last_irrigation_app"
        )
        watered = _time(last.state) if last else None
        if watered is None or watered < at:
            shots.append(f"Zone {z}: the controller has not reported the test shot yet")
        elif seen.get(str(z)) != pressed.state:
            shots.append(f"Zone {z}: confirm water reached the drippers")

    checks = [
        _check("controller", 0, False, controller),
        _check("room", 1, False, room),
        _check("valves", 2, True, valves),
        _check("probes", 3, True, probes),
        _check("sizing", 4, False, sizing),
        _check("test_shot", 6, True, shots),
    ]
    failing = next((c for c in checks if c["blocking"] and not c["ok"]), None)
    return {
        "commissioned": commissioned,
        "ready": failing is None,
        "waiting_for": failing["problems"][0] if failing else None,
        "checks": checks,
        "draft": {
            "water_seen": dict(seen),
            "sizing_confirmed": draft.get("sizing_confirmed") is True,
        },
    }


async def save_commissioning(hass, payload):
    """Save the wizard's draft: which test shots a person saw water from, sizing confirmed, done.
    Revision-checked like every setup change, but it does not bump the setup revision: nothing in it
    is part of the setup the controller adopts, so it never asks for a disarm cycle."""
    from .setup_api import setup_room

    entry = _selected(hass, payload)
    data = deepcopy(dict(entry.data))
    if (
        not isinstance(data.get("commissioning"), dict)
        or data["commissioning"].get("done") is True
    ):
        raise ValueError("This room is already set up")
    draft = data["commissioning"]
    seen = payload.get("water_seen", {})
    if not isinstance(seen, dict) or not all(
        isinstance(v, str) and str(k).isdigit() for k, v in seen.items()
    ):
        raise ValueError("water_seen maps a zone to the test shot it confirms")
    draft["water_seen"] = {
        **(draft.get("water_seen") or {}),
        **{str(k): v for k, v in seen.items()},
    }
    if "sizing_confirmed" in payload:
        if type(payload["sizing_confirmed"]) is not bool:
            raise ValueError("sizing_confirmed must be a boolean")
        draft["sizing_confirmed"] = payload["sizing_confirmed"]
    done = payload.get("done", False)
    if type(done) is not bool:
        raise ValueError("done must be a boolean")
    hass.config_entries.async_update_entry(entry, data=data)
    if done:
        status = readiness(hass, entry)
        if not status["ready"]:
            raise ValueError(f"Not ready to switch on: {status['waiting_for']}")
        data = deepcopy(dict(entry.data))
        data["commissioning"]["done"] = True
        hass.config_entries.async_update_entry(entry, data=data)
    return setup_room(hass, entry)
