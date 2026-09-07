"""Actual controller regressions for missing EC and persisted seven-grow-day usage."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import controller
import fake_ha


class FixedDateTime(datetime):
    instant = datetime(2026, 9, 8, 12)

    @classmethod
    def now(cls, tz=None):
        return cls.instant.replace(tzinfo=tz) if tz else cls.instant


@pytest.fixture
def rig(monkeypatch, tmp_path):
    FixedDateTime.instant = datetime(2026, 9, 8, 12)
    monkeypatch.setattr(controller, "datetime", FixedDateTime)
    fake = fake_ha.FakeHA()
    options = {"num_zones": 1, "substrate_l": 100,
               "hardware": {"pump": "switch.p", "mainline": "switch.m",
                            "valves": {"1": "switch.v1"}}}
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    room = c.rooms[0]
    room.state[1].update(last_daily_reset=FixedDateTime.instant.date(),
                         last_shot=FixedDateTime.instant - timedelta(hours=1))
    for key in ("system_enabled", "auto_irrigation_enabled", "zone_1_enabled"):
        fake.set_state(f"switch.crop_steering_{key}", "on")
    fake.set_state(room.enable_flag, "on")
    # Keep all actuation local and deterministic.
    clock = {"seconds": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["seconds"])
    monkeypatch.setattr(controller.time, "sleep",
                        lambda dt: clock.__setitem__("seconds", clock["seconds"] + dt))
    return c, fake, room, clock


def probe(fake, entity, value, timestamp="current"):
    if timestamp == "current":
        timestamp = FixedDateTime.now(timezone.utc).isoformat()
    fake.set_state(entity, value, last_updated=timestamp)


@pytest.mark.parametrize("value,stamp", [
    ("unavailable", "current"), ("unknown", "current"), ("NaN", "current"),
    ("inf", "current"), ("-inf", "current"), ("21", "current"),
    ("6", None), ("6", "bad timestamp"), ("6", "2026-09-08T12:00:00"),
    ("6", "2026-09-08T11:39:00+00:00"), ("6", "2026-09-08T12:01:01+00:00"),
])
@pytest.mark.parametrize("pid", [False, True])
def test_invalid_ec_real_loop_uses_base_vwc_and_pauses_learning(rig, value, stamp, pid):
    c, fake, room, _ = rig
    probe(fake, "sensor.crop_steering_vwc_zone_1", "44")
    probe(fake, "sensor.crop_steering_ec_zone_1", value, stamp)
    fake.set_state("switch.crop_steering_ec_stacking_enabled", "on")
    fake.set_state("input_boolean.crop_steering_ec_pid_enabled", "on" if pid else "off")
    fake.set_state(room.enable_flag, "off")  # decision allowed; physical gate must still hold
    st = room.state[1]
    st.update(ec_offset=-8, ec_smooth=1, ec_integral=2, ec_prev_err=3)
    before = {key: st[key] for key in ("ec_offset", "ec_smooth", "ec_integral", "ec_prev_err", "last_ec_steer")}
    pub = c._loop_room(room, FixedDateTime.now())
    assert pub[1]["ec"] is None
    assert pub[1]["fire"] and pub[1]["p"].p2_threshold == 45
    assert "EC unknown" in pub[1]["reason"]
    assert {key: st[key] for key in before} == before
    assert not any(dom == "switch" and svc == "turn_on" for dom, svc, _ in fake.calls)
    c._publish_status(room, pub, FixedDateTime.now())
    status, attrs = fake.sets["sensor.crop_steering_zone_1_safety_status"]
    assert status == "ec_unknown" and attrs["ec_degraded"] and not attrs["ec_valid"]
    assert fake.sets["sensor.crop_steering_system_safety_status"][0] == "warning"
    def ec_alerts():
        return [call for call in fake.calls if call[0] == "persistent_notification"
                and "ec_unknown" in call[2].get("notification_id", "")]
    assert len(ec_alerts()) == 1
    c._loop_room(room, FixedDateTime.now())
    assert len(ec_alerts()) == 1  # same 30-minute debounce as other alerts


def test_unknown_ec_delivers_full_base_shot(rig):
    c, fake, room, _ = rig
    probe(fake, "sensor.crop_steering_vwc_zone_1", "44")
    probe(fake, "sensor.crop_steering_ec_zone_1", "unavailable")
    c._loop_room(room, FixedDateTime.now())
    # 5 percent of 100 L; old fake-zero path silently delivered only 2.5 L.
    assert room.state[1]["daily_vol"] == pytest.approx(5.0)
    assert c._water_usage(room, 1, FixedDateTime.now())[0] == 5.0


@pytest.mark.parametrize("metric", ["ec", "ph"])
@pytest.mark.parametrize("value,stamp", [("NaN", "current"), ("inf", "current"),
                                         ("3", None), ("3", "broken")])
def test_invalid_feed_holds_without_last_good_grace(rig, metric, value, stamp):
    c, fake, room, _ = rig
    setattr(room, f"feed_{metric}_sensor", f"sensor.feed_{metric}")
    fake.set_state(f"number.crop_steering_irrigation_{metric}_min", "2")
    fake.set_state(f"number.crop_steering_irrigation_{metric}_max", "7")
    probe(fake, f"sensor.feed_{metric}", value, stamp)
    assert "fail-closed" in c._blocked(room, 1)


def test_sensor_accepts_valid_aware_time_and_small_clock_skew(rig):
    c, fake, _, _ = rig
    for stamp in ("2026-09-08T12:00:59+00:00", "2026-09-09T00:00:00+12:00"):
        probe(fake, "sensor.ec", 4.2, stamp)
        assert c._read_sensor("sensor.ec", 0, 20) == 4.2


def test_weekly_total_rolls_at_lights_on_and_survives_restart(rig):
    c, _, room, _ = rig
    st = room.state[1]
    st["daily_vol"] = 9.0
    # Retain an old installation's current dated counter, without claiming seven days.
    assert c._water_usage(room, 1, FixedDateTime.now()) == (9.0, {
        "window_start_grow_day": "2026-09-02", "window_end_grow_day": "2026-09-08",
        "observed_grow_days": 1, "complete_grow_days": 0, "history_complete": False,
        "coverage": "partial_history", "legacy_volume_excluded_l": 0.0,
        "measurement": "estimated controller delivery; current grow-day to date",
    })
    c._advance_shot_counters(room, 1, 1)  # 1 L, current bucket now 10
    # Midnight and just before lights-on remain the same grow-day.
    for instant in (datetime(2026, 9, 9, 0), datetime(2026, 9, 9, 9, 59)):
        assert c._water_usage(room, 1, instant)[0] == 10
        assert len(st["water_history"]) == 1
    for day in range(9, 16):
        FixedDateTime.instant = datetime(2026, 9, day, 10)
        c._advance_shot_counters(room, 1, day - 7)  # daily values 2,3,4,5,6,7,8
    total, attrs = c._water_usage(room, 1, FixedDateTime.now())
    assert total == 35  # Sept9..15; Sept8 10L expired
    assert attrs["history_complete"] and attrs["observed_grow_days"] == 7
    assert len(st["water_history"]) == 7
    assert st["daily_vol"] == 45  # water history does not reset the existing daily counter
    c._load_state()
    assert c._water_usage(room, 1, FixedDateTime.now()) == (total, attrs)
    assert room.state[1]["daily_vol"] == 45


def test_weekly_restart_old_state_unattributed_volume_and_missing_days(rig):
    c, _, room, _ = rig
    with open(c._state_path, "w") as file:
        json.dump({"1": {"phase": "P1", "daily_vol": 12, "shots": 4,
                          "last_daily_reset": "2026-09-05"}}, file)
    c._load_state()
    total, attrs = c._water_usage(room, 1, FixedDateTime.now())
    assert total == 0 and attrs["legacy_volume_excluded_l"] == 12
    assert attrs["coverage"] == "partial_history"
    assert room.state[1]["daily_vol"] == 12 and room.state[1]["shots"] == 4
    FixedDateTime.instant = datetime(2026, 9, 11, 12)
    c._advance_shot_counters(room, 1, 3)
    total, attrs = c._water_usage(room, 1, FixedDateTime.now())
    assert total == 3 and attrs["observed_grow_days"] == 2
    assert not attrs["history_complete"]  # missing days never fabricated as recorded zeroes


def test_weekly_rooms_and_disabled_blind_rollover_are_isolated(rig):
    c, fake, room, _ = rig
    other = controller.Room("veg", "veg_", room.zones.copy(), room.hw.copy(),
                            "input_boolean.veg_enabled", "", "", 18, 6)
    other.state = {1: c._fresh_zone()}
    c.rooms.append(other)
    c._advance_shot_counters(room, 1, 2)
    c._advance_shot_counters(other, 1, 7)
    assert other.state[1]["water_history"][0]["grow_day"] == "2026-09-07"
    FixedDateTime.instant = datetime(2026, 9, 9, 10)
    room.state[1]["phase"] = "P3"
    fake.set_state(room.enable_flag, "off")
    pub = c._loop_room(room, FixedDateTime.now())  # no VWC: actual blind reset path
    assert room.state[1]["daily_vol"] == 0
    assert c._water_usage(room, 1, FixedDateTime.now())[0] == 2
    assert c._water_usage(other, 1, FixedDateTime.now())[0] == 7
    c._publish_status(room, pub, FixedDateTime.now())
    assert fake.sets["sensor.crop_steering_zone_1_weekly_water_app"][0] == 2
    c._load_state()
    assert c._water_usage(room, 1, FixedDateTime.now())[0] == 2
    assert c._water_usage(other, 1, FixedDateTime.now())[0] == 7


def test_aborted_shot_records_only_delivered_volume_in_weekly_total(rig, monkeypatch):
    c, fake, room, clock = rig
    def partial_wait(_room, _zone, _duration, started=None):
        clock["seconds"] += 2
        return 2, True
    monkeypatch.setattr(c, "_wait_shot", partial_wait)
    c._execute_shot(room, 1, 10, 10)
    assert room.state[1]["daily_vol"] == pytest.approx(2)
    assert c._water_usage(room, 1, FixedDateTime.now())[0] == 2
    assert any("partial volume counted" in data.get("message", "") for _, _, data in fake.calls)


@pytest.mark.parametrize("month", [1, 9])
def test_last_irrigation_publication_includes_event_local_offset_without_state_migration(
    rig, month
):
    c, fake, room, _ = rig
    event = datetime(2026, month, 8, 10, 30)
    room.state[1]["last_shot"] = event
    probe(fake, "sensor.crop_steering_vwc_zone_1", "60")
    probe(fake, "sensor.crop_steering_ec_zone_1", "3")
    fake.set_state(room.enable_flag, "off")
    pub = c._loop_room(room, FixedDateTime.now())
    c._publish_status(room, pub, FixedDateTime.now())
    encoded, attrs = fake.sets["sensor.crop_steering_zone_1_last_irrigation_app"]
    actual = datetime.fromisoformat(encoded)
    expected = event.astimezone()
    assert actual.tzinfo is not None
    assert actual.utcoffset() == expected.utcoffset()
    assert actual.timestamp() == expected.timestamp()
    assert attrs["device_class"] == "timestamp"
    assert room.state[1]["last_shot"] is event
    assert event.tzinfo is None
