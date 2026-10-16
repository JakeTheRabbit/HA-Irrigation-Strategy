"""The one defaults table moves no value an installed room uses.

Before the table, the same settings had two sets of built-in values: the integration's entity defaults
(number.py) and the controller's fallbacks (what it uses when neither the zone's nor the room's setting
can be read, around a Home Assistant restart for example). They disagree for some settings, and both
are what installed rooms run on today. The table keeps both columns, so this pins each column to the
values the release before it shipped (the AI assistant 3.11.1, commit 12c6d1a), plus the P3 Time Between Shots
added since at 10 minutes in both, the source-water pH band a new room starts with, 5.5-6.5 (a
room that has a band keeps its own), the pump prime and main-line lead, at the 2 s and 1 s the
controller always waited, in both, the P2 Time Between Shots at 0 (off) in both, and the EC-correction
minimum interval at the 10 minutes the engine always used. Making the columns agree is a change of its
own, with a bold line
in the changelog; it is never a side effect of editing the table.

The controller half is checked where it is used: every _zone_num call reads its fallback from the
table, under its own setting's name, so no number can be typed beside a call site again.
"""

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "addons/f2_control/f2_control/controller.py"


def table():
    """The table's source module, loaded from its file (it imports nothing)."""
    path = ROOT / "crop-steering-engine/src/crop_steering_engine/defaults.py"
    spec = importlib.util.spec_from_file_location("defaults_table", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# number.py DEFAULT_VALUES at 12c6d1a, and the per-zone plant count and daily cap defaults beside it,
# plus P3 Time Between Shots (10 minutes), the sump pump's run threshold (the 20 W the controller
# always compared with) and the minimum daily water per plant (0), all added after it, the pump
# prime and main-line lead (2 s and 1 s, the waits 12c6d1a's controller had fixed), P2 Time Between
# Shots (0, off) and the EC-correction minimum interval (10 minutes, the gap the engine always used).
ENTITY_DEFAULTS_12C6D1A = {
    "max_shot_duration": 900,
    "substrate_volume": 10.0,
    "dripper_flow_rate": 1.2,
    "drippers_per_plant": 2,
    "field_capacity": 70.0,
    "maximum_ec": 9.0,
    "watchdog_hours": 3.0,
    "vegetative_dryback_target": 35.0,  # a new room's, since; a room set up before keeps 50
    "generative_dryback_target": 45.0,  # a new room's, since; a room set up before keeps 40
    "p1_target_vwc": 65.0,
    "p2_vwc_threshold": 60.0,
    "p0_maximum_wait_time": 120.0,
    "p0_dryback_drop_percent": 15.0,
    "p1_initial_shot_size": 2.0,
    "p1_shot_size_increment": 0.5,
    "p1_time_between_shots": 15.0,
    "p1_maximum_shots": 6.0,
    "p1_minimum_shots": 3.0,
    "p2_shot_size": 5.0,
    "p2_time_between_shots": 0.0,  # added after it: off, as top-ups always went
    "p2_ec_high_threshold": 1.2,
    "p2_ec_low_threshold": 0.8,
    "p3_emergency_vwc_threshold": 40.0,
    "p3_emergency_shot_size": 2.0,
    "ec_target_veg_p0": 3.0,
    "ec_target_veg_p1": 3.0,
    "ec_target_veg_p2": 3.2,
    "ec_target_veg_p3": 3.0,
    "ec_target_gen_p0": 4.0,
    "ec_target_gen_p1": 5.0,
    "ec_target_gen_p2": 6.0,
    "ec_target_gen_p3": 4.5,
    "irrigation_ph_min": 5.5,
    "irrigation_ph_max": 6.5,
    "irrigation_ec_min": 0.0,
    "irrigation_ec_max": 0.0,
    "lights_on_hour": 12,
    "lights_off_hour": 0,
    "plant_count": 4,
    "max_daily_volume": 20.0,
    "p3_time_between_shots": 10.0,
    "sump_power_threshold_w": 20.0,
    "p1_rise_pts": 0.5,
    "p1_maximum_extra_shots": 3.0,
    "min_daily_ml_per_plant": 0.0,  # added after it: off, as the missing helper read
    "pump_prime_time": 2.0,
    "main_line_lead_time": 1.0,
    "ec_min_interval": 10.0,
    # added after it, each off (or the engine's own value) so nothing waters differently on update
    "p0_minimum_wait": 0.0,
    "ec_flush_target": 0.0,
    "p2_dilute_ratio": 1.2,
    "p2_timed_interval_min": 60.0,
    "p2_timed_shot_size": 0.0,
    "p2_timed_first_hours": 0.0,
    "p2_end_hours_before_off": 0.0,
    "setpoint_max_step_per_day": 1.0,  # the controller's FC_STEP_MAX
    # added after it, the runoff estimator's calibration: 0 is unknown, as no estimate was made
    "sump_litres_per_run": 0.0,
    "sump_pump_flow_lpm": 0.0,
    "runoff_attribution_min": 90.0,
    "hvac_run_power_w": 50.0,
    "cwsi_lower_baseline": 0.0,  # added after it: both 0 is off (the plant-stress card's CWSI)
    "cwsi_upper_baseline": 0.0,
}

# The literal at each controller _zone_num call site at 12c6d1a, plus P3 Time Between Shots, the P1 rise
# and extra-shot settings (the engine constants P1_RISE_PTS and P1_MAX_EXTRA_SHOTS), and the pump prime
# and main-line lead it waited as fixed sleeps, P2 Time Between Shots and the EC-correction minimum interval
# (the engine's own 10 minutes before it was a setting).
CONTROLLER_FALLBACKS_12C6D1A = {
    "p2_vwc_threshold": 45,
    "p1_target_vwc": 60,
    "field_capacity": 70,
    "p3_emergency_vwc_threshold": 40,
    "p2_shot_size": 5,
    "p2_time_between_shots": 0.0,  # added after it: off, as top-ups always went
    "p1_initial_shot_size": 2,
    "p1_shot_size_increment": 0.5,
    "p1_maximum_shots": 12,
    "p1_minimum_shots": 0,
    "p1_time_between_shots": 15,
    "vegetative_dryback_target": 20,
    "generative_dryback_target": 20,
    "p0_maximum_wait_time": 45,
    "ec_target_veg_p0": 4,
    "ec_target_veg_p1": 5,
    "ec_target_veg_p2": 6,
    "ec_target_gen_p0": 4,
    "ec_target_gen_p1": 5,
    "ec_target_gen_p2": 6,
    "p3_emergency_shot_size": 2,
    "max_daily_volume": 150,
    "maximum_ec": 9,
    "watchdog_hours": 3,
    "plant_count": 0,
    "drippers_per_plant": 1,
    "p3_time_between_shots": 10.0,
    "p1_rise_pts": 0.5,
    "p1_maximum_extra_shots": 3,
    "pump_prime_time": 2.0,
    "main_line_lead_time": 1.0,
    "p0_additional_dryback": 0,  # added after it: off, as P0 always was
    "ec_min_interval": 10.0,
    # added after it, each off (or the engine's own value) so nothing waters differently on update
    "p0_minimum_wait": 0.0,
    "ec_flush_target": 0.0,
    "p2_dilute_ratio": 1.2,  # the engine's literal dilute ratio, read only behind its opt-in switch
    "p2_timed_interval_min": 60.0,
    "p2_timed_shot_size": 0.0,
    "p2_timed_first_hours": 0.0,
    "p2_end_hours_before_off": 0.0,
}


def test_every_entity_default_is_the_one_installed_rooms_were_given():
    assert table().ENTITY_DEFAULTS == ENTITY_DEFAULTS_12C6D1A


def test_every_controller_fallback_is_the_one_installed_controllers_use():
    assert table().CONTROLLER_FALLBACKS == CONTROLLER_FALLBACKS_12C6D1A


def test_the_columns_differ_only_where_they_already_did():
    """Listed so a change to either side shows up here by name, not as a silent move."""
    t = table()
    differ = {
        key
        for key, (entity, fallback) in t.DEFAULTS.items()
        if entity is not None and fallback is not None and entity != fallback
    }
    assert differ == {
        "drippers_per_plant",
        "plant_count",
        "max_daily_volume",
        "vegetative_dryback_target",
        "generative_dryback_target",
        "p0_maximum_wait_time",
        "p1_target_vwc",
        "p1_maximum_shots",
        "p1_minimum_shots",
        "p2_vwc_threshold",
        "ec_target_veg_p0",
        "ec_target_veg_p1",
        "ec_target_veg_p2",
    }


def test_new_rooms_are_offered_the_sizing_their_numbers_would_start_at():
    t = table()
    assert t.SIZING_DEFAULTS == {
        "substrate_volume": 10.0,
        "plant_count": 4,
        "drippers_per_plant": 2,
        "dripper_flow_rate": 1.2,
    }
    assert all(t.SIZING_DEFAULTS[k] == t.ENTITY_DEFAULTS[k] for k in t.SIZING_DEFAULTS)


def _zone_num_calls():
    tree = ast.parse(CONTROLLER.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_zone_num"
    ]


# Call sites whose fallback is not a fixed value, and so not in the table: the substrate falls back to
# the add-on's substrate_l option, the dripper flow to the room's own setting, the minimum daily water
# to the old input_number helper, the floor's drown ceiling to field capacity plus a margin (it was a
# fixed 90 until the minimum daily water became a setting), and one P2 read wants no value at all when
# the setting is missing. None of them may be a number typed at the call site.
NOT_FROM_THE_TABLE = {
    "substrate_volume",
    "dripper_flow_rate",
    "p2_vwc_threshold",
    "min_daily_ml_per_plant",
    "min_floor_drown_ceiling",
}


def test_every_controller_fallback_is_read_from_the_table_under_its_own_name():
    calls = _zone_num_calls()
    assert len(calls) > 20, "the scan found too few call sites: fix the test"
    read = set()
    for call in calls:
        suffix, fallback = call.args[2], call.args[3]
        where = f"controller.py:{call.lineno} falls back to {ast.unparse(fallback)}"
        if (
            isinstance(fallback, ast.Subscript)
            and isinstance(fallback.value, ast.Name)
            and fallback.value.id == "FALLBACK"
        ):
            assert ast.dump(fallback.slice) == ast.dump(suffix), where
            read.add(suffix.value if isinstance(suffix, ast.Constant) else None)
        elif isinstance(fallback, ast.Constant) and fallback.value is None:
            continue  # read only to note it was read (_settings_hold): no value is used
        else:
            assert isinstance(suffix, ast.Constant), where
            assert suffix.value in NOT_FROM_THE_TABLE, where
            assert not (
                isinstance(fallback, ast.Constant)
                and isinstance(fallback.value, (int, float))
            ), where
    # Every controller fallback in the table is used by some call site (the dryback and EC
    # target keys are read through a name built from the steering mode).
    templated = {
        key
        for key in table().CONTROLLER_FALLBACKS
        if key.startswith(("ec_target_", "vegetative_", "generative_"))
    }
    assert (read - {None}) | templated == set(table().CONTROLLER_FALLBACKS)
