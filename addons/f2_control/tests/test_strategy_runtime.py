"""Opt-in continuous profiles, durable holds, and safe setup reconciliation."""

import json
from datetime import datetime, timedelta, timezone

import controller
import fake_ha
from strategy_runtime import parse_snapshot, parameter_override, strategy_block


def snapshot(now, prefix=""):
    parameters = {
        "dryback_target": 15,
        "ec_target_p0": 2.5,
        "ec_target_p1": 3.5,
        "ec_target_p2": 4.5,
        "p1_target_vwc": 62.5,
        "p2_vwc_threshold": 50,
        "p2_shot_size": 4,
        "p1_initial_shot_size": 6,
        "p3_emergency_vwc_threshold": 30,
        "p3_emergency_shot_size": 2,
    }
    return {
        "snapshot_version": 1,
        "room_id": f"room:{prefix}",
        "enabled": True,
        "updated_at": now.isoformat(),
        "valid_until": (now + timedelta(seconds=180)).isoformat(),
        "managed_zone_ids": [1],
        "zones": [{"zone_id": 1, "status": "active", "parameters": parameters}],
    }


def rig(monkeypatch, tmp_path):
    c = controller.Controller.__new__(controller.Controller)
    room = controller.Room(
        "default",
        "",
        {1: {}},
        {"pump": "switch.p", "mainline": "switch.m", "valves": {1: "switch.v"}},
        "switch.engine",
        "",
        "",
        10,
        22,
    )
    c.rooms = [room]
    c._saved_room_blocks = {}
    c._state_path = str(tmp_path / "state.json")
    c._defaulted_this_loop = set()
    c._fused_id_cache = {}
    c._load_room_state(room, {})
    monkeypatch.setattr(controller, "ha_get", lambda entity, **kwargs: (None, {}, None))
    return c, room


def test_old_install_has_no_strategy_influence_and_activated_missing_data_holds():
    now = datetime.now(timezone.utc)
    legacy = parse_snapshot(None, {}, "", now.timestamp())
    assert not legacy["required"] and strategy_block(legacy, 1) is None
    active = parse_snapshot(None, {}, "", now.timestamp(), was_required=True)
    assert "Strategy hold" in strategy_block(active, 1)


def test_fresh_default_uses_real_switch_without_changing_existing_legacy_helper(
    monkeypatch, tmp_path
):
    c, _room = rig(monkeypatch, tmp_path)
    descriptor = {
        "setup_revision": 1,
        "enable_flag": "switch.crop_steering_engine_enabled",
    }
    assert (
        c._default_enable_flag({}, descriptor) == "switch.crop_steering_engine_enabled"
    )
    monkeypatch.setattr(
        controller, "ha_get", lambda entity, **kwargs: ("off", {}, None)
    )
    assert c._default_enable_flag({}, descriptor) == "input_boolean.f2_control_enabled"
    assert (
        c._default_enable_flag({"enable_flag": "switch.custom"}, descriptor)
        == "switch.custom"
    )


