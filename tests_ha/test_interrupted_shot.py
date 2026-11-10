"""An interrupted shot on an upgraded room, with the room's "Watering" switch off.

A 2.25.1 room, updated in place: the real integration on its seeded install, the real controller on the state
file that version left, to which a shot in flight is added (the host lost power mid-shot, or the app was killed).
At the next start the controller closes what that shot opened. Before, it did so only while the room's engine
switch read ON; with it OFF, the valve, main line and pump stayed ON, with one line in the log.
"""

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import fixture, switch_calls
from test_upgrade_in_place import KILL, UPSTREAM_2_25_1, _upgrade

VALVE, MAINLINE, PUMP = "switch.zone_1_valve", "switch.irrigation_main_line", "switch.irrigation_pump"


async def _interrupted(hass, controller_for, kill):
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    if kill is None:
        hass.states.async_remove(KILL)
    else:
        hass.states.async_set(KILL, kill)
    saved = copy.deepcopy(seed["controller_saved"])
    started = datetime.now(timezone.utc) - timedelta(seconds=20)
    saved["default"]["_shot_inflight"] = {
        "zone": 1, "valve": VALVE, "mainline": MAINLINE, "pump": PUMP, "started": started.isoformat()}
    for entity in (PUMP, MAINLINE, VALVE):
        hass.states.async_set(entity, "on")  # switched on by that shot: on since it started
    c, fake, _clock = controller_for(seed["addon_options"], saved_state=saved)
    room = c.rooms[0]
    assert room.shot_inflight["valve"] == VALVE and room.hw["valves"][1] == VALVE
    fake.calls.clear()
    return c, fake, room


@pytest.mark.parametrize("kill", ["off", "unavailable", None, "on"])
async def test_the_next_start_closes_an_interrupted_shot_whatever_the_engine_switch_reads(
    hass, controller_for, kill
):
    c, fake, room = await _interrupted(hass, controller_for, kill)

    c._reconcile_inflight()

    assert switch_calls(fake) == [("turn_off", VALVE), ("turn_off", MAINLINE), ("turn_off", PUMP)]
    assert [fake.states[e][0] for e in (VALVE, MAINLINE, PUMP)] == ["off", "off", "off"]
    assert room.shot_inflight is None and room.hardware_fault is None
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))["default"]
    assert "_shot_inflight" not in saved


async def test_with_the_engine_switch_off_nothing_else_is_switched_and_no_shot_starts(hass, controller_for):
    """Closing what was left open is all it does: the room stays dry while its engine switch is off."""
    c, fake, _room = await _interrupted(hass, controller_for, "off")

    c.loop_once(datetime.now())
    c.loop_once(datetime.now())

    assert [call for call in switch_calls(fake) if call[0] != "turn_off"] == []
    assert switch_calls(fake) == [("turn_off", VALVE), ("turn_off", MAINLINE), ("turn_off", PUMP)]
