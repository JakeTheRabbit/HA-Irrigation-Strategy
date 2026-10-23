"""The feed EC watering compares pore EC with: a measured feed EC probe first, then the declared EC of the
feed recipe in use today (the integration's dosing_config, `feed.ec`), else unknown (None).

Declared values can't catch a mis-mixed tank, so a mapped probe always wins and the source-water gate
runs on it alone. A room with neither (every room before feed recipes declared an EC) has no feed EC: the engine
then takes no EC flush and no CS-206 hold on a feed it never measured (CTL-008; it used to invent 3.0).
"""
import controller
from test_plan_hold_never_stops_rescues import Clock, probe, rig  # noqa: F401 (rig: a pytest fixture)

DOSING = "sensor.crop_steering_dosing_config"
FEED_EC = "sensor.feed_ec"


def _feed_ec(c, room):
    snap, _params = c._snapshot(room, 1, Clock.now(), True, False)
    return snap.feed_ec


def _recipe(fake, ec, name="Bloom"):
    fake.set_state(DOSING, "3", {"pumps": [], "batch": {}, "feed": {"recipe": name, "ec": ec}})


def test_no_probe_and_no_declared_ec_is_an_unknown_feed(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    assert _feed_ec(c, room) is None  # no dosing setup at all
    _recipe(fake, None)
    assert _feed_ec(c, room) is None  # a recipe that declares none
    fake.set_state(DOSING, "unknown", {"error": "the stored setup cannot be read"})
    assert _feed_ec(c, room) is None


def test_the_recipe_in_use_declares_the_feed_ec_without_a_probe(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    _recipe(fake, 2.4)
    assert _feed_ec(c, room) == 2.4
    for bad in ("strong", 0, 25.0, float("nan")):  # never a value a valid save could hold
        _recipe(fake, bad)
        assert _feed_ec(c, room) is None


def test_a_measured_feed_ec_always_wins_and_the_gate_runs_on_it(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    room.feed_ec_sensor = FEED_EC
    _recipe(fake, 2.4)
    fake.set_state(FEED_EC, "3.6", {"unit_of_measurement": "mS/cm"},
                   last_updated=Clock.now(controller.timezone.utc).isoformat())
    assert _feed_ec(c, room) == 3.6  # a mis-mixed tank shows on the probe, never on the recipe
    assert c._read_feed_ec(room) == 3.6  # what the source-water gate reads: the probe alone


def _cards(fake, key="f2_feed_unknown_default"):
    return [(svc, d) for dom, svc, d in fake.calls if dom == "persistent_notification" and d.get("notification_id") == key]


def test_a_room_with_no_feed_ec_is_told_once_that_ec_flushing_is_off(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    probe(fake, 2, 50)
    c._loop_room(room, Clock.now())
    c._loop_room(room, Clock.now())
    cards = _cards(fake)
    assert [svc for svc, _d in cards] == ["create"]  # once, not every pass
    assert "CS-907" in cards[0][1]["title"]
    assert "set a recipe feed EC or map a feed EC probe" in cards[0][1]["message"]


def test_the_card_goes_when_a_recipe_ec_or_a_feed_probe_appears(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    probe(fake, 2, 50)
    c._loop_room(room, Clock.now())
    _recipe(fake, 2.4)
    c._loop_room(room, Clock.now())
    assert [svc for svc, _d in _cards(fake)] == ["create", "dismiss"]
    _recipe(fake, None)
    c._loop_room(room, Clock.now())
    room.feed_ec_sensor = FEED_EC
    c._loop_room(room, Clock.now())
    assert [svc for svc, _d in _cards(fake)] == ["create", "dismiss", "create", "dismiss"]
