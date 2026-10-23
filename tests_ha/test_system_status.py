"""System status in a real Home Assistant: sensor.crop_steering_system_health and system_status_get, through
Home Assistant's own services, clock, state machine and Lovelace resources. No recorder here (its
behaviour without one: uptime is None);
test_system_status_recorder.py has the recorder."""

from datetime import timedelta

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import Context, SupportsResponse
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_setup_entry import _install
from test_timeline import _veg_room
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
HEALTH = "sensor.crop_steering_system_health"
BEAT = "sensor.crop_steering_tent_ai_heartbeat"
TENT = ["sensor.gt1_vwc", "sensor.gt1_ec", "switch.gt1_irrigation_switch"]


async def _status(hass, **data):
    return await hass.services.async_call(
        DOMAIN,
        "system_status_get",
        data,
        blocking=True,
        return_response=True,
        context=Context(),
    )


async def _tick(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _tracker(hass):
    return hass.data[DOMAIN].get("_system_status")


async def test_a_fresh_room_is_all_online_and_answers_its_status(hass):
    await _install(hass)
    assert hass.services.supports_response(DOMAIN, "system_status_get") is SupportsResponse.ONLY
    state = hass.states.get(HEALTH)
    assert state.state == "100.0"
    assert state.attributes["pct_online"] == 100.0 and state.attributes["silent"] == []
    assert state.attributes["controller"] == "absent"
    assert state.attributes["addon_version"] is None

    out = await _status(hass)
    assert out["controller"] == "absent" and out["pct_online"] == 100.0
    assert out["ha_version"] == HA_VERSION
    assert out["ai"] is None and out["card_version"] is None
    (room,) = out["rooms"]
    assert room["room_id"] == "room:tent_" and room["alerts_open"] == 0
    assert [g["kind"] for g in room["groups"]] == ["probe_vwc", "probe_ec", "valve"]
    assert [e["entity_id"] for e in room["entities"]] == TENT
    assert all(e["ok"] and e["zone"] == 1 and e["uptime_7d_pct"] is None for e in room["entities"])
    assert room["heartbeat"]["controller"] == "absent" and room["heartbeat"]["beats"] == []

    v2 = await _status(hass, api=2)
    assert v2["ok"] is True and v2["data"]["rooms"][0]["room_id"] == "room:tent_"


async def test_heartbeats_fill_the_ring_and_a_stale_one_reaches_the_sensor(hass, freezer):
    await _install(hass)
    hass.states.async_set(BEAT, "ok", {"controller_version": "4.2.0", "n": 1})
    await _tick(hass, freezer, 60)
    hass.states.async_set(BEAT, "ok", {"controller_version": "4.2.0", "n": 2, "readback_ms": 35})
    await _tick(hass, freezer, 240)  # a gap of 4 min: one missed beat
    hass.states.async_set(BEAT, "ok", {"controller_version": "4.2.0", "n": 3})
    await hass.async_block_till_done()

    out = await _status(hass)
    beat = out["rooms"][0]["heartbeat"]
    assert [b["missed"] for b in beat["beats"]] == [False, False, True, False]
    assert [b["readback_ms"] for b in beat["beats"]] == [None, 35, None, None]
    assert beat["controller"] == "running" and out["addon_version"] == "4.2.0"

    # A probe left unreported past the 900 s fallback (no interval known) is silent, and no beat for
    # 11 min leaves the controller stale, both on the owner's 5-min tick.
    for _ in range(3):
        await _tick(hass, freezer, 300)
    state = hass.states.get(HEALTH)
    assert state.attributes["controller"] == "stale"
    assert state.attributes["silent"] == ["sensor.gt1_ec", "sensor.gt1_vwc"]
    assert state.state == str(1 / 3 * 100)  # 1 of 3 online, unrounded


async def test_the_card_version_is_read_from_the_lovelace_resources(hass):
    await _install(hass)
    assert await async_setup_component(hass, "lovelace", {})
    assert (await _status(hass))["card_version"] is None
    from custom_components.crop_steering.dashboards import lovelace_part

    resources = lovelace_part(hass, "resources")
    await resources.async_create_item(
        {"res_type": "module", "url": "/crop_steering/crop-steering-card.js?v=3171"}
    )
    assert (await _status(hass))["card_version"] == "3171"


async def test_a_steady_probe_is_never_silent_and_one_that_stops_is(hass, freezer):
    """A probe repeating its value is reported, not changed: its report times still count."""
    await _install(hass)
    first = hass.states.get("sensor.gt1_vwc").last_changed
    for _ in range(8):  # 40 min of the same value every 5 min
        await _tick(hass, freezer, 300)  # the owner's tick publishes first: 300 s since the report
        assert hass.states.get(HEALTH).attributes["silent"] == []
        hass.states.async_set("sensor.gt1_vwc", "41", {"unit_of_measurement": "%"})
        hass.states.async_set("sensor.gt1_ec", "3100", {"unit_of_measurement": "µS/cm"})
        await hass.async_block_till_done()
    assert hass.states.get("sensor.gt1_vwc").last_changed == first  # never a state change
    assert _tracker(hass).median("sensor.gt1_vwc") == 300.0

    # It stops: still online at 10 min, silent past 3 x 5 min.
    await _tick(hass, freezer, 300)
    await _tick(hass, freezer, 300)
    assert hass.states.get(HEALTH).attributes["silent"] == []
    await _tick(hass, freezer, 301)
    assert hass.states.get(HEALTH).attributes["silent"] == ["sensor.gt1_ec", "sensor.gt1_vwc"]


async def test_the_first_room_owns_the_sensor_until_it_unloads(hass, freezer):
    listening = dict(hass.bus.async_listeners())
    tent = await _install(hass)
    await _veg_room(hass)
    veg = next(
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != tent.entry_id
    )
    tracker = _tracker(hass)
    assert tracker.owner == tent.entry_id
    rooms = [r["room_id"] for r in (await _status(hass))["rooms"]]
    assert rooms == ["room:tent_", "room:veg_"]
    hass.states.async_set("sensor.veg_vwc", "unavailable")
    await _tick(hass, freezer, 300)  # the owner's tick publishes
    assert "sensor.veg_vwc" in hass.states.get(HEALTH).attributes["silent"]

    assert await hass.config_entries.async_unload(tent.entry_id)
    await hass.async_block_till_done()
    assert tracker.owner == veg.entry_id
    assert [r["room_id"] for r in (await _status(hass))["rooms"]] == ["room:veg_"]
    assert hass.states.get(HEALTH).attributes["silent"] == ["sensor.veg_vwc"]  # tent's are gone
    await _tick(hass, freezer, 290)
    hass.states.async_set("sensor.veg_vwc", "40")
    await _tick(hass, freezer, 10)  # now veg's tick publishes
    state = hass.states.get(HEALTH)
    assert state.attributes["silent"] == [] and state.state == "100.0"

    assert await hass.config_entries.async_unload(veg.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(HEALTH) is None
    assert _tracker(hass) is None
    assert not hass.services.has_service(DOMAIN, "system_status_get")
    # The probe and heartbeat listeners went with it.
    for event in ("state_changed", "state_reported"):
        assert hass.bus.async_listeners().get(event, 0) <= listening.get(event, 0), event
    hass.states.async_set(BEAT, "ok", {"n": 9})  # no listener left
    await _tick(hass, freezer, 300)
    assert hass.states.get(HEALTH) is None


async def test_an_old_install_loads_its_status_without_errors(hass, caplog):
    entry, _ = await _upgrade(hass, "entry_3_11_1_pumped_room.json")
    await hass.async_block_till_done()
    from custom_components.crop_steering.room import room_prefix

    assert hass.states.get(HEALTH) is not None
    out = await _status(hass)
    (room,) = out["rooms"]
    assert room["room_id"] == "room:" + room_prefix(entry) and room["entities"]
    assert not [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]
