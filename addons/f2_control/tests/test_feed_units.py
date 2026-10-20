"""The source-water EC gate compares the reservoir probe with limits written in mS/cm. A probe that
reports uS/cm (many do) read as 3040 "mS/cm": outside the 0-20 sanity range, so the reading was
discarded and the gate, correctly fail-closed, blocked every shot with no hint why."""
import pytest

from test_controller import _build, _desc

DESCRIPTOR = "sensor.crop_steering_engine_config"


def _feed(value, unit):
    states = {DESCRIPTOR: ("ok", _desc()), "sensor.feed": (str(value), {"unit_of_measurement": unit})}
    c, _fake = _build({"num_zones": 1, "feed_ec_sensor": "sensor.feed"}, states=states)
    return c._read_feed_ec(c.rooms[0])


@pytest.mark.parametrize("value,unit,expected", [
    (3040, "µS/cm", 3.04),  # micro sign
    (3040, "μS/cm", 3.04),  # Greek mu, what several integrations emit
    (3040, "uS/cm", 3.04),
    (3.04, "mS/cm", 3.04),
    (3.04, "dS/m", 3.04),
    (3.04, "", 3.04),  # no unit: read exactly as before
])
def test_source_water_ec_is_read_in_millisiemens(value, unit, expected):
    assert _feed(value, unit) == pytest.approx(expected)


def test_a_reading_that_is_still_absurd_after_conversion_is_discarded():
    assert _feed(3040, "mS/cm") is None  # sanity range is applied to the converted value
