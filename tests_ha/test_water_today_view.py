"""How Water today reads is one choice per room, in Home Assistant: the dashboard shows it for everyone
and the controller's vitals notification follows it. Zone total until someone chooses Per plant."""

from datetime import datetime

from homeassistant.const import ATTR_OPTION
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

VIEW = "select.crop_steering_water_today_view"


async def _choose(hass, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": VIEW, ATTR_OPTION: option}, blocking=True
    )


async def test_a_new_room_shows_each_zones_total_until_someone_chooses(hass):
    entry = await _install(hass)
    view = hass.states.get(VIEW)
    assert view.state == "Zone total"
    assert view.attributes["options"] == ["Zone total", "Per plant"]
    await _choose(hass, "Per plant")
    assert hass.states.get(VIEW).state == "Per plant"
    # The choice is the room's: it survives the room being reloaded (a restart restores it the same way).
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(VIEW).state == "Per plant"


async def test_an_upgraded_room_gets_the_choice_at_zone_total(hass):
    await _upgrade(hass, "entry_2_17_wizard.json")
    assert hass.states.get(VIEW).state == "Zone total"


async def test_the_controllers_vitals_follow_the_rooms_choice(hass, controller_for):
    await _install(hass)
    await _choose(hass, "Per plant")
    c, fake, _clock = controller_for({})
    c.loop_once(datetime.now())  # the first pass sends the vitals
    (message,) = [
        d["message"]
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create") and d.get("notification_id") == "f2_vitals"
    ]
    assert "mL/plant day" in message and "L day" not in message.replace("mL/plant day", "")
