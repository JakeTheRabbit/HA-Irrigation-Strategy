"""Batch-tank dosing, the pure rules (docs/DOSING.md, Validation): each entity in its allowed domain
and present, pump ids unique, a recipe that doses only pumps that exist and each at most once, a
fill valve only with its full entity, a mix pump minimum power only with its power sensor, and no
switch that is both a pump's power and batch hardware. Plus the request checks and when a request
still counts as waiting for the controller."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.crop_steering import dosing

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
PUMP = {
    "id": "balance",
    "name": "Balance",
    "volume_entity": "number.doser_balance_volume",
    "start_entity": "button.doser_balance_start",
    "dosing_entity": "sensor.doser_balance_status",
    "power_entity": "switch.doser_balance_power",
    "flow_entity": "number.doser_balance_flow",
    "max_ml": 2000,
}
BATCH = {
    "fill_valve": "switch.tank_fill",
    "full_entity": "binary_sensor.tank_full",
    "mix_pump": "switch.tank_mixer",
    "mix_valves": ["switch.mix_return"],
    "mix_power_sensor": "sensor.tank_mixer_power",
    "mix_min_w": 200,
    "close_entities": ["switch.f1_feed"],
    "hold_entity": "input_boolean.tank_dosing",
    "filled_at_entity": "input_datetime.tank_filled_at",
    "recipe": [{"pump": "balance", "ml": 300, "ml_entity": "number.recipe_balance"}],
}
KNOWN = {
    *(value for key, value in PUMP.items() if key.endswith("_entity")),
    "switch.tank_fill",
    "binary_sensor.tank_full",
    "switch.tank_mixer",
    "switch.mix_return",
    "sensor.tank_mixer_power",
    "switch.f1_feed",
    "input_boolean.tank_dosing",
    "input_datetime.tank_filled_at",
    "number.recipe_balance",
}


def clean(pumps=None, batch=None, exists=KNOWN.__contains__, stock_tanks=None):
    return dosing.clean(
        [deepcopy(PUMP)] if pumps is None else pumps,
        deepcopy(BATCH) if batch is None else batch,
        exists,
        stock_tanks,
    )


def pump(**changes):
    return {**deepcopy(PUMP), **changes}


def batch(**changes):
    return {**deepcopy(BATCH), **changes}


def test_a_room_with_no_pumps_is_valid_and_does_nothing():
    pumps, cleaned = dosing.clean([], None)
    assert pumps == [] and cleaned == dosing.empty_batch()
    assert cleaned["recipe"] == [] and cleaned["fill_valve"] is None
    assert dosing.empty()["revision"] == 0 and dosing.empty()["request"] is None


def test_a_full_setup_is_stored_with_its_defaults():
    [stored], cleaned = clean()
    assert stored == {
        **PUMP,
        "dosing_prefix": "Dosing",
        "restore_volume": True,
        "stock_tank": None,
    }
    assert list(stored) == [
        "id",
        "name",
        "volume_entity",
        "start_entity",
        "dosing_entity",
        "dosing_prefix",
        "power_entity",
        "flow_entity",
        "max_ml",
        "restore_volume",
        "stock_tank",
    ]
    assert cleaned["full_state"] == "on" and cleaned["fill_timeout_min"] == 20
    assert (cleaned["premix_min"], cleaned["postmix_min"]) == (2, 5)
    assert cleaned["recipe"] == [
        {"pump": "balance", "ml": 300, "ml_entity": "number.recipe_balance"}
    ]
    # Given values are kept, and an empty text field takes its default.
    [kept], again = clean(
        [pump(dosing_prefix="Busy", restore_volume=False)],
        batch(full_state="", fill_timeout_min=35, premix_min=0, postmix_min=60),
    )
    assert (kept["dosing_prefix"], kept["restore_volume"]) == ("Busy", False)
    assert again["full_state"] == "on" and again["fill_timeout_min"] == 35
    assert (again["premix_min"], again["postmix_min"]) == (0, 60)


@pytest.mark.parametrize(
    "field, entity",
    [
        ("volume_entity", "sensor.doser_balance_volume"),
        ("start_entity", "switch.doser_balance_start"),
        ("dosing_entity", "switch.doser_balance_status"),
        ("power_entity", "input_boolean.doser_balance_power"),
        ("flow_entity", "button.doser_balance_flow"),
    ],
)
def test_every_pump_entity_is_in_its_allowed_domain(field, entity):
    with pytest.raises(dosing.DosingError, match="must be a"):
        clean([pump(**{field: entity})])


@pytest.mark.parametrize(
    "field, entity",
    [
        ("volume_entity", "input_number.doser_balance_volume"),
        ("start_entity", "input_button.doser_balance_start"),
        ("start_entity", "script.doser_balance_start"),
        ("dosing_entity", "binary_sensor.doser_balance_dosing"),
        ("flow_entity", "sensor.doser_balance_flow"),
        ("flow_entity", "input_number.doser_balance_flow"),
    ],
)
def test_every_allowed_domain_is_accepted(field, entity):
    [stored], _ = clean([pump(**{field: entity})], exists=None)
    assert stored[field] == entity


@pytest.mark.parametrize(
    "field, entity",
    [
        ("fill_valve", "input_boolean.tank_fill"),
        ("full_entity", "switch.tank_full"),
        ("mix_pump", "input_boolean.tank_mixer"),
        ("mix_power_sensor", "number.tank_mixer_power"),
        ("hold_entity", "switch.tank_dosing"),
        ("filled_at_entity", "sensor.tank_filled_at"),
    ],
)
def test_every_batch_entity_is_in_its_allowed_domain(field, entity):
    with pytest.raises(dosing.DosingError, match="must be a"):
        clean(batch=batch(**{field: entity}))


def test_lists_of_switches_and_the_recipe_entity_are_checked_too():
    for changes in (
        {"mix_valves": ["input_boolean.mix_return"]},
        {"close_entities": ["number.f1_feed"]},
        {"recipe": [{"pump": "balance", "ml": 300, "ml_entity": "switch.x"}]},
    ):
        with pytest.raises(dosing.DosingError, match="must be a"):
            clean(batch=batch(**changes))
    with pytest.raises(dosing.DosingError, match="not a"):
        clean(batch=batch(fill_valve="not a entity"))


def test_every_entity_must_exist_in_home_assistant():
    with pytest.raises(dosing.DosingError, match="does not exist"):
        clean(exists=(KNOWN - {"button.doser_balance_start"}).__contains__)
    with pytest.raises(dosing.DosingError, match="does not exist"):
        clean(exists=(KNOWN - {"switch.f1_feed"}).__contains__)
    # A stored setup read back before its devices return is not thrown away.
    assert clean(exists=None)[0][0]["id"] == "balance"


def test_pump_ids_are_unique_well_formed_or_made_from_the_name():
    with pytest.raises(dosing.DosingError, match="two pumps have the id balance"):
        clean([pump(), pump(name="Balance B", power_entity="switch.other")])
    for bad in ("Balance", "bal-ance", "x" * 25):
        with pytest.raises(dosing.DosingError, match="id must be"):
            clean([pump(id=bad)])
    # A pump sent without an id gets one from its name, never one another pump was sent with.
    first, second = clean(
        [pump(id=None, name="Balance"), pump(name="Base", id="balance")],
        batch(recipe=[]),
    )[0]
    assert (first["id"], second["id"]) == ("balance_2", "balance")
    with pytest.raises(dosing.DosingError, match="name of 1 to 40"):
        clean([pump(name="  ")])
    with pytest.raises(dosing.DosingError, match="name of 1 to 40"):
        clean([pump(name="x" * 41)])


def test_numbers_are_numbers_inside_their_ranges():
    for bad in (0, 5001, "lots", None, True, float("nan")):
        with pytest.raises(dosing.DosingError, match="max mL"):
            clean([pump(max_ml=bad)])
    for field, bad in (
        ("fill_timeout_min", 0),
        ("fill_timeout_min", 61),
        ("premix_min", 31),
        ("postmix_min", 61),
        ("mix_min_w", -1),
    ):
        with pytest.raises(dosing.DosingError, match="between"):
            clean(batch=batch(**{field: bad}))
    with pytest.raises(dosing.DosingError, match="true or false"):
        clean([pump(restore_volume="yes")])


def test_the_recipe_doses_pumps_that_exist_once_each_within_their_maximum():
    with pytest.raises(dosing.DosingError, match="not set up"):
        clean(batch=batch(recipe=[{"pump": "bloom", "ml": 10}]))
    with pytest.raises(dosing.DosingError, match="twice"):
        clean(batch=batch(recipe=[{"pump": "balance", "ml": 10}, {"pump": "balance"}]))
    with pytest.raises(dosing.DosingError, match="between 0 and 2000"):
        clean(batch=batch(recipe=[{"pump": "balance", "ml": 2001}]))
    # 0 skips the pump; the order is the dose order.
    bloom = pump(id="bloom", name="Bloom", power_entity="switch.doser_bloom_power")
    _, cleaned = clean(
        [pump(), bloom],
        batch(recipe=[{"pump": "bloom", "ml": 1800}, {"pump": "balance", "ml": 0}]),
        exists=None,
    )
    assert [(r["pump"], r["ml"], r["ml_entity"]) for r in cleaned["recipe"]] == [
        ("bloom", 1800, None),
        ("balance", 0, None),
    ]


def test_a_fill_valve_needs_its_full_entity():
    with pytest.raises(dosing.DosingError, match="needs the entity"):
        clean(batch=batch(full_entity=None))
    # No fill valve: the batch starts with the tank already filled.
    _, cleaned = clean(batch=batch(fill_valve=None, full_entity=None))
    assert cleaned["fill_valve"] is None


def test_a_mix_pump_minimum_power_needs_the_sensor_that_reads_it():
    """Without the sensor the controller could not check the power, and would mix unchecked."""
    with pytest.raises(dosing.DosingError, match="needs the mix pump power sensor"):
        clean(batch=batch(mix_power_sensor=None))
    # No minimum, no sensor needed; a sensor with no minimum is kept for the page.
    _, cleaned = clean(batch=batch(mix_power_sensor=None, mix_min_w=0))
    assert (cleaned["mix_power_sensor"], cleaned["mix_min_w"]) == (None, 0)
    assert (
        clean(batch=batch(mix_min_w=0))[1]["mix_power_sensor"]
        == BATCH["mix_power_sensor"]
    )


def test_a_pumps_power_switch_is_never_batch_hardware():
    for field in ("fill_valve", "mix_pump"):
        with pytest.raises(dosing.DosingError, match="cannot be both"):
            clean(batch=batch(**{field: PUMP["power_entity"]}), exists=None)
    for field in ("mix_valves", "close_entities"):
        with pytest.raises(dosing.DosingError, match="cannot be both"):
            clean(batch=batch(**{field: [PUMP["power_entity"]]}), exists=None)


def test_mixing_and_closing_may_use_a_rooms_own_irrigation_switches():
    """The batch holds that room's watering (docs/DOSING.md): the same switch in two roles of the
    batch is allowed, and nothing here knows or needs a room's pump."""
    _, cleaned = clean(
        batch=batch(mix_pump="switch.main_pump", close_entities=["switch.main_pump"]),
        exists=None,
    )
    assert cleaned["mix_pump"] == cleaned["close_entities"][0] == "switch.main_pump"


