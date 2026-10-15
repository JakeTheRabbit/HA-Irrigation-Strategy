"""The reservoir minimum, the plan-ahead refill and the overfill guard (docs/USER_GUIDE.md, "Reservoir minimum").

Armed only by a tank level mapped in Rooms & setup: at or below 8 % every shot is held until the level reads 12 %
(CS-901), a level that reads nothing holds too (CS-902), a shot that would take the tank to its minimum waits and
a round that would asks for a refill (CS-903), and a fill is forced off at 102 % until the level reads 98 %
(CS-904). A room with no level mapped, as every upgraded room is, never holds here.
"""
import json

import pytest

import tank_level
from test_dosing_runner import BATCH, BALANCE, make_rig
from test_plan_hold_never_stops_rescues import rig  # noqa: F401 (rig: a pytest fixture)
from test_tank_level import DESCRIPTOR, DIST, FLOAT, LEVEL, _learned

pytestmark = pytest.mark.usefixtures("settings_built_in")

# Full at 100 mm down, empty at 1100 mm: the level is (1100 - mm) / 10 %.
MM = {2: "1080", 8: "1020", 10: "1000", 11.9: "981", 12: "980", 70: "400", 90: "200",
      98: "120", 99: "110", 100: "100", 102: "80"}


def _level(fake, pct, unit="mm"):
    fake.set_state(DIST, MM[pct], {"unit_of_measurement": unit})


def _mapped(fake, room, pct=70, float_state="off"):
    room.tank = tank_level.mapping(DESCRIPTOR)
    _level(fake, pct)
    fake.set_state(FLOAT, float_state)


def _cards(fake, code):
    return [data for domain, service, data in fake.calls
            if (domain, service) == ("persistent_notification", "create") and data["title"].endswith(f"({code})")]


def _dismissed(fake, key):
    return ("persistent_notification", "dismiss", {"notification_id": f"f2_{key}"}) in fake.calls


# ---------------------------------------------------------------- the bands
def test_the_minimum_holds_at_8_and_frees_at_12():
    held, seen = False, []
    for pct in (20, 9, 8, 10, 11.9, 12, 10):
        held = tank_level.below_minimum(held, pct)
        seen.append(held)
    assert seen == [False, False, True, True, True, False, False]


def test_the_overfill_guard_holds_at_102_and_frees_at_98():
    held, seen = False, []
    for pct in (100, 101.9, 102, 100, 98.1, 98, 101):
        held = tank_level.over_full(held, pct)
        seen.append(held)
    assert seen == [False, False, True, True, True, False, False]


# ---------------------------------------------------------------- the minimum holds the room's shots
def test_a_tank_at_its_minimum_holds_every_shot_until_it_reads_12(rig):  # noqa: F811
    c, fake, room = rig
    _mapped(fake, room, 10)
    assert c._blocked(room, 1) is None
    _level(fake, 8)
    assert c._blocked(room, 1) == "tank at its minimum (reads 8.0 %)"
    assert c._blocked(room, 2) == "tank at its minimum (reads 8.0 %)"
    [card] = _cards(fake, "CS-901")
    assert card["notification_id"] == "f2_tank_low_default"
    for pct in (10, 11.9):  # between the marks: still held
        _level(fake, pct)
        assert c._blocked(room, 1) == f"tank at its minimum (reads {pct:.1f} %)"
    _level(fake, 12)
    assert c._blocked(room, 1) is None
    assert _dismissed(fake, "tank_low_default")
    _level(fake, 10)  # falling again, above the minimum: watering carries on
    assert c._blocked(room, 1) is None


def test_a_low_float_holds_and_an_unreadable_level_holds(rig):  # noqa: F811
    c, fake, room = rig
    _mapped(fake, room, 70, float_state="on")  # mapped low when on
    assert c._blocked(room, 1) == "tank at its minimum (float reads low)"
    fake.set_state(FLOAT, "off")
    assert c._blocked(room, 1) is None
    fake.set_state(DIST, "unavailable")
    assert c._blocked(room, 1) == f"tank level unknown ({DIST})"
    assert _cards(fake, "CS-902")
    _level(fake, 70)
    assert c._blocked(room, 1) is None
    assert _dismissed(fake, "tank_unknown_default")


def test_a_room_with_no_tank_level_mapped_is_never_held(rig):  # noqa: F811
    """Open on upgrade: no room has a level mapped until its operator maps one, and a batch tank's full float, or
    a latch left in the state file by a level since removed, is not one."""
    c, fake, room = rig
    fake.set_state("binary_sensor.tank_full", "off")
    room.tank_drawdown.update(low=True, over=True)
    assert room.tank == {} and c._tank_hold(room) is None and c._blocked(room, 1) is None
    assert c._tank_over(room) is False and c._tank_short(room, 1, 500.0) is None
    assert not _cards(fake, "CS-901") and not _cards(fake, "CS-902")


