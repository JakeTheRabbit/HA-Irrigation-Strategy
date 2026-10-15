"""A batch recipe in whole mL, in the operator's order, and entered in parts (docs/DOSING.md, Configuration):
each fixed amount is stored rounded half up to whole mL; a dose may be given in parts of the
batch's "1 part (mL)", which is stored as its whole mL; and a setup saved before either existed
reads back unchanged."""

from copy import deepcopy

import pytest

from custom_components.crop_steering import dosing

PUMPS = [
    {
        "id": pump_id,
        "name": pump_id.title(),
        "volume_entity": f"number.{pump_id}_volume",
        "start_entity": f"button.{pump_id}_start",
        "dosing_entity": f"sensor.{pump_id}_status",
        "power_entity": f"switch.{pump_id}_power",
        "flow_entity": f"number.{pump_id}_flow",
        "max_ml": 500,
    }
    for pump_id in ("part_a", "part_b", "boost")
]


def clean(recipe, **batch):
    return dosing.clean(deepcopy(PUMPS), {**batch, "recipe": recipe})[1]


def test_the_recipe_doses_in_the_order_it_is_saved_in():
    order = ["boost", "part_b", "part_a"]
    batch = clean([{"pump": pump, "ml": 10} for pump in order])
    assert [line["pump"] for line in batch["recipe"]] == order


@pytest.mark.parametrize(
    "ml, stored", [(12.5, 13), (12.49, 12), (0.5, 1), (0.4, 0), (300, 300)]
)
def test_a_fixed_amount_is_stored_in_whole_ml_rounded_half_up(ml, stored):
    [line] = clean([{"pump": "part_a", "ml": ml}])["recipe"]
    assert line["ml"] == stored and isinstance(line["ml"], int)


def test_a_dose_in_parts_is_stored_as_whole_ml_of_the_batch_one_part():
    batch = clean(
        [
            {"pump": "part_a", "parts": 2},
            {"pump": "part_b", "parts": 1.5},
            {"pump": "boost", "ml": 7},
        ],
        part_ml=12.5,
    )
    assert batch["part_ml"] == 12.5
    assert batch["recipe"] == [
        {"pump": "part_a", "ml": 25, "ml_entity": None, "parts": 2},
        {"pump": "part_b", "ml": 19, "ml_entity": None, "parts": 1.5},  # 18.75
        {"pump": "boost", "ml": 7, "ml_entity": None},
    ]
    # Read back at start-up, a setup in parts is the same setup.
    assert dosing.clean(deepcopy(PUMPS), deepcopy(batch))[1] == batch


def test_a_new_one_part_moves_every_dose_in_parts():
    recipe = [{"pump": "part_a", "parts": 2, "ml": 25}, {"pump": "boost", "ml": 7}]
    batch = clean(recipe, part_ml=20)
    assert [line["ml"] for line in batch["recipe"]] == [40, 7]


@pytest.mark.parametrize(
    "recipe, part_ml, message",
    [
        ([{"pump": "part_a", "parts": 2}], None, "set how many mL 1 part is"),
        (
            [{"pump": "part_a", "parts": 30}],
            20,
            "30 parts is 600 mL, more than its 500",
        ),
        ([{"pump": "part_a", "parts": -1}], 20, "(parts) must be between 0 and 100"),
        ([{"pump": "part_a", "parts": "two"}], 20, "(parts) must be a number"),
        ([], 0, "1 part (mL) must be between 0.1 and 5000"),
    ],
)
def test_a_dose_in_parts_that_cannot_be_dosed_is_refused(recipe, part_ml, message):
    batch = {"recipe": recipe}
    if part_ml is not None:
        batch["part_ml"] = part_ml
    with pytest.raises(
        dosing.DosingError, match=message.replace("(", r"\(").replace(")", r"\)")
    ):
        dosing.clean(deepcopy(PUMPS), batch)


def test_a_setup_saved_before_parts_reads_back_unchanged():
    stored = {
        **dosing.empty_batch(),
        "recipe": [
            {"pump": "part_a", "ml": 400, "ml_entity": None},
            {"pump": "boost", "ml": 0, "ml_entity": "number.recipe_boost"},
        ],
    }
    assert dosing.clean(deepcopy(PUMPS), deepcopy(stored))[1] == stored
    assert "part_ml" not in dosing.empty_batch()
