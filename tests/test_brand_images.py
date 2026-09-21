"""The integration ships its own brand images (Home Assistant 2026.3+ serves
`custom_components/<domain>/brand/` for a custom integration, with no manifest change).

Without them the "add integration" dialog, the integrations page and HACS all show
"icon not available". Pinned here because the failure is silent: a missing or mis-sized file
is simply not shown. Sizes follow the home-assistant/brands rules, read from the PNG header
so the lean suite needs no imaging library.
"""

import struct
from pathlib import Path

import pytest

BRAND = Path(__file__).parents[1] / "custom_components" / "crop_steering" / "brand"
PNG = b"\x89PNG\r\n\x1a\n"


def _size(name):
    data = (BRAND / name).read_bytes()
    assert data[:8] == PNG and data[12:16] == b"IHDR", f"{name} is not a PNG"
    return struct.unpack(">II", data[16:24])


@pytest.mark.parametrize("prefix", ["", "dark_"])
def test_icons_are_square_at_the_two_sizes_home_assistant_asks_for(prefix):
    assert _size(f"{prefix}icon.png") == (256, 256)
    assert _size(f"{prefix}icon@2x.png") == (512, 512)


@pytest.mark.parametrize("prefix", ["", "dark_"])
def test_logos_are_landscape_with_the_short_side_in_range_and_a_true_2x(prefix):
    width, height = _size(f"{prefix}logo.png")
    assert width >= height and 128 <= height <= 256
    assert _size(f"{prefix}logo@2x.png")[1] == 2 * height


def test_nothing_else_is_in_the_folder_and_nothing_is_huge():
    names = {path.name for path in BRAND.iterdir()}
    assert names == {
        f"{prefix}{kind}{scale}.png"
        for prefix in ("", "dark_")
        for kind in ("icon", "logo")
        for scale in ("", "@2x")
    }
    # these are downloaded by every install and served on every integrations page
    assert all((BRAND / name).stat().st_size < 200_000 for name in names)