def test_lists_have_limits_and_no_repeats():
    pumps = [
        pump(id=f"p{n}", name=f"P{n}", power_entity=f"switch.p{n}") for n in range(9)
    ]
    with pytest.raises(dosing.DosingError, match="at most 8 pumps"):
        clean(pumps, batch(recipe=[]), exists=None)
    with pytest.raises(dosing.DosingError, match="at most 4"):
        clean(batch=batch(mix_valves=[f"switch.v{n}" for n in range(5)]), exists=None)
    with pytest.raises(dosing.DosingError, match="at most 16"):
        clean(
            batch=batch(close_entities=[f"switch.c{n}" for n in range(17)]),
            exists=None,
        )
    with pytest.raises(dosing.DosingError, match="listed twice"):
        clean(batch=batch(mix_valves=["switch.a", "switch.a"]), exists=None)
    with pytest.raises(dosing.DosingError, match="each pump must be an object"):
        clean(["balance"])
    with pytest.raises(dosing.DosingError, match="the batch must be an object"):
        clean(batch=["switch.tank_fill"])


def test_a_pump_draws_one_of_the_rooms_stock_tanks_and_no_tank_has_two_pumps():
    """docs/DOSING.md, Stock tanks: its level then follows what the pump actually doses."""
    bloom = pump(id="bloom", name="Bloom", power_entity="switch.bloom_power")
    [linked], _ = clean([pump(stock_tank="balance")], stock_tanks={"balance", "cal"})
    assert linked["stock_tank"] == "balance"
    assert clean([pump(stock_tank="")], stock_tanks=set())[0][0]["stock_tank"] is None
    with pytest.raises(dosing.DosingError, match="not one of this room's stock tanks"):
        clean([pump(stock_tank="bloom")], stock_tanks={"balance"})
    with pytest.raises(
        dosing.DosingError, match="stock tank cal is linked to two pumps"
    ):
        clean(
            [pump(stock_tank="cal"), dict(bloom, stock_tank="cal")],
            batch(recipe=[]),
            exists=None,
            stock_tanks={"cal"},
        )
    # Read back at start-up: the stock store may not be loaded yet, and the link is kept.
    assert clean([pump(stock_tank="gone")], exists=None)[0][0]["stock_tank"] == "gone"


