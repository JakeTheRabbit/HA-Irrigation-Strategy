"""A restart must not strand irrigation behind a disarm cycle when the setup has not changed.

Seen live on 2026-09-20: the host rebooted, the controller came back with no memory of the setup
revision it had adopted (4), saw "4 > 0", and blocked every F2 zone with "Setup changed; disarm
current and requested engine flags and verify hardware OFF" because the kill switch was, correctly,
still ON. Overnight the hold line showed no reason, so it looked healthy; F2 then lost two hours of
its P1 ramp before anyone saw it.

The adopted revision is now saved with a fingerprint of what was adopted. Same revision and same
fingerprint after a restart = resume (hardware must still read OFF; the kill switch may stay ON).
Anything else keeps the full fail-safe.
"""
import json
import os
import tempfile

import pytest

import controller
from test_controller import _build, _desc

KILL = "input_boolean.kill"
DESCRIPTOR = "sensor.crop_steering_engine_config"
HARDWARE = ("switch.p", "switch.m", "switch.v1")


def _states(kill="on", revision=4, **descriptor):
    states = {
        DESCRIPTOR: ("ok", _desc(enable_flag=KILL, setup_revision=revision, active=True,
                                 active_zone_ids=[1], **descriptor)),
        KILL: (kill, {}),
    }
    states.update({entity: ("off", {}) for entity in HARDWARE})
    return states


def _start(states, state_path=None):
    """A controller process starting up; pass the previous process's state file to model a restart.

    The real constructor reads its state file BEFORE its first setup pass, so point it at the
    previous process's file (or at a brand-new empty location: a first start with nothing saved)
    before constructing. `_build` then re-seeds from a scratch file, so the pass is replayed
    against the intended file below."""
    os.environ["F2_STATE_PATH"] = state_path or os.path.join(
        tempfile.mkdtemp(prefix="f2resume_"), "state.json")  # restored by the autouse fixture
    c, fake = _build({"num_zones": 1, "enable_flag": KILL, "notify_service": "notify/phone"}, states=states)
    if state_path:
        c._state_path = state_path
        c._load_state()
        c._alerted.clear()
        fake.calls.clear()
        c._apply_setup_descriptors()
    else:
        c._save_state()  # what the constructor's own adoption wrote, had /data existed here
    return c, fake


def _adopted_then_restarted(**restart_states):
    """Adopt revision 4 the supported way (kill switch OFF, hardware OFF), then restart."""
    first, _fake = _start(_states(kill="off"))
    assert first.rooms[0].setup_revision == 4 and first.rooms[0]._setup_pending is None
    return _start(_states(**restart_states), state_path=first._state_path)


def _setup_alerts(fake):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and "setup" in d["notification_id"]]


def test_a_restart_resumes_an_unchanged_setup_with_the_kill_switch_left_on():
    c, fake = _adopted_then_restarted(kill="on")
    room = c.rooms[0]
    assert room.setup_revision == 4 and room._setup_pending is None
    assert "Setup" not in (c._blocked(room, 1) or "")  # the setup gate is open again (other gates are not this test's)
    assert _setup_alerts(fake) == []


def test_a_newer_revision_after_a_restart_still_needs_the_disarm_cycle():
    c, fake = _adopted_then_restarted(kill="on", revision=5)
    room = c.rooms[0]
    assert room._setup_pending and "Setup changed" in c._blocked(room, 1)
    fake.set_state(KILL, "off")
    c._apply_setup_descriptors()
    assert room.setup_revision == 5 and room._setup_pending is None


def test_the_same_revision_with_a_different_valve_map_still_needs_the_disarm_cycle():
    c, _fake = _adopted_then_restarted(kill="on", valves={"1": "switch.other_valve"})
    assert c.rooms[0]._setup_pending  # a revision number alone is not proof of an unchanged setup


def test_nothing_saved_keeps_the_legacy_fail_safe():
    c, _fake = _start(_states(kill="on"))  # first start after upgrading from a build that saved nothing
    assert c.rooms[0]._setup_pending and getattr(c.rooms[0], "setup_revision", 0) == 0


def test_resume_waits_for_running_hardware_and_then_heals_without_touching_the_kill_switch():
    states = _states(kill="on")
    first, _ = _start(_states(kill="off"))
    states["switch.p"] = ("on", {})  # someone is circulating the tank by hand as the controller restarts
    c, fake = _start(states, state_path=first._state_path)
    assert c.rooms[0]._setup_pending
    fake.set_state("switch.p", "off")
    c._apply_setup_descriptors()  # the next rediscover pass
    assert c.rooms[0]._setup_pending is None and c.rooms[0].setup_revision == 4


def test_a_pending_setup_is_announced_with_the_entities_in_the_way_and_what_to_do():
    c, fake = _start(_states(kill="on"))
    alerts = _setup_alerts(fake)
    assert len(alerts) == 1
    assert KILL in alerts[0]["message"] and "OFF" in alerts[0]["message"]
    assert any(dom == "notify" for dom, _svc, _d in fake.calls)  # a total irrigation block reaches the phone
    c._apply_setup_descriptors()
    assert len(_setup_alerts(fake)) == 1  # debounced, not one per rediscover pass


def test_a_blocked_zone_says_why_even_when_no_shot_is_due(capsys):
    c, _fake = _start(_states(kill="on"))
    room = c.rooms[0]
    room.state[1]["phase"] = "P3"
    c._act_zone(room, 1, None, None, (False, 0.0, ""), c._blocked(room, 1), False, controller.datetime.now())
    assert "Setup changed" in capsys.readouterr().out  # the overnight hold line used to be blank


@pytest.mark.parametrize("saved", [{"revision": "4", "fingerprint": "x"}, "garbage", {"revision": 4}])
def test_malformed_saved_setup_is_never_trusted(saved):
    first, _ = _start(_states(kill="off"))
    blocks = first._read_state_file()
    assert blocks["default"]["_setup"]["revision"] == 4  # the good record, about to be corrupted
    blocks["default"]["_setup"] = saved
    with open(first._state_path, "w") as fh:
        json.dump(blocks, fh)
    c, _fake = _start(_states(kill="on"), state_path=first._state_path)
    assert c.rooms[0]._setup_pending
