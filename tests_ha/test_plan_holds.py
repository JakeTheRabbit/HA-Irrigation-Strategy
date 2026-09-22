"""A room's grow-strategy plan and its holds, in a real Home Assistant.

A plan that is armed or running manages a fixed set of zones. A zone change saved underneath it used to
put the plan in error, which holds the steering of every zone it manages: the options flow now refuses
it until the plan is disarmed. And every hold of the plan, and a plan that could not apply its day, is a
card in the real Repairs registry.
"""

from datetime import timedelta

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.crop_steering import health
from test_configure import _open, _shown, _suggested
from test_setup_entry import _install

DOMAIN = "crop_steering"
HEARTBEAT = "sensor.crop_steering_ai_heartbeat"
ZONE_2 = {
    "zone_2_name": "Second tent",
    "zone_2_active": True,
    "zone_2_switch": "switch.gt2_irrigation_switch",
    "zone_2_vwc": ["sensor.gt2_vwc"],
    "zone_2_ec": ["sensor.gt2_ec"],
    "zone_2_plant_count": 4,
}


def _plan(hass, entry):
    return hass.data[DOMAIN]["_strategy"][entry.entry_id]


async def _add_a_zone(hass, entry):
    hass.states.async_set("switch.gt2_irrigation_switch", "off")
    hass.states.async_set("sensor.gt2_vwc", "43", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.gt2_ec", "3000", {"unit_of_measurement": "µS/cm"})
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"num_zones": 2}
    )
    assert flow["step_id"] == "edit_zones_map"
    return await hass.config_entries.options.async_configure(
        flow["flow_id"], {**_shown(flow), **_suggested(flow), **ZONE_2}
    )


async def test_a_zone_change_is_refused_in_the_form_while_the_plan_is_armed(hass):
    entry = await _install(hass)
    _plan(hass, entry).document["status"] = "armed"
    revision = entry.data["setup_revision"]
    result = await _add_a_zone(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "edit_zones_map"
    assert "disarm it" in result["description_placeholders"]["error"]
    assert entry.data["num_zones"] == 1 and entry.data["setup_revision"] == revision


async def test_the_same_zone_change_is_saved_while_the_plan_is_a_draft(hass):
    entry = await _install(hass)
    assert _plan(hass, entry).document["status"] == "draft"  # every new room's plan
    result = await _add_a_zone(hass, entry)
    assert result["type"] is FlowResultType.CREATE_ENTRY, result.get("errors")
    await hass.async_block_till_done()
    assert entry.data["num_zones"] == 2


async def test_every_hold_of_the_plan_is_a_repairs_card(hass):
    entry = await _install(hass)
    plan = _plan(hass, entry)
    registry = ir.async_get(hass)

    # A plan that manages zones the room does not have: only the operator can put that right.
    plan.document.update(status="armed", armed_at=dt_util.now().isoformat())
    plan.document["plan"]["zones"] = []
    await plan.tick()
    assert plan.document["status"] == "error"
    health.run_health_check(hass, entry)
    card = registry.async_get_issue(DOMAIN, "strategy_hold")
    assert card is not None and card.severity is ir.IssueSeverity.ERROR
    assert card.translation_key == "strategy_hold"
    assert "do not match" in card.translation_placeholders["reason"]

    # A controller holding the room on a plan it cannot use says so on its heartbeat.
    plan.document.update(status="draft", error=None)
    await plan.tick()
    hass.states.async_set(
        HEARTBEAT,
        "healthy",
        {
            "enable_flag": "switch.crop_steering_engine_enabled",
            "strategy_error": "Strategy snapshot is stale",
        },
    )
    health.run_health_check(hass, entry)
    card = registry.async_get_issue(DOMAIN, "strategy_hold")
    assert card is not None and "stale" in card.translation_placeholders["reason"]

    hass.states.async_set(
        HEARTBEAT, "healthy", {"enable_flag": "switch.crop_steering_engine_enabled"}
    )
    health.run_health_check(hass, entry)
    assert registry.async_get_issue(DOMAIN, "strategy_hold") is None


async def test_a_plan_that_could_not_apply_its_day_is_a_warning_card(hass):
    entry = await _install(hass)
    plan = _plan(hass, entry)
    registry = ir.async_get(hass)
    # Armed two days ago; no controller has reported since, so the day cannot be applied yet.
    armed = dt_util.now() - timedelta(days=2)
    plan.document.update(status="armed", armed_at=armed.isoformat())
    await plan.tick()
    assert plan.document["status"] == "armed" and plan.degraded_reason
    published = hass.states.get("sensor.crop_steering_strategy_plan")
    assert published.attributes["degraded_reason"] == plan.degraded_reason
    health.run_health_check(hass, entry)
    card = registry.async_get_issue(DOMAIN, "strategy_degraded")
    assert card is not None and card.severity is ir.IssueSeverity.WARNING
    assert card.translation_placeholders["reason"] == plan.degraded_reason

    plan.document.update(status="draft", armed_at=None)
    await plan.tick()
    health.run_health_check(hass, entry)
    assert registry.async_get_issue(DOMAIN, "strategy_degraded") is None
