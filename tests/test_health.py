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
