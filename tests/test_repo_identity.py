"""One repository, everywhere: this one.

`repository.yaml` is what the Supervisor shows for the app repository a box added, and the app's
`config.yaml` carries the link its store page opens. Both name this repository, so a box never
sends an operator to a copy that gets no updates. Neither decides the Supervisor id (the slug and
the repository address the box added do), so this content can change without moving an install.

The same holds for every other link a shipped file carries: the integration's manifest, HACS, the
README and docs, the app's store page and the dashboard all point here, and nowhere else.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy"
REPOSITORY_NAME = REPOSITORY.rsplit("/", 1)[1]

# Every way a file can name a repository on this account: a page or clone address, a raw file, the
# address escaped inside a link, the HACS redirect's owner and repository pair, the demo site, `gh`.
REPOSITORY_NAMES = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"github\.com[/:]JakeTheRabbit/([\w.-]+)",
        r"githubusercontent\.com/JakeTheRabbit/([\w.-]+)",
        r"github\.com%2FJakeTheRabbit%2F([\w.-]+)",
        r"owner=JakeTheRabbit&(?:amp;)?repository=([\w.-]+)",
        r"jaketherabbit\.github\.io/([\w.-]+)",
        r"--repo JakeTheRabbit/([\w.-]+)",
    )
]
# Release history keeps the names it was written with.
HISTORY = {"CHANGELOG.md", "addons/f2_control/CHANGELOG.md"}
BINARY = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".pdf",
}
# The my.home-assistant.io redirects these files use. A name it does not serve opens its error page.
REDIRECTS = {"hacs_repository", "config_flow_start", "supervisor_add_addon_repository"}


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _text(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _shipped_text_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode("utf-8")
    return [
        ROOT / name
        for name in listed.split("\0")
        if name and name not in HISTORY and Path(name).suffix.lower() not in BINARY
    ]


def test_the_store_listing_and_the_app_link_name_this_repository():
    store = _yaml(ROOT / "repository.yaml")
    app = _yaml(ROOT / "addons" / "f2_control" / "config.yaml")
    assert store["url"] == REPOSITORY
    assert app["url"] == REPOSITORY


def test_the_store_names_the_product_without_an_edition():
    store = _yaml(ROOT / "repository.yaml")
    app = _yaml(ROOT / "addons" / "f2_control" / "config.yaml")
    assert store["name"] == "Crop Steering"
    assert app["name"] == "Crop Steering Controller"
    # The Supervisor id hangs on the slug, so it never changes.
    assert app["slug"] == "f2_control"


def test_hacs_the_readme_and_the_app_page_name_the_product_without_an_edition():
    assert json.loads(_text("hacs.json"))["name"] == "Crop Steering"
    assert _text("README.md").splitlines()[0] == "# Crop Steering"
    app = _yaml(ROOT / "addons" / "f2_control" / "config.yaml")
    assert (
        _text("addons", "f2_control", "DOCS.md").splitlines()[0] == f"# {app['name']}"
    )


def test_every_link_to_a_repository_on_this_account_names_this_one():
    elsewhere = []
    for path in _shipped_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in REPOSITORY_NAMES:
            for match in pattern.finditer(text):
                if match.group(1).removesuffix(".git").rstrip(".") != REPOSITORY_NAME:
                    elsewhere.append(
                        f"{path.relative_to(ROOT).as_posix()}: {match.group(0)}"
                    )
    assert not elsewhere, "links to another repository:\n" + "\n".join(elsewhere)


def test_the_integration_and_the_dashboard_build_their_links_from_this_repository():
    manifest = json.loads(_text("custom_components", "crop_steering", "manifest.json"))
    assert manifest["documentation"] == REPOSITORY
    assert manifest["issue_tracker"] == f"{REPOSITORY}/issues"
    const = _text("custom_components", "crop_steering", "const.py")
    assert f'REPAIRS_DOCS_URL = "{REPOSITORY}/' in const
    assert f'REPOSITORY_URL = "{REPOSITORY}"' in _text(
        "frontend", "src", "lib", "whats-new.ts"
    )


def test_every_home_assistant_redirect_is_one_it_serves():
    used: set[str] = set()
    for path in _shipped_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        used |= set(
            re.findall(r"my\.home-assistant\.io/(?:redirect|badges)/(\w+)", text)
        )
    assert used <= REDIRECTS, sorted(used - REDIRECTS)


def test_the_readme_links_and_images_resolve_inside_this_repository():
    readme = _text("README.md")
    targets = re.findall(r"\]\(([^)\s]+)\)", readme) + re.findall(
        r'<img src="([^"]+)"', readme
    )
    local = [target for target in targets if not re.match(r"[a-z]+:|#", target)]
    assert any(target.startswith("img/") for target in local)
    missing = [
        target for target in local if not (ROOT / target.split("#", 1)[0]).is_file()
    ]
    assert not missing, missing


def test_releases_with_no_page_here_have_the_changelog_section_the_dashboard_links_to():
    # 3.0.0 to 3.11.1 were released before this repository carried the 3.x line, so the dashboard's
    # What's new links each to its changelog section, `## [x.y.z] - YYYY-MM-DD`.
    sections = re.findall(
        r"^## (3\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$",
        _text("custom_components", "crop_steering", "WHATS_NEW.md"),
        re.MULTILINE,
    )
    earlier = [
        (v, d) for v, d in sections if tuple(map(int, v.split("."))) <= (3, 11, 1)
    ]
    assert len(earlier) == 16
    changelog = _text("CHANGELOG.md").splitlines()
    for version, date in earlier:
        assert f"## [{version}] - {date}" in changelog, version
