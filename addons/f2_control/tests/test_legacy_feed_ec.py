"""The upgrade to 3.18 keeps controller 3.17.0's feed EC for a room that has no feed EC probe and no recipe feed
EC (migration spec M15): the integration publishes `legacy_feed_ec_fallback: 3.0` on the room's descriptor, and
the controller hands decide() that 3.0 where it would now hand None, so the room's EC flushes and its holds for
a high EC work as they did before the update. A mapped probe or a declared recipe EC always wins, the descriptor
without the key is a room as it is today (no feed EC), and CS-907 still tells the grower, in words that say what
is assumed.
"""
import controller
from test_plan_hold_never_stops_rescues import Clock, probe, rig  # noqa: F401 (rig: a pytest fixture)

DOSING = "sensor.crop_steering_dosing_config"
FEED_EC = "sensor.feed_ec"


def _feed_ec(c, room):
    snap, _params = c._snapshot(room, 1, Clock.now(), True, False)
    return snap.feed_ec


def _cards(fake, key="f2_feed_unknown_default"):
    return [(svc, d) for dom, svc, d in fake.calls
            if dom == "persistent_notification" and d.get("notification_id") == key]


def test_the_descriptor_value_is_read_only_when_it_is_a_plain_feed_ec():
    read = controller.Controller._legacy_feed_ec
    assert read({"legacy_feed_ec_fallback": 3.0}) == 3.0
    assert read({"legacy_feed_ec_fallback": 3}) == 3.0
    for bad in (None, True, "3.0", 0, 25.0, float("nan"), float("inf")):
        assert read({"legacy_feed_ec_fallback": bad}) is None, bad
    assert read({}) is None and read(None) is None


def test_a_probe_less_room_the_upgrade_kept_hands_decide_the_old_3_0(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    assert _feed_ec(c, room) is None  # today's room without the key: an unknown feed
    room.legacy_feed_ec = 3.0
    assert _feed_ec(c, room) == 3.0  # what 3.17.0 handed decide()


def test_a_declared_recipe_ec_or_a_mapped_probe_wins_over_the_kept_value(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    room.legacy_feed_ec = 3.0
    fake.set_state(DOSING, "3", {"pumps": [], "batch": {}, "feed": {"recipe": "Bloom", "ec": 2.4}})
    assert _feed_ec(c, room) == 2.4
    fake.set_state(DOSING, "4", {"pumps": [], "batch": {}, "feed": {"recipe": "Bloom", "ec": None}})
    room.feed_ec_sensor = FEED_EC  # a probe that does not read: unknown, never the kept value
    assert _feed_ec(c, room) is None


def test_the_descriptor_puts_it_on_the_room_with_no_disarm_cycle(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state("sensor.crop_steering_engine_config", "default",
                   {"prefix": "", "slug": "default", "legacy_feed_ec_fallback": 3.0})
    c._apply_setup_descriptors()
    assert room.legacy_feed_ec == 3.0 and getattr(room, "_setup_pending", None) is None
    fake.set_state("sensor.crop_steering_engine_config", "default", {"prefix": "", "slug": "default"})
    c._apply_setup_descriptors()
    assert room.legacy_feed_ec is None  # a probe mapped since: the integration stops publishing it


def test_cs_907_still_tells_the_grower_and_says_what_is_assumed(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    probe(fake, 2, 50)
    room.legacy_feed_ec = 3.0
    c._loop_room(room, Clock.now())
    c._loop_room(room, Clock.now())
    cards = _cards(fake)
    assert [svc for svc, _d in cards] == ["create"]
    assert "CS-907" in cards[0][1]["title"] and "3.0 mS/cm" in cards[0][1]["title"]
    assert "assumes a feed EC of 3 mS/cm" in cards[0][1]["message"]
    assert "Set a recipe feed EC or map a feed EC probe" in cards[0][1]["message"]
