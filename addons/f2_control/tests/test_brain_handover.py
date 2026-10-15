"""The Setpoints judge's two numbers when the brain cannot act (haiku-brain-design 10.3): the learner takes them over,
its writes and field capacity's are never read as edits by hand, and at the next lights-on the threshold comes back
through a guard that never breaks the ladder rescue + 3 <= threshold < P1 target <= field capacity."""
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import jev_bridge
import jev_kit as K
from jev.judges.setpoints import SHOT, THRESHOLD, SetpointsJudge
from jev.setpoint_memory import SetpointMemory

NOW = datetime(2026, 9, 27, 13, 0)


class FakeC:
    """Just what the handover reads and writes: the zone's numbers, the Auto setpoints switch, the number limits."""

    def __init__(self, threshold=40.0, shot=5.0, can_act=True, limits=(20.0, 70.0), auto=True):
        self.nums = {THRESHOLD: threshold, SHOT: shot}
        self.limits, self.auto, self.writes = limits, auto, []
        meter = SimpleNamespace(live=lambda: self.live, lights_on=lambda at: None)
        self.live = can_act
        self.jev = SimpleNamespace(judges=[SetpointsJudge()], setpoints=SetpointMemory(), dry_run=False,
                                   asker=SimpleNamespace(meter=meter), journal=None)

    def _jev_read(self, entity):
        return self.nums[entity.rsplit("_", 3)[-3] + "_" + "_".join(entity.rsplit("_", 3)[-2:])]

    def _on(self, entity, default=False):
        return self.auto

    def _zone_bounded(self, room, zone, suffix, value):
        return round(max(self.limits[0], min(self.limits[1], value)), 1)

    def _auto_write(self, room, zone, suffix, old, value, learn, now, by="auto"):
        self.writes.append((suffix, old, value, by))
        self.nums[suffix] = value
        return True


ROOM = SimpleNamespace(slug="default", prefix="", state={1: {"learn": {}}}, strategy_required=False)


def _p(fc=48.0, rescue=35.0, p1=46.0):
    return K.params(field_capacity=fc, p3_emergency_floor=rescue, p1_target=p1)


def _hold(c, p, home=40.0):
    c.jev.setpoints.zone("default", 1)["home"][THRESHOLD] = home
    c.live = False
    assert jev_bridge.judge_levers(c, ROOM) == ()
    jev_bridge._handover(c, ROOM, 1, p, NOW, ())


def _back(c, p):
    c.live = True
    jev_bridge.lights_on(c, ROOM, NOW + timedelta(hours=20))
    levers = jev_bridge.judge_levers(c, ROOM)
    jev_bridge._handover(c, ROOM, 1, p, NOW + timedelta(hours=20), levers)
    return levers


def test_the_levers_stay_with_the_learner_until_a_lights_on_at_which_the_brain_can_act():
    c = FakeC()
    assert jev_bridge.judge_levers(c, ROOM) == (SHOT, THRESHOLD)
    c.live = False
    assert jev_bridge.judge_levers(c, ROOM) == ()
    c.live = True  # a 60 s pause ended: no flip back within the grow-day
    assert jev_bridge.judge_levers(c, ROOM) == ()
    jev_bridge.lights_on(c, ROOM, NOW)
    assert jev_bridge.judge_levers(c, ROOM) == (SHOT, THRESHOLD)


def test_learner_writes_during_a_hold_are_not_edits_by_hand_and_leave_home_put():
    c, p = FakeC(), _p()
    _hold(c, p)
    jev_bridge.learner_wrote(c, ROOM, 1, THRESHOLD, 40.0, 38.5, NOW)
    rec = c.jev.setpoints.zone("default", 1)
    assert rec["written"][THRESHOLD] == 38.5 and rec["home"][THRESHOLD] == 40.0 and rec["held"]


def test_with_nothing_moved_the_held_value_comes_back_once():
    c, p = FakeC(), _p()
    _hold(c, p)
    c.nums[THRESHOLD] = 38.5  # the learner's day
    assert _back(c, p) == (SHOT, THRESHOLD)
    assert c.writes == [(THRESHOLD, 38.5, 40.0, "brain: levers back")]
    assert "held" not in c.jev.setpoints.zone("default", 1)
    jev_bridge._handover(c, ROOM, 1, p, NOW, (SHOT, THRESHOLD))
    assert len(c.writes) == 1  # at most once


def test_field_capacity_moving_during_the_hold_keeps_the_ladder_whole():
    c, p = FakeC(threshold=40.0), _p(fc=48.0, rescue=37.0)
    _hold(c, p)
    c.nums[THRESHOLD] = 42.0  # _follow_fc moved the threshold and the rescue floor up 2
    jev_bridge.fc_moved(c, ROOM, 1, 40.0, 42.0, NOW)
    assert c.jev.setpoints.zone("default", 1)["home"][THRESHOLD] == 42.0
    after = _p(fc=50.0, rescue=39.0, p1=48.0)
    _back(c, after)  # the held 40 belongs to a ladder that moved: never written back under rescue + 3
    lo, hi = jev_bridge.setpoint_band(THRESHOLD, 42.0, after)
    assert lo <= c.nums[THRESHOLD] <= hi and after.p3_emergency_floor + 3 <= c.nums[THRESHOLD]
    assert all(w[2] != 40.0 for w in c.writes)


def test_a_learner_value_under_the_band_moves_to_its_lower_edge_only():
    c, p = FakeC(), _p()
    _hold(c, p, home=40.0)
    c.nums[THRESHOLD] = 35.0
    c.jev.setpoints.zone("default", 1)["held"]["field_capacity"] = 0  # field capacity moved: the target is today's
    _back(c, p)
    lo, _hi = jev_bridge.setpoint_band(THRESHOLD, 40.0, p)
    assert c.writes == [(THRESHOLD, 35.0, lo, "brain: levers back")]


def test_limits_an_empty_band_or_a_broken_ladder_write_nothing():
    for c, p in ((FakeC(limits=(20.0, 36.0)), _p()), (FakeC(), _p(rescue=44.0)), (FakeC(), _p(p1=39.0))):
        _hold(c, p)
        c.nums[THRESHOLD] = 35.0
        _back(c, p)
        assert c.writes == []


def test_a_zone_with_auto_setpoints_off_is_never_written():
    c, p = FakeC(auto=False), _p()
    _hold(c, p)
    c.nums[THRESHOLD] = 35.0
    _back(c, p)
    assert c.writes == []


def test_after_every_handback_the_ladder_is_whole():
    rng = random.Random(11)
    for _ in range(500):
        fc = rng.uniform(40, 60)
        p = _p(fc=fc, rescue=rng.uniform(20, fc - 12), p1=fc - rng.uniform(0, 4))
        c = FakeC(threshold=round(rng.uniform(p.p3_emergency_floor + 3, p.p1_target - 0.5), 1),
                  limits=(round(rng.uniform(15, 30), 1), round(rng.uniform(45, 70), 1)))
        _hold(c, p, home=c.nums[THRESHOLD])
        c.nums[THRESHOLD] = round(rng.uniform(p.p3_emergency_floor, p.p1_target + 2), 1)
        if rng.random() < 0.3:
            jev_bridge.fc_moved(c, ROOM, 1, c.nums[THRESHOLD], c.nums[THRESHOLD] + 1, NOW)
        _back(c, p)
        if c.writes:
            v = c.writes[-1][2]
            assert p.p3_emergency_floor + 3 <= v < p.p1_target <= p.field_capacity
            assert c.limits[0] <= v <= c.limits[1]
