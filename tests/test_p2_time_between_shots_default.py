"""The controller's fallback for P2 Time Between Shots is the number's own default.

A controller updated ahead of its integration has no such number and spaces top-ups by its built-in
value instead. Both are 0 (off); if either moves alone, a controller-only update and a full update
would water the same room differently.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _assigned(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    )


def test_the_controller_falls_back_to_the_numbers_default_of_off():
    default = _assigned("custom_components/crop_steering/number.py", "DEFAULT_VALUES")
    fallback = _assigned(
        "addons/f2_control/f2_control/controller.py", "P2_TIME_BETWEEN_SHOTS_MIN"
    )
    assert default["p2_time_between_shots"] == fallback == 0
