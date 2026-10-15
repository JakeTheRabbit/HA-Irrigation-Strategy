"""Tests for the per-room Repairs health checks (#22).

Confirms the kill-switch / heartbeat health checks resolve per room instead of
hardcoding one site's default, so a custom default kill switch and additional rooms are
all monitored.
"""

from __future__ import annotations

from datetime import datetime, timezone

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


# ---------------------------------------------------------------- the grow-strategy plan
# Every hold of a room's plan is a Repairs card: while it lasts the controller waters the zones the plan
# manages only with emergency, watchdog and minimum-daily shots. It used to be visible only on the
# plan's own sensor.
PLAN = "sensor.crop_steering_strategy_plan"
BEAT = "sensor.crop_steering_ai_heartbeat"


def _plan_issues(plan=None, heartbeat=None):
    now = datetime.now(timezone.utc)
    states = {"switch.crop_steering_engine_enabled": ha_stubs.FakeState("off")}
    if plan is not None:
        states[PLAN] = ha_stubs.FakeState(plan[0], plan[1], now)
    states[BEAT] = ha_stubs.FakeState(
        "healthy",
        {"enable_flag": "switch.crop_steering_engine_enabled", **(heartbeat or {})},
        now,
    )
    hass = ha_stubs.FakeHass(states=states)
    _run(hass, ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}}))
    return hass._issues


def test_a_plan_in_error_is_an_error_card_that_says_why():
    issues = _plan_issues(
        ("error", {"error": "Strategy zones do not match room setup"})
    )
    card = issues["strategy_hold"]
    assert card["severity"] == "error"
    assert card["translation_placeholders"]["reason"].startswith("Strategy zones")


def test_a_controller_holding_on_a_plan_it_cannot_use_is_an_error_card():
    issues = _plan_issues(
        ("active", {"zones": [{"zone_id": 1, "status": "active"}]}),
        {"strategy_error": "Strategy snapshot is stale"},
    )
    assert issues["strategy_hold"]["severity"] == "error"
    assert "stale" in issues["strategy_hold"]["translation_placeholders"]["reason"]


def test_a_zone_the_plan_does_not_steer_today_is_a_warning_card():
    zones = [{"zone_id": 1, "status": "active"}, {"zone_id": 2, "status": "complete"}]
    issues = _plan_issues(("active", {"zones": zones}))
    assert issues["strategy_hold"]["severity"] == "warning"
    assert (
        "zone 2 (complete)"
        in issues["strategy_hold"]["translation_placeholders"]["reason"]
    )


def test_a_plan_behind_on_its_day_is_a_warning_and_a_healthy_plan_is_no_card():
    degraded = {
        "zones": [{"zone_id": 1, "status": "active"}],
        "degraded_reason": "heartbeat",
    }
    issues = _plan_issues(("active", degraded))
    assert issues["strategy_degraded"]["severity"] == "warning"
    assert "strategy_hold" not in issues
    healthy = _plan_issues(("active", {"zones": [{"zone_id": 1, "status": "active"}]}))
    assert "strategy_hold" not in healthy and "strategy_degraded" not in healthy
    assert not {"strategy_hold", "strategy_degraded"} & set(_plan_issues())


def test_a_room_switched_off_clears_its_plan_cards():
    hass = ha_stubs.FakeHass(
        states={
            "switch.crop_steering_room_active": ha_stubs.FakeState("off"),
            PLAN: ha_stubs.FakeState("error", {"error": "x"}),
        }
    )
    hass._issues["strategy_hold"] = {"severity": "error"}
    _run(hass, ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}}))
    assert "strategy_hold" not in hass._issues


# ---------------------------------------------------------------- the card names the running gate
# One gate per room, and only the running controller knows which: the heartbeat names it unless it
# is behind the published setup. The kill-switch card names the switch the room stops on. A card of
# its own says the room's Engine Enabled switch does not stop water, whenever a current heartbeat
# names another gate: with that gate present and ON, an operator switching Engine Enabled OFF
# expects water to stop, and it does not.
NOT_GATE = "engine_switch_not_gate"


def _card(**kw):
    return _behind(**kw)["kill_switch_missing"]["translation_placeholders"]


def test_the_card_names_the_gate_the_controller_reports():
    card = _card(
        heartbeat={"enable_flag": "input_boolean.my_kill", "setup_revision": 3},
        descriptor={"enable_flag": OWN, "setup_revision": 3},
        present=[OWN],
    )
    assert card["kill_switch"] == "input_boolean.my_kill"
    assert card["source"] == "the one its controller reports"


