"""pH auto-correct of a room's batch tank (docs/DOSING.md, pH auto-correct): off unless switched on, never on a
probe that is dead, implausible, jumping or not yet steady, and every way a correction can end: reaching the
band, a dose that does not move the pH, an overshoot, a probe that can't be read after the mix, doses that are
not enough, the daily cap, a mix pump that does not start, a stop, the kill switch and a restart. Any end but the
band locks it (CS-809) until a person switches it off, and the source-water gate is never loosened.

Driven through the real Controller and dosing runner on the fake clock of test_dosing_runner.py.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

import ph_correct
from test_dosing_runner import BALANCE, BATCH, KILL, make_rig

PH = "sensor.tank_ph"
SWITCH = "switch.crop_steering_ph_auto_correct"
UP = dict(BALANCE, ph_role="ph_up")
DOWN = dict(BALANCE, id="acid", name="Acid", volume_entity="number.acid_volume",
            start_entity="button.acid_start", dosing_entity="binary_sensor.acid_dosing",
            power_entity="switch.acid_power", flow_entity="number.acid_flow", ph_role="ph_down")


@pytest.fixture
def build(tmp_path, monkeypatch):
    make = make_rig(tmp_path, monkeypatch)

    def go(ph="5.6", switch="on", pumps=(UP,), batch=None, **states):
        r = make(
            states={SWITCH: (switch, {}), "number.crop_steering_irrigation_ph_min": ("5.8", {}),
                    "number.crop_steering_irrigation_ph_max": ("6.5", {}),
                    **{k: (v, {}) for k, v in states.items()}},
            options={"num_zones": 1, "enable_flag": KILL, "feed_ph_sensor": PH},
        )
        r.config(pumps=pumps, batch=dict(BATCH, recipe=[]) if batch is None else batch)
        r.ph = float(ph) if ph not in ("unavailable",) else None
        r.set(PH, ph)
        r.moves = []  # what each dose does to the tank's pH, in order (the last repeats)
        original = r._press

        def press(entity):
            original(entity)
            pump = r.pumps[entity]
            seconds = float(r.fake.states[pump["volume_entity"]][0]) / float(r.fake.states[pump["flow_entity"]][0])
            move = r.moves.pop(0) if len(r.moves) > 1 else (r.moves[0] if r.moves else 0.0)

            def mixed():
                if move is None:
                    r.ph = None
                    r.set(PH, "unavailable")
                else:
                    r.ph = round(r.ph + move, 3)
                    r.set(PH, f"{r.ph:g}")
            r.clock.at(seconds + 1, mixed)

        r._press = press
        return r

    return go


def minutes(r, n):
    """n minutes of the main loop: the probe reports each minute (so it is never stale), dosing polls."""
    for _ in range(n):
        r.clock.sleep(60)
        r.set(PH, "unavailable" if r.ph is None else f"{r.ph:g}")
        r.fake.states[PH] = (r.fake.states[PH][0], r.fake.states[PH][1], r.clock.now().isoformat())
        r.poll()


def presses(r):
    return [entity for service, entity in r.actions() if service == "press"]


def ph_block(r):
    return r.saved().get("ph") or {}


def test_off_by_default_nothing_is_dosed(build):
    r = build(switch="off")
    minutes(r, 15)
    assert presses(r) == [] and r.codes() == []


def test_an_install_without_the_switch_never_doses(build):
    r = build()
    del r.fake.states[SWITCH]
    minutes(r, 15)
    assert presses(r) == []


def test_a_low_tank_is_held_mixed_dosed_mixed_and_read_until_inside_its_band(build):
    r = build()
    r.moves = [0.3]  # 5.6 -> 5.9: inside 5.8-6.5 by the 0.1 margin
    minutes(r, 4)
    assert presses(r) == []  # not steady for 5 minutes yet
    minutes(r, 3)
    assert presses(r) == ["button.balance_start"]
    acts = r.actions("input_boolean.tank_hold", "switch.tank_mixer", "button.balance_start")
    assert acts[:3] == [("turn_on", "input_boolean.tank_hold"), ("turn_on", "switch.tank_mixer"),
                        ("press", "button.balance_start")]
    assert acts[-2:] == [("turn_off", "switch.tank_mixer"), ("turn_off", "input_boolean.tank_hold")]
    sets = [d["value"] for dom, svc, d in r.fake.calls if svc == "set_value" and d["entity_id"] == "number.balance_volume"]
    assert sets[0] == 50  # 5 s at 10 mL/s
    entry = r.status()[1]["history"][0]
    assert entry["kind"] == "correct" and entry["result"] == "finished: the tank is inside its band"
    assert entry["ph"] == [5.6, 5.9]
    assert "CS-809" not in r.codes()
    assert ph_block(r)["doses"] == 1 and ph_block(r)["latch"] is None
    assert r.saved()["inflight"] is None and r.runner.holds(r.c.rooms[0]) is None
    minutes(r, 10)
    assert presses(r) == ["button.balance_start"]  # inside its band: nothing more


def test_the_room_is_held_while_it_corrects(build):
    r = build()
    seen = []
    original = r.call

    def watch(domain, service, **data):
        if service == "press":
            seen.append(r.runner.holds(r.c.rooms[0]))
        return original(domain, service, **data)

    r.runner._call = watch
    r.moves = [0.3]
    minutes(r, 7)
    assert seen == ["correcting the batch tank's pH"]


def test_a_high_tank_is_corrected_down_by_the_ph_down_pump(build):
    r = build(ph="6.9", pumps=(UP, DOWN), **{"number.acid_volume": "0", "button.acid_start": "unknown",
                                              "binary_sensor.acid_dosing": "off", "switch.acid_power": "off",
                                              "number.acid_flow": "10"})
    r.pumps[DOWN["start_entity"]] = DOWN
    r.moves = [-0.6]
    minutes(r, 7)
    assert presses(r) == ["button.acid_start"]
    assert r.status()[1]["history"][0]["ph"] == [6.9, 6.3]


@pytest.mark.parametrize("readings", [["5.6", "2.5", "5.6"], ["5.6", "6.9", "5.6"], ["5.6", "unavailable", "5.6"]])
def test_an_implausible_jumping_or_dead_reading_restarts_the_wait(build, readings):
    r = build()
    for value in readings:
        r.ph = None if value == "unavailable" else float(value)
        minutes(r, 2)
    assert presses(r) == []  # 6 minutes in all, but never 5 steady ones


def test_a_stale_reading_never_doses(build):
    r = build()
    old = (r.clock.now() - timedelta(seconds=ph_correct.PROBE_MAX_AGE_S + 60)).isoformat()
    r.fake.states[PH] = ("5.6", {}, old)  # the probe stopped reporting long ago
    for _ in range(15):
        r.clock.sleep(60)
        r.poll()
    assert presses(r) == []


def test_a_dose_that_does_not_move_the_ph_stops_alerts_and_locks(build):
    r = build()
    r.moves = [0.02]
    minutes(r, 7)
    assert presses(r) == ["button.balance_start"]  # one dose, not a second
    assert r.status()[1]["history"][0]["result"] == "finished: a dose did not move the pH"
    assert "CS-809" in r.codes()
    assert "locked" in r.alert("CS-809")["message"]
    assert ph_block(r)["latch"] is not None
    minutes(r, 20)
    assert presses(r) == ["button.balance_start"]  # locked
    # A person switches it off and on: unlocked, and it corrects again (after 5 steady minutes).
    r.set(SWITCH, "off")
    minutes(r, 2)
    assert ph_block(r)["latch"] is None
    r.set(SWITCH, "on")
    minutes(r, 7)
    assert presses(r) == ["button.balance_start"] * 2


@pytest.mark.parametrize("state", ["unknown", "unavailable", None])
def test_an_unreadable_switch_keeps_the_fault_locked_after_recovery(build, state):
    r = build()
    r.moves = [0.02]
    minutes(r, 7)
    latch = ph_block(r)["latch"]
    assert latch is not None
    if state is None:
        del r.fake.states[SWITCH]
    else:
        r.set(SWITCH, state)
    minutes(r, 2)
    assert ph_block(r)["latch"] == latch
    r.set(SWITCH, "on")
    minutes(r, 10)
    assert presses(r) == ["button.balance_start"]
    assert ph_block(r)["latch"] == latch
    r.set(SWITCH, "off")
    minutes(r, 2)
    assert ph_block(r)["latch"] is None
    r.set(SWITCH, "on")
    minutes(r, 7)
    assert presses(r) == ["button.balance_start"] * 2


def test_a_new_fill_unlocks_it(build):
    r = build()
    r.moves = [0.02]
    minutes(r, 7)
    assert ph_block(r)["latch"] is not None
    r.set("input_datetime.tank_filled", "2026-09-28 05:00:00")
    minutes(r, 8)
    assert len(presses(r)) == 2


def test_an_overshoot_stops_and_locks(build):
    r = build()
    r.moves = [1.0]  # 5.6 -> 6.6, past 6.5
    minutes(r, 7)
    assert r.status()[1]["history"][0]["result"] == "finished: the pH went past the other side of its band"
    assert "CS-809" in r.codes() and ph_block(r)["latch"] is not None


def test_doses_that_are_not_enough_stop_at_the_tries_and_lock(build):
    r = build()
    r.moves = [0.1]  # 5.6 -> 5.7 -> 5.8: never 5.9
    minutes(r, 20)
    assert presses(r) == ["button.balance_start"] * 2  # max_tries 2 by default
    assert r.status()[1]["history"][0]["result"] == "finished: the doses did not bring the tank into its band"
    assert "CS-809" in r.codes()


def test_the_probe_unreadable_after_the_mix_stops_and_locks(build):
    r = build()
    r.moves = [None]
    minutes(r, 7)
    assert r.status()[1]["history"][0]["result"] == "finished: the probe could not be read after the mix"
    assert ph_block(r)["latch"] is not None


def test_the_daily_cap_is_never_passed(build):
    r = build(**{"number.crop_steering_ph_correct_daily_max": "3"})
    r.moves = [0.06]  # 5.6 -> 5.66 -> 5.72 -> 5.78: still under 5.8
    minutes(r, 20)  # 2 doses, not enough: locked
    r.set(SWITCH, "off")
    minutes(r, 2)
    r.set(SWITCH, "on")
    minutes(r, 20)  # 1 dose left today
    assert len(presses(r)) == 3
    r.set(SWITCH, "off")
    minutes(r, 2)
    r.set(SWITCH, "on")
    minutes(r, 20)
    assert len(presses(r)) == 3
    assert any("doses a day it may give are used" in a["message"] for a in r.creates("CS-809"))


def test_a_mix_pump_that_does_not_start_never_doses(build):
    r = build()
    r.watts = 0
    minutes(r, 7)
    assert presses(r) == []
    assert "CS-805" in r.codes()
    assert r.status()[1]["history"][0]["result"].startswith("stopped: mix:")
    assert ph_block(r)["latch"] is not None
    assert ("turn_off", "switch.tank_mixer") in r.actions() and r.fake.states["input_boolean.tank_hold"][0] == "off"


def test_no_pump_with_the_role_is_told_once_a_day(build):
    r = build(pumps=(BALANCE,))
    minutes(r, 30)
    assert presses(r) == []
    refusals = r.creates("CS-809")
    assert len(refusals) == 1 and "no dosing pump has the pH up role" in refusals[0]["message"]


def test_no_mix_pump_never_doses(build):
    r = build(batch=dict(BATCH, recipe=[], mix_pump=None, mix_valves=[]))
    minutes(r, 10)
    assert presses(r) == []
    assert "no mixing pump" in r.alert("CS-809")["message"]


def test_the_kill_switch_off_never_doses(build):
    r = build()
    r.set(KILL, "off")
    minutes(r, 15)
    assert presses(r) == [] and r.codes() == []


def test_the_kill_switch_off_mid_correction_ends_it_before_the_next_dose(build):
    r = build()
    r.moves = [0.1]
    original = r._press

    def press(entity):
        original(entity)
        r.set(KILL, "off")  # a person stops the room during the first dose

    r._press = press
    minutes(r, 20)
    assert presses(r) == ["button.balance_start"]  # no second dose
    assert r.status()[1]["history"][0]["result"] == "stopped: postmix: the room or its kill switch was switched off"
    assert r.fake.states["switch.tank_mixer"][0] == "off" and r.fake.states["input_boolean.tank_hold"][0] == "off"


def test_a_hold_already_on_waits(build):
    r = build(**{"input_boolean.tank_hold": "on"})
    minutes(r, 15)
    assert presses(r) == []


def test_a_stop_ends_it_switches_off_and_locks(build):
    r = build()
    r.moves = [0.1]
    original = r._press

    def press(entity):
        original(entity)
        r.ask("stop")  # a person stops it mid-dose

    r._press = press
    minutes(r, 7)
    assert r.status()[1]["history"][0]["result"].startswith("stopped")
    assert r.fake.states["switch.tank_mixer"][0] == "off" and r.fake.states["input_boolean.tank_hold"][0] == "off"
    assert ph_block(r)["latch"] is not None


def test_a_restart_mid_correction_is_recovered_never_resumed(build, tmp_path):
    r = build()
    r.moves = [0.1]
    original = r._press

    def press(entity):
        original(entity)
        r.runner.stop_starting()  # the app is stopped (SIGTERM) mid-dose

    r._press = press
    minutes(r, 7)
    record = r.saved()["inflight"]
    assert record["kind"] == "correct" and record["hold"] == "input_boolean.tank_hold"
    assert r.fake.states["input_boolean.tank_hold"][0] == "on"  # left for the next start
    again = r.build(tmp_path / "dosing_state.json")
    r.c.dosing = again
    r._press = original
    assert again.recover()
    for _ in range(5):
        r.clock.sleep(2)
        r.poll(again)
    assert "CS-803" in r.codes()
    assert r.fake.states["switch.tank_mixer"][0] == "off" and r.fake.states["input_boolean.tank_hold"][0] == "off"
    assert again.holds(r.c.rooms[0]) is None
    assert again._doc["rooms"]["default"]["history"][0]["kind"] == "correct"
    assert len(presses(r)) == 1  # never resumed


def test_the_source_water_gate_is_never_loosened(build):
    from datetime import datetime, timezone

    sizing = {f"number.crop_steering_{key}": "4" for key in
              ("substrate_volume", "plant_count", "drippers_per_plant", "dripper_flow_rate", "max_daily_volume")}
    r = build(**{"switch.crop_steering_zone_1_enabled": "on"}, **sizing)
    r.moves = [0.02]
    minutes(r, 7)
    assert ph_block(r)["latch"] is not None
    r.fake.states[PH] = ("5.62", {}, datetime.now(timezone.utc).isoformat())
    assert "source-water pH 5.62 out of [5.8,6.5]" == r.c._blocked(r.c.rooms[0], 1)


def test_an_old_dosing_state_file_loads_with_it_off(build, tmp_path):
    r = build(switch="off")
    path = tmp_path / "old_state.json"
    path.write_text(json.dumps({"rooms": {"default": {"handled": "x", "history": [], "inflight": None}},
                                "outbox": []}), encoding="utf-8")
    old = r.build(path)
    r.c.dosing = old
    old.poll()
    assert r.status()[1]["ph_correct"] is None


def test_the_settings_defaults_are_the_integrations():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "ph_and_dim", root / "custom_components" / "crop_steering" / "ph_and_dim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    numbers = {key: (low, high, default) for key, _n, _i, low, high, _s, _u, default in module.NUMBERS}
    for key, (default, low, high) in ph_correct.SETTINGS.items():
        assert numbers[f"ph_correct_{key}"] == (low, high, default), key
    import dry_dim
    for key, (default, low, high) in dry_dim.SETTINGS.items():
        assert numbers[f"dry_dim_{key}"] == (low, high, default), key
    assert numbers["held_alert_hours"][2] == 0  # off


def test_the_rules():
    w = ph_correct.Watch()
    assert [w.read(5.6, 5.8, 6.5, t) for t in (0, 60, 299)] == [None, None, None]
    assert w.read(5.6, 5.8, 6.5, 300) == "up"
    assert ph_correct.verdict("up", 5.6, 5.9, 5.8, 6.5, 0.1) == "done"
    assert ph_correct.verdict("up", 5.6, 5.62, 5.8, 6.5, 0.1) == "no response"
    assert ph_correct.verdict("up", 5.6, 5.7, 5.8, 6.5, 0.1) == "again"
    assert ph_correct.verdict("up", 5.6, 6.6, 5.8, 6.5, 0.1) == "overshot"
    assert ph_correct.verdict("down", 6.9, 6.3, 5.8, 6.5, 0.1) == "done"
    assert ph_correct.verdict("up", 5.6, None, 5.8, 6.5, 0.1) == "not read"
    assert ph_correct.dose_ml(5, 11.06, 2000) == 55 and ph_correct.dose_ml(5, 11.06, 20) == 20
    assert ph_correct.setting(None, "dose_s") == 5 and ph_correct.setting(99, "max_tries") == 3