def test_the_latches_survive_a_restart_and_old_state_files_load_open(rig):  # noqa: F811
    c, fake, room = rig
    _mapped(fake, room, 8)
    assert c._blocked(room, 1)
    _level(fake, 10)
    with open(c._state_path) as fh:
        saved = json.load(fh)
    assert saved["default"]["_tank"]["low"] is True
    room.tank_drawdown = tank_level.fresh()
    c._load_room_state(room, saved)
    assert c._blocked(room, 1) == "tank at its minimum (reads 10.0 %)"  # 10 % after a restart: still held
    c._load_room_state(room, {"default": {"_tank": {"base_pct": 10.0, "litres": 0, "litres_per_pct": None}}})
    assert room.tank_drawdown["low"] is False and room.tank_drawdown["over"] is False
    assert c._blocked(room, 1) is None


# ---------------------------------------------------------------- plan ahead
def test_a_shot_that_would_take_the_tank_to_its_minimum_waits_and_asks_for_a_refill(rig):  # noqa: F811
    c, fake, room = rig
    _mapped(fake, room, 10)
    room.tank_drawdown = _learned(tank_level.fresh())  # 40 L per 1 %
    assert c._blocked(room, 1) is None
    assert c._tank_short(room, 1, 40.0) is None  # 1 %: 9 % left
    c._watch_tank(room)
    assert not _cards(fake, "CS-903")
    assert c._tank_short(room, 1, 120.0) == (
        "this 120.0 L shot would take the tank from 10.0 % to 7.0 %, at or below its 8 % minimum")
    c._watch_tank(room)
    [card] = _cards(fake, "CS-903")
    assert "120.0 L" in card["message"] and fake.sets[LEVEL][1]["minimum_pct"] == 8.0
    _level(fake, 90)  # refilled
    c._watch_tank(room)
    assert _dismissed(fake, "tank_refill_default")


def test_a_waiting_shot_opens_nothing(rig, capsys):  # noqa: F811
    c, fake, room = rig
    room.tank = tank_level.mapping(DESCRIPTOR)
    fake.set_state(DIST, "1018", {"unit_of_measurement": "mm"})  # 8.2 %
    fake.set_state(FLOAT, "off")
    room.tank_drawdown = _learned(tank_level.fresh())
    assert c._blocked(room, 1) is None
    fake.calls.clear()
    c._execute_shot(room, 1, 60.0, 5.0)  # 14.175 L, about 0.35 %: to 7.85 %
    assert [call for call in fake.calls if call[0] != "persistent_notification"] == []
    assert "would take the tank from 8.2 % to 7.8 %" in capsys.readouterr().out
    assert room.tank_round == {1: pytest.approx(14.175)}


# ---------------------------------------------------------------- the overfill guard
def test_the_overfill_guard_latches_at_102_and_frees_at_98(rig):  # noqa: F811
    c, fake, room = rig
    _mapped(fake, room, 100)
    assert c._tank_over(room) is False
    _level(fake, 102)
    assert c._tank_over(room) is True
    assert len(_cards(fake, "CS-904")) == 1
    _level(fake, 99)
    assert c._tank_over(room) is True
    _level(fake, 98)
    assert c._tank_over(room) is False
    assert _dismissed(fake, "tank_over_default")
    assert c._blocked(room, 1) is None  # watering carries on throughout


def _batch(tmp_path, monkeypatch, pct):
    r = make_rig(tmp_path, monkeypatch)()
    room = r.c.rooms[0]
    room.tank = tank_level.mapping(DESCRIPTOR)
    _level(r.fake, pct)
    r.config(pumps=(BALANCE,), batch=dict(BATCH, recipe=[]))
    return r


def test_a_tank_over_its_full_mark_is_never_filled(tmp_path, monkeypatch):
    r = _batch(tmp_path, monkeypatch, 102)
    r.ask("batch")
    r.poll()
    steps = {s["step"]: (s["state"], s["note"]) for s in r.status()[1]["batch"]["steps"]}
    assert steps["fill"] == ("skipped", "the tank level reads over its full mark")
    assert ("turn_on", "switch.tank_fill") not in r.actions()
    assert "CS-904" in r.codes()


def test_a_fill_that_reaches_102_is_closed_before_its_float_reads_full(tmp_path, monkeypatch):
    r = _batch(tmp_path, monkeypatch, 90)
    r.full_after = None  # the full float never reads full
    r.clock.at(20, lambda: _level(r.fake, 102))
    r.ask("batch")
    r.poll()
    steps = {s["step"]: s["state"] for s in r.status()[1]["batch"]["steps"]}
    assert steps["fill"] == "done"
    assert r.actions("switch.tank_fill") == [("turn_on", "switch.tank_fill"), ("turn_off", "switch.tank_fill")]
    assert r.status()[1]["handled_result"] == "finished"
    assert "CS-904" in r.codes() and "CS-804" not in r.codes()
