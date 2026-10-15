"""One kill switch per room, the one it had before the update, against a real Home Assistant.

test_gate_matrix.py proves WHICH switch each upgraded room stops on. These prove what that switch
does: OFF holds and no valve opens, OFF mid-shot closes the valve, an entity that is not the gate
neither stops nor starts water, a fresh install waters with no helper at all, and the Repairs card
names the switch the room really stops on.
"""

import pytest
from conftest import fixture, room_of, switch_calls
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from test_kill_switch_repair import _health_check_fires, _report, _shipped_options, checks  # noqa: F401
from test_setup_entry import _install
from test_upgrade_in_place import UPSTREAM_2_25_1, _upgrade

DOMAIN = "crop_steering"
LEGACY = "input_boolean.f2_control_enabled"
OWN = "switch.crop_steering_engine_enabled"
WATERING = (
    "switch.crop_steering_system_enabled",
    "switch.crop_steering_auto_irrigation_enabled",
    "switch.crop_steering_zone_1_enabled",
)
HELD = "Crop Steering Controller disabled (kill switch off)"


async def _f2251(hass, controller_for, *, helper, switch):
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    hass.states.async_set(OWN, switch)
    hass.states.async_set(LEGACY, helper)  # the app option still names it; the setup does not
    c, fake, clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = room_of(c, "")
    assert room._setup_pending is None  # resumed after the update: no disarm cycle
    for entity in WATERING:
        fake.set_state(entity, "on")
    return c, fake, clock, room


async def _env_era(hass, controller_for, *, helper):
    await _upgrade(hass, "entry_env_era.json")
    hass.states.async_set(LEGACY, helper)
    c, fake, clock = controller_for(_shipped_options())
    room = room_of(c, "")
    for entity in WATERING:
        fake.set_state(entity, "on")
    return c, fake, clock, room


# ------------------------------------------------------------------ the gate holds, others do not
@pytest.mark.parametrize("helper,switch", [("on", "off"), ("off", "on")])
async def test_a_2_25_1_room_stops_on_its_engine_switch_and_the_helper_changes_nothing(
    hass, controller_for, helper, switch
):
    import controller

    c, _fake, _clock, room = await _f2251(hass, controller_for, helper=helper, switch=switch)
    assert controller.room_gate(room) == OWN
    if switch == "off":
        assert c._blocked(room, 1) == HELD  # the helper ON does not start water
        return
    assert c._blocked(room, 1) is None  # the helper OFF does not stop it
    elapsed, aborted = c._wait_shot(room, 1, 6)
    assert aborted is None and elapsed == 6


async def test_an_env_era_room_stops_on_its_helper(hass, controller_for):
    import controller

    c, _fake, _clock, room = await _env_era(hass, controller_for, helper="off")
    assert controller.room_gate(room) == LEGACY
    assert c._blocked(room, 1) == HELD


async def test_a_fresh_install_waters_with_no_helper(hass, controller_for):
    import controller

    await _install(hass)
    c, fake, _clock = controller_for(_shipped_options())  # the shipped option names the helper
    room = room_of(c)  # a new room has a slug: its own switches are tent_ ones
    own = OWN.replace("crop_steering_", "crop_steering_tent_")
    assert hass.states.get(LEGACY) is None
    assert controller.room_gate(room) == own
    for entity in (own, *(w.replace("crop_steering_", "crop_steering_tent_") for w in WATERING)):
        fake.set_state(entity, "on")  # the room's own switch on, as the operator does after setup
    assert c._blocked(room, 1) is None


# ------------------------------------------------------------------ OFF mid-shot closes the valve
def _turn_off_mid_shot(monkeypatch, clock, fake, gate):
    import controller

    def sleep(seconds):
        clock.sleep(seconds)
        fake.set_state(gate, "off")  # the operator, after the shot has started

    monkeypatch.setattr(controller.time, "sleep", sleep)


