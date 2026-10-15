"""The one table of device units, and the integration reading its probes through it.

Every number read from a device (a moisture or EC probe, a feed probe, a thermometer, a power plug)
becomes the unit the system steers in through crop_steering_engine/defaults.py UNITS, in the
integration and the controller alike. Units either layer already converted convert exactly as they
did; ppm and ppt EC are refused; a unit nobody knows, or none, is read as before while the reading is
plausible, and set aside outside that range. A unitless moisture reading is never guessed to be a
fraction from its size.
"""

import pytest

from custom_components.crop_steering import setup_api, units
from custom_components.crop_steering.generated.defaults import UNITS, to_canonical


@pytest.mark.parametrize(
    "quantity,value,unit,expected",
    [
        ("vwc", 0.45, "m³/m³", 45.0),
        ("vwc", 0.42, "m3/m3", 42.0),
        ("ec", 3100, "µS/cm", 3.1),  # micro sign
        ("ec", 3100, "μS/cm", 3.1),  # Greek mu
        ("ec", 3100, "uS/cm", 3.1),
        ("ec", 3.1, "dS/m", 3.1),
        ("ph", 5.9, "pH", 5.9),
        ("ph", 5.9, None, 5.9),
        ("temperature", 212, "°F", 100.0),
        ("temperature", 68, "° F", 20.0),
        ("temperature", 293.15, "K", 20.0),
        ("power", 0.05, "kW", 50.0),
        ("power", 25000, "mW", 25.0),
    ],
)
def test_recognised_units_convert_exactly(quantity, value, unit, expected):
    got, taken = to_canonical(quantity, value, unit)
    assert taken == "recognised" and got == pytest.approx(expected)


@pytest.mark.parametrize(
    "quantity,unit",
    [
        ("vwc", "%"),
        ("ec", "mS/cm"),
        ("ph", "pH"),
        ("temperature", "°C"),
        ("power", "W"),
    ],
)
def test_a_reading_already_in_the_steering_unit_is_untouched(quantity, unit):
    for value in (0.0, 0.1, 3.3, 45.7, 7.123456789):
        assert to_canonical(quantity, value, unit) == (value, "recognised")
    assert UNITS[quantity]["canonical"] == unit


def test_conversions_match_the_arithmetic_each_layer_used_before():
    for value in (1, 333, 2500, 3040, 3100, 12345.6):
        # The controller divided a feed probe's uS/cm by 1000.0.
        assert to_canonical("ec", value, "µS/cm")[0] == value / 1000.0
    for value in (0.01, 0.3, 0.42, 0.45, 0.999):
        # The integration multiplied a volume fraction by 100.0.
        assert to_canonical("vwc", value, "m³/m³")[0] == value * 100.0


@pytest.mark.parametrize("unit", ["ppm", "PPM", "ppt"])
def test_ppm_and_ppt_have_no_exact_ec_conversion(unit):
    assert to_canonical("ec", 1200, unit) == (None, "refused")
    # even when the number would look plausible
    assert to_canonical("ec", 2.0, unit) == (None, "refused")


@pytest.mark.parametrize(
    "quantity,inside,outside",
    [
        ("vwc", 45, 450),
        ("ec", 3.2, 3200),
        ("ph", 6, 60),
        ("temperature", 22, 300),
        ("power", 30, 50000),
    ],
)
def test_an_unknown_or_missing_unit_counts_only_while_plausible(
    quantity, inside, outside
):
    for unit in (None, "", "bananas"):
        if quantity == "ph" and not unit:
            continue  # a pH probe with no unit is the normal case: recognised
        assert to_canonical(quantity, inside, unit) == (inside, "unrecognised")
        assert to_canonical(quantity, outside, unit) == (None, "implausible")


def test_a_unitless_moisture_reading_is_never_guessed_to_be_a_fraction():
    assert to_canonical("vwc", 0.45, None) == (0.45, "unrecognised")


def test_a_milliwatt_is_not_a_megawatt():
    assert to_canonical("power", 5000, "mW") == (5.0, "recognised")
    assert to_canonical("power", 5000, "MW") == (5000, "unrecognised")


def test_the_integration_accepts_and_refuses_exactly_the_units_it_did():
    assert units.accepted("vwc") == {"%", "m³/m³", "m3/m3"}
    assert units.accepted("ec") == {"ms/cm", "ds/m", "µs/cm", "μs/cm", "us/cm"}
    assert setup_api.UNITS["ph"] == {"ph", ""}
    assert setup_api.UNITS["tank_temperature"] == {"°c", "°f", "k"}
    assert "500 or 700 scale" in units.refusal("ec", "ppm")
    assert units.refusal("ec", "bananas") is None


def test_the_integration_reads_a_probe_through_the_table():
    assert units.to_native("ec", "µS/cm", 3100) == (pytest.approx(3.1), False)
    assert units.to_native("ec", "ppm", 1200) == (None, True)
    # an old unitless probe reads as it always did, and out of range it is out of range
    assert units.to_native("vwc", "", 52) == (52, False)
    assert units.to_native("vwc", "", 520) == (520, False)
    assert units.to_native("vwc", "bananas", 520) == (None, True)
    # no quantity: the reading as it is
    assert units.to_native(None, "anything", 520) == (520, False)


def test_the_integration_says_once_which_probe_it_reads_or_sets_aside_for_its_unit(
    caplog,
):
    caplog.set_level("INFO", logger=units.__name__)
    for _ in range(3):
        units.to_native("vwc", "pct", 45, "sensor.odd_label")
        units.to_native("ec", "ppm", 1200, "sensor.ppm_probe")
        units.to_native("ec", "mS/cm", 2.0, "sensor.good_probe")
    said = [r.getMessage() for r in caplog.records if r.name == units.__name__]
    assert len(said) == 2
    assert "sensor.odd_label" in said[0] and "'pct'" in said[0]
    assert (
        "sensor.ppm_probe" in said[1] and "'ppm'" in said[1] and "set aside" in said[1]
    )
