"""The substrate profile pack is one table, the substrates the integration offers, and its dryback
targets fit its own moisture ladder.

A dryback target is a percent of the day's peak. The P1 target is where the peak lands on a new
room, and the rescue floor (the P3 emergency threshold) waters the zone the moment it reads under it.
So a generative target is only reachable if the peak, dried back by it, still ends above the rescue
floor, and it only steers differently from vegetative if it is deeper.
"""

import importlib.util
from pathlib import Path

from custom_components.crop_steering.const import RECIPE_STAGES, SUBSTRATES

ROOT = Path(__file__).resolve().parents[1]


def table():
    path = ROOT / "crop-steering-engine/src/crop_steering_engine/defaults.py"
    spec = importlib.util.spec_from_file_location("defaults_table", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ladder_problems(profile):
    """What is wrong with a profile's dryback targets against its own peak and rescue floor."""
    peak = profile["vwc"]["p1_target_vwc"]
    rescue = profile["vwc"]["p3_emergency_vwc_threshold"]
    veg = profile["dryback"]["vegetative_dryback_target"]
    gen = profile["dryback"]["generative_dryback_target"]
    problems = []
    for name, target in (("vegetative", veg), ("generative", gen)):
        floor = peak * (1.0 - target / 100.0)
        if floor <= rescue:
            problems.append(
                f"{name} {target:g} % of a {peak:g} peak ends at {floor:g}, under the rescue {rescue:g}"
            )
    if gen <= veg:
        problems.append(f"generative {gen:g} % is not deeper than vegetative {veg:g} %")
    ladder = (
        profile["vwc"]["field_capacity"],
        peak,
        profile["vwc"]["p2_vwc_threshold"],
        rescue,
    )
    if not (ladder[0] >= ladder[1] > ladder[2] >= ladder[3] + 3.0):
        problems.append(
            f"field capacity, P1 target, P2 threshold, rescue {ladder} is not a ladder"
        )
    return problems


def test_the_integration_offers_exactly_the_profiles_the_pack_has():
    assert SUBSTRATES == list(table().SUBSTRATE_PROFILES)
    assert SUBSTRATES[0] == "generic"  # the select's default


def test_generic_starts_new_settings_where_the_table_does():
    t = table()
    generic = t.SUBSTRATE_PROFILES["generic"]
    for key, value in {**generic["vwc"], **generic["dryback"]}.items():
        assert value == t.ENTITY_DEFAULTS[key], key


def test_every_chosen_substrate_fits_its_own_ladder():
    for name, profile in table().SUBSTRATE_PROFILES.items():
        if name != "generic":
            assert ladder_problems(profile) == [], name


def test_generic_is_held_at_todays_values_and_its_one_known_gap_is_named():
    """generic keeps the new-room dryback targets rooms get today (35 % / 45 %). The 45 % generative
    target of a 65 peak ends at 35.75, under the 40 rescue, so on a new generic room the rescue waters
    first. Changing a generic number is a release decision of its own; this names the gap so that
    any change to it shows up here."""
    assert ladder_problems(table().SUBSTRATE_PROFILES["generic"]) == [
        "generative 45 % of a 65 peak ends at 35.75, under the rescue 40"
    ]


def test_the_curve_and_stage_map_agree_in_every_profile():
    for name, profile in table().SUBSTRATE_PROFILES.items():
        assert set(profile["stage_map"]) <= set(RECIPE_STAGES), name
        assert set(profile["stage_map"].values()) <= set(profile["curve"]), name
        assert set(profile["generative_stages"]) <= set(profile["curve"]), name
        lo, hi = profile["learner"]["p2_shot_range"]
        assert 0 < lo < hi, name
        assert len(profile["learner"]["ec_step"]) == 5, name
