#!/usr/bin/env python3
"""Draw MCA site and unit floor plans (A4 landscape SVG, plus PDF when Chrome/Chromium is present).

Usage:
    python floorplan.py application_data.yaml -o plans/        # or an intake.json from the app

Writes:
    fig1_site_plan.svg/.pdf      licensed area, structures, fence, gates, cameras, alarm devices,
                                 north arrow, 10 m scale bar, legend, title block
    fig2_unit_<use>.svg/.pdf     one typical interior plan per building use (entry sequence, racks,
                                 aisle, cameras, PIR, siren, exhaust and carbon filter)
Pure Python (PyYAML only). Layout format: references/floor-plans.md.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

import yaml

W_MM, H_MM = 297.0, 210.0
USE_COLOURS = {
    "flowering": "#4f8a5b",
    "vegetative": "#7fb069",
    "mothers / propagation": "#a3c26b",
    "drying / curing": "#b88a3d",
    "secure store (vault)": "#8a4f4f",
    "shed (no cannabis)": "#9a9a9a",
    "office": "#5a7fa8",
    "waste": "#6e6e4f",
    "other": "#7a6aa8",
}
GROW_USES = {"flowering", "vegetative", "mothers / propagation"}


def colour(use: str) -> str:
    return USE_COLOURS.get((use or "other").lower(), "#7a6aa8")


def load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if "schema" in data and data.get("schema", "").startswith("mca-intake"):  # raw intake.json
        a = data.get("answers", {})
        lay = data.get("layout", {})
        return {
            "applicant": {"legal_name": (a.get("Q010") or "").split("\n")[0]},
            "site": {"one_line": a.get("Q040", ""), "legal_description": a.get("Q041", "")},
            "layout": {
                "site": lay.get("site", {"w": 40, "d": 30}),
                "north_deg": lay.get("north", 0),
                "items": lay.get("items", []),
                "source": "phone layout tool - indicative",
            },
        }
    return data


def svg_open(title: str) -> list[str]:
    return [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_MM}mm" height="{H_MM}mm" '
            f'viewBox="0 0 {W_MM} {H_MM}" font-family="Helvetica, Arial, sans-serif">'
        ),
        f"<title>{escape(title)}</title>",
        (
            '<defs><pattern id="hatch" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<line x1="0" y1="0" x2="0" y2="3" stroke="#9a9a9a" stroke-width="0.6"/></pattern>'
            '<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker></defs>'
        ),
        f'<rect x="0" y="0" width="{W_MM}" height="{H_MM}" fill="#fff"/>',
        f'<rect x="8" y="8" width="{W_MM-16}" height="{H_MM-16}" fill="none" stroke="#222" stroke-width="0.5"/>',
    ]


def title_block(out: list[str], data: dict, fig: str, subtitle: str, note: str) -> None:
    x, y, w, h = W_MM - 100, H_MM - 46, 90, 36
    app = (data.get("applicant") or {}).get("legal_name") or "Applicant"
    site = (data.get("site") or {}).get("one_line") or ""
    legal = (data.get("site") or {}).get("legal_description") or ""
    meta = data.get("meta") or {}
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" stroke="#222" stroke-width="0.4"/>')
    lines = [
        (f"{fig}", 4.2, "bold"),
        (subtitle, 3.0, "normal"),
        (app, 3.0, "bold"),
        (site, 2.6, "normal"),
        (legal, 2.6, "normal"),
        (f"{meta.get('package_version', 'v1.0')} · {meta.get('prepared_date', '')}", 2.4, "normal"),
        (note, 2.2, "italic"),
    ]
    yy = y + 6
    for text, size, weight in lines:
        if not text:
            continue
        style = 'font-style="italic"' if weight == "italic" else f'font-weight="{weight}"'
        out.append(f'<text x="{x+3}" y="{yy:.1f}" font-size="{size}" {style}>{escape(str(text))[:70]}</text>')
        yy += size + 1.6


def north_arrow(out: list[str], cx: float, cy: float, deg: float) -> None:
    out.append(
        f'<g transform="translate({cx},{cy}) rotate({deg})">'
        '<path d="M0,-9 L4,5 L0,2 L-4,5 z" fill="#222"/>'
        '<text x="0" y="-11" font-size="4" text-anchor="middle" font-weight="bold">N</text></g>'
    )


def scale_bar(out: list[str], x: float, y: float, s: float, metres: int = 10) -> None:
    seg = metres / 2 * s
    out.append(
        f'<rect x="{x}" y="{y}" width="{seg}" height="1.6" fill="#222"/>'
        f'<rect x="{x+seg}" y="{y}" width="{seg}" height="1.6" fill="#fff" stroke="#222" stroke-width="0.3"/>'
        f'<text x="{x}" y="{y+5}" font-size="2.6">0</text>'
        f'<text x="{x+seg}" y="{y+5}" font-size="2.6" text-anchor="middle">{metres//2}</text>'
        f'<text x="{x+2*seg}" y="{y+5}" font-size="2.6" text-anchor="middle">{metres} m</text>'
    )


def dims(it: dict) -> tuple[float, float]:
    ln, w = float(it.get("l", 1)), float(it.get("w", 1))
    return (w, ln) if int(it.get("rot", 0)) == 90 else (ln, w)


def door_side(it: dict) -> str | None:
    t = (it.get("doors") or "").lower()
    for side in ("west", "east", "north", "south"):
        if side in t:
            return side
    return None


def site_plan(data: dict) -> str:
    lay = data.get("layout") or {}
    site = lay.get("site") or {"w": 40, "d": 30}
    items = lay.get("items") or []
    sw, sd = float(site["w"]), float(site["d"])
    # drawing area: left part of the sheet; legend and title block on the right
    ax, ay, aw, ah = 16, 22, 180, 170
    s = min(aw / sw, ah / sd)
    ox, oy = ax + (aw - sw * s) / 2, ay + (ah - sd * s) / 2

    def X(m):
        return ox + m * s

    def Y(m):
        return oy + m * s

    out = svg_open("Figure 1 - Site plan")
    out.append(
        '<text x="16" y="17" font-size="5.5" font-weight="bold">Figure 1 - Site plan of the licensed area</text>'
    )
    # grid
    for gx in range(0, int(sw) + 1, 5):
        out.append(
            f'<line x1="{X(gx):.2f}" y1="{Y(0):.2f}" x2="{X(gx):.2f}" y2="{Y(sd):.2f}" stroke="#eee" stroke-width="0.2"/>'
        )
    for gy in range(0, int(sd) + 1, 5):
        out.append(
            f'<line x1="{X(0):.2f}" y1="{Y(gy):.2f}" x2="{X(sw):.2f}" y2="{Y(gy):.2f}" stroke="#eee" stroke-width="0.2"/>'
        )
    for poly in lay.get("excluded") or []:
        pts = " ".join(f"{X(p[0]):.2f},{Y(p[1]):.2f}" for p in poly)
        out.append(f'<polygon points="{pts}" fill="url(#hatch)" stroke="#9a9a9a" stroke-width="0.4"/>')
    boundary = lay.get("boundary") or [[0, 0], [sw, 0], [sw, sd], [0, sd]]
    pts = " ".join(f"{X(p[0]):.2f},{Y(p[1]):.2f}" for p in boundary)
    fence = lay.get("fence") or {}
    out.append(f'<polygon points="{pts}" fill="#f3f8f3" stroke="#c0392b" stroke-width="0.9"/>')
    # buildings first, then devices on top
    order = sorted(items, key=lambda i: 0 if i.get("kind") == "building" else 1)
    cams = 0
    for it in order:
        k = it.get("kind", "building")
        x, y = X(float(it.get("x", 0))), Y(float(it.get("y", 0)))
        if k == "building":
            a, b = dims(it)
            out.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{a*s:.2f}" height="{b*s:.2f}" fill="{colour(it.get("use"))}" '
                f'fill-opacity="0.85" stroke="#222" stroke-width="0.4"/>'
            )
            fs = max(2.2, min(4.0, b * s * 0.35))
            out.append(
                f'<text x="{x+a*s/2:.2f}" y="{y+b*s/2:.2f}" font-size="{fs:.1f}" fill="#fff" font-weight="bold" '
                f'text-anchor="middle" dominant-baseline="middle">{escape(str(it.get("label", "")))}</text>'
            )
            side = door_side(it)
            if side:
                dw = min(a, b) * s * 0.8
                if side in ("west", "east"):
                    dx = x if side == "west" else x + a * s
                    out.append(
                        f'<line x1="{dx:.2f}" y1="{y+b*s/2-dw/2:.2f}" x2="{dx:.2f}" y2="{y+b*s/2+dw/2:.2f}" stroke="#f1c40f" stroke-width="1.4"/>'
                    )
                else:
                    dy = y if side == "north" else y + b * s
                    out.append(
                        f'<line x1="{x+a*s/2-dw/2:.2f}" y1="{dy:.2f}" x2="{x+a*s/2+dw/2:.2f}" y2="{dy:.2f}" stroke="#f1c40f" stroke-width="1.4"/>'
                    )
        elif k == "gate":
            gl = float(it.get("l", 4)) * s
            x2, y2 = (x, y + gl) if int(it.get("rot", 0)) == 90 else (x + gl, y)
            out.append(
                f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#e67e22" stroke-width="1.8"/>'
            )
            out.append(
                f'<text x="{x+1:.2f}" y="{y-1.5:.2f}" font-size="2.8" font-weight="bold">{escape(str(it.get("label", "Gate")))}</text>'
            )
        elif k == "camera":
            cams += 1
            d = float(it.get("dir", 0))
            r = 12 * s / 2
            a0, a1 = math.radians(d - 30), math.radians(d + 30)
            out.append(
                f'<path d="M{x:.2f},{y:.2f} L{x+r*math.cos(a0):.2f},{y+r*math.sin(a0):.2f} '
                f'A{r:.2f},{r:.2f} 0 0 1 {x+r*math.cos(a1):.2f},{y+r*math.sin(a1):.2f} z" fill="#2c3e50" fill-opacity="0.12"/>'
            )
            out.append(
                f'<g transform="translate({x:.2f},{y:.2f}) rotate({d})"><path d="M-1.6,-1.3 L2,0 L-1.6,1.3 z" fill="#2c3e50"/></g>'
            )
            out.append(
                f'<text x="{x+2:.2f}" y="{y-1.6:.2f}" font-size="2.2">{escape(str(it.get("label", f"CAM{cams}")))}</text>'
            )
        elif k == "pir":
            out.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.2" fill="#8e44ad"/><text x="{x+1.8:.2f}" y="{y+0.8:.2f}" font-size="2">PIR</text>'
            )
        elif k == "siren":
            out.append(
                f'<rect x="{x-1.2:.2f}" y="{y-1.2:.2f}" width="2.4" height="2.4" fill="#c0392b"/><text x="{x+1.8:.2f}" y="{y+0.8:.2f}" font-size="2">Siren</text>'
            )
    north_arrow(out, X(sw) - 6 if X(sw) < 190 else 188, ay + 4, float(lay.get("north_deg", 0)))
    scale_bar(out, ax, H_MM - 16, s)
    # legend
    lx, ly = W_MM - 98, 22
    out.append(f'<text x="{lx}" y="{ly}" font-size="3.6" font-weight="bold">Legend</text>')
    ly += 5
    out.append(
        f'<rect x="{lx}" y="{ly-2.6}" width="6" height="3.2" fill="#f3f8f3" stroke="#c0392b" stroke-width="0.9"/>'
        f'<text x="{lx+8}" y="{ly}" font-size="2.8">Licensed area, fenced {fence.get("height_m", 1.8)} m '
        f'{escape(str(fence.get("type", "")))}</text>'
    )
    ly += 5
    if lay.get("excluded"):
        out.append(
            f'<rect x="{lx}" y="{ly-2.6}" width="6" height="3.2" fill="url(#hatch)" stroke="#9a9a9a" stroke-width="0.3"/>'
            f'<text x="{lx+8}" y="{ly}" font-size="2.8">Excluded - not licensed, not leased</text>'
        )
        ly += 5
    uses = []
    for it in items:
        if it.get("kind", "building") == "building" and it.get("use") not in uses:
            uses.append(it.get("use"))
    for u in uses:
        out.append(
            f'<rect x="{lx}" y="{ly-2.6}" width="6" height="3.2" fill="{colour(u)}"/>'
            f'<text x="{lx+8}" y="{ly}" font-size="2.8">{escape(str(u))}'
            f'{" - holds no cannabis" if "no cannabis" in str(u).lower() or str(u).lower() == "office" else ""}</text>'
        )
        ly += 5
    for sym, label in (
        ('<line x1="0" y1="1" x2="6" y2="1" stroke="#e67e22" stroke-width="1.8"/>', "Gate"),
        ('<line x1="3" y1="-1" x2="3" y2="3" stroke="#f1c40f" stroke-width="1.4"/>', "Door end"),
        ('<path d="M1.4,-0.3 L5,1 L1.4,2.3 z" fill="#2c3e50"/>', "Wired camera and view"),
        ('<circle cx="3" cy="1" r="1.2" fill="#8e44ad"/>', "Motion detector (PIR)"),
        ('<rect x="1.8" y="-0.2" width="2.4" height="2.4" fill="#c0392b"/>', "Siren"),
    ):
        out.append(
            f'<g transform="translate({lx},{ly-2.2})">{sym}</g><text x="{lx+8}" y="{ly}" font-size="2.8">{label}</text>'
        )
        ly += 5
    # schedule of structures
    ly += 2
    out.append(f'<text x="{lx}" y="{ly}" font-size="3.2" font-weight="bold">Structures (internal size)</text>')
    ly += 4.2
    grow_m2 = 0.0
    for it in items:
        if it.get("kind", "building") != "building":
            continue
        area = float(it.get("l", 0)) * float(it.get("w", 0))
        if (it.get("use") or "").lower() in GROW_USES:
            grow_m2 += area
        out.append(
            f'<text x="{lx}" y="{ly}" font-size="2.5">{escape(str(it.get("label")))}: {it.get("l")} x {it.get("w")} m '
            f'({area:.1f} m²) - {escape(str(it.get("use")))}</text>'
        )
        ly += 3.4
        if ly > H_MM - 50:
            break
    out.append(
        f'<text x="{lx}" y="{ly+1}" font-size="2.7" font-weight="bold">Indoor cultivation area: {grow_m2:.1f} m²</text>'
    )
    note = (
        "Indicative - not to construction scale"
        if "indicative" in str(lay.get("source", ""))
        else "Dimensions in metres"
    )
    title_block(out, data, "Figure 1", "Site plan", note)
    out.append("</svg>")
    return "\n".join(out)


def unit_plan(data: dict, use: str, it: dict) -> str:
    ln, w = float(it.get("l", 12.19)), float(it.get("w", 2.44))
    ax, ay, aw, ah = 30, 50, 190, 90
    s = min(aw / ln, ah / w)
    ox, oy = ax + (aw - ln * s) / 2, ay + (ah - w * s) / 2
    out = svg_open(f"Figure 2 - {use} unit")
    out.append(
        f'<text x="16" y="17" font-size="5.5" font-weight="bold">Figure 2 - Typical {escape(use.lower())} unit '
        f'({escape(str(it.get("label")))}, {ln} x {w} m internal)</text>'
    )
    out.append(
        f'<rect x="{ox:.2f}" y="{oy:.2f}" width="{ln*s:.2f}" height="{w*s:.2f}" fill="#fafafa" stroke="#222" stroke-width="1.2"/>'
    )
    vest = min(1.2, ln * 0.15)
    out.append(
        f'<line x1="{ox+vest*s:.2f}" y1="{oy:.2f}" x2="{ox+vest*s:.2f}" y2="{oy+w*s:.2f}" stroke="#222" stroke-width="0.8"/>'
    )
    out.append(
        f'<rect x="{ox+vest*s-0.6:.2f}" y="{oy+w*s*0.3:.2f}" width="1.2" height="{w*s*0.4:.2f}" fill="#f1c40f"/>'
    )
    out.append(
        f'<line x1="{ox:.2f}" y1="{oy+w*s*0.08:.2f}" x2="{ox:.2f}" y2="{oy+w*s*0.92:.2f}" stroke="#f1c40f" stroke-width="2"/>'
    )
    callouts = [
        (
            ox,
            oy + w * s + 20,
            "Left end: cargo doors with PIN + fob lock, door contact and inside emergency release",
            "start",
        ),
        (
            ox + vest * s,
            oy - 3,
            "Vestibule, then solid inner door: self-locking PIN + fob, closer, contact, lever always opens from inside",
            "start",
        ),
    ]
    grow = use.lower() in GROW_USES
    if grow or "dry" in use.lower() or "store" in use.lower():
        rack_d = min(0.9, w * 0.32)
        for ry in (oy, oy + w * s - rack_d * s):
            out.append(
                f'<rect x="{ox+(vest+0.4)*s:.2f}" y="{ry:.2f}" width="{(ln-vest-1.2)*s:.2f}" height="{rack_d*s:.2f}" '
                f'fill="{colour(use)}" fill-opacity="0.35" stroke="#555" stroke-width="0.3"/>'
            )
        label = (
            "Racks / benches (tiers as stated in the application)"
            if grow
            else "Drying racks; locked steel cabinet fixed to the container"
        )
        callouts.append((ox + ln * s * 0.55, oy + w * s + 4, label, "middle"))
        callouts.append((ox + ln * s * 0.55, oy + w * s / 2 + 1, "Aisle", "middle"))
    cams = [(ox + vest * s + 2, oy + 2, 0, "CAM A"), (ox + ln * s - 2, oy + w * s - 2, 180, "CAM B")]
    for cx, cy, d, lab in cams:
        r = 24
        a0, a1 = math.radians(d - 25), math.radians(d + 25)
        out.append(
            f'<path d="M{cx:.2f},{cy:.2f} L{cx+r*math.cos(a0):.2f},{cy+r*math.sin(a0):.2f} A{r},{r} 0 0 1 '
            f'{cx+r*math.cos(a1):.2f},{cy+r*math.sin(a1):.2f} z" fill="#2c3e50" fill-opacity="0.10"/>'
        )
        out.append(
            f'<g transform="translate({cx:.2f},{cy:.2f}) rotate({d})"><path d="M-2,-1.6 L2.4,0 L-2,1.6 z" fill="#2c3e50"/></g>'
        )
        out.append(
            f'<text x="{cx:.2f}" y="{cy+ (5 if d == 0 else -3):.2f}" font-size="2.4" text-anchor="middle">{lab}</text>'
        )
    px, py = ox + (vest + 1.0) * s, oy + w * s * 0.5
    out.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="1.4" fill="#8e44ad"/>')
    out.append(f'<rect x="{ox+(vest+0.3)*s:.2f}" y="{oy+w*s*0.5-1.2:.2f}" width="2.4" height="2.4" fill="#c0392b"/>')
    fx = ox + ln * s - 6
    out.append(f'<rect x="{fx:.2f}" y="{oy+w*s*0.35:.2f}" width="5" height="{w*s*0.3:.2f}" fill="#555"/>')
    out.append(
        f'<line x1="{fx+5:.2f}" y1="{oy+w*s*0.5:.2f}" x2="{ox+ln*s+10:.2f}" y2="{oy+w*s*0.5:.2f}" stroke="#555" stroke-width="0.8" marker-end="url(#arr)"/>'
    )
    callouts += [
        (px, oy - 9, "Motion detector (PIR) and internal siren near the inner door", "start"),
        (ox + ln * s + 12, oy + w * s * 0.5 - 2, "Exhaust fan and carbon filter", "start"),
        (ox + ln * s + 12, oy + w * s * 0.5 + 2, "(negative pressure)", "start"),
        (
            ox,
            oy + w * s + 12,
            "CAM A at the inner door looks down the aisle; CAM B at the far end looks back to the door",
            "start",
        ),
    ]
    for cx, cy, text, anchor in callouts:
        out.append(f'<text x="{cx:.2f}" y="{cy:.2f}" font-size="2.7" text-anchor="{anchor}">{escape(text)}</text>')
    scale_bar(out, 20, H_MM - 16, s, metres=2 if ln < 6 else 4)
    north_arrow(
        out,
        W_MM - 20,
        30,
        float((data.get("layout") or {}).get("north_deg", 0)) - (90 if int(it.get("rot", 0)) == 90 else 0),
    )
    title_block(
        out, data, "Figure 2", f"Typical {use.lower()} unit - indicative interior", "Device positions indicative"
    )
    out.append("</svg>")
    return "\n".join(out)


def find_chrome() -> str | None:
    for c in (
        os.environ.get("CHROME"),
        "google-chrome",
        "chromium",
        "chromium-browser",
        "/opt/pw-browsers/chromium/chrome-linux64/chrome",
    ):
        if c and (shutil.which(c) or Path(c).exists()):
            return shutil.which(c) or c
    for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux64/chrome"):
        return str(p)
    return None


def to_pdf(svg_path: Path) -> Path | None:
    chrome = find_chrome()
    if not chrome:
        return None
    html = (
        f'<!doctype html><html><head><meta charset="utf-8"><style>@page{{size:A4 landscape;margin:0}}'
        f"html,body{{margin:0}}svg{{display:block;width:297mm;height:210mm}}</style></head><body>"
        f'{svg_path.read_text(encoding="utf-8")}</body></html>'
    )
    pdf = svg_path.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "p.html"
        h.write_text(html, encoding="utf-8")
        r = subprocess.run(
            [
                chrome,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf}",
                h.as_uri(),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
    return pdf if r.returncode == 0 and pdf.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path, help="application_data.yaml or intake.json")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    data = load(a.data)
    items = (data.get("layout") or {}).get("items") or []
    if not items:
        print("No layout items. Draw the site in the intake app or fill layout.items.", file=sys.stderr)
        return 1
    a.out.mkdir(parents=True, exist_ok=True)
    files = []
    p = a.out / "fig1_site_plan.svg"
    p.write_text(site_plan(data), encoding="utf-8")
    files.append(p)
    seen = {}
    for it in items:
        if it.get("kind", "building") == "building" and it.get("use") not in seen:
            seen[it.get("use")] = it
    for use, it in seen.items():
        if "no cannabis" in str(use).lower() or str(use).lower() == "office":
            continue
        slug = "_".join("".join(ch if ch.isalnum() else " " for ch in str(use).lower()).split())
        p = a.out / f"fig2_unit_{slug}.svg"
        p.write_text(unit_plan(data, str(use), it), encoding="utf-8")
        files.append(p)
    for f in files:
        pdf = None if a.no_pdf else to_pdf(f)
        print(f"wrote {f}" + (f" and {pdf.name}" if pdf else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
