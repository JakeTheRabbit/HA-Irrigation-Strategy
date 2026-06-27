"""Version consistency — the integration's version must match across every surface
that advertises it, so a release can't ship with a stale number somewhere.

Checks: custom_components/crop_steering/manifest.json  ==  the latest released
heading in CHANGELOG.md  ==  the Release badge in README.md.

(The f2-control add-on carries its own independent version line in
addons/f2_control/config.yaml; that is synced to the dedicated add-on repo by
scripts/publish_addon.sh and is not part of this integration-release check.)
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _manifest_version() -> str:
    data = json.loads((ROOT / "custom_components" / "crop_steering" / "manifest.json").read_text(encoding="utf-8"))
    return data["version"]


def _changelog_version() -> str | None:
    for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s*\[(\d+\.\d+\.\d+)\]", line.strip())
        if m:  # first numbered heading = latest release (skips "[Unreleased]")
            return m.group(1)
    return None


def _readme_badge_version() -> str | None:
    m = re.search(r"Release-(\d+\.\d+\.\d+)-", (ROOT / "README.md").read_text(encoding="utf-8"))
    return m.group(1) if m else None


def test_integration_version_is_consistent():
    manifest = _manifest_version()
    changelog = _changelog_version()
    readme = _readme_badge_version()
    assert changelog is not None, "CHANGELOG.md has no released `## [x.y.z]` heading"
    assert readme is not None, "README.md has no `Release-x.y.z-` badge"
    assert manifest == changelog == readme, (
        f"version mismatch: manifest.json={manifest} CHANGELOG={changelog} README badge={readme}"
    )
