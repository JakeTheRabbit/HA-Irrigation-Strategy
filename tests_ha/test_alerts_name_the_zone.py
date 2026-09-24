"""The name typed into the real wizard reaches the real controller's notifications.

First real install: zones named GT1 and GT4, and the phone said "default Z2 probe dead". See
addons/f2_control/tests/test_alerts_name_the_zone.py for the controller's own tests; this is the
two halves together: the descriptor a real Home Assistant publishes, read by the real controller.
"""

from datetime import datetime

from test_configure import _save_map
from test_real_flow import ZONES
from test_recreated_room_controller import _see
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

KILL = "switch.crop_steering_engine_enabled"
NOW = datetime(2026, 9, 21, 14, 0, 0)


def _texts(fake):
    return [
        f"{data['title']} | {data['message']}"
        for domain, service, data in fake.calls
        if (domain, service) == ("persistent_notification", "create")
    ]


async def test_fresh_install_a_zone_named_in_the_wizard_is_named_in_its_alert(
    hass, controller_for, monkeypatch
):
    monkeypatch.setitem(ZONES, "zone_1_name", "GT1")
    entry = await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    assert c.rooms[0].zone_names == {1: "GT1"}
    c.loop_once(NOW)  # a bare install: never watered, so the watchdog speaks
    # The wizard's first question named the room "Tent": that, not the internal "default".
    assert any(text.startswith("Tent · GT1 (Z1): ") for text in _texts(fake)), _texts(fake)
    assert not any("default" in text.split(" | ")[0] for text in _texts(fake)), _texts(fake)

    # Renamed in Configure: the running controller follows, with no restart and no disarm cycle.
    await _save_map(hass, entry, zone_1_name="Bench A")
    await hass.async_block_till_done()
    _see(hass, fake)
    c._rediscover(NOW)
    assert c.rooms[0].zone_names == {1: "Bench A"}


async def test_upgrade_in_place_old_installs_get_their_names_or_the_number(
    hass, controller_for
):
    for name, room in (
        ("entry_2_17_wizard.json", "Flower room"),
        ("entry_2_18_one_switch_tent.json", "Tent"),
        ("entry_env_era.json", ""),  # no room_name stored: no room shown, never "default"
    ):
        _entry, seed = await _upgrade(hass, name)
        c, _fake, _clock = controller_for({"enable_flag": KILL})
        expected = {
            int(number): zone["name"]
            for number, zone in seed["data"]["zones"].items()
            if zone.get("name") and zone["name"] != f"Zone {number}"
        }
        assert c.rooms[0].zone_names == expected, name
        assert c.rooms[0].room_name == room, name
        for entry in hass.config_entries.async_entries("crop_steering"):
            assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
