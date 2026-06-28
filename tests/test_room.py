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
    assert room.room_prefix(_entry(None)) == ""  # defensive: bad/missing data -> default


def test_slugify():
    assert room.slugify_room("Flower B") == "flower_b"
    assert room.slugify_room("  Veg!! ") == "veg"
    assert room.slugify_room("") == "room"
    assert room.slugify_room("Room-2") == "room_2"
