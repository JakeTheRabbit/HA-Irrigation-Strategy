"""The AI assistant's powers, in a real Home Assistant with the real controller (docs/AI_ASSISTANT.md, "Powers").

One switch per power per room says what the AI assistant may change. A new room gets them at their defaults; a room
updated in place from 3.11.1 (the newest seeded snapshot, tests_ha/fixtures/entry_3_11_1_pumped_room.json; 3.12.1
registers the same entities) gets the same defaults, which reproduce what its AI assistant did before: every power
that acted is on, the two new ones are off. A power switched off turns its judge's answer into advice. With the
targets power on, the AI assistant sets a zone's ladder itself: its values reach the real numbers as given, clamped
only to each number's own range, written in an order the integration's own ladder check accepts, and named in the
room's setpoint change log with the AI's reason and the result it expects.
"""

import functools
from datetime import datetime, timedelta
from types import SimpleNamespace

from conftest import fixture
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
POWERS = (
    ("advance_phase", "AI power: start the next phase early", "on"),
    ("ramp_control", "AI power: end the morning ramp", "on"),
    ("set_probe_aside", "AI power: set a probe aside", "on"),
    ("ec_mode", "AI power: change the EC steer", "on"),
    ("nudge_setpoints", "AI power: adjust maintenance watering", "on"),
    ("plan_catch_up", "AI power: apply today's plan day", "on"),
    ("set_targets_from_achievable", "AI power: set targets from what a zone reaches", "off"),
    ("tune_shot_sizes", "AI power: tune shot sizes", "off"),
)
KILL = "switch.crop_steering_engine_enabled"
BRAIN = {"enable_flag": KILL, "brain_provider": "claude_haiku", "anthropic_api_key": "sk-ant-test-0000000000"}
NUMBER = "number.crop_steering_zone_1_"


def _powers(hass, prefix=""):
    return [(key, hass.states.get(f"switch.crop_steering_{prefix}ai_power_{key}")) for key, _n, _d in POWERS]


async def test_a_new_room_gets_every_power_switch_at_its_default(hass):
    await _install(hass)
    for (key, state), (_k, name, default) in zip(_powers(hass, "tent_"), POWERS):
        assert state is not None, key
        assert (state.state, state.attributes["friendly_name"].endswith(name)) == (default, True), key


async def test_a_room_updated_in_place_gets_defaults_that_do_what_it_did_and_nothing_else_moves(hass):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert [(k, s.state) for k, s in _powers(hass)] == [(k, d) for k, _n, d in POWERS]
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        assert (float(state) == float(tuned)) if entity_id.startswith("number.") else (state == tuned), entity_id


async def _brain(hass, controller_for, monkeypatch, *, power_on=True, off=()):
    import brain_kit
    import jev_bridge
    from jev import client as jc
    from jev.client import Asker

    # The Claude brain with a stand-in SDK and no background worker: nothing here reaches the network.
    monkeypatch.setattr(jc, "anthropic", brain_kit.FakeSDK(brain_kit.FakeClient()))
    monkeypatch.setattr(jev_bridge, "Asker", functools.partial(Asker, threaded=False))
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    if power_on:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.crop_steering_ai_power_set_targets_from_achievable"},
            blocking=True,
        )
    for key in off:  # the owner unticks a power on the dashboard
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": f"switch.crop_steering_ai_power_{key}"}, blocking=True
        )
    c, fake, _clock = controller_for(BRAIN)
    room = c.rooms[0]
    c._refresh_lights(room)
    return c, fake, room


async def test_toggling_a_power_off_stops_it_acting(hass, controller_for, monkeypatch):
    import jev_bridge
    from jev.envelope import Directive, admit

    c, _fake, room = await _brain(hass, controller_for, monkeypatch, power_on=False, off=("ramp_control",))
    now = datetime(2026, 10, 10, 12, 0)
    powers = jev_bridge.room_powers(c, room, now)
    assert powers["ramp_control"] is False and powers["advance_phase"] is True
    assert not jev_bridge.targets_owned(c, room)  # the targets power is off by default
    d = Directive("ramp", "advance", "P2", "slab_full", now + timedelta(minutes=30))
    ok, why = admit(d, SimpleNamespace(now=now, powers=powers, snap=None, params=None))
    assert not ok and why.endswith("advice only")


