"""The controller names the writer of each of its setpoint writes first (the `crop_steering_setpoint_write`
claim, the integration's setpoint_log.py), and takes that claim back when the write does not land, so an
operator who writes the same value soon after is not taken for the brain (CTL-035)."""

from datetime import datetime

import controller
from test_controller import _build, _desc

SHOT = "number.crop_steering_zone_1_p2_shot_size"
CLAIM, CANCEL = "crop_steering_setpoint_write", "crop_steering_setpoint_claim_cancel"


def _room(monkeypatch, lands):
    c, fake = _build(
        {"num_zones": 1},
        states={"sensor.crop_steering_engine_config": ("ok", _desc()), SHOT: ("5", {})},
    )
    calls = []
    monkeypatch.setattr(controller, "ha_call", lambda domain, service, **data: calls.append((domain, service)) or lands)
    fake.events.clear()
    return c, fake, calls


def test_a_failed_write_takes_its_claim_back(monkeypatch):
    c, fake, calls = _room(monkeypatch, False)
    assert not c._auto_write(c.rooms[0], 1, "p2_shot_size", 5.0, 6.0, {}, datetime.now(), by="Jev")
    assert calls == [("number", "set_value")]
    (claim_event, claim), (cancel_event, cancel) = fake.events
    assert (claim_event, cancel_event) == (CLAIM, CANCEL)
    assert claim["who"] == "brain" and claim["expires"] and claim["claim_id"]
    assert cancel == {k: claim[k] for k in ("entity_id", "value", "who", "claim_id")}


def test_a_write_that_lands_keeps_its_claim(monkeypatch):
    c, fake, _calls = _room(monkeypatch, True)
    assert c._auto_write(c.rooms[0], 1, "p2_shot_size", 5.0, 6.0, {}, datetime.now(), by="Jev")
    assert [event for event, _ in fake.events] == [CLAIM]
    # Each claim is told apart from the next on the same number.
    assert c._auto_write(c.rooms[0], 1, "p2_shot_size", 6.0, 7.0, {}, datetime.now(), by="Jev")
    first, second = (data["claim_id"] for _, data in fake.events)
    assert first != second
