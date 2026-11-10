"""THE PLAN FOLLOWS THE PROBE across both layers, in a real Home Assistant.

The real integration's running plan, its real strategy_zone_offset service (schema, admin rule, store, the plan
sensor it publishes, strategy_get and strategy_preview), and the real controller that sets the offset: its
crop_steering.strategy_zone_offset call goes into this Home Assistant's own service, and it reads the plan sensor
back as the REST API would hand it over. Only the web server and time are stood in for (test_plan_adherence.py).
"""

import asyncio
import json
from datetime import timedelta

import pytest
from conftest import fixture, room_of
from homeassistant.exceptions import HomeAssistantError
from test_plan_adherence import (
    TENT,
    TENT_ARMED,
    TENT_KILL,
    _install,
    _lights,
    _pass,
    _running,
    _start,
    _tent,
    _utc,
)

DOMAIN = "crop_steering"
ROOM = "room:tent_"
PLAN = "sensor.crop_steering_tent_strategy_plan"


async def _offset(hass, offset, zone=1):
    return await hass.services.async_call(
        DOMAIN, "strategy_zone_offset", {"room_id": ROOM, "zone_id": zone, "offset": offset, "reason": "probe moved"},
        blocking=True, return_response=True)


async def test_the_offset_service_moves_a_running_zone_at_once(hass, controller_for, monkeypatch):
    at = _start()
    _entry, manager, _c, _fake = await _tent(hass, controller_for, monkeypatch, at)
    revision = manager.document["revision"]
    before = hass.states.get(PLAN).attributes["zones"][0]["parameters"]
    answer = await _offset(hass, -2)
    assert answer["offsets"] == {"1": -2}
    row = hass.states.get(PLAN).attributes["zones"][0]
    assert row["vwc_offset"] == -2
    for key in ("p1_target_vwc", "p2_vwc_threshold", "p3_emergency_vwc_threshold"):
        assert row["parameters"][key] == pytest.approx(before[key] - 2), key
        assert row["vwc_base"][key] == pytest.approx(before[key]), key
    got = await hass.services.async_call(DOMAIN, "strategy_get", {"room_id": ROOM}, blocking=True,
                                         return_response=True)
    assert got["offsets"] == {"1": -2} and got["revision"] == revision
    preview = await hass.services.async_call(DOMAIN, "strategy_preview", {"room_id": ROOM, "date": at.date().isoformat()},
                                             blocking=True, return_response=True)
    assert preview["preview"]["zones"][0]["parameters"] == row["parameters"]
    # what the controller reads: the snapshot is still one it takes
    from strategy_runtime import check_parameters

    check_parameters(row["parameters"])


async def test_the_service_refuses_a_bad_offset_and_a_plan_that_is_not_running(hass, controller_for, monkeypatch):
    at = _start()
    _entry, manager, _c, _fake = await _tent(hass, controller_for, monkeypatch, at)
    with pytest.raises(HomeAssistantError, match="no room"):  # the minimums leave no order that fits
        await _offset(hass, -100)
    with pytest.raises(HomeAssistantError, match="not in this room"):
        await _offset(hass, -2, zone=5)
    assert manager.offset(1) == 0
    await manager.disarm(at)
    manager.document["status"] = "draft"
    with pytest.raises(HomeAssistantError, match="armed or active"):
        await _offset(hass, -2)


async def test_the_real_controller_sets_the_offset_and_reads_it_back(hass, controller_for, monkeypatch):
    import controller

    at = _start()
    _entry, manager, c, fake = await _tent(hass, controller_for, monkeypatch, at)
    hass.states.async_set("switch.crop_steering_tent_auto_setpoints", "on")
    await _pass(hass, c, fake, monkeypatch, manager, at)  # the controller reads the room and its plan
    room = room_of(c, TENT)
    row = room._strategy_raw[1]["zones"][0]
    p1 = row["parameters"]["p1_target_vwc"]
    base_fc = row["vwc_base"].get("field_capacity", p1)
    st = room.state[1]
    # the pass itself looked once (no peaks kept yet: nothing to do) and will not look again today
    assert st["phase"] in ("P2", "P3")
    assert st["plan_follow"]["checked"] == c._grow_day_start(room, at).isoformat()
    assert manager.offset(1) == 0
    # the F1 shape: one clean grow-day since the probe settled, its peak 15 points under the P1 target (over 8:
    # one day is enough), and the offset set the whole way in one write
    st["plan_follow"]["checked"] = None
    peak = round(p1 - 15, 1)
    st["plan_follow"]["days"] = [{"day": "d0", "peak": peak, "rose": 8.0}]  # a watered day
    want = round(peak + 1 - base_fc, 1)
    loop = asyncio.get_running_loop()

    def answer(domain, service, data, timeout=12):
        """The REST call, into this Home Assistant's own service; the plan sensor it publishes, mirrored back."""
        fake.calls.append((domain, service, dict(data)))
        got = asyncio.run_coroutine_threadsafe(
            hass.services.async_call(domain, service, data, blocking=True, return_response=True), loop).result(10)
        state = hass.states.get(PLAN)
        fake.set_state(PLAN, state.state, json.loads(json.dumps(dict(state.attributes), default=str)))
        return 200, json.loads(json.dumps(got, default=str))

    monkeypatch.setattr(controller, "ha_service_response", answer)
    assert await hass.async_add_executor_job(c._plan_follow, room, 1, st, at) is True
    assert want < -14 and manager.offset(1) == want
    landed = hass.states.get(PLAN).attributes["zones"][0]
    assert landed["vwc_offset"] == want
    levels = [landed["parameters"].get("field_capacity", p1), landed["parameters"]["p1_target_vwc"],
              landed["parameters"]["p2_vwc_threshold"], landed["parameters"]["p3_emergency_vwc_threshold"]]
    assert levels[1] == pytest.approx(p1 + want)  # P1 lands under the peak the zone reaches
    assert levels[0] >= levels[1] > levels[2] >= levels[3] + 3  # in order, as the controller reads it
    cards = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
             and "CS-714" in d.get("title", "")]
    assert len(cards) == 1
    assert f"from +0 to {want:+g} points, a move of {want:+g} points in one step" in cards[0]["message"]
    assert "one clean grow-day is enough when a zone is more than 8 points off" in cards[0]["message"]
    # once a grow-day: a second look the same day changes nothing
    assert await hass.async_add_executor_job(c._plan_follow, room, 1, st, at + timedelta(hours=1)) is False
    assert manager.offset(1) == want


