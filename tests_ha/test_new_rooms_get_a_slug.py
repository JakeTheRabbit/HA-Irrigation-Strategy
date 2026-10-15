"""Every new room gets a slug; only an upgraded install's un-prefixed room keeps un-prefixed ids.

The first room used to be the "default" room with no prefix (`number.crop_steering_p1_target_vwc`),
and every room after it was prefixed. So a new install's ids depended on which room happened to be
set up first, and a room that was deleted and set up again moved between the two schemes. Now a
new room is always `crop_steering_<slug>_*`, from its name. Rooms already installed keep the ids
their registry holds: dashboards, automations and history hang off them.

One exception: a .env import still makes the un-prefixed room. The controller app's kill switch and
feed probe options govern that room, and this integration cannot see them, so a slug would move its
kill switch and drop its source-water gate without a word.
"""

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from conftest import room_of, switch_calls
from test_real_flow import VALVE
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
SITE_WIDE = {"sensor.crop_steering_notify_config"}  # one for the whole site, never prefixed


def _ids(hass, entry):
    registry = er.async_get(hass)
    return {
        item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    } - SITE_WIDE


async def test_a_new_installs_first_room_has_a_slug_and_every_id_carries_it(hass):
    entry = await _install(hass)
    assert (entry.data["room_slug"], entry.data["room_prefix"]) == ("tent", "tent_")
    assert entry.unique_id == "room_tent"
    assert entry.data["enable_flag"] == "switch.crop_steering_tent_engine_enabled"
    ids = _ids(hass, entry)
    assert len(ids) > 80
    assert all(i.split(".", 1)[1].startswith("crop_steering_tent_") for i in ids), sorted(
        i for i in ids if "crop_steering_tent_" not in i
    )
    assert hass.states.get("sensor.crop_steering_tent_engine_config").attributes["prefix"] == "tent_"
    assert hass.states.get("sensor.crop_steering_engine_config") is None


ENV_FILE = "ZONE_1_SWITCH=switch.bench_valve\nZONE_1_VWC_SENSORS=sensor.bench_vwc\nZONE_1_EC_SENSORS=sensor.bench_ec\n"


