"""Build custom_components/crop_steering/brand/ from the project's own logo artwork.

Run from the repository root:  python scripts/make_brand_images.py   (needs Pillow)

Home Assistant 2026.3+ serves these for a custom integration (no manifest change). The icon is the
emblem alone (it is shown at about 40 px, where the wordmark is unreadable); the logo keeps the
wordmark. Dark-theme variants sit on a white rounded tile, because the artwork's navy outlines
and dark-green lettering disappear on a dark card.
"""

import os

from PIL import Image, ImageDraw

SRC, OUT = "img/crop-steering-logo.png", "custom_components/crop_steering/brand/"
src = Image.open(SRC).convert("RGBA")
alpha = src.getchannel("A").point(
    lambda v: 255 if v >= 8 else 0
)  # ignore near-invisible haze
art = src.crop(alpha.getbbox())
mask = alpha.crop(alpha.getbbox())
w, h = art.size
rows = [mask.crop((0, y, w, y + 1)).getbbox() is not None for y in range(h)]
gaps, start = [], None
for y, solid in enumerate(rows):
    if not solid and start is None:
        start = y
    if solid and start is not None:
        gaps.append((start, y))
        start = None
split = max(gaps, key=lambda g: g[0])[0]  # the lowest gap: emblem above, wordmark below
emblem = art.crop((0, 0, w, split))
emblem = emblem.crop(mask.crop((0, 0, w, split)).getbbox())
print("art", art.size, "gaps", gaps, "-> emblem", emblem.size)


def tile(size_w, size_h, radius):
    canvas = Image.new("RGBA", (size_w, size_h), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).rounded_rectangle(
        (0, 0, size_w - 1, size_h - 1), radius=radius, fill=(255, 255, 255, 255)
    )
    return canvas


def icon(size, dark=False):
    canvas = (
        tile(size, size, size // 6)
        if dark
        else Image.new("RGBA", (size, size), (0, 0, 0, 0))
    )
    room = int(size * (0.80 if dark else 0.94))
    scale = min(room / emblem.width, room / emblem.height)
    scaled = emblem.resize(
        (round(emblem.width * scale), round(emblem.height * scale)), Image.LANCZOS
    )
    canvas.paste(
        scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled
    )
    return canvas


def logo(height, dark=False):
    if not dark:
        return art.resize(
            (round(art.width * height / art.height), height), Image.LANCZOS
        )
    inner = int(height * 0.80)
    scaled = art.resize((round(art.width * inner / art.height), inner), Image.LANCZOS)
    canvas = tile(scaled.width + (height - inner), height, height // 6)
    canvas.paste(
        scaled, ((canvas.width - scaled.width) // 2, (height - inner) // 2), scaled
    )
    return canvas


files = {
    "icon.png": icon(256),
    "icon@2x.png": icon(512),
    "dark_icon.png": icon(256, dark=True),
    "dark_icon@2x.png": icon(512, dark=True),
    "logo.png": logo(256),
    "logo@2x.png": logo(512),
    "dark_logo.png": logo(256, dark=True),
    "dark_logo@2x.png": logo(512, dark=True),
}
for name, image in files.items():
    # 256 colours with alpha: the illustration is a third of the size and looks the same. Every
    # install downloads these, and Home Assistant serves them on each integrations page.
    image = image.quantize(
        colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE
    )
    image.save(OUT + name, optimize=True)
    print(f"{name:18} {image.size}")

prev = Image.new("RGBA", (660, 300), (255, 255, 255, 255))
prev.paste(Image.new("RGBA", (330, 300), (28, 28, 28, 255)), (330, 0))
for x, key in ((12, "icon.png"), (342, "dark_icon.png")):
    prev.paste(files[key], (x, 22), files[key])
    small = files[key].resize((40, 40), Image.LANCZOS)
    prev.paste(small, (x + 270, 130), small)
if os.environ.get(
    "PREVIEW"
):  # optional: a light/dark preview to look at before committing
    prev.save(os.environ["PREVIEW"])
