"""A room DECLARES how it is plumbed; the controller no longer has to guess from what is mapped.

2.18.0 made the pump and main-line optional by inference: no pump mapped = the room has no pump. That
is right for a tent on one smart plug and silently wrong for a pumped room whose pump mapping was
cleared, mistyped away or never filled in. Reproduced against 2.18.0: pump "" in the descriptor, the
valve opened, no pump ran, and 1.5 L was counted as delivered while the plants got nothing.

Now the setup can state the layout (`plumbing` in the descriptor). Declared: the switches must match
it, or the room is held with a reason. Never declared (every install from before this): exactly the
old behaviour, including the saved setup fingerprint, so an update strands nobody.
"""
import json
import pathlib
import re

import pytest

import controller
from test_controller import _build, _desc
from test_setup_resume import KILL as RESUME_KILL, _start, _states

KILL = "input_boolean.kill"
VALVE = "switch.v1"
DESCRIPTOR = "sensor.crop_steering_engine_config"
FLAGS = {
    KILL: ("on", {}),
    "switch.crop_steering_system_enabled": ("on", {}),
    "switch.crop_steering_auto_irrigation_enabled": ("on", {}),
    "switch.crop_steering_zone_1_enabled": ("on", {}),
}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = {"seconds": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: now["seconds"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: now.__setitem__("seconds", now["seconds"] + dt))
    return now


def _room(plumbing=None, pump=None, mainline=None):
    extra = {"plumbing": plumbing} if plumbing else {}
    states = {
        DESCRIPTOR: ("ok", _desc(pump=pump, mainline=mainline, valves={"1": VALVE}, enable_flag=KILL, **extra)),
        VALVE: ("off", {}),
        **FLAGS,
    }
    states.update({entity: ("off", {}) for entity in (pump, mainline) if entity})
    return _build({"num_zones": 1, "enable_flag": KILL}, states=states)


def _switch_calls(fake):
    return [(svc, d["entity_id"]) for dom, svc, d in fake.calls if dom == "switch"]


def _alerts(fake, word):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and word in d["notification_id"]]


# --------------------------------------------------------------------------- the defect
def test_a_pumped_room_that_lost_its_pump_mapping_is_held_not_run_dry():
    c, fake = _room(plumbing="pump_valves", pump=None)
    room = c.rooms[0]
    reason = c._blocked(room, 1)
    assert "has a pump" in reason and "no pump switch is mapped" in reason
    c._execute_shot(room, 1, 6, 2.0)  # whatever asks for a shot, the valve stays shut
    assert _switch_calls(fake) == []
    assert room.state[1]["shots"] == 0 and room.state[1]["daily_vol"] == 0  # and nothing is counted as delivered
    alert = _alerts(fake, "plumbing")
    assert len(alert) == 1 and "BLOCKED" in alert[0]["title"]
    assert "map the pump" in alert[0]["message"]  # says what to do, not only what is wrong


def test_the_same_room_undeclared_still_runs_as_2_18_did():
    """Pinned on purpose: an install that never declared must not change behaviour on update."""
    c, fake = _room(plumbing=None, pump=None)
    assert "pump" not in (c._blocked(c.rooms[0], 1) or "")
    c._execute_shot(c.rooms[0], 1, 6, 2.0)
    assert _switch_calls(fake) == [("turn_on", VALVE), ("turn_off", VALVE)]


# --------------------------------------------------------------------------- every declared layout
@pytest.mark.parametrize(
    "layout, pump, mainline, sequence",
    [
        ("valves_only", None, None, [("turn_on", VALVE), ("turn_off", VALVE)]),
        ("pump_valves", "switch.p", None,
         [("turn_on", "switch.p"), ("turn_on", VALVE), ("turn_off", VALVE), ("turn_off", "switch.p")]),
        ("mainline_valves", None, "switch.m",
         [("turn_on", "switch.m"), ("turn_on", VALVE), ("turn_off", VALVE), ("turn_off", "switch.m")]),
        ("pump_mainline_valves", "switch.p", "switch.m",
         [("turn_on", "switch.p"), ("turn_on", "switch.m"), ("turn_on", VALVE),
          ("turn_off", VALVE), ("turn_off", "switch.m"), ("turn_off", "switch.p")]),
    ],
)
def test_a_declared_layout_with_matching_switches_waters_in_order(layout, pump, mainline, sequence):
    c, fake = _room(plumbing=layout, pump=pump, mainline=mainline)
    room = c.rooms[0]
    assert room.hw["plumbing"] == layout
    assert "setup says" not in (c._blocked(room, 1) or "")
    c._execute_shot(room, 1, 6, 2.0)
    assert _switch_calls(fake) == sequence
    assert room.state[1]["shots"] == 1 and room.hardware_fault is None


