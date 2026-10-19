"""Build the illustrated pilot storyboard from the existing, complete spoken scripts.

Python stdlib only. Generated illustrations are copied unchanged; teaching diagrams
are original SVG. HTML assets are local, with no network or Home Assistant access.
"""

from pathlib import Path
import html
import json
import os
import re
import shutil

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
SCRIPTS = ROOT.parent / "PILOT-SCRIPTS.md"
GEN = (
    Path(os.environ["STORYBOARD_GENERATED_IMAGE_DIR"])
    if os.environ.get("STORYBOARD_GENERATED_IMAGE_DIR")
    else None
)
RASTER = {
    "A1-01": "exec-a61a0474-e311-4ce1-8f48-50725a84fcac.png",
    "A1-03": "exec-960c2002-1cbb-487f-9354-9b28d323d8fb.png",
    "A3-03": "exec-2587c7a0-d06a-4899-bb4e-8c84ccf62205.png",
    "C1-01": "exec-8a371815-e3b2-4922-aa13-d30f873413df.png",
    "C1-04": "exec-2061f015-60bf-4ce9-a723-ac6b76baa7f8.png",
    "C1-06": "exec-757fe922-f3b4-4341-978b-0ca426f19073.png",
}
E = html.escape
INK, MUTED, WATER, EC, PAPER = "#25363a", "#647171", "#008cbb", "#b83d82", "#faf7f1"


def text(x, y, value, size=30, fill=INK, weight="400", anchor="start"):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" text-anchor="{anchor}">{E(str(value))}</text>'


def lines(x, y, values, size=28, fill=INK, gap=40, weight="400"):
    return "".join(
        text(x, y + i * gap, v, size, fill, weight) for i, v in enumerate(values)
    )


def rect(x, y, w, h, fill="white", stroke="#dadbd5", radius=20):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'


def line(x1, y1, x2, y2, color=INK, width=3, dash=""):
    return f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}"/>'


def card(x, y, w, h, title, body, accent=WATER):
    return (
        rect(x, y, w, h)
        + rect(x, y, 7, h, accent, accent, 0)
        + text(x + 30, y + 57, title, 31, INK, "600")
        + lines(x + 30, y + 112, body, 25, gap=37)
    )


def sample(x, y, w=430, h=300, saturated=False, dry=False):
    # Conceptual pores and solids, not a physical calibration or quantitative model.
    out = rect(x, y, w, h, "#b8e1ee" if saturated else "#f0ebe1", INK, 10)
    for row in range(4):
        for col in range(6):
            cx = x + 40 + col * (w - 80) / 5 + (10 if row % 2 else 0)
            cy = y + 40 + row * (h - 80) / 3
            out += f'<ellipse cx="{cx}" cy="{cy}" rx="25" ry="20" fill="#998270" stroke="#6d6056" stroke-width="2"/>'
            if not saturated and not dry and row < 3 and col < 4:
                out += f'<ellipse cx="{cx+22}" cy="{cy+28}" rx="22" ry="10" fill="#9bd4e7"/>'
    return out


