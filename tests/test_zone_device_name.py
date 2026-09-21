"""A zone's Home Assistant device is called what the operator called the zone.

Seen on a first install: the zone was set up as "GT1" and Home Assistant offered a device called
"Zone 1". Three platforms each named the device themselves ("Zone 1", "Crop Steering Zone 1"),
so the winner was whichever registered last, and none of them used the configured name.
"""

import importlib.util
import re
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "crop_steering"
_spec = importlib.util.spec_from_file_location("cs_room_names", INTEGRATION / "room.py")
room = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(room)


def _entry(data=None, options=None):
    return types.SimpleNamespace(data=data or {}, options=options or {})


def test_the_device_takes_the_name_that_was_typed():
    entry = _entry({"zones": {"1": {"name": "GT1"}, "2": {"name": "Veg bench"}}})
    assert room.zone_device_name(entry, 1) == "GT1"
    assert room.zone_device_name(entry, 2) == "Veg bench"


@pytest.mark.parametrize(
    "zones",
    [
        {},
        {"1": {}},
        {"1": {"name": ""}},
        {"1": {"name": "   "}},
        {"1": {"name": None}},
        {"1": {"name": 7}},
        {"1": "not a mapping"},
    ],
)
def test_without_a_usable_name_it_falls_back_to_zone_n(zones):
    assert room.zone_device_name(_entry({"zones": zones}), 1) == "Zone 1"


def test_every_zone_number_up_to_the_limit_and_both_key_styles():
    limit = int(
        re.search(
            r"^MAX_ZONES\s*=\s*(\d+)", (INTEGRATION / "const.py").read_text(), re.M
        ).group(1)
    )
    assert limit >= 20
    named = {str(n): {"name": f"Bench {n}"} for n in range(1, limit + 1)}
    for n in range(1, limit + 1):
        assert room.zone_device_name(_entry({"zones": named}), n) == f"Bench {n}"
    # the env-file path stores integer keys
    assert room.zone_device_name(_entry({"zones": {3: {"name": "Rear"}}}), 3) == "Rear"
    # a zone that is not configured at all still gets a sane name
    assert (
        room.zone_device_name(_entry({"zones": named}), limit + 1)
        == f"Zone {limit + 1}"
    )


def test_a_rename_saved_into_options_wins_and_whitespace_is_trimmed():
    entry = _entry(
        {"zones": {"1": {"name": "Old"}}}, {"zones": {"1": {"name": "  GT1  "}}}
    )
    assert room.zone_device_name(entry, 1) == "GT1"
    assert room.zone_device_name(types.SimpleNamespace(data=None), 1) == "Zone 1"


def test_no_platform_names_the_zone_device_by_itself_any_more():
    """How the bug happened: each platform had its own f-string. Every zone device, in every
    platform, must get its name from the one helper."""
    offenders = []
    for path in sorted(INTEGRATION.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for block in re.findall(r"DeviceInfo\((.*?)\n\s*\)", source, re.S):
            if "_zone_" in block and "zone_device_name(" not in block:
                offenders.append(path.name)
    assert offenders == []
    users = [
        path.name
        for path in sorted(INTEGRATION.glob("*.py"))
        if "name=zone_device_name(self._entry, self._zone_num)" in path.read_text()
    ]
    assert users == ["button.py", "number.py", "select.py"]
