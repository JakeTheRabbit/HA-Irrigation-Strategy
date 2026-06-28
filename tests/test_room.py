"""Multi-room namespacing — lock the contract that the DEFAULT room stays un-prefixed so
existing single-room installs (e.g. F2) keep their exact entity ids, while named rooms get an
isolated prefix."""

import importlib.util
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "cs_room", ROOT / "custom_components" / "crop_steering" / "room.py"
)
room = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(room)


def _entry(data):
    return types.SimpleNamespace(data=data)


def test_default_room_is_unprefixed():
    # No room_prefix, or an explicit "" -> default room -> F2 entities unchanged.
    assert room.room_prefix(_entry({})) == ""
    assert room.room_prefix(_entry({"room_prefix": ""})) == ""


def test_named_room_is_prefixed():
    assert room.room_prefix(_entry({"room_prefix": "veg_"})) == "veg_"


def test_room_prefix_never_raises():
    assert (
        room.room_prefix(_entry(None)) == ""
    )  # defensive: bad/missing data -> default


def test_slugify():
    assert room.slugify_room("Flower B") == "flower_b"
    assert room.slugify_room("  Veg!! ") == "veg"
    assert room.slugify_room("") == "room"
    assert room.slugify_room("Room-2") == "room_2"


# ----------------------------------------- engine_config descriptor (what the add-on reads)

_HW = {
    "pump_switch": "switch.veg_pump",
    "main_line_switch": "switch.veg_main",
    "feed_ec_sensor": "sensor.veg_res_ec",
    "feed_ph_sensor": "sensor.veg_res_ph",
}
_ZONES = {
    "1": {"zone_switch": "switch.veg_zone_1"},
    "2": {"zone_switch": "switch.veg_zone_2"},
}


def test_named_room_engine_config_has_own_kill_switch_and_hardware():
    d = room.build_engine_config("veg_", "veg", 2, _ZONES, _HW)
    assert d["prefix"] == "veg_" and d["slug"] == "veg" and d["num_zones"] == 2
    assert d["pump"] == "switch.veg_pump" and d["mainline"] == "switch.veg_main"
    assert d["valves"] == {1: "switch.veg_zone_1", 2: "switch.veg_zone_2"}
    assert (
        d["enable_flag"] == "switch.crop_steering_veg_engine_enabled"
    )  # per-room kill switch
    assert d["feed_ec_sensor"] == "sensor.veg_res_ec"
    assert d["feed_ph_sensor"] == "sensor.veg_res_ph"


def test_default_room_engine_config_uses_global_kill_switch():
    d = room.build_engine_config(
        "", "default", 1, {"1": {"zone_switch": "switch.f2_row1"}}, {}
    )
    assert (
        d["enable_flag"] == "input_boolean.f2_control_enabled"
    )  # default keeps the global kill switch
    assert d["prefix"] == "" and d["valves"] == {1: "switch.f2_row1"}
    assert (
        d["feed_ec_sensor"] == "" and d["feed_ph_sensor"] == ""
    )  # unset -> gate disabled


def test_engine_config_skips_zones_without_a_valve():
    d = room.build_engine_config(
        "veg_", "veg", 3, _ZONES, _HW
    )  # only zones 1,2 have a switch
    assert d["valves"] == {1: "switch.veg_zone_1", 2: "switch.veg_zone_2"}
