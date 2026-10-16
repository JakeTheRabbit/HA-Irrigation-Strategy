"""The sump water balance (runoff_balance.py): a room-wide runoff estimate from the sump's runs, the AC and dehumidifier
run time and the litres fed, calibrated and checked by the sealed-room closure. Read only."""
from datetime import datetime

import pytest

import runoff_balance as rb
from test_zone_status_one_owner import _room

V = 4.0  # litres one sump run empties
T0 = 1_760_000_000.0


def _simulate(days=7, runoff=0.15, delay_min=20, ac_lph=6.0, dehum_lph=2.0, base_lph=0.3, shot_l=2.0):
    """Minute by minute: the pit fills from the AC (on in alternate 30-minute blocks, more by day), the
    dehumidifier (on with the lights, 08-20), a baseline and the runoff of hourly shots by day; a run empties V."""
    st = rb.fresh()
    ac, dehum = [], []
    level, pending = 0.0, []
    ac_on = dehum_on = None
    for m in range(days * 1440):
        t = T0 + m * 60
        hour = (m // 60) % 24
        day = 8 <= hour < 20
        a = (m // 30) % 2 == 0 if day else (m // 30) % 4 == 0
        d = day
        for flag, was, spans in ((a, ac_on, ac), (d, dehum_on, dehum)):
            if flag and not was:
                spans.append([t, None])
            if not flag and was:
                spans[-1][1] = t
        ac_on, dehum_on = a, d
        if day and m % 60 == 0:
            rb.add_shot(st, t, shot_l)
            pending.append((t + delay_min * 60, shot_l * runoff))
        level += (ac_lph * a + dehum_lph * d + base_lph) / 60.0
        for item in [p for p in pending if p[0] <= t]:
            level += item[1]
            pending.remove(item)
        if level >= V:
            st["runs"].append([t, t + 60])
            level -= V
    end = T0 + days * 86400
    st["on"] = {"switch.ac": [[s, e or end] for s, e in ac], "switch.dehum": [[s, e or end] for s, e in dehum]}
    return st


def test_the_fit_recovers_the_runoff_share_the_condensate_and_the_drain_delay():
    st = _simulate()
    f = rb.fit(st, ["switch.ac", "switch.dehum"], 90)
    assert f is not None and f["n"] > 100
    assert f["r_pit_per_l"] * V == pytest.approx(0.15, abs=0.05)
    assert f["beta"][0] * V == pytest.approx(6.0, rel=0.25)
    assert f["beta"][1] * V == pytest.approx(2.0, rel=0.5)
    assert f["delay_min"] in (15, 20, 30)
    state, attrs = rb.estimate(st, ["switch.ac", "switch.dehum"], volume=V, volume_source="sump_litres_per_run",
                               f=f, now_s=T0 + 7 * 86400, today_start_s=T0 + 6 * 86400)
    assert state == pytest.approx(15, abs=5) and attrs["band_pct"] is not None
    assert "room-wide" in attrs["scope"] and attrs["blocks"]
    assert attrs["transpiration_today_l"] > 0


def test_too_few_cycles_is_learning_and_a_stopped_sump_is_unresolvable():
    st = _simulate(days=1)
    st["runs"] = st["runs"][:5]
    assert rb.fit(st, [], 90) is None
    assert rb.estimate(st, [], volume=V, volume_source="x", f=None, now_s=T0, today_start_s=T0)[0] == "learning"
    state, attrs = rb.estimate(st, [], volume=V, volume_source="x", f=None, now_s=T0, today_start_s=T0,
                               unresolvable="the sump pump has not run (CS-311)")
    assert state == "unresolvable" and "CS-311" in attrs["why"]


def test_without_litres_per_run_no_litres_are_invented():
    st = _simulate()
    f = rb.fit(st, ["switch.ac", "switch.dehum"], 90)
    state, attrs = rb.estimate(st, ["switch.ac", "switch.dehum"], volume=None, volume_source="unknown", f=f,
                               now_s=T0 + 7 * 86400, today_start_s=T0 + 6 * 86400)
    assert state == "learning" and "runoff_pct" not in attrs and attrs["runoff_share_of_pit_pct"] is not None


def test_the_sealed_room_closure_calibrates_the_pit_and_checks_each_day():
    st = rb.fresh()
    for i, (runs, fed, ds) in enumerate([(10, 210.0, 10.0), (11, 220.0, 0.0), (9, 185.0, 5.0), (10, 200.0, 0.0)]):
        st["days"].append({"date": f"2026-10-0{i + 1}", "runs": runs, "fed_l": fed, "delta_substrate_l": ds})
    assert rb.closure_volume(st) == pytest.approx(20.0)
    assert rb.closure_error_pct(st["days"][0], 20.0) == pytest.approx(0.0)
    leak = {"date": "x", "runs": 6, "fed_l": 200.0, "delta_substrate_l": 0.0}
    assert rb.closure_error_pct(leak, 20.0) == pytest.approx(-40.0)
    st["days"] = st["days"][:2]
    assert rb.closure_volume(st) is None  # fewer than three complete days


def test_a_new_grow_day_closes_the_last_with_its_runs_feed_and_substrate_change():
    st = rb.fresh()
    st["runs"] = [[T0 + 3600, T0 + 3660], [T0 + 7200, T0 + 7260]]
    rb.add_shot(st, T0 + 100, 3.0)
    assert rb.day_tick(st, "2026-10-01", T0, 50.0) is None
    closed = rb.day_tick(st, "2026-10-02", T0 + 86400, 48.0)
    assert (closed["runs"], closed["fed_l"], closed["delta_substrate_l"]) == (2, 3.0, -2.0)
    assert st["day"]["date"] == "2026-10-02" and st["days"] == [closed]


def test_spans_and_merges_from_history():
    rows = [(0.0, 10.0), (120.0, 20.0), (0.0, 80.0), (300.0, 100.0)]
    assert rb.spans(rows, lambda w: w > 20, 200.0) == [[20.0, 80.0], [100.0, 200.0]]
    assert rb.merge([[20.0, 80.0], [100.0, 150.0]], [[100.0, 200.0]]) == [[20.0, 80.0], [100.0, 200.0]]


def test_an_old_or_damaged_record_loads_fresh():
    assert rb.load(None) == rb.fresh()
    assert rb.load({"runs": "x", "on": {"a": [[1, 2], "bad"]}, "cursor": True})["on"] == {"a": [[1, 2]]}


def test_off_reads_nothing_and_a_room_without_a_sump_says_so():
    c, fake = _room()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert "sensor.crop_steering_runoff_estimate_app" not in fake.sets and c.rooms[0]._runoff_mode == "off"
    fake.set_state("select.crop_steering_runoff_estimator", "shadow")
    c.loop_once(datetime(2026, 9, 23, 12, 1))
    assert fake.sets["sensor.crop_steering_runoff_estimate_app"][0] == "no_sump"
    assert not rb.has_data(c.rooms[0]._runoff)


def test_shadow_with_a_sump_records_runs_and_publishes_a_room_wide_estimate(monkeypatch):
    import controller

    c, fake = _room()
    c.sump_sensors = {"*": "sensor.sump_power"}
    fake.set_state("sensor.sump_power", "0", {"unit_of_measurement": "W"})
    fake.set_state("select.crop_steering_runoff_estimator", "shadow")
    rows = [("0", "2026-09-23T10:00:00+00:00"), ("150", "2026-09-23T10:30:00+00:00"),
            ("0", "2026-09-23T10:31:00+00:00")]
    monkeypatch.setattr(controller, "ha_history", lambda entity, since, timeout=12: rows)
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    state, attrs = fake.sets["sensor.crop_steering_runoff_estimate_app"]
    assert state == "learning" and attrs["mode"] == "shadow" and "room-wide" in attrs["scope"]
    assert len(c.rooms[0]._runoff["runs"]) == 1
