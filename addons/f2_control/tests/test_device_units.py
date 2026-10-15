"""Every number the irrigation loop reads from a device goes through the one device-unit table.

The integration converted a probe's unit and the controller mostly did not: a zone EC probe in uS/cm,
a moisture probe in m3/m3 and a sump plug in kW were each read as if they were mS/cm, % and W. A kW plug
never read above 20, so CS-311 said the sump pump had stopped while it ran. Now one helper (_device)
reads each device and converts its reading with the table; a reading in a unit the table refuses, or in
an unknown unit and implausible, is set aside. Nothing new holds water: a zone whose only moisture probe
is set aside takes the dead-probe path it always took, and says why (CS-503).
"""
import sys
from datetime import timedelta

import pytest

import controller
from test_plan_hold_never_stops_rescues import Clock, probe, rig  # noqa: F401 (rig: a pytest fixture)

EC1, VWC1, VWC2 = "sensor.crop_steering_ec_zone_1", "sensor.crop_steering_vwc_zone_1", "sensor.crop_steering_vwc_zone_2"
SUMP = "sensor.sump_plug_power"
FEED_EC, FEED_PH, RAW2 = "sensor.feed_ec", "sensor.feed_ph", "sensor.zone_2_raw_moisture"
RAW1 = "sensor.zone_1_raw_moisture"


def _now():
    return Clock.now(controller.timezone.utc).isoformat()


def _notices(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if "unit: " in line]


# ---------------------------------------------------------------- the zone and feed probes
def test_a_moisture_probe_in_cubic_metres_per_cubic_metre_reads_as_a_percentage(rig):  # noqa: F811
    c, fake, _room = rig
    fake.set_state(RAW2, "0.45", {"unit_of_measurement": "m³/m³"}, last_updated=_now())
    assert c._read_sensor(RAW2, "vwc") == pytest.approx(45.0)  # was 0.45 %: bone dry


def test_a_zone_ec_probe_in_microsiemens_reads_as_millisiemens(rig):  # noqa: F811
    c, fake, _room = rig
    fake.set_state(EC1, "3100", {"unit_of_measurement": "µS/cm"}, last_updated=_now())
    assert c._read_sensor(EC1, "ec") == pytest.approx(3.1)  # was set aside as out of range


def test_an_ec_probe_in_ppm_is_set_aside_and_its_zone_runs_without_ec(rig):  # noqa: F811
    c, fake, room = rig
    probe(fake, 1, 50)
    fake.set_state(EC1, "4.0", {"unit_of_measurement": "ppm"}, last_updated=_now())  # read raw as 4 mS/cm before
    assert c._read_sensor(EC1, "ec") is None
    snap, _params = c._snapshot(room, 1, Clock.now(), True, False)
    assert snap.vwc == 50 and snap.ec is None  # moisture steers on; EC sizing and learning pause (CS-104)


def test_a_unitless_feed_ph_and_a_feed_ec_in_microsiemens_read_as_before(rig):  # noqa: F811
    c, fake, room = rig
    room.feed_ec_sensor, room.feed_ph_sensor = FEED_EC, FEED_PH
    fake.set_state(FEED_EC, "2200", {"unit_of_measurement": "μS/cm"}, last_updated=_now())
    fake.set_state(FEED_PH, "5.9", {}, last_updated=_now())
    assert c._read_feed_ec(room) == pytest.approx(2.2) and c._read_feed_ph(room) == 5.9


def _read_feed_3_11_1(state):
    """3.11.1's feed-EC read, written out: uS/cm divided by 1000, every other unit taken as mS/cm, 0-20."""
    f = float(state)
    return f if 0 <= f <= 20 else None


