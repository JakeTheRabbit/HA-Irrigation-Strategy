"""zone_history.py: each zone's plateaus and nights, the dryback planner's record. The numbers are zone 1's: the
explainer's planned night (36.0 plateau, 32.78 at lights-off, 25.58 at lights-on, first shot from 25.18), and the
real night of 30 Sep 2026, which dried to the 20.7 floor and fired a rescue at 08:59."""
from datetime import datetime, timedelta, timezone

import pytest

import zone_history as H


def _zone(**over):
    st = {"phase": "P2", "peak": 0.0, "shots": 0, **H.fresh()}
    st.update(over)
    return st


def test_a_fresh_zone_and_an_old_file_have_no_history():
    assert H.fresh() == {"plateau_hist": [], "night_hist": [], "night": None}
    assert H.restore({}) == H.fresh()
    junk = {"plateau_hist": "junk", "night_hist": [1, {"no": "date"}], "night": {"off_vwc": 3}}
    assert H.restore(junk) == H.fresh()


def test_restore_keeps_good_entries_and_the_newest_14():
    saved = {
        "plateau_hist": [{"date": f"2026-09-{d:02d}", "value": 30.0 + d, "how": "x", "shots": 6} for d in range(1, 21)],
        "night": {"off_at": "2026-09-30T22:00:00", "off_vwc": 30.81},
    }
    out = H.restore(saved)
    assert [e["date"] for e in out["plateau_hist"]] == [f"2026-09-{d:02d}" for d in range(7, 21)]
    assert out["night"]["off_vwc"] == 30.81 and out["night"]["shots"] == 0 and out["night"]["on_at"] is None


def test_p1_handing_over_records_the_days_plateau():
    st = _zone(phase="P1", peak=36.0, shots=6)
    entry = H.phase_changed(st, "P1", "P2", day="2026-10-01", how="P1 recovered 36>=36 EC ok 4.6")
    assert entry == {"date": "2026-10-01", "value": 36.0, "how": "P1 recovered 36>=36 EC ok 4.6", "shots": 6}
    assert st["plateau_hist"] == [entry]


def test_a_second_hand_over_the_same_day_replaces_the_first():
    st = _zone(peak=35.2, shots=4)
    H.phase_changed(st, "P1", "P2", day="2026-10-01", how="set by hand")
    st.update(peak=36.1, shots=6)
    H.phase_changed(st, "P1", "P2", day="2026-10-01", how="Jev's ramp judge: ramp done")
    assert [(e["value"], e["how"]) for e in st["plateau_hist"]] == [(36.1, "Jev's ramp judge: ramp done")]


def test_only_p1_to_p2_is_a_plateau():
    st = _zone(peak=36.0, shots=6)
    for was, new in (("P0", "P1"), ("P2", "P3"), ("P1", "P3"), ("P3", "P0"), ("P1", "P0")):
        assert H.phase_changed(st, was, new, day="2026-10-01", how="x") is None
    assert H.phase_changed(_zone(peak=0.0), "P1", "P2", day="2026-10-01", how="x") is None
    assert st["plateau_hist"] == []


def test_a_clean_night_from_lights_off_to_the_first_shot():
    st = _zone(plateau_hist=[{"date": "2026-10-01", "value": 36.0, "how": "x", "shots": 6}])
    H.lights_off(st, 32.78, datetime(2026, 10, 1, 22, 0), "2026-10-01")
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))
    rec = H.shot(st, vwc_before=25.18, now=datetime(2026, 10, 2, 10, 30), day="2026-10-02", first=True)
    assert st["night"] is None and st["night_hist"] == [rec]
    assert (rec["date"], rec["plateau"], rec["landing"], rec["night_shots"]) == ("2026-10-02", 36.0, 25.18, 0)
    assert (rec["off_at"], rec["on_at"], rec["first_at"]) == (
        "2026-10-01T22:00:00", "2026-10-02T10:00:00", "2026-10-02T10:30:00")
    assert rec["night_rate"] == pytest.approx(0.6) and rec["p0_drop"] == pytest.approx(0.4)
    assert rec["dryback_pct"] == pytest.approx((36.0 - 25.18) / 36.0 * 100.0)
    assert H.night_words(rec) == "night: landed 25.18 (30.1 % under 36.00), 0.60 pts/h, P0 drop 0.40"


def test_30_sep_the_nights_rate_stops_at_the_rescue_shot():
    st = _zone(plateau_hist=[{"date": "2026-09-30", "value": 35.0, "how": "x", "shots": 8}])
    H.lights_off(st, 30.81, datetime(2026, 9, 30, 22, 0), "2026-09-30")
    assert H.shot(st, vwc_before=20.7, now=datetime(2026, 10, 1, 8, 59), day="2026-09-30", first=False) is None
    H.lights_on(st, 24.12, datetime(2026, 10, 1, 10, 0))
    rec = H.shot(st, vwc_before=24.12, now=datetime(2026, 10, 1, 10, 2), day="2026-10-01", first=True)
    assert rec["night_rate"] == pytest.approx((30.81 - 20.7) / (10 + 59 / 60))  # 0.92 an hour, down to the rescue
    assert rec["night_shots"] == 1 and rec["p0_drop"] == pytest.approx(0.0)
    assert rec["dryback_pct"] == pytest.approx((35.0 - 24.12) / 35.0 * 100.0)
    assert H.night_words(rec).endswith(", 1 night shot(s)")


