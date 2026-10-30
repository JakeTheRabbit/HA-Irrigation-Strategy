"""The alerts inbox (alerts_inbox.open_alerts): which raised alerts are still open, folded from the
room's alert.* journal events and the notifications seen live that are now gone. PURE."""

from datetime import datetime, timedelta, timezone

from custom_components.crop_steering.alerts_inbox import (
    LOOKBACK,
    SINCE_EVER,
    open_alerts,
    window_start,
)

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
    alerts = open_alerts(events, set(), {"R1": TANK})
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
    (alert,) = open_alerts([named], set())
    assert alert["entity_id"] == "sensor.f2_z2_vwc"
    assert open_alerts([_rule()], set())[0]["entity_id"] is None


def test_raised_then_cleared_is_not_open():
    assert open_alerts([_rule(), _rule("E2", "07:30", "alert.cleared")], set()) == []
    events = [
        _controller(),
        _controller("C2", "07:30", "alert.cleared"),
    ]
    assert open_alerts(events, set()) == []
    # Raised again after it cleared: open again, as the new raise.
    again = [*events, _controller("C3", "08:00")]
    assert [a["event_id"] for a in open_alerts(again, set())] == ["C3"]
    # Another rule's clear leaves it open.
    other = _ev("alert.cleared", "X", "07:40", rule_id="R2")
    assert [a["event_id"] for a in open_alerts([_rule(), other], set())] == ["E1"]


def test_a_repeated_raise_keeps_the_first_of_the_episode():
    """The controller repeats an alert while it lasts: one inbox row, the id an ack was given."""
    events = [_controller(), _controller("C2", "07:35")]
    assert [a["event_id"] for a in open_alerts(events, set())] == ["C1"]


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
    assert open_alerts([_controller(), ack], set()) == []
    # An alert with neither key nor rule_id is acknowledged by its own event id.
    bare = _ev("alert.raised", "B1", "07:00", actor="engine")
    ack = _ev("alert.acknowledged", "A3", "07:10", actor="manual", alert_event_id="B1")
    assert open_alerts([bare], set())[0]["event_id"] == "B1"
    assert open_alerts([bare, ack], set()) == []


def test_an_alert_whose_notification_is_gone_leaves_the_inbox():
    """The controller dismisses its f2_<key> notification directly at 12 places, with no
    alert.cleared: an alert whose notification was seen live and is now gone closes."""
    assert open_alerts([_controller()], {"f2_stale_z2"}) == []
    assert open_alerts([_controller()], {"f2_other"})[0]["event_id"] == "C1"
    # Never seen live (a restart wiped the notifications): stale beats dropped, still open.
    assert [a["event_id"] for a in open_alerts([_controller()], set())] == ["C1"]
    # A rule alert is the integration's own (actor system): never closed by a notification.
    rule = _ev("alert.raised", "E1", "07:00", rule_id="R1", key="stale_z2")
    assert [a["event_id"] for a in open_alerts([rule], {"f2_stale_z2"})] == ["E1"]


NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def test_the_next_fold_starts_at_the_oldest_open_raise_or_the_lookback():
    """P1 M2: the 5-min fold reads from the oldest alert still open (a gone one too: the controller shows its
    notification again, with no new raise), or LOOKBACK before now when that is earlier.
    """
    old = _ev("alert.raised", "O1", "07:00", actor="engine", key="k")
    old["ts"] = "2026-08-01T07:00:00+12:00"
    assert window_start([old, _controller()], NOW) == datetime.fromisoformat(old["ts"])
    cleared = _ev("alert.cleared", "X1", "07:30", actor="engine", key="k")
    assert window_start([old, cleared, _controller()], NOW) == NOW - LOOKBACK
    assert window_start([], NOW) == NOW - LOOKBACK
    assert LOOKBACK >= timedelta(days=1)


def test_an_open_raise_with_no_time_reads_everything():
    """Fail closed: a raise whose time cannot be read keeps the whole history in the fold."""
    bad = _controller()
    bad["ts"] = "not a time"
    assert window_start([bad], NOW) == datetime.fromisoformat(SINCE_EVER)
