"""Three safety claims the README and the system map make, each pinned here because no test named it.

  * "An unreadable kill switch counts as off" (docs/SYSTEM_MAP.md), before a shot: a kill switch that reads
    unavailable, unknown or nothing, or that Home Assistant no longer has, holds every shot, a rescue included.
    No other switch is read in its place, and the last value read is not kept. (A shot already running is the
    other rule, in test_failed_reads.py: it runs to its length, and only a definite OFF ends it early.)
  * "It reads your probes each minute" (README.md): the controller passes every 60 s unless the operator sets
    another interval, and that is how long its loop waits between two passes.
  * "It never operates a pump, a valve or the main line. It never starts a shot" (README.md, of the AI
    assistant). The AI assistant's code reaches the controller through brain_bridge.py only. This file lists
    what that module may touch on the controller, and what it may write to Home Assistant. A change that
    widens the list fails here, so that widening it is a decision somebody makes and not a side effect.
"""
import ast
import pathlib
import re
from datetime import timedelta

import pytest
import test_p3_time_between_shots as p3

import controller

pytestmark = pytest.mark.usefixtures("settings_built_in")
night_room = p3.rig  # two zones in P3 at night; in p3.night() zone 1 reads under its rescue level
KILL = "input_boolean.kill"
ADDON = pathlib.Path(controller.__file__).resolve().parent


# ------------------------------------------------------------------ the kill switch, before a shot
@pytest.mark.parametrize("state", ["unavailable", "unknown", "", None])
def test_a_kill_switch_that_stops_reading_holds_every_shot_whatever_any_other_switch_says(night_room, state):
    """`None`: Home Assistant no longer has the entity (and a read it does not answer gives the same)."""
    c, fake, room = night_room
    for other in (controller.LEGACY_ENABLE_FLAG, "switch.crop_steering_engine_enabled"):
        fake.set_state(other, "on")  # never read in its place
    assert p3.night(c, fake, room, 1) == [0]  # it read ON, and the zone was watered
    if state is None:
        del fake.states[KILL]
    else:
        fake.set_state(KILL, state)
    assert c._blocked(room, 1) == f"{controller.PRODUCT} disabled (kill switch off)"
    p3.Clock.instant += timedelta(minutes=1)
    assert p3.night(c, fake, room, 12) == []  # minutes 1 to 12: the rescue due at minute 10 is held
    fake.set_state(KILL, "on")
    assert p3.night(c, fake, room, 1) == [0]  # and it goes as soon as the switch reads ON again


# ------------------------------------------------------------------ once a minute
def test_the_controller_passes_once_a_minute_unless_told_otherwise(night_room, monkeypatch):
    c, _fake, _room = night_room
    assert c.loop_seconds == 60.0  # no loop_seconds in its options
    shipped = (ADDON.parent / "config.yaml").read_text(encoding="utf-8")
    assert re.search(r"^  loop_seconds: 60$", shipped, re.M)  # what the app's options start with
    waits = []

    class Stop(Exception):
        pass

    def wait(seconds):
        waits.append(seconds)
        raise Stop

    monkeypatch.setattr(c, "_start_dosing", lambda: None)
    monkeypatch.setattr(c, "loop_once", lambda now: None)
    monkeypatch.setattr(c, "_sleep_for", wait)
    with pytest.raises(Stop):
        c.run()
    assert waits == [60.0]  # and that is what the loop waits between two passes


# ------------------------------------------------------------------ the AI assistant cannot reach the hardware
# Every attribute of the controller that brain_bridge.py reads or calls today. None of them switches a pump or
# a valve, presses a button or starts a shot: they read, alert, save state, and write a zone's setpoint numbers
# (_auto_write, inside the limits of each number) or a phase the engine then acts on by its own rules.
MAY_TOUCH = frozenset("""__dict__ _alert _auto_write _busy _dosing_hold _feed_band _fused_id _grow_day_start _hours_to
    _jev_alert _jev_read _lights_on _no_touch_until _notify_event _num_or_none _number_range _on _p1_stall_today
    _read_feed_ec _read_feed_ph _read_sensor _record_phase _room_active _save_state _state_path _step_allowance
    _step_count _step_limit _step_limit_all _substrate_l _veg _zone_bounded _zone_num _zone_title brain_status jev
    journal rooms""".split())
