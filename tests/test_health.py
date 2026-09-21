"""Tests for the per-room Repairs health checks (#22).

Confirms the kill-switch / heartbeat health checks resolve per room instead of
hardcoding the F2 default, so a custom default kill switch and additional rooms are
all monitored.
"""

from __future__ import annotations

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import health  # noqa: E402


def _run(hass, entry):
    health.run_health_check(hass, entry)


def test_default_kill_switch_resolves_from_heartbeat():
    # The RUNNING engine reports the kill switch it actually uses on its heartbeat —
    # this is what covers a custom add-on `enable_flag` (the engine_config descriptor
    # always carries the documented default for the default room).
    hass = ha_stubs.FakeHass(
        states={
            "sensor.crop_steering_ai_heartbeat": ha_stubs.FakeState(
                "healthy",
                {"engine": "f2-control", "enable_flag": "input_boolean.my_kill"},
            ),
            "input_boolean.my_kill": ha_stubs.FakeState("on"),
            # the documented default is absent — must NOT be flagged, because it's
            # not the switch this install actually uses
        }
    )
    entry = ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}})
    _run(hass, entry)
    assert "kill_switch_missing" not in hass._issues


def test_default_kill_switch_resolves_from_descriptor():
    # No heartbeat yet (engine not started) — the descriptor's enable_flag is the fallback.
    hass = ha_stubs.FakeHass(
        states={
            "sensor.crop_steering_engine_config": ha_stubs.FakeState(
                "ok", {"prefix": "", "enable_flag": "input_boolean.my_kill"}
            ),
            "input_boolean.my_kill": ha_stubs.FakeState("on"),
        }
    )
    entry = ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}})
    _run(hass, entry)
    assert "kill_switch_missing" not in hass._issues


def test_default_kill_switch_missing_is_flagged():
    hass = ha_stubs.FakeHass(states={})  # nothing present at all
    entry = ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}})
    _run(hass, entry)
    assert "kill_switch_missing" in hass._issues


def test_named_room_kill_switch_is_monitored():
    # a second room whose per-room kill switch is MISSING must now be flagged
    hass = ha_stubs.FakeHass(states={})
    entry = ha_stubs.FakeEntry(
        data={"room_slug": "veg", "room_prefix": "veg_", "zones": {}},
        entry_id="veg",
    )
    _run(hass, entry)
    # per-room issue id so it doesn't clobber the default room's card
    assert "kill_switch_missing_veg" in hass._issues


def test_named_room_kill_switch_present_not_flagged():
    hass = ha_stubs.FakeHass(
        states={"switch.crop_steering_veg_engine_enabled": ha_stubs.FakeState("off")}
    )
    entry = ha_stubs.FakeEntry(
        data={"room_slug": "veg", "room_prefix": "veg_", "zones": {}},
        entry_id="veg",
    )
    _run(hass, entry)
    # switch exists (even though OFF) -> not "missing"
    assert "kill_switch_missing_veg" not in hass._issues


# ---------------------------------------------------------------- an engine that is behind
# The controller app is often started BEFORE the integration is set up (it is the first thing the
# install guide has you add). With no room to read, it builds its default room around the add-on's
# shipped `enable_flag` option, input_boolean.f2_control_enabled, and says so on its heartbeat. A
# fresh install never creates that helper: the wizard gives the room its own
# switch.crop_steering_engine_enabled. Until the controller adopts the new setup (up to
# rediscover_seconds, and only while everything reads OFF) its heartbeat still names the helper, and
# this check believed it: sixty seconds after a clean first setup, Repairs told a new operator to
# create a second kill switch by hand, one the room would never use.
LEGACY = "input_boolean.f2_control_enabled"
OWN = "switch.crop_steering_engine_enabled"


def _behind(*, heartbeat, descriptor, present):
    states = {
        "sensor.crop_steering_ai_heartbeat": ha_stubs.FakeState("healthy", heartbeat),
        "sensor.crop_steering_engine_config": ha_stubs.FakeState(
            "ok", {"prefix": "", **descriptor}
        ),
    }
    states.update({entity: ha_stubs.FakeState("off") for entity in present})
    hass = ha_stubs.FakeHass(states=states)
    _run(hass, ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}}))
    return hass._issues


def test_a_controller_started_before_setup_does_not_send_the_operator_to_create_a_helper():
    issues = _behind(
        heartbeat={"enable_flag": LEGACY, "setup_revision": 0},
        descriptor={"enable_flag": OWN, "setup_revision": 1},
        present=[OWN],
    )
    assert "kill_switch_missing" not in issues


def test_while_the_engine_is_behind_the_room_is_judged_on_the_kill_switch_it_is_moving_to():
    issues = _behind(
        heartbeat={"enable_flag": LEGACY, "setup_revision": 0},
        descriptor={"enable_flag": OWN, "setup_revision": 1},
        present=[
            LEGACY
        ],  # the flag being left behind exists; the one the room needs does not
    )
    assert "kill_switch_missing" in issues


def test_an_engine_that_is_up_to_date_is_still_believed_about_its_own_kill_switch():
    """Upgrade path: the heartbeat stays the authority whenever the engine is NOT behind, so a
    custom add-on `enable_flag` that has gone missing is still reported, even though the
    descriptor's documented default happens to exist."""
    issues = _behind(
        heartbeat={"enable_flag": "input_boolean.my_kill", "setup_revision": 3},
        descriptor={"enable_flag": LEGACY, "setup_revision": 3},
        present=[LEGACY],
    )
    assert "kill_switch_missing" in issues


def test_a_legacy_room_whose_helper_was_deleted_is_still_reported():
    issues = _behind(
        heartbeat={"enable_flag": LEGACY, "setup_revision": 0},
        descriptor={"enable_flag": LEGACY, "setup_revision": 0},
        present=[],
    )
    assert "kill_switch_missing" in issues


def test_a_controller_too_old_to_report_a_setup_revision_is_believed_as_before():
    """It never adopts a descriptor's kill switch, so the flag it names is the one that gates it."""
    issues = _behind(
        heartbeat={"enable_flag": LEGACY},
        descriptor={"enable_flag": OWN, "setup_revision": 1},
        present=[OWN],
    )
    assert "kill_switch_missing" in issues


def test_a_revision_that_is_not_a_plain_integer_never_counts_as_behind():
    for junk in (True, "2", 1.0, None):
        issues = _behind(
            heartbeat={"enable_flag": LEGACY, "setup_revision": 0},
            descriptor={"enable_flag": OWN, "setup_revision": junk},
            present=[OWN],
        )
        assert "kill_switch_missing" in issues, junk
