"""PLAN ADHERENCE across both layers, in a real Home Assistant: the real integration's grow plan (its store, its
lights-on boundary, its strategy_get and strategy_preview answers, which the fake hands the controller exactly as the
real services gave them) and the real controller that checks the room runs it.

Only the web server is stood in for, and time: the controller is handed the pass's time, and before each pass the
integration republishes its snapshot at that time (StrategyManager._publish, its own code), because a plan sensor
written minutes ago is one the controller rightly refuses as stale. Readings stay fresh on the real clock.
"""

import copy
import functools
import json
from datetime import datetime, time, timedelta, timezone

import pytest
from conftest import fixture, room_of
from homeassistant.util import dt as dt_util
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, KILL, _upgrade

DOMAIN = "crop_steering"


async def _utc(hass):
    """The integration's wall clock and the controller's are the same: both UTC here."""
    await hass.config.async_set_time_zone("UTC")


def _start():
    """A time today, at least an hour after a lights-on on the hour, with the rest of the day before midnight."""
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    return now - timedelta(hours=2) if now.hour >= 21 else now


async def _lights(hass, prefix, on, off):
    for key, hour in (("lights_on_hour", on), ("lights_off_hour", off)):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": f"number.crop_steering_{prefix}{key}", "value": hour}, blocking=True
        )


def _beat(hass, prefix, kill):
    hass.states.async_set(
        f"sensor.crop_steering_{prefix}ai_heartbeat", "healthy", {"enable_flag": kill, "strategy_snapshot_version": 1}
    )


def _manager(hass, entry):
    return hass.data[DOMAIN]["_strategy"][entry.entry_id]


def _mirror(hass, fake):
    """Every Home Assistant state into the controller's fake, as the REST API would hand it over now; the heartbeat
    is the controller's own (the one in Home Assistant stands in for it, for the integration)."""
    for state in hass.states.async_all():
        if state.entity_id.endswith("ai_heartbeat"):
            continue
        fake.set_state(state.entity_id, state.state, json.loads(json.dumps(dict(state.attributes), default=str)))


async def _pass(hass, c, fake, monkeypatch, manager, at, days=None):
    """One controller pass at `at`: the plan published at that time, the real services' answers for today and
    yesterday, every state mirrored."""
    import controller

    manager._publish(at.replace(tzinfo=timezone.utc))
    room_id = manager.room_id
    got = await hass.services.async_call(DOMAIN, "strategy_get", {"room_id": room_id}, blocking=True,
                                         return_response=True)
    previews = {}
    for day in days or (at.date(), at.date() - timedelta(days=1)):
        previews[day.isoformat()] = await hass.services.async_call(
            DOMAIN, "strategy_preview", {"room_id": room_id, "date": day.isoformat()}, blocking=True,
            return_response=True)

    def answer(domain, service, data, timeout=12):
        fake.calls.append((domain, service, dict(data)))
        if service == "strategy_get":
            return 200, json.loads(json.dumps(got, default=str))
        if service == "strategy_preview":
            return 200, json.loads(json.dumps(previews.get(data.get("date")), default=str))
        return 200, None

    monkeypatch.setattr(controller, "ha_service_response", answer)
    _mirror(hass, fake)
    c.loop_once(at)


def _cards(fake, prefix="f2_plan_"):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
            and str(d.get("notification_id", "")).startswith(prefix)]


def _number_writes(fake):
    return [(dom, svc, d) for dom, svc, d in fake.calls if dom == "number"]


def _aligned_plan(manager, *, start, second_from=None, shot_steps=2):
    """The plan every room starts with, its values on their numbers' steps, as one profile, or two when
    `second_from` names the first day of a second profile whose maintenance shot is `shot_steps` steps bigger."""
    doc = copy.deepcopy(manager.document["plan"])
    catalog = manager.catalog()
    extra = []
    for profile in doc["profiles"]:
        zone = int(profile["id"].split("-")[1])
        for side in ("vegetative", "generative"):
            for key, value in list(profile[side].items()):
                b = catalog[zone][key]
                profile[side][key] = round(b["min"] + round((value - b["min"]) / b["step"]) * b["step"], 6)
        late = copy.deepcopy(profile)
        late["id"], late["name"] = f"late-{zone}", "Finish"
        for side in ("vegetative", "generative"):
            late[side]["p2_shot_size"] = round(late[side]["p2_shot_size"] + shot_steps * catalog[zone]["p2_shot_size"][
                "step"], 6)
        profile["name"] = "Bulk"
        extra.append(late)
    if second_from:
        doc["profiles"] += extra
    for assignment in doc["zones"]:
        zone = assignment["zone_id"]
        assignment["start_date"] = start.isoformat()
        assignment["schedule"] = (
            [{"start_day": 1, "end_day": second_from - 1, "profile_id": f"zone-{zone}-current", "bias": 50},
             {"start_day": second_from, "end_day": 84, "profile_id": f"late-{zone}", "bias": 50}]
            if second_from else [{"start_day": 1, "end_day": 84, "profile_id": f"zone-{zone}-current", "bias": 50}])
    doc["name"] = "Autumn run"
    return doc