def graph(stage):
    out = ""

    def x(h):
        return 150 + h / 24 * 1280

    def y(v):
        return 650 - (v - 30) / 40 * 430

    def ey(v):
        return 650 - v / 10 * 430

    out += rect(x(12), 220, x(24) - x(12), 430, "#ece9e1", "#ece9e1", 0)
    out += text(x(12) + 20, 205, "Lights off / night", 23, MUTED)
    for v in [30, 40, 50, 60, 70]:
        out += line(150, y(v), 1430, y(v), "#dfdfd8", 1)
        if stage >= 2:
            out += text(125, y(v) + 8, str(v), 23, MUTED, anchor="end")
    out += line(150, 220, 150, 650) + line(150, 650, 1430, 650)
    if stage >= 2:
        out += text(150, 188, "VWC (%)", 27, WATER, "600")
    if stage >= 3:
        out += line(1430, 220, 1430, 650)
        out += text(1430, 188, "EC (mS/cm)", 27, EC, "600", anchor="end")
        for v in [0, 2, 4, 6, 8, 10]:
            out += text(1451, ey(v) + 8, str(v), 23, MUTED)
    for h in [0, 6, 12, 18, 24]:
        out += line(x(h), 650, x(h), 661)
        out += text(x(h), 693, str(h), 23, MUTED, anchor="middle")
    out += text(790, 731, "Hours after lights-on", 24, MUTED, anchor="middle")
    observed = [
        (0, 44),
        (1, 42),
        (2, 47),
        (2.5, 45),
        (3, 53),
        (3.5, 51),
        (4, 60),
        (6, 55),
        (8, 49),
        (8.1, 54),
        (10, 48),
        (10.1, 53),
        (12, 48),
        (16, 43),
        (20, 39),
        (24, 35),
    ]
    ec = [
        (0, 4.1),
        (2, 4.4),
        (4, 3.8),
        (6, 4.2),
        (8, 4.7),
        (8.1, 4.1),
        (10, 4.6),
        (10.1, 4.3),
        (12, 4.5),
        (16, 5),
        (20, 5.6),
        (24, 6),
    ]
    ref = [
        (0, 44),
        (1, 42),
        (2, 48),
        (3, 55),
        (4, 60),
        (6, 56),
        (8, 50),
        (8.1, 55),
        (10, 50),
        (10.1, 55),
        (12, 51),
        (16, 49),
        (20, 46),
        (24, 44),
    ]
    ecref = [(0, 4.5), (4, 4), (8, 4.4), (12, 4.7), (24, 4.5)]

    def curve(points, color, mapper, dash="", width=4):
        d = "M" + " L".join(f"{x(a):.1f},{mapper(b):.1f}" for a, b in points)
        return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-dasharray="{dash}"/>'

    def point_markers(points, color, mapper, shape):
        result = ""
        for a, b in points:
            cx, cy = x(a), mapper(b)
            if shape == "circle":
                result += f'<circle cx="{cx}" cy="{cy}" r="5" fill="{PAPER}" stroke="{color}" stroke-width="2.5"/>'
            else:
                result += f'<path d="M{cx} {cy-7} l7 7 l-7 7 l-7 -7 z" fill="{PAPER}" stroke="{color}" stroke-width="2.5"/>'
        return result

    if stage >= 2:
        out += curve(observed, WATER, y) + point_markers(observed, WATER, y, "circle")
    if stage >= 3:
        out += curve(ec, EC, ey) + point_markers(ec, EC, ey, "diamond")
    if stage >= 4:
        out += curve(ref, WATER, y, "10 8", 3) + curve(ecref, EC, ey, "4 7", 3)
        for h in [2, 3, 4, 8.1, 10.1]:
            out += f'<path d="M{x(h)} 622 l-7 13 h14 z" fill="{INK}"/>'
    if stage == 5:
        out += line(x(12), y(35), x(24), y(35), "#6d7474", 3, "6 7")
        out += line(x(12), y(39), x(24), y(39), "#a75912", 4, "12 6")
        out += text(x(12) + 16, y(39) - 15, "Draft floor 39%", 24, "#99520f", "600")
        out += text(x(12) + 16, y(35) + 33, "Saved floor 35%", 22, MUTED)
        out += line(x(20), y(35) - 4, x(20), y(39) + 4, "#a75912", 3)
    if stage >= 2:
        out += (
            line(150, 779, 193, 779, WATER, 4)
            + f'<circle cx="171" cy="779" r="5" fill="{PAPER}" stroke="{WATER}" stroke-width="2.5"/>'
            + text(204, 787, "Synthetic observed VWC", 23)
        )
    if stage >= 3:
        out += (
            line(630, 779, 673, 779, EC, 4)
            + f'<path d="M651 772 l7 7 l-7 7 l-7 -7 z" fill="{PAPER}" stroke="{EC}" stroke-width="2.5"/>'
            + text(684, 787, "Synthetic observed EC", 23)
        )
    if stage >= 4:
        out += line(1110, 779, 1150, 779, MUTED, 3, "8 6") + text(
            1161, 787, "Dashed/dotted: refs", 22
        )
    out += text(
        80,
        852,
        "Example only. Separate axes; illustrative traces are not crop predictions.",
        24,
        MUTED,
    )
    if stage == 6:
        out += text(
            80, 105, "Which axis? Which line? How fresh is the reading?", 37, INK, "600"
        )
    return out


