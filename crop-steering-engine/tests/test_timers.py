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
