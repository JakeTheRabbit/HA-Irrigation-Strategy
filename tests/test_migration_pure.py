"""The upgrade to 3.18 (migration.py): its pure parts. The steps themselves run in a real Home Assistant
(tests_ha/test_upgrade_migration.py)."""

import copy

# The Home Assistant stubs, before the integration imports.
from . import ha_stubs  # noqa: F401
from custom_components.crop_steering import migration, presets  # noqa: E402
from custom_components.crop_steering.const import DEFAULT_RECIPE  # noqa: E402

SECTIONS = ("targets", "phase_timing", "water_limits")


def test_every_recipe_key_lands_in_a_preset_section():
    known = {k for s in SECTIONS for k in presets.SECTIONS[s]}
    for stage, values in DEFAULT_RECIPE["stages"].items():
        assert set(values) <= known, stage


def test_only_the_stages_that_differ_from_their_default_become_presets():
    recipe = copy.deepcopy(DEFAULT_RECIPE)
    assert migration.recipe_presets(recipe, "F2", "room:f2_") == ([], [])
    recipe["stages"]["Bulk"]["maximum_ec"] = 9.5
    rows, unmapped = migration.recipe_presets(recipe, "F2", "room:f2_")
    assert unmapped == [] and [r["stage"] for r in rows] == ["Bulk"]
    (row,) = rows
    assert row["name"] == "F2 – Bulk (from 3.17 recipe)" and row["scope"] == "all"
    assert row["from"] == {"room_id": "room:f2_"}
    assert row["values"] == {
        s: v
        for s, v in presets.capture(recipe["stages"]["Bulk"], SECTIONS).items()
        if v
    }
    assert row["sections"] == list(row["values"])


def test_a_key_no_section_holds_is_listed_never_dropped_silently():
    recipe = copy.deepcopy(DEFAULT_RECIPE)
    recipe["stages"]["Veg"]["made_up_key"] = 1.0
    rows, unmapped = migration.recipe_presets(recipe, "F2", "room:f2_")
    assert unmapped == ["made_up_key"] and "made_up_key" not in str(rows[0]["values"])


def test_a_long_room_name_keeps_the_preset_name_within_60_characters():
    recipe = copy.deepcopy(DEFAULT_RECIPE)
    recipe["stages"]["Ripen"]["p2_shot_size"] = 7.0
    (row,), _ = migration.recipe_presets(recipe, "R" * 80, "room:r_")
    assert len(row["name"]) == 60 and row["name"].endswith("Ripen (from 3.17 recipe)")


def test_no_recipe_or_a_broken_one_makes_nothing():
    for recipe in (None, {}, {"stages": "x"}, {"stages": {"Bulk": "x"}}):
        assert migration.recipe_presets(recipe, "F2", "room:f2_") == ([], [])


def test_the_kept_feed_ec_is_published_only_without_a_feed_ec_probe():
    room = {"legacy_feed_ec_fallback": 3.0}
    assert migration.published_fallback(room, "") == 3.0
    assert migration.published_fallback(room, "sensor.feed_ec") is None
    assert migration.published_fallback({}, "") is None
    assert migration.published_fallback(None, "") is None
    assert migration.published_fallback({"legacy_feed_ec_fallback": True}, "") is None


def test_a_report_row_replaces_the_one_with_its_id_in_either_list():
    report = {"carried": [], "needs_you": []}
    migration.put(report, migration.row("a", "A", "needs_you", "x", "#/", "supply"))
    migration.put(report, migration.row("a", "A", "carried", "y", "#/", "supply"))
    assert report["needs_you"] == []
    assert [r["detail"] for r in report["carried"]] == ["y"]
    assert report["carried"][0]["doc"] == "docs/UPGRADING.md#supply"


