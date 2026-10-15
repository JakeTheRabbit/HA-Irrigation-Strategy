"""What a room grows in reaches the controller through the room's descriptor (`substrate`, from the
integration's substrate select). It is read like the room's name: no adoption, no disarm cycle, and
"generic" whenever an older integration publishes none or a value this controller does not know."""
import json

import controller
from test_controller import _build, _desc

KILL = "input_boolean.kill"
DESCRIPTOR = "sensor.crop_steering_engine_config"


def _start(**descriptor):
    return _build(
        {"num_zones": 1, "enable_flag": KILL},
        states={
            DESCRIPTOR: ("ok", _desc(enable_flag=KILL, setup_revision=4, active=True,
                                     active_zone_ids=[1], **descriptor)),
            KILL: ("off", {}),
        },
    )


def test_a_descriptor_without_the_key_runs_the_room_as_generic():
    c, _fake = _start()
    room = c.rooms[0]
    assert room.substrate == "generic"
    assert room._setup_pending is None and room.setup_revision == 4


def test_the_rooms_choice_is_read_and_a_change_needs_no_disarm_cycle():
    c, fake = _start(substrate="coco")
    room = c.rooms[0]
    assert room.substrate == "coco"
    fake.set_state(KILL, "on")  # armed and growing
    attrs = fake.states[DESCRIPTOR][1]
    fake.set_state(DESCRIPTOR, "ok", {**attrs, "substrate": "rockwool"})
    c._apply_setup_descriptors()
    assert room.substrate == "rockwool"
    assert room._setup_pending is None and "Setup" not in (c._blocked(room, 1) or "")


def test_a_value_this_controller_does_not_know_reads_as_generic():
    for value in ("peat", "", None, 3, ["coco"]):
        assert controller.Controller._substrate({"substrate": value}) == "generic"
    assert controller.Controller._substrate(None) == "generic"
    assert [controller.Controller._substrate({"substrate": s}) for s in controller.SUBSTRATES] == list(
        controller.SUBSTRATES
    )


def test_the_substrate_does_not_touch_the_setup_fingerprint():
    """A substrate change must never bring a room back blocked behind a disarm cycle."""
    room = type("R", (), {"enable_flag": KILL})()
    attrs = _desc(enable_flag=KILL, setup_revision=4, active=True, active_zone_ids=[1])
    before = controller.Controller._setup_fingerprint(attrs, room)
    after = controller.Controller._setup_fingerprint({**attrs, "substrate": "coco"}, room)
    assert before == after and "substrate" not in json.loads(after)
