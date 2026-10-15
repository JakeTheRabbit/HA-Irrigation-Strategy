"""The controller image is built only for a candidate and re-tagged only once it is promoted.

container.yml publishes nothing its plan refuses: the version is the tag, config.yaml's and
manifest.json's; the bases are build.yaml's; stable needs a promoted release with main at its tag.
"""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / ".github/scripts/container_plan.py"
spec = importlib.util.spec_from_file_location("container_plan", SCRIPT)
container_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(container_plan)

ADDON = ROOT / "addons/f2_control"
CONFIG = (ADDON / "config.yaml").read_text(encoding="utf-8")
BUILD = (ADDON / "build.yaml").read_text(encoding="utf-8")
MANIFEST = (ROOT / "custom_components/crop_steering/manifest.json").read_text(
    encoding="utf-8"
)
VERSION = json.loads(MANIFEST)["version"]
TAG, SHA = f"v{VERSION}", "c" * 40
PRE, FULL = {"prerelease": True, "draft": False}, {"prerelease": False, "draft": False}


def run(channel="candidate", release=PRE, main_sha=SHA, tag=TAG, config=CONFIG):
    return container_plan.plan(
        tag, channel, "Owner", config, MANIFEST, BUILD, release, main_sha, SHA
    )


def test_a_candidate_builds_this_version_on_build_yamls_bases():
    result = run()
    bases = yaml.safe_load(BUILD)["build_from"]
    assert result["version"] == VERSION and result["channel"] == "candidate"
    assert result["minor"] == ".".join(VERSION.split(".")[:2])
    assert result["amd64_from"] == bases["amd64"]
    assert result["aarch64_from"] == bases["aarch64"]
    assert "armv7_from" not in result  # armv7 stays an on-box app build
    assert result["image"] == "ghcr.io/owner/crop-steering-controller"


def test_stable_needs_the_promoted_release_with_main_at_its_tag():
    assert run("stable", FULL)["channel"] == "stable"
    with pytest.raises(container_plan.Refused, match="still a pre-release"):
        run("stable", PRE)
    with pytest.raises(container_plan.Refused, match="main is not at"):
        run("stable", FULL, main_sha="d" * 40)


@pytest.mark.parametrize(
    "kwargs,refusal",
    [
        ({"release": FULL}, "not a pre-release"),
        ({"release": {"prerelease": True, "draft": True}}, "draft"),
        ({"tag": "v9.9.9"}, "config.yaml version"),
        ({"tag": "latest"}, "not a vX.Y.Z"),
        ({"config": CONFIG.replace(VERSION, "0.0.1")}, "config.yaml version"),
        ({"channel": "nightly"}, "Unknown channel"),
    ],
)
def test_anything_else_is_refused(kwargs, refusal):
    with pytest.raises(container_plan.Refused, match=refusal):
        run(**kwargs)


def test_a_version_already_published_with_other_bytes_is_refused():
    workflow = (ROOT / ".github/workflows/container.yml").read_text(encoding="utf-8")
    publish = workflow.split("\n  publish:")[1].split("\n  promote:")[0]
    assert "--dry-run" in publish
    assert publish.index('"$have" != "$want"') < publish.index("imagetools create -t")
