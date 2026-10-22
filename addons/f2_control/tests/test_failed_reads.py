"""A read or a write Home Assistant does not answer is never taken for a real value.

  * A zone setting is parsed from the one read that found it: a second read failing used to give the
    built-in value and remember it as read, past the settings wait (CTL-007).
  * A state write that fails is logged, once an hour per entity, and counted on the heartbeat (CTL-017).
  * The controller-vs-Home Assistant time-zone check is tried again each loop until Home Assistant
    answers, not only once at start (CTL-019).
  * Zone detection without a descriptor counts from one read of every state, so a read that fails
    part-way never counts too few zones (CTL-023).
  * Mid-shot, an unreadable kill switch keeps the documented policy: the shot runs to the length it
    started with, and a definite OFF still ends it (CTL-024).
"""

from datetime import datetime

import pytest

import controller
from test_controller import _build

REAL_SET = controller.ha_set  # before any test's fake_ha.install replaces it
KILL = "input_boolean.kill"
PER = "number.crop_steering_zone_1_substrate_volume"


class _Stop(BaseException):
    """Ends run()'s endless loop in a test."""


def _fail_second_read(monkeypatch, entity):
    """Home Assistant answers the first read of `entity`, and not the next ones."""
    real, reads = controller.ha_get, {"n": 0}

    def ha_get(eid, *args, **kwargs):
        if eid == entity:
            reads["n"] += 1
            if reads["n"] > 1:
                return controller.HAState()
        return real(eid, *args, **kwargs)

    monkeypatch.setattr(controller, "ha_get", ha_get)


# ---------------------------------------------------------------- CTL-007
def test_a_zone_setting_is_the_value_its_one_read_found(monkeypatch):
    c, _fake = _build({"num_zones": 1}, states={PER: ("6.5", {})})
    _fail_second_read(monkeypatch, PER)
    assert c._zone_num(c.rooms[0], 1, "substrate_volume", 11.0) == 6.5
    assert c._settings_seen[PER] == 6.5  # never the built-in 11.0 remembered as read


def test_a_failed_second_read_never_breaks_the_settings_wait(monkeypatch):
    c, _fake = _build({"num_zones": 1}, states={PER: ("6.5", {})})
    _fail_second_read(monkeypatch, PER)
    c._settings_hold(
        c.rooms[0], 1
    )  # WATER_SIZING reads with no default: float(None) used to raise here
    assert c._settings_seen[PER] == 6.5


# ---------------------------------------------------------------- CTL-017
class _Answer:
    def __init__(self, status):
        self.status_code = status


class _Session:
    def __init__(self, answers):
        self.answers = list(answers)

    def post(self, *args, **kwargs):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Answer(answer)


def test_a_failed_state_write_is_logged_once_an_hour_and_counted(monkeypatch):
    lines, clock = [], {"s": 0.0}
    monkeypatch.setattr(
        controller, "_SET_FAILED", {"count": 0, "logged": {}}, raising=False
    )
    monkeypatch.setattr(
        controller, "log", lambda *a: lines.append(" ".join(str(x) for x in a))
    )
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["s"])
    session = _Session([500, OSError("down"), 200, 503])
    monkeypatch.setattr(controller, "_session", lambda: session)
    beat = "sensor.crop_steering_ai_heartbeat"
    assert REAL_SET(beat, "healthy") == 500
    assert REAL_SET(beat, "healthy") is None
    assert REAL_SET(beat, "healthy") == 200
    clock["s"] = 3600.0
    assert REAL_SET(beat, "healthy") == 503
    failed = [line for line in lines if "state write failed" in line]
    assert (
        len(failed) == 2
    )  # the first, and the first an hour later; the one between is counted only
    assert beat in failed[0] and "HTTP 500" in failed[0]
    assert (
        "HTTP 503" in failed[1] and "3 failed since the controller started" in failed[1]
    )
    assert controller._SET_FAILED["count"] == 3


