"""System Enabled and Auto Irrigation Enabled are retired: the room's engine switch is the one switch.

Each used to stop every shot by itself, as the engine switch does, but less well: a shot already
running carried on. Now nothing reads them as a gate. While one still exists and reads off, the
controller switches the engine switch off in its place, so a room someone stopped with one of them
stays stopped, and a running shot stops as well (_wait_shot reads the engine switch).
"""
import pytest

from test_controller import _build, _desc

KILL = "input_boolean.kill"
SYSTEM = "switch.crop_steering_system_enabled"
AUTO = "switch.crop_steering_auto_irrigation_enabled"


def _room(overrides=None, without=()):
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: ("on", {}),
        SYSTEM: ("on", {}),
        AUTO: ("on", {}),
        "switch.crop_steering_zone_1_enabled": ("on", {}),
    }
    states.update(overrides or {})
    for entity in without:
        states.pop(entity)
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=states)
    return c, fake, c.rooms[0]


def _engine_offs(fake):
    return [d for dom, svc, d in fake.calls if svc == "turn_off" and d.get("entity_id") == KILL]


def _cs208(fake):
    return [
        d
        for dom, svc, d in fake.calls
        if dom == "persistent_notification" and "(CS-208)" in d.get("title", "")
    ]


@pytest.mark.parametrize("entity, name", [(SYSTEM, "System Enabled"), (AUTO, "Auto Irrigation Enabled")])
def test_an_off_one_switches_watering_off_in_its_place(entity, name):
    c, fake, room = _room({entity: ("off", {})})
    assert c._carry_retired_switches(room) == [name]
    assert len(_engine_offs(fake)) == 1
    (note,) = _cs208(fake)
    assert note["title"] == f"{name} is off, so watering was switched off (CS-208)"
    assert entity in note["message"] and "Settings → Watering" in note["message"]
    # Home Assistant may not read OFF yet this pass: the gate holds on the carried names meanwhile.
    room._retired_off = [name]
    fake.set_state(KILL, "on")
    assert c._blocked(room, 1) == f"{name} off: engine switch switched off in its place"


def test_on_or_missing_they_change_nothing():
    for c, fake, room in (_room(), _room(without=(SYSTEM, AUTO))):
        assert c._carry_retired_switches(room) == []
        assert _engine_offs(fake) == [] and _cs208(fake) == []
        room._retired_off = []
        assert c._blocked(room, 1) is None


def test_an_unreadable_one_changes_nothing():
    c, fake, room = _room({SYSTEM: ("unavailable", {})})
    assert c._carry_retired_switches(room) == []
    assert _engine_offs(fake) == []


def test_the_shot_gate_no_longer_reads_them():
    """An off one holds only through the carry: the gate itself never asks either switch again."""
    c, fake, room = _room({SYSTEM: ("off", {}), AUTO: ("off", {})})
    room._retired_off = []  # as if the carry had not run
    assert c._blocked(room, 1) is None


def test_it_only_ever_switches_watering_off():
    c, fake, room = _room({KILL: ("off", {}), SYSTEM: ("off", {})})
    assert c._carry_retired_switches(room) == ["System Enabled"]
    assert not any(svc == "turn_on" for _dom, svc, _d in fake.calls)
    assert _engine_offs(fake) == [] and _cs208(fake) == []  # already off: nothing switched, nothing said


def test_it_is_carried_again_while_the_switch_stays_off():
    c, fake, room = _room({SYSTEM: ("off", {})})
    c._carry_retired_switches(room)
    fake.set_state(KILL, "on")  # someone switched watering back on, System Enabled still off
    c._carry_retired_switches(room)
    assert len(_engine_offs(fake)) == 2
