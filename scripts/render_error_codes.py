#!/usr/bin/env python3
"""Write docs/ERROR_CODES.md from docs/error-codes.json, the one list of error codes.

    python scripts/render_error_codes.py

The dashboard's Help & tools page reads the same JSON, and tests/test_error_codes.py fails when the
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
        "Every notification from the Crop Steering controller app, and every Crop Steering card under",
        "**Settings → Repairs**, ends with a code such as **CS-101**. Find the code below for what it",
        "means, what happens to watering meanwhile, the likely causes and what to do. The same list is",
        "in the Crop Steering sidebar under **Help & tools → Error codes**.",
        "",
        "Most notifications are raised again, at most every 30 minutes, for as long as their cause lasts,",
        "and sooner when the cause changes. A few are said once: CS-301 once per fault (dismissing it does",
        "not clear the hold), CS-403 once each time the controller app starts and CS-405 at start-up. A",
        "notification stays in Home Assistant until you dismiss it, even after its cause has gone.",
        "A room whose *Room Active* switch is off (nothing growing) raises no watering notifications; a",
        "setup change (CS-201) and a hardware hold (CS-301, CS-308, CS-309) are still reported.",
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
                f"**Watering meanwhile.** {entry['watering']}",
                "",
                "**Likely causes**",
                "",
                *[f"- {cause}" for cause in entry["causes"]],
                "",
                "**Suggested fixes**",
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
