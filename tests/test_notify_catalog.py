"""The kinds of alert a phone can tick (docs/NOTIFICATIONS.md): every code in docs/error-codes.json is in one,
the emergencies are exactly its critical codes, and each Repairs card carries the code the catalog routes it
by. A code nobody could tick would be a push nobody gets."""

import json
import re
from pathlib import Path

from custom_components.crop_steering import notify_catalog as catalog

ROOT = Path(__file__).resolve().parent.parent
CODES = {
    entry["code"]: entry
    for entry in json.loads(
        (ROOT / "docs" / "error-codes.json").read_text(encoding="utf-8")
    )["codes"]
}
STRINGS = ROOT / "custom_components" / "crop_steering" / "strings.json"


def test_every_code_in_the_list_belongs_to_a_kind():
    covered = {code for kind in catalog.KINDS for code in kind["codes"]}
    assert set(CODES) - covered == set()
    # No watering for a while: the controller raises it.
    assert "CS-209" in _kind("watering")


def _kind(kind_id):
    return next(kind["codes"] for kind in catalog.KINDS if kind["id"] == kind_id)


def test_the_emergencies_are_exactly_the_critical_codes():
    critical = {
        code for code, entry in CODES.items() if entry["severity"] == "critical"
    }
    assert set(catalog.EMERGENCY) == critical == set(_kind("emergency"))


def test_the_table_is_the_contracts():
    assert catalog.KIND_IDS == (
        "emergency",
        "hardware",
        "sensors",
        "watering",
        "phases",
        "stock",
        "dosing",
        "jev",
        "setup",
    )
    assert catalog.EVENTS == {"phase": "phases", "jev_setpoint": "jev"}
    assert set(_kind("hardware")) == {f"CS-30{n}" for n in range(1, 10)} | {
        "CS-310",
        "CS-311",
        "CS-701",
    }
    assert set(_kind("stock")) == {"CS-608", "CS-807"}
    assert set(_kind("dosing")) == {f"CS-80{n}" for n in range(1, 7)}
    assert "CS-404" not in _kind("setup") and "CS-404" in _kind("jev")
    for kind in catalog.serial():
        assert set(kind) == {"id", "name", "detail", "codes", "events"}
        assert kind["name"] and kind["detail"] and (kind["codes"] or kind["events"])
    assert json.loads(json.dumps(catalog.serial())) == catalog.serial()


def test_a_code_in_two_kinds_is_in_both():
    assert catalog.kinds_for("CS-301") == {"emergency", "hardware"}
    assert catalog.kinds_for("CS-207") == {"emergency", "watering"}
    assert catalog.kinds_for("CS-608") == {"stock"}


def test_events_and_codes_the_catalog_does_not_know():
    assert catalog.kinds_for(event="phase") == {"phases"}
    assert catalog.kinds_for(event="jev_setpoint") == {"jev"}
    assert catalog.kinds_for(event="something new") == set()  # not an alert: nobody
    # A newer controller's code: an emergency when it says the code is critical, else setup.
    assert catalog.kinds_for("CS-299", urgent=True) == {"emergency"}
    assert catalog.kinds_for("CS-299") == {"setup"}
    assert catalog.kinds_for() == {"setup"}
    assert catalog.kinds_for(urgent=True) == {"emergency"}
    assert catalog.kinds_for("CS-608", "phase") == {"stock", "phases"}


def test_every_repairs_card_is_routed_by_the_code_in_its_title():
    issues = json.loads(STRINGS.read_text(encoding="utf-8"))["issues"]
    titled = {
        key: re.search(r"\((CS-\d{3})\)$", issue["title"]).group(1)
        for key, issue in issues.items()
    }
    assert catalog.REPAIRS == titled
    for code in catalog.REPAIRS.values():
        assert CODES[code]["source"] == "repairs"
