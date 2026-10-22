"""Characterisation: every reason the controller gives today for not watering, word for word.

These pin what the code does TODAY, before the guard chain is refactored (Task 10). A string here
that differs from controller.py is a bug in the refactor, never a reason to edit the string.
The ORDER of the checks is pinned too: STAGES lists the holds of Controller._blocked in the order the
code asks them, and test_the_order_of_blocked_is_pinned peels them off one by one.
"""
from __future__ import annotations

import pytest

import controller
import tank_level
from test_blind_grace import _Clock
from test_controller import _build, _desc
from test_room_status import _room as _blind_room

pytestmark = pytest.mark.usefixtures("settings_built_in")

KILL = "input_boolean.kill"
ZONE_SWITCH = "switch.crop_steering_zone_1_enabled"
FLUSH = "input_boolean.flush"
FEED_EC, FEED_PH = "sensor.feed_ec", "sensor.feed_ph"
TANK_DIST = "sensor.tank_distance"
WASTE = "switch.waste"
LATCH = (f"max-run latch: {controller.MAX_RUN_IN_A_ROW} shots in a row cut to the longest allowed shot; "
         "fix its Repairs card (CS-312) to water again")
NOT_SWITCHABLE = "a zone valve, main line or pump must be a switch, input_boolean or valve"
PLUMBING_TEXT = ("setup says this room has no main-line valve, but a main-line valve switch is mapped (switch.m) - "
                 "not watering until they agree; clear it, or change the room's plumbing")


def _room():
    """A one-zone room, prefix "", that nothing holds: _blocked(room, 1) is None."""
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: ("on", {}),
        "switch.crop_steering_room_active": ("on", {}),
        ZONE_SWITCH: ("on", {}),
        "switch.crop_steering_zone_1_manual_override": ("off", {}),
        FLUSH: ("off", {}),
    }
    c, fake = _build({"num_zones": 1, "enable_flag": KILL, "hold_entities": [FLUSH]}, states=states)
    room = c.rooms[0]
    assert room.hw["valves"] == {1: "switch.v1"} and room.prefix == ""
    assert c._blocked(room, 1) is None
    return c, fake, room


# ---- the holds: each is (name, apply, undo, the text _blocked returns). `mp` is pytest's monkeypatch.
def _setup_pending(c, fake, room, mp):
    room._setup_pending = "Invalid setup descriptor: no valves"


def _plan_hold(c, fake, room, mp):
    room.strategy_snapshot = {"required": True, "error": "plan unreadable"}


def _fault(c, fake, room, mp):
    room.hardware_fault = {"reason": "unconfirmed hardware close", "entities": ["switch.v1"], "switches": []}


def _latch(c, fake, room, mp):
    room.state[1]["max_run_latch"] = {"since": "2026-10-22T10:00:00", "resets": 0}
    fake.set_state("switch.crop_steering_max_run_latch", "on", {"resets": 0})


def _no_hardware(c, fake, room, mp):
    room.hw["valves"] = {}


def _plumbing(c, fake, room, mp):
    room.hw["plumbing"] = "pump_valves"


def _undrivable(c, fake, room, mp):
    room.hw["pump"] = "light.p"


def _retired(c, fake, room, mp):
    room._retired_off = ["switch.old_engine"]


def _waste_open(c, fake, room, mp):
    room.waste = WASTE
    fake.set_state(WASTE, "on")
    fake.set_state("select.crop_steering_waste_valve_rule", controller.WASTE_CHECK)


def _settings_loading(c, fake, room, mp):
    mp.setattr(controller, "SETTINGS_WAIT_PASSES", 3)
    room._settings_missing = {"number.crop_steering_p1_target_vwc"}


def _tank_min(c, fake, room, mp):
    room.tank = tank_level.mapping({"tank_distance_sensor": TANK_DIST,
                                    "tank_level": {"full_mm": 100, "empty_mm": 1100}})
    fake.set_state(TANK_DIST, "102.0", {"unit_of_measurement": "cm"})  # 1020 mm of 100..1100 = 8.0 %


def _ec_out(c, fake, room, mp):
    room.feed_ec_sensor = FEED_EC
    fake.set_state(FEED_EC, "4.0")
    fake.set_state("number.crop_steering_irrigation_ec_min", "0")
    fake.set_state("number.crop_steering_irrigation_ec_max", "1")