# What it may assign on a room or on the controller: its own notes, never a switch's entity id or the hardware map.
MAY_SET = frozenset({"_brain_health", "_jev_sib", "_jev_params", "_strategy_batch_invalid", "_ai_powers"})
# Names that are a way to Home Assistant, to a hardware call or to the shot code. No AI module may hold one.
NEVER_NAMED = ("hw_call", "ha_call", "ha_service_response", "ha_fire", "hw_state", "_execute_shot", "_act_zone",
               "_test_shot", "_loop_room", "_switch_off", "_safe_off", "turn_on", "open_valve", "importlib",
               "__import__", "SUPERVISOR_TOKEN", "HA_URL")
WIDENED = ("the AI assistant's code now reaches something new on the controller. Add it to the list in this test "
           "only when it cannot switch a pump or a valve, press a button, change a switch or start a shot: ")


def _ai_modules():
    return sorted([*(ADDON / "brain").rglob("*.py"), ADDON / "brain_bridge.py"])


def _named(source):
    return [name for name in NEVER_NAMED if re.search(rf"\b{re.escape(name)}\b", source)]


def _is(node, name):
    return isinstance(node, ast.Name) and node.id == name


def test_no_module_of_the_ai_assistant_names_a_hardware_call_the_shot_code_or_another_way_to_home_assistant():
    modules = _ai_modules()
    assert len(modules) > 10 and (ADDON / "brain" / "envelope.py") in modules  # the scan sees the package
    sources = {path: path.read_text(encoding="utf-8") for path in modules}
    found = [(path.relative_to(ADDON).as_posix(), name) for path, source in sources.items() for name in _named(source)]
    assert found == []
    # the one module that talks to the network is the client of the AI service, and none but the bridge and the
    # brief (which reads the alert list) imports the controller
    assert [p.name for p, s in sources.items() if re.search(r"\brequests\b", s)] == ["client.py"]
    assert [p.name for p, s in sources.items() if re.search(r"^\s*import controller\b|sys\.modules", s, re.M)] == [
        "controller_brief.py", "brain_bridge.py"]


def test_the_scan_catches_a_hardware_call():
    assert _named("def act(c, room):\n    c._execute_shot(room, 1, 30, 5)\n") == ["_execute_shot"]
    assert _named("ha_service_response('button', 'press', {})") == ["ha_service_response"]
    assert _named("# only reads the room's state\nvalue = c._num_or_none(entity)\n") == []


def test_the_bridge_touches_only_these_parts_of_the_controller_and_writes_only_its_own_sensors():
    nodes = list(ast.walk(ast.parse((ADDON / "brain_bridge.py").read_text(encoding="utf-8"))))
    # an attribute of the controller is never reached by a name worked out at run time
    by_name = [n.args[1] for n in nodes if isinstance(n, ast.Call) and getattr(n.func, "id", None) in ("getattr", "setattr")
               and n.args and _is(n.args[0], "c")]
    assert all(isinstance(a, ast.Constant) for a in by_name)
    touched = {n.attr for n in nodes if isinstance(n, ast.Attribute) and _is(n.value, "c")}
    touched |= {a.value for a in by_name}
    assert touched <= MAY_TOUCH, WIDENED + ", ".join(sorted(touched - MAY_TOUCH))
    stored = {n.attr for n in nodes if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
              and (_is(n.value, "room") or _is(n.value, "c"))}
    assert stored <= MAY_SET, WIDENED + ", ".join(sorted(stored - MAY_SET))
    # the states it writes to Home Assistant are its own sensors of the room, never a switch, a button or a number
    # (`out_id` is the one built on a line of its own: sensor.crop_steering_<prefix>brain_answers)
    source = (ADDON / "brain_bridge.py").read_text(encoding="utf-8")
    assert 'out_id = f"sensor.crop_steering_{room.prefix}brain_answers"' in source
    written = [ast.unparse(n.args[0]) for n in nodes if isinstance(n, ast.Call) and _is(n.func, "ha_set")]
    assert written and all(w == "out_id" or w.startswith("f'sensor.crop_steering_{room.prefix}") for w in written), written
