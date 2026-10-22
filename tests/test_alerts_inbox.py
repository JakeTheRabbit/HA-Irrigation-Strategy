"""The alerts inbox (alerts_inbox.open_alerts): which raised alerts are still open, folded from the
room's alert.* journal events and the live persistent notifications. PURE."""

from custom_components.crop_steering.alerts_inbox import open_alerts

TANK = "sensor.crop_steering_f2_tank_level"


def _ev(kind, event_id, ts, actor="system", code=None, zone=None, **data):
    return {
        "v": 1,
        "id": event_id,
        "ts": f"2026-10-22T{ts}:00+13:00",
        "kind": kind,
        "zone": zone,
        "outcome": "ok",
        "code": code,
        "source": {"actor": actor},
        "data": data,
    }


def _rule(event_id="E1", ts="07:00", kind="alert.raised", **data):
    return _ev(kind, event_id, ts, rule_id="R1", **data)


def _controller(event_id="C1", ts="07:05", kind="alert.raised", **data):
    return _ev(
        kind,
        event_id,
        ts,
        actor="engine",
        code="CS-101",
        zone=2,
        key="stale_z2",
        **data,
    )


def test_each_open_alert_names_its_entity_or_none():
    events = [
        _rule(title="F2 tank level below 30%", value=12.0, threshold=30.0),
        _controller(title="Zone 2 probe stale"),
    ]
    alerts = open_alerts(events, {"f2_stale_z2"}, {"R1": TANK})
    by_id = {a["event_id"]: a for a in alerts}
    assert by_id["E1"] == {
        "event_id": "E1",
        "ts": "2026-10-22T07:00:00+13:00",
        "code": None,
        "title": "F2 tank level below 30%",
        "zone": None,
        "entity_id": TANK,
        "rule_id": "R1",
        "acknowledged": False,
    }
    assert by_id["C1"] == {
        "event_id": "C1",
        "ts": "2026-10-22T07:05:00+13:00",
        "code": "CS-101",
        "title": "Zone 2 probe stale",
        "zone": 2,
        "entity_id": None,
        "acknowledged": False,
    }
    assert [a["event_id"] for a in alerts] == ["C1", "E1"]  # newest first
    # Task 8's controller alert names its sensor; a rule nobody maps names nothing.
    named = _controller(title="t", entity_id="sensor.f2_z2_vwc")
    (alert,) = open_alerts([named], {"f2_stale_z2"})
    assert alert["entity_id"] == "sensor.f2_z2_vwc"
    assert open_alerts([_rule()], set())[0]["entity_id"] is None


def test_raised_then_cleared_is_not_open():
    assert open_alerts([_rule(), _rule("E2", "07:30", "alert.cleared")], set()) == []
    events = [
        _controller(),
        _controller("C2", "07:30", "alert.cleared"),
    ]
    assert open_alerts(events, {"f2_stale_z2"}) == []
    # Raised again after it cleared: open again, as the new raise.
    again = [*events, _controller("C3", "08:00")]
    assert [a["event_id"] for a in open_alerts(again, {"f2_stale_z2"})] == ["C3"]
    # Another rule's clear leaves it open.
    other = _ev("alert.cleared", "X", "07:40", rule_id="R2")
    assert [a["event_id"] for a in open_alerts([_rule(), other], set())] == ["E1"]


def test_a_repeated_raise_keeps_the_first_of_the_episode():
    """The controller repeats an alert while it lasts: one inbox row, the id an ack was given."""
    events = [_controller(), _controller("C2", "07:35")]
    assert [a["event_id"] for a in open_alerts(events, {"f2_stale_z2"})] == ["C1"]


def test_acknowledged_leaves_the_inbox():
    ack = _ev(
        "alert.acknowledged",
        "A1",
        "07:10",
        actor="manual",
        alert_event_id="E1",
        rule_id="R1",
    )
    assert open_alerts([_rule(), ack], set(), {"R1": TANK}) == []
    ack = _ev(
        "alert.acknowledged",
        "A2",
        "07:10",
        actor="manual",
        alert_event_id="C1",
        key="stale_z2",
    )
    assert open_alerts([_controller(), ack], {"f2_stale_z2"}) == []
    # An alert with neither key nor rule_id is acknowledged by its own event id.
    bare = _ev("alert.raised", "B1", "07:00", actor="engine")
    ack = _ev("alert.acknowledged", "A3", "07:10", actor="manual", alert_event_id="B1")
    assert open_alerts([bare], set())[0]["event_id"] == "B1"
    assert open_alerts([bare, ack], set()) == []


def test_an_alert_whose_notification_is_gone_leaves_the_inbox():
    """The controller dismisses its f2_<key> notification directly at 12 places, with no
    alert.cleared: the inbox follows the notification."""
    assert [a["event_id"] for a in open_alerts([_controller()], {"f2_stale_z2"})] == [
        "C1"
    ]
    assert open_alerts([_controller()], set()) == []
    assert open_alerts([_controller()], {"f2_other"}) == []
    # A rule alert is the integration's own (actor system): no notification, still open.
    assert [a["event_id"] for a in open_alerts([_rule()], set())] == ["E1"]