def test_continuous_snapshot_controls_dryback_and_all_ec_phases_in_both_modes(
    monkeypatch, tmp_path
):
    c, room = rig(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    room.strategy_snapshot = parse_snapshot(
        "active", snapshot(now), "", now.timestamp()
    )
    for mode in (True, False):
        c._veg = lambda _room, _zone: mode
        params = c._params(room, 1)
        assert params.dryback_target == 15
        assert [params.ec_target_p0, params.ec_target_p1, params.ec_target_p2] == [
            2.5,
            3.5,
            4.5,
        ]
        assert params.p1_target == 62.5
    assert parameter_override(room.strategy_snapshot, 2, "p1_target_vwc") is None
    assert strategy_block(room.strategy_snapshot, 2) is None


def test_wrong_room_stale_incomplete_snapshot_never_falls_back():
    now = datetime.now(timezone.utc)
    for attrs in (
        snapshot(now, "f1_"),
        snapshot(now - timedelta(minutes=5)),
        {**snapshot(now), "zones": []},
    ):
        parsed = parse_snapshot("active", attrs, "", now.timestamp())
        assert parsed["required"] and parsed["error"]


def test_strategy_requirement_is_durable_and_missing_after_restart_holds(
    monkeypatch, tmp_path
):
    c, room = rig(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        controller, "ha_get", lambda entity, **kwargs: ("active", snapshot(now), None)
    )
    c._load_strategy_snapshot(room, now)
    assert (
        json.loads((tmp_path / "state.json").read_text())["default"][
            "_strategy_required"
        ]
        is True
    )
    c._load_room_state(room, c._read_state_file())
    monkeypatch.setattr(controller, "ha_get", lambda entity, **kwargs: (None, {}, None))
    c._load_strategy_snapshot(room, now)
    assert strategy_block(room.strategy_snapshot, 1)


def test_setup_revision_requires_old_and_new_hardware_off_and_preserves_archived_counters(
    monkeypatch, tmp_path
):
    c, room = rig(monkeypatch, tmp_path)
    room.state[2] = c._fresh_zone()
    room.state[2]["daily_vol"] = 19
    attrs = {
        "prefix": "",
        "setup_revision": 1,
        "active": True,
        "active_zone_ids": [1, 3],
        "pump": "switch.new",
        "mainline": "switch.m",
        "valves": {"1": "switch.v", "3": "switch.v3"},
        "enable_flag": "switch.engine",
    }
    monkeypatch.setattr(
        controller,
        "ha_get_all",
        lambda: [
            {"entity_id": "sensor.crop_steering_engine_config", "attributes": attrs}
        ],
    )
    states = {"switch.new": "on"}
    monkeypatch.setattr(
        controller,
        "ha_get",
        lambda entity, **kwargs: (states.get(entity, "off"), {}, None),
    )
    c._apply_setup_descriptors()
    assert room.hw["pump"] == "switch.p" and room._setup_pending
    states["switch.new"] = "off"
    c._apply_setup_descriptors()
    assert room.hw["pump"] == "switch.new" and set(room.zones) == {1, 3}
    assert room.state[2]["daily_vol"] == 19 and room.setup_revision == 1
    attrs.update(setup_revision=2, active=False)
    c._apply_setup_descriptors()
    assert room.setup_active is False
    assert "archived" in c._blocked(room, 1)


def test_snapshot_is_revalidated_before_next_shot_and_changed_parameters_require_recompute(
    monkeypatch, tmp_path
):
    c, room = rig(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    room.strategy_snapshot = parse_snapshot(
        "active", snapshot(now), "", now.timestamp()
    )
    room.strategy_required = True
    monkeypatch.setattr(
        controller,
        "ha_get",
        lambda entity, **kwargs: ("active", snapshot(now - timedelta(minutes=6)), None),
    )
    assert c._strategy_preflight(room, 1, now)
    room.strategy_snapshot = parse_snapshot(
        "active", snapshot(now), "", now.timestamp()
    )
    changed = snapshot(now)
    changed["zones"][0]["parameters"]["p1_target_vwc"] = 61
    monkeypatch.setattr(
        controller, "ha_get", lambda entity, **kwargs: ("active", changed, None)
    )
    assert "recompute" in c._strategy_preflight(room, 1, now)


def test_archived_default_is_gated_before_first_loop_even_if_flags_are_on(monkeypatch):
    fake = fake_ha.FakeHA()
    descriptor = {
        "prefix": "",
        "setup_revision": 2,
        "active": False,
        "active_zone_ids": [],
        "num_zones": 1,
        "pump": "switch.p",
        "mainline": "switch.m",
        "valves": {"1": "switch.v"},
        "enable_flag": "input_boolean.kill",
    }
    fake.set_state("sensor.crop_steering_engine_config", "ready", descriptor)
    for flag in (
        "input_boolean.kill",
        "switch.crop_steering_system_enabled",
        "switch.crop_steering_auto_irrigation_enabled",
        "switch.crop_steering_zone_1_enabled",
    ):
        fake.set_state(flag, "on")
    options = {
        "num_zones": 1,
        "enable_flag": "input_boolean.kill",
        "hardware": {
            "pump": "switch.p",
            "mainline": "switch.m",
            "valves": {"1": "switch.v"},
        },
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_get_all", "ha_set", "ha_call"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    monkeypatch.setattr(controller.Controller, "_read_state_file", lambda self: {})
    c = controller.Controller()
    assert c._blocked(c.rooms[0], 1)
    assert not fake.calls


def test_low_positive_flow_uses_real_hydraulics_without_hidden_denominator_floor(
    monkeypatch, tmp_path
):
    c, room = rig(monkeypatch, tmp_path)
    c._substrate_l = lambda room, zone: 6
    c._zone_flow_lps = lambda room, zone: 2 / 3600
    c._num = lambda entity, default: 900
    c._alert = lambda *args: None
    recorded = []
    c._execute_shot = lambda room, zone, duration, size: recorded.append(duration)
    c._act_zone(room, 1, None, None, (True, 6, "test"), None, True, datetime.now())
    assert recorded == [648]


def test_entire_batch_stays_invalid_after_change_release_or_transient_hold(
    monkeypatch, tmp_path
):
    c, room = rig(monkeypatch, tmp_path)
    room.zones[2] = {}
    now = datetime.now(timezone.utc)
    original = snapshot(now)
    original["managed_zone_ids"] = [1, 2]
    original["zones"].append({**original["zones"][0], "zone_id": 2})
    for event in ("change", "release", "hold"):
        room.strategy_snapshot = parse_snapshot("active", original, "", now.timestamp())
        room.strategy_required = True
        room._strategy_batch_invalid = False
        changed = json.loads(json.dumps(original))
        state = "active"
        if event == "change":
            for zone in changed["zones"]:
                zone["parameters"]["p2_shot_size"] = 2
        elif event == "release":
            state = "draft"
            changed.update(release_legacy=True, enabled=False)
        else:
            state = "error"
        monkeypatch.setattr(
            controller, "ha_get", lambda entity, **kw: (state, changed, None)
        )
        assert c._strategy_preflight(room, 1, now)
        if event == "hold":
            state, changed = "active", original
        assert c._strategy_preflight(room, 2, now), event


def test_new_zone_cannot_run_legacy_outside_active_strategy(monkeypatch, tmp_path):
    c, room = rig(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    room.zones[2] = {}
    monkeypatch.setattr(
        controller, "ha_get", lambda entity, **kw: ("active", snapshot(now), None)
    )
    c._load_strategy_snapshot(room, now)
    assert strategy_block(room.strategy_snapshot, 1)
    assert strategy_block(room.strategy_snapshot, 2)


def test_explicit_invalid_emitter_flow_cannot_use_legacy_fallback(
    monkeypatch, tmp_path
):
    c, room = rig(monkeypatch, tmp_path)
    c.flow_lps = 0.02
    monkeypatch.setattr(
        controller,
        "ha_get",
        lambda entity, **kw: (
            "0" if entity == "number.crop_steering_zone_1_dripper_flow_rate" else None,
            {},
            None,
        ),
    )
    assert c._zone_flow_lps(room, 1) == 0
