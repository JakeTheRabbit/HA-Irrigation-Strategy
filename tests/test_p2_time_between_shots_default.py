"""The controller's fallback for P2 Time Between Shots is the number's own default.

A controller updated ahead of its integration has no such number and spaces top-ups by its built-in
value instead. Both are 0 (off); if either moves alone, a controller-only update and a full update
would water the same room differently. Both are a row of the one defaults table, which the
integration and the controller each carry a copy of.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_controller_falls_back_to_the_numbers_default_of_off():
    path = ROOT / "crop-steering-engine/src/crop_steering_engine/defaults.py"
    spec = importlib.util.spec_from_file_location("defaults_table", path)
    table = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(table)
    entity_default, controller_fallback = table.DEFAULTS["p2_time_between_shots"]
    assert entity_default == controller_fallback == 0
