"""Files that ship as copies are their source, byte for byte.

The one defaults table, and the one rule for how long a shot runs, are each written once, in the
engine, and ship three times: the engine itself, the controller's vendored engine and the integration
(which Home Assistant installs on its own, so it cannot import the engine). A copy edited by hand, or
a source edited without its copies, would let the integration offer or show one value and the
controller use another. To fix a failure, edit the source and copy it over: cp <source> <copy>.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "crop-steering-engine/src/crop_steering_engine/defaults.py"
COPIES = [
    "addons/f2_control/f2_control/crop_steering_engine/defaults.py",
    "custom_components/crop_steering/generated/defaults.py",
]
SHOT_SOURCE = "crop-steering-engine/src/crop_steering_engine/shot_length.py"
SHOT_COPIES = [
    "addons/f2_control/f2_control/crop_steering_engine/shot_length.py",
    "custom_components/crop_steering/generated/shot_length.py",
]


def _same(source: Path, copy: Path) -> bool:
    return copy.read_bytes() == source.read_bytes()


@pytest.mark.parametrize(
    "source, copy",
    [(SOURCE, c) for c in COPIES] + [(SHOT_SOURCE, c) for c in SHOT_COPIES],
)
def test_each_copy_is_its_source_byte_for_byte(source, copy):
    assert _same(ROOT / source, ROOT / copy), f"{copy} differs: cp {source} {copy}"


@pytest.mark.parametrize("position", [0, "middle", -1])
def test_a_one_byte_edit_anywhere_in_a_copy_is_caught(tmp_path, position):
    data = bytearray((ROOT / SOURCE).read_bytes())
    at = len(data) // 2 if position == "middle" else position
    data[at] ^= 0x01
    edited = tmp_path / "defaults.py"
    edited.write_bytes(bytes(data))
    assert not _same(ROOT / SOURCE, edited)
