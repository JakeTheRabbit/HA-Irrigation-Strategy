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
SRC = "crop-steering-engine/src/crop_steering_engine/"
COPY_DIRS = [
    "addons/f2_control/f2_control/crop_steering_engine/",
    "custom_components/crop_steering/generated/",
]
PAIRS: list[tuple[Path, Path]] = [
    (ROOT / SRC / name, ROOT / d / name)
    for name in ("defaults.py", "ids.py", "timers.py", "guards.py", "shot_length.py")
    for d in COPY_DIRS
] + [(ROOT / SRC / "flow.py", ROOT / COPY_DIRS[0] / "flow.py")]


def _same(source: Path, copy: Path) -> bool:
    return copy.read_bytes() == source.read_bytes()


def _label(pair):
    return str(pair[1].relative_to(ROOT))


@pytest.mark.parametrize("pair", PAIRS, ids=_label)
def test_each_copy_is_its_source_byte_for_byte(pair):
    source, copy = pair
    assert _same(
        source, copy
    ), f"{_label(pair)} differs: cp {source.relative_to(ROOT)} {_label(pair)}"


@pytest.mark.parametrize("pair", PAIRS, ids=_label)
@pytest.mark.parametrize("position", [0, "middle", -1])
def test_a_one_byte_edit_anywhere_in_a_copy_is_caught(tmp_path, pair, position):
    source, _ = pair
    data = bytearray(source.read_bytes())
    at = len(data) // 2 if position == "middle" else position
    data[at] ^= 0x01
    edited = tmp_path / source.name
    edited.write_bytes(bytes(data))
    assert not _same(source, edited)
