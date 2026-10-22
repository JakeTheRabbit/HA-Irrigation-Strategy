"""Read-only sensing (sensing.py): each zone's live dryback sensor, and the water-and-VPD record behind its switch."""
from datetime import datetime, timedelta

import pytest

import sensing
from test_zone_status_one_owner import _room


def test_each_zone_publishes_its_relative_dryback_with_the_points_beside_it():
    c, fake = _room()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    fake.set_state("sensor.crop_steering_vwc_zone_1", "50")
    c.loop_once(datetime(2026, 9, 23, 12, 1))
    state, attrs = fake.sets["sensor.crop_steering_zone_1_dryback_app"]
    peak = c.rooms[0].state[1]["peak"]
    assert state == pytest.approx((peak - 50) / peak * 100)
    assert attrs["unit_of_measurement"] == "%"
    assert attrs["peak_vwc"] == peak and attrs["dryback_points"] == pytest.approx(peak - 50)
    assert "rate_points_per_h" in attrs and "drying_back" in attrs and "relative" in attrs["note"].lower()


def test_a_zone_without_a_probe_reads_unknown():
    c, fake = _room()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert fake.sets["sensor.crop_steering_zone_2_dryback_app"][0] == "unknown"


def test_dryback_is_unknown_without_a_peak():
    assert sensing.dryback(0.0, 50.0, 0.4, 60)[0] == "unknown"
    assert sensing.dryback(None, 50.0, 0.4, 60)[0] == "unknown"


def test_drying_back_only_once_the_shot_has_settled():
    assert sensing.dryback(60, 55, 0.5, 30)[1]["drying_back"] is True
    assert sensing.dryback(60, 55, 0.5, 5)[1]["drying_back"] is False
    assert sensing.dryback(60, 55, 0.0, 60)[1]["drying_back"] is False


def test_water_vpd_off_publishes_nothing_and_keeps_no_record():
    c, fake = _room()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert "sensor.crop_steering_zone_1_water_response_app" not in fake.sets
    assert c.rooms[0].state[1]["water_vpd"] is None


def test_water_vpd_on_samples_and_says_not_enough_data():
    c, fake = _room()
    fake.set_state("switch.crop_steering_water_vpd_insight", "on")
    fake.set_state("sensor.room_vpd", "1.2")
    c.rooms[0].climate = {"vpd_sensor": "sensor.room_vpd"}
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    state, attrs = fake.sets["sensor.crop_steering_zone_1_water_response_app"]
    assert state == "unknown" and attrs["n_days"] == 0 and attrs["words"].startswith("Not enough data")
    assert attrs["vpd_now_kpa"] == pytest.approx(1.2)
    w = c.rooms[0].state[1]["water_vpd"]
    assert w["vpd"][1] == 1  # lights on at noon: this pass's VPD is counted


def test_a_new_grow_day_closes_yesterdays_record_with_its_litres():
    st = sensing.fresh()
    for i in range(6):
        sensing.sample(st, day="2026-10-01", ts=1000.0 + i * 700, lights_on=True, rate=0.5 + i * 0.1,
                       minutes_since_shot=45, vpd=1.0 + i * 0.02)
    closed = sensing.sample(st, day="2026-10-02", ts=10000.0, lights_on=False, rate=0.9, minutes_since_shot=45,
                            vpd=1.5)
    assert closed["date"] == "2026-10-01" and closed["samples"] == 6
    assert closed["rate"] == pytest.approx(0.75) and closed["vpd"] == pytest.approx(1.05)
    rec = sensing.keep(st, closed, 8.0, 4)
    assert rec["litres"] == 8.0 and rec["per_plant"] == 2.0 and st["day_hist"] == [rec]
    assert st["water_vpd"]["day"] == "2026-10-02" and st["water_vpd"]["vpd"] == [0.0, 0]  # lights off: not counted


def test_samples_skip_shot_windows_and_come_at_most_every_ten_minutes():
    st = sensing.fresh()
    sensing.sample(st, day="d", ts=0.0, lights_on=True, rate=0.5, minutes_since_shot=10, vpd=None)
    sensing.sample(st, day="d", ts=60.0, lights_on=True, rate=0.5, minutes_since_shot=40, vpd=None)
    sensing.sample(st, day="d", ts=120.0, lights_on=True, rate=0.6, minutes_since_shot=41, vpd=None)
    sensing.sample(st, day="d", ts=700.0, lights_on=True, rate=0.7, minutes_since_shot=50, vpd=None)
    assert st["water_vpd"]["rates"] == [0.5, 0.7]


def test_the_fit_finds_the_slope_once_there_are_enough_days_with_spread():
    days = [{"date": f"2026-10-{i:02d}", "vpd": 0.8 + i * 0.05, "rate": 0.4 + (0.8 + i * 0.05) * 0.5}
            for i in range(1, 8)]
    f = sensing.fit(days)
    assert f["n"] == 7 and f["slope"] == pytest.approx(0.5) and f["r"] == pytest.approx(1.0)
    assert "faster" in f["words"] and "not a cause" in f["words"]
    assert sensing.fit(days[:6])["slope"] is None
    flat = [{**d, "vpd": 1.0 + i * 0.01} for i, d in enumerate(days)]
    assert sensing.fit(flat)["slope"] is None  # spread under 0.2 kPa


def test_vpd_from_temperature_and_humidity():
    assert sensing.vpd_from(25.0, 60.0) == pytest.approx(1.2675, abs=1e-3)
    assert sensing.vpd_from(None, 60.0) is None and sensing.vpd_from(25.0, 120.0) is None


