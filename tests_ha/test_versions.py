"""What the dashboard's sidebar reads: the real descriptor entity says which integration is loaded."""

import json
from pathlib import Path

from test_setup_entry import _install
from test_upgrade_in_place import DESCRIPTOR, _upgrade

MANIFEST = json.loads(
    (Path(__file__).parents[1] / "custom_components/crop_steering/manifest.json").read_text()
)


async def test_a_fresh_install_publishes_the_integration_version(hass):
    await _install(hass)
    assert hass.states.get(DESCRIPTOR).attributes["integration_version"] == MANIFEST["version"]


async def test_an_upgraded_old_install_publishes_it_too_and_its_fingerprint_inputs_do_not_move(hass):
    await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    attrs = hass.states.get(DESCRIPTOR).attributes
    assert attrs["integration_version"] == MANIFEST["version"]
    assert "plumbing" not in attrs  # still undeclared: nothing the controller fingerprints changed
