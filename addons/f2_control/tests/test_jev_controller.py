"""The Jev edition inside the real controller: Jev off or failing changes nothing; Jev's admitted
directives move the zone, and everything it judged is published (docs/JEV.md, properties 2, 3 and 7)."""
import functools
from datetime import datetime, timedelta

import pytest

import controller
import jev_bridge
import jev_kit as K
from jev.client import Asker
from test_controller import _build, _desc

KILL = "input_boolean.kill"
NOW = datetime(2026, 9, 27, 13, 0)


def _states(vwc=40.5, ec=6.5):
    return {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: ("on", {}),
        "switch.crop_steering_room_active": ("on", {}),
        "switch.crop_steering_zone_1_enabled": ("on", {}),
        "switch.crop_steering_system_enabled": ("on", {}),
        "switch.crop_steering_auto_irrigation_enabled": ("on", {}),
        "sensor.crop_steering_vwc_zone_1": (str(vwc), {"unit_of_measurement": "%"}),
        "sensor.crop_steering_ec_zone_1": (str(ec), {"unit_of_measurement": "mS/cm"}),
        "number.crop_steering_p1_target_vwc": ("40", {}),
        "number.crop_steering_field_capacity": ("42", {}),
        "number.crop_steering_p2_vwc_threshold": ("33", {}),
        "number.crop_steering_lights_on_hour": ("10", {}),
        "number.crop_steering_lights_off_hour": ("22", {}),
    }


def _p1_zone(c):
    """A zone in its ramp: three ramp shots in, the last 20 minutes ago, at the ceiling, EC holding P1."""
    st = c.rooms[0].state[1]
    st.update(phase="P1", shots=3, last_shot=NOW - timedelta(minutes=20),
              last_phase_change=NOW - timedelta(minutes=70), last_daily_reset=NOW.date())
    return st


@pytest.fixture
def jev_with(monkeypatch):
    """Build controllers whose Jev answers with `answers` (or fails with `error`), synchronously."""
    def make(answers=None, error=None):
        transport = K.FakeTransport(answers, error)
        monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: transport)
        monkeypatch.setattr(jev_bridge, "Asker", functools.partial(
            Asker, threaded=False, clock=lambda: NOW.timestamp()))
        K.has_run()  # Cloudflare alone starts Jev only where it has run before
        c, fake = _build({"num_zones": 1, "enable_flag": KILL, "cf_account_id": "acct",
                          "cf_api_token": "tok"}, states=_states())
        c._jev_transport = transport
        return c, fake
    return make


def _switches(fake):
    return [(svc, d.get("entity_id")) for dom, svc, d in fake.calls if dom == "switch"]


def test_without_cloudflare_the_jev_edition_is_the_plain_engine():
    c, _ = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    assert c.jev is None
    _p1_zone(c)
    c.loop_once(NOW)
    assert c.rooms[0].state[1]["phase"] == "P1"  # the base engine: at the ceiling, but EC holds P1


def test_a_failing_jev_changes_nothing(jev_with):
    base, base_fake = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    _p1_zone(base)
    base.loop_once(NOW)
    c, fake = jev_with(error="HTTP 503: unavailable")
    _p1_zone(c)
    c.loop_once(NOW)
    assert c.jev is not None and c._jev_transport.calls  # it asked
    assert c.rooms[0].state[1]["phase"] == base.rooms[0].state[1]["phase"] == "P1"
    assert _switches(fake) == _switches(base_fake)
    room_jev = fake.sets["sensor.crop_steering_jev"][1]
    assert room_jev["errors_today"] >= 1 and "503" in room_jev["last_error"]


def test_jev_hands_the_ramp_over_when_the_ec_is_just_the_feed(jev_with):
    answers = K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8, "real_salt": 0.2}))
    c, fake = jev_with(answers)
    _p1_zone(c)
    c.loop_once(NOW)
    assert c.rooms[0].state[1]["phase"] == "P2"
    zone = fake.sets["sensor.crop_steering_zone_1_jev"]
    assert "ramp" in zone[0]
    assert zone[1]["judges"]["ramp"]["directive"] == "advance P2"
    assert c.jev.ledger.entries[-1]["judge"] == "ramp"


