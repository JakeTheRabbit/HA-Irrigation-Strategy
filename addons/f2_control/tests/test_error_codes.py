"""Every notification carries an error code, names the room and zone the operator's way, and a
zone without a usable moisture reading says which of three different things is wrong.

First real install, after 2.20.3: "default GT4 (Z2) probe dead — blind schedule", "No live VWC at
sensor.crop_steering_vwc_zone_2 and no healthy sibling". The probe was fine; it sat in a cube with
no plant, so its reading never moved. "default" is the controller's internal name for the first
room, and the one sentence covered a missing sensor, an unavailable one, an impossible number and
a reading that has not changed. docs/error-codes.json holds what each code means and what to do;
tests/test_error_codes.py keeps this controller and that catalog in step.
"""
import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import controller
from test_controller import _build, _desc
from test_zone_count import DESCRIPTOR, _room
import pytest

# What happens once a probe is dead; how long it must be out first is test_blind_grace.py.
pytestmark = pytest.mark.usefixtures("no_blind_grace")

NOW = datetime(2026, 9, 21, 14, 0, 0)
OPTIONS = {"num_zones": 3, "enable_flag": "input_boolean.f2_control_enabled"}
FOOTER = "Code {}. What it means and what to do: Crop Steering → Help & tools → Error codes."


def _alerts(states, options=OPTIONS):
    c, fake = _build(dict(options), states=states)
    c.loop_once(NOW)
    return c, {d["notification_id"]: d for dom, svc, d in fake.calls
               if (dom, svc) == ("persistent_notification", "create")}


def _probe_alert(value, *, last_updated=None, names=None, room_name=None, both=False):
    states = _room(2)
    if names:
        states[DESCRIPTOR][1]["zone_names"] = names
    if room_name is not None:
        states[DESCRIPTOR][1]["room_name"] = room_name
    for zone in (1, 2) if both else (2,):
        entity = f"sensor.crop_steering_vwc_zone_{zone}"
        if value is None:
            states.pop(entity)
        else:
            states[entity] = (value, {"unit_of_measurement": "%"})
    c, fake = _build(dict(OPTIONS), states=states)
    if last_updated is not None:
        for zone in (1, 2) if both else (2,):
            fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", value,
                           {"unit_of_measurement": "%"}, last_updated=last_updated)
    c.loop_once(NOW)
    alerts = {d["notification_id"]: d for dom, svc, d in fake.calls
              if (dom, svc) == ("persistent_notification", "create")}
    return alerts["f2_blind_default_z2"]


# ------------------------------------------------------------------ the reading, by why
def test_a_reading_that_has_not_moved_is_not_called_a_dead_probe():
    """The case on the first real install: a probe in a cube with no plant."""
    stale = (datetime.now(timezone.utc) - timedelta(minutes=47)).isoformat()
    alert = _probe_alert("31.2", last_updated=stale, names={"1": "GT1", "2": "GT4"}, both=True)
    assert alert["title"] == "GT4 (Z2): moisture reading hasn't changed (CS-101)"
    message = alert["message"]
    assert "stayed at 31.2% for 47 minutes" in message
    assert "no plant in it" in message
    assert "one shot every 90 minutes" in message  # no healthy zone to copy: the timer
    assert "dead" not in alert["title"] + message
    assert message.endswith(FOOTER.format("CS-101"))
    assert "Sensor: sensor.crop_steering_vwc_zone_2" in message  # the id, kept as a detail line


def test_a_sensor_that_is_not_reporting_says_so():
    for value, words in (("unavailable", "reads 'unavailable'"), ("unknown", "reads 'unknown'"),
                         ("wet", "reads 'wet', which isn't a number"),
                         (None, "can't be found in Home Assistant")):
        alert = _probe_alert(value)
        assert alert["title"] == "Zone 2: moisture sensor not reporting (CS-102)", value
        assert words in alert["message"], value
        assert "powered and online" in alert["message"]


def test_an_impossible_number_is_out_of_range():
    alert = _probe_alert("140")
    assert alert["title"] == "Zone 2: moisture reading out of range (CS-103)"
    assert "reads 140" in alert["message"] and "calibration" in alert["message"]


def test_a_reading_from_the_future_says_the_clocks_disagree():
    """_read_sensor rejects a reading stamped more than a minute ahead; it is not a dead probe."""
    ahead = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    alert = _probe_alert("31.2", last_updated=ahead)
    assert alert["title"] == "Zone 2: moisture sensor not reporting (CS-102)"
    assert "stamped 5 minutes in the future" in alert["message"]
    assert "clock" in alert["message"]


def test_a_changed_cause_replaces_the_card_within_minutes_not_half_an_hour():
    """One notification carries CS-101, CS-102 and CS-103. A probe that goes from "hasn't changed"
    to "unavailable" must not go on saying it is normal for an empty cube for half an hour, and a
    cause that flaps must not raise a card every loop."""
    stale = (datetime.now(timezone.utc) - timedelta(minutes=47)).isoformat()
    c, fake = _build(dict(OPTIONS), states=_room(2))
    fake.set_state("sensor.crop_steering_vwc_zone_2", "31.2", {"unit_of_measurement": "%"},
                   last_updated=stale)

    def titles():
        return [d["title"] for dom, svc, d in fake.calls
                if (dom, svc) == ("persistent_notification", "create")
                and d["notification_id"] == "f2_blind_default_z2"]

    c.loop_once(NOW)
    assert titles()[-1].endswith("(CS-101)")
    fake.set_state("sensor.crop_steering_vwc_zone_2", "unavailable", {})
    c._alerted["blind_default_z2"] -= timedelta(minutes=2)
    c.loop_once(NOW)
    assert len(titles()) == 1  # changed two minutes ago: it may still flap back
    c._alerted["blind_default_z2"] -= timedelta(minutes=4)
    c.loop_once(NOW)
    assert len(titles()) == 2 and titles()[-1].endswith("(CS-102)")
    c._alerted["blind_default_z2"] -= timedelta(minutes=10)
    c.loop_once(NOW)
    assert len(titles()) == 2  # the same cause keeps its 30-minute window


