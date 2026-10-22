"""Display options as stored: an old or foreign store loads, never refused for one bad option."""

import pytest

from custom_components.crop_steering.display import (
    OPTIONS,
    clean_option,
    defaults,
    from_store,
)


def test_an_option_a_newer_version_saved_is_dropped_not_the_store():
    loaded = from_store(
        {
            "revision": 4,
            "options": {
                "show_climate": True,
                "from_the_future": True,
                "show_camera": 1,
            },
        }
    )
    assert loaded == {"revision": 4, "options": {"show_climate": True}}


def test_a_store_without_options_reads_every_option_off():
    assert from_store({"revision": 0}) == {"revision": 0, "options": {}}
    units = {"ec_unit", "temp_unit", "volume_unit", "clock"}
    assert all(defaults()[k] in (False, "cards") for k in OPTIONS if k not in units)


@pytest.mark.parametrize("bad", [None, [], {"revision": "1"}, {"options": {}}])
def test_a_store_without_a_revision_is_refused(bad):
    with pytest.raises(ValueError):
        from_store(bad)


def test_values_are_checked():
    assert clean_option("today_zone_layout", "table") == "table"
    for key, value in (("show_climate", 1), ("today_zone_layout", "grid"), ("x", True)):
        with pytest.raises(ValueError):
            clean_option(key, value)


def test_old_store_reads_units_as_mS_C_L_24():
    old = from_store({"revision": 2, "options": {"show_climate": True}})
    assert old["options"] == {"show_climate": True}
    shown = {**defaults(), **old["options"]}
    assert (shown["ec_unit"], shown["temp_unit"]) == ("mS/cm", "C")
    assert (shown["volume_unit"], shown["clock"]) == ("L", 24)


def test_save_refuses_an_unknown_unit():
    for key, value in (
        ("ec_unit", "ppm640"),
        ("temp_unit", "K"),
        ("volume_unit", "oz"),
        ("clock", "12"),
        ("clock", 13),
        ("clock", True),
        ("clock", 12.0),
    ):
        with pytest.raises(ValueError):
            clean_option(key, value)
    for key, value in (
        ("ec_unit", "ppm700"),
        ("temp_unit", "F"),
        ("volume_unit", "gal"),
        ("clock", 12),
    ):
        assert clean_option(key, value) == value