async def _import_env(hass, tmp_path, name):
    """A fresh install set up from a crop_steering.env file instead of the wizard."""
    (tmp_path / "crop_steering.env").write_text(ENV_FILE, encoding="utf-8")
    hass.config.config_dir = str(tmp_path)
    hass.states.async_set("switch.bench_valve", "off")
    hass.states.async_set("sensor.bench_vwc", "41", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.bench_ec", "3.1", {"unit_of_measurement": "mS/cm"})
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "user"
    result = await flow.async_configure(result["flow_id"], {"name": name, "config_method": "env"})
    await hass.async_block_till_done()
    return result


async def test_a_new_install_imported_from_env_stays_the_un_prefixed_room_the_app_options_govern(
    hass, tmp_path, controller_for
):
    result = await _import_env(hass, tmp_path, "Veg Tent")
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    entry = result["result"]
    assert entry.data["config_method"] == "env"
    assert (entry.data["room_slug"], entry.data["room_prefix"]) == ("default", "")
    assert entry.unique_id == "default"
    assert not any("crop_steering_veg_tent_" in i for i in _ids(hass, entry))
    descriptor = hass.states.get("sensor.crop_steering_engine_config").attributes
    assert descriptor["prefix"] == "" and descriptor["setup_revision"] == 0

    kill = "input_boolean.bench_kill_switch"  # the operator's own helper, named in the app option
    hass.states.async_set(kill, "on")
    hass.states.async_set("sensor.app_feed_ec", "3.5", {"unit_of_measurement": "mS/cm"})
    hass.states.async_set("sensor.app_feed_ph", "6.0")
    c, fake, _clock = controller_for(
        {"enable_flag": kill, "feed_ec_sensor": "sensor.app_feed_ec", "feed_ph_sensor": "sensor.app_feed_ph"}
    )
    room = room_of(c, "")
    assert sorted(room.zones) == [1] and room.hw["valves"] == {1: "switch.bench_valve"}
    assert room.enable_flag == kill
    assert (room.feed_ec_sensor, room.feed_ph_sensor) == ("sensor.app_feed_ec", "sensor.app_feed_ph")
    fake.set_state("switch.crop_steering_room_active", "on")
    fake.set_state("switch.crop_steering_zone_1_enabled", "on")
    fake.set_state("number.crop_steering_irrigation_ec_min", "1.0")
    fake.set_state("number.crop_steering_irrigation_ec_max", "2.0")
    assert "source-water EC 3.5" in c._blocked(room, 1)  # the app's feed probe gates the room
    fake.set_state(kill, "off")
    assert "disabled" in c._blocked(room, 1)  # the app's kill switch holds the room


@pytest.mark.parametrize(
    "name",
    [
        "entry_2_17_wizard.json",  # F-217
        "entry_env_era.json",  # F-ENV
        "entry_2_25_1_pumped_room.json",  # F-2251
        "entry_3_11_1_pumped_room.json",  # F-3111
    ],
)
async def test_an_upgraded_un_prefixed_room_keeps_its_ids_and_the_next_room_gets_a_slug(
    hass, name
):
    hass.states.async_set("input_boolean.f2_control_enabled", "off")  # an env-era room's kill switch
    entry, seed = await _upgrade(hass, name)
    assert entry.data.get("room_prefix", "") == "" == seed["data"].get("room_prefix", "")
    assert hass.states.get("sensor.crop_steering_engine_config").attributes["prefix"] == ""
    assert hass.states.get("number.crop_steering_lights_on_hour") is not None
    assert not any("crop_steering_tent_" in i for i in _ids(hass, entry))

    # A room added beside it is new, so it has a slug like any new room.
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "room"
    result = await flow.async_configure(result["flow_id"], {"room_name": "Veg Tent"})
    assert result["step_id"] == "manual_zones"


async def test_the_controller_adopts_and_waters_a_new_room_that_has_a_slug(hass, controller_for):
    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": "input_boolean.f2_control_enabled"})
    room = room_of(c)
    assert room.slug == "tent" and room.enable_flag == "switch.crop_steering_tent_engine_enabled"
    assert room.setup_revision == 1 and room._setup_pending is None
    assert room_of(c, "").zones == {}  # the app's built-in room invents nothing to water
    for switch in (
        "switch.crop_steering_tent_engine_enabled",
        "switch.crop_steering_tent_system_enabled",
        "switch.crop_steering_tent_auto_irrigation_enabled",
        "switch.crop_steering_tent_zone_1_enabled",
    ):
        fake.set_state(switch, "on")
    assert not c._blocked(room, 1)
    fake.calls.clear()
    c._execute_shot(room, 1, 30, 5, flow_lps=c._zone_flow_lps(room, 1))
    assert switch_calls(fake) == [("turn_on", VALVE), ("turn_off", VALVE)]
    assert room.state[1]["shots"] == 1


@pytest.mark.parametrize("install", ["new", "entry_2_25_1_pumped_room.json"])  # a new room; F-2251
async def test_the_app_options_reach_a_new_room_with_a_slug_as_they_reached_a_wizard_room(
    hass, controller_for, install
):
    """The app's `enable_flag`, `feed_ec_sensor` and `feed_ph_sensor` options set only a room's
    start-up values once the room has a revisioned setup, which every room the wizard or the
    dashboard's setup makes has (F-2251's un-prefixed one included). Such a room then runs on its
    own setup's kill switch and feed probes, so a new room with a slug gates and checks its source
    water exactly as the un-prefixed room the wizard used to make. A .env import has no revisioned
    setup; it stays un-prefixed and the options govern it (tested above)."""
    helper = "input_boolean.f2_control_enabled"
    hass.states.async_set(helper, "off")  # the operator made the helper and switched it off
    if install == "new":
        await _install(hass)
        prefix = "tent_"
    else:
        await _upgrade(hass, install)
        prefix = ""
    kill = f"switch.crop_steering_{prefix}engine_enabled"
    hass.states.async_set(kill, "off")
    published = hass.states.get(f"sensor.crop_steering_{prefix}engine_config").attributes
    c, fake, _clock = controller_for(
        {"enable_flag": helper, "feed_ec_sensor": "sensor.app_feed_ec", "feed_ph_sensor": "sensor.app_feed_ph"}
    )
    room = room_of(c, prefix)
    assert published["setup_revision"] == room.setup_revision == 1 and room._setup_pending is None
    assert room.enable_flag == published["enable_flag"] == kill
    assert (room.feed_ec_sensor, room.feed_ph_sensor) == (
        published["feed_ec_sensor"],
        published["feed_ph_sensor"],
    )
    fake.set_state(kill, "off")
    assert "disabled" in c._blocked(room, 1)  # the room's own kill switch holds it, as before


async def test_a_service_call_naming_no_room_reaches_the_only_room(hass):
    await _install(hass)
    await hass.services.async_call(
        DOMAIN, "set_manual_override", {"zone": 1, "timeout_minutes": 5}, blocking=True
    )
    assert hass.states.get("switch.crop_steering_tent_zone_1_manual_override").state == "on"
