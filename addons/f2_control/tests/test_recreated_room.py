"""A room that is deleted in Home Assistant and set up again is a NEW room to the controller.

First real install, 2026-09-21. Setup went badly, so the integration was deleted and added again,
this time with two zones instead of one. The controller kept running throughout. A re-created
room's setup revision starts again at 1, the controller had adopted revision 2, and it skips any
revision that is not higher than the one it holds: so it went on driving the map of a room that
no longer existed, behind the same kill-switch id the new room uses. It took a controller restart
to notice. Had the valves differed, arming the new room would have watered through the old ones.

The integration now says which room it is (`entry_id` in the descriptor). When that changes, the
setup is adopted afresh through the usual gate: kill switch OFF, hardware OFF. An integration
that does not say (every version before this) is handled exactly as before.
"""
import json

import controller
from test_controller import _desc
from test_setup_resume import _setup_alerts, _start

KILL = "input_boolean.kill"
DESCRIPTOR = "sensor.crop_steering_engine_config"
OLD_MAP = {1: "switch.v1", 2: "switch.v2"}
NEW_MAP = {1: "switch.v9"}
EVERY_SWITCH = ("switch.p", "switch.m", "switch.v1", "switch.v2", "switch.v9")


def _states(*, entry_id, revision, valves, kill="off", on=()):
    attrs = _desc(
        enable_flag=KILL,
        setup_revision=revision,
        active=True,
        valves={str(zone): switch for zone, switch in valves.items()},
        num=len(valves),
        active_zone_ids=sorted(valves),
    )
    if entry_id is not None:
        attrs["entry_id"] = entry_id
    states = {DESCRIPTOR: ("ok", attrs), KILL: (kill, {})}
    states.update({s: ("on" if s in on else "off", {}) for s in EVERY_SWITCH})
    return states


def _now():
    return controller.datetime.now()


def _see(fake, states):
    for entity_id, (state, attributes) in states.items():
        fake.set_state(entity_id, state, attributes)


def _running_on_the_old_room(entry_id="entry-A"):
    c, fake = _start(_states(entry_id=entry_id, revision=2, valves=OLD_MAP))
    room = c.rooms[0]
    assert room.setup_revision == 2 and room.hw["valves"] == OLD_MAP
    return c, fake, room


# --------------------------------------------------------------------------- the running controller
def test_a_room_set_up_again_is_adopted_by_the_running_controller():
    c, fake, room = _running_on_the_old_room()
    _see(fake, _states(entry_id="entry-B", revision=1, valves=NEW_MAP))
    c._rediscover(_now())
    assert room.hw["valves"] == NEW_MAP  # was still {1: v1, 2: v2}: a room that no longer exists
    assert sorted(room.zones) == [1]
    assert room.setup_revision == 1 and room._setup_pending is None


def test_it_is_adopted_through_the_usual_gate_never_while_armed():
    c, fake, room = _running_on_the_old_room()
    _see(fake, _states(entry_id="entry-B", revision=1, valves=NEW_MAP, kill="on"))
    c._rediscover(_now())
    assert room._setup_pending and "Setup" in c._blocked(room, 1)  # every zone is held...
    assert room.hw["valves"] == OLD_MAP  # ...and the new map is not in force yet
    (alert,) = _setup_alerts(fake)
    assert KILL in alert["message"]  # it says what has to read OFF

    _see(fake, {KILL: ("off", {})})
    c._rediscover(_now())
    assert room.hw["valves"] == NEW_MAP and room._setup_pending is None


def test_nor_while_a_switch_of_either_map_is_on():
    c, fake, room = _running_on_the_old_room()
    _see(fake, _states(entry_id="entry-B", revision=1, valves=NEW_MAP, on=("switch.v2",)))
    c._rediscover(_now())
    assert room._setup_pending and room.hw["valves"] == OLD_MAP


def test_the_same_room_at_a_lower_revision_is_still_ignored():
    """Unchanged: only a different room re-opens adoption. A descriptor that goes backwards under
    the same entry is not something the integration produces, and is not acted on."""
    c, fake, room = _running_on_the_old_room()
    _see(fake, _states(entry_id="entry-A", revision=1, valves=NEW_MAP))
    c._rediscover(_now())
    assert room.hw["valves"] == OLD_MAP and room.setup_revision == 2
    assert room._setup_pending is None and _setup_alerts(fake) == []


