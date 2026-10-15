"""Every upgraded room stops on exactly the kill switch it stopped on before the update.

A room has one kill switch (its gate): the entity that must read ON before anything in it is
watered. The controller picks it in two steps: a start-up value (a named room its engine switch; the
default room the app's `enable_flag` option, or its setup's flag where that option is the legacy
helper and the helper does not exist), which a revisioned setup replaces with its own flag once the
controller adopts or resumes it. The integration names the same switch from the room's heartbeat,
unless the heartbeat is behind the published setup.

The oracle is the code that ran before the gate had one rule per layer, 12c6d1a, not a reading of
it. tests_ha/fixtures/capture_gate_matrix.py starts that controller on each seeded room below, through its
first setup pass, and writes what it ended with to tests_ha/fixtures/gate_matrix_12c6d1a.json,
along with the descriptor the 12c6d1a integration published and the gate its health check named.
Here the same rooms are started on this code, and every row must match:

- the gate after the first setup pass (room_gate), not the start-up value;
- whether the setup waits for a disarm, and on exactly which switches;
- the descriptor's attributes and the setup fingerprint, so a resumed room resumes with no disarm;
- the integration's gate for a heartbeat that is absent, current and behind.

Axes: the room (F-2251, F-217, F-38, F-ENV and a named room) x the setup's own flag (none, so the
room kind's default; the helper; the engine switch) x the saved setup (none; resumed after restart
with its fingerprint; older than the published one, so pending) x the app's `enable_flag` option
(absent, the helper, another entity) x the helper (absent, ON, OFF) x the engine switch (absent, ON,
OFF).
"""

import json
import os
import re
import types
from pathlib import Path

import pytest
from conftest import FIXTURES, fixture
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "crop_steering"
LEGACY = "input_boolean.f2_control_enabled"
OTHER = "input_boolean.another_kill_switch"  # an app option naming some other entity
REPORTED = "input_boolean.reported_kill_switch"  # what a heartbeat names in the integration rows
TABLE = FIXTURES / "gate_matrix_12c6d1a.json"
# Set only by capture_gate_matrix.py, which runs this file against the 12c6d1a tree.
RECORD = os.environ.get("GATE_MATRIX_RECORD")

ROOMS = {
    "F-2251": ("entry_2_25_1_pumped_room.json", ""),
    "F-217": ("entry_2_17_wizard.json", ""),
    "F-38": ("entry_3_8_learned_tent.json", ""),
    "F-ENV": ("entry_env_era.json", ""),
    "named": ("entry_2_25_1_pumped_room.json", "room_b"),
}
SETUP_FLAGS = ("kind_default", "helper", "engine_switch")
SAVED = ("none", "resumed", "pending")
OPTIONS = {"absent": {}, "helper": {"enable_flag": LEGACY}, "other": {"enable_flag": OTHER}}
PRESENCE = ("absent", "on", "off")
# Not part of what the gate depends on: the version moves with every release, and the other two are
# Home Assistant's own, not the descriptor's.
NOT_COMPARED = ("integration_version", "friendly_name", "icon")
# Descriptor attributes added since 12c6d1a, which the controller reads for something other than
# the gate and which the setup fingerprint does not cover.
ADDED_SINCE = ("substrate",)


async def _seed(hass, room, setup_flag):
    """The seeded room, set up by the integration, with its setup naming `setup_flag`."""
    name, slug = ROOMS[room]
    seed = fixture(name)
    prefix = f"{slug}_" if slug else ""
    own = f"switch.{DOMAIN}_{prefix}engine_enabled"
    data = dict(seed["data"])
    if slug:
        data.update(room_prefix=prefix, room_slug=slug, room_name="Room B", name="Room B")
    data.pop("enable_flag", None)
    if setup_flag != "kind_default":
        data["enable_flag"] = LEGACY if setup_flag == "helper" else own
    for entity_id, (state, attributes) in seed["states"].items():
        hass.states.async_set(entity_id, state, attributes)
    hass.states.async_set(OTHER, "on")
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=seed.get("version", 1),
        minor_version=seed.get("minor_version", 1),
        entry_id=seed["entry_id"],
        unique_id=seed["unique_id"],
        title=seed["title"],
        data=data,
        options=seed["options"],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return prefix, slug or "default", own


def _present(hass, entity_id, presence):
    if presence == "absent":
        hass.states.async_remove(entity_id)
    else:
        hass.states.async_set(entity_id, presence)


