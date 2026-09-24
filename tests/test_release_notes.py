"""A release's GitHub notes come from its changelog entry (scripts/release_notes.py).

HACS shows a release's notes in its update dialog. They were one line ("Candidate. Pair:
controller 0.16.5 ..."); the plain-English section written for exactly those readers stayed in
CHANGELOG.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import release_notes  # noqa: E402

REPO = "https://github.com/owner/repo"
CHANGELOG = """# Changelog

## [Unreleased]

### 🌱 In plain English

- Not released yet.

## [2.21.0] - 2026-10-01

Pair: one number. Not run on
hardware.

### 🌱 In plain English

- **Error codes.** See [Error codes](docs/ERROR_CODES.md) and [HACS](https://hacs.xyz),
  wrapped onto a second line.
- A second bullet.

### 🔧 Technical notes

- `controller.py` internals.

## [2.20.0] - 2026-09-01

No plain section here.
"""


def test_the_notes_are_the_opening_and_the_plain_english_section():
    text = release_notes.notes(CHANGELOG, "2.21.0", REPO)
    assert text.startswith("Pair: one number. Not run on hardware.")
    assert "### 🌱 In plain English" in text and "**Error codes.**" in text
    assert "Technical notes" in text and "controller.py internals" not in text
    assert "Not released yet" not in text
    assert text.rstrip().endswith(f"({REPO}/blob/v2.21.0/CHANGELOG.md)")


def test_relative_links_point_at_the_files_at_that_tag():
    text = release_notes.notes(CHANGELOG, "2.21.0", REPO)
    assert f"[Error codes]({REPO}/blob/v2.21.0/docs/ERROR_CODES.md)" in text
    assert "[HACS](https://hacs.xyz)" in text  # absolute links are left alone


def test_a_missing_entry_or_section_is_refused():
    with pytest.raises(SystemExit, match="no entry for 9.9.9"):
        release_notes.notes(CHANGELOG, "9.9.9", REPO)
    with pytest.raises(SystemExit, match="no '### 🌱 In plain English' section"):
        release_notes.notes(CHANGELOG, "2.20.0", REPO)


def test_the_newest_release_in_this_repository_has_notes():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M).group(1)
    text = release_notes.notes(changelog, newest, REPO)
    assert "### 🌱 In plain English" in text and len(text) > 200


def test_wrapped_lines_are_joined_into_their_paragraph_or_bullet():
    text = release_notes.notes(CHANGELOG, "2.21.0", REPO)
    assert "Pair: one number. Not run on hardware." in text
    assert "(https://hacs.xyz), wrapped onto a second line.\n- A second bullet." in text
