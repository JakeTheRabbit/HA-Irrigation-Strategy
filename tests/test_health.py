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


def test_default_kill_switch_resolves_from_descriptor():
    # add-on configured a NON-default kill switch, published on the descriptor
    hass = ha_stubs.FakeHass(
        states={
            "sensor.crop_steering_engine_config": ha_stubs.FakeState(
                "ok", {"prefix": "", "enable_flag": "input_boolean.my_kill"}
            ),
            "input_boolean.my_kill": ha_stubs.FakeState("on"),
            # the OLD hardcoded default is absent — must NOT be flagged, because it's
            # not the switch this install actually uses
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
