"""The error codes are one list, and everything that shows one agrees with it.

docs/error-codes.json is the list. The controller app puts a code in every notification, the
integration puts one on every Repairs card, docs/ERROR_CODES.md is written from the list, and the
dashboard's Help & tools page imports it. A code shown to an operator that the list does not
explain, or a list entry nothing can raise, fails here.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import render_error_codes  # noqa: E402

CATALOG = json.loads((ROOT / "docs" / "error-codes.json").read_text(encoding="utf-8"))
CODES = {entry["code"]: entry for entry in CATALOG["codes"]}
CONTROLLER = ROOT / "addons" / "f2_control" / "f2_control" / "controller.py"
INTEGRATION = ROOT / "custom_components" / "crop_steering"


def _controller_codes() -> set[str]:
    source = CONTROLLER.read_text(encoding="utf-8")
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_alert":
            code = node.args[1]
            if isinstance(code, ast.Constant):
                found.add(code.value)
            else:  # the moisture alert picks one of _PROBE_ALERTS by why the reading is unusable
                assert ast.unparse(code) == "code", ast.unparse(node)[:80]
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "_PROBE_ALERTS" for t in node.targets
        ):
            found |= {key.value for key in node.value.keys}
    return found


def _repairs_codes(path: Path) -> dict[str, str]:
    issues = json.loads(path.read_text(encoding="utf-8"))["issues"]
    out = {}
    for key, issue in issues.items():
        match = re.search(r"\((CS-\d{3})\)$", issue["title"])
        assert match, f"{path.name}: Repairs card {key} has no code in its title"
        assert f"Code {match.group(1)}." in issue["description"], key
        out[key] = match.group(1)
    return out


def test_the_list_is_well_formed():
    codes = [entry["code"] for entry in CATALOG["codes"]]
    assert codes == sorted(codes) and len(codes) == len(set(codes))
    prefixes = [group["prefix"] for group in CATALOG["groups"]]
    for entry in CATALOG["codes"]:
        assert re.fullmatch(r"CS-\d{3}", entry["code"])
        assert sum(entry["code"].startswith(p) for p in prefixes) == 1, entry["code"]
        assert entry["severity"] in ("critical", "warning", "info")
        assert entry["source"] in ("notification", "repairs")
        for field in ("title", "meaning", "watering"):
            assert entry[field].strip(), (entry["code"], field)
        assert entry["causes"] and entry["fixes"], entry["code"]


def test_every_notification_code_is_explained_and_every_explained_code_is_raised():
    raised = _controller_codes()
    listed = {
        code for code, entry in CODES.items() if entry["source"] == "notification"
    }
    assert raised == listed


def test_every_repairs_card_carries_its_code_in_both_languages_files():
    strings = _repairs_codes(INTEGRATION / "strings.json")
    assert _repairs_codes(INTEGRATION / "translations" / "en.json") == strings
    listed = {code for code, entry in CODES.items() if entry["source"] == "repairs"}
    assert set(strings.values()) == listed and len(strings) == len(listed)


def test_a_code_named_inside_an_entry_exists():
    for entry in CATALOG["codes"]:
        text = " ".join(
            [entry["meaning"], entry["watering"], *entry["causes"], *entry["fixes"]]
        )
        for code in re.findall(r"CS-\d{3}", text):
            assert code in CODES, (entry["code"], code)


def test_the_readable_page_is_exactly_what_the_list_writes():
    page = (ROOT / "docs" / "ERROR_CODES.md").read_text(encoding="utf-8")
    assert page == render_error_codes.render(
        CATALOG
    ), "docs/ERROR_CODES.md is stale: run python scripts/render_error_codes.py"


def test_troubleshooting_sends_people_to_the_codes():
    assert "ERROR_CODES.md" in (ROOT / "docs" / "troubleshooting.md").read_text(
        encoding="utf-8"
    )
