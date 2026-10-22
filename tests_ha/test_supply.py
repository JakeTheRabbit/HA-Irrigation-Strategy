"""The site store's supply section through a real Home Assistant: supply_get and supply_save in the
service registry, schema and auth store; sensor.crop_steering_supply_config absent until a supply is
saved, then carrying the pumps and each zone's demand from the room's own sizing; pump_over_capacity
refused with the number that fits; the save kept across a reload."""

import pytest
from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from test_setup_entry import _install

from custom_components.crop_steering.generated.defaults import SIZING_DEFAULTS
from custom_components.crop_steering.generated.guards import zone_demand_lph

DOMAIN = "crop_steering"
ROOM = "room:tent_"
SENSOR = "sensor.crop_steering_supply_config"
PUMP = "switch.main_pump"
REFUSED = "requires an authenticated Home Assistant administrator"


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


async def _call(hass, service, user=None, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def _room(hass):
    hass.states.async_set(PUMP, "off")
    return await _install(hass, {"pump_switch": PUMP, "plumbing": "pump_valves"})


def _demand():
    # The room's one zone has 4 plants and the generic dripper layout.
    return zone_demand_lph(
        4, SIZING_DEFAULTS["drippers_per_plant"], SIZING_DEFAULTS["dripper_flow_rate"]
    )


async def test_a_site_that_never_saved_a_supply_reads_as_before(hass):
    await _room(hass)
    assert hass.services.supports_response(DOMAIN, "supply_get") is (
        SupportsResponse.ONLY
    )
    assert hass.services.supports_response(DOMAIN, "supply_save") is (
        SupportsResponse.OPTIONAL
    )
    read = await _call(hass, "supply_get")
    assert (read["revision"], read["irrigation_pumps"]) == (0, [])
    assert read["capacity_check"]["ok"] is True and read["warnings"] == []
    assert hass.states.get(SENSOR) is None


async def test_supply_save_publishes_the_descriptor_and_reads_back(
    hass, hass_admin_user
):
    await _room(hass)
    demand = _demand()
    pump = {"entity_id": PUMP, "max_flow_lph": demand * 3, "max_concurrent_zones": 1}
    saved = await _call(
        hass,
        "supply_save",
        hass_admin_user,
        expected_revision=0,
        irrigation_pumps=[pump],
        zone_groups={ROOM: {"1": "a"}},
        zone_meters={ROOM: {"1": "sensor.tent_meter"}},
    )
    assert saved["revision"] == 1 and saved["readback"]["status"] == "ok"
    assert saved["capacity_check"]["ok"] is True
    state = hass.states.get(SENSOR)
    assert state.state == "1"
    assert state.attributes["irrigation_pumps"][0]["entity_id"] == PUMP
    assert state.attributes["zone_groups"] == {ROOM: {"1": "a"}}
    assert state.attributes["zone_meters"] == {ROOM: {"1": "sensor.tent_meter"}}
    assert state.attributes["zone_demand_lph"] == {ROOM: {"1": pytest.approx(demand)}}
    read = await _call(hass, "supply_get")
    assert read["revision"] == 1 and read["zone_groups"] == {ROOM: {"1": "a"}}
    with pytest.raises(HomeAssistantError, match="changed elsewhere"):
        await _call(
            hass,
            "supply_save",
            hass_admin_user,
            expected_revision=0,
            irrigation_pumps=[pump],
        )


async def test_a_pump_asked_to_feed_more_than_it_can_is_refused(hass, hass_admin_user):
    await _room(hass)
    pump = {"entity_id": PUMP, "max_flow_lph": _demand() / 2, "max_concurrent_zones": 2}
    with pytest.raises(HomeAssistantError, match=r"^pump_over_capacity:"):
        await _call(
            hass,
            "supply_save",
            hass_admin_user,
            expected_revision=0,
            irrigation_pumps=[pump],
        )
    preview = await _call(
        hass,
        "supply_save",
        hass_admin_user,
        expected_revision=0,
        preview=True,
        irrigation_pumps=[{**pump, "max_concurrent_zones": 1}],
    )
    assert set(preview) == {"diff", "capacity_check"}
    over = await _call(
        hass,
        "supply_save",
        hass_admin_user,
        expected_revision=0,
        preview=True,
        irrigation_pumps=[pump],
    )  # shown, not refused
    assert over["capacity_check"]["ok"] is False
    assert over["capacity_check"]["suggest_max_concurrent"] == 1
    assert (await _call(hass, "supply_get"))["revision"] == 0
    assert hass.states.get(SENSOR) is None


async def test_only_an_administrator_saves(hass):
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockUser

    await _room(hass)
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    staff = MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)
    with pytest.raises(HomeAssistantError, match=REFUSED):
        await _call(
            hass, "supply_save", staff, expected_revision=0, irrigation_pumps=[]
        )
    assert (await _call(hass, "supply_get", staff))["revision"] == 0


async def test_the_supply_is_kept_across_a_reload(hass, hass_admin_user):
    entry = await _room(hass)
    await _call(
        hass,
        "supply_save",
        hass_admin_user,
        expected_revision=0,
        irrigation_pumps=[{"entity_id": PUMP, "max_flow_lph": 5000.0}],
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "1"
    assert (await _call(hass, "supply_get"))["irrigation_pumps"][0][
        "max_concurrent_zones"
    ] == 1
