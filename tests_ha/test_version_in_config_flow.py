"""The config flow says which version of the integration is RUNNING.

First real install, 2026-09-21: HACS had 2.19.2 on disk, Home Assistant was still running code
from before 2.18.0 because it had not been restarted, and nothing anywhere said so. Setup was run
twice on the stale code, which let Home Assistant name every entity, and the evening went on
finding out why the controller could not see them. HACS replaces the files; Home Assistant runs
what it loaded when it started.

So the first setup screen, the add-a-room screen and the Configure menu show the running version;
and a room is not set up at all while a different version is sitting on disk waiting for a restart.
"""

import json
from pathlib import Path

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

from custom_components.crop_steering import config_flow
from custom_components.crop_steering.const import SOFTWARE_VERSION

DOMAIN = "crop_steering"
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "crop_steering"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


def _text(section, step):
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    return strings[section]["step"][step]["description"]


# ------------------------------------------------------------------ fresh install
async def test_the_first_setup_screen_shows_the_running_version(hass):
    form = await _start(hass)
    assert form["type"] is FlowResultType.FORM and form["step_id"] == "user"
    assert (
        form["description_placeholders"]["version"]
        == SOFTWARE_VERSION
        == MANIFEST["version"]
    )
    assert (
        form["description_placeholders"]["restart_notice"] == ""
    )  # nothing pending: say nothing
    assert "{version}" in _text("config", "user")  # and the screen really prints it


async def test_adding_another_room_shows_it_too(hass):
    await _install(hass)
    form = await _start(hass)
    assert form["step_id"] == "room"
    assert form["description_placeholders"]["version"] == SOFTWARE_VERSION
    assert "{version}" in _text("config", "room")


async def test_the_configure_menu_shows_it(hass):
    entry = await _install(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["type"] is FlowResultType.MENU
    assert menu["description_placeholders"]["version"] == SOFTWARE_VERSION
    assert "{version}" in _text("options", "init")


# ------------------------------------------------------------------ an update waiting for a restart
@pytest.fixture
def newer_on_disk(monkeypatch):
    """HACS has downloaded 9.9.9; Home Assistant is still running what it started with."""
    monkeypatch.setattr(config_flow, "_installed_version", lambda: "9.9.9")


async def test_a_room_is_not_set_up_on_code_that_is_waiting_for_a_restart(
    hass, newer_on_disk
):
    result = await _start(hass)
    assert (
        result["type"] is FlowResultType.ABORT
        and result["reason"] == "restart_required"
    )
    assert result["description_placeholders"] == {
        "running": SOFTWARE_VERSION,
        "installed": "9.9.9",
    }
    assert hass.config_entries.async_entries(DOMAIN) == []
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    message = strings["config"]["abort"]["restart_required"]
    assert "{running}" in message and "{installed}" in message and "estart" in message


async def test_nor_a_second_room_and_not_through_the_dashboard_either(
    hass, monkeypatch
):
    await _install(hass)
    monkeypatch.setattr(config_flow, "_installed_version", lambda: "9.9.9")
    assert (await _start(hass))["reason"] == "restart_required"
    created = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={"setup_payload": {}},
    )
    assert (
        created["type"] is FlowResultType.ABORT
        and created["reason"] == "restart_required"
    )
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_an_existing_room_can_still_be_configured_and_is_told_why_it_looks_odd(
    hass, monkeypatch
):
    """Configure is not blocked: an operator with a growing room must be able to reach it. It says
    what is going on instead."""
    entry = await _install(hass)
    monkeypatch.setattr(config_flow, "_installed_version", lambda: "9.9.9")
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["type"] is FlowResultType.MENU
    notice = menu["description_placeholders"]["restart_notice"]
    assert SOFTWARE_VERSION in notice and "9.9.9" in notice and "estart" in notice


async def test_a_manifest_that_cannot_be_read_never_stops_anybody(hass, monkeypatch):
    monkeypatch.setattr(config_flow, "_installed_version", lambda: None)
    form = await _start(hass)
    assert form["type"] is FlowResultType.FORM
    assert form["description_placeholders"]["restart_notice"] == ""


def test_the_installed_version_is_read_from_the_manifest_on_disk():
    assert config_flow._installed_version() == MANIFEST["version"]


def test_the_english_translation_says_the_same_as_the_strings():
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (ROOT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    for section, step in (("config", "user"), ("config", "room"), ("options", "init")):
        assert english[section]["step"][step] == strings[section]["step"][step]
    assert (
        english["config"]["abort"]["restart_required"]
        == strings["config"]["abort"]["restart_required"]
    )


# ------------------------------------------------------------------ upgrade in place
@pytest.mark.parametrize(
    "name",
    ["entry_2_18_one_switch_tent.json", "entry_2_17_wizard.json", "entry_env_era.json"],
)
async def test_an_upgraded_rooms_configure_menu_shows_the_version_and_still_opens_every_step(
    hass, name
):
    entry, _seed = await _upgrade(hass, name)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["description_placeholders"]["version"] == SOFTWARE_VERSION
    assert set(menu["menu_options"]) == {
        "reload_env",
        "edit_parameters",
        "edit_zones",
        "edit_features",
    }