def test_the_ec_notification_names_the_sensor_actually_read():
    """UPGRADE IN PLACE: a box keeps the EC id it was first given (sensor.crop_steering_zone_1_ec)."""
    states = _room(1)
    for entity in ("sensor.crop_steering_ec_zone_1", "sensor.crop_steering_zone_1_ec"):
        states.pop(entity, None)
    states["sensor.crop_steering_vwc_zone_1"] = ("55", {"unit_of_measurement": "%"})
    states["sensor.crop_steering_zone_1_ec"] = ("25", {"unit_of_measurement": "mS/cm"})  # too high to use
    _c, alerts = _alerts(states)
    assert "Sensor: sensor.crop_steering_zone_1_ec" in alerts["f2_ec_unknown_default_z1"]["message"]


def test_a_zone_with_a_working_neighbour_says_which_one_it_copies():
    alert = _probe_alert("unavailable", names={"1": "GT1", "2": "GT4"})
    assert "gets the same shots as GT1 (Z1), whose probe is working" in alert["message"]
    assert "timer" not in alert["message"]


# ------------------------------------------------------------------ which room
def test_the_room_is_called_what_the_operator_called_it():
    alert = _probe_alert("unavailable", names={"2": "GT4"}, room_name="Tent")
    assert alert["title"] == "Tent · GT4 (Z2): moisture sensor not reporting (CS-102)"


def test_one_unnamed_room_says_nothing_about_the_room():
    """UPGRADE IN PLACE and FRESH: an older integration publishes no room_name, the wizard's
    default is "Crop Steering" (or "Crop Steering System"), and anything else may be rubbish.
    None of them is a name anybody chose, and "default" is never shown for the only room."""
    for name in (None, "", "  ", "Crop Steering", "Crop Steering System", "default", 7):
        states = _room(2)
        states["sensor.crop_steering_vwc_zone_2"] = ("unavailable", {})
        if name is None:
            states[DESCRIPTOR][1].pop("room_name", None)
        else:
            states[DESCRIPTOR][1]["room_name"] = name
        _c, alerts = _alerts(states)
        assert alerts["f2_blind_default_z2"]["title"].startswith("Zone 2: "), name


def test_two_rooms_are_told_apart_even_unnamed():
    states = {
        DESCRIPTOR: ("ok", _desc(pump=None, mainline=None, valves={"1": "switch.a"}, num=1)),
        "sensor.crop_steering_veg_engine_config": (
            "ok", _desc(prefix="veg_", pump=None, mainline=None, valves={"1": "switch.b"}, num=1,
                        slug="veg", room_name="Veg tent")),
        "sensor.crop_steering_vwc_zone_1": ("unavailable", {}),
        "sensor.crop_steering_veg_vwc_zone_1": ("unavailable", {}),
    }
    _c, alerts = _alerts(states, {"num_zones": 1})
    assert alerts["f2_blind_default_z1"]["title"].startswith("default · Zone 1: ")
    assert alerts["f2_blind_veg_z1"]["title"].startswith("Veg tent · Zone 1: ")


# ------------------------------------------------------------------ what does not change
def test_notification_ids_do_not_follow_the_wording():
    """UPGRADE IN PLACE: the new text replaces the card an older controller raised, instead of
    adding a second one beside it."""
    states = _room(2)
    states[DESCRIPTOR][1].update(zone_names={"2": "GT4"}, room_name="Tent")
    states["sensor.crop_steering_vwc_zone_2"] = ("unavailable", {})
    _c, alerts = _alerts(states)
    assert "f2_blind_default_z2" in alerts


def test_the_log_line_carries_the_code(capsys):
    _probe_alert("unavailable")
    assert "ALERT Zone 2: moisture sensor not reporting (CS-102) - This zone's" in capsys.readouterr().out


def test_a_zone_never_watered_is_not_given_a_number_of_hours():
    """It said "no water 16666666.7h" on a bare install: the never-watered marker, divided."""
    states = _room(1)
    states["sensor.crop_steering_vwc_zone_1"] = ("20", {"unit_of_measurement": "%"})
    _c, alerts = _alerts(states)
    alert = alerts["f2_wd_default_z1"]
    assert alert["title"] == "Zone 1: URGENT, drying out and not being watered (CS-207)"
    assert "has never been watered by the controller" in alert["message"]
    assert "16666666" not in alert["message"]
    assert "Blocked by: f2-control disabled (kill switch off)" in alert["message"]


def test_every_alert_the_controller_raises_passes_a_code():
    """The catalog check (tests/test_error_codes.py) reads these; a call without one fails here."""
    tree = ast.parse(Path(controller.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_alert"]
    assert len(calls) >= 24  # both daily-limit refusals raise CS-205 through _alert_daily_cap
    for call in calls:
        code = call.args[1]
        if isinstance(code, ast.Name):  # the moisture alert: one of _PROBE_ALERTS
            continue
        assert isinstance(code, ast.Constant) and re.fullmatch(r"CS-\d{3}", code.value), ast.unparse(call)[:80]
    assert sorted(controller._PROBE_ALERTS) == ["CS-101", "CS-102", "CS-103"]

