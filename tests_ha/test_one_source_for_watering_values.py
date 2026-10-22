"""One source for each derived watering value, in a real Home Assistant.

The integration worked out figures of its own beside the controller's: an EC ratio and an "adjusted
re-water point" from a select the controller never reads, with four settings that only fed them, a
shot length that ignored a broken room limit, and room means over archived zones. The figures that
mirror the controller now give its number; the ones it has no number for are retired: kept, hidden
and unknown with a reason, so an old install loads with every entity id it had and an automation
that names one still loads, with a Repairs card (CS-614) saying so.
"""

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_component import async_update_entity
from homeassistant.setup import async_setup_component

from conftest import fixture, room_of
from custom_components.crop_steering.const import DEPRECATED
from test_install_to_controller import KILL
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
OLD = "entry_3_11_1_pumped_room.json"


def _deprecated_ids(prefix):
    return [f"{domain}.{DOMAIN}_{prefix}{key}" for domain, keys in DEPRECATED.items() for key in keys]


async def test_an_old_install_keeps_every_retired_entity_id_hidden_and_loads(hass):
    await _upgrade(hass, OLD, registry_ids=fixture(OLD)["registry"])
    registry = er.async_get(hass)
    for entity_id in _deprecated_ids(""):
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id  # the same id the old install had
        assert registry.async_get(entity_id + "_2") is None, entity_id
        assert entry.hidden_by is er.RegistryEntryHider.INTEGRATION, entity_id
        assert hass.states.get(entity_id) is not None, entity_id
    for key in ("ec_ratio", "p2_vwc_threshold_adjusted"):
        state = hass.states.get(f"sensor.{DOMAIN}_{key}")
        assert state.state == "unknown" and state.attributes["reason"].startswith("Retired:")
    # The settings keep working for whatever still sets them.
    assert float(hass.states.get(f"number.{DOMAIN}_p2_ec_high_threshold").state) > 0
    assert ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_entities") is None


async def test_a_new_room_creates_the_retired_entities_hidden(hass):
    await _install(hass)
    registry = er.async_get(hass)
    for entity_id in _deprecated_ids("tent_"):
        assert registry.async_get(entity_id).hidden_by is er.RegistryEntryHider.INTEGRATION
    assert ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_entities_tent") is None


async def test_an_automation_that_uses_a_retired_entity_gets_a_repairs_card(hass):
    used = f"number.{DOMAIN}_tent_p2_ec_high_threshold"
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "ec_watch",
                "alias": "EC watch",
                "triggers": [{"trigger": "state", "entity_id": used}],
                "actions": [{"event": "ec_watch"}],
            }
        },
    )
    await _install(hass)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_entities_tent")
    assert issue is not None and issue.translation_key == "deprecated_entities"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert used in issue.translation_placeholders["entities"]
    assert "automation.ec_watch" in issue.translation_placeholders["entities"]
    assert issue.translation_placeholders["count"] == "1"


async def test_a_retired_entity_named_only_inside_a_template_is_found_too(hass):
    used = f"sensor.{DOMAIN}_tent_ec_ratio"
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "ec_note": {
                    "sequence": [
                        {"event": "ec_note", "event_data": {"ratio": "{{ states('%s') }}" % used}}
                    ]
                }
            }
        },
    )
    await _install(hass)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_entities_tent")
    assert issue is not None
    assert "script.ec_note" in issue.translation_placeholders["entities"]
    assert used in issue.translation_placeholders["entities"]


async def test_a_room_limit_that_is_not_one_shows_no_shot_length_as_the_controller_runs_none(
    hass, controller_for
):
    await _install(hass)
    hass.states.async_set(f"number.{DOMAIN}_tent_max_shot_duration", "unavailable")
    c, _fake, _clock = controller_for({"enable_flag": KILL})
    assert c._room_duration_cap(room_of(c)) is None  # the controller starts no shot (CS-203)
    entity_id = f"sensor.{DOMAIN}_tent_p2_shot_duration_seconds"
    await async_update_entity(hass, entity_id)
    state = hass.states.get(entity_id)
    assert state.state == "unknown" and state.attributes["zones"] == {}


async def test_shots_today_is_unknown_until_the_controller_counts(hass):
    await _install(hass)
    entity_id = f"sensor.{DOMAIN}_tent_zone_1_irrigation_count_today"
    await async_update_entity(hass, entity_id)
    assert hass.states.get(entity_id).state == "unknown"
    hass.states.async_set(f"sensor.{DOMAIN}_tent_zone_1_irrigation_count_app", "4")
    await async_update_entity(hass, entity_id)
    assert hass.states.get(entity_id).state == "4"
