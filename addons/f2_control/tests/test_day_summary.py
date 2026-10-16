"""Grow-day summaries (day_summary.py): measured through the grow-day while the room's Record grow days switch is on,
closed at lights-on, sent to Home Assistant in one call, kept until it takes them, and never anything with the switch
off. A state file from before them loads with them empty."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

import controller
import day_summary
import fake_ha

pytestmark = pytest.mark.usefixtures("settings_built_in")

SWITCH = "switch.crop_steering_record_grow_days"
PROBES = ("sensor.front_vwc", "sensor.back_vwc")


class Clock(datetime):
    instant = None

    @classmethod
    def now(cls, tz=None):
        return cls.instant.replace(tzinfo=tz) if tz else cls.instant


class Monotonic:
    seconds = 0.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


@pytest.fixture
def rig(monkeypatch, tmp_path):
    Clock.instant = Clock(2026, 9, 22, 11, 0)  # lights 10-22
    monkeypatch.setattr(controller, "datetime", Clock)
    fake = fake_ha.FakeHA()
    options = {"num_zones": 1, "hardware": {"pump": "switch.p", "valves": {"1": "switch.v1"}},
               "enable_flag": "input_boolean.kill"}
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_get_status", "ha_call", "ha_get_all", "ha_set", "ha_service_response"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in ("input_boolean.kill", "switch.crop_steering_zone_1_enabled"):
        fake.set_state(eid, "on")
    for eid in ("switch.p", "switch.v1"):
        fake.set_state(eid, "off")
    for key, value in {"plant_count": 10, "substrate_volume": 5, "drippers_per_plant": 1,
                       "dripper_flow_rate": 4, "max_daily_volume": 60}.items():
        fake.set_state(f"number.crop_steering_{key}", str(value))
    clock = Monotonic()
    monkeypatch.setattr(controller.time, "sleep", clock.sleep)
    monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
    room = c.rooms[0]
    room.state[1].update(phase="P2", last_daily_reset=date(2026, 9, 22))
    return c, fake, room


def read(fake, vwc, ec=5.0, front=None, back=None):
    stamp = Clock.now(timezone.utc).isoformat()
    fake.set_state("sensor.crop_steering_vwc_zone_1", str(vwc),
                   {"used": list(PROBES), "excluded": {}}, last_updated=stamp)
    fake.set_state("sensor.crop_steering_ec_zone_1", str(ec), last_updated=stamp)
    fake.set_state(PROBES[0], str(front if front is not None else vwc),
                   {"friendly_name": "Row 1 front", "unit_of_measurement": "%"})
    fake.set_state(PROBES[1], str(back if back is not None else vwc), {"friendly_name": "Row 1 back"})


def sent(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("crop_steering", "grow_day_record")]


def run_day(c, fake, room):
    """Grow-day 22 Sep: three readings, the last under the re-water point (a top-up fires), then the next
    lights-on."""
    for hour, vwc, front in ((11, 50.0, 51.0), (15, 46.0, 47.5), (21, 44.0, 44.5)):
        Clock.instant = Clock(2026, 9, 22, hour, 0)
        read(fake, vwc, front=front)
        c._loop_room(room, Clock.now())
    room.fed = room.state[1]["daily_vol"]
    Clock.instant = Clock(2026, 9, 23, 10, 5)
    read(fake, 43.0)
    room._was_lights_on = False
    c._loop_room(room, Clock.now())


def test_with_the_switch_off_nothing_is_measured_or_sent(rig):
    c, fake, room = rig
    run_day(c, fake, room)
    assert room.state[1]["day_acc"] is None and room.state[1]["day_out"] == []
    assert sent(fake) == []


def test_the_grow_day_is_summarised_at_lights_on_and_sent_in_one_call(rig):
    c, fake, room = rig
    fake.set_state(SWITCH, "on")
    run_day(c, fake, room)
    assert room.state[1]["phase"] == "P0"
    (call,) = sent(fake)
    assert call["room_id"] == "room:"
    (day,) = call["days"]
    assert day["date"] == "2026-09-22" and day["zone"] == 1 and day["partial"] is False
    assert day["vwc"] == {"peak": 50.0, "trough": 44.0, "mean": pytest.approx((50 + 46 + 44) / 3, abs=1e-3)}
    assert day["ec"]["mean"] == 5.0
    assert day["shots"] == {"topup": 1} and room.fed > 0
    assert day["litres"] == round(room.fed, 3) and day["shot_litres"] == {"topup": round(room.fed, 3)}
    assert day["litres_per_plant"] == round(room.fed / 10, 4)
    assert day["plant_count"] == 10 and day["mode"] == "Generative" and day["lights"] == {"on": 10.0, "off": 22.0}
    assert day["targets"]["max_daily_volume"] == 60
    front = next(p for p in day["probes"] if p["entity_id"] == PROBES[0])
    assert front["name"] == "Row 1 front" and front["unit"] == "%" and front["peak"] == 51.0 and front["used_share"] == 1
    assert room.state[1]["day_out"] == []  # taken
    json.dumps(call)  # what goes over REST


def test_summaries_home_assistant_does_not_take_wait_across_a_restart(rig, monkeypatch):
    c, fake, room = rig
    fake.set_state(SWITCH, "on")
    monkeypatch.setattr(controller, "ha_service_response", lambda *a, **k: (400, None))
    run_day(c, fake, room)
    assert [s["date"] for s in room.state[1]["day_out"]] == ["2026-09-22"]
    c._save_state()
    c._load_state()
    assert [s["date"] for s in room.state[1]["day_out"]] == ["2026-09-22"]
    monkeypatch.setattr(controller, "ha_service_response", fake.ha_service_response)
    Clock.instant += timedelta(minutes=11)
    read(fake, 43.0)
    c._loop_room(room, Clock.now())
    assert [d["date"] for d in sent(fake)[-1]["days"]] == ["2026-09-22"] and room.state[1]["day_out"] == []


def test_an_old_state_file_loads_with_no_summary_and_a_damaged_one_is_dropped(rig):
    c, fake, room = rig
    with open(c._state_path, "w") as fh:
        json.dump({"default": {"1": {"phase": "P2", "daily_vol": 3}}}, fh)
    c._load_state()
    assert room.state[1]["day_acc"] is None and room.state[1]["day_out"] == []
    with open(c._state_path, "w") as fh:
        json.dump({"default": {"1": {"day_acc": {"day": "junk"}, "day_out": [{"date": "x"}, "y"]}}}, fh)
    c._load_state()
    assert room.state[1]["day_acc"] is None and room.state[1]["day_out"] == []


def test_shots_are_counted_by_kind_and_a_day_measured_from_late_is_partial():
    st = day_summary.fresh()
    start = datetime(2026, 9, 22, 10, 0)
    late = start + timedelta(hours=3)
    day_summary.observe(st, day="2026-09-22", now=late, vwc=40, ec=None, stalled=True)
    for kind in ("p1_ramp", "p1_ramp", "p1_extra", "p3_emergency", "watchdog", "p2_dilute", "something_new"):
        day_summary.shot(st, day="2026-09-22", now=late, kind=kind, litres=0.5)
    day_summary.alert(st, "CS-207")
    day_summary.alert(st, "CS-207")
    out = day_summary.close(st, day="2026-09-22", now=late, info={"zone": 2, "day_start": start, "plant_count": 0})
    assert out["shots"] == {"ramp": 2, "extra": 1, "rescue": 2, "dilute": 1, "other": 1}
    assert out["rescues"] == 2 and out["litres"] == 3.5 and out["litres_per_plant"] is None
    assert out["partial"] is True and out["p1_stall"] is True and out["alerts"] == ["CS-207"]
    assert out["ec"] is None and st["day_acc"] is None
