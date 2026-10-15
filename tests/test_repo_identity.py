"""The app store sees one repository: this one.

`repository.yaml` is what the Supervisor shows for the app repository a box added, and the app's
`config.yaml` carries the link its store page opens. Both name this repository, so a box never
sends an operator to a copy that gets no updates. Neither decides the Supervisor id (the slug and
the repository address the box added do), so this content can change without moving an install.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