def test_the_heartbeat_carries_the_count_of_failed_writes(monkeypatch):
    c, fake = _build({"num_zones": 1})
    monkeypatch.setattr(
        controller, "_SET_FAILED", {"count": 4, "logged": {}}, raising=False
    )
    c._heartbeat(c.rooms[0], datetime.now(), False)
    assert fake.sets["sensor.crop_steering_ai_heartbeat"][1]["write_failures"] == 4


# ---------------------------------------------------------------- CTL-019
class _Config:
    def __init__(self, answers):
        self.answers = answers

    def get(self, url, **kwargs):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        result = _Answer(200)
        result.json = lambda: {"time_zone": answer}
        return result


def test_the_time_zone_check_runs_again_until_home_assistant_answers(monkeypatch):
    c, fake = _build({"num_zones": 1})
    local = datetime.now().astimezone().utcoffset().total_seconds() / 3600.0
    other = (
        "Pacific/Kiritimati" if abs(local - 14) > 0.01 else "Etc/GMT+12"
    )  # never the local offset
    config = _Config([OSError("starting"), OSError("starting"), other])
    monkeypatch.setattr(controller, "_session", lambda: config)
    passes = []
    monkeypatch.setattr(c, "_start_dosing", lambda: None)
    monkeypatch.setattr(c, "loop_once", lambda now: passes.append(now))

    def sleep(_seconds):
        if len(passes) >= 3:
            raise _Stop

    monkeypatch.setattr(c, "_sleep_for", sleep)
    with pytest.raises(_Stop):
        c.run()
    cards = [
        d
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create")
        and d["notification_id"] == "f2_tz_mismatch"
    ]
    assert len(cards) == 1 and other in cards[0]["message"]


# ---------------------------------------------------------------- CTL-023
def test_zone_detection_never_stops_at_a_read_that_failed(monkeypatch):
    states = {f"sensor.crop_steering_vwc_zone_{z}": ("50", {}) for z in (1, 2, 3)}
    c, _fake = _build({"num_zones": 1}, states=states)
    real = controller.ha_get
    monkeypatch.setattr(
        controller,
        "ha_get",
        lambda eid, *a, **k: (
            controller.HAState() if eid.endswith("zone_2") else real(eid, *a, **k)
        ),
    )
    assert c._detect_zones("", 7) == 3


def test_zone_detection_with_no_answer_gives_the_fallback(monkeypatch):
    c, _fake = _build(
        {"num_zones": 1}, states={"sensor.crop_steering_vwc_zone_1": ("50", {})}
    )
    monkeypatch.setattr(controller, "ha_get_all", lambda: [])
    assert c._detect_zones("", 7) == 7


def test_zone_detection_counts_the_legacy_ids_too():
    states = {
        "sensor.crop_steering_vwc_zone_1": ("50", {}),
        "sensor.crop_steering_zone_2_vwc": ("50", {}),
        "sensor.crop_steering_vwc_zone_4": ("50", {}),
    }  # zone 3 missing: the count stops there
    c, _fake = _build({"num_zones": 1}, states=states)
    assert c._detect_zones("", 7) == 2


# ---------------------------------------------------------------- CTL-024 (policy kept, pinned)
def test_an_unreadable_kill_switch_mid_shot_runs_the_shot_to_its_length_and_off_still_ends_it(
    monkeypatch,
):
    c, fake = _build(
        {
            "num_zones": 1,
            "enable_flag": KILL,
            "hardware": {
                "pump": "switch.p",
                "mainline": "switch.m",
                "valves": {"1": "switch.v1"},
            },
        },
        states={KILL: ("on", {})},
    )
    clock = {"s": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["s"])
    monkeypatch.setattr(
        controller.time, "sleep", lambda dt: clock.__setitem__("s", clock["s"] + dt)
    )
    fake.set_state(KILL, "unavailable")
    assert c._wait_shot(c.rooms[0], 1, 6) == (6, None)
    fake.set_state(KILL, "off")
    clock["s"] = 0.0
    assert c._wait_shot(c.rooms[0], 1, 6)[1] == ("abort", KILL)