async def _replay(hass, fake):
    """What the controller sent, sent to this Home Assistant exactly as the controller sent it: its event first."""
    for event, data in fake.events:
        hass.bus.async_fire(event, data)
    await hass.async_block_till_done()
    for domain, service, data in fake.calls:
        if (domain, service) == ("number", "set_value"):
            await hass.services.async_call(domain, service, data, blocking=True)
            fake.set_state(data["entity_id"], str(data["value"]), fake.states[data["entity_id"]][1])
    fake.events.clear()
    fake.calls.clear()


def _value(hass, suffix):
    return float(hass.states.get(NUMBER + suffix).state)


async def _night_move(hass, c, fake, room, now, values, expected):
    import jev_bridge
    import jev_kit as K
    from jev import council
    from jev.envelope import admit
    from jev.judges.targets import TargetsJudge

    p = c._snapshot(room, 1, now, False, False)[1]
    room.state[1]["phase"] = "P3"
    view = jev_bridge.targets_view(c, room, 1, p, now)
    ctx = K.ctx("P3", now=now, lights_on=False, targets=view, powers=jev_bridge.room_powers(c, room, now))
    answer = {"type": "values", "values": {k: {"value": v, "reason": f"the scorecard: {k}"} for k, v in values.items()},
              "expected": expected, "confidence": 0.8}
    d = TargetsJudge().decide({"targets": council.combine({"targets__v0": answer}, "targets")}, ctx)
    ok, why = admit(d, ctx)
    assert ok, why
    fake.events.clear()
    fake.calls.clear()
    jev_bridge.apply_values(c, room, 1, d, ctx, now)
    await _replay(hass, fake)
    return d


async def _log(hass):
    return (await hass.services.async_call(DOMAIN, "setpoint_log_get", {"room_id": "room:"}, blocking=True,
                                           return_response=True))["changes"]


async def test_the_targets_power_writes_the_ais_values_through_the_real_numbers(hass, controller_for, monkeypatch):
    import jev_bridge

    c, fake, room = await _brain(hass, controller_for, monkeypatch)
    assert jev_bridge.targets_owned(c, room)
    keys = ("field_capacity", "p1_target_vwc", "p2_vwc_threshold", "p3_emergency_vwc_threshold")
    before = {s: _value(hass, s) for s in keys}

    # Raise everything by 8 points, the rescue floor too: no limit of code's own, written from the top.
    up = {k: before[k] + 8.0 for k in keys}
    night = datetime(2026, 10, 10, 20, 0)
    await _night_move(hass, c, fake, room, night, up, "P1 reaches the new peak in 4 shots")
    assert {s: _value(hass, s) for s in keys} == up
    rows = (await _log(hass))[-4:]
    assert [r["field"] for r in rows] == list(keys)  # from the top: each write the ladder check accepts
    assert all(r["who"] == "brain" and r["reason"] == f"the scorecard: {r['field']}"
               and r["expected"] == "P1 reaches the new peak in 4 shots" for r in rows)
    overlays = await hass.services.async_call(DOMAIN, "overlay_get", {"room_id": "room:"}, blocking=True,
                                              return_response=True)
    assert not [o for o in overlays.get("overlays", []) if o.get("field") in keys]  # kept, not an overlay

    # Lower by 10, the next night: written from the bottom, each write accepted.
    down = {k: up[k] - 10.0 for k in keys}
    await _night_move(hass, c, fake, room, night + timedelta(days=1), down, "a deeper dryback")
    assert {s: _value(hass, s) for s in keys} == down
    assert [r["field"] for r in (await _log(hass))[-4:]] == list(reversed(keys))

    # Outside a number's own range: clamped to it, and the clamp is in the log's reason.
    hi = float(hass.states.get(NUMBER + "p1_target_vwc").attributes["max"])
    await _night_move(hass, c, fake, room, night + timedelta(days=2), {"p1_target_vwc": hi + 50.0}, "x")
    assert _value(hass, "p1_target_vwc") == hi
    last = (await _log(hass))[-1]
    assert (last["field"], last["new"]) == ("p1_target_vwc", hi) and "clamped to its range" in last["reason"]
