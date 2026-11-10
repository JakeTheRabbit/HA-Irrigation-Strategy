"""A shot interrupted in a room without a main line, or without a pump, is closed at the next start.

The setup wizard's descriptor says `mainline: ""` for a room with no main line and `pump: ""` for
one with no pump. The controller saved its record of a shot with that "", and at the next start it
took the record for damaged and ignored it. So after a crash, a kill -9 or a power cut in the
middle of a shot in such a room, the controller did not close the valve and the pump at its next
start. (It did raise CS-201, which names switches that are on.)

Here the integration runs in a real Home Assistant and writes the real descriptor. The real
controller reads it through the test's mirror of Home Assistant's states (conftest.controller_for),
is killed in a shot, and a new controller starts on the state file that the first one left.
"""

import json
import os
from pathlib import Path

import pytest
from conftest import room_of, switch_calls
from test_declared_plumbing import UPGRADED_ARMED, UPGRADED_KILL
from test_declared_plumbing import _arm as _arm_these
from test_real_flow import VALVE as TENT_VALVE
from test_safety_ops import KILL, NEW, PUMP, VALVE, _arm, _pumped_room
from test_upgrade_in_place import DESCRIPTOR, _upgrade


def _offs(fake):
    """The pump and the valve of the wizard's pumped room are input_booleans."""
    return [(service, data["entity_id"]) for domain, service, data in fake.calls if domain == "input_boolean"]


def _killed_in_a_shot(c, room):
    """The controller dies in the shot's wait: no cleanup runs."""

    def killed(*_a, **_k):
        raise SystemExit(137)

    c._wait_shot = killed
    with pytest.raises(SystemExit):
        c._execute_shot(room, 1, 30, 5, flow_lps=0.05)
    return json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))


async def _pumped_room_killed_in_a_shot(hass, controller_for):
    await _pumped_room(hass, waste=False)
    desc = hass.states.get("sensor.crop_steering_tent_engine_config").attributes
    assert desc["mainline"] == "" and desc["pump"] == PUMP  # what the wizard writes
    c, fake, _clock = controller_for({"enable_flag": KILL})
    _arm(fake)
    saved = _killed_in_a_shot(c, room_of(c, NEW))
    assert fake.states[PUMP][0] == "on" and fake.states[VALVE][0] == "on"
    for entity_id in (PUMP, VALVE):  # Home Assistant has them on, as the dead controller left them
        await hass.services.async_call("input_boolean", "turn_on", {"entity_id": entity_id}, blocking=True)
    return saved


async def test_the_next_start_closes_the_valve_and_the_pump_of_a_room_with_no_main_line(hass, controller_for):
    saved = await _pumped_room_killed_in_a_shot(hass, controller_for)
    record = saved["tent"]["_shot_inflight"]
    assert (record["valve"], record["pump"], record["mainline"]) == (VALVE, PUMP, None)

    again, fake, _clock = controller_for({"enable_flag": KILL}, saved_state=saved)
    room = room_of(again, NEW)
    assert room.shot_inflight == record  # read back, not ignored
    fake.set_state(KILL, "on")
    fake.calls.clear()
    again._reconcile_inflight()
    assert _offs(fake) == [("turn_off", VALVE), ("turn_off", PUMP)]
    assert room.shot_inflight is None and room.hardware_fault is None


async def test_a_record_that_the_version_before_saved_is_closed_after_the_update(hass, controller_for):
    """The controller crashed on the version before this one, and is updated before it starts again:
    the state file holds the record with the "" that version wrote."""
    saved = await _pumped_room_killed_in_a_shot(hass, controller_for)
    saved["tent"]["_shot_inflight"]["mainline"] = ""
    again, fake, _clock = controller_for({"enable_flag": KILL}, saved_state=saved)
    room = room_of(again, NEW)
    assert room.shot_inflight is not None
    fake.set_state(KILL, "on")
    fake.calls.clear()
    again._reconcile_inflight()
    assert _offs(fake) == [("turn_off", VALVE), ("turn_off", PUMP)]
    assert room.shot_inflight is None


@pytest.mark.parametrize("as_saved_by", ["this version", "the version before"])
async def test_a_one_switch_tent_from_2_18_updated_in_place_has_its_valve_closed(hass, controller_for, as_saved_by):
    """The seeded 2.18 tent has one switch: no pump and no main line, both "" in its descriptor."""
    _entry, seed = await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    desc = hass.states.get(DESCRIPTOR).attributes
    assert (desc["pump"], desc["mainline"]) == ("", "")
    hass.states.async_set(UPGRADED_KILL, "on")
    c, fake, _clock = controller_for({"enable_flag": UPGRADED_KILL}, saved_state=seed["controller_saved"])
    _arm_these(fake, UPGRADED_ARMED)
    saved = _killed_in_a_shot(c, room_of(c, ""))
    assert fake.states[TENT_VALVE][0] == "on"
    (block,) = [b for b in saved.values() if isinstance(b, dict) and "_shot_inflight" in b]
    assert block["_shot_inflight"] == {**block["_shot_inflight"], "valve": TENT_VALVE, "pump": None, "mainline": None}
    if as_saved_by == "the version before":
        block["_shot_inflight"].update(pump="", mainline="")
    hass.states.async_set(TENT_VALVE, "on")

    again, fake, _clock = controller_for({"enable_flag": UPGRADED_KILL}, saved_state=saved)
    room = room_of(again, "")
    assert room.shot_inflight is not None
    fake.calls.clear()
    again._reconcile_inflight()
    assert switch_calls(fake) == [("turn_off", TENT_VALVE)]
    assert room.shot_inflight is None
