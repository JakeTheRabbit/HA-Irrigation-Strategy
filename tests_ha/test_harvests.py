"""Harvest services run in real HA, with revision, ownership and upgrade checks."""

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockUser
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade


async def call(hass, user, service, room="room:tent_", **data):
    return await hass.services.async_call(
        "crop_steering", service, {"room_id": room, **data}, blocking=True,
        return_response=True, context=Context(user_id=user.id),
    )


async def test_harvest_persists_across_reload_and_run_edits(hass, hass_admin_user):
    entry = await _install(hass)
    runs = await call(hass, hass_admin_user, "runs_save", expected_revision=0,
                      record={"name": "Grow", "start_date": "2026-01-01"})
    run = runs["runs"][0]
    harvest = {"room": {"dry_weight_g": 2500, "plants_harvested": 10}, "notes": "Hand weighed"}
    doc = await call(hass, hass_admin_user, "runs_set_harvest", expected_revision=0,
                     run_id=run["id"], harvest=harvest)
    assert doc["harvests"][run["id"]]["room"]["dry_weight_g"] == 2500
    with pytest.raises(HomeAssistantError, match="changed elsewhere"):
        await call(hass, hass_admin_user, "runs_set_harvest", expected_revision=0,
                   run_id=run["id"], harvest=harvest)
    with pytest.raises(HomeAssistantError, match="does not belong"):
        await call(hass, hass_admin_user, "runs_set_harvest", expected_revision=1,
                   run_id="other-room-run", harvest=harvest)
    await call(hass, hass_admin_user, "runs_save", expected_revision=runs["revision"],
               record={"id": run["id"], "name": "Renamed", "start_date": "2026-01-01"})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await call(hass, hass_admin_user, "harvests_get") == doc
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    user = MockUser(name="Reader", groups=[group]).add_to_hass(hass)
    assert await call(hass, user, "harvests_get") == doc
    with pytest.raises(HomeAssistantError, match="administrator"):
        await call(hass, user, "runs_set_harvest", expected_revision=1,
                   run_id=run["id"], harvest=None)
    with pytest.raises(HomeAssistantError, match="outside"):
        await call(hass, hass_admin_user, "runs_set_harvest", expected_revision=1,
                   run_id=run["id"], harvest={"room": {"dry_weight_g": -1}})


async def test_old_install_has_empty_harvest_store(hass, hass_admin_user):
    await _upgrade(hass, JEV_3_11_1)
    doc = await call(hass, hass_admin_user, "harvests_get", room="room:")
    assert doc["revision"] == 0 and doc["harvests"] == {}
