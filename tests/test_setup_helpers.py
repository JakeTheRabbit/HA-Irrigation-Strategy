"""Setup asks in the units growers have, and works answers out instead of asking.

The engine works in mS/cm, litres and L/hr. People have uS/cm probes, ppm pens on two
different scales, pots in US gallons and drippers in GPH. A wrong unit here is not cosmetic:
a uS/cm probe read as mS/cm is a thousand times over the EC ceiling (a permanent flush), and a
gallon typed as litres is a shot a quarter of the size it should be.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "crop_steering"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"cs_{name}", INTEGRATION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


units = _load("units")
helpers = _load("setup_helpers")


# ------------------------------------------------------------------ EC
@pytest.mark.parametrize(
    "reading, unit, expected",
    [
        (2.3, "mS/cm", 2.3),
        (2.3, "dS/m", 2.3),  # the same number by definition
        (2.3, "mS / cm", 2.3),  # spacing and case are not the operator's problem
        (2300, "µS/cm", 2.3),  # U+00B5 MICRO SIGN, what HA's own constant uses
        (2300, "μS/cm", 2.3),  # U+03BC GREEK MU, what people paste
        (2300, "uS/cm", 2.3),  # ASCII, what ESPHome YAML often has
        (0.23, "S/m", 2.3),
        (23, "CF", 2.3),
        (2.3, "EC", 2.3),  # a bare "EC" conventionally means mS/cm
    ],
)
def test_a_probe_that_states_its_unit_is_converted_without_asking(reading, unit, expected):
    assert units.ec_factor(unit) == (pytest.approx(expected / reading), None)
    assert units.ec_to_ms_cm(reading, unit) == pytest.approx(expected)


def test_the_same_feed_reads_1000_or_1400_ppm_so_ppm_needs_its_scale():
    assert units.ec_factor("ppm") == (None, units.EC_PROBLEM_AMBIGUOUS_PPM)
    assert units.ec_to_ms_cm(1000, "ppm", "ppm_500") == pytest.approx(2.0)
    assert units.ec_to_ms_cm(1400, "ppm", "ppm_700") == pytest.approx(2.0)
    # Telling it "mS/cm" does not settle which ppm scale the pen uses.
    assert units.ec_factor("ppm", "ms_cm") == (None, units.EC_PROBLEM_AMBIGUOUS_PPM)


def test_a_probe_with_no_unit_needs_to_be_told_and_then_obeys():
    assert units.ec_factor("") == (None, units.EC_PROBLEM_MISSING)
    assert units.ec_factor(None) == (None, units.EC_PROBLEM_MISSING)
    assert units.ec_to_ms_cm(2300, None, "us_cm") == pytest.approx(2.3)


def test_the_probes_own_unit_beats_the_operators_pick():
    """The pick is for probes that say nothing. One that says uS/cm is believed."""
    assert units.ec_to_ms_cm(2300, "µS/cm", "ms_cm") == pytest.approx(2.3)


@pytest.mark.parametrize("unit", ["%", "°C", "pH", "V"])
def test_a_unit_that_is_not_ec_is_refused_at_setup(unit):
    assert units.ec_factor(unit) == (None, units.EC_PROBLEM_UNKNOWN)


@pytest.mark.parametrize("unit", ["", None, "ppm", "%"])
def test_an_unconvertible_live_reading_passes_through_unchanged(unit):
    """In-place upgrade: an install from before units were checked may have such a probe
    mapped. Its readings were always averaged as-is; they must not move under the operator."""
    assert units.ec_to_ms_cm(3.1, unit) == 3.1


def test_every_pickable_ec_unit_converts():
    assert set(units.EC_UNIT_CHOICES) - {units.EC_UNIT_AUTO} <= set(units.EC_FACTORS)


# ------------------------------------------------------------------ volume and flow
def test_us_gallons_and_gph_round_trip_to_litres():
    assert units.to_litres(1, "gal") == pytest.approx(3.785, abs=1e-3)
    assert units.to_lph(1, "gal/hr") == pytest.approx(3.785, abs=1e-3)
    for litres in (0.65, 6.0, 18.9):
        assert units.from_litres(units.to_litres(litres, "gal"), "gal") == pytest.approx(litres)
    assert units.to_litres(6, "L") == 6 and units.to_lph(2, "L/hr") == 2


def test_units_start_from_home_assistants_own_unit_system():
    assert units.default_units(True) == ("L", "L/hr")
    assert units.default_units(False) == ("gal", "gal/hr")


def test_an_unknown_unit_is_treated_as_metric_rather_than_crashing_setup():
    assert units.to_litres(6, "bucket") == 6


# ------------------------------------------------------------------ substrate presets
def test_a_preset_supplies_the_volume_and_custom_uses_what_was_typed():
    assert helpers.substrate_litres("cube_4in", 99) == 0.65
    assert helpers.substrate_litres("custom", 4.2) == 4.2
    assert helpers.substrate_litres(None, 4.2) == 4.2
    assert helpers.substrate_litres("a_preset_from_a_newer_version", 4.2) == 4.2


def test_gallon_presets_are_the_gallons_they_claim():
    for key, litres in helpers.SUBSTRATE_PRESETS.items():
        if key.startswith("pot_"):
            gallons = int(key.removeprefix("pot_").removesuffix("gal"))
            assert litres == pytest.approx(units.to_litres(gallons, "gal"), abs=0.06)


def test_rockwool_presets_are_their_stated_dimensions():
    assert helpers.SUBSTRATE_PRESETS["cube_4in"] == pytest.approx(10 * 10 * 6.5 / 1000)
    assert helpers.SUBSTRATE_PRESETS["block_6in"] == pytest.approx(15 * 15 * 15 / 1000, abs=0.03)


def test_every_preset_is_a_volume_setup_accepts():
    for litres in filter(None, helpers.SUBSTRATE_PRESETS.values()):
        assert 0.1 <= litres <= 200


# ------------------------------------------------------------------ catch test
def test_a_catch_test_gives_litres_per_hour_per_dripper():
    # 4 drippers, 60 s, 200 mL -> 50 mL each per minute -> 3.0 L/hr each
    assert helpers.catch_test_lph(200, 60, 4) == (3.0, None)
    assert helpers.catch_test_lph(33.3, 60, 1) == (2.0, None)


@pytest.mark.parametrize("ml, seconds, drippers", [
    (0, 60, 1), (200, 0, 1), (200, 60, 0), (-5, 60, 1),
    (None, 60, 1), ("a jug", 60, 1), (float("nan"), 60, 1), (float("inf"), 60, 1),
])
def test_a_catch_test_with_a_missing_or_impossible_number_is_refused(ml, seconds, drippers):
    assert helpers.catch_test_lph(ml, seconds, drippers) == (None, helpers.CATCH_PROBLEM_INPUT)


def test_a_catch_test_that_implies_an_implausible_dripper_is_refused_not_saved():
    # 5 L in 10 s from one dripper is 1800 L/hr: a hose, or seconds entered as minutes.
    assert helpers.catch_test_lph(5000, 10, 1) == (None, helpers.CATCH_PROBLEM_RANGE)
    assert helpers.catch_test_lph(1, 3600, 100) == (None, helpers.CATCH_PROBLEM_RANGE)


# ------------------------------------------------------------------ suggested field capacity
def test_field_capacity_is_suggested_from_where_the_zone_really_tops_out():
    assert helpers.suggested_field_capacity(61.4) == 63.4
    assert helpers.suggested_field_capacity("58") == 60.0  # HA attributes arrive as strings too
    assert helpers.suggested_field_capacity(30) == 40.0  # never under the engine's own floor
    assert helpers.suggested_field_capacity(99.5) == 100.0


@pytest.mark.parametrize("peak", [None, "", "unknown", 0, -3, 140, float("nan")])
def test_no_suggestion_until_a_believable_plateau_has_been_seen(peak):
    assert helpers.suggested_field_capacity(peak) is None


def test_the_suggestion_is_exactly_what_auto_setpoints_would_set():
    """Two layers, one rule: a zone must not be told one number and managed to another."""
    source = (
        ROOT / "addons" / "f2_control" / "f2_control" / "setpoint_supervisor.py"
    ).read_text(encoding="utf-8")
    margin, floor = helpers.FIELD_CAPACITY_MARGIN_PTS, helpers.FIELD_CAPACITY_FLOOR
    assert f'"field_capacity": max({floor}, round(peak + {margin}, 1))' in source