def test_a_shot_after_lights_on_spoils_only_the_p0_drop():
    st = _zone()
    H.lights_off(st, 32.78, datetime(2026, 10, 1, 22, 0), "2026-10-01")
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))
    H.shot(st, vwc_before=25.4, now=datetime(2026, 10, 2, 10, 10), day="2026-10-02", first=False)  # a P0 shot
    rec = H.shot(st, vwc_before=26.0, now=datetime(2026, 10, 2, 10, 40), day="2026-10-02", first=True)
    assert rec["night_rate"] == pytest.approx(0.6)  # lights-off to lights-on: the night itself had no shot
    assert rec["p0_drop"] is None and rec["night_shots"] == 1
    assert rec["plateau"] is None and rec["dryback_pct"] is None  # no plateau was recorded on 1 Oct


def test_a_night_that_never_reached_a_first_shot_is_dropped_at_the_next_lights_off():
    st = _zone()
    H.lights_off(st, 32.78, datetime(2026, 10, 1, 22, 0), "2026-10-01")
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))  # the zone was off all day: no ramp
    H.lights_off(st, 30.0, datetime(2026, 10, 2, 22, 0), "2026-10-02")
    assert st["night"]["off_at"] == "2026-10-02T22:00:00" and st["night"]["on_at"] is None
    assert st["night_hist"] == []


def test_a_missing_reading_leaves_that_number_unknown():
    st = _zone()
    H.lights_off(st, None, datetime(2026, 10, 1, 22, 0), "2026-10-01")  # the probe was unreadable
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))
    rec = H.shot(st, vwc_before=25.18, now=datetime(2026, 10, 2, 10, 30), day="2026-10-02", first=True)
    assert rec["night_rate"] is None and rec["p0_drop"] == pytest.approx(0.4)
    assert "unknown pts/h" in H.night_words(rec)


def test_a_first_shot_with_no_night_open_records_nothing():
    st = _zone()
    assert H.shot(st, vwc_before=25.18, now=datetime(2026, 10, 2, 10, 30), day="2026-10-02", first=True) is None
    assert st["night_hist"] == []


def test_yesterdays_plateau_is_not_used_for_tonight():
    st = _zone(plateau_hist=[{"date": "2026-09-30", "value": 36.0, "how": "x", "shots": 6}])
    H.lights_off(st, 31.0, datetime(2026, 10, 1, 22, 0), "2026-10-01")  # P1 never handed over on 1 Oct
    assert st["night"]["plateau"] is None


def test_the_lists_keep_the_newest_14():
    st = _zone(peak=36.0, shots=6)
    for d in range(1, 21):
        H.phase_changed(st, "P1", "P2", day=f"2026-09-{d:02d}", how="x")
    assert len(st["plateau_hist"]) == H.KEEP == 14 and st["plateau_hist"][0]["date"] == "2026-09-07"


def test_a_night_from_another_grow_day_is_dropped_at_the_first_shot():
    """The room went off on 24 Sep before the ramp and came back on the 25th: the 23rd's night never reached its
    first shot, so it is dropped, never closed as the 25th's night."""
    st = _zone(plateau_hist=[{"date": "2026-09-23", "value": 61.0, "how": "x", "shots": 6}])
    H.lights_off(st, 58.4, datetime(2026, 9, 23, 22, 0), "2026-09-23")
    H.lights_on(st, 51.2, datetime(2026, 9, 24, 10, 0))
    assert H.shot(st, vwc_before=47.0, now=datetime(2026, 9, 25, 10, 5), day="2026-09-25", first=True) is None
    assert st["night"] is None and st["night_hist"] == []


def test_restore_drops_what_has_the_wrong_type_and_keeps_what_a_newer_version_added():
    saved = {
        "plateau_hist": [
            {"date": "2026-09-28", "how": "x", "shots": 6},  # no value
            {"date": "2026-09-29", "value": "36", "how": "x", "shots": 6},  # a value that is not a number
            {"date": "2026-09-31", "value": 36.0, "how": "x", "shots": 6},  # no such date
            {"date": "2026-09-30", "value": float("nan"), "how": "x", "shots": 6},
            {"date": "2026-10-01", "value": 36.0, "how": "x", "shots": "6"},  # shots that are not a count
            {"date": "2026-10-02", "value": 36.1, "how": "x", "shots": 6, "rule": "plateau"},  # a newer key: kept
        ],
        "night": {"off_at": "2026-10-01T22:00:00", "off_vwc": 32.78, "shots": "x"},
    }
    out = H.restore(saved)
    assert out["plateau_hist"] == [{"date": "2026-10-02", "value": 36.1, "how": "x", "shots": 6, "rule": "plateau"}]
    assert out["night"] is None
    for bad in ({"off_at": "garbage"}, {"off_at": "2026-10-01T22:00:00", "off_vwc": "abc"},
                {"off_at": "2026-10-01T22:00:00", "on_at": "noon"}, {"off_at": "2026-10-01T22:00:00", "day": "yesterday"},
                {"off_at": "2026-10-01T22:00:00", "plateau": True}, {"off_at": "2026-10-01T22:00:00", "on_shots": -1}):
        assert H.restore({"night": bad})["night"] is None, bad


def test_a_night_mixing_times_with_and_without_a_utc_offset_is_still_measured():
    """A newer version may write its times with a UTC offset, this one writes local times: both are real moments,
    measured in real hours."""
    off = datetime(2026, 9, 26, 22, 0, tzinfo=timezone(timedelta(hours=12)))
    st = _zone(night=H.restore({"night": {"off_at": off.isoformat(), "off_vwc": 33.0, "day": "2026-09-26"}})["night"])
    on = datetime(2026, 9, 27, 10, 0)
    H.lights_on(st, 26.4, on)
    rec = H.shot(st, vwc_before=26.0, now=datetime(2026, 9, 27, 10, 30), day="2026-09-27", first=True)
    assert rec["night_rate"] == pytest.approx(6.6 / ((on.timestamp() - off.timestamp()) / 3600.0))