def _ph_dead(c, fake, room, mp):
    room.feed_ph_sensor = FEED_PH
    room._feed_ph_last_good_time = None
    fake.set_state(FEED_PH, "unavailable")
    fake.set_state("number.crop_steering_irrigation_ph_min", "5.5")
    fake.set_state("number.crop_steering_irrigation_ph_max", "6.5")


def _offline(c, fake, room, mp):
    fake.set_state("switch.m", "unavailable")


# (name, apply, undo, expected text). The order IS the order of Controller._blocked.
STAGES = [
    ("setup_pending", _setup_pending, lambda c, f, r: setattr(r, "_setup_pending", None),
     lambda c: "Invalid setup descriptor: no valves"),
    ("archived", lambda c, f, r, mp: setattr(r, "setup_active", False),
     lambda c, f, r: setattr(r, "setup_active", True), lambda c: "Room archived in integration setup"),
    ("room_off", lambda c, f, r, mp: f.set_state("switch.crop_steering_room_active", "off"),
     lambda c, f, r: f.set_state("switch.crop_steering_room_active", "on"),
     lambda c: "Room off (nothing growing)"),
    ("batch_running",
     lambda c, f, r, mp: setattr(c, "dosing", type("D", (), {"holds": staticmethod(lambda room: "making a batch")})()),
     lambda c, f, r: setattr(c, "dosing", None), lambda c: "making a batch"),
    ("plan_hold", _plan_hold, lambda c, f, r: setattr(r, "strategy_snapshot", None),
     lambda c: "Strategy hold: plan unreadable"),
    ("hardware_fault", _fault, lambda c, f, r: setattr(r, "hardware_fault", None),
     lambda c: "hardware fault (CS-301): unconfirmed hardware close"),
    ("max_run_latched", _latch, lambda c, f, r: r.state[1].update(max_run_latch=None, capped_in_a_row=0),
     lambda c: LATCH),
    ("no_hardware", _no_hardware, lambda c, f, r: r.hw.update(valves={1: "switch.v1"}),
     lambda c: "no hardware mapped — set this zone's valve (and the pump and mainline, if the room has them) "
               "in the Crop Steering integration (or the add-on `hardware` option)"),
    ("plumbing", _plumbing, lambda c, f, r: r.hw.pop("plumbing", None), lambda c: PLUMBING_TEXT),
    ("undrivable", _undrivable, lambda c, f, r: r.hw.update(pump="switch.p"),
     lambda c: f"light.p can't be switched ({NOT_SWITCHABLE})"),
    ("kill_off", lambda c, f, r, mp: f.set_state(KILL, "off"), lambda c, f, r: f.set_state(KILL, "on"),
     lambda c: "Crop Steering Controller disabled (kill switch off)"),
    ("retired_switch", _retired, lambda c, f, r: setattr(r, "_retired_off", None),
     lambda c: "switch.old_engine off: engine switch switched off in its place"),
    ("zone_unreadable", lambda c, f, r, mp: f.set_state(ZONE_SWITCH, "unavailable"),
     lambda c, f, r: f.set_state(ZONE_SWITCH, "on"),  # the zone ENABLE switch, not the valve
     lambda c: f"{ZONE_SWITCH} unreadable (reads neither on nor off)"),
    ("zone_off", lambda c, f, r, mp: f.set_state(ZONE_SWITCH, "off"),
     lambda c, f, r: f.set_state(ZONE_SWITCH, "on"), lambda c: "zone disabled"),
    ("manual_override",
     lambda c, f, r, mp: f.set_state("switch.crop_steering_zone_1_manual_override", "on"),
     lambda c, f, r: f.set_state("switch.crop_steering_zone_1_manual_override", "off"),
     lambda c: "manual override"),
    ("external_hold", lambda c, f, r, mp: f.set_state(FLUSH, "on"), lambda c, f, r: f.set_state(FLUSH, "off"),
     lambda c: "external hold (flush)"),
    ("waste_valve", _waste_open, lambda c, f, r: setattr(r, "waste", ""),
     lambda c: f"waste valve {WASTE} reads on"),
    ("settings_loading", _settings_loading, lambda c, f, r: setattr(r, "_settings_missing", set()),
     lambda c: "waiting for its settings to load (number.crop_steering_p1_target_vwc)"),
    ("tank_min", _tank_min, lambda c, f, r: setattr(r, "tank", {}),
     lambda c: "tank at its minimum (reads 8.0 %)"),
    ("feed_ec_out", _ec_out, lambda c, f, r: setattr(r, "feed_ec_sensor", None),
     lambda c: "source-water EC 4.0 out of [0,1]"),
    ("feed_ph_dead", _ph_dead, lambda c, f, r: setattr(r, "feed_ph_sensor", None),
     lambda c: "source-water pH probe dead >30min — holding (fail-closed)"),
    ("feed_path_offline", _offline, lambda c, f, r: f.set_state("switch.m", "off"),
     lambda c: "switch.m offline (reads neither on nor off)"),
]
NAMES = [s[0] for s in STAGES]


