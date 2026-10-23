"""The room's current_phase sensor mirrors the phase the controller publishes, and is unknown
(with a reason) when the controller has not published one lately. It never invents a phase: it
used to fall back to the irrigation_phase select (which the controller never reads) and then to a
hard-coded "P2", so a room whose controller was stopped was shown in maintenance as if real."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.crop_steering.zone_status import (
    STALE_MINUTES,
    app_phase_entity,
    mirrored_phase,
)

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def app(state="Z1:P3, Z2:P3", updated=2, reported=1):
    source = SimpleNamespace(
        state=state, attributes={}, last_updated=NOW - timedelta(minutes=updated)
    )
    if reported is not None:
        source.last_reported = NOW - timedelta(minutes=reported)
    return source


def test_a_fresh_controller_phase_is_mirrored_as_is():
    assert mirrored_phase(app(), NOW) == ("Z1:P3, Z2:P3", {})


@pytest.mark.parametrize("state", ["unavailable", "unknown", "", "None"])
def test_a_missing_or_dead_report_is_unknown_never_p2(state):
    for source in (None, app(state=state)):
        shown, attributes = mirrored_phase(source, NOW)
        assert shown is None and "P2" not in str(attributes)
        assert "has not published" in attributes["reason"]


def test_a_controller_that_has_stopped_reporting_is_unknown_with_the_reason():
    shown, attributes = mirrored_phase(app(reported=STALE_MINUTES + 1), NOW)
    assert shown is None and f"{STALE_MINUTES} minutes" in attributes["reason"]
    assert mirrored_phase(app(reported=STALE_MINUTES - 1), NOW)[0] == "Z1:P3, Z2:P3"


def test_a_phase_the_controller_keeps_repeating_stays_fresh():
    assert mirrored_phase(app(updated=300, reported=1), NOW)[0] == "Z1:P3, Z2:P3"


def test_home_assistant_without_last_reported_uses_last_updated():
    assert mirrored_phase(app(updated=2, reported=None), NOW)[0] == "Z1:P3, Z2:P3"
    assert mirrored_phase(app(updated=30, reported=None), NOW)[0] is None


def test_each_room_reads_its_own_entity():
    assert app_phase_entity("") == "sensor.crop_steering_app_current_phase"
    assert (
        app_phase_entity("room_b_") == "sensor.crop_steering_room_b_app_current_phase"
    )