def test_with_the_controller_behind_the_card_names_the_published_gate():
    card = _card(
        heartbeat={"enable_flag": LEGACY, "setup_revision": 0},
        descriptor={"enable_flag": "input_boolean.my_kill", "setup_revision": 1},
        present=[OWN],
    )
    assert card["kill_switch"] == "input_boolean.my_kill"
    assert card["source"].startswith("as the room's setup publishes it")


def test_a_current_heartbeat_naming_another_gate_says_engine_enabled_does_not_stop_water():
    # The gate is there: no kill-switch card, and still this one.
    issues = _behind(
        heartbeat={"enable_flag": LEGACY, "setup_revision": 0},
        descriptor={"enable_flag": LEGACY, "setup_revision": 0},
        present=[LEGACY, OWN],
    )
    assert "kill_switch_missing" not in issues
    assert issues[NOT_GATE]["severity"] == "warning"
    assert issues[NOT_GATE]["translation_placeholders"] == {
        "kill_switch": LEGACY,
        "engine_switch": OWN,
    }


def test_only_a_current_heartbeat_says_engine_enabled_does_not_stop_water():
    # Behind the published setup: the gate it names is the one being left behind.
    assert NOT_GATE not in _behind(
        heartbeat={"enable_flag": LEGACY, "setup_revision": 0},
        descriptor={"enable_flag": "input_boolean.my_kill", "setup_revision": 1},
        present=[LEGACY, "input_boolean.my_kill", OWN],
    )
    # No heartbeat: the descriptor's flag is only what the setup publishes.
    hass = ha_stubs.FakeHass(
        states={
            "sensor.crop_steering_engine_config": ha_stubs.FakeState(
                "ok", {"prefix": "", "enable_flag": LEGACY, "setup_revision": 0}
            ),
            LEGACY: ha_stubs.FakeState("on"),
            OWN: ha_stubs.FakeState("off"),
        }
    )
    _run(hass, ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}}))
    assert NOT_GATE not in hass._issues
    # A stale heartbeat: the controller is not running, and may start on another gate.
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
    hass = ha_stubs.FakeHass(
        states={
            BEAT: ha_stubs.FakeState("healthy", {"enable_flag": LEGACY}, stale),
            LEGACY: ha_stubs.FakeState("on"),
            OWN: ha_stubs.FakeState("off"),
        }
    )
    _run(hass, ha_stubs.FakeEntry(data={"room_slug": "default", "zones": {}}))
    assert "engine_offline" in hass._issues and NOT_GATE not in hass._issues


def test_no_card_says_the_gate_itself_does_not_stop_water():
    # The room stops on its own Engine Enabled switch.
    assert NOT_GATE not in _behind(
        heartbeat={"enable_flag": OWN, "setup_revision": 1},
        descriptor={"enable_flag": OWN, "setup_revision": 1},
        present=[OWN, LEGACY],
    )
    # Another gate, and no Engine Enabled switch in the room: nothing to say about one.
    assert NOT_GATE not in _behind(
        heartbeat={
            "enable_flag": "switch.crop_steering_veg_engine_enabled",
            "setup_revision": 1,
        },
        descriptor={"enable_flag": OWN, "setup_revision": 1},
        present=["switch.crop_steering_veg_engine_enabled"],
    )


def test_a_named_room_card_says_its_engine_switch_does_not_stop_water_until_switched_off():
    veg_own = "switch.crop_steering_veg_engine_enabled"
    states = {
        "sensor.crop_steering_veg_ai_heartbeat": ha_stubs.FakeState(
            "healthy", {"enable_flag": "input_boolean.veg_kill", "setup_revision": 2}
        ),
        "sensor.crop_steering_veg_engine_config": ha_stubs.FakeState(
            "ok", {"prefix": "veg_", "enable_flag": veg_own, "setup_revision": 2}
        ),
        veg_own: ha_stubs.FakeState("on"),
    }
    hass = ha_stubs.FakeHass(states=states)
    entry = ha_stubs.FakeEntry(
        data={"room_slug": "veg", "room_prefix": "veg_", "zones": {}}, entry_id="veg"
    )
    _run(hass, entry)
    card = hass._issues["kill_switch_missing_veg"]["translation_placeholders"]
    assert card["kill_switch"] == "input_boolean.veg_kill"
    assert hass._issues[f"{NOT_GATE}_veg"]["translation_placeholders"] == {
        "kill_switch": "input_boolean.veg_kill",
        "engine_switch": veg_own,
    }
    hass.states.set("input_boolean.veg_kill", "on")  # its gate back: that card stays
    _run(hass, entry)
    assert "kill_switch_missing_veg" not in hass._issues
    assert f"{NOT_GATE}_veg" in hass._issues
    hass.states.set("switch.crop_steering_veg_room_active", "off")
    _run(hass, entry)
    assert f"{NOT_GATE}_veg" not in hass._issues
