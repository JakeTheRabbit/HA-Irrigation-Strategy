"""What's new: the release highlights the dashboard shows once after an update.

They are custom_components/crop_steering/WHATS_NEW.md, which every release adds its section to in
its release pull request. This reads them as the integration does, and holds the file to its own
rules: the newest section is the version being released, and the lines are for growers.
"""

import json
import re
from datetime import date
from pathlib import Path

from custom_components.crop_steering.whats_new import NOTES, parse, version_key

ROOT = Path(__file__).resolve().parents[1]
FIXES = "Bug fixes and improvements."
# What a grower's line never needs: entity ids, file names, code, pull requests, error codes, links.
TECHNICAL = [
    (
        r"\b(switch|sensor|number|select|input_boolean|binary_sensor)\.[a-z]",
        "an entity id",
    ),
    (r"_", "an underscore (an entity id or a setting's key)"),
    (r"`", "code"),
    (r"\.(py|md|json|yaml|tsx?)\b", "a file name"),
    (r"#\d", "a pull request or issue number"),
    (r"\bCS-\d", "an error code"),
    (r"https?://", "a link"),
]


def _shipped():
    return parse(NOTES.read_text(encoding="utf-8"))


def test_a_section_is_a_heading_and_its_lines():
    text = "\n".join(
        [
            "# What's new",
            "",
            "The rules for writing it, with - a dash that is not an item.",
            "- A rule above every section is not an item either.",
            "",
            "## 2.9.0 - 2026-09-01",
            "",
            "- Older.",
            "## 2.10.0 - 2026-10-01",
            "- Each zone says what it waits for,",
            "  on its card and its grow-day line.",
            "- Bug fixes and improvements.",
            "## Not a release",
            "- Not an item.",
        ]
    )
    assert parse(text) == [  # newest first, by number: 2.10.0 is after 2.9.0
        {
            "version": "2.10.0",
            "date": "2026-10-01",
            "items": [
                "Each zone says what it waits for, on its card and its grow-day line.",
                "Bug fixes and improvements.",
            ],
        },
        {"version": "2.9.0", "date": "2026-09-01", "items": ["Older."]},
    ]


def test_nothing_readable_is_no_releases():
    assert parse("") == []
    assert parse("## 2.25 - soon\n- not a version\n") == []


def test_the_newest_section_is_the_version_being_released():
    manifest = json.loads(
        (ROOT / "custom_components" / "crop_steering" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )["version"]
    releases = _shipped()
    assert releases, "WHATS_NEW.md has no `## x.y.z - YYYY-MM-DD` section"
    assert releases[0]["version"] == manifest, (
        f"WHATS_NEW.md's newest section is {releases[0]['version']}, but this is {manifest}: "
        f"add a `## {manifest} - <release date>` section at the top, written for growers"
    )


def test_sections_run_newest_first_with_real_dates():
    text = NOTES.read_text(encoding="utf-8")
    written = re.findall(r"^## (\d+\.\d+\.\d+) - (\S+)$", text, re.M)
    assert [version for version, _ in written] == [r["version"] for r in _shipped()]
    assert len({version for version, _ in written}) == len(
        written
    ), "a version appears twice"
    dates = [date.fromisoformat(day) for _, day in written]
    assert dates == sorted(dates, reverse=True), "a newer release has an older date"
    assert all(version_key(v) for v, _ in written)


def test_every_release_says_a_little_in_plain_words():
    for release in _shipped():
        items, version = release["items"], release["version"]
        assert 1 <= len(items) <= 5, f"{version}: one to five lines, not {len(items)}"
        assert FIXES not in items[:-1], f"{version}: '{FIXES}' is the last line"
        for item in items:
            assert len(item) <= 160, f"{version}: shorten '{item}'"
            assert item.endswith(
                (".", "!", "?")
            ), f"{version}: end '{item}' with a full stop"
            for pattern, what in TECHNICAL:
                assert not re.search(pattern, item), f"{version}: '{item}' has {what}"