def test_every_report_anchor_is_a_section_of_the_upgrade_guide():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    guide = (root / "docs" / "UPGRADING.md").read_text(encoding="utf-8")
    anchors = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
        for h in re.findall(r"^## (.+)$", guide, re.M)
    }
    source = (root / "custom_components" / "crop_steering" / "migration.py").read_text(
        encoding="utf-8"
    )
    used = set(re.findall(r'"#/[^"]*",\s*"([a-z-]+)",?\s*\)', source))
    assert used and used <= anchors, used - anchors


# The dashboard's pages (frontend/src/lib/routes.ts RENDERED_PAGES on feat/parity-system): an address
# that is not one of them opens Today.
DASHBOARD_PAGES = {
    "all-zones", "today", "zone", "today/ai", "plan/watering", "plan/targets", "plan/timers",
    "plan/schedule", "history/explorer", "history/water", "history/compare", "history/changes",
    "history/grows", "history/drivers", "equipment/probes", "equipment/dosing", "equipment/stock",
    "equipment/pump-calibration", "equipment/feed-calibration", "equipment/setup", "settings",
    "settings/alerts", "settings/notifications", "settings/system", "settings/ai",
    "settings/features", "help",
}  # fmt: skip


def test_every_report_page_is_a_dashboard_page():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "custom_components" / "crop_steering" / "migration.py").read_text(
        encoding="utf-8"
    )
    used = set(re.findall(r'"#/([^"?]*)"', source))
    assert used and used <= DASHBOARD_PAGES, used - DASHBOARD_PAGES
    routes = (root / "frontend" / "src" / "lib" / "routes.ts").read_text(
        encoding="utf-8"
    )
    # Once the frontend lane's menu is merged, read the pages from it too.
    if "RENDERED_PAGES" in routes:
        listed = routes.split("RENDERED_PAGES = [", 1)[1].split("]", 1)[0]
        assert used <= set(re.findall(r'"([^"]+)"', listed)), used


def test_a_store_that_is_not_loaded_fails_the_step_so_it_runs_again():
    """A missing or failed recipe or dosing store is an error (tried at the next start), never a step
    recorded as skipped for good with its rows silently missing from the report."""
    import asyncio
    from types import SimpleNamespace

    import pytest

    entry = SimpleNamespace(entry_id="e1", data={}, options={}, title="F2")
    site = SimpleNamespace(error=None, document={"presets": []})
    for data in (
        {"_site": site},
        {"_site": site, "_dosing": {"e1": SimpleNamespace(error="disk error")}},
    ):
        hass = SimpleNamespace(data={migration.DOMAIN: data})
        with pytest.raises(RuntimeError):
            asyncio.run(migration.step_dosing_pumps(hass, entry, {}))
    hass = SimpleNamespace(data={migration.DOMAIN: {"_site": site}})
    with pytest.raises(RuntimeError):
        asyncio.run(migration.step_recipe_presets(hass, entry, {}))


def test_a_dosing_pump_with_a_flow_sensor_is_not_sent_to_a_calibration_that_changes_nothing():
    """A pump's flow sensor wins over its calibrated mL/min (dosing doses from the sensor), so only a
    pump without one is told to calibrate."""
    import asyncio
    from types import SimpleNamespace

    pumps = [
        {"id": "a", "name": "Part A", "flow_entity": "sensor.part_a_flow"},
        {"id": "b", "name": "Part B"},
    ]
    manager = SimpleNamespace(error=None, data={"pumps": pumps})
    hass = SimpleNamespace(data={migration.DOMAIN: {"_dosing": {"e1": manager}}})
    entry = SimpleNamespace(entry_id="e1")
    rows = {
        r["id"]: r["detail"]
        for r in asyncio.run(migration.step_dosing_pumps(hass, entry, {}))
    }
    assert "calibration" not in rows["dosing.pump.a"].split("(")[0]
    assert "sensor.part_a_flow" in rows["dosing.pump.a"]
    assert "run a pump calibration" in rows["dosing.pump.b"]