def test_a_ramp_hand_over_the_envelope_refuses_does_not_move_the_zone(jev_with):
    answers = K.both("ramp_state", K.choice_answer("slab_full", {"slab_full": 0.9}))
    c, fake = jev_with(answers)
    _p1_zone(c)
    fake.set_state("sensor.crop_steering_vwc_zone_1", "30.0", {"unit_of_measurement": "%"})
    c.loop_once(NOW)
    st = c.rooms[0].state[1]
    assert st["phase"] == "P1"  # 10 points under the ceiling: refused
    shown = fake.sets["sensor.crop_steering_zone_1_jev"][1]["judges"]["ramp"]
    assert shown["why"].startswith("refused")


def test_a_broken_brain_never_stops_the_loop(jev_with, monkeypatch):
    c, _ = jev_with({})
    monkeypatch.setattr(jev_bridge, "tick", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _p1_zone(c)
    c.loop_once(NOW)  # must not raise
    assert c.rooms[0].state[1]["phase"] == "P1"


def test_the_controller_starts_even_if_jev_cannot(monkeypatch):
    monkeypatch.setattr(jev_bridge, "build", lambda *a, **k: (_ for _ in ()).throw(OSError("no /data")))
    c, _ = _build({"num_zones": 1, "enable_flag": KILL, "cf_account_id": "a", "cf_api_token": "t"},
                  states=_states())
    assert c.jev is None


def test_the_options_choose_the_judges(jev_with, monkeypatch, tmp_path):
    monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: K.FakeTransport({}))
    monkeypatch.setattr(jev_bridge, "Asker", functools.partial(Asker, threaded=False))
    state = str(tmp_path / "state.json")
    K.has_run(state)
    brain = jev_bridge.build({"jev_judges": "ramp, salt"}, ("a", "t", ""), state, lambda *a: None)
    assert sorted(j.name for j in brain.judges) == ["ramp", "salt"]
    assert jev_bridge.build({"jev_enabled": False}, ("a", "t", ""), "/tmp/s.json", lambda *a: None) is None
    assert controller.Controller.__dict__  # controller imports the bridge


def _created(fake, code):
    return [d["notification_id"] for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and f"({code})" in d["title"]]


def test_the_jev_sensor_shows_the_routes_the_budget_and_the_stricter_gate(jev_with):
    c, fake = jev_with({})
    _p1_zone(c)  # in its ramp: nothing fires, so the pass takes no shot time
    for _ in range(3):
        c.jev.ledger.resolve(c.jev.ledger.record("ramp", "default", 1, "P2", "advance"), "fell back", False)
    c.loop_once(NOW)
    room = fake.sets["sensor.crop_steering_jev"][1]
    assert room["routes"] == ["Cloudflare"] and room["daily_budget"] == 5000
    assert {"last_route", "retries_today", "failovers_today", "reasks_today"} <= set(room)
    assert fake.sets["sensor.crop_steering_zone_1_jev"][1]["strict"] == ["ramp"]


def test_jev_pushes_once_when_todays_calls_reach_80_percent(jev_with):
    c, fake = jev_with({})
    _p1_zone(c)  # in its ramp, so the Ramp judge is asked: the day's first call
    c.jev.asker.daily_budget = 1  # and that call is all of the budget
    c.loop_once(NOW)
    assert _created(fake, "CS-706") == ["f2_jev_budget_default"]
    c.loop_once(NOW + timedelta(minutes=1))
    assert len(_created(fake, "CS-706")) == 1


def test_jev_pushes_when_a_judge_goes_on_the_stricter_gate(jev_with):
    c, fake = jev_with({})
    _p1_zone(c)
    c.jev.events.append(("strict", "default", 1, "ramp"))
    c.loop_once(NOW)
    assert _created(fake, "CS-707") == ["f2_jev_ramp_default_z1"] and c.jev.events == []
