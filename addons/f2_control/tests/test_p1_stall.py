"""The controller drives the P1 stall exit (core.p1_stall) the way it went live.

Seen live: zones ramped for hours at 25-28 % against peak targets of 40-51 %, every shot bigger, the reading flat.
The controller now counts the ramp shots in a row that did not give the rise P1 needs, hands the zone to P2 after
two, and holds the re-water point under what the zone reached for the rest of that grow-day, so P2 does not keep
firing at a point the zone cannot reach. A probe in doubt (CS-710 raised, or a reading that does not move) keeps
the ramp as it was.
"""
from datetime import timedelta

import pytest

from test_plan_hold_never_stops_rescues import Clock, opened, probe, rig  # noqa: F401 (rig: a pytest fixture)

pytestmark = pytest.mark.usefixtures("no_blind_grace", "settings_built_in")


def _since_shot(st, now, value, minutes=10):
    st["win"] = [(now - timedelta(minutes=minutes - i), value + (0.05 if i % 2 else 0.0)) for i in range(minutes)]


def _ramp(c, fake, room, now, vwc, before, flat):
    probe(fake, 1, vwc)
    probe(fake, 2, 55)
    st = room.state[1]
    st.update(phase="P1", shots=3, last_shot=now - timedelta(minutes=20), p1_settled_before=before, p1_flat=flat,
              p1_reached=False, peak=40.0)
    room.state[2].update(phase="P2", last_shot=now - timedelta(minutes=20))
    for zone in (1, 2):
        room.state[zone].update(last_daily_reset=now.date(), last_phase_change=now - timedelta(hours=2))
    _since_shot(st, now, vwc)
    return st


def test_the_live_sequence_hands_over_after_two_flat_shots_and_rewaters_under_it(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 10, 16, 13, 0)
    st = _ramp(c, fake, room, now, 25.2, 25.0, 0)  # shot 1 took it 25.0 -> 25.2
    pub = c._loop_room(room, now)
    assert st["phase"] == "P1" and pub[1]["fire"] and pub[1]["reason"].kind == "p1_ramp"
    assert "switch.v1" in opened(fake)
    assert st["p1_flat"] == 1 and st["p1_settled_before"] == pytest.approx(25.2, abs=0.06)

    now = Clock.instant = now + timedelta(minutes=20)  # shot 2 took it 25.2 -> 25.1
    probe(fake, 1, 25.1)
    probe(fake, 2, 55)
    _since_shot(st, now, 25.1)
    fake.calls.clear()
    pub = c._loop_room(room, now)
    assert st["phase"] == "P2"
    assert str(pub[1]["reason"]).startswith("P1 stalled at 25.2%: 2 shots did not raise moisture")
    assert not pub[1]["fire"] and "switch.v1" not in opened(fake)
    stall = st["p1_stall"]
    assert stall["day"] == "2026-10-16" and stall["rewater"] < 25.1
    assert any("P1 stalled at" in line for line in c._activity)

    now = Clock.instant = now + timedelta(minutes=5)  # the rest of the day re-waters under what it reached
    probe(fake, 1, 25.0)
    probe(fake, 2, 55)
    pub = c._loop_room(room, now)
    assert pub[1]["p"].p2_threshold == stall["rewater"] and not pub[1]["fire"]
    # the next lights-on starts a new day with the set re-water point
    assert c._p1_stall_today(room, st, now + timedelta(days=1)) is None


def test_a_rising_shot_resets_the_count(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 10, 16, 13, 0)
    st = _ramp(c, fake, room, now, 27.0, 25.0, 1)
    pub = c._loop_room(room, now)
    assert st["phase"] == "P1" and pub[1]["fire"] and st["p1_flat"] == 0


def test_a_zone_with_cs_710_raised_keeps_ramping(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 10, 16, 13, 0)
    st = _ramp(c, fake, room, now, 25.1, 25.2, 1)
    c._alerted[f"jev_channel_{room.slug}_z1"] = now - timedelta(hours=1)
    pub = c._loop_room(room, now)
    assert st["phase"] == "P1" and pub[1]["fire"] and pub[1]["reason"].kind == "p1_ramp"
    assert st["p1_stall"] is None


def test_a_reading_that_does_not_move_is_in_doubt(rig):  # noqa: F811
    c, _fake, room = rig
    now = Clock(2026, 10, 16, 13, 0)
    st = room.state[1]
    st["last_shot"] = now - timedelta(minutes=20)
    st["win"] = [(now - timedelta(minutes=i), 25.0) for i in range(10)]
    assert "has not moved" in c._p1_probe_suspect(room, 1, st, now)
    _since_shot(st, now, 25.0)
    assert c._p1_probe_suspect(room, 1, st, now) is None
