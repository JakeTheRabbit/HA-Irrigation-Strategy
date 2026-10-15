"""The error codes are one list, and everything that shows one agrees with it.

docs/error-codes.json is the list. The controller app puts a code in every notification, the
integration puts one on every Repairs card, docs/ERROR_CODES.md is written from the list, and the
dashboard's Help & tools page imports it. A code shown to an operator that the list does not
explain, or a list entry nothing can raise, fails here.

A code is defined once: once in the list, on at most one Repairs card in each language file, and
once in every shipped copy of the dashboard. A number is never handed out twice either: every
code after the ones 3.11.1 shipped is first reserved in RESERVED below, for the pull request that
will add it.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import render_error_codes  # noqa: E402

CATALOG = json.loads((ROOT / "docs" / "error-codes.json").read_text(encoding="utf-8"))
CODES = {entry["code"]: entry for entry in CATALOG["codes"]}
CONTROLLER = ROOT / "addons" / "f2_control" / "f2_control" / "controller.py"
INTEGRATION = ROOT / "custom_components" / "crop_steering"
DASHBOARDS = [
    ROOT / "www" / "dashboard.html",
    INTEGRATION / "www" / "dashboard.html",
    ROOT / "addons" / "f2_control" / "www" / "public" / "dashboard.html",
]

# The codes the list held at 3.11.1, by group: CS-101 to CS-104, CS-201 to CS-209, and so on.
SHIPPED = {
    f"CS-{group}{n:02d}"
    for group, last in {1: 4, 2: 9, 3: 11, 4: 5, 5: 1, 6: 8, 7: 7, 8: 7}.items()
    for n in range(1, last + 1)
}

# Numbers promised to a pull request that has not landed: code (or "CS-9xx" for a whole group)
# -> (its branch, what the code will say). JSON has no comments and docs/ERROR_CODES.md is written
# from the list, so the promises live here. A reserved code joins docs/error-codes.json only in
# the pull request named here, together with the commit that puts it in a notification kind
# (tests/test_notify_catalog.py). A new code nobody reserved fails until its reservation is added.
# CS-701 to CS-707 are the brain's today and are never reused.
RESERVED = {
    "CS-312": ("feat/max-run-latch", "a pump or valve on past its longest allowed run"),
    "CS-313": ("feat/actuator-domains", "an actuator the controller cannot switch"),
    "CS-502": ("feat/probe-fusion-guarded", "a zone's probes disagree"),
    "CS-503": ("fix/probe-unit-table", "a probe set aside for its unit"),
    "CS-504": ("feat/ec-type-per-probe", "bulk and pore EC mixed in one zone"),
    "CS-505": ("feat/probe-primary", "a zone's primary probe is offline"),
    "CS-609": ("feat/duplicate-controller-guard", "two controllers on one room"),
    "CS-610": ("fix/one-kill-switch-rule", "a room switch that does not stop water"),
    "CS-708": ("feat/claude-haiku-brain", "the brain"),
    "CS-709": ("feat/claude-haiku-brain", "the brain"),
    "CS-710": ("feat/brain-channel", "the brain: water finding a channel"),
    "CS-711": ("feat/brain-feed-proposal", "the brain: a feed proposal"),
    "CS-712": ("feat/claude-haiku-brain", "the brain"),
    "CS-9xx": ("feat/reservoir-minimum", "reservoir and feed"),
}


def _reservation(code: str) -> str | None:
    """The RESERVED key that holds a code: the code itself, or its group's "CS-Nxx"."""
    for key in (code, code[:4] + "xx"):
        if key in RESERVED:
            return key
    return None


def _strict_json(text: str):
    """json.loads, except that a key written twice in one object fails instead of the last winning."""

    def pairs(items):
        twice = sorted(key for key, n in Counter(k for k, _ in items).items() if n > 1)
        assert not twice, f"defined twice: {twice}"
        return dict(items)

    return json.loads(text, object_pairs_hook=pairs)


