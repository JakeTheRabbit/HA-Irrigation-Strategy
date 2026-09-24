"""Version consistency — the integration's version must match across every surface
that advertises it, so a release can't ship with a stale number somewhere.

Checks: custom_components/crop_steering/manifest.json  ==  the latest released
heading in CHANGELOG.md  ==  the Release badge in README.md.

The f2-control add-on carries its version line in addons/f2_control/config.yaml. From
2.21.0 it is the integration's number (docs/RELEASING.md, Versions); before that the
controller had its own. It is also checked against the add-on's own changelog, and against
the pairing both changelogs advertise: Supervisor offers a controller update the moment
`version:` changes on the branch a box tracks, so a bumped number with no changelog entry
is a release nobody wrote down.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _manifest_version() -> str:
    data = json.loads(
        (ROOT / "custom_components" / "crop_steering" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return data["version"]


def _changelog_version() -> str | None:
    for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s*\[(\d+\.\d+\.\d+)\]", line.strip())
        if m:  # first numbered heading = latest release (skips "[Unreleased]")
            return m.group(1)
    return None


def _readme_badge_version() -> str | None:
    m = re.search(
        r"Release-(\d+\.\d+\.\d+)-", (ROOT / "README.md").read_text(encoding="utf-8")
    )
    return m.group(1) if m else None


def test_integration_version_is_consistent():
    manifest = _manifest_version()
    changelog = _changelog_version()
    readme = _readme_badge_version()
    assert changelog is not None, "CHANGELOG.md has no released `## [x.y.z]` heading"
    assert readme is not None, "README.md has no `Release-x.y.z-` badge"
    assert (
        manifest == changelog == readme
    ), f"version mismatch: manifest.json={manifest} CHANGELOG={changelog} README badge={readme}"


ADDON = ROOT / "addons" / "f2_control"


def _addon_version() -> str:
    match = re.search(
        r'^version:\s*"?(\d+\.\d+\.\d+)"?\s*$',
        (ADDON / "config.yaml").read_text(encoding="utf-8"),
        re.M,
    )
    assert match, "addons/f2_control/config.yaml has no `version: x.y.z`"
    return match.group(1)


def _addon_changelog_version() -> str | None:
    for line in (ADDON / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{1,2}\s*(\d+\.\d+\.\d+)\s*$", line.strip())
        if m:  # the newest entry is first
            return m.group(1)
    return None


def test_controller_version_has_a_changelog_entry():
    """The add-on is built on the box from the branch it tracks, so changing `version:` IS the
    release of the part that drives the pump. It must never go out unexplained."""
    assert _addon_version() == _addon_changelog_version(), (
        f"config.yaml says {_addon_version()}, the newest entry in "
        f"addons/f2_control/CHANGELOG.md is {_addon_changelog_version()}"
    )


def test_the_release_names_the_controller_it_pairs_with():
    """The two halves ship as a pair. The integration's newest changelog entry has to name the
    controller version actually in this tree, or an operator installs a mismatched pair.
    """
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index(f"## [{_manifest_version()}]")
    following = re.search(r"^## \[", text[start + 4 :], re.M)
    entry = text[start : start + 4 + following.start()] if following else text[start:]
    assert _addon_version() in entry, (
        f"the {_manifest_version()} changelog entry never mentions controller "
        f"{_addon_version()}"
    )


ONE_NUMBER_FROM = (2, 21, 0)


def test_from_2_21_the_controller_carries_the_integration_number():
    """One number for the pair. Every release changes both halves anyway (the release guard
    refuses a controller-only release), so a second number only hid a mismatched pair.
    """
    manifest = _manifest_version()
    if tuple(int(part) for part in manifest.split(".")) < ONE_NUMBER_FROM:
        pytest.skip(f"{manifest}: before 2.21.0 the controller had its own number")
    assert _addon_version() == manifest, (
        f"integration {manifest}, controller {_addon_version()}: from 2.21.0 both halves "
        "carry one number (docs/RELEASING.md, Versions)"
    )
