#!/usr/bin/env python3
"""Write docs/ERROR_CODES.md from docs/error-codes.json, the one list of error codes.

    python scripts/render_error_codes.py

The dashboard's Settings > Help page reads the same JSON, and tests/test_error_codes.py fails when the
committed page is not what this writes, so the two cannot drift. Edit the JSON, never the page.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "error-codes.json"
PAGE = ROOT / "docs" / "ERROR_CODES.md"
SEVERITY = {"critical": "Critical", "warning": "Warning", "info": "Information"}
SOURCE_NAME = {"notification": "Notification", "repairs": "Repairs card"}


def render(catalog):
    lines = [
        "# Error codes",
        "",
        "<!-- Generated from docs/error-codes.json by scripts/render_error_codes.py. Edit the JSON. -->",
        "",
        "Each alert from the Crop Steering controller app, and each Crop Steering card in",
        "**Settings → Repairs**, ends with a code, for example **CS-101**. The regular status summary of",
        "the controller has no code. Find the code below. It tells you what the alert means, what occurs",
        "to the water, the probable causes and what to do. The same list is in the Crop Steering sidebar",
        "under **Settings → Help → Error codes**.",
        "",
        "A critical alert, or a warning about a zone that gets no water, comes again each 30 min while its",
        "cause continues. Other warnings come again after 15 min, then less frequently. An information",
        "alert comes once. When the code of an alert changes, the new alert comes after 5 min. CS-403 comes",
        "once each time the controller app starts, and CS-405 comes at the start. A dismissed CS-301 alert",
        "does not clear the hardware hold.",
        "",
        "Most alerts stay in Home Assistant until you dismiss them, also after their cause stops. The",
        "controller removes CS-201, CS-209, CS-210, CS-308 and CS-309 itself. When you set *Room Active* of a room",
        "to off, the controller removes the alerts of the room.",
        "When *Room Active* is off (no plants in the room), the room gives no alerts about water. The",
        "controller still reports a setup change (CS-201) and a hardware hold (CS-301, CS-308, CS-309).",
        "",
        "| Codes | About |",
        "| --- | --- |",
    ]
    for group in catalog["groups"]:
        lines.append(f"| {group['prefix']}xx | **{group['name']}**: {group['detail']} |")
    lines += ["", "## All codes", "", "| Code | What it says | Severity | Shown as |", "| --- | --- | --- | --- |"]
    for entry in catalog["codes"]:
        lines.append(
            f"| [{entry['code']}](#{entry['code'].lower()}) | {entry['title']} | "
            f"{SEVERITY[entry['severity']]} | {SOURCE_NAME[entry['source']]} |"
        )
    for group in catalog["groups"]:
        lines += ["", f"## {group['name']} ({group['prefix']}xx)"]
        for entry in catalog["codes"]:
            if not entry["code"].startswith(group["prefix"]):
                continue
            lines += [
                "",
                f'<a id="{entry["code"].lower()}"></a>',
                "",
                f"### {entry['code']}: {entry['title']}",
                "",
                f"*{SEVERITY[entry['severity']]} · {SOURCE_NAME[entry['source']]}*",
                "",
                f"**What it means.** {entry['meaning']}",
                "",
                f"**Effect on water.** {entry['watering']}",
                "",
                "**Probable causes**",
                "",
                *[f"- {cause}" for cause in entry["causes"]],
                "",
                "**What to do**",
                "",
                *[f"- {fix}" for fix in entry["fixes"]],
            ]
    return "\n".join(lines) + "\n"


def main():
    # newline="\n": the committed page is LF, and on Windows write_text would otherwise write CRLF.
    PAGE.write_text(
        render(json.loads(SOURCE.read_text(encoding="utf-8"))), encoding="utf-8", newline="\n"
    )
    print(f"wrote {PAGE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