def _defined_twice(catalog: dict, *repairs: dict[str, str]) -> set[str]:
    """Codes with two entries in the list, or on two Repairs cards of one language file."""
    counts = [Counter(entry["code"] for entry in catalog["codes"])]
    counts += [Counter(cards.values()) for cards in repairs]
    return {code for count in counts for code, n in count.items() if n > 1}


def _bundled_codes(html: str) -> Counter:
    """How often each code is an entry (`code:"CS-101"`) in a built dashboard."""
    return Counter(re.findall(r"\bcode\"?:\s*[\"'`](CS-\d{3})[\"'`]", html))


def _unreserved(codes) -> set[str]:
    """Codes 3.11.1 did not ship and no reservation holds."""
    return {code for code in codes if code not in SHIPPED and not _reservation(code)}


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
    issues = _strict_json(path.read_text(encoding="utf-8"))["issues"]
    out = {}
    for key, issue in issues.items():
        match = re.search(r"\((CS-\d{3})\)$", issue["title"])
        assert match, f"{path.name}: Repairs card {key} has no code in its title"
        # a fixable card explains itself in its fix flow's confirm step
        body = issue.get("description")
        if body is None:
            body = issue["fix_flow"]["step"]["confirm"]["description"]
        assert f"Code {match.group(1)}." in body, key
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


def test_the_controller_sends_exactly_the_critical_codes_as_urgent():
    """docs/NOTIFICATIONS.md: a critical code's push is urgent, high priority on a phone that asks for it."""
    tree = ast.parse(CONTROLLER.read_text(encoding="utf-8"))
    [urgent] = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "CRITICAL_CODES" for t in node.targets)
    ]
    assert ast.unparse(urgent.func) == "frozenset"
    critical = {
        code for code, entry in CODES.items() if entry["severity"] == "critical"
    }
    assert set(ast.literal_eval(urgent.args[0])) == critical


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


def test_no_code_is_defined_twice():
    text = (ROOT / "docs" / "error-codes.json").read_text(encoding="utf-8")
    strings = _repairs_codes(INTEGRATION / "strings.json")
    english = _repairs_codes(INTEGRATION / "translations" / "en.json")
    assert _defined_twice(_strict_json(text), strings, english) == set()
    listed = Counter(CODES.keys())
    for dashboard in DASHBOARDS:
        bundled = _bundled_codes(dashboard.read_text(encoding="utf-8"))
        assert bundled == listed, f"{dashboard.relative_to(ROOT)}: rebuild it"


def test_every_code_after_3_11_1_was_reserved_first():
    assert _unreserved(CODES) == set()


def test_a_reservation_never_reuses_a_shipped_number():
    for key, (branch, what) in RESERVED.items():
        assert re.fullmatch(r"CS-(\d{3}|\dxx)", key), key
        assert re.fullmatch(r"(feat|fix)/[a-z0-9-]+", branch) and what, key
        assert key.endswith("xx") or key[:4] + "xx" not in RESERVED, key
    assert not {code for code in SHIPPED if _reservation(code)}


def test_the_guard_catches_a_second_definition_and_an_unreserved_code():
    doubled = {"codes": [{"code": "CS-101"}, {"code": "CS-102"}, {"code": "CS-101"}]}
    assert _defined_twice(doubled) == {"CS-101"}
    cards = {"a": "CS-601", "b": "CS-602", "c": "CS-601"}
    assert _defined_twice({"codes": []}, {"a": "CS-601"}, cards) == {"CS-601"}
    with pytest.raises(AssertionError, match=r"defined twice: \['a'\]"):
        _strict_json('{"issues": {"a": {}, "a": {}}}')
    assert _bundled_codes('codes:[{code:`CS-101`},{"code":"CS-101"}]') == {"CS-101": 2}
    assert _unreserved(["CS-105", "CS-314", "CS-609", "CS-901", "CS-207"]) == {
        "CS-105",
        "CS-314",
    }
