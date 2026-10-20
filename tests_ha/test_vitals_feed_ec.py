"""The vitals notification, from the real controller looking at a real install: feed EC only for a room
whose feed EC probe is mapped. The wizard's room maps none, so its line says nothing about it."""

from datetime import datetime

from test_setup_entry import _install


async def test_a_room_with_no_feed_ec_probe_says_nothing_about_feed_ec(hass, controller_for):
    await _install(hass)
    c, fake, _clock = controller_for({})
    assert not c.rooms[0].feed_ec_sensor
    c.loop_once(datetime.now())  # the first pass sends the vitals
    (message,) = [
        d["message"]
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create") and d.get("notification_id") == "f2_vitals"
    ]
    assert "LIVE" in message or "HELD" in message
    assert "feed EC" not in message
