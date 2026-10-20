"""Named-stage recipe model + the pure apply-target mapping.

Locks: the default recipe is complete (every stage carries every param) and sane,
the veg->ripen progression actually steers generative (VWC down, dryback up, EC up),
and build_targets maps a stage to the right global + per-zone number entities.
"""

from custom_components.crop_steering.const import (
    RECIPE_STAGES,
    RECIPE_PARAMS,
    DEFAULT_RECIPE,
)
from custom_components.crop_steering.recipe import build_targets


def test_default_recipe_is_complete_and_numeric():
    for stage in RECIPE_STAGES:
        assert stage in DEFAULT_RECIPE["stages"], f"missing stage {stage}"
        row = DEFAULT_RECIPE["stages"][stage]
        for param in RECIPE_PARAMS:
            assert param in row, f"{stage} missing {param}"
            assert isinstance(row[param], (int, float))
    assert DEFAULT_RECIPE["active_stage"] in RECIPE_STAGES


def test_default_recipe_values_in_sane_ranges():
    for stage in RECIPE_STAGES:
        r = DEFAULT_RECIPE["stages"][stage]
        assert 30 <= r["p1_target_vwc"] <= 90
        assert 30 <= r["p2_vwc_threshold"] <= r["p1_target_vwc"]  # floor below target
        assert 5 <= r["generative_dryback_target"] <= 60
        assert 5 <= r["p0_dryback_drop_percent"] <= 50
        assert 0.5 <= r["ec_target_gen_p1"] <= r["ec_target_gen_p2"] <= r["maximum_ec"]
        assert 1 <= r["p2_shot_size"] <= 15


def test_progression_steers_generative_veg_to_ripen():
    order = ["Veg", "Transition", "Bulk", "Ripen"]
    vwc = [DEFAULT_RECIPE["stages"][s]["p1_target_vwc"] for s in order]
    dry = [DEFAULT_RECIPE["stages"][s]["generative_dryback_target"] for s in order]
    ec = [DEFAULT_RECIPE["stages"][s]["ec_target_gen_p2"] for s in order]
    ceil = [DEFAULT_RECIPE["stages"][s]["maximum_ec"] for s in order]
    assert vwc == sorted(vwc, reverse=True)  # VWC target falls
    assert dry == sorted(dry)  # dryback deepens
    assert ec == sorted(ec)  # feed EC climbs
    assert ceil == sorted(ceil)  # EC ceiling climbs


def test_build_targets_global_and_per_zone():
    targets = build_targets("Bulk", DEFAULT_RECIPE, num_zones=3, prefix="")
    # each of 8 params -> 1 global + 3 per-zone = 4 entities
    assert len(targets) == len(RECIPE_PARAMS) * 4
    eids = {e for e, _ in targets}
    assert "number.crop_steering_p1_target_vwc" in eids
    assert "number.crop_steering_zone_1_p1_target_vwc" in eids
    assert "number.crop_steering_zone_3_maximum_ec" in eids
    # values match the Bulk row
    bulk = DEFAULT_RECIPE["stages"]["Bulk"]
    for eid, val in targets:
        if eid.endswith("p2_shot_size"):
            assert val == bulk["p2_shot_size"]


def test_build_targets_applies_room_prefix():
    targets = build_targets("Veg", DEFAULT_RECIPE, num_zones=1, prefix="flower_b_")
    eids = {e for e, _ in targets}
    assert "number.crop_steering_flower_b_p1_target_vwc" in eids
    assert "number.crop_steering_flower_b_zone_1_p1_target_vwc" in eids


def test_build_targets_unknown_stage_is_empty():
    assert build_targets("Nope", DEFAULT_RECIPE, num_zones=4, prefix="") == []