# ---------------------------------------------------------------- CTL-034: say so when there is no estimate
NEXT = "sensor.crop_steering_prediction_zone_1_next_irrigation_hours"
DRYBACK = "sensor.crop_steering_zone_1_dryback_app"


def _p2(vwcs, start=datetime(2026, 9, 23, 12, 0), shot_at=None):
    """A P2 zone read once a minute at these VWCs. -> (controller, fake, [(next sensor, dryback sensor)] per pass)."""
    c, fake = _room()
    c.rooms[0].state[1]["phase"] = "P2"
    seen = []
    for i, v in enumerate(vwcs):
        now = start + timedelta(minutes=i)
        fake.set_state("sensor.crop_steering_vwc_zone_1", str(v))
        if shot_at == i:
            c.rooms[0].state[1]["last_shot"] = now
        c.loop_once(now)
        seen.append((fake.sets.get(NEXT), fake.sets.get(DRYBACK)))
    return c, fake, seen


def test_next_irrigation_is_unknown_with_a_reason_when_the_controller_has_no_estimate():
    _, _, seen = _p2([55, 55, 55, 55])  # steady: no falling VWC, no estimate
    state, attrs = seen[-1][0]
    assert state == "unknown" and attrs["reason"]


def test_a_stale_zero_is_replaced_by_unknown_after_the_shot():
    c, fake = _room()
    st = c.rooms[0].state[1]
    st["phase"] = "P2"
    t0 = datetime(2026, 9, 23, 12, 0)
    fake.set_state("sensor.crop_steering_vwc_zone_1", "30")  # below the re-water point: due now
    c.loop_once(t0)
    assert fake.sets[NEXT][0] == 0.0
    fake.set_state("sensor.crop_steering_vwc_zone_1", "60")  # the shot has gone in
    st["last_shot"] = t0
    for i in (1, 2, 3):
        c.loop_once(t0 + timedelta(minutes=i))
    state, attrs = fake.sets[NEXT]
    assert state == "unknown" and "shot" in attrs["reason"]


def test_a_falling_zone_publishes_a_number_and_no_estimated_at():
    now = datetime(2026, 9, 23, 12, 0)
    c, fake = _room()
    c.rooms[0].state[1]["phase"] = "P2"
    for i, v in enumerate([60, 59, 58, 57]):
        fake.set_state("sensor.crop_steering_vwc_zone_1", str(v))
        c.loop_once(now + timedelta(minutes=i))
    state, attrs = fake.sets[NEXT]
    assert isinstance(state, float) and state > 0 and "reason" not in attrs and "estimated_at" not in attrs


def test_the_rate_is_known_after_three_post_shot_readings_though_the_window_spans_the_shot():
    c, fake = _room()
    st = c.rooms[0].state[1]
    st["phase"] = "P2"
    t0 = datetime(2026, 9, 23, 12, 0)
    for i in range(30):  # a full 30-reading window before the shot
        fake.set_state("sensor.crop_steering_vwc_zone_1", "50")
        c.loop_once(t0 + timedelta(minutes=i))
    shot = t0 + timedelta(minutes=29, seconds=30)
    st["last_shot"] = shot
    rates = []
    for i, v in enumerate([62, 61.9, 61.8, 61.7]):
        fake.set_state("sensor.crop_steering_vwc_zone_1", str(v))
        c.loop_once(t0 + timedelta(minutes=30 + i))
        rates.append(fake.sets[DRYBACK][1]["rate_points_per_h"])
    assert rates[:2] == [None, None] and rates[2] == pytest.approx(0.2 * 30, rel=0.01)  # 0.2 points in 2 min
    assert rates[3] is not None and rates[3] > 0


def test_the_reason_does_not_say_shot_when_the_last_shot_is_only_the_switch_on_anchor():
    c, fake = _room()
    st = c.rooms[0].state[1]
    st["phase"] = "P2"
    st["last_shot_is_anchor"] = True
    t0 = datetime(2026, 9, 23, 12, 0)
    st["last_shot"] = t0
    fake.set_state("sensor.crop_steering_vwc_zone_1", "55")
    c.loop_once(t0 + timedelta(minutes=1))
    assert "shot" not in fake.sets[NEXT][1]["reason"]


def test_the_dryback_rate_is_null_when_there_is_no_rate_and_a_number_when_steady():
    assert sensing.dryback(60, 55, None, 60)[1]["rate_points_per_h"] is None
    assert sensing.dryback(60, 55, None, 60)[1]["drying_back"] is False
    assert sensing.dryback(60, 55, 0.0, 60)[1]["rate_points_per_h"] == 0.0
    _, _, seen = _p2([55, 55])  # two readings: not yet a rate
    assert seen[-1][1][1]["rate_points_per_h"] is None
    _, _, seen = _p2([55, 55, 55, 55])
    assert seen[-1][1][1]["rate_points_per_h"] == 0.0  # a real steady reading


def test_no_rate_right_after_a_shot_until_a_new_one_exists():
    _, _, seen = _p2([50, 50, 50, 60, 60, 60], shot_at=3)
    assert seen[3][1][1]["rate_points_per_h"] is None
    assert seen[4][1][1]["rate_points_per_h"] is None
    assert seen[5][1][1]["rate_points_per_h"] is None  # fewer than 3 readings since the shot


def test_a_consumer_that_reads_a_number_gets_none_from_unknown_and_null_not_a_crash():
    for state in ("unknown", "unavailable", None):
        assert sensing.number(state) is None
    assert sensing.number(sensing.dryback(60, 55, None, 60)[1]["rate_points_per_h"]) is None
