"""Tests for the Lovelace dashboard generator (#23, #24).

Confirms the generated dashboard is zone-count-driven (not locked to 3 zones), carries
no facility-specific entity ids, and no longer references the phantom
input_select.growth_phase / nutrient_phase helpers (the false "selectors disagree" alarm).
"""

from __future__ import annotations

import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import build_lovelace as B  # noqa: E402


def _ids(n, prefix=""):
    ids = []
    for z in range(1, n + 1):
        for s in (
            f"vwc_zone_{z}",
            f"ec_zone_{z}",
            f"zone_{z}_phase",
            f"zone_{z}_status",
        ):
            ids.append(f"sensor.crop_steering_{prefix}{s}")
        ids.append(f"number.crop_steering_{prefix}zone_{z}_p2_vwc_threshold")
        ids.append(f"number.crop_steering_{prefix}zone_{z}_p1_target_vwc")
        ids.append(f"switch.crop_steering_{prefix}zone_{z}_enabled")
        ids.append(f"switch.crop_steering_{prefix}zone_{z}_manual_override")
    for g in (
        "sensor_health",
        "system_safety_status",
        "app_current_phase",
        "current_decision",
        "sensor_fusion_confidence",
    ):
        ids.append(f"sensor.crop_steering_{prefix}{g}")
    for g in ("irrigation_ec_max", "field_capacity"):
        ids.append(f"number.crop_steering_{prefix}{g}")
    for g in ("system_enabled", "auto_irrigation_enabled"):
        ids.append(f"switch.crop_steering_{prefix}{g}")
    for g in ("steering_mode", "growth_stage", "irrigation_phase"):
        ids.append(f"select.crop_steering_{prefix}{g}")
    # facility junk that must never leak into a generated dashboard
    ids += [
        "sensor.f2_row_1_vwc",
        "switch.veg_main_pump",
        "sensor.atlas_legacy_1_ec",
        "input_select.growth_phase",
    ]
    return ids


def _dump(n, prefix=""):
    dash, cs, zones = B.build_dashboard(_ids(n, prefix), prefix=prefix)
    return yaml.dump(dash, allow_unicode=True, width=1000), zones


def test_six_zones_all_present():
    s, zones = _dump(6)
    assert zones == [1, 2, 3, 4, 5, 6]
    for z in (4, 5, 6):
        assert f"zone_{z}_vwc" in s and f"zone_{z}_ec" in s


def test_jinja_loop_is_not_hardcoded_to_three_zones():
    s, _ = _dump(6)
    assert "[1,2,3]" not in s
    assert "[1,2,3,4,5,6]" in s  # the live-computed verdict/exception loops all zones


def test_no_phantom_selector_helpers():
    s, _ = _dump(3)
    assert "input_select.growth_phase" not in s
    assert "nutrient_phase" not in s
    assert "selectors disagree" not in s.lower()


def test_no_facility_specific_entities():
    s, _ = _dump(3)
    for junk in (
        "f2_row",
        "veg_main_pump",
        "atlas_legacy",
        "aquaponics_kit",
        "veg_scd41",
        "substrate_",
        "espoe_irrigation",
    ):
        assert junk not in s, f"leaked facility id: {junk}"


def test_prefixed_room_targets_prefixed_entities():
    s, zones = _dump(2, prefix="veg_")
    assert zones == [1, 2]
    assert "crop_steering_veg_vwc_zone_1" in s
    # must not target the default room's un-prefixed entities
    assert "crop_steering_vwc_zone_1" not in s.replace(
        "crop_steering_veg_vwc_zone_1", ""
    )


def test_single_zone_no_ec_spread_crash():
    # 1 zone -> the EC-spread row is guarded (len > 1); dashboard still builds
    s, zones = _dump(1)
    assert zones == [1]
    assert "zone_1_vwc" in s