# --------------------------------------------------------------------------- upgrade in place
def test_an_integration_that_does_not_say_which_room_it_is_behaves_exactly_as_before():
    c, fake, room = _running_on_the_old_room(entry_id=None)
    _see(fake, _states(entry_id=None, revision=1, valves=NEW_MAP))  # lower: ignored, as today
    c._rediscover(_now())
    assert room.hw["valves"] == OLD_MAP and room.setup_revision == 2
    _see(fake, _states(entry_id=None, revision=3, valves=NEW_MAP))  # higher: adopted, as today
    c._rediscover(_now())
    assert room.hw["valves"] == NEW_MAP and room.setup_revision == 3


def test_updating_the_integration_under_a_growing_room_changes_nothing():
    """The descriptor starts carrying `entry_id` while the controller runs, kill switch ON. First
    sight is remembered and nothing else happens: no re-adoption, no hold, no alert."""
    c, fake, room = _running_on_the_old_room(entry_id=None)
    _see(fake, _states(entry_id="entry-A", revision=2, valves=OLD_MAP, kill="on"))
    c._rediscover(_now())
    assert room.setup_revision == 2 and room._setup_pending is None
    assert _setup_alerts(fake) == []
    assert "Setup" not in (c._blocked(room, 1) or "")
    saved = json.load(open(c._state_path))["default"]["_setup"]
    assert saved["entry_id"] == "entry-A" and saved["revision"] == 2  # and it is written down


def test_a_restart_on_a_state_file_from_before_this_resumes_without_a_disarm_cycle():
    """The 2026-09-20 outage, again, if this were wrong: controller 0.16.2 saved no `entry_id`.
    After the update the room is armed and growing, and must carry straight on."""
    first, _ = _start(_states(entry_id=None, revision=4, valves=OLD_MAP))
    saved = json.load(open(first._state_path))
    assert "entry_id" not in saved["default"]["_setup"]  # what 0.16.2 wrote

    c, fake = _start(
        _states(entry_id="entry-A", revision=4, valves=OLD_MAP, kill="on"),
        state_path=first._state_path,
    )
    room = c.rooms[0]
    assert room.setup_revision == 4 and room._setup_pending is None
    assert _setup_alerts(fake) == []


def test_a_restart_does_not_resume_a_different_room_even_if_it_looks_identical():
    """Same revision, same map, same fingerprint: but it is another room, born with its kill
    switch OFF. Finding that switch ON is not a setup to resume, it is one to gate."""
    first, _ = _start(_states(entry_id="entry-A", revision=1, valves=OLD_MAP))
    c, fake = _start(
        _states(entry_id="entry-B", revision=1, valves=OLD_MAP, kill="on"),
        state_path=first._state_path,
    )
    room = c.rooms[0]
    assert room._setup_pending and room.setup_revision == 0

    _see(fake, {KILL: ("off", {})})
    c._rediscover(_now())
    assert room.setup_revision == 1 and room._setup_pending is None
    assert json.load(open(c._state_path))["default"]["_setup"]["entry_id"] == "entry-B"


# --------------------------------------------------------------------------- it changes nothing else
def test_which_room_it_is_never_enters_the_setup_fingerprint():
    """If it did, every room would come back from this update behind a disarm cycle."""
    room = type("R", (), {"enable_flag": KILL})()
    attrs = _desc(enable_flag=KILL, setup_revision=4, active=True, active_zone_ids=[1])
    plain = controller.Controller._setup_fingerprint(attrs, room)
    assert controller.Controller._setup_fingerprint({**attrs, "entry_id": "entry-A"}, room) == plain
    assert controller.Controller._setup_fingerprint({**attrs, "entry_id": "entry-B"}, room) == plain


def test_a_descriptor_whose_entry_id_is_junk_is_treated_as_not_saying():
    c, fake, room = _running_on_the_old_room()
    for junk in (7, "", None, ["entry-B"], True):
        states = _states(entry_id="x", revision=1, valves=NEW_MAP)
        states[DESCRIPTOR][1]["entry_id"] = junk
        _see(fake, states)
        c._rediscover(_now())
        assert room.hw["valves"] == OLD_MAP and room.setup_revision == 2, junk