async def _running(hass, entry, prefix, kill, start, **plan):
    """A plan saved, armed two days ago and applied at today's lights-on, on the integration's own clock."""
    manager = _manager(hass, entry)
    _beat(hass, prefix, kill)
    await manager.save(_aligned_plan(manager, start=start, **plan), manager.document["revision"])
    now = dt_util.now()
    await manager.activate(manager.document["revision"], now)
    manager.document["armed_at"] = (now - timedelta(days=2)).isoformat()
    await manager.tick(now)
    assert manager.document["status"] == "active", manager.degraded_reason
    hass.states.async_remove(f"sensor.crop_steering_{prefix}ai_heartbeat")  # the controller writes its own
    return manager


TENT, TENT_KILL = "tent_", "switch.crop_steering_tent_engine_enabled"
TENT_ARMED = (TENT_KILL, "switch.crop_steering_tent_system_enabled",
              "switch.crop_steering_tent_auto_irrigation_enabled", "switch.crop_steering_tent_zone_1_enabled")


async def _tent(hass, controller_for, monkeypatch, at, **plan):
    await _utc(hass)
    entry = await _install(hass)
    await _lights(hass, TENT, (at.hour - 1) % 24, (at.hour + 15) % 24)
    manager = await _running(hass, entry, TENT, TENT_KILL, at.date() - timedelta(days=16), **plan)
    c, fake, _clock = controller_for({"enable_flag": TENT_KILL})
    c._start = at - timedelta(hours=1)
    for switch in TENT_ARMED:
        hass.states.async_set(switch, "off")  # a room nobody has armed: nothing actuates while it is judged
    return entry, manager, c, fake


# ------------------------------------------------------------------ 1. a fresh install with a plan
async def test_a_fresh_install_runs_its_plan_on_track(hass, controller_for, monkeypatch):
    at = _start()
    entry, manager, c, fake = await _tent(hass, controller_for, monkeypatch, at)
    await _pass(hass, c, fake, monkeypatch, manager, at)
    room = room_of(c)
    assert room.strategy_snapshot["required"] and not room.strategy_snapshot["error"]
    plan = fake.sets["sensor.crop_steering_tent_jev"][1]["plan"]
    assert plan["status"] == "active" and plan["headline"] == "Plan: Autumn run · day 17 of 84 (week 3) · on track"
    assert _cards(fake) == []
    today = manager.preview(grow_day=at.date().isoformat())["zones"][0]["parameters"]
    for key, value in today.items():
        assert c._zone_num(room, 1, key, None) == pytest.approx(value), key  # what the engine reads
    assert _number_writes(fake) == []


# ------------------------------------------------------------------ 2. an upgraded 3.11.1 install with an active plan
def _seeded_3_11_1(hass_storage, today):
    """The strategy store document 3.11.1 wrote for the pumped room, moved to today: day 25 of its first profile."""
    store = copy.deepcopy(fixture("strategy_3_11_1_active.json")["store"])
    data = store["data"]
    start = today - timedelta(days=24)
    for assignment in data["plan"]["zones"]:
        assignment["start_date"] = start.isoformat()
    data["active"]["grow_day"] = today.isoformat()
    data["armed_at"] = (datetime.combine(start, time()) - timedelta(days=1)).isoformat() + "+00:00"
    data["armed_after"] = None
    hass_storage[store["key"]] = store
    return data