@pytest.mark.parametrize(
    "layout, pump, mainline, says",
    [
        ("pump_valves", None, None, "has a pump, but no pump switch is mapped"),
        ("mainline_valves", None, None, "has a main-line valve, but no main-line valve switch is mapped"),
        ("pump_mainline_valves", "switch.p", None, "has a main-line valve, but no main-line valve switch"),
        ("pump_mainline_valves", None, "switch.m", "has a pump, but no pump switch is mapped"),
        ("valves_only", "switch.p", None, "has no pump, but a pump switch is mapped (switch.p)"),
        ("pump_valves", "switch.p", "switch.m", "has no main-line valve, but a main-line valve switch is mapped"),
    ],
)
def test_a_declaration_the_switches_contradict_is_held_both_ways(layout, pump, mainline, says):
    c, fake = _room(plumbing=layout, pump=pump, mainline=mainline)
    assert says in c._blocked(c.rooms[0], 1)
    c._execute_shot(c.rooms[0], 1, 6, 2.0)
    assert _switch_calls(fake) == []


def test_a_layout_from_a_newer_integration_is_held_not_guessed():
    c, fake = _room(plumbing="gravity_fed_manifold", pump="switch.p")
    assert "does not know" in c._blocked(c.rooms[0], 1)
    c._execute_shot(c.rooms[0], 1, 6, 2.0)
    assert _switch_calls(fake) == []


def test_a_mapped_pump_is_still_safed_and_gated_even_when_the_declaration_disowns_it():
    """The hold must never make hardware invisible: a pump that is mapped is a pump that gets turned
    off on exit and that has to read OFF before a setup change is adopted."""
    c, fake = _room(plumbing="valves_only", pump="switch.p")
    assert "switch.p" in c._hardware_entities(c.rooms[0])
    c._safe_off()
    assert ("turn_off", "switch.p") in _switch_calls(fake)


# --------------------------------------------------------------------------- discovery and adoption
def test_an_additional_room_carries_its_declaration():
    c, fake = _room()
    fake.set_state("sensor.crop_steering_gt1_engine_config", "ok",
                   _desc(prefix="gt1_", pump=None, mainline=None, valves={"1": "switch.gt1_valve"}, slug="gt1",
                         enable_flag="switch.crop_steering_gt1_engine_enabled", plumbing="valves_only"))
    fake.set_state("sensor.crop_steering_gt1_vwc_zone_1", "40", {})
    (room,) = c._discover_rooms()
    assert room.hw["plumbing"] == "valves_only"


def test_declaring_the_layout_is_a_setup_change_adopted_the_usual_way():
    c, fake = _room(pump="switch.p")
    attrs = dict(fake.states[DESCRIPTOR][1], setup_revision=1, active=True, active_zone_ids=[1],
                 plumbing="pump_valves")
    fake.set_state(DESCRIPTOR, "ok", attrs)
    c._apply_setup_descriptors()
    room = c.rooms[0]
    assert room._setup_pending and "plumbing" not in room.hw  # kill switch is ON: not adopted yet
    fake.set_state(KILL, "off")
    c._apply_setup_descriptors()
    assert room._setup_pending is None and room.hw["plumbing"] == "pump_valves"


# --------------------------------------------------------------------------- upgrade in place
def test_an_install_that_never_declared_keeps_its_saved_fingerprint_and_resumes():
    """The exact string a 0.15.x controller saved. If this fingerprint moved, every existing room
    would come back from the update blocked behind a disarm cycle (the 2026-09-20 outage)."""
    attrs = _states()["sensor.crop_steering_engine_config"][1]
    room = type("R", (), {"enable_flag": RESUME_KILL})()
    assert json.loads(controller.Controller._setup_fingerprint(attrs, room)) == {
        "active": True, "zones": [1], "pump": "switch.p", "mainline": "switch.m",
        "valves": {"1": "switch.v1"}, "enable_flag": RESUME_KILL,
        "feed_ec_sensor": "", "feed_ph_sensor": "",
    }
    first, _ = _start(_states(kill="off"))
    c, fake = _start(_states(kill="on"), state_path=first._state_path)
    assert c.rooms[0].setup_revision == 4 and c.rooms[0]._setup_pending is None
    assert "plumbing" not in c.rooms[0].hw


def test_a_declared_room_resumes_after_a_restart_and_a_changed_declaration_does_not():
    first, _ = _start(_states(kill="off", plumbing="pump_mainline_valves"))
    assert first.rooms[0].hw["plumbing"] == "pump_mainline_valves"
    same, _ = _start(_states(kill="on", plumbing="pump_mainline_valves"), state_path=first._state_path)
    assert same.rooms[0]._setup_pending is None and same.rooms[0].setup_revision == 4
    changed, _ = _start(_states(kill="on", plumbing="pump_valves"), state_path=first._state_path)
    assert changed.rooms[0]._setup_pending  # same revision number, different plumbing: not the setup it adopted


# --------------------------------------------------------------------------- one table, two copies
def test_the_controller_and_the_integration_agree_on_the_layouts():
    """The controller cannot import the integration (it runs in its own container), so the table
    exists twice. They must never drift: a layout only one side knows is a held room."""
    source = (pathlib.Path(__file__).parents[3] / "custom_components/crop_steering/plumbing.py").read_text()
    block = re.search(r"^PLUMBING_LAYOUTS = \{(.*?)^\}", source, re.S | re.M).group(1)
    theirs = {
        name: (pump == "True", mainline == "True")
        for name, pump, mainline in re.findall(r'"(\w+)":\s*\((True|False),\s*(True|False)\)', block)
    }
    assert theirs == controller.PLUMBING_LAYOUTS and len(theirs) == 4