@pytest.mark.parametrize("name,apply,undo,expect", STAGES, ids=NAMES)
def test_blocked_reason_is_pinned(name, apply, undo, expect, monkeypatch):
    c, fake, room = _room()
    apply(c, fake, room, monkeypatch)
    assert c._blocked(room, 1) == expect(c)
    undo(c, fake, room)
    assert c._blocked(room, 1) is None  # and each undo really frees the zone


def test_the_feed_grace_default_is_thirty_minutes():
    c, _fake, _room_ = _room()
    assert c.feed_grace_min == 30


def test_the_order_of_blocked_is_pinned(monkeypatch):
    """Every hold on at once: the first in STAGES shows, and peeling them in order shows each next one.
    zone_off is left out: it is the same switch as zone_unreadable, which is asked first (see below)."""
    stages = [s for s in STAGES if s[0] != "zone_off"]
    c, fake, room = _room()
    for _name, apply, _undo, _expect in stages:
        apply(c, fake, room, monkeypatch)
    seen = []
    for _name, _apply, undo, _expect in stages:
        seen.append(c._blocked(room, 1))
        undo(c, fake, room)
    seen.append(c._blocked(room, 1))
    assert seen == [expect(c) for _n, _a, _u, expect in stages] + [None]


def test_first_hold_wins_in_todays_order():
    c, fake, room = _room()
    _tank_min(c, fake, room, None)
    fake.set_state(ZONE_SWITCH, "off")
    fake.set_state(KILL, "off")
    assert c._blocked(room, 1) == "Crop Steering Controller disabled (kill switch off)"
    fake.set_state(KILL, "on")
    assert c._blocked(room, 1) == "zone disabled"
    fake.set_state(ZONE_SWITCH, "on")
    assert c._blocked(room, 1) == "tank at its minimum (reads 8.0 %)"


# ---- the variants of a hold that the ordered table has one text for
def test_a_plan_hold_on_a_zone_names_its_status():
    c, _fake, room = _room()
    room.strategy_snapshot = {"required": True, "managed": {1}, "zones": {1: {"status": "paused"}}}
    assert c._blocked(room, 1) == "Strategy zone paused"
    room.strategy_snapshot = {"required": True, "managed": {1}, "zones": {}}
    assert c._blocked(room, 1) == "Strategy zone unavailable"


@pytest.mark.parametrize("kind", sorted(controller.PLAN_HOLD_EXEMPT))
def test_a_plan_hold_lets_the_exempt_kinds_through_and_says_so(kind, capsys):
    c, _fake, room = _room()
    _plan_hold(c, _fake, room, None)
    reason = type("R", (), {"kind": kind})()
    assert c._blocked(room, 1, reason) is None
    assert f"[default] Z1 Strategy hold: plan unreadable: not holding a {kind} shot" in capsys.readouterr().out


def test_a_plan_hold_still_holds_a_steering_shot():
    c, _fake, room = _room()
    _plan_hold(c, _fake, room, None)
    assert c._blocked(room, 1, type("R", (), {"kind": "p2_top_up"})()) == "Strategy hold: plan unreadable"


def test_a_hold_home_assistant_does_not_have_is_said_in_its_own_words():
    c, fake, room = _room()
    fake.states.pop(FLUSH)
    assert c._blocked(room, 1) == (f"Hold entity {FLUSH} does not exist in Home Assistant. Remove it from the "
                                   "app's hold entities, or create it.")


def test_a_hold_that_cannot_be_read_names_the_entity():
    c, fake, room = _room()
    fake.set_state(FLUSH, "unavailable")
    assert c._blocked(room, 1) == f"external hold {FLUSH} unreadable (reads neither on nor off)"


def test_a_tank_level_that_cannot_be_read_holds():
    c, fake, room = _room()
    room.tank = tank_level.mapping({"tank_distance_sensor": TANK_DIST,
                                    "tank_level": {"full_mm": 100, "empty_mm": 1100}})
    fake.set_state(TANK_DIST, "unavailable")
    assert c._blocked(room, 1) == f"tank level unknown ({TANK_DIST})"


