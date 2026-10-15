"""The controller feeds the P1 rise rule settled readings, the learned gain and the zone's two new settings.

At each P1 shot it keeps the zone's settled reading (the median of its readings over the last minutes, since its
last shot) and what the shot should lift it by from the learned gain; the engine compares the settled reading
afterwards with it. The rise each extra shot needs and how many extra shots P1 may give are numbers, the zone's
over the room's, falling back to the rule as it was (0.5 and 3) when an older integration has neither, without
raising the missing-setting alert. A state file from before them loads with nothing to compare, as before.
"""
import json
from datetime import timedelta

import pytest

import controller
from test_plan_hold_never_stops_rescues import Clock, probe, rig  # noqa: F401 (rig: a pytest fixture)


def _win(st, now, values):
    st["win"] = [(now - timedelta(minutes=len(values) - 1 - i), v) for i, v in enumerate(values)]


def test_the_settled_reading_is_the_median_since_the_last_shot(rig):  # noqa: F811
    c, _fake, room = rig
    st, now = room.state[1], Clock(2026, 9, 23, 14, 0)
    assert c._settled_vwc(dict(st, win=[])) is None
    _win(st, now, [50.0] * 5 + [62.0, 62.4, 61.6, 66.0, 62.1, 61.9, 62.2, 62.0, 62.3, 61.8])
    st["last_shot"] = now - timedelta(hours=1)
    assert c._settled_vwc(st) == pytest.approx(62.05)  # the last 10 minutes; one jump to 66 hardly moves it
    st["last_shot"] = now - timedelta(minutes=3, seconds=30)
    assert c._settled_vwc(st) == pytest.approx(62.1)  # only what was read since the shot


def test_each_p1_shot_keeps_the_settled_reading_and_the_rise_the_gain_expects(rig):  # noqa: F811
    c, _fake, room = rig
    st, now = room.state[1], Clock(2026, 9, 23, 14, 0)
    _win(st, now, [61.6, 62.4] * 5)
    st.update(phase="P1", peak=62.4, p1_reached=True, last_shot=now - timedelta(minutes=30))
    st["learn"].update(gain=0.8)
    c._advance_shot_counters(room, 1, 3.0, delivered_l=10.0)
    assert (st["p1_settled_before"], st["p1_expected_rise"], st["p1_extra"]) == (62.0, 2.4, 1)
    st["learn"].update(gain=None)
    c._advance_shot_counters(room, 1, 3.0, delivered_l=10.0)
    assert st["p1_expected_rise"] is None
    c._record_phase(room, 1, st, "P0", "P1", now, "test")  # a fresh P1 starts with nothing to compare
    assert (st["p1_settled_before"], st["p1_expected_rise"]) == (None, None)


def test_the_snapshot_carries_them_to_the_engine(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    probe(fake, 1, 62.0)
    st = room.state[1]
    _win(st, now - timedelta(minutes=1), [62.0] * 9)
    st.update(phase="P1", last_shot=now - timedelta(minutes=20), p1_settled_before=61.0, p1_expected_rise=2.4)
    snap, _p = c._snapshot(room, 1, now, True, False)
    assert (snap.vwc_settled, snap.p1_settled_before_shot, snap.p1_expected_rise) == (62.0, 61.0, 2.4)


def test_the_zones_settings_win_and_an_older_integration_falls_back_quietly(rig):  # noqa: F811
    c, fake, room = rig
    p = c._params(room, 1)
    assert (p.p1_rise_pts, p.p1_max_extra_shots) == (0.5, 3)
    assert not {e for e in c._defaulted_this_loop if "p1_rise_pts" in e or "extra_shots" in e}
    fake.set_state("number.crop_steering_p1_rise_pts", "0.8")
    fake.set_state("number.crop_steering_p1_maximum_extra_shots", "2")
    fake.set_state("number.crop_steering_zone_1_p1_maximum_extra_shots", "1")
    p = c._params(room, 1)
    assert (p.p1_rise_pts, p.p1_max_extra_shots) == (0.8, 1)
    assert controller.FALLBACK["p1_rise_pts"] == 0.5 and controller.FALLBACK["p1_maximum_extra_shots"] == 3


def test_the_new_keys_survive_a_restart_and_an_old_file_loads_without_them(rig):  # noqa: F811
    c, _fake, room = rig
    room.state[1].update(p1_settled_before=62.05, p1_expected_rise=2.4)
    saved = c._serialize_zone(room.state[1])
    back = c._apply_saved_zone(c._fresh_zone(), json.loads(json.dumps(saved)))
    assert (back["p1_settled_before"], back["p1_expected_rise"]) == (62.05, 2.4)
    old = {k: v for k, v in saved.items() if k not in ("p1_settled_before", "p1_expected_rise")}
    back = c._apply_saved_zone(c._fresh_zone(), old)
    assert (back["p1_settled_before"], back["p1_expected_rise"]) == (None, None)
    junk = dict(old, p1_settled_before="x", p1_expected_rise=-1)
    back = c._apply_saved_zone(c._fresh_zone(), junk)
    assert (back["p1_settled_before"], back["p1_expected_rise"]) == (None, None)
