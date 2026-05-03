"""Unit tests for ClimateSense recipe loader and phase resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.climate.timeline import (  # noqa: E402
    Recipe,
    Phase,
    Target,
    load_recipe,
)


def test_load_real_athena_recipe():
    """The shipped athena_f1_default.yaml loads cleanly."""
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "config" / "recipes" / "athena_f1_default.yaml"
    recipe = load_recipe(path)
    assert recipe.name == "athena_f1_default"
    assert len(recipe.phases) >= 5
    # Standard cannabis grow ≈ 70-100 days
    assert 50 <= recipe.total_days <= 130
    # First phase has reasonable veg targets
    p0 = recipe.phases[0]
    assert "day_temp_c" in p0.targets
    assert 23 <= p0.targets["day_temp_c"].value <= 28


def test_phase_for_day_returns_correct_phase():
    recipe = Recipe(
        name="test",
        units={},
        phases=[
            Phase(name="A", days=7, targets={}),
            Phase(name="B", days=10, targets={}),
            Phase(name="C", days=14, targets={}),
        ],
    )
    # day 0 → A, day_in_phase 0
    p, d = recipe.phase_for_day(0)
    assert p.name == "A" and d == 0
    # day 6 (end of A) → still A, day_in_phase 6
    p, d = recipe.phase_for_day(6)
    assert p.name == "A" and d == 6
    # day 7 (first day of B) → B, day_in_phase 0
    p, d = recipe.phase_for_day(7)
    assert p.name == "B" and d == 0
    # day 16 (last day of B) → still B
    p, d = recipe.phase_for_day(16)
    assert p.name == "B" and d == 9
    # day 17 → C
    p, d = recipe.phase_for_day(17)
    assert p.name == "C" and d == 0
    # day 30 → C, day_in_phase 13
    p, d = recipe.phase_for_day(30)
    assert p.name == "C" and d == 13


def test_phase_for_day_returns_none_after_recipe_end():
    recipe = Recipe(
        name="t", units={},
        phases=[Phase(name="A", days=5, targets={})],
    )
    assert recipe.phase_for_day(5) is None  # past end
    assert recipe.phase_for_day(100) is None


def test_load_recipe_validates_target_format(tmp_path):
    f = tmp_path / "recipe.yaml"
    f.write_text("""
recipe: minimal
units: {temp: c}
phases:
  - name: only
    days: 7
    photoperiod_hours: 18
    targets:
      day_temp_c: {value: 25, tolerance: 1}
      simple_short: 22
""")
    recipe = load_recipe(f)
    assert recipe.phases[0].targets["day_temp_c"].value == 25
    assert recipe.phases[0].targets["day_temp_c"].tolerance == 1
    # Short-form (just a number) gets default tolerance 0
    assert recipe.phases[0].targets["simple_short"].value == 22
    assert recipe.phases[0].targets["simple_short"].tolerance == 0


def test_load_recipe_rejects_empty_phases(tmp_path):
    f = tmp_path / "recipe.yaml"
    f.write_text("""
recipe: empty
units: {}
phases: []
""")
    with pytest.raises(ValueError):
        load_recipe(f)


def test_load_recipe_extracts_intent_when_present():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "config" / "recipes" / "athena_f1_default.yaml"
    recipe = load_recipe(path)
    # Late flower phase should have a pronounced generative bias
    late = next((p for p in recipe.phases if "Late flower" in p.name), None)
    assert late is not None
    assert late.crop_steering_intent is not None
    assert late.crop_steering_intent < -20  # generative bias