def diagram(kind):
    if kind == "root":
        return (
            sample(120, 250)
            + lines(670, 270, ["Inside the root zone"], 38, weight="600")
            + card(
                670,
                320,
                760,
                320,
                "Three components",
                [
                    "Solids: the growing medium",
                    "Water: some of the pore space",
                    "Air: some of the pore space",
                ],
            )
            + text(
                120,
                725,
                "Conceptual cross-section; proportions are not measured.",
                25,
                MUTED,
            )
        )
    if kind == "recall":
        return (
            sample(120, 250)
            + lines(
                690,
                320,
                [
                    "Name the three components.",
                    "1. __________________",
                    "2. __________________",
                    "3. __________________",
                ],
                36,
                gap=80,
            )
            + text(120, 725, "Pause before revealing the labels.", 28, MUTED)
        )
    if kind == "wetdry":
        return (
            sample(140, 250, saturated=True)
            + sample(920, 250, dry=True)
            + text(140, 605, "Very wet", 36, weight="600")
            + text(920, 605, "Drying", 36, weight="600")
            + lines(
                140,
                700,
                [
                    "Similar symptoms can have different causes.",
                    "Check the root zone before adding more water.",
                ],
                32,
            )
        )
    if kind == "sensorlimits":
        return (
            card(
                100,
                220,
                410,
                250,
                "Local measurement",
                ["One probe", "One sensing region", "Not every pot"],
            )
            + text(545, 365, "→", 60)
            + card(
                630,
                220,
                410,
                250,
                "A trend",
                ["Changes over time", "Freshness matters", "Not a diagnosis"],
            )
            + text(1070, 365, "→", 60)
            + card(
                1150,
                220,
                350,
                250,
                "Check",
                ["Equipment", "Other readings", "Observation"],
            )
            + text(
                100,
                550,
                "A smooth line does not prove uniform delivery.",
                34,
                weight="600",
            )
            + f'<g transform="translate(100 610) scale(0.65)">{sample(0,0)}</g>'
            + lines(
                490,
                650,
                [
                    "Teach back:",
                    "Point to solids, water and air.",
                    "Name one sensor limitation.",
                ],
                30,
                gap=50,
            )
        )
    if kind == "ten":
        out = text(100, 250, "Six of ten equal volumes are water.", 40, weight="600")
        for i in range(10):
            out += rect(
                100 + i * 140, 330, 120, 190, "#9bd4e7" if i < 6 else "#e8e1d6", INK, 8
            )
        return (
            out
            + text(100, 590, "6 ÷ 10 × 100 = 60% VWC", 52, WATER, "600")
            + lines(
                100,
                675,
                [
                    "The rest includes solids AND air.",
                    "These blocks explain a fraction, not the physical arrangement of water.",
                ],
                28,
                MUTED,
            )
        )
    if kind == "volume":
        out = text(110, 250, "A hypothetical uniform 5 L sample", 40, weight="600")
        for i in range(5):
            out += rect(
                110 + i * 270, 320, 240, 190, "#9bd4e7" if i < 3 else "#e8e1d6", INK, 12
            )
        return (
            out
            + text(110, 585, "3 L water ÷ 5 L total × 100 = 60%", 46, WATER, "600")
            + lines(
                110,
                675,
                [
                    "A volume explanation, not an instruction to add 3 L.",
                    "A local probe does not establish the average of an entire pot.",
                ],
                28,
                MUTED,
            )
        )
    if kind == "localprobe":
        out = (
            sample(150, 250, 640, 390)
            + f'<ellipse cx="470" cy="420" rx="95" ry="95" fill="#d5eff8" opacity="0.8" stroke="{WATER}" stroke-width="3" stroke-dasharray="9 6"/>'
        )
        out += rect(458, 190, 24, 250, INK, INK, 6)
        return (
            out
            + card(
                930,
                270,
                540,
                310,
                "A local sensing region",
                [
                    "Placement and contact matter.",
                    "Calibration and medium matter.",
                    "One probe is not the whole zone.",
                ],
            )
            + text(
                150,
                735,
                "Sensing-region illustration only; no fixed dimensions implied.",
                25,
                MUTED,
            )
        )
    if kind == "misconceptions":
        return (
            card(
                100,
                240,
                660,
                340,
                "Is the rest all air?",
                ["No. The remaining volume", "includes solids and air."],
            )
            + card(
                820,
                240,
                660,
                340,
                "Is this usable water left?",
                ["No. VWC is a volume fraction,", "not a plant-available fuel gauge."],
                EC,
            )
            + lines(
                100,
                700,
                [
                    "Teach back: “60% of the sample volume is water.”",
                    "Then name one limitation of the reading.",
                ],
                32,
            )
        )
    if kind == "full":
        return (
            sample(120, 260)
            + text(700, 330, "“Full” ≠ 100% VWC", 53, INK, "600")
            + lines(
                700,
                430,
                [
                    "The total volume still includes solids.",
                    "Ask which drained condition",
                    "the operating reference represents.",
                ],
                33,
                gap=55,
            )
            + text(
                120,
                740,
                "No universal percentage is prescribed in this lesson.",
                28,
                MUTED,
            )
        )
    if kind == "saturation":
        return (
            sample(120, 250, 650, 380, saturated=True)
            + card(
                900,
                260,
                570,
                350,
                "Saturation",
                [
                    "Pore spaces filled with water.",
                    "Solid material is still present.",
                    "Not an all-day operating goal.",
                ],
            )
            + text(
                120,
                730,
                "Conceptual cross-section; no numeric capacity is implied.",
                26,
                MUTED,
            )
        )
    if kind == "states":
        return (
            card(
                100,
                250,
                430,
                350,
                "Saturation",
                ["Physical condition", "Pores filled with water"],
            )
            + card(
                585,
                250,
                430,
                350,
                "Drained capacity",
                ["Physical condition", "Defined drainage method"],
            )
            + card(
                1070,
                250,
                430,
                350,
                "App reference",
                ["Configured setting", "Needs measured evidence"],
                EC,
            )
            + text(
                100,
                720,
                "The setting does not prove the physical condition.",
                35,
                weight="600",
            )
        )
    if kind == "reference":
        out = (
            card(
                110,
                220,
                650,
                310,
                "Teaching example: 60%",
                ["A hypothetical reference.", "Not a target to copy."],
            )
            + card(
                830,
                220,
                650,
                310,
                "Your container",
                [
                    "Medium + dimensions",
                    "Drainage protocol + sensor",
                    "Repeat and verify",
                ],
                EC,
            )
            + text(
                110,
                610,
                "A peak reading alone is not a calibration procedure.",
                32,
                weight="600",
            )
        )
        for i, name in enumerate(
            ["Saturation", "Drained capacity", "Configured reference"]
        ):
            out += rect(110 + i * 470, 680, 430, 110) + text(
                140 + i * 470, 745, name, 29, weight="600"
            )
        return out
    if kind.startswith("graph"):
        return graph(int(kind[-1]))
    if kind == "hostcontrol":
        out = card(
            100, 190, 650, 150, "Choose ONE host", ["Supported Pi OR supported x86-64"]
        ) + card(
            830, 190, 650, 150, "Same shared setup", ["HAOS + integration + Controller"]
        )
        out += text(80, 405, "READINGS / DEVICE PATH", 24, MUTED, "600")
        titles = [
            ["Probe"],
            ["Compatible", "interface"],
            ["HA sensor", "entity"],
            ["Controller"],
            ["Mapped", "output"],
        ]
        for i, words in enumerate(titles):
            xx = 80 + i * 300
            out += rect(xx, 440, 250, 140) + lines(
                xx + 25, 490, words, 28, gap=38, weight="600"
            )
            if i < 4:
                out += text(xx + 264, 520, "→", 32)
        out += text(
            80, 635, "CONFIGURATION / REVIEWED OPERATOR INPUT", 24, MUTED, "600"
        )
        for i, (title, body) in enumerate(
            [
                ("Reviewed configuration", "Not a sensor reading"),
                ("Crop Steering integration", "Stores / provides configuration"),
                ("Same Controller", "Uses reviewed configuration"),
            ]
        ):
            xx = 80 + i * 480
            out += (
                rect(xx, 670, 420, 125)
                + text(xx + 22, 715, title, 27, weight="600")
                + text(xx + 22, 760, body, 22, MUTED)
            )
            if i < 2:
                out += text(xx + 434, 742, "→", 32)
        return out + text(
            80,
            845,
            "The measurement and configuration paths are separate inputs.",
            25,
            MUTED,
        )
    if kind == "waterpaths":
        out = text(85, 225, "A — suitable pressurised supply", 34, weight="600")
        rows = [
            ["Supply", "Protection*", "Zone valve", "Emitters", "Pots / drain"],
            ["Reservoir", "Pump*", "Protection*", "Zone valve", "Emitters / pots"],
        ]
        for r, names in enumerate(rows):
            if r:
                out += text(
                    85,
                    500,
                    "B — reservoir route, when a pump is needed",
                    34,
                    weight="600",
                )
            yy = 275 + r * 275
            for i, name in enumerate(names):
                out += rect(85 + i * 290, yy, 250, 125) + text(
                    210 + i * 290, yy + 73, name, 28, weight="600", anchor="middle"
                )
                if i < 4:
                    out += text(347 + i * 290, yy + 77, "→", 31)
        return out + lines(
            85,
            765,
            [
                "* Match actual equipment, order and protections to the installed design.",
                "Functional diagrams only — not plumbing or electrical construction drawings.",
            ],
            25,
            MUTED,
            gap=40,
        )
    if kind == "kit":
        return (
            card(
                85,
                230,
                440,
                440,
                "Start here",
                [
                    "Supported host + network",
                    "Compatible VWC reading",
                    "Safe controllable water path",
                    "Known emitters + sizing",
                    "Isolation + independent protection",
                ],
            )
            + card(
                580,
                230,
                440,
                440,
                "Depends on the system",
                [
                    "Pump: only if needed",
                    "Bridge: if probe needs it",
                    "Identified EC: for EC lessons",
                    "Useful climate/feed readings",
                ],
            )
            + card(
                1075,
                230,
                440,
                440,
                "Add later",
                [
                    "Extra representative probes",
                    "Verified flow measurement",
                    "UPS / expanded monitoring",
                    "Advanced dosing or AI",
                ],
                EC,
            )
            + text(
                85,
                765,
                "Buy verified functions, not every dashboard accessory.",
                32,
                weight="600",
            )
        )
    raise ValueError(kind)


