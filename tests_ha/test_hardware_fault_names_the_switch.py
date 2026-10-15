"""A hardware fault (CS-301) names the switch that did not read OFF, and how it failed.

The notification used to say only "a pump or valve did not confirm it had switched OFF", so the
grower had to walk every pump and valve to find the one at fault. Here the real integration maps the
valve, a real Home Assistant names it, the valve stays ON after the real controller switches it off,
and the hold must name it (its name, its entity id, "still read ON") in the notification and in the
zone's status, keep naming it after a restart, and a fault saved by an older controller, which has
no switch in it, must still load and hold.
"""

import json
import os
from pathlib import Path

from test_real_flow import VALVE
from test_recreated_room_controller import KILL, _see
from test_setup_entry import _install

NAME = "Tent valve"


def _stuck(monkeypatch, fake, entity):
    """Home Assistant takes the command; the relay stays ON."""
    import controller

    def call(domain, service, **data):
        if domain == "switch" and service == "turn_off" and data.get("entity_id") == entity:
            fake.calls.append((domain, service, data))
            return True
        return fake.ha_call(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", call)


def _cs301(fake):
    return [
        d for dom, svc, d in fake.calls
        if dom == "persistent_notification" and svc == "create" and "(CS-301)" in d.get("title", "")
    ]


async def test_the_hold_names_the_valve_that_stayed_on_and_still_does_after_a_restart(
    hass, controller_for, monkeypatch
):
    await _install(hass)
    hass.states.async_set(VALVE, "on", {"friendly_name": NAME})
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert room.hw["valves"] == {1: VALVE}
    _stuck(monkeypatch, fake, VALVE)

    failures = c._switch_off_failures([VALVE])
    assert failures == [{"entity_id": VALVE, "problem": "on", "name": NAME}]
    c._latch_hardware_fault(room, "zone 1 shot end", failures)

    (alert,) = _cs301(fake)
    assert f"{NAME} ({VALVE}) still read ON" in alert["message"]
    assert c._hardware_fault_block(room).startswith(
        f"hardware fault (CS-301): zone 1 shot end: {NAME} ({VALVE}) still read ON"
    )
    assert c._hardware_fault_short(room) == "hardware fault (CS-301)"

    # Restart: the next controller reads the fault back from /data/state.json and still names it.
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))
    _see(hass, fake)
    again, _fake, _ = controller_for({"enable_flag": KILL}, saved_state=saved)
    assert again.rooms[0].hardware_fault["switches"] == failures
    assert f"{NAME} ({VALVE}) still read ON" in again._hardware_fault_block(again.rooms[0])


async def test_an_offline_switch_is_named_as_unavailable(hass, controller_for):
    await _install(hass)
    hass.states.async_set(VALVE, "unavailable", {"friendly_name": NAME})
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    (failure,) = c._close_failures([VALVE])
    assert failure == {"entity_id": VALVE, "problem": "unavailable", "name": NAME}
    c._latch_hardware_fault(c.rooms[0], "zone 1 shot end", [failure])
    assert "read unavailable: Home Assistant could not reach it" in c._hardware_fault_block(c.rooms[0])


async def test_a_fault_saved_by_an_older_controller_loads_and_still_holds(hass, controller_for):
    """3.11.1 and older saved the reason and the hardware, never which switch failed."""
    await _install(hass)
    old = {"reason": "zone 1 valve/pump/mainline close not confirmed", "entities": [VALVE]}
    c, _fake, _clock = controller_for({"enable_flag": KILL}, saved_state={"default": {"_hardware_fault": old}})
    room = c.rooms[0]
    assert room.hardware_fault == {**old, "switches": []}
    assert c._hardware_fault_block(room) == f"hardware fault (CS-301): {old['reason']}"