def test_a_dose_request_names_a_pump_and_an_amount_it_can_dose():
    config = {"pumps": clean()[0]}
    assert dosing.check_request(config, "dose", "balance", 25) == ("balance", 25)
    assert dosing.check_request(config, "dose", "balance", "2000") == ("balance", 2000)
    assert dosing.check_request(config, "dose", "balance", 2.5) == ("balance", 2.5)
    with pytest.raises(dosing.DosingError, match="unknown pump: bloom"):
        dosing.check_request(config, "dose", "bloom", 25)
    for bad in (0, -1, 2000.5, None, "a lot", float("inf"), True):
        with pytest.raises(dosing.DosingError, match="more than 0 and at most 2000"):
            dosing.check_request(config, "dose", "balance", bad)
    # A batch and a stop carry neither, whatever is sent.
    assert dosing.check_request(config, "batch", "bloom", -1) == (None, None)
    assert dosing.check_request({"pumps": []}, "stop") == (None, None)
    with pytest.raises(dosing.DosingError, match="dose, batch or stop"):
        dosing.check_request(config, "flush")


def test_a_request_waits_until_it_is_handled_or_too_old_to_act_on():
    request = {"id": "abc", "at": (NOW - timedelta(seconds=30)).isoformat()}
    assert dosing.pending(request, None, NOW)
    assert dosing.pending(request, "older", NOW)
    assert not dosing.pending(request, "abc", NOW)  # the controller has it
    old = {"id": "abc", "at": (NOW - timedelta(seconds=121)).isoformat()}
    assert not dosing.pending(old, None, NOW)  # the controller will never act on it
    assert not dosing.pending(None, None, NOW)
    assert not dosing.pending({"id": "abc", "at": "yesterday"}, None, NOW)
    assert not dosing.pending({"id": "abc", "at": "2026-09-28T12:00:00"}, None, NOW)