# [paragraph start, paragraph end): partitions include every spoken paragraph once.
SCENES = {
    "A1": [
        (
            "The question",
            0,
            1,
            "A1-01",
            "Medium shot, locked camera",
            "Open beside one unplanted pot. Leave space for the title.",
            "Before the buttons",
            "Keep the question short; no dashboard montage.",
            4,
        ),
        (
            "Inside the root zone",
            1,
            3,
            "root",
            "Graphic, slow push-in",
            "Reveal solids, then water, then air as they are named.",
            "Solids · water · air",
            "Conceptual proportions; do not imply a measured air fraction.",
            8,
        ),
        (
            "Watch water arrive and drain",
            3,
            4,
            "A1-03",
            "Bench close-up",
            "Show a small pour and actual drainage into a tray.",
            "Some stays. Some drains.",
            "Use spare medium. Identify any time compression.",
            14,
        ),
        (
            "Pause before adding water",
            4,
            8,
            "wetdry",
            "Two-state teaching graphic",
            "Ask the question; hold before revealing the answer.",
            "More water — or check first?",
            "Do not diagnose crop symptoms from one cartoon.",
            12,
        ),
        (
            "What steering and sensing can do",
            8,
            13,
            "sensorlimits",
            "Graphic, then return to presenter",
            "Explain steering, sensor limits and the learner teach-back.",
            "Measure · check · observe",
            "Reveal each card in order. Do not promise yield or stress benefits.",
            10,
        ),
    ],
    "A2": [
        (
            "Recall before the reveal",
            0,
            2,
            "recall",
            "Full-screen teaching graphic",
            "Ask for the three components, then reveal labels.",
            "Name the three parts",
            "Give a real recall pause before the answer.",
            8,
        ),
        (
            "Six out of ten",
            2,
            5,
            "ten",
            "Progressive ten-volume diagram",
            "Colour exactly six equal blocks as water.",
            "60% VWC = 6 / 10 by volume",
            "Explain the simplified fraction; blocks are not actual pore geometry.",
            8,
        ),
        (
            "Put litres beside the fraction",
            5,
            6,
            "volume",
            "Graphic, one calculation",
            "Reveal 5 L total, then 3 L water, then the equation.",
            "3 L ÷ 5 L × 100 = 60%",
            "This is a hypothetical uniform sample, not an instruction to water.",
            8,
        ),
        (
            "The probe sees a region",
            6,
            11,
            "localprobe",
            "Probe-region graphic with answer reveal",
            "Explain solids/air and usable-water misconceptions before showing local sensing.",
            "Local reading ≠ entire zone",
            "Do not imply a real probe has this exact sensing radius.",
            8,
        ),
        (
            "Teach it back",
            11,
            18,
            "misconceptions",
            "Question/answer cards",
            "Ask whether 40% is automatically dry, then invite the learner sentence.",
            "What does 60% mean?",
            "No universal target. Pause before each answer.",
            14,
        ),
    ],
    "A3": [
        (
            "What does full mean?",
            0,
            2,
            "full",
            "Teaching graphic, no dashboard",
            "Ask the question and recall the solid fraction.",
            "Full of what?",
            "Do not equate useful capacity with 100% VWC.",
            6,
        ),
        (
            "Saturation is a physical state",
            2,
            3,
            "saturation",
            "Conceptual cross-section",
            "Show water in pores while solids remain visible.",
            "Pores full of water",
            "Not a recommended all-day condition.",
            8,
        ),
        (
            "Observe drainage",
            3,
            7,
            "A3-03",
            "Bench close-up with inserts",
            "Watch drainage; cut to notebook/weight only as supporting observations.",
            "Define and repeat your method",
            "Record conditions and elapsed time; no universal drainage interval.",
            16,
        ),
        (
            "Physical state or entered setting?",
            7,
            8,
            "states",
            "Three-card graphic",
            "Separate saturation, drained capacity and software reference.",
            "A reference needs evidence",
            "A field in the app is not proof of correct measurement.",
            6,
        ),
        (
            "An example is not your target",
            8,
            15,
            "reference",
            "Question, then card-sort activity",
            "Pause, reject target copying, sort the cards and hand off to dryback.",
            "Example only — not a recipe",
            "Retain medium/container/protocol context; do not adopt highest-ever reading.",
            16,
        ),
    ],
    "B1": [
        (
            "Start with time",
            0,
            2,
            "graph1",
            "Progressive graph, static axes",
            "Reveal time and night shading before any data.",
            "Time moves to the right",
            "Elapsed hours after lights-on, not arbitrary clock hours.",
            6,
        ),
        (
            "Add water content",
            2,
            3,
            "graph2",
            "Graph, point highlight",
            "Reveal the blue VWC trace and its left-hand scale.",
            "VWC uses the left axis (%)",
            "Synthetic teaching data, not a private grow capture.",
            6,
        ),
        (
            "Add EC and a second scale",
            3,
            7,
            "graph3",
            "Graph, alternate axis highlights",
            "Reveal EC with its own scale; ask about crossing lines.",
            "EC uses the right axis (mS/cm)",
            "Name the actual measurement type when filming; never silently rename bulk EC.",
            12,
        ),
        (
            "Events, observations and references",
            7,
            9,
            "graph4",
            "Graph, reveal one layer at a time",
            "Add event triangles, then clearly dashed references.",
            "Observed ≠ reference",
            "A plausible shape is not proof of cause or a crop forecast.",
            8,
        ),
        (
            "Continue into night; move a threshold",
            9,
            12,
            "graph5",
            "Graph, then version-checked demo capture",
            "Follow continuous references into morning; animate only the draft floor upward.",
            "Draft floor moves; observations stay",
            "Dashed overnight EC joins references. The saved floor remains for comparison.",
            8,
        ),
        (
            "Explain what changed",
            12,
            16,
            "graph6",
            "Question hold, then graph labels",
            "Ask the three-way question, reveal the answer and complete axis checks.",
            "A draft, not a guaranteed shot",
            "Keep review/apply/readback separate. Do not imply historical values moved.",
            12,
        ),
    ],
    "C1": [
        (
            "Five functions, not a shopping spree",
            0,
            1,
            "C1-01",
            "Overhead equipment lay-flat",
            "Reveal the functions before discussing brands.",
            "Host · measure · deliver · control · prove",
            "Illustrative props, not a tested model-specific shopping cart.",
            6,
        ),
        (
            "Host and measurement paths",
            1,
            5,
            "hostcontrol",
            "Graphic with equipment inserts",
            "Introduce either host, HA entities, both program components and identified sensors.",
            "Choose one host; verify the probe",
            "EC type matters. A compatible interface is not proven calibration.",
            8,
        ),
        (
            "Draw the actual water path",
            5,
            6,
            "waterpaths",
            "Two functional diagrams",
            "Show pressurised supply separately from a reservoir/pump path.",
            "A pump is conditional",
            "Installed order/protections must be designed for the actual equipment.",
            8,
        ),
        (
            "Safe control and proof",
            6,
            9,
            "C1-04",
            "Catch-test close-up; separate dry control insert",
            "Explain rated controls, one owner per output, catch volumes and physical shutdown.",
            "Measure delivery. Prove stopping.",
            "No mains demonstration. Illustrative stop prop does not certify protection; keep controls dry.",
            10,
        ),
        (
            "Essentials, conditional, later",
            9,
            10,
            "kit",
            "Three-column graphic",
            "Place additional monitoring and advanced features in context.",
            "Build one proven zone first",
            "Do not describe AI/dosing/thermal cameras as beginner requirements.",
            6,
        ),
        (
            "Your own layout",
            10,
            13,
            "C1-06",
            "Overhead learner worksheet",
            "Pause for drawing; circle unknown functions and choose a host route.",
            "Sketch · label · check",
            "Use exact-model compatibility sheet before buying or energising.",
            20,
        ),
    ],
}