def test_source_water_ec_dead_past_the_grace_holds_fail_closed():
    c, fake, room = _room()
    room.feed_ec_sensor = FEED_EC
    room._feed_last_good_time = None
    fake.set_state(FEED_EC, "unavailable")
    fake.set_state("number.crop_steering_irrigation_ec_min", "0.5")
    fake.set_state("number.crop_steering_irrigation_ec_max", "2")
    assert c._blocked(room, 1) == "source-water EC dead >30min — holding (fail-closed)"


def test_source_water_ph_out_of_band_holds():
    c, fake, room = _room()
    room.feed_ph_sensor = FEED_PH
    fake.set_state(FEED_PH, "7.0")
    fake.set_state("number.crop_steering_irrigation_ph_min", "5.5")
    fake.set_state("number.crop_steering_irrigation_ph_max", "6.5")
    assert c._blocked(room, 1) == "source-water pH 7.00 out of [5.5,6.5]"


# ---------------------------------------------------------------- the pre-open stage (_execute_shot)
def _x_fault(c, fake, room):
    _fault(c, fake, room, None)


def _x_token(c, fake, room):
    controller._GATE.state = "refused"


def _x_inflight(c, fake, room):
    room.shot_inflight = {"zone": 1, "valve": "switch.v1", "mainline": "switch.m", "pump": "switch.p",
                          "started": "2026-10-22T10:00:00+00:00"}


def _x_strategy(c, fake, room):
    room._strategy_batch_invalid = True


def _x_tank_short(c, fake, room):
    room.tank = tank_level.mapping({"tank_distance_sensor": TANK_DIST,
                                    "tank_level": {"full_mm": 100, "empty_mm": 1100}})
    room.tank_reading = (9.0, None)
    room.tank_drawdown = tank_level.fresh()
    room.tank_drawdown["litres_per_pct"] = 40.0


def _x_waste(c, fake, room):
    _waste_open(c, fake, room, None)


def _x_batch(c, fake, room):
    c.dosing = type("D", (), {"holds": staticmethod(lambda r: "making a batch")})()


HELD = "[default] Z1 shot held: "
# (name, apply, undo, the log line it leaves; None = held silently). Order of Controller._execute_shot.
PREOPEN = [
    ("hardware_fault", _x_fault, lambda c, f, r: setattr(r, "hardware_fault", None), None),
    ("token_refused", _x_token, lambda c, f, r: setattr(controller._GATE, "state", None),
     HELD + "Home Assistant refuses this controller's token"),
    ("inflight", _x_inflight, lambda c, f, r: setattr(r, "shot_inflight", None),
     HELD + "an interrupted shot's hardware is not accounted for yet"),
    ("plumbing", lambda c, f, r: _plumbing(c, f, r, None), lambda c, f, r: r.hw.pop("plumbing", None),
     HELD + PLUMBING_TEXT),
    ("undrivable", lambda c, f, r: _undrivable(c, f, r, None), lambda c, f, r: r.hw.update(pump="switch.p"),
     HELD + "light.p can't be switched"),
    ("strategy", _x_strategy, lambda c, f, r: setattr(r, "_strategy_batch_invalid", False),
     HELD + "Strategy changed or held; recompute the irrigation batch on the next loop"),
    ("tank_short", _x_tank_short, lambda c, f, r: setattr(r, "tank", {}),
     HELD + "this 100.0 L shot would take the tank from 9.0 % to 6.5 %, at or below its 8 % minimum"),
    ("waste_not_closed", _x_waste, lambda c, f, r: setattr(r, "waste", ""),
     HELD + "the waste valve did not close"),
    ("batch_running", _x_batch, lambda c, f, r: setattr(c, "dosing", None), HELD + "making a batch"),
]
PRE_NAMES = [p[0] for p in PREOPEN]


def _opened(fake):
    """Anything that would open water: a turn_on, open_valve or open on any domain."""
    return [call for call in fake.calls if call[1] in ("turn_on", "open_valve", "open")]


def _shot(c, room):
    c._execute_shot(room, 1, 10, 5, flow_lps=10.0)


