"""Stopping the app in the middle of a shot, on an upgraded room, with Home Assistant answering slowly.

The real integration is started on a seeded old install (2.25.1, and the Jev 3.11.1 line), and the real
controller resumes it with the options and state file that version left. A shot runs; half a minute
in, every answer from Home Assistant starts arriving 3 or 3.5 s after it is asked for (a call whose
timeout is shorter fails when it is up, as a requests timeout does), or never, and the app is stopped.
The Supervisor kills it 30 s after SIGTERM, so the safe-off must be done inside its 25 s budget: the
water given counted, the state file saved, and the shot's switches switched off, valve first, as far
as the reads and offs fit in the budget at that speed; what is not confirmed off stays recorded for
the next start.
"""

import json
import os
from pathlib import Path

import pytest
from conftest import fixture, switch_calls
from test_upgrade_in_place import JEV_3_11_1, KILL, UPSTREAM_2_25_1, _jev_3_11_1_app, _upgrade

VALVE, MAINLINE, PUMP = "switch.zone_1_valve", "switch.irrigation_main_line", "switch.irrigation_pump"


def _slow_then_stop(c, fake, clock, monkeypatch, latency):
    """The shot's wait: 30 s of water, then Home Assistant answers each call `latency` s after it is
    asked for (never, when None) and SIGTERM arrives."""
    import controller

    def slow(shim, default, failed):
        def answer(*args, timeout=default, **kwargs):
            if latency is None or timeout < latency:
                clock.sleep(timeout)
                return failed
            clock.sleep(latency)
            return shim(*args, **kwargs)

        return answer

    def wait(room, zone, duration_s, started=None):
        clock.sleep(30)
        for name, default, failed in (("ha_get", 8, controller.HAState()), ("ha_call", 12, False),
                                      ("ha_history", 12, None)):
            monkeypatch.setattr(controller, name, slow(getattr(controller, name), default, failed))
        fake.calls.clear()
        stop["at"] = clock.seconds
        c._safe_exit()

    stop = {}
    monkeypatch.setattr(c, "_wait_shot", wait)
    return stop


# At 3.5 s the four reads, three offs and the second's pause after the valve's off need 25.5 s: the
# pump's off is the one that does not fit.
@pytest.mark.parametrize("latency, taken", [(3.0, (VALVE, MAINLINE, PUMP)), (3.5, (VALVE, MAINLINE)), (None, ())])
@pytest.mark.parametrize("seeded", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_slow_home_assistant_never_takes_the_stop_past_the_apps_timeout(
    hass, controller_for, monkeypatch, seeded, latency, taken
):
    monkeypatch.delenv("F2_STOP_BUDGET_S", raising=False)
    seed = fixture(seeded)
    await _upgrade(hass, seeded, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    if seeded == JEV_3_11_1:
        c, fake, _built, _usage, _state = _jev_3_11_1_app(
            controller_for, monkeypatch, "options_3_11_1_jev_cf.json"
        )
    else:
        c, fake, _clock = controller_for(
            seed["addon_options"], saved_state=seed["controller_saved"]
        )
    import controller

    clock = controller.time.sleep.__self__  # the test clock controller_for runs the controller on
    room = c.rooms[0]
    assert room.hw["valves"][1] == VALVE
    for switch in (
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    shots = room.state[1]["shots"]
    stop = _slow_then_stop(c, fake, clock, monkeypatch, latency)

    with pytest.raises(SystemExit):
        c._execute_shot(room, 1, 300, 5, flow_lps=0.05)

    assert clock.seconds - stop["at"] <= 25 + 2  # inside the Supervisor's 30 s, with room to exit
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))["default"]
    assert saved["1"]["shots"] == shots + 1  # the 30 s of water given are counted
    assert switch_calls(fake) == [("turn_off", e) for e in taken]  # what Home Assistant took, valve first
    if len(taken) < 3:  # what is still on is closed at the next start
        assert saved["_shot_inflight"]["valve"] == VALVE


@pytest.mark.parametrize("seeded", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_the_stop_says_stopped_on_the_heartbeat_and_the_integration_still_finds_the_switch(
    hass, controller_for, monkeypatch, seeded
):
    """Stopped mid-shot with Home Assistant answering at once: the heartbeat says "stopped", and the
    real integration, reading it, still finds the room's engine switch."""
    from custom_components.crop_steering.room import room_gate

    monkeypatch.delenv("F2_STOP_BUDGET_S", raising=False)
    seed = fixture(seeded)
    await _upgrade(hass, seeded, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    if seeded == JEV_3_11_1:
        c, fake, _built, _usage, _state = _jev_3_11_1_app(
            controller_for, monkeypatch, "options_3_11_1_jev_cf.json"
        )
    else:
        c, fake, _clock = controller_for(
            seed["addon_options"], saved_state=seed["controller_saved"]
        )
    import controller

    clock = controller.time.sleep.__self__
    room = c.rooms[0]
    for switch in (
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    stop = _slow_then_stop(c, fake, clock, monkeypatch, 0.0)

    with pytest.raises(SystemExit):
        c._execute_shot(room, 1, 300, 5, flow_lps=0.05)

    assert clock.seconds - stop["at"] <= 25
    state, attributes = fake.sets["sensor.crop_steering_ai_heartbeat"]
    assert state == "stopped" and "strategy_snapshot_version" not in attributes
    hass.states.async_set("sensor.crop_steering_ai_heartbeat", state, attributes)
    assert room_gate(hass, "") == room.enable_flag
