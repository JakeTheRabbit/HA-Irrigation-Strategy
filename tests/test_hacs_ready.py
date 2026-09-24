"""This repository stays eligible for the HACS default store.

HACS lists a repository only when its action passes with no ignores, the integration has brand
images (its own `brand/icon.png` is enough since hacs/integration#5128) or a home-assistant/brands
entry, the manifest carries what HACS reads, and `hacs.json` names it
(https://hacs.xyz/docs/publish/include). The action itself runs in CI; this catches a change that
would quietly make it need an ignore again.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "crop_steering"


def _hacs_steps():
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job in (document.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("hacs/action"):
                    yield workflow.name, step


def test_the_hacs_action_runs_and_ignores_nothing():
    steps = list(_hacs_steps())
    assert steps, "no workflow runs hacs/action"
    for name, step in steps:
        options = step.get("with") or {}
        assert options.get("category") == "integration", name
        assert not options.get("ignore"), f"{name} ignores {options.get('ignore')!r}"


def test_the_integration_carries_its_own_brand_images():
    brand = INTEGRATION / "brand"
    for image in ("icon.png", "logo.png"):
        data = (brand / image).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", image


def test_the_manifest_has_every_key_hacs_reads():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    for key in (
        "domain",
        "name",
        "version",
        "documentation",
        "issue_tracker",
        "codeowners",
    ):
        assert manifest.get(key), key
    assert manifest["domain"] == INTEGRATION.name


def test_hacs_json_names_the_integration():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs.get("name")
    assert (
        "country" not in hacs
    )  # not limited to any country; HACS asks for it only if it is
