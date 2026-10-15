"""A zone's primary probe, in a real Home Assistant: the Probes page picks which of a zone's probes
count and one primary through `crop_steering.setup_save`, sending only that choice, which needs
nothing switched off. When the primary goes offline the zone reads on from its other probes and the
controller says so once. A room that never chose has no primary and reads as before.
"""

from datetime import datetime

from homeassistant.core import Context

from conftest import fixture
from test_probe_fusion import A, B, C, _install, _read
from test_real_flow import VALVE
from test_upgrade_in_place import JEV_3_11_1, _upgrade

ENGINE = "switch.crop_steering_tent_engine_enabled"  # a new room has a slug: the wizard's "Tent"
NOW = datetime(2026, 9, 21, 14, 0, 0)
KEY = "f2_probe_primary_tent_z1_vwc"
OLD_ZONE = "sensor.crop_steering_vwc_zone_1"  # an upgraded room keeps its un-prefixed ids


async def _service(hass, admin, name, data=None):
    return await hass.services.async_call(
        "crop_steering",
        name,
        data or {},
        blocking=True,
        return_response=True,
        context=Context(user_id=admin.id),
    )


async def _choose(hass, admin, **zone1):
    """What the Probes page sends: each zone's id, whether it is active, and its probe choice."""
    (room,) = (await _service(hass, admin, "setup_read"))["rooms"]
    zones = [{"id": z["id"], "active": z["active"]} for z in room["zones"]]
    zones[0].update(zone1)
    await _service(
        hass,
        admin,
        "setup_save",
        {
            "entry_id": room["entry_id"],
            "expected_revision": room["revision"],
            "zones": zones,
        },
    )
    await hass.async_block_till_done()


def _raised(fake):
    return [
        data
        for domain, service, data in fake.calls
        if (domain, service) == ("persistent_notification", "create")
        and data["notification_id"] == KEY
    ]


async def test_a_3_11_1_room_has_no_primary_and_reads_as_before(hass, hass_admin_user):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    (room,) = (await _service(hass, hass_admin_user, "setup_read"))["rooms"]
    for zone in room["zones"]:
        assert (zone["vwc_primary"], zone["vwc_unused"]) == ("", [])
        assert (zone["ec_primary"], zone["ec_unused"]) == ("", [])
    vwc = hass.states.get(OLD_ZONE)
    assert float(vwc.state) == 52.0  # zone 1's two probes, 50 and 54, as 3.11.1 read them
    assert vwc.attributes["primary"] is None
    assert vwc.attributes["used"] == ["sensor.zone_1_vwc_a", "sensor.zone_1_vwc_b"]


async def test_pulling_the_primary_raises_one_alert_and_watering_carries_on(
    hass, hass_admin_user, freezer, controller_for
):
    await _install(hass, [A, B, C])
    await _read(hass, freezer, **{A: "40", B: "42", C: "44"})
    # Watering is on and a valve open: a probe choice alone is still saved.
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": ENGINE}, blocking=True
    )
    hass.states.async_set(VALVE, "on")
    await _choose(hass, hass_admin_user, vwc_primary=B, vwc_unused=[C])
    state = await _read(hass, freezer, **{A: "40", B: "42", C: "44"})
    assert float(state.state) == 41.0  # A and B; C does not count
    assert state.attributes["primary"] == B
    assert state.attributes["excluded"] == {C: "not counted"}

    hass.states.async_set(B, "unavailable")  # the primary is pulled
    state = await _read(hass, freezer, **{A: "40"})
    assert float(state.state) == 41.0  # A, with what it learned of B
    assert state.attributes["excluded"] == {B: "no reading", C: "not counted"}

    c, fake, _clock = controller_for({"enable_flag": ENGINE})
    assert c._read_sensor(c._fused_id("tent_", "vwc", 1), "vwc") == 41.0
    c.loop_once(NOW)
    c.loop_once(NOW.replace(minute=45))
    (alert,) = _raised(fake)
    assert alert["title"].endswith("the primary moisture probe is offline (CS-505)")
    assert B in alert["message"]
