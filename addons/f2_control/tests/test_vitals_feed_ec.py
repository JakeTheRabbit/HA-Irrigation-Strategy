"""The vitals notification mentions feed EC only for a room with a feed EC probe. A room without one
used to say "feed EC —" every half hour about a probe it never had."""
from datetime import datetime

from test_controller import _build

HARDWARE = {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1"}}
PUBLISHED = {"default": {1: {"phase": "P2", "vwc": 85.0, "ec": 0.7}}}


def _vitals(options, states=None):
    c, fake = _build({"num_zones": 1, "hardware": HARDWARE, **options}, states=states)
    c._maybe_notify(PUBLISHED, datetime(2026, 9, 27, 13, 4))
    (message,) = [d["message"] for dom, svc, d in fake.calls if dom == "persistent_notification"]
    return message.splitlines()[1]  # the room's line, under the time


def test_a_room_without_a_feed_ec_probe_says_nothing_about_feed_ec():
    assert "feed EC" not in _vitals({})


def test_a_room_with_one_shows_its_reading():
    line = _vitals({"feed_ec_sensor": "sensor.feed_ec"}, {"sensor.feed_ec": ("1.8", {})})
    assert line.endswith("| feed EC 1.8")


def test_a_probe_that_reads_nothing_is_named_because_it_holds_watering():
    line = _vitals({"feed_ec_sensor": "sensor.feed_ec"}, {"sensor.feed_ec": ("unavailable", {})})
    assert line.endswith("| feed EC unreadable")
