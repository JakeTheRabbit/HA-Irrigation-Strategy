"""Room health stops the Claude brain's asks (gap SF-26): a zone whose moisture reading is stale or missing makes the
room impaired (every zone stale: critical), the brain asks nothing for any zone of it, the brain panel says why, and
it asks again once the probes report. The rules keep watering throughout."""
import functools
from datetime import datetime, timedelta, timezone

import brain_kit as B
import brain_bridge
import pytest
from brain import client as jc
from test_brain_wiring import Clock, _zone
from test_controller import _build, _desc
from test_jev_controller import KILL, NOW, _states

PROBE_2 = "sensor.crop_steering_vwc_zone_2"


def _old():
    return (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()


@pytest.fixture
def two_zones(monkeypatch):
    """A two-zone room whose brain is Claude with a fake SDK client, answered synchronously."""
    def make(zone_2_on=True):
        client = B.FakeClient(B.judging())
        monkeypatch.setattr(jc, "anthropic", B.FakeSDK(client))
        clock = Clock(NOW.timestamp())
        monkeypatch.setattr(brain_bridge, "Asker", functools.partial(jc.Asker, threaded=False, clock=clock))
        monkeypatch.setattr(brain_bridge, "Meter", functools.partial(jc.Meter, clock=clock))
        monkeypatch.setattr(brain_bridge, "Routes", functools.partial(jc.Routes, sleep=lambda s: None))
        states = _states()
        states["sensor.crop_steering_engine_config"] = ("ok", _desc(
            enable_flag=KILL, num=2, valves={"1": "switch.v1", "2": "switch.v2"}))
        states.update({"switch.crop_steering_zone_2_enabled": ("on" if zone_2_on else "off", {}),
                       PROBE_2: ("37.0", {"unit_of_measurement": "%"}),
                       "sensor.crop_steering_ec_zone_2": ("6.0", {"unit_of_measurement": "mS/cm"})})
        c, fake = _build({"num_zones": 2, "enable_flag": KILL, "brain_provider": "claude_haiku",
                          "anthropic_api_key": B.SENTINEL}, states=states)
        c._clock, c._client = clock, client
        return c, fake
    return make


def test_a_stale_zone_stops_every_ask_in_the_room_and_the_panel_says_why(two_zones):
    c, fake = two_zones()
    fake.set_state(PROBE_2, "37.0", {"unit_of_measurement": "%"}, last_updated=_old())
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests == []  # zone 1 reads fine, but the room is impaired: nothing is asked
    state, panel = fake.sets["sensor.crop_steering_jev"]
    assert state == "on" and panel["state"] == "stale_data" and panel["room_health"] == "impaired"
    assert panel["state_words"].startswith("Readings too old to judge: Zone 2 has no fresh moisture reading.")
    assert "rules keep watering" in panel["state_words"]
    assert panel["judges_acting"] == []

    fake.set_state(PROBE_2, "36.5", {"unit_of_measurement": "%"})  # the probe reports again
    c._clock.t += 20 * 60
    c.loop_once(NOW + timedelta(minutes=20))
    assert c._client.requests, "it asks again once every probe reports"
    panel = fake.sets["sensor.crop_steering_jev"][1]
    assert panel["state"] == "acting" and panel["room_health"] == "ok"


def test_every_zone_stale_is_critical_and_nothing_is_asked(two_zones):
    c, fake = two_zones()
    for probe in ("sensor.crop_steering_vwc_zone_1", PROBE_2):
        fake.set_state(probe, "unavailable")
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests == []
    panel = fake.sets["sensor.crop_steering_jev"][1]
    assert (panel["state"], panel["room_health"]) == ("stale_data", "critical")
    assert panel["state_words"].startswith("Readings too old to judge: no zone has a fresh moisture reading.")


def test_a_switched_off_zone_with_no_probe_does_not_stop_the_brain(two_zones):
    c, fake = two_zones(zone_2_on=False)
    fake.set_state(PROBE_2, "unavailable")
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests
    assert fake.sets["sensor.crop_steering_jev"][1]["room_health"] == "ok"
