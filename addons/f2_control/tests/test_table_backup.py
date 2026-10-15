"""CS-310: a zone's moisture rising while no water goes in is a table that isn't draining.

On 29 Sep 2026 F2 Zone 2 climbed from 37 % to 71 % in a day with one shot: its slabs were sitting in runoff from
a sump that had stopped. Nothing said so. The controller now watches every zone's reading against its valve: a
rise of BACKUP_RISE_PTS within BACKUP_WINDOW_MIN, with the valve shut for that time and the BACKUP_GRACE_MIN
before it, raises CS-310 (critical) and holds the zone's daily minimum, which waters whatever the probe reads and
would otherwise pour more into a flooded table.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import controller
import pytest
from crop_steering_engine.defaults import ENTITY_DEFAULTS
from test_plan_hold_never_stops_rescues import Clock, probe, rig  # noqa: F401 (rig: a pytest fixture)

T0 = Clock(2026, 9, 23, 14, 0)  # the rig pins the controller's clock to Clock: times are Clocks
RISING = [(m, 36.6 + 0.07 * m) for m in range(0, 61, 5)]  # +4.2 points in an hour, as Zone 2 on 29 Sep


def feed(c, room, points, start=T0, zone=1):
    """Readings [(minute, vwc)] from `start`, one loop each -> what the last loop said."""
    held = None
    for minute, vwc in points:
        Clock.instant = Clock.fromtimestamp((start + timedelta(minutes=minute)).timestamp())
        held = c._watch_backup(room, zone, SimpleNamespace(vwc=vwc), Clock.instant)
    return held


def cards(fake, zone=1):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and d["notification_id"] == f"f2_backup_default_z{zone}"]


def settled(c, room, last_shot=Clock(2026, 9, 23, 11, 0)):
    c._start = T0 - timedelta(hours=2)  # running long enough to know the valves
    room.state[1]["last_shot"] = last_shot


def test_moisture_rising_with_no_water_is_a_table_not_draining(rig):  # noqa: F811
    c, fake, room = rig
    settled(c, room)
    assert feed(c, room, RISING) is True
    [card] = cards(fake)
    assert card["title"] == "Zone 1: moisture rising with no water: the table is not draining (CS-310)"
    # said as soon as the rise reaches 3 points: 36.6 to 39.8 in 45 minutes
    assert "Moisture went from 36.6 to 39.8 % in the last 45 minutes" in card["message"]
    assert "no water since 11:00" in card["message"] and "sump pump" in card["message"]
    assert "CS-310" in controller.CRITICAL_CODES  # an emergency: a high-priority push


def test_water_that_went_in_explains_a_rise(rig):  # noqa: F811
    c, fake, room = rig
    settled(c, room)
    fake.set_state("switch.v1", "on")  # opened by hand at minute 20: the rise is that water
    feed(c, room, RISING[:5])
    fake.set_state("switch.v1", "off")
    assert feed(c, room, RISING[5:]) is False and cards(fake) == []


def test_a_shots_own_wetting_front_is_never_counted(rig):  # noqa: F811
    c, fake, room = rig
    settled(c, room, last_shot=Clock(2026, 9, 23, 14, 20))  # the controller's shot, part-way through
    assert feed(c, room, RISING) is False and cards(fake) == []


def test_a_small_rise_is_not_one(rig):  # noqa: F811
    c, fake, room = rig
    settled(c, room)
    assert feed(c, room, [(m, 36.6 + 0.04 * m) for m in range(0, 61, 5)]) is False  # +2.4 in an hour


def test_right_after_a_restart_it_waits_to_know_the_valves(rig):  # noqa: F811
    c, fake, room = rig
    settled(c, room)
    c._start = T0 - timedelta(minutes=10)  # a valve opened just before the restart is not known
    assert feed(c, room, RISING) is False and cards(fake) == []


def test_it_clears_an_hour_after_the_reading_stops_rising_and_the_minimum_comes_back(rig):  # noqa: F811
    c, fake, room = rig
    settled(c, room)
    assert feed(c, room, RISING) is True
    # The reading stops at 40.8; the rise leaves the hour's window by 80 minutes, and an hour after that it clears.
    assert feed(c, room, [(m, 40.8) for m in range(65, 91, 5)]) is True
    assert feed(c, room, [(m, 40.8) for m in range(95, 141, 5)]) is False
    assert any((dom, svc, d.get("notification_id")) == ("persistent_notification", "dismiss", "f2_backup_default_z1")
               for dom, svc, d in fake.calls)
    assert "backup_default_z1" not in c._alerted


def test_a_backed_up_zone_gets_no_daily_minimum(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    fake.set_state("input_number.crop_steering_zone_1_min_daily_ml_per_plant", "500")  # 21 L for 42 plants
    for zone in (1, 2):
        probe(fake, zone, 50)
        room.state[zone].update(phase="P2", last_shot=now - timedelta(minutes=30), last_daily_reset=date(2026, 9, 23))
    room._backed_up = {1: now}
    pub = c._loop_room(room, now)
    assert not pub[1]["fire"]
    del room._backed_up[1]
    Clock.instant = now = now + timedelta(minutes=11)
    probe(fake, 1, 50)
    probe(fake, 2, 50)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and pub[1]["reason"].kind == "min_daily"  # the same zone, not held


def test_a_backed_up_zone_gets_no_ec_flush(rig):  # noqa: F811
    # Flushes no longer wait for the reading to drop under field capacity - 2 (5 Oct 2026, F2 Zone 2 read 70 against
    # 54 and got none); what stops one is this hold: a flush poured into a table that isn't draining floods it.
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    for zone in (1, 2):
        probe(fake, zone, 50, ec=10.0)  # over max_ec 9, feed 3: the anti-lockout flush is due
        room.state[zone].update(phase="P2", last_shot=now - timedelta(minutes=60), last_daily_reset=date(2026, 9, 23))
    room._backed_up = {1: now}
    pub = c._loop_room(room, now)
    assert not pub[1]["fire"] and "table not draining" in pub[1]["reason"]
    assert pub[2]["fire"] and pub[2]["reason"].kind == "flush_high_ec"  # the zone that drains is flushed


# ------------------------------------------------------------------ CS-311, the sump pump standing still
SUMP = "sensor.f2_sump_pump_power"


def sump_cards(fake):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and d["notification_id"] == "f2_sump_default"]


def sump_history(monkeypatch, rows):
    """What Home Assistant's history says of the sump's power since `since` -> the queries made."""
    asked = []

    def history(entity, since, timeout=12):
        asked.append((entity, since))
        return rows[0]

    monkeypatch.setattr(controller, "ha_history", history)
    return asked


def test_a_sump_pump_that_has_stood_still_for_three_hours_is_critical(rig, monkeypatch):  # noqa: F811
    c, fake, room = rig
    c.sump_sensors = {"*": SUMP}
    rows = [[("0", "2026-09-23T00:00:00+00:00"), ("unavailable", "x"), ("0", "y")]]  # a restart in between
    asked = sump_history(monkeypatch, rows)
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    c._watch_sump(room, now)
    [card] = sump_cards(fake)
    assert card["title"] == "The sump pump has not run (CS-311)" and f"Sensor: {SUMP}" in card["message"]
    assert asked == [(SUMP, Clock.now(controller.timezone.utc) - timedelta(hours=3))]
    assert "CS-311" in controller.CRITICAL_CODES
    Clock.instant = now + timedelta(minutes=4)
    c._watch_sump(room, Clock.instant)
    assert len(asked) == 1  # read every five minutes: a run lasts about a minute, history keeps it
    rows[0] = [("0", "a"), ("412", "b"), ("0", "c")]  # it ran
    Clock.instant = now + timedelta(minutes=5)
    c._watch_sump(room, Clock.instant)
    assert any((dom, svc, d.get("notification_id")) == ("persistent_notification", "dismiss", "f2_sump_default")
               for dom, svc, d in fake.calls)
    assert len(sump_cards(fake)) == 1 and "sump_default" not in c._alerted


def test_no_evidence_says_nothing_and_an_unset_sensor_is_never_read(rig, monkeypatch):  # noqa: F811
    c, fake, room = rig
    asked = sump_history(monkeypatch, [None])
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    c._watch_sump(room, now)
    assert asked == []  # no sump_power_sensor option
    c.sump_sensors = {"f1": SUMP}  # another room's
    c._watch_sump(room, now)
    assert asked == []
    c.sump_sensors = {"default": SUMP}
    c._watch_sump(room, now)
    assert len(asked) == 1 and sump_cards(fake) == []  # Home Assistant could not say


def test_the_loop_watches_the_sump(rig, monkeypatch):  # noqa: F811
    c, fake, room = rig
    c.sump_sensors = {"*": SUMP}
    asked = sump_history(monkeypatch, [[("0", "a"), ("405", "b")]])
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    for zone in (1, 2):
        probe(fake, zone, 50)
        room.state[zone].update(phase="P2", last_shot=now - timedelta(minutes=30))
    c._loop_room(room, now)
    assert asked and sump_cards(fake) == []


def test_the_option_takes_one_sensor_or_room_pairs():
    assert controller.room_option("") == {}
    assert controller.room_option(SUMP) == {"*": SUMP}
    assert controller.room_option(f"default={SUMP}, f1=sensor.f1_sump_power") == {
        "default": SUMP, "f1": "sensor.f1_sump_power"}


# ------------------------------------------------------------------ the room's drainage
DRAINAGE = "select.crop_steering_drainage"


@pytest.mark.parametrize("drainage", [None, "unknown", "flood_table"])
def test_a_room_on_tables_or_that_has_not_said_is_watched_as_before(rig, drainage):  # noqa: F811
    c, fake, room = rig
    if drainage:
        fake.set_state(DRAINAGE, drainage)  # None: an integration from before the select
    settled(c, room)
    assert feed(c, room, RISING) is True and len(cards(fake)) == 1


def test_a_free_draining_room_is_never_held_for_a_table_backing_up(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state(DRAINAGE, "free_drain")
    settled(c, room)
    assert feed(c, room, RISING) is False and cards(fake) == []


def test_saying_the_room_drains_freely_clears_a_card_it_had(rig):  # noqa: F811
    c, fake, room = rig
    settled(c, room)
    assert feed(c, room, RISING) is True
    fake.set_state(DRAINAGE, "free_drain")
    assert feed(c, room, [(65, 41.2)]) is False  # at once, not an hour later
    assert any((dom, svc, d.get("notification_id")) == ("persistent_notification", "dismiss", "f2_backup_default_z1")
               for dom, svc, d in fake.calls)
    assert "backup_default_z1" not in c._alerted


def test_a_free_draining_room_gets_its_ec_flush(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state(DRAINAGE, "free_drain")
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    for zone in (1, 2):
        probe(fake, zone, 50, ec=10.0)
        room.state[zone].update(phase="P2", last_shot=now - timedelta(minutes=60), last_daily_reset=date(2026, 9, 23))
    room._backed_up = {1: now}  # held before the room said it drains freely
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and pub[1]["reason"].kind == "flush_high_ec"


# ------------------------------------------------------------------ the sump pump's run threshold
THRESHOLD = "number.crop_steering_sump_power_threshold_w"


def stopped(c, fake, monkeypatch, room, unit, rows):
    """Whether CS-311 says the sump pump has not run, its plug reporting in `unit`."""
    c.sump_sensors = {"*": SUMP}
    fake.set_state(SUMP, rows[-1][0], {"unit_of_measurement": unit})
    sump_history(monkeypatch, [rows])
    room._sump_checked = None  # a fresh check, and a card said afresh
    c._alerted.pop("sump_default", None)
    fake.calls.clear()
    c._watch_sump(room, Clock.instant)
    return bool(sump_cards(fake))


def test_the_threshold_is_compared_in_watts(rig, monkeypatch):  # noqa: F811
    c, fake, room = rig
    Clock.instant = Clock(2026, 9, 23, 14, 0)
    fake.set_state(THRESHOLD, "10")
    assert stopped(c, fake, monkeypatch, room, "kW", [("0", "a"), ("0.015", "b"), ("0", "c")]) is False  # 15 W
    assert stopped(c, fake, monkeypatch, room, "kW", [("0", "a"), ("0.005", "b"), ("0", "c")]) is True  # 5 W
    fake.set_state(THRESHOLD, "50")
    assert stopped(c, fake, monkeypatch, room, "W", [("0", "a"), ("30", "b"), ("0", "c")]) is True


@pytest.mark.parametrize("threshold", [None, "unavailable", "unknown", ""])
def test_without_a_readable_threshold_it_is_the_20_w_it_always_was(rig, monkeypatch, threshold):  # noqa: F811
    c, fake, room = rig
    Clock.instant = Clock(2026, 9, 23, 14, 0)
    if threshold is not None:  # None: an integration from before the setting
        fake.set_state(THRESHOLD, threshold)
    assert stopped(c, fake, monkeypatch, room, "W", [("0", "a"), ("15", "b"), ("0", "c")]) is True
    assert stopped(c, fake, monkeypatch, room, "W", [("0", "a"), ("25", "b"), ("0", "c")]) is False


def test_a_new_rooms_threshold_starts_where_the_controller_falls_back():
    assert ENTITY_DEFAULTS["sump_power_threshold_w"] == controller.SUMP_RUN_W == 20