async def test_an_upgraded_3_11_1_room_with_an_active_plan_runs_it_unchanged(
    hass, hass_storage, controller_for, monkeypatch
):
    """F-3111 with the plan 3.11.1 stored and the state.json 3.11.1 left (no _adherence): the room loads, the targets
    in force are exactly the stored snapshot's, no CS-713, and the plan line appears."""
    await _utc(hass)
    at = _start()
    seed = fixture(JEV_3_11_1)
    stored = _seeded_3_11_1(hass_storage, at.date())
    entry, _ = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    manager = _manager(hass, entry)
    assert manager.document["status"] == "active" and "applied_day" not in manager.document["active"]["zones"][0]
    await _lights(hass, "", (at.hour - 1) % 24, (at.hour + 15) % 24)
    state = fixture("state_3_11_1_learn_jev.json")["state"]
    assert "_adherence" not in state["default"]
    c, fake, _clock = controller_for(fixture("options_3_11_1_jev_cf.json")["options"] | {"brain_provider": "rules"},
                                     saved_state=state)
    c._start = at - timedelta(hours=1)
    await _pass(hass, c, fake, monkeypatch, manager, at)
    room = room_of(c, "")
    assert room._setup_pending is None
    for row in stored["active"]["zones"]:
        for key, value in row["parameters"].items():
            assert c._zone_num(room, row["zone_id"], key, None) == pytest.approx(value), key
    assert _cards(fake) == []
    plan = fake.sets["sensor.crop_steering_jev"][1]["plan"]
    assert plan["headline"].startswith("Plan: Zone 1 early") is False  # two zones, two profiles: no one name
    assert plan["headline"].startswith("Plan · day 25 of 84 (week 4) · on track")
    assert _number_writes(fake) == []


# ------------------------------------------------------------------ 3. a restart across lights-on that misses a day
async def _held_room(hass, hass_storage, controller_for, monkeypatch, options):
    """F-3111, its plan's day 41 starting a second profile today. The controller stopped yesterday in P3; at lights-on
    zone 2's moisture probe went dark (zone 2 switched off: an empty bench), so the integration moves zone 1 on to
    day 41 and keeps zone 2 on day 40. The controller restarts after lights-on."""
    await _utc(hass)
    at = _start()
    seed = fixture(JEV_3_11_1)
    data = _seeded_3_11_1(hass_storage, at.date())
    start = at.date() - timedelta(days=40)
    for assignment in data["plan"]["zones"]:
        assignment["start_date"] = start.isoformat()
        assignment["schedule"] = [
            {"start_day": 1, "end_day": 40, "profile_id": assignment["schedule"][0]["profile_id"], "bias": 50},
            {"start_day": 41, "end_day": 84, "profile_id": assignment["schedule"][1]["profile_id"], "bias": 50}]
    data["active"]["grow_day"] = (at.date() - timedelta(days=1)).isoformat()
    for row in data["active"]["zones"]:
        row["day"] = 40
    entry, _ = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    manager = _manager(hass, entry)
    await _lights(hass, "", (at.hour - 1) % 24, (at.hour + 15) % 24)
    hass.states.async_set(KILL, "on")
    hass.states.async_set("switch.crop_steering_zone_1_enabled", "on")
    hass.states.async_set("switch.crop_steering_zone_2_enabled", "off")
    hass.states.async_set("sensor.zone_2_vwc", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.crop_steering_vwc_zone_2", "unavailable")
    _beat(hass, "", KILL)
    await manager.tick(dt_util.now())
    rows = {r["zone_id"]: r for r in manager.document["active"]["zones"]}
    assert manager.document["active"]["grow_day"] == at.date().isoformat()
    assert (rows[1]["day"], rows[2]["day"]) == (41, 40) and rows[2]["held"]
    assert manager.degraded_kind == "probe_stale"
    hass.states.async_remove("sensor.crop_steering_ai_heartbeat")  # the controller writes its own
    state = fixture("state_3_11_1_learn_jev.json")["state"]
    yesterday = (at.date() - timedelta(days=1)).isoformat()
    for zone in ("1", "2"):
        state["default"][zone].update(phase="P3", last_daily_reset=yesterday,
                                      last_phase_change=f"{yesterday}T{(at.hour + 15) % 24:02d}:00:00")
    c, fake, _clock = controller_for(fixture("options_3_11_1_jev_cf.json")["options"] | options, saved_state=state)
    c._start = at - timedelta(hours=1)
    return manager, c, fake, at, {z: rows[z]["parameters"] for z in rows}, manager.preview(
        grow_day=at.date().isoformat())


async def test_a_missed_day_is_caught_and_under_rules_only_said(hass, hass_storage, controller_for, monkeypatch):
    manager, c, fake, at, held, _today = await _held_room(
        hass, hass_storage, controller_for, monkeypatch, {"brain_provider": "rules"})
    room = room_of(c, "")
    await _pass(hass, c, fake, monkeypatch, manager, at)
    # The restart across lights-on: decide() starts zone 1's day ("missed light edge"), the dead-probe path zone 2's.
    assert room.state[1]["phase"] in ("P0", "P1") and room.state[2]["phase"] in ("P0", "P1")
    log = room._adherence["phase_log"]
    assert "missed light edge" in log["1"][-1]["how"] and log["1"][-1]["to"] == "P0"
    assert "no moisture reading" in log["2"][-1]["how"] and log["2"][-1]["to"] == "P0"
    assert not _cards(fake, "f2_plan_missed")  # no tripwire: the existing guards did their job
    [card] = _cards(fake, "f2_plan_transition_missed")
    assert "(CS-713)" in card["title"] and "the maintenance shot size from" in card["message"]
    assert "Zone 2 VWC is unavailable or stale" in card["message"]
    for later in (11, 12, 40, 41):
        await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(minutes=later))
    assert c._zone_num(room, 2, "p2_shot_size", None) == pytest.approx(held[2]["p2_shot_size"])  # day 40 stays
    assert room._adherence["bridge"] is None and len(_cards(fake, "f2_plan_transition_missed")) == 1
    assert _number_writes(fake) == []