@pytest.mark.parametrize("name,apply,undo,line", PREOPEN, ids=PRE_NAMES)
def test_preopen_stage_log_is_pinned(name, apply, undo, line, capsys, monkeypatch):
    c, fake, room = _room()
    monkeypatch.setattr(controller, "_GATE", controller._AuthGate())  # a fresh gate per case
    apply(c, fake, room)
    fake.calls.clear()
    capsys.readouterr()
    _shot(c, room)
    out = capsys.readouterr().out
    if line is None:
        assert "shot held" not in out  # a hardware fault returns without a word
    else:
        assert line in out
    assert _opened(fake) == [] and not c._busy  # nothing opened


def test_the_order_of_the_preopen_stage_is_pinned(capsys, monkeypatch):
    """Every hold on at once; peeled in order, each next one is what _execute_shot says."""
    c, fake, room = _room()
    monkeypatch.setattr(controller, "_GATE", controller._AuthGate())
    for _name, apply, _undo, _line in PREOPEN:
        apply(c, fake, room)
    fake.calls.clear()
    seen = []
    for _name, _apply, undo, _line in PREOPEN:
        capsys.readouterr()
        _shot(c, room)
        seen.append(capsys.readouterr().out)
        undo(c, fake, room)
    assert _opened(fake) == []
    assert "shot held" not in seen[0]
    for out, (_name, _a, _u, line) in zip(seen[1:], PREOPEN[1:]):
        assert line in out
        assert out.count("shot held") == 1


def test_a_plan_exempt_shot_does_not_wait_on_the_strategy_preflight(capsys):
    c, fake, room = _room()
    _x_strategy(c, fake, room)
    _x_batch(c, fake, room)
    capsys.readouterr()
    c._execute_shot(room, 1, 10, 5, flow_lps=10.0, plan_exempt=True)
    out = capsys.readouterr().out
    assert HELD + "making a batch" in out and "Strategy changed" not in out


# ---------------------------------------------------------------- _act_zone
def _cap_rig():
    c, fake, room = _room()
    room.state[1]["daily_vol"] = 1000.0
    p = type("P", (), {"max_daily_volume": 5.0, "watchdog_hours": 0, "p2_threshold": 0})()
    c._zone_flow_lps = lambda room, zone: 0.1
    c._substrate_l = lambda room, zone: 3.0
    c._room_duration_cap = lambda room: 600
    return c, fake, room, p


def test_daily_cap_hold_is_pinned(capsys):
    c, _fake, room, p = _cap_rig()
    told = []
    c._alert_daily_cap = lambda *a, **k: told.append(a)
    reason = type("R", (), {"cap_exempt": False, "kind": "p1", "seconds": 0})()
    out = c._act_zone(room, 1, p, None, (True, 10.0, reason), None, True, controller.datetime.now())
    assert out == (False, 0.0, "BLOCK daily-cap (0.00 L left)")
    assert "BLOCK daily-cap (0.00 L left)" in capsys.readouterr().out
    assert [a[-1] for a in told] == ["BLOCK daily-cap (0.00 L left)"]  # the same text goes to the CS-205 card
    assert told[0][3] is True  # blind: no snapshot


def test_a_blocked_shot_logs_what_it_would_have_done(capsys):
    c, _fake, room, p = _cap_rig()
    phase = room.state[1]["phase"]
    c._act_zone(room, 1, p, None, (True, 10.0, "water the zone"), "zone disabled", True, controller.datetime.now())
    assert f"[default] Z1 {phase} BLOCKED (zone disabled): would water the zone" in capsys.readouterr().out


@pytest.fixture
def pinned_clock(monkeypatch):
    """The wall clock test_blind_grace pins (14:00, lights on), for the one test that runs a whole loop."""
    _Clock.current = _Clock(2026, 9, 25, 14, 0)
    monkeypatch.setattr(controller, "datetime", _Clock)


@pytest.mark.usefixtures("no_blind_grace", "pinned_clock")
def test_a_blind_zone_over_its_budget_is_held_with_the_blind_budget_text():
    c, fake = _blind_room("on")
    c.rooms[0].state[1].update(daily_vol=1000.0, last_daily_reset=_Clock.now().date(), last_shot=None)
    seen = []
    real = c._act_zone
    c._act_zone = lambda *a, **k: (seen.append(a[4]), real(*a, **k))[1]
    c.loop_once(_Clock.now())
    [(fire, size, reason)] = seen
    assert (fire, size) == (False, 0.0)
    assert reason.startswith("BLOCK daily-cap 1000/") and reason.endswith("L (blind irrigation budget)")
    assert _opened(fake) == []