def svg_asset(scene_id, kind, title):
    body = diagram(kind)
    heading = "" if kind == "graph6" else text(80, 115, title, 42, weight="600")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" role="img" aria-labelledby="title desc"><title id="title">{E(title)}</title><desc id="desc">Conceptual educational storyboard frame for {E(scene_id)}. Numbers are teaching examples, not crop targets.</desc><rect width="1600" height="900" fill="{PAPER}"/><g font-family="Arial, Helvetica, sans-serif">{text(80,57,scene_id+' / CROP STEERING FROM ZERO',22,MUTED)}{heading}{body}{text(80,889,'Teaching illustration • example values only • not a product screenshot',19,MUTED)}</g></svg>"""
    path = ASSETS / (scene_id + ".svg")
    path.write_text(svg, encoding="utf-8")
    return path


def timecode(seconds):
    return f"{seconds//60:02d}:{seconds%60:02d}"


def main():
    source = SCRIPTS.read_text(encoding="utf-8")
    blocks = re.split(r"^## ", source, flags=re.M)[1:]
    lessons = []
    for block in blocks:
        title = block.splitlines()[0]
        code = title.split()[0]
        speech = block.split("### Spoken script\n\n", 1)[1].split(
            "\n\n**Exit answer:**", 1
        )[0]
        paras = speech.split("\n\n")
        scenes = []
        cursor = 0
        covered = []
        for idx, (
            name,
            start,
            end,
            kind,
            camera,
            action,
            overlay,
            accuracy,
            hold,
        ) in enumerate(SCENES[code], 1):
            sid = f"{code}-{idx:02d}"
            assert start == len(covered), (sid, "gap or duplication")
            covered.extend(range(start, end))
            excerpt = paras[start:end]
            words = len(
                re.findall(
                    r"\b[\w'-]+\b",
                    " ".join(p for p in excerpt if not p.startswith("[")),
                )
            )
            duration = round(words * 60 / 130) + hold
            if kind in RASTER:
                path = ASSETS / (sid + ".png")
                if GEN and (GEN / RASTER[kind]).exists():
                    shutil.copy2(GEN / RASTER[kind], path)
                assert path.exists(), path
                origin = "AI-generated filming illustration; built-in image_gen"
            else:
                path = svg_asset(sid, kind, name)
                origin = "Original deterministic SVG teaching diagram"
            scenes.append(
                dict(
                    id=sid,
                    title=name,
                    image="assets/" + path.name,
                    alt=action,
                    camera=camera,
                    action=action,
                    overlay=overlay,
                    accuracy=accuracy,
                    narration=excerpt,
                    words=words,
                    start=cursor,
                    end=cursor + duration,
                    time=f"{timecode(cursor)}–{timecode(cursor+duration)}",
                    origin=origin,
                )
            )
            cursor += duration
        assert covered == list(range(len(paras))), (code, "omitted narration")
        lessons.append(
            dict(id=code, title=title.split(" — ", 1)[1], seconds=cursor, scenes=scenes)
        )
    assert sum(len(lesson["scenes"]) for lesson in lessons) == 27
    (ROOT / "scenes.json").write_text(
        json.dumps(
            dict(
                title="Crop Steering from Zero — illustrated pilots",
                date="2026-10-19",
                status="Storyboard for review; not recorded footage",
                timing="Proposed at 130 spoken words/minute plus demonstration/learner holds; verify by read-through.",
                lessons=lessons,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_html(lessons)
    write_markdown(lessons)
    print(
        f"Built {len(lessons)} lessons / 27 scene images; every spoken paragraph assigned exactly once."
    )
    print(
        "Proposed runtimes:",
        ", ".join(
            lesson["id"] + " " + timecode(lesson["seconds"]) for lesson in lessons
        ),
    )


def write_html(lessons):
    nav = "".join(
        f'<a href="#{lesson["id"]}">{lesson["id"]} <span>{E(lesson["title"])}</span></a>'
        for lesson in lessons
    )
    parts = []
    for lesson in lessons:
        parts.append(
            f'<section class="lesson" id="{lesson["id"]}"><header class="lesson-heading"><p class="eyebrow">PILOT {lesson["id"]} · {len(lesson["scenes"])} SCENES · PROPOSED {timecode(lesson["seconds"])}</p><h2>{E(lesson["title"])}</h2></header>'
        )
        for scene in lesson["scenes"]:
            narration = "".join(
                f'<p class="{"pause" if p.startswith("[") else ""}">{E(p)}</p>'
                for p in scene["narration"]
            )
            parts.append(
                f"""<article class="scene" id="{scene['id']}"><header class="scene-title"><span class="scene-code">{scene['id']}</span><h3>{E(scene['title'])}</h3><span class="timing">{scene['time']}</span></header><div class="scene-layout"><div class="visual"><img loading="eager" src="{scene['image']}" alt="{E(scene['alt'])}" width="1600" height="900"><div class="overlay"><small>ON-SCREEN TEXT</small><strong>{E(scene['overlay'])}</strong></div><dl><dt>Camera / format</dt><dd>{E(scene['camera'])}</dd><dt>Action / edit</dt><dd>{E(scene['action'])}</dd><dt>Accuracy / staging</dt><dd>{E(scene['accuracy'])}</dd></dl><p class="origin">{E(scene['origin'])}</p></div><div class="voice"><h4>Narration &amp; learner pauses</h4>{narration}</div></div></article>"""
            )
        parts.append("</section>")
    css = """*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:110px}body{margin:0;background:#f2f1ec;color:#25363a;font:16px/1.55 Arial,Helvetica,sans-serif}a{color:#006c90}button,a{touch-action:manipulation}header.cover{max-width:1320px;margin:0 auto;padding:65px 40px 40px}.eyebrow{font-size:12px;letter-spacing:1.8px;font-weight:700;color:#60716d}h1{font-size:clamp(36px,5vw,66px);line-height:1.06;letter-spacing:-2px;margin:20px 0}h1 span{color:#008cbb}p.lead{max-width:820px;font-size:21px;color:#536261}.facts{display:flex;gap:30px;flex-wrap:wrap;margin:25px 0}.facts strong{display:block;font-size:27px}.facts span{font-size:13px;color:#62706b}.tools{display:flex;gap:10px;flex-wrap:wrap;margin-top:25px}.button,button{display:inline-block;border:1px solid #a8bab6;background:#fff;border-radius:8px;padding:10px 16px;font:inherit;color:#25363a;text-decoration:none;cursor:pointer}.button.primary,button{background:#253f3c;color:white;border-color:#253f3c}.notice{max-width:940px;border-left:3px solid #b83d82;padding-left:16px;color:#63706d;font-size:14px}nav{position:sticky;top:0;z-index:10;background:#f8f7f2f5;backdrop-filter:blur(12px);border-block:1px solid #d8ded7;display:flex;gap:8px;padding:12px max(20px,calc((100vw - 1240px)/2));overflow:auto}nav a{white-space:nowrap;text-decoration:none;background:white;border:1px solid #dce1d9;border-radius:7px;padding:9px 12px;font-size:13px;font-weight:bold}nav a span{font-weight:400;display:inline-block;max-width:145px;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom}main{max-width:1320px;margin:auto;padding:0 40px 60px}.lesson-heading{padding:55px 0 20px}h2{font-size:31px;line-height:1.2;margin:8px 0}.scene{margin:0 0 35px;background:#fff;border:1px solid #dce0d8;border-radius:12px;overflow:hidden;scroll-margin-top:105px;box-shadow:0 8px 28px #263c3410}.scene-title{display:flex;align-items:center;gap:15px;padding:17px 22px;border-bottom:1px solid #e4e6e0}.scene-code{color:#007ba3;font-size:12px;font-weight:bold;letter-spacing:1px}h3{font-size:19px;line-height:1.25;margin:0}.timing{font-size:13px;color:#697972;margin-left:auto;white-space:nowrap}.scene-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr)}.visual{border-right:1px solid #e5e8df}.visual img{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:contain;background:#faf7f1}.overlay{padding:13px 22px;background:#f0f6f5;border-block:1px solid #e4e8df}.overlay small{font-size:10px;letter-spacing:1px;color:#63716d;display:block}.overlay strong{font-size:16px;font-weight:500}dl{padding:5px 22px 0;font-size:13px;display:grid;grid-template-columns:112px 1fr;gap:9px 12px}dt{color:#6b7972}dd{margin:0}.origin{padding:0 22px 14px;font-size:11px;color:#748078}.voice{padding:22px 25px;align-self:start}.voice h4{margin:0 0 15px;font-size:11px;letter-spacing:1.3px;text-transform:uppercase;color:#65756d}.voice p{font-size:14px;line-height:1.65;margin:0 0 12px}.voice .pause{color:#8b4670;background:#f8eef3;border-radius:5px;padding:7px 10px;font-style:italic}footer{font-size:13px;color:#6e7b73;border-top:1px solid #dce0d8;padding-top:20px}body.contact .voice,body.contact dl,body.contact .origin{display:none}body.contact .lesson{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}body.contact .lesson-heading{grid-column:1/-1}body.contact .scene{margin:0}body.contact .scene-layout{display:block}body.contact .scene-title{padding:10px;flex-wrap:wrap;gap:6px}body.contact h3{font-size:14px}body.contact .timing{font-size:11px}body.contact .overlay{padding:10px;font-size:12px}body.contact .overlay strong{font-size:12px}body.contact .visual{border:0}@media(max-width:850px){header.cover{padding:35px 20px}main{padding:0 18px 40px}.scene-layout{grid-template-columns:1fr}.visual{border-right:0}body.contact .lesson{grid-template-columns:repeat(2,minmax(0,1fr))}.scene-title{flex-wrap:wrap}h2{font-size:26px}}@media(max-width:520px){body.contact .lesson{grid-template-columns:1fr}nav a span{display:none}}@page{size:A4 landscape;margin:12mm}@media print{html{scroll-padding:0}body{background:#fff;font-size:11px;print-color-adjust:exact;-webkit-print-color-adjust:exact}nav,.tools{display:none!important}header.cover{height:175mm;padding:18mm 8mm;break-after:page}h1{font-size:48px}.lead{font-size:18px!important}.facts{margin:18px 0}.notice{font-size:11px}main{padding:0;max-width:none}.lesson{display:block!important}.lesson-heading{padding:0 0 8px;break-after:avoid}.lesson-heading h2{font-size:20px}.lesson-heading .eyebrow{font-size:10px;margin:0 0 3px}.scene{break-inside:avoid;break-after:page;margin:0;border:0;border-radius:0;box-shadow:none}.scene-title{padding:6px 0 10px}.scene-title h3{font-size:17px}.scene-layout{grid-template-columns:1.12fr 1fr;gap:18px}.visual{border:0}.visual img{width:100%;height:auto}.overlay{padding:7px 10px}.overlay strong{font-size:13px}dl{font-size:10px;padding:0;grid-template-columns:85px 1fr;gap:5px 9px}.origin{font-size:8px;padding:0}.voice{padding:0}.voice h4{font-size:9px;margin-bottom:8px}.voice p{font-size:10.5px;line-height:1.4;margin-bottom:7px}.voice .pause{padding:4px 8px}.timing{font-size:10px}.scene-code{font-size:10px}.eyebrow{font-size:11px}footer{display:none}body.contact .lesson{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;break-after:page}body.contact .scene{break-after:auto;border:1px solid #dce0d8}body.contact .scene-layout{display:block}body.contact .scene-title h3{font-size:11px}body.contact .overlay strong{font-size:10px}body.contact .lesson-heading{padding:0}.lesson:last-child .scene:last-child{break-after:auto}}"""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Crop Steering from Zero — illustrated storyboard</title><style>{css}</style></head><body><header class="cover"><p class="eyebrow">CROP STEERING FROM ZERO / VISUAL PRODUCTION PACK / 19 OCTOBER 2026</p><h1>Understand the pot.<br><span>Then touch the controls.</span></h1><p class="lead">An illustrated scene-by-scene storyboard for the five pilot lessons. Real objects first, precise measurement diagrams second, software decisions last.</p><div class="facts"><div><strong>5</strong><span>PILOT LESSONS</span></div><div><strong>27</strong><span>SCENES WITH IMAGES</span></div><div><strong>16:9</strong><span>FILMING FRAMES</span></div></div><p class="notice">For review and filming preparation, not recorded footage. Images include six AI-generated filming illustrations and 21 original teaching diagrams. Numeric curves are synthetic examples, not recommended settings or crop forecasts. Timings are proposed from a 130-word/minute read plus learner/demo holds. Final performance determines the edit.</p><div class="tools"><button type="button" onclick="document.body.classList.toggle('contact');this.setAttribute('aria-pressed',document.body.classList.contains('contact'))" aria-pressed="false">Toggle contact sheet</button><button type="button" onclick="window.print()">Print / save PDF</button><a class="button" href="storyboard.pdf">Download PDF</a><a class="button" href="../PILOT-SCRIPTS.md">Full pilot scripts</a></div></header><nav aria-label="Pilot lessons">{nav}</nav><main>{''.join(parts)}<footer>Scope: every scene in A1, A2, A3, B1 and C1. The remaining course episodes have briefs and are not represented as completed visual storyboards. Full narration is retained, partitioned once across these scenes. See scenes.json for structured shot data and image origin.</footer></main><script>if(new URLSearchParams(location.search).has('contact'))document.body.classList.add('contact');</script></body></html>"""
    (ROOT / "index.html").write_text(page, encoding="utf-8")


def write_markdown(lessons):
    out = [
        "# Illustrated pilot storyboard",
        "",
        "[Open the visual storyboard](index.html) · [Printable PDF](storyboard.pdf)",
        "",
        "27 scenes across five pilot lessons. Images are filming illustrations or precise teaching diagrams, not installation evidence. Timing is proposed, not a recorded runtime.",
        "",
    ]
    for lesson in lessons:
        out += ["## " + lesson["id"] + " — " + lesson["title"], ""]
        for s in lesson["scenes"]:
            out += [
                f'### {s["id"]} — {s["title"]}',
                "",
                f'![{s["alt"]}]({s["image"]})',
                "",
                f'**Proposed time:** {s["time"]} · **Camera:** {s["camera"]}',
                "",
                f'**Action:** {s["action"]}',
                "",
                f'**On-screen text:** {s["overlay"]}',
                "",
                f'**Accuracy/staging:** {s["accuracy"]}',
                "",
                "**Narration:**",
                "",
                *s["narration"],
                "",
            ]
    (ROOT / "STORYBOARD.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