async def test_the_brain_bridges_the_missed_day_until_the_plan_applies_it(
    hass, hass_storage, controller_for, monkeypatch
):
    import brain_kit as B
    import brain_bridge
    from brain import client as jc

    client = B.FakeClient(B.judging(picks={"cause": "reading_holds_plan"}, p_yes=0.1))
    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(client))
    monkeypatch.setattr(brain_bridge, "Asker", functools.partial(jc.Asker, threaded=False))
    manager, c, fake, at, held, today = await _held_room(
        hass, hass_storage, controller_for, monkeypatch,
        {"brain_provider": "claude_haiku", "anthropic_api_key": B.SENTINEL, "jev_judges": "plan"})
    room = room_of(c, "")
    day41 = next(r["parameters"] for r in today["zones"] if r["zone_id"] == 2)
    assert day41["p2_shot_size"] != held[2]["p2_shot_size"]
    for minutes in (0, 11, 12, 31, 32):
        await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(minutes=minutes))
    asked = [r for r in client.requests if "keep_yesterday" in json.dumps(r["messages"])]
    assert asked, "the brain was asked whether to keep yesterday's targets"
    bridge = room._adherence["bridge"]
    assert bridge and bridge["day"] == at.date().isoformat() and bridge["checked"]
    assert c._zone_num(room, 2, "p2_shot_size", None) == pytest.approx(day41["p2_shot_size"])
    beat = fake.sets["sensor.crop_steering_ai_heartbeat"][1]
    assert beat["plan_bridged"] is True and beat["plan_day_in_force"] == at.date().isoformat()
    assert _cards(fake, "f2_jev_plan_bridge")
    assert _number_writes(fake) == []  # no number written: the plan's day, through the plan's read path
    assert manager.document["active"]["zones"][1]["day"] == 40  # and the plan itself untouched
    # Zone 2's probe reads again: the integration applies day 41 itself, and the bridge ends with no tripwire.
    hass.states.async_set("sensor.zone_2_vwc", "41.5", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    hass.states.async_set("sensor.crop_steering_vwc_zone_2", "41.5", {"unit_of_measurement": "%"})
    _beat(hass, "", KILL)
    await manager.tick(dt_util.now())
    hass.states.async_remove("sensor.crop_steering_ai_heartbeat")
    assert manager.degraded_kind is None
    await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(minutes=33))
    assert room._adherence["bridge"] is None and room._adherence["bridge_outcome"] == at.date().isoformat()
    assert not _cards(fake, "f2_plan_bridge_differs")
    assert c._zone_num(room, 2, "p2_shot_size", None) == pytest.approx(day41["p2_shot_size"])


# ------------------------------------------------------------------ 4. a hand edit advises, never overwrites
async def test_a_hand_edit_is_advised_and_comes_into_force_only_when_the_plan_is_disarmed(
    hass, controller_for, monkeypatch
):
    at = _start()
    entry, manager, c, fake = await _tent(hass, controller_for, monkeypatch, at)
    room = room_of(c)
    shot = "number.crop_steering_tent_zone_1_p2_shot_size"
    await _pass(hass, c, fake, monkeypatch, manager, at)  # the baseline
    planned = c._zone_num(room, 1, "p2_shot_size", None)
    by_hand = planned + 1.0
    await hass.services.async_call("number", "set_value", {"entity_id": shot, "value": by_hand}, blocking=True)
    fake.calls.clear()
    await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(minutes=16))
    [card] = _cards(fake, "f2_plan_shadowed_edit")
    assert "has no effect" in card["message"]
    assert _number_writes(fake) == []  # the controller never writes it back
    assert float(hass.states.get(shot).state) == by_hand
    assert c._zone_num(room, 1, "p2_shot_size", None) == pytest.approx(planned)  # the plan's value in force
    # Disarmed: at the next lights-on the room goes back to its own settings, the hand value included.
    await manager.disarm()
    boundary = datetime.combine(at.date() + timedelta(days=1), time(hour=(at.hour - 1) % 24, minute=1))
    await manager.tick(boundary.replace(tzinfo=timezone.utc))
    assert manager.document["status"] == "draft" and manager.document["release_legacy"] is True
    await _pass(hass, c, fake, monkeypatch, manager, boundary + timedelta(minutes=1), days=())
    assert c._zone_num(room, 1, "p2_shot_size", None) == pytest.approx(by_hand)


