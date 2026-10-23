"""Shrink the release screenshots in docs/screens/ in place: a 256-colour palette, no dithering
(flat UI colours stay exact), maximum zlib compression. Run after capture-screens.mjs."""

import sys
from pathlib import Path

from PIL import Image

SCREENS = Path(__file__).resolve().parent.parent / "docs" / "screens"


def main() -> int:
    before = after = 0
    for path in sorted(SCREENS.glob("*.png")):
        before += path.stat().st_size
        with Image.open(path) as image:
            small = image.convert("RGB").quantize(
                colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
            )
        small.save(path, optimize=True)
        after += path.stat().st_size
    print(f"docs/screens: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
