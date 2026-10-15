"""A room muted in Crop Steering (sensor.crop_steering_notify_config `muted`: room prefix -> until, docs/NOTIFICATIONS.md)
pushes nothing but a critical code until its mute ends, through the integration or to the notify_service option.
Every alert is still a card. An integration from before mutes publishes none, and nothing changes."""
from datetime import datetime, timedelta, timezone

import pytest

import controller
from test_notify_routing import CONFIG, OPTION, Router, _cards, _option, _setup


@pytest.fixture
def router(monkeypatch):
    def install():
        routed = Router()
        monkeypatch.setattr(controller, "ha_service_response", routed)
        return routed

    return install


def _muted(recipients, until, notify_service=OPTION):
    c, fake = _setup(recipients=recipients, notify_service=notify_service)
    fake.set_state(CONFIG, "4", {"recipients": recipients, "idle_hours": 3, "muted": {"": until}})
    return c, fake


LATER = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
EARLIER = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()


@pytest.mark.parametrize("recipients", [0, 1], ids=["to the option", "through the integration"])
def test_a_muted_room_pushes_nothing_but_a_critical_code(router, recipients):
    c, fake = _muted(recipients, LATER)
    routed = router()
    room = c.rooms[0]
    assert c._alert("blind_default_z1", "CS-102", "moisture sensor not reporting", "m", room=room, zone=1)
    assert c._alert("block_default_z1", "CS-205", "daily water limit reached", "m", room=room, zone=1)
    assert _cards(fake, "f2_blind_default_z1") and _cards(fake, "f2_block_default_z1")  # the cards, as always
    assert routed.calls == [] and _option(fake) == []
    assert c._alert("hw_default_z1", "CS-301", "hardware fault", "m", room=room, zone=1)
    if recipients:
        assert [d["key"] for d in routed.sent] == ["hw_default_z1"]
    else:
        assert len(_option(fake)) == 1
    # An alert about no room in particular is never muted.
    assert c._alert("tz_mismatch", "CS-405", "timezone mismatch", "m")
    assert len(routed.sent) + len(_option(fake)) == 2


def test_a_mute_that_is_over_or_unreadable_mutes_nothing(router):
    for until in (EARLIER, "tomorrow", "2026-10-15T08:00:00", None):
        c, fake = _muted(0, until)
        router()
        assert c._alert("k", "CS-102", "moisture sensor not reporting", "m", room=c.rooms[0], zone=1)
        assert len(_option(fake)) == 1, until


def test_another_rooms_mute_leaves_this_one_alone(router):
    c, fake = _setup(recipients=0)
    fake.set_state(CONFIG, "4", {"recipients": 0, "idle_hours": 3, "muted": {"f1_": LATER}})
    router()
    assert c._alert("k", "CS-102", "moisture sensor not reporting", "m", room=c.rooms[0], zone=1)
    assert len(_option(fake)) == 1