async def test_the_engine_switch_off_mid_shot_closes_the_valve_of_a_2_25_1_room(hass, controller_for, monkeypatch):
    c, fake, clock, room = await _f2251(hass, controller_for, helper="on", switch="on")
    fake.calls.clear()
    _turn_off_mid_shot(monkeypatch, clock, fake, OWN)
    c._execute_shot(room, 1, 10, 30, flow_lps=0.05)
    calls = switch_calls(fake)
    assert calls[:3] == [
        ("turn_on", "switch.irrigation_pump"),
        ("turn_on", "switch.irrigation_main_line"),
        ("turn_on", "switch.zone_1_valve"),
    ]
    assert ("turn_off", "switch.zone_1_valve") in calls
    assert fake.states["switch.zone_1_valve"][0] == "off"
    assert clock.seconds < 30  # cut short, not run to the end


async def test_the_helper_off_mid_shot_closes_the_valve_of_an_env_era_room(hass, controller_for, monkeypatch):
    c, fake, clock, room = await _env_era(hass, controller_for, helper="on")
    fake.calls.clear()
    _turn_off_mid_shot(monkeypatch, clock, fake, LEGACY)
    c._execute_shot(room, 1, 10, 30, flow_lps=0.05)
    calls = switch_calls(fake)
    assert ("turn_on", "switch.veg_valve") in calls and ("turn_off", "switch.veg_valve") in calls
    assert fake.states["switch.veg_valve"][0] == "off"
    assert clock.seconds < 30


# ------------------------------------------------------------------ the Repairs cards name the gate
def _card(hass, key="kill_switch_missing"):
    issue = ir.async_get(hass).async_get_issue(DOMAIN, key)
    return None if issue is None else issue.translation_placeholders


def _not_gate(hass):
    return _card(hass, "engine_switch_not_gate")


async def test_a_2_25_1_room_is_never_told_its_engine_switch_does_not_stop_water(
    hass, controller_for, checks  # noqa: F811
):
    c, fake, _clock, _room = await _f2251(hass, controller_for, helper="on", switch="off")
    assert _report(hass, c, fake, "")["enable_flag"] == OWN
    hass.states.async_remove(LEGACY)  # the helper it no longer uses can go
    await _health_check_fires(hass, checks)
    assert _card(hass) is None and _not_gate(hass) is None

    er.async_get(hass).async_remove(OWN)  # its real kill switch gone: the card names it, and only it
    await hass.async_block_till_done()
    assert hass.states.get(OWN) is None
    await _health_check_fires(hass, checks)
    assert _card(hass)["kill_switch"] == OWN
    assert _not_gate(hass) is None


async def test_a_room_on_its_helper_is_told_its_engine_switch_does_not_stop_water(
    hass, controller_for, checks  # noqa: F811
):
    c, fake, _clock, _room = await _env_era(hass, controller_for, helper="on")
    hass.states.async_set(OWN, "on")  # a switch of that name exists; this room stops on the helper
    await _health_check_fires(hass, checks)
    assert _card(hass) is None  # its gate is there and ON: the room waters
    assert _not_gate(hass) is None  # no heartbeat yet: only the running controller knows its gate

    assert _report(hass, c, fake, "")["enable_flag"] == LEGACY
    await _health_check_fires(hass, checks)
    assert _card(hass) is None  # the gate is there: no kill-switch card
    # ...and still the operator is told, while the room waters, that Engine Enabled is not it.
    assert _not_gate(hass) == {"kill_switch": LEGACY, "engine_switch": OWN}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "engine_switch_not_gate")
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "engine_switch_not_gate"

    hass.states.async_remove(LEGACY)  # the helper goes: the kill-switch card names it
    await _health_check_fires(hass, checks)
    card = _card(hass)
    assert card["kill_switch"] == LEGACY and card["source"] == "the one its controller reports"
    assert _not_gate(hass) == {"kill_switch": LEGACY, "engine_switch": OWN}
