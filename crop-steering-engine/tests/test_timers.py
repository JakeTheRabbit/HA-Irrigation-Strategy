"""Timer programs — pure projection of a program into planned intents. Offline."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from crop_steering_engine.timers import PlannedIntent, project, validate

NZ = ZoneInfo("Pacific/Auckland")
DAY = (datetime(2026, 10, 22, 0, 0, tzinfo=NZ), datetime(2026, 10, 23, 0, 0, tzinfo=NZ))


def _prog(**kw):
    base = {"id": "t", "zones": [1], "type": "recycle", "duration_s": 120, "interval_min": 30,
            "window": {"kind": "custom", "from": "08:00", "to": "12:00"}, "active": True}
    base.update(kw)
    return base


def _hm(got):
    return [i.at.strftime("%H:%M") for i in got]


def test_recycle_0800_to_1200_every_30_min_is_8_shots():
    got = project(_prog(), (6, 18), *DAY)
    assert _hm(got) == ["08:00", "08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]
    assert {i.duration_s for i in got} == {120}
    assert all(isinstance(i, PlannedIntent) and i.program_id == "t" and i.zone == 1 for i in got)


def test_sync_time_shifts_the_first_recycle_shot():
    got = project(_prog(sync_time="08:10"), (6, 18), *DAY)
    assert _hm(got)[0] == "08:10" and _hm(got)[-1] == "11:40" and len(got) == 8


def test_simple_spreads_frequency_evenly_over_lights_on():
    p = _prog(type="simple", frequency_per_day=6, window={"kind": "lights_on"})
    assert _hm(project(p, (6, 18), *DAY)) == ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00"]


def test_one_off_fires_once_inside_range_and_never_outside():
    p = _prog(type="one_off", start_at="2026-10-22T09:15:00+13:00", zones=[1])
    assert _hm(project(p, (6, 18), *DAY)) == ["09:15"]
    assert project(p, (6, 18), datetime(2026, 10, 23, tzinfo=NZ), datetime(2026, 10, 24, tzinfo=NZ)) == []
    # end is exclusive
    assert project(p, (6, 18), DAY[0], datetime(2026, 10, 22, 9, 15, tzinfo=NZ)) == []


def test_lights_off_window_crosses_midnight():
    p = _prog(interval_min=120, window={"kind": "lights_off"})
    got = project(p, (6, 18), *DAY)
    # the 22nd's range sees the previous night's tail (00:00-04:00) and this night's start (18:00-22:00)
    assert _hm(got) == ["00:00", "02:00", "04:00", "18:00", "20:00", "22:00"]
    got2 = project(p, (6, 18), datetime(2026, 10, 22, 18, 0, tzinfo=NZ), datetime(2026, 10, 23, 6, 0, tzinfo=NZ))
    assert _hm(got2) == ["18:00", "20:00", "22:00", "00:00", "02:00", "04:00"]


def test_dst_spring_forward_keeps_interval_on_wall_clock():
    p = _prog(interval_min=60, window={"kind": "custom", "from": "00:00", "to": "06:00"})
    got = project(p, (6, 18), datetime(2026, 9, 27, 0, 0, tzinfo=NZ), datetime(2026, 9, 28, 0, 0, tzinfo=NZ))
    assert _hm(got) == ["00:00", "01:00", "03:00", "04:00", "05:00"]
    assert len({i.at for i in got}) == len(got)


def test_inactive_program_projects_nothing():
    assert project(_prog(active=False), (6, 18), *DAY) == []


def test_one_shot_per_zone_per_slot():
    got = project(_prog(zones=[2, 1]), (6, 18), *DAY)
    assert len(got) == 16
    assert [(i.at.strftime("%H:%M"), i.zone) for i in got[:4]] == [
        ("08:00", 1), ("08:00", 2), ("08:30", 1), ("08:30", 2)]


@pytest.mark.parametrize("bad,msg", [
    ({"window": {"kind": "custom", "from": "08:00", "to": "08:00"}}, "End must be after start"),
    ({"duration_s": 0}, "duration"), ({"interval_min": 0}, "interval"),
    ({"zones": []}, "zone"), ({"type": "x"}, "type")])
def test_validate_refuses(bad, msg):
    with pytest.raises(ValueError, match=msg):
        validate(_prog(**bad))


def test_validate_normalises():
    out = validate(_prog(zones=[1, "2"], duration_s="90"))
    assert out["zones"] == [1, 2] and out["duration_s"] == 90.0 and out["active"] is True


@pytest.mark.parametrize("field", ["duration_s", "interval_min"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), "nan", "-inf"])
def test_validate_refuses_numbers_that_are_not_finite(field, value):
    with pytest.raises(ValueError, match=field.split("_")[0]):
        validate(_prog(**{field: value}))


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_validate_refuses_a_frequency_or_a_zone_that_is_not_finite(value):
    with pytest.raises(ValueError, match="frequency"):
        validate(_prog(type="simple", frequency_per_day=value))
    with pytest.raises(ValueError, match="zones"):
        validate(_prog(zones=[1, value]))


def test_validate_refuses_an_interval_under_a_minute():
    with pytest.raises(ValueError, match="at least 1 minute"):
        validate(_prog(interval_min=0.5))
    assert validate(_prog(interval_min=1))["interval_min"] == 1.0


def test_validate_drops_a_zone_named_twice_keeping_the_order():
    assert validate(_prog(zones=[3, 1, "3", 2, 1]))["zones"] == [3, 1, 2]


def test_validate_refuses_a_sync_time_outside_the_window():
    with pytest.raises(ValueError, match="sync time must be inside the window"):
        validate(_prog(sync_time="13:00"))
    with pytest.raises(ValueError, match="sync time must be inside the window"):
        validate(_prog(sync_time="12:00"))  # the window ends at 12:00, not after it
    assert validate(_prog(sync_time="08:00"))["sync_time"] == "08:00"
    # across midnight: 22:00-02:00 holds 01:00
    assert validate(_prog(sync_time="01:00", window={"kind": "custom", "from": "22:00", "to": "02:00"}))
    # a lights window is checked when the lights are given
    lit = _prog(sync_time="20:00", window={"kind": "lights_on"})
    assert validate(lit)["sync_time"] == "20:00"
    with pytest.raises(ValueError, match="sync time must be inside the window"):
        validate(lit, (6, 18))


def test_a_sync_time_the_lights_moved_away_from_starts_at_the_window_start():
    lit = _prog(sync_time="20:00", interval_min=120, window={"kind": "lights_on"})
    assert _hm(project(lit, (12, 0), *DAY)) == ["20:00", "22:00"]  # as saved
    assert _hm(project(lit, (6, 18), *DAY)) == ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00"]


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_validate_takes_active_only_as_true_or_false(value):
    with pytest.raises(ValueError, match="active must be true or false"):
        validate(_prog(active=value))
    assert validate(_prog(active=False))["active"] is False
    program = _prog()
    del program["active"]
    assert validate(program)["active"] is True


@pytest.mark.parametrize("value", ["all", ["custom"], 3])
def test_validate_names_a_window_that_is_not_an_object(value):
    with pytest.raises(ValueError, match="window must be an object"):
        validate(_prog(window=value))
    assert validate(_prog(window=None))["window"] == {"kind": "all"}
