"""Two controllers on one room hold it, irrigation and dosing (the duplicate-controller guard, CS-609).

A container started while the app still runs, or a second app, would open the same valves and take the
same dosing request. Each controller now writes its own id (`controller_instance`, kept in `instance_id`
beside state.json) in the room's heartbeat and reads the heartbeat before each pass: a write by another
controller, or by one from before the guard (no id), holds the room for 3 minutes of this controller's
monotonic clock after the last pass that saw one. Freshness is Home Assistant's `last_updated`, never the
naive `last_beat`, so the two controllers' time zones and clocks do not matter.
"""

from datetime import timedelta, timezone

import pytest

import controller
import fake_ha
from test_dosing_runner import make_rig
from test_plan_hold_never_stops_rescues import Clock, opened, probe, rig  # noqa: F401 (rig: a fixture)

BEAT = "sensor.crop_steering_ai_heartbeat"
REFUSED = "refused: another controller is driving this room"


def foreign(fake, instance="the-other-controller", *, age_s=0.0, last_beat=None):
    """Another controller's beat, stamped by Home Assistant `age_s` ago (negative: ahead of this clock)."""
    attributes = {"engine": "f2-control", "last_beat": last_beat or Clock.now().isoformat()}
    if instance is not None:
        attributes["controller_instance"] = instance
    stamp = (Clock.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    fake.set_state(BEAT, "healthy", attributes, last_updated=stamp)


def first_read(c, room):
    """The guard's first read, as at start."""
    c._guard.clear()
    c._guard_read(room)


def due(fake, room):
    """Zone 1 dry in P2 for four hours: the watchdog shot is due this pass."""
    probe(fake, 1, 40)
    probe(fake, 2, 60)
    now = Clock.now()
    room.state[1].update(phase="P2", last_shot=now - timedelta(hours=4))
    room.state[2].update(phase="P2", last_shot=now - timedelta(hours=1))
    return now


def alerted(fake):
    return [d["notification_id"] for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]


@pytest.mark.parametrize("instance", ["the-other-controller", None], ids=["another id (a)", "no id (b)"])
def test_a_fresh_beat_from_another_controller_holds_the_room(rig, instance):  # noqa: F811
    c, fake, room = rig
    now = due(fake, room)
    foreign(fake, instance)
    first_read(c, room)
    assert c.duplicate_hold(room)
    pub = c._loop_room(room, now)
    assert pub == {} and opened(fake) == []
    assert "f2_duplicate_default" in alerted(fake)
    # Its own beat is written, with its id, so the other controller holds too.
    assert fake.sets[BEAT][1]["controller_instance"] == c.instance_id


def test_a_stale_beat_at_start_does_not_hold(rig):  # noqa: F811
    """(c) Another controller's beat Home Assistant stamped over 3 minutes ago: it has stopped."""
    c, fake, room = rig
    now = due(fake, room)
    foreign(fake, age_s=181)
    first_read(c, room)
    assert not c.duplicate_hold(room)
    c._loop_room(room, now)
    assert "switch.v1" in opened(fake) and "f2_duplicate_default" not in alerted(fake)


def test_the_hold_lasts_3_minutes_after_the_last_foreign_write_and_holds_every_write(rig):  # noqa: F811
    """(d) Our own beat overwrites the other's, and the room still holds until 3 min of this
    controller's monotonic clock after the last pass that saw another write; then it waters, by itself.
    Over the hold nothing the room's logic writes is sent: no phase change, no setpoint, no shot."""
    c, fake, room = rig
    now = due(fake, room)
    room.state[2]["phase"] = "P3"  # lights on: the zone would move to P0 on any pass that ran
    foreign(fake)
    for minute in range(4):
        c.loop_once(now)
        if minute == 0:
            assert fake.states[BEAT][1]["controller_instance"] == c.instance_id  # ours overwrote it
            foreign(fake, age_s=-1)  # the other writes again in the first minute
        controller.time.sleep(60)
    assert opened(fake) == [] and room.state[2]["phase"] == "P3"
    assert not [call for call in fake.calls if call[1] == "set_value"]
    c.loop_once(now)  # minute 4: 3 min past the pass that saw the second write (minute 1)
    assert "switch.v1" in opened(fake)
    assert "f2_duplicate_default" in [d["notification_id"] for dom, svc, d in fake.calls
                                      if (dom, svc) == ("persistent_notification", "dismiss")]


def test_an_update_from_a_version_before_the_guard_holds_3_minutes_then_waters(rig):  # noqa: F811
    """(e) The first start after an in-place update reads its own previous version's fresh beat, which
    has no id: it holds, and carries on by itself 3 minutes later."""
    c, fake, room = rig
    now = due(fake, room)
    foreign(fake, None, age_s=30)
    first_read(c, room)
    c.loop_once(now)
    assert opened(fake) == []
    controller.time.sleep(179)
    c.loop_once(now)
    assert opened(fake) == []
    controller.time.sleep(2)
    c.loop_once(now)
    assert "switch.v1" in opened(fake)


@pytest.mark.parametrize("hours", [13, -12])
def test_the_other_controllers_time_zone_never_stretches_or_skips_the_hold(rig, hours):  # noqa: F811
    """(f) last_beat is a naive local time: 13 h ahead or 12 h behind this zone, the hold follows
    Home Assistant's last_updated all the same, and ends 3 min after the other's writes stop."""
    c, fake, room = rig
    now = due(fake, room)
    foreign(fake, last_beat=(Clock.now() + timedelta(hours=hours)).isoformat())
    first_read(c, room)
    assert c.duplicate_hold(room)
    controller.time.sleep(181)
    assert not c.duplicate_hold(room)
    c._loop_room(room, now)
    assert "switch.v1" in opened(fake)


def test_a_stale_beat_whose_last_beat_looks_like_now_in_another_zone_does_not_hold(rig):  # noqa: F811
    c, fake, room = rig
    foreign(fake, age_s=3600, last_beat=Clock.now().isoformat())
    first_read(c, room)
    assert not c.duplicate_hold(room)


def test_a_beat_stamped_in_this_clocks_future_counts_as_fresh(rig):  # noqa: F811
    """(g) Skew: Home Assistant's clock 2 min ahead of this one. Fresh at start, and the hold still
    ends 3 min after the last foreign write."""
    c, fake, room = rig
    foreign(fake, age_s=-120)
    first_read(c, room)
    assert c.duplicate_hold(room)
    controller.time.sleep(181)
    assert not c.duplicate_hold(room)


def test_a_host_clock_ahead_of_home_assistant_is_judged_by_home_assistants_clock(rig, monkeypatch):  # noqa: F811
    """This machine's clock 10 min ahead of Home Assistant's: a beat Home Assistant stamped a minute
    ago by its own clock (its Date header) is fresh, so a running older app is seen at once."""
    c, fake, room = rig
    foreign(fake, age_s=600 + 60)
    served = Clock.now(timezone.utc) - timedelta(seconds=600)

    def status(entity, timeout=8):
        code, read = fake.ha_get_status(entity)
        read.served_at = served
        return code, read

    monkeypatch.setattr(controller, "ha_get_status", status)
    first_read(c, room)
    assert c.duplicate_hold(room)


def test_no_heartbeat_at_all_never_holds(rig):  # noqa: F811
    """(h) Home Assistant restarted: a state set over REST is not restored, so there is no heartbeat
    until a controller writes one. That is nobody's: the first due shot goes on the first pass."""
    c, fake, room = rig
    now = due(fake, room)
    fake.states.pop(BEAT, None)
    first_read(c, room)
    assert not c.duplicate_hold(room)
    c.loop_once(now)
    assert "switch.v1" in opened(fake)


def test_until_its_heartbeat_has_been_read_a_room_holds(rig, monkeypatch):  # noqa: F811
    """A room found later, or one whose first read Home Assistant did not answer, holds until a read is."""
    c, fake, room = rig
    monkeypatch.setattr(controller, "ha_get_status", lambda entity, timeout=8: (None, controller.HAState()))
    first_read(c, room)
    assert c.duplicate_hold(room)
    monkeypatch.setattr(controller, "ha_get_status", fake.ha_get_status)
    c._guard_read(room)
    assert not c.duplicate_hold(room)


def test_our_own_beat_from_before_a_restart_never_holds(rig):  # noqa: F811
    """A restart of the same install reads its own id back from instance_id, and its own beat."""
    c, fake, room = rig
    foreign(fake, c.instance_id)
    first_read(c, room)
    assert not c.duplicate_hold(room)


# ------------------------------------------------------------------ (i) dosing holds too
@pytest.fixture
def dosing(tmp_path, monkeypatch):
    r = make_rig(tmp_path, monkeypatch)()
    monkeypatch.setattr(controller.time, "monotonic", r.clock.monotonic)
    r.config()
    return r


def hold(r):
    room = r.c.rooms[0]
    r.fake.set_state(BEAT, "healthy", {"controller_instance": "the-other-controller"})
    r.c._guard_read(room)
    assert r.c.duplicate_hold(room)
    return room


@pytest.mark.parametrize("action", ["dose", "batch"])
def test_a_dose_or_batch_asked_for_while_the_room_holds_is_refused_and_never_taken_later(dosing, action):
    r = dosing
    room = hold(r)
    r.fake.calls.clear()
    request = r.ask(action)
    r.runner.poll()
    assert r.status()[1]["handled"] == request["id"]
    assert r.status()[1]["handled_result"] == REFUSED
    assert not [a for a in r.actions() if a[0] in ("turn_on", "press", "set_value")]
    r.clock.t += 181  # the hold ends; the same request is still there
    assert not r.c.duplicate_hold(room)
    r.runner.poll()
    assert not [a for a in r.actions() if a[0] in ("turn_on", "press", "set_value")]
    assert r.status()[1]["handled_result"] == REFUSED


def test_a_dose_waiting_before_the_first_read_is_refused(tmp_path, monkeypatch):
    """The dosing thread starts after the guard's first read; when that read is not answered, the room
    holds, so a dose request already waiting is refused, not taken."""
    monkeypatch.setattr(controller, "ha_get_status", lambda entity, timeout=8: (None, controller.HAState()))
    monkeypatch.setattr(fake_ha.FakeHA, "ha_get_status", lambda self, entity, timeout=8: (None, controller.HAState()))
    r = make_rig(tmp_path, monkeypatch)()
    r.config()
    request = r.ask("dose")
    r.runner.poll()
    assert r.status()[1]["handled"] == request["id"] and r.status()[1]["handled_result"] == REFUSED
    assert not [a for a in r.actions() if a[0] in ("turn_on", "press", "set_value")]


def test_a_stop_still_switches_the_pumps_off_while_the_room_holds(dosing):
    r = dosing
    hold(r)
    r.fake.calls.clear()
    r.ask("stop")
    r.runner.poll()
    assert ("turn_off", "switch.balance_power") in r.actions()
    assert r.status()[1]["handled_result"] == "stopped"


def test_a_dose_running_when_the_other_controller_appears_runs_to_its_end(dosing):
    r = dosing
    room = r.c.rooms[0]
    request = r.ask("dose", ml=50)
    # The other controller's beat lands while the dose runs (2 s in, between two of its reads).
    r.clock.at(2, lambda: (r.fake.set_state(BEAT, "healthy", {"controller_instance": "x"}),
                           r.c._guard_read(room)))
    r.runner.poll()
    assert r.c.duplicate_hold(room)
    assert (r.status()[1]["handled"], r.status()[1]["handled_result"]) == (request["id"], "finished")
