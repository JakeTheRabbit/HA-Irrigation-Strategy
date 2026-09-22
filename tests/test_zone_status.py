"""zone_N_status shows the controller's label for the zone, or that the controller is not reporting.

It used to compute its own label from fixed 40 % / 70 % VWC thresholds while the controller wrote a
phase-aware one to the same entity, and the two took turns (about twice a minute)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.crop_steering.zone_status import (
    NOT_REPORTING,
    STALE_MINUTES,
    mirrored_status,
    status_app_entity,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def app(state="Overnight dryback", reason="lights-off -> P3", updated=2, reported=1):
    attributes = {} if reason is None else {"reason": reason}
    source = SimpleNamespace(
        state=state,
        attributes=attributes,
        last_updated=NOW - timedelta(minutes=updated),
    )
    if reported is not None:
        source.last_reported = NOW - timedelta(minutes=reported)
    return source


def test_the_controllers_label_and_reason_are_shown():
    assert mirrored_status(app(), NOW) == (
        "Overnight dryback",
        {"reason": "lights-off -> P3"},
    )


@pytest.mark.parametrize("state", ["unavailable", "unknown", "", "None"])
def test_a_missing_or_dead_report_is_not_reporting(state):
    assert mirrored_status(None, NOW)[0] == NOT_REPORTING
    assert mirrored_status(app(state=state), NOW)[0] == NOT_REPORTING


def test_a_label_the_controller_keeps_repeating_stays_fresh():
    # Unchanged all afternoon, so last_updated is old; every write still moves last_reported.
    assert mirrored_status(app(updated=300, reported=1), NOW)[0] == "Overnight dryback"


def test_a_controller_that_has_stopped_reporting_is_said_to():
    stale = mirrored_status(app(updated=30, reported=STALE_MINUTES + 1), NOW)
    assert stale[0] == NOT_REPORTING and "10 minutes" in stale[1]["reason"]
    assert (
        mirrored_status(app(reported=STALE_MINUTES - 1), NOW)[0] == "Overnight dryback"
    )


def test_home_assistant_without_last_reported_uses_last_updated():
    assert mirrored_status(app(updated=2, reported=None), NOW)[0] == "Overnight dryback"
    assert mirrored_status(app(updated=30, reported=None), NOW)[0] == NOT_REPORTING


def test_no_threshold_is_applied_and_a_reason_that_is_not_text_is_dropped():
    assert mirrored_status(app(state="Dry - Needs Water", reason=None), NOW) == (
        "Dry - Needs Water",
        {},
    )
    assert mirrored_status(app(reason=42), NOW)[1] == {}


def test_each_room_reads_its_own_entity():
    assert status_app_entity("", 1) == "sensor.crop_steering_zone_1_status_app"
    assert status_app_entity("f1_", 3) == "sensor.crop_steering_f1_zone_3_status_app"
