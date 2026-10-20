"""A room declares how it is plumbed. The integration stores and checks the declaration; a room
that never declared one is left exactly as it was (tests pin that too: it is the upgrade path).
"""

import asyncio

import pytest

from custom_components.crop_steering import plumbing, setup_api as api
from custom_components.crop_steering.room import build_engine_config

from .test_setup import payload, rig


def _prepared(hass, entry, **changes):
    data = payload()
    data.update(changes)
    return api.prepare_setup(hass, data, api.effective(entry), entry.entry_id)


# --------------------------------------------------------------------------- the rules
@pytest.mark.parametrize(
    "pump, mainline, layout",
    [
        ("", "", "valves_only"),
        ("switch.p", "", "pump_valves"),
        ("", "switch.m", "mainline_valves"),
        ("switch.p", "switch.m", "pump_mainline_valves"),
    ],
)
def test_the_layout_the_mapped_switches_imply(pump, mainline, layout):
    hardware = {"pump_switch": pump, "main_line_switch": mainline}
    assert plumbing.infer(hardware) == layout
    assert plumbing.problems(layout, hardware) == []  # and that layout agrees with them


def test_inference_copes_with_a_room_that_has_no_hardware_block_at_all():
    assert plumbing.infer(None) == "valves_only" and plumbing.infer({}) == "valves_only"


def test_nothing_declared_is_never_a_problem():
    assert plumbing.problems(None, {"pump_switch": "switch.p"}) == []
    assert plumbing.problems("", {}) == []


def test_a_contradiction_is_explained_in_words_that_say_what_to_do():
    (missing,) = plumbing.problems("pump_valves", {})
    assert (
        "[a pump, then zone valves]" in missing and "Choose the pump switch" in missing
    )
    (extra,) = plumbing.problems("valves_only", {"pump_switch": "switch.p"})
    assert "switch.p" in extra and "Clear the pump switch" in extra
    assert (
        len(
            plumbing.problems(
                "valves_only",
                {"pump_switch": "switch.p", "main_line_switch": "switch.m"},
            )
        )
        == 2
    )
    assert "Unknown plumbing layout" in plumbing.problems("siphon", {})[0]


# --------------------------------------------------------------------------- saving a room
def test_a_declaration_that_matches_the_switches_is_saved():
    hass, entry, _ = rig()
    assert (
        _prepared(hass, entry, plumbing="pump_mainline_valves")["plumbing"]
        == "pump_mainline_valves"
    )


def test_a_pumped_room_cannot_be_saved_without_its_pump():
    """The 2.18.0 defect, stopped at the door: this exact payload used to save, and the controller
    then opened the valve with no pump and counted the water as delivered."""
    hass, entry, _ = rig()
    with pytest.raises(ValueError, match="no pump switch is chosen"):
        _prepared(
            hass,
            entry,
            plumbing="pump_mainline_valves",
            hardware={"pump_switch": "", "main_line_switch": "switch.m"},
        )


def test_a_tent_cannot_be_saved_with_a_pump_it_says_it_does_not_have():
    hass, entry, _ = rig()
    with pytest.raises(ValueError, match=r"a pump switch is mapped \(switch\.p\)"):
        _prepared(hass, entry, plumbing="valves_only")


def test_an_unknown_layout_is_refused_whatever_the_switches():
    hass, entry, _ = rig()
    for bad in ("siphon", 3, ["pump_valves"]):
        with pytest.raises(ValueError, match="Unknown plumbing layout"):
            _prepared(hass, entry, plumbing=bad)


def test_an_archived_room_may_hold_any_mapping():
    hass, entry, _ = rig()
    saved = _prepared(hass, entry, active=False, plumbing="valves_only")
    assert (
        saved["plumbing"] == "valves_only"
        and saved["hardware"]["pump_switch"] == "switch.p"
    )


def test_once_declared_it_survives_a_client_that_does_not_send_it():
    hass, entry, _ = rig()
    entry.data["plumbing"] = "pump_mainline_valves"
    assert (
        _prepared(hass, entry)["plumbing"] == "pump_mainline_valves"
    )  # an older dashboard, the env file
    assert (
        _prepared(hass, entry, plumbing="")["plumbing"] == "pump_mainline_valves"
    )  # cannot be withdrawn
    with pytest.raises(
        ValueError, match="no pump switch is chosen"
    ):  # and it still guards later edits
        _prepared(
            hass, entry, hardware={"pump_switch": "", "main_line_switch": "switch.m"}
        )


def test_a_declaration_can_be_changed_together_with_the_switches():
    hass, entry, _ = rig()
    entry.data["plumbing"] = "pump_mainline_valves"
    saved = _prepared(
        hass,
        entry,
        plumbing="valves_only",
        hardware={"pump_switch": "", "main_line_switch": ""},
    )
    assert saved["plumbing"] == "valves_only"


def test_the_full_save_path_stores_it_and_cannot_be_shadowed_by_old_options():
    hass, entry, _ = rig()
    entry.options = {
        "plumbing": "valves_only",
        "unrelated": 1,
    }  # a stale shadow must not win
    data = payload()
    data["plumbing"] = "pump_mainline_valves"
    room = asyncio.run(api.save_setup(hass, data))
    update = hass.config_entries.updates[-1]
    assert update["data"]["plumbing"] == "pump_mainline_valves"
    assert update["options"] == {"unrelated": 1}
    assert room["plumbing"] == "pump_mainline_valves"


# --------------------------------------------------------------------------- never declared = untouched
def test_a_room_that_never_declared_is_saved_without_one():
    hass, entry, _ = rig()
    saved = _prepared(hass, entry)
    assert "plumbing" not in saved
    assert "plumbing" not in api.configuration_payload(saved)


def test_a_room_that_never_declared_publishes_the_descriptor_it_always_did():
    """A room that never declared its plumbing must not grow a `plumbing` key, or anything else
    the controller's setup fingerprint reads: that would bring every existing install back from
    an update blocked behind a disarm cycle. (`integration_version` is not one of the keys the
    fingerprint reads; addons/f2_control/tests/test_versions.py pins that side.)"""
    legacy = {
        "setup_api_version", "setup_revision", "active", "room_name", "active_zone_ids", "zone_names",
        "slug", "prefix", "num_zones", "pump", "mainline", "valves", "enable_flag", "feed_ec_sensor",
        "feed_ph_sensor", "water_level_sensor", "tank_temperature_sensor", "tank_ec_sensor",
        "tank_ph_sensor", "tank_last_fill_sensor", "tank_fill_entity",
    }  # fmt: skip
    hass, entry, _ = rig()
    data = api.effective(entry)
    args = ("veg_", "veg", 2, data["zones"], data["hardware"])
    assert set(build_engine_config(*args, data)) == legacy
    assert set(build_engine_config(*args, {**data, "plumbing": ""})) == legacy
    declared = build_engine_config(*args, {**data, "plumbing": "pump_mainline_valves"})
    assert (
        set(declared) == legacy | {"plumbing"}
        and declared["plumbing"] == "pump_mainline_valves"
    )


# --------------------------------------------------------------------------- what the dashboard is told
def test_the_setup_document_offers_the_declared_layout_and_a_prefill_for_rooms_without_one():
    hass, entry, _ = rig()
    document = api.read_setup(hass)
    assert document["capabilities"]["plumbing"] is True
    (room,) = document["rooms"]
    assert (
        room["plumbing"] == "" and room["plumbing_inferred"] == "pump_mainline_valves"
    )
    entry.data["plumbing"] = "pump_mainline_valves"
    assert api.setup_room(hass, entry)["plumbing"] == "pump_mainline_valves"