# ------------------------------------------------------------------ 5. saved, not armed
async def test_a_plan_saved_and_never_armed_is_said_once(hass, controller_for, monkeypatch):
    await _utc(hass)
    at = _start()
    entry = await _install(hass)
    await _lights(hass, TENT, (at.hour - 1) % 24, (at.hour + 15) % 24)
    manager = _manager(hass, entry)
    await manager.save(_aligned_plan(manager, start=at.date() - timedelta(days=1), second_from=60), 0)
    c, fake, _clock = controller_for({"enable_flag": TENT_KILL})
    c._start = at - timedelta(hours=1)
    for day in (0, 1, 2):
        await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(days=day), days=())
    assert len(_cards(fake, "f2_plan_saved_not_armed")) == 1
    assert fake.sets["sensor.crop_steering_tent_jev"][1]["plan"]["headline"].startswith("Plan saved, not armed")


# ------------------------------------------------------------------ 6. a plan ending
@pytest.mark.parametrize("day, said", [(81, "in 3 days"), (83, "in 1 days"), (80, None)])
async def test_a_plan_ending_is_said_at_three_days_and_at_one(hass, controller_for, monkeypatch, day, said):
    at = _start()
    await _utc(hass)
    entry = await _install(hass)
    await _lights(hass, TENT, (at.hour - 1) % 24, (at.hour + 15) % 24)
    manager = await _running(hass, entry, TENT, TENT_KILL, at.date() - timedelta(days=day - 1))
    c, fake, _clock = controller_for({"enable_flag": TENT_KILL})
    c._start = at - timedelta(hours=1)
    await _pass(hass, c, fake, monkeypatch, manager, at)
    cards = _cards(fake, "f2_plan_plan_ending")
    assert (said in cards[0]["message"]) if said else cards == []


async def test_a_plan_that_has_ended_is_the_integrations_hold_not_a_cs_713(hass, controller_for, monkeypatch):
    at = _start()
    await _utc(hass)
    entry = await _install(hass)
    await _lights(hass, TENT, (at.hour - 1) % 24, (at.hour + 15) % 24)
    manager = await _running(hass, entry, TENT, TENT_KILL, at.date() - timedelta(days=90))
    assert manager.document["active"]["zones"][0]["status"] == "complete"
    c, fake, _clock = controller_for({"enable_flag": TENT_KILL})
    c._start = at - timedelta(hours=1)
    await _pass(hass, c, fake, monkeypatch, manager, at)
    assert _cards(fake) == []
    from strategy_runtime import strategy_block

    assert strategy_block(room_of(c).strategy_snapshot, 1) == "Strategy zone complete"


# ------------------------------------------------------------------ 5.76b the grow light against the lights hours
async def test_a_mapped_grow_light_on_at_night_is_said(hass, controller_for, monkeypatch):
    await _utc(hass)
    at = _start()
    hass.states.async_set("light.grow", "on")
    entry = await _install(hass, {"light_entity": "light.grow"})
    descriptor = hass.states.get("sensor.crop_steering_tent_engine_config").attributes
    assert descriptor["light_entity"] == "light.grow"
    # Lights on at the next hour: now is night by the hours, while the light reads on.
    await _lights(hass, TENT, (at.hour + 2) % 24, (at.hour + 10) % 24)
    manager = _manager(hass, entry)
    c, fake, _clock = controller_for({"enable_flag": TENT_KILL})
    c._start = at - timedelta(hours=1)
    for minutes in (0, 16):
        await _pass(hass, c, fake, monkeypatch, manager, at + timedelta(minutes=minutes), days=())
    assert room_of(c).light_entity == "light.grow"
    [card] = _cards(fake, "f2_plan_lights_entity")
    assert "reads on, but the lights hours say off" in card["message"]
    assert [d for dom, svc, d in fake.calls if dom == "light"] == []  # checked, never switched
