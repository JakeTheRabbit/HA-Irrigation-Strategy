"""Safety and operations, in a real Home Assistant with the real controller.

Stop all switches the room's kill switch off and every pump and valve of the room off, from the integration, so it
works with the controller app stopped. Each opt-in setting starts at what the room did before it (a select at
Off, a switch off, a tank size of 0, the Test Shot's 10 s), on a new room and on an updated one, and the real
controller then behaves as before: the waste valve rule, a rescue past a dead feed probe, the manual shot length,
rescue shots that do not raise the moisture, the pump dead-head alert and the estimated tank level.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from conftest import fixture, room_of
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from test_real_flow import ZONES, _to_zones_step
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

from homeassistant.data_entry_flow import FlowResultType

DOMAIN = "crop_steering"
NEW = "tent_"
KILL = "switch.crop_steering_tent_engine_enabled"
ARMED = (
    KILL,
    "switch.crop_steering_tent_room_active",
    "switch.crop_steering_tent_system_enabled",
    "switch.crop_steering_tent_auto_irrigation_enabled",
    "switch.crop_steering_tent_zone_1_enabled",
)
PUMP = "input_boolean.tent_pump"
VALVE = "input_boolean.tent_valve"
WASTE = "switch.tent_waste"

DEFAULTS = {
    "select.crop_steering_{p}rescue_miss_action": "Off",
    "select.crop_steering_{p}waste_valve_rule": "Off",
    "switch.crop_steering_{p}rescue_past_dead_feed_probe": "off",
    "number.crop_steering_{p}rescue_miss_count": "4",
    "number.crop_steering_{p}tank_size_l": "0",
    "number.crop_steering_{p}tank_estimate_low_pct": "20",
    "number.crop_steering_{p}pump_deadhead_watts": "20",
    "number.crop_steering_{p}zone_1_manual_shot_seconds": "10",
    "button.crop_steering_{p}stop_all": "unknown",
    "button.crop_steering_{p}tank_filled": "unknown",
}


def _states(hass, prefix):
    out = {}
    for key in DEFAULTS:
        state = hass.states.get(key.format(p=prefix))
        out[key] = None if state is None else str(state.state).removesuffix(".0")
    return out


async def _pumped_room(hass, waste=True):
    """A room on two real input_booleans (pump, zone valve), and a waste valve switch that is only a state."""
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"tent_pump": {}, "tent_valve": {}}}
    )
    hass.states.async_set(WASTE, "off")
    hass.states.async_set("sensor.gt1_vwc", "41", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.gt1_ec", "3100", {"unit_of_measurement": "µS/cm"})
    flow = hass.config_entries.flow
    flow_id = await _to_zones_step(hass)
    result = await flow.async_configure(flow_id, {**ZONES, "zone_1_switch": VALVE})
    assert result["step_id"] == "hardware", result.get("description_placeholders")
    answers = {"plumbing": "pump_valves", "pump_switch": PUMP}
    if waste:
        answers["waste_switch"] = WASTE
    result = await flow.async_configure(flow_id, answers)
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


async def _call(hass, domain, service, entity_id):
    await hass.services.async_call(domain, service, {"entity_id": entity_id}, blocking=True)


# ------------------------------------------------------------------ the settings start where the room was
async def test_a_new_room_starts_every_setting_at_what_it_did_before(hass):
    await _install(hass)
    assert _states(hass, NEW) == {key: value for key, value in DEFAULTS.items()}
    select = hass.states.get("select.crop_steering_tent_waste_valve_rule")
    assert select.attributes["options"] == ["Off", "Check closed", "Close for each shot"]
    desc = hass.states.get("sensor.crop_steering_tent_engine_config").attributes
    assert "waste" not in desc  # no waste valve mapped: the descriptor is as it was


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_updated_room_gets_every_setting_at_what_it_did_before(hass, controller_for, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed["registry"])
    assert _states(hass, "") == DEFAULTS
    c, fake, _clock = controller_for(seed.get("addon_options"), saved_state=seed.get("controller_saved"))
    room = room_of(c, "")
    for zone, st in room.state.items():  # an old state file has none of the new keys
        assert st["rescue_misses"] == 0 and st["rescue_check"] is None
    assert room.tank_estimate == {"filled_at": None, "used_l": 0.0}
    assert c._waste_rule(room) == "Off" and c._rescue_watch_on(room) is False
    c._watch_tank(room)
    assert not [e for e in fake.sets if e.endswith("tank_level")]  # a tank size of 0 publishes nothing


# ------------------------------------------------------------------ Stop all, with no controller running
async def test_stop_all_switches_the_room_off_with_the_controller_stopped(hass, hass_admin_user, monkeypatch):
    from homeassistant.components import persistent_notification

    from custom_components.crop_steering import safety_ops

    monkeypatch.setattr(safety_ops, "STOP_READBACK_S", 1.0)
    notes = []
    monkeypatch.setattr(persistent_notification, "async_create",
                        lambda hass, message, title=None, notification_id=None: notes.append(title))
    await _pumped_room(hass)
    await _call(hass, "switch", "turn_on", KILL)
    await _call(hass, "input_boolean", "turn_on", PUMP)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    hass.states.async_set(WASTE, "on")  # a switch Home Assistant has no device for: it stays on
    answer = await hass.services.async_call(
        DOMAIN, "stop_all", {"room_id": "room:tent_"}, blocking=True, return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.async_block_till_done()
    assert hass.states.get(KILL).state == "off"
    assert hass.states.get(PUMP).state == "off" and hass.states.get(VALVE).state == "off"
    assert answer["kill_switch"] == [KILL]
    assert answer["still_on"] == [WASTE]
    assert [t for t in notes if "(CS-308)" in t], notes


async def test_the_stop_all_button_does_the_same_and_switches_nothing_on(hass):
    await _pumped_room(hass, waste=False)
    await _call(hass, "switch", "turn_on", KILL)
    await _call(hass, "input_boolean", "turn_on", VALVE)
    assert hass.states.get(PUMP).state == "off"
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.crop_steering_tent_stop_all"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(KILL).state == "off"
    assert hass.states.get(VALVE).state == "off" and hass.states.get(PUMP).state == "off"
    assert hass.states.get("button.crop_steering_tent_stop_all").state != "unknown"


# ------------------------------------------------------------------ the real controller
def _arm(fake):
    for switch in ARMED:
        fake.set_state(switch, "on")


async def test_the_waste_valve_rule_holds_or_closes_and_off_changes_nothing(hass, controller_for, monkeypatch):
    import controller

    await _pumped_room(hass)
    desc = hass.states.get("sensor.crop_steering_tent_engine_config").attributes
    assert desc["waste"] == WASTE
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    assert room.waste == WASTE
    _arm(fake)
    rule = "select.crop_steering_tent_waste_valve_rule"
    fake.set_state(WASTE, "on")
    assert c._blocked(room, 1) is None  # Off: the waste valve is not read, as before

    fake.set_state(rule, "Check closed")
    assert c._blocked(room, 1) == f"waste valve {WASTE} reads on"
    fake.set_state(WASTE, "off")
    assert c._blocked(room, 1) is None

    fake.set_state(rule, "Close for each shot")
    fake.set_state(WASTE, "on")
    assert c._blocked(room, 1) is None
    fake.calls.clear()
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    sent = [(d, s, data["entity_id"]) for d, s, data in fake.calls if "entity_id" in data]
    assert sent[0] == ("switch", "turn_off", WASTE)  # closed before the pump primes
    assert ("input_boolean", "turn_on", PUMP) in sent and fake.states[WASTE][0] == "off"
    assert not [s for s in sent if s[2] == WASTE and s[1] == "turn_on"]  # never opened

    real = controller.ha_call

    def stuck(domain, service, **data):
        if data.get("entity_id") == WASTE:
            fake.calls.append((domain, service, data))
            return True  # taken, and it stays on
        return real(domain, service, **data)

    monkeypatch.setattr(controller, "ha_call", stuck)
    fake.set_state(WASTE, "on")
    fake.calls.clear()
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    assert not [call for call in fake.calls if call[2].get("entity_id") in (PUMP, VALVE)]  # nothing opened
    titles = [d["title"] for dom, s, d in fake.calls if (dom, s) == ("persistent_notification", "create")]
    assert any("(CS-316)" in t for t in titles), titles
    assert room.hardware_fault is None


@pytest.mark.parametrize("policy", ["Check closed", "Close for each shot"])
@pytest.mark.parametrize("lost", ["unknown", "unavailable", None])
async def test_an_unreadable_waste_policy_never_opens_the_feed(hass, controller_for, policy, lost):
    await _pumped_room(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    _arm(fake)
    rule = "select.crop_steering_tent_waste_valve_rule"
    fake.set_state(rule, policy)
    assert c._waste_rule(room) == policy
    fake.states[rule] = (lost, {})
    fake.set_state(WASTE, "on")
    assert "rule unreadable" in c._blocked(room, 1)
    fake.calls.clear()
    assert c._close_waste(room, 1) is False
    c._execute_shot(room, 1, 10, 5, flow_lps=0.05)
    assert not [call for call in fake.calls if call[2].get("entity_id") in (PUMP, VALVE)]


async def test_the_waste_policy_is_remembered_across_restart_but_old_missing_entities_stay_off(
    hass, controller_for, monkeypatch
):
    import controller

    await _pumped_room(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    rule = "select.crop_steering_tent_waste_valve_rule"
    monkeypatch.setattr(controller, "ha_get_status", lambda entity: (404, None))
    fake.states[rule] = (None, {})
    assert c._waste_rule(room) == "Off"  # confirmed absent, never configured on an older install
    fake.set_state(rule, "Close for each shot")
    assert c._waste_rule(room) == "Close for each shot"
    c._save_state()
    restarted, new_fake, _clock = controller_for({"enable_flag": KILL})
    new_room = room_of(restarted, NEW)
    assert new_room._waste_rule_known == "Close for each shot"
    monkeypatch.setattr(controller, "ha_get_status", lambda entity: (404, None))
    new_fake.states[rule] = (None, {})
    assert restarted._waste_rule(new_room) == "Unreadable"


async def test_a_rescue_passes_a_dead_feed_probe_only_when_switched_on(hass, controller_for):
    import controller

    hass.states.async_set("sensor.tank_ph", "6.0", {"unit_of_measurement": "pH"})
    await _install(hass, {"feed_ph_sensor": "sensor.tank_ph"})
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    _arm(fake)
    fake.set_state("sensor.tank_ph", "unavailable")
    rescue = controller.Reason("P3 emergency", "p3_emergency")
    routine = controller.Reason("P2 top-up", "p2_topup")
    assert "pH probe dead" in c._blocked(room, 1, rescue)  # off: held, as before
    fake.set_state("switch.crop_steering_tent_rescue_past_dead_feed_probe", "on")
    assert c._blocked(room, 1, rescue) is None
    assert c._blocked(room, 1, controller.Reason("watchdog", "watchdog")) is None
    assert "pH probe dead" in c._blocked(room, 1, routine)  # a routine shot still holds
    fake.set_state("sensor.tank_ph", "7.4", {"unit_of_measurement": "pH"})
    assert c._blocked(room, 1, rescue) == "source-water pH 7.40 out of [5.5,6.5]"  # bad feed never passes
    fake.set_state(KILL, "off")
    fake.set_state("sensor.tank_ph", "unavailable")
    assert "kill switch" in c._blocked(room, 1, rescue)  # nothing before the gate is skipped


async def test_the_test_shot_runs_for_the_manual_shot_length(hass, hass_admin_user, controller_for):
    hour = datetime.now().hour
    await _install(hass, {"lights_on_hour": (hour + 2) % 24, "lights_off_hour": (hour + 4) % 24})
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    _arm(fake)
    now = datetime.now()
    fake.set_state("number.crop_steering_tent_lights_on_hour", str((now.hour + 6) % 24))
    fake.set_state("number.crop_steering_tent_lights_off_hour", str((now.hour + 18) % 24))
    button = "button.crop_steering_tent_zone_1_test_shot"
    c.loop_once(datetime.now())
    flow = c._zone_flow_lps(room, 1)
    for seconds in (10, 30):
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": "number.crop_steering_tent_zone_1_manual_shot_seconds", "value": seconds}, blocking=True,
        )
        fake.set_state("number.crop_steering_tent_zone_1_manual_shot_seconds",
                       hass.states.get("number.crop_steering_tent_zone_1_manual_shot_seconds").state)
        water = room.state[1]["daily_vol"]
        await hass.services.async_call(DOMAIN, "test_shot", {"room_id": "room:tent_", "zone": 1}, blocking=True,
                                       return_response=True, context=Context(user_id=hass_admin_user.id))
        fake.set_state(button, hass.states.get(button).state)
        c.loop_once(datetime.now())
        assert room.state[1]["daily_vol"] - water == pytest.approx(flow * seconds, rel=0.25)
        assert room.state[1]["capped_in_a_row"] == 0


async def test_rescues_that_do_not_raise_the_moisture_alert_and_never_hold(hass, controller_for):
    import safety_ops

    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    _arm(fake)
    st, t = room.state[1], datetime.now()

    def titles():
        return [d["title"] for dom, s, d in fake.calls if (dom, s) == ("persistent_notification", "create")]

    for i in range(4):  # Off: nothing is counted
        safety_ops.rescue_fired(st, 30.0, t)
        c._watch_rescues(room, 1, SimpleNamespace(vwc=30.0), t + timedelta(minutes=20))
    assert st["rescue_misses"] == 0 and not [x for x in titles() if "CS-315" in x]

    fake.set_state("select.crop_steering_tent_rescue_miss_action", "Alert")
    for i in range(4):
        t += timedelta(hours=1)
        safety_ops.rescue_fired(st, 30.0, t)
        c._watch_rescues(room, 1, SimpleNamespace(vwc=30.2), t + timedelta(minutes=5))  # not settled yet
        c._watch_rescues(room, 1, SimpleNamespace(vwc=30.2), t + timedelta(minutes=16))
    assert st["rescue_misses"] == 4
    assert [x for x in titles() if "(CS-315)" in x]
    assert c._blocked(room, 1) is None  # it only tells
    safety_ops.rescue_fired(st, 30.0, t)
    c._watch_rescues(room, 1, SimpleNamespace(vwc=33.0), t + timedelta(minutes=16))
    assert st["rescue_misses"] == 0


async def test_the_pump_dead_head_alert_needs_its_sensor_and_only_tells(hass, controller_for):
    await _pumped_room(hass, waste=False)
    power = "sensor.feed_pump_power"
    c, fake, _clock = controller_for({"enable_flag": KILL, "pump_power_sensor": power})
    room = room_of(c, NEW)
    _arm(fake)
    fake.set_state(power, "150", {"unit_of_measurement": "W"})
    fake.set_state(PUMP, "on")
    fake.set_state(VALVE, "off")
    t = datetime.now()

    def raised():
        return [d["title"] for dom, s, d in fake.calls if (dom, s) == ("persistent_notification", "create")
                and "(CS-317)" in d["title"]]

    fake.set_state("input_boolean.hold", "on")
    c.hold_entities = ["input_boolean.hold"]
    c._watch_deadhead(room, t)
    c._watch_deadhead(room, t + timedelta(seconds=90))
    assert raised() == []  # a hold may run the pump with the valves shut
    c.hold_entities = []
    c._watch_deadhead(room, t)
    assert raised() == []  # not for a moment
    c._watch_deadhead(room, t + timedelta(seconds=61))
    assert raised()
    assert not [call for call in fake.calls if call[2].get("entity_id") == PUMP]  # never switched off


async def test_the_estimated_tank_level_counts_shots_from_the_fill_and_never_holds(hass, controller_for):
    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = room_of(c, NEW)
    _arm(fake)
    level = "sensor.crop_steering_tent_tank_level"
    fake.set_state("number.crop_steering_tent_tank_size_l", "100")
    c._watch_tank(room)
    assert fake.sets[level][0] == "unknown"  # no fill seen yet: not a guess at full
    fake.set_state("button.crop_steering_tent_tank_filled", datetime.now(timezone.utc).isoformat())
    c._watch_tank(room)
    assert fake.sets[level][0] == 100.0 and fake.sets[level][1]["source"] == "estimate"
    c._advance_shot_counters(room, 1, 5, delivered_l=85.0)
    c._watch_tank(room)
    assert fake.sets[level][0] == 15.0 and fake.sets[level][1]["holds_shots"] is False
    titles = [d["title"] for dom, s, d in fake.calls if (dom, s) == ("persistent_notification", "create")]
    assert [x for x in titles if "(CS-905)" in x]
    assert c._blocked(room, 1) is None and c._tank_hold(room) is None
    saved = c._read_state_file()[room.slug]["_tank_estimate"]
    assert saved["used_l"] == 85.0
    c._tank_estimate_filled(room)  # a batch that filled the tank
    assert room.tank_estimate["used_l"] == 0.0
