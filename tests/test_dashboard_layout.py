"""Regression tests for the standalone operator dashboard layout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "www" / "f2.html"


def test_fixed_navigation_is_opaque_and_content_reserves_safe_area():
    source = DASHBOARD.read_text(encoding="utf-8")

    assert source.count('class="sticky top-0 z-30 app-navbar') == 1
    assert source.count("app-navbar border-t") == 1
    assert "background:#0d1117" in source
    assert "padding-bottom:calc(5rem + env(safe-area-inset-bottom))" in source
    assert 'class="app-content flex-1 min-w-0 flex flex-col"' in source


def test_tune_stage_sticks_below_header():
    source = DASHBOARD.read_text(encoding="utf-8")

    assert ":root{--app-header-h:64px}" in source
    assert "#tuneRoot .tune-stage{position:sticky;top:var(--app-header-h)" in source