def _waits_on(fake, slug):
    """The switches a waiting setup asks to read OFF (its CS-201 notice), or None."""
    notices = [
        data
        for domain, service, data in fake.calls
        if domain == "persistent_notification"
        and service == "create"
        and data.get("notification_id") == f"f2_setup_{slug}"
    ]
    if not notices:
        return None
    found = re.search(r"OFF: (.*?)\. Turn them off", notices[-1]["message"])
    return found.group(1).split(", ") if found else notices[-1]["message"]


def _gate(controller, room):
    return room.enable_flag if RECORD else controller.room_gate(room)


def _integration_gate(hass, prefix):
    if RECORD:
        from custom_components.crop_steering import health

        return health._kill_switch(hass, prefix)
    from custom_components.crop_steering.room import room_gate

    return room_gate(hass, prefix)


async def _run(hass, controller_for, room, setup_flag):
    """Everything this room ends up with, case by case, on the code under test."""
    import controller

    prefix, slug, own = await _seed(hass, room, setup_flag)
    descriptor = json.loads(
        json.dumps(dict(hass.states.get(f"sensor.{DOMAIN}_{prefix}engine_config").attributes), default=str)
    )
    revision = descriptor.get("setup_revision", 0)
    fingerprint = controller.Controller._setup_fingerprint(descriptor, types.SimpleNamespace(enable_flag=None))
    state_path = Path(os.environ["F2_STATE_PATH"])
    cases = {}
    for saved in SAVED:
        for option, options in OPTIONS.items():
            for helper in PRESENCE:
                for switch in PRESENCE:
                    _present(hass, LEGACY, helper)
                    _present(hass, own, switch)
                    state_path.unlink(missing_ok=True)  # nothing left over from the case before
                    saved_state = None
                    if saved != "none":
                        block = {
                            "revision": revision if saved == "resumed" else revision - 1,
                            "fingerprint": fingerprint,
                        }
                        if descriptor.get("entry_id"):
                            block["entry_id"] = descriptor["entry_id"]
                        saved_state = {slug: {"_setup": block}}
                    c, fake, _clock = controller_for(dict(options), saved_state=saved_state)
                    r = next(r for r in c.rooms if r.slug == slug)
                    cases[f"{saved}|{option}|{helper}|{switch}"] = [
                        _gate(controller, r),
                        getattr(r, "_setup_pending", None) is not None,
                        _waits_on(fake, slug),
                        getattr(r, "setup_revision", 0),
                    ]
    integration = {}
    heartbeat = f"sensor.{DOMAIN}_{prefix}ai_heartbeat"
    for beat, have in (("absent", None), ("current", revision), ("behind", revision - 1)):
        if have is None:
            hass.states.async_remove(heartbeat)
        else:
            hass.states.async_set(heartbeat, "healthy", {"enable_flag": REPORTED, "setup_revision": have})
        integration[beat] = _integration_gate(hass, prefix)
    return {
        "descriptor": {k: v for k, v in descriptor.items() if k not in NOT_COMPARED + ADDED_SINCE},
        "fingerprint": fingerprint,
        "integration": integration,
        "cases": cases,
    }


def _record(key, result):
    path = Path(RECORD)
    table = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    table[key] = result
    path.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.parametrize("setup_flag", SETUP_FLAGS)
@pytest.mark.parametrize("room", list(ROOMS))
async def test_each_room_keeps_the_gate_it_had(hass, controller_for, room, setup_flag):
    key = f"{room}|{setup_flag}"
    result = await _run(hass, controller_for, room, setup_flag)
    if RECORD:
        _record(key, result)
        return
    before = json.loads(TABLE.read_text(encoding="utf-8"))[key]
    assert result["descriptor"] == before["descriptor"]  # published byte for byte as before
    assert result["fingerprint"] == before["fingerprint"]  # so a resumed room resumes
    assert result["integration"] == before["integration"]
    moved = {
        case: {"12c6d1a": before["cases"].get(case), "now": now}
        for case, now in result["cases"].items()
        if before["cases"].get(case) != now
    }
    assert not moved, json.dumps(dict(list(moved.items())[:12]), indent=1)
    assert set(result["cases"]) == set(before["cases"])
    # No disarm on a restart: a resumed setup never waits (every fixture's hardware reads OFF).
    for case, (_gate_now, pending, waits, _revision) in result["cases"].items():
        if case.startswith("resumed|"):
            assert not pending and waits is None, case