def _moved_to_today(seed, today):
    """The fixture's state file with its two dates moved: its grow-day to today, the day before to yesterday."""
    text = json.dumps(seed["state"])
    text = text.replace(seed["grow_day"], today.isoformat())
    text = text.replace(seed["day_before"], (today - timedelta(days=1)).isoformat())
    return json.loads(text)


async def test_a_3_19_0_state_file_keeps_no_day_without_water_and_the_plan_does_not_move(hass, controller_for,
                                                                                        monkeypatch):
    """3.19.0 kept a grow-day's peak without asking whether water raised it (fixtures/state_3_19_0_plan_follow.json:
    the tent at lights-on after a day with no water, its kept peak 14 points under the P1 target). The new
    controller loads that file with everything else as it was, drops the day it cannot vouch for, and its look
    after the ramp moves nothing. On 3.19.0 the same file wrote an offset of about -13 points, the rescue floor
    included."""
    import controller

    seed = fixture("state_3_19_0_plan_follow.json")
    at = _start()
    state = _moved_to_today(seed, at.date())
    old = state["tent"]["1"]
    yesterday = (at.date() - timedelta(days=1)).isoformat()
    assert old["plan_follow"]["days"] == [{"day": yesterday, "peak": seed["peak"]}]
    old["last_phase_change"] = (at - timedelta(minutes=30)).isoformat()  # lights-on was within the hour
    await _utc(hass)
    entry = await _install(hass)
    await _lights(hass, TENT, (at.hour - 1) % 24, (at.hour + 15) % 24)
    manager = await _running(hass, entry, TENT, TENT_KILL, at.date() - timedelta(days=16))
    c, fake, _clock = controller_for({"enable_flag": TENT_KILL}, saved_state=state)
    c._start = at - timedelta(hours=1)
    for switch in TENT_ARMED:
        hass.states.async_set(switch, "off")
    hass.states.async_set("switch.crop_steering_tent_auto_setpoints", "on")
    room = room_of(c, TENT)
    st = room.state[1]
    # the old file loads: what it held is kept, and only the day nobody judged is gone
    assert (st["phase"], st["peak_prev"], st["shots"], st["daily_vol"], st["last_daily_reset"]) == (
        old["phase"], old["peak_prev"], old["shots"], old["daily_vol"], at.date())
    assert st["plan_follow"]["days"] == []
    assert (st["plan_follow"]["watered"], st["plan_follow"]["before"], st["plan_follow"]["ramped"]) == (
        False, None, False)
    assert st["plan_follow"]["last"] == old["plan_follow"]["last"]
    await _pass(hass, c, fake, monkeypatch, manager, at)
    assert seed["p1"] == room._strategy_raw[1]["zones"][0]["parameters"]["p1_target_vwc"]  # the same plan
    assert seed["p1"] - seed["peak"] > 8  # one such day was enough for 3.19.0
    calls = []
    monkeypatch.setattr(controller, "ha_service_response",
                        lambda domain, service, data, timeout=12: calls.append((domain, service, data)) or (200, {}))
    st["phase"], st["plan_follow"]["checked"] = "P2", None  # today's ramp has ended: the rule looks
    assert await hass.async_add_executor_job(c._plan_follow, room, 1, st, at) is False
    assert calls == [] and manager.offset(1) == 0
    cards = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
             and "CS-714" in d.get("title", "")]
    assert cards == []