@pytest.mark.parametrize("unit", ["ppm", "ppt"])
@pytest.mark.parametrize("reading", ["1.2", "800"])
def test_a_feed_probe_in_a_refused_unit_is_read_as_before_and_never_newly_holds(
    rig, capsys, unit, reading  # noqa: F811
):
    """A zone probe in ppm is set aside and its zone runs without EC; the feed probe feeds a gate that
    holds when it is dead, so setting it aside would stop a room that waters. It reads as 3.11.1 read it."""
    c, fake, room = rig
    capsys.readouterr()
    room.feed_ec_sensor = FEED_EC
    for key, value in {"irrigation_ec_min": 0.5, "irrigation_ec_max": 4}.items():
        fake.set_state(f"number.crop_steering_{key}", str(value))
    fake.set_state(FEED_EC, reading, {"unit_of_measurement": unit}, last_updated=_now())
    assert room._feed_last_good_time is None  # no grace left to hide a dead probe
    assert c._read_feed_ec(room) == _read_feed_3_11_1(reading)
    blocked = c._blocked(room, 1) or ""
    if reading == "1.2":
        assert "source-water EC" not in blocked  # in its band: the room waters, as at 3.11.1
        [notice] = _notices(capsys)
        assert FEED_EC in notice and f"'{unit}'" in notice and "as it always was" in notice
    else:
        assert "source-water EC dead" in blocked  # 800 was no reading at 3.11.1 either


def test_an_unknown_label_is_read_as_a_percentage_while_plausible_and_said_once(rig, capsys):  # noqa: F811
    c, fake, _room = rig
    capsys.readouterr()
    fake.set_state(RAW2, "45", {"unit_of_measurement": "pct"}, last_updated=_now())
    assert c._read_sensor(RAW2, "vwc") == 45.0
    assert c._read_sensor(RAW2, "vwc") == 45.0
    [notice] = _notices(capsys)
    assert RAW2 in notice and "'pct'" in notice and "read as %" in notice


def test_a_unitless_moisture_reading_is_taken_as_a_percentage_never_guessed_from_its_size(rig):  # noqa: F811
    c, fake, _room = rig
    fake.set_state(RAW2, "0.45", {}, last_updated=_now())
    assert c._read_sensor(RAW2, "vwc") == 0.45  # as at 3.11.1: only a probe that says m³/m³ is converted
    fake.set_state(RAW2, "450", {}, last_updated=_now())
    assert c._read_sensor(RAW2, "vwc") is None
    assert c._unreadable(RAW2)[0] == "CS-103"  # out of range, exactly as before
    fake.set_state(RAW2, "1250", {"unit_of_measurement": "mV"}, last_updated=_now())
    code, why = c._unreadable(RAW2)
    assert code == "CS-503" and "1250" in why and "'mV'" in why


# ---------------------------------------------------------------- the dead-probe path, unchanged
def _decisions(c, room, monkeypatch):
    """What the loop decided for each zone, without acting on it."""
    seen = {}

    def act(room, zone, p, snap, decision, block, lights_on, now):
        fire, size, reason = decision
        seen[zone] = (fire, size, getattr(reason, "kind", reason))

    monkeypatch.setattr(c, "_act_zone", act)
    c._loop_room(room, Clock.now())
    return seen


def _blind_zone_1(fake, cause):
    """Zone 1's moisture probe unusable: unavailable (a dead probe, the path 3.11.1 already had), or reporting
    a voltage, set aside for its unit by the integration, whose zone reading then says so."""
    if cause == "dead":
        fake.set_state(VWC1, "unavailable", {}, last_updated=_now())
    else:
        fake.set_state(VWC1, "unknown", {
            "unit_of_measurement": "%", "probes": 1, "used": [], "spread": None,
            "excluded": {RAW1: "set aside for its unit"}, "unit_set_aside": {RAW1: "mV"},
        }, last_updated=_now())


@pytest.mark.usefixtures("no_blind_grace")
@pytest.mark.parametrize("cause", ["dead", "unit"])
@pytest.mark.parametrize("sibling", [True, False])
@pytest.mark.parametrize("since_shot_min", [30, 120])
def test_a_probe_set_aside_for_its_unit_takes_exactly_the_dead_probe_path(
    rig, monkeypatch, cause, sibling, since_shot_min  # noqa: F811
):
    c, fake, room = rig
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=Clock.now() - timedelta(minutes=since_shot_min))
    _blind_zone_1(fake, cause)
    if sibling:
        probe(fake, 2, 30)  # dry: the working zone wants a shot
    else:
        fake.set_state(VWC2, "unavailable", {}, last_updated=_now())
    decided = _decisions(c, room, monkeypatch)
    # The table: the same row whatever made the probe unusable.
    if sibling:
        assert decided[1] == (decided[2][0], decided[2][1], "blind_copy")
    else:
        p2_shot = c._params(room, 1).p2_shot_size
        assert decided[1] == (since_shot_min >= c.blind_fallback_min, p2_shot, "blind_fallback")
    card = [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and d["notification_id"] == "f2_blind_default_z1"]
    assert card and card[-1]["title"].endswith("(CS-503)" if cause == "unit" else "(CS-102)")
    if cause == "unit":
        assert f"{RAW1} (in 'mV')" in card[-1]["message"] and f"Sensor: {VWC1}" in card[-1]["message"]


