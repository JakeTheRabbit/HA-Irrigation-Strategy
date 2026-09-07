"""Contracts for all shipped dashboard entry points and install metadata."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "www/dashboard.html"


def test_dashboard_is_accessible_self_contained_and_bundles_font_license():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert '<html lang="en"' in source
    assert 'id="root"' in source
    assert "Operator dashboard" in source
    assert not re.search(r"<script[^>]+src=", source)
    assert not re.search(r'<link[^>]+rel="stylesheet"', source)
    assert not re.search(r"url\([\"\x27]?https?://", source)
    assert "<noscript>" in source
    assert "SIL OPEN FONT LICENSE" in source


def test_all_install_paths_ship_identical_dashboard():
    for relative in (
        "addons/f2_control/www/public",
        "custom_components/crop_steering/www",
    ):
        assert (
            DASHBOARD.read_bytes() == (ROOT / relative / "dashboard.html").read_bytes()
        )


def test_compatibility_entries_preserve_context_and_route_to_native_workspace():
    for relative in (
        "www/index.html",
        "www/f2.html",
        "www/f2-classic.html",
        "addons/f2_control/web-index.html",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "dashboard.html" in source
        assert "location.search" in source
        assert "location.hash" in source
        assert "legacyViews" in source
    classic = (ROOT / "www/f2-classic.html").read_text(encoding="utf-8")
    assert '"room:f1_":"room:"' in classic
    assert '"grow-plan"' in classic


def test_repository_metadata_does_not_expose_legacy_facility_config_as_an_app():
    assert (ROOT / "repository.yaml").exists()
    assert not (ROOT / "config.yaml").exists()
    assert not list((ROOT / "archive").rglob("config.yaml"))
    assert (ROOT / "addons/f2_control/config.yaml").exists()
