"""What a user reads names the product, the Crop Steering Controller, never the app's machine slug.

The log, the `engine` value on every entity the controller and Jev publish, and the kill-switch hold
say "Crop Steering Controller". The machine ids keep theirs: the app slug `f2_control`,
`sensor.f2_control_vitals`, notification ids and the /data files (automations and the dashboard
read those, so they never move). tests_ha/test_product_name.py proves the same on old installs.
"""
import ast
from pathlib import Path

import controller
import jev_bridge

CODE = Path(controller.__file__).parent
OLD = "f2-control"


def _strings(path):
    """Every string literal in a module except docstrings (comments are not literals)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def test_no_string_the_controller_shows_says_the_old_name():
    """The controller, Jev and the dosing runner: the vendored engine is pure and publishes nothing."""
    paths = [p for p in [*CODE.glob("*.py"), *CODE.glob("jev/**/*.py")] if "crop_steering_engine" not in p.parts]
    assert any(p.name == "controller.py" for p in paths) and any(p.name == "jev_bridge.py" for p in paths)
    found = {(p.name, s) for p in paths for s in _strings(p) if OLD in s.lower()}
    assert not found, found


def test_the_entrypoint_writes_the_product_name_to_the_log():
    """run.sh echoes into the same log; its comments are not output."""
    lines = (CODE.parent / "run.sh").read_text(encoding="utf-8").splitlines()
    assert not [s for s in lines if not s.lstrip().startswith("#") and OLD in s.lower()]


def test_one_name_in_the_controller_and_in_jev():
    assert controller.PRODUCT == jev_bridge.PRODUCT == "Crop Steering Controller"


def test_the_log_names_the_product(capsys):
    controller.log("hello")
    assert capsys.readouterr().out == "[Crop Steering Controller] hello\n"
