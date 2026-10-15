"""F-605: a room whose setting ids moved (CS-605) keeps watering after a controller-only update.

The controller finds a setting by its exact entity id. Where an id has moved it cannot read that
setting, and an update must not stop the room for it: after a three-pass wait the room waters on
the built-in value and CS-402 names the setting. Only a zone whose water-sizing setting (here zone
2's daily limit) has never been read holds, and says why; the other zone carries on.
"""

from datetime import datetime

from conftest import fixture
from test_upgrade_in_place import _upgrade

KILL = "switch.crop_steering_engine_enabled"
WAITING = "waiting for its settings to load"


def _cards(fake):
    return [
        data["message"]
        for domain, service, data in fake.calls
        if (domain, service) == ("persistent_notification", "create") and "CS-402" in data["title"]
    ]


async def test_a_room_whose_ids_moved_keeps_watering_and_holds_only_the_zone_it_cannot_size(
    hass, controller_for
):
    moved = fixture("entities_moved_2_25_1.json")
    seed = fixture(moved["from"])
    registry = {moved["moved"].get(e, e): key for e, key in seed["registry"].items()}
    await _upgrade(hass, moved["from"], registry_ids=registry)
    for old, new in moved["moved"].items():
        assert hass.states.get(old) is None and hass.states.get(new) is not None, old
    hass.states.async_set(KILL, "on")  # armed and growing

    c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room._setup_pending is None, room._setup_pending
    for switch in (
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
        "switch.crop_steering_zone_2_enabled",
    ):
        fake.set_state(switch, "on")

    c.loop_once(datetime.now())
    for zone in (1, 2):  # just started: the moved settings may still be loading
        assert WAITING in c._blocked(room, zone), zone
    c.loop_once(datetime.now())
    c.loop_once(datetime.now())

    assert c._blocked(room, 1) is None  # zone 1 waters, on the built-in re-water threshold
    held = c._blocked(room, 2)
    assert "number.crop_steering_max_daily_volume not read since the controller started" in held
    assert "CS-402" in held
    card = _cards(fake)[-1]
    assert "number.crop_steering_p2_vwc_threshold" in card
    assert "number.crop_steering_max_daily_volume" in card and "gets no shots" in card