@pytest.mark.usefixtures("no_blind_grace")
def test_a_zone_whose_only_probe_is_set_aside_is_still_watered_on_the_timer(rig):  # noqa: F811
    c, fake, room = rig
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=Clock.now() - timedelta(hours=3))
    fake.set_state(VWC1, "1250", {"unit_of_measurement": "mV"}, last_updated=_now())
    fake.set_state(VWC2, "1250", {"unit_of_measurement": "mV"}, last_updated=_now())
    c._loop_room(room, Clock.now())
    opened = [d["entity_id"] for dom, svc, d in fake.calls if (dom, svc) == ("switch", "turn_on")]
    assert "switch.v1" in opened  # no new hold: the timer waters it within its daily limit


# ---------------------------------------------------------------- the sump plug (CS-311)
def _sump(c, fake, monkeypatch, rows, unit, state="0"):
    c.sump_sensors = {"*": SUMP}
    fake.set_state(SUMP, state, {} if unit is None else {"unit_of_measurement": unit})
    monkeypatch.setattr(controller, "ha_history", lambda entity, since, timeout=12: rows)
    c._watch_sump(c.rooms[0], Clock.now())
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and d["notification_id"] == "f2_sump_default"]


def test_a_plug_in_kilowatts_counts_a_50_watt_run(rig, monkeypatch):  # noqa: F811
    c, fake, _room = rig
    assert _sump(c, fake, monkeypatch, [("0", "a"), ("0.05", "b"), ("0", "c")], "kW") == []


def test_a_plug_in_kilowatts_that_never_ran_is_still_caught(rig, monkeypatch):  # noqa: F811
    c, fake, _room = rig
    assert len(_sump(c, fake, monkeypatch, [("0", "a"), ("0.002", "b")], "kW")) == 1  # 2 W: no run


@pytest.mark.parametrize("reading,ran", [("25000", True), ("15000", False)])
def test_a_plug_in_milliwatts_is_compared_in_watts(rig, monkeypatch, reading, ran):  # noqa: F811
    c, fake, _room = rig
    assert (_sump(c, fake, monkeypatch, [("0", "a"), (reading, "b")], "mW") == []) is ran


def test_an_unavailable_plug_is_read_in_the_unit_it_last_reported(rig, monkeypatch):  # noqa: F811
    c, fake, _room = rig
    fake.set_state(SUMP, "0", {"unit_of_measurement": "kW"})
    c._device(SUMP, "power")  # read while it reports
    fake.set_state(SUMP, "unavailable", {})
    c.sump_sensors = {"*": SUMP}
    monkeypatch.setattr(controller, "ha_history", lambda entity, since, timeout=12: [("0", "a"), ("0.4", "b")])
    c._watch_sump(c.rooms[0], Clock.now())
    assert not any(d.get("notification_id") == "f2_sump_default" for _dom, _svc, d in fake.calls)


def test_a_unitless_plug_is_read_in_watts_and_said_once(rig, monkeypatch, capsys):  # noqa: F811
    c, fake, _room = rig
    capsys.readouterr()
    assert _sump(c, fake, monkeypatch, [("0", "a"), ("30", "b")], None) == []
    [notice] = _notices(capsys)
    assert SUMP in notice and "read as W" in notice


def test_a_plug_reading_set_aside_for_its_unit_is_no_evidence_either_way(rig, monkeypatch):  # noqa: F811
    c, fake, _room = rig
    assert _sump(c, fake, monkeypatch, [("0", "a"), ("50000", "b")], "VA") == []  # not W, and no sane W
    assert not any(svc == "dismiss" for _dom, svc, _d in fake.calls)


