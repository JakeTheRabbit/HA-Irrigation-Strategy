"""What the README says it needs is what the repository actually asks for and tests.

The minimum Home Assistant lives in five places: `hacs.json` (what HACS enforces), the oldest leg of
the Real Home Assistant job (what is tested), the README badge, the README's *What you need* table
and docs/INSTALL.md. docs/TESTING.md says to move them together; this fails when one is left
behind. The Python and Node versions the README names are read from where they are set.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
INSTALL = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")


def _legs() -> list[dict]:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci-validate.yml").read_text(encoding="utf-8")
    )
    for job in workflow["jobs"].values():
        include = (job.get("strategy") or {}).get("matrix", {}).get("include") or []
        if include and all("homeassistant" in leg for leg in include):
            return include
    raise AssertionError("no Real Home Assistant matrix in ci-validate.yml")


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _requirements_table() -> str:
    start = README.index("## What you need")
    return README[start : README.index("\n## ", start + 1)]


def test_the_minimum_home_assistant_is_one_number_everywhere():
    minimum = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))[
        "homeassistant"
    ]
    oldest = min((leg["homeassistant"] for leg in _legs()), key=_key)
    assert (
        oldest == minimum
    ), "the oldest tested Home Assistant is not hacs.json's minimum"
    major_minor = ".".join(minimum.split(".")[:2])
    assert f"Home%20Assistant-{major_minor}+" in README, "README badge"
    assert f"**{minimum} or newer.**" in _requirements_table(), "README: What you need"
    assert (
        f"Home Assistant {major_minor} or newer" in INSTALL
    ), "docs/INSTALL.md: Requirements"


def test_every_tested_home_assistant_is_named():
    table = _requirements_table()
    for leg in _legs():
        assert leg["homeassistant"] in table, leg["homeassistant"]


def test_the_controller_python_is_the_one_its_image_is_built_on():
    build = yaml.safe_load(
        (ROOT / "addons" / "f2_control" / "build.yaml").read_text(encoding="utf-8")
    )
    pythons = {
        re.search(r"base-python:(\d+\.\d+)-", image).group(1)
        for image in build["build_from"].values()
    }
    assert len(pythons) == 1, pythons
    assert f"brings its own Python {pythons.pop()}" in _requirements_table()


def test_the_controller_architectures_are_the_ones_it_is_built_for():
    config = yaml.safe_load(
        (ROOT / "addons" / "f2_control" / "config.yaml").read_text(encoding="utf-8")
    )
    arches = config["arch"]
    named = ", ".join(arches[:-1]) + f" or {arches[-1]}"
    assert f"({named})" in _requirements_table(), named


def test_hacs_and_node_are_the_versions_their_files_ask_for():
    table = _requirements_table()
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["hacs"]
    assert f"{hacs} or newer for the guided download" in table
    node = json.loads(
        (ROOT / "mcp-server" / "package.json").read_text(encoding="utf-8")
    )["engines"]["node"]
    assert node.startswith(">="), node
    assert f"Node.js {node[2:]} or newer" in table
