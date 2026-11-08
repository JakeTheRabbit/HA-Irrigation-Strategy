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
from conftest import room_of
from homeassistant.exceptions import HomeAssistantError
from test_plan_adherence import TENT, _pass, _start, _tent

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
    with pytest.raises(Exception):  # the schema's or the integration's refusal, never a stored change
        await _offset(hass, -40)
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
    st = room.state[1]
    # the pass itself looked once (no peaks kept yet: nothing to do) and will not look again today
    assert st["phase"] in ("P2", "P3")
    assert st["plan_follow"]["checked"] == c._grow_day_start(room, at).isoformat()
    assert manager.offset(1) == 0
    st["plan_follow"]["checked"] = None  # three clean grow-days of peaks, 8 points under its P1 target
    st["plan_follow"]["days"] = [{"day": f"d{i}", "peak": round(p1 - 8, 1)} for i in range(3)]
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
    assert manager.offset(1) == -3
    landed = hass.states.get(PLAN).attributes["zones"][0]
    assert landed["vwc_offset"] == -3
    assert landed["parameters"]["p1_target_vwc"] == pytest.approx(p1 - 3)
    cards = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
             and "CS-714" in d.get("title", "")]
    assert len(cards) == 1 and "from +0 to -3 points" in cards[0]["message"]
    # once a grow-day: a second look the same day changes nothing
    assert await hass.async_add_executor_job(c._plan_follow, room, 1, st, at + timedelta(hours=1)) is False
    assert manager.offset(1) == -3