ROWS = [
    [("0", "a"), ("412", "b"), ("0", "c")],
    [("0", "a"), ("unavailable", "b"), ("0", "c")],
    [("20", "a"), ("19.9", "b")],
    [("20.1", "a")],
    [("unknown", "a")],
    [("-5", "a"), ("0", "b")],
    [("nan", "a"), ("0", "b")],
    [("inf", "a")],
]


def _ran_3_11_1(rows):
    """3.11.1's _watch_sump verdict, written out: any row whose float is over 20."""
    ran = False
    for state, _changed in rows:
        try:
            ran = ran or float(state) > 20.0
        except (TypeError, ValueError):
            continue
    return ran


@pytest.mark.parametrize("rows", ROWS)
def test_a_plug_in_watts_gives_the_verdicts_it_always_did(rig, monkeypatch, rows):  # noqa: F811
    c, fake, _room = rig
    assert (_sump(c, fake, monkeypatch, rows, "W") == []) is _ran_3_11_1(rows)


# ---------------------------------------------------------------- no device read skips the table
ALLOWED = {
    "ha_get": {"_device", "_fused_id", "_detect_zones"},  # the last two only ask whether the entity exists
    "ha_history": {"_device_history"},
}


def _spy(monkeypatch, devices):
    """Record which function fetched each device entity, for every ha_get and ha_history from now on."""
    fetched = []
    for name in ALLOWED:
        real = getattr(controller, name)

        def spy(entity, *args, _real=real, _name=name, **kwargs):
            if entity in devices:
                fetched.append((entity, _name, sys._getframe(1).f_code.co_name))
            return _real(entity, *args, **kwargs)

        monkeypatch.setattr(controller, name, spy)
    return fetched


def _bypasses(fetched):
    return [row for row in fetched if row[2] not in ALLOWED[row[1]]]


@pytest.mark.usefixtures("no_blind_grace")
def test_every_device_read_in_a_loop_goes_through_the_unit_table(rig, monkeypatch):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    room.feed_ec_sensor, room.feed_ph_sensor = FEED_EC, FEED_PH
    room.zones[2]["vwc"] = RAW2  # a probe mapped to the zone by hand, read directly
    c.sump_sensors = {"*": SUMP}
    for key, value in {"irrigation_ec_min": 1, "irrigation_ec_max": 4,
                       "irrigation_ph_min": 5, "irrigation_ph_max": 7}.items():
        fake.set_state(f"number.crop_steering_{key}", str(value))
    stamp = _now()
    fake.set_state(FEED_EC, "2.2", {"unit_of_measurement": "mS/cm"}, last_updated=stamp)
    fake.set_state(FEED_PH, "5.9", {"unit_of_measurement": "pH"}, last_updated=stamp)
    fake.set_state(RAW2, "0.31", {"unit_of_measurement": "m³/m³"}, last_updated=stamp)
    fake.set_state(SUMP, "0.4", {"unit_of_measurement": "kW"})
    fake.history[SUMP] = [("0", "a"), ("0.4", "b")]
    probe(fake, 1, 30)  # dry, in P2 and three hours since its last shot: a shot is due, so the gate is read
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=now - timedelta(hours=3))
    devices = {VWC1, EC1, "sensor.crop_steering_ec_zone_2", RAW2, FEED_EC, FEED_PH, SUMP}
    monkeypatch.setattr(controller, "ha_history", fake.ha_history)
    fetched = _spy(monkeypatch, devices)
    c.loop_once(now)
    assert _bypasses(fetched) == []
    through = {entity for entity, _name, caller in fetched if caller in ("_device", "_device_history")}
    assert through == devices  # every device was read, and only through the table


def test_the_guard_catches_a_read_that_skips_the_table(monkeypatch):
    fetched = _spy(monkeypatch, {SUMP})
    controller.ha_get(SUMP)  # a new code path reading the plug straight from Home Assistant
    assert _bypasses(fetched) == [(SUMP, "ha_get", "test_the_guard_catches_a_read_that_skips_the_table")]
