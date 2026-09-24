"""A real Home Assistant shows every Crop Steering Repairs card with its error code.

The lean check (tests/test_error_codes.py) reads the two JSON files; this is what Home Assistant
itself loads for the card: the translation it resolves for the issue the integration raised.
The controller's half, a real install's room and zone names in a notification's title, is in
test_alerts_name_the_zone.py.
"""

import json
import re
from pathlib import Path

from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.translation import async_get_translations

from custom_components.crop_steering import health
from test_setup_entry import _install

DOMAIN = "crop_steering"
CATALOG = json.loads(
    (Path(__file__).resolve().parent.parent / "docs" / "error-codes.json").read_text(
        encoding="utf-8"
    )
)
REPAIRS = {entry["code"] for entry in CATALOG["codes"] if entry["source"] == "repairs"}


async def _issue_strings(hass):
    strings = await async_get_translations(hass, "en", "issues", {DOMAIN})
    out = {}
    for key, value in strings.items():
        issue, field = key.split(".")[3:5]
        out.setdefault(issue, {})[field] = value
    return out


async def test_every_card_home_assistant_can_show_carries_its_code(hass):
    await _install(hass)
    cards = await _issue_strings(hass)
    assert set(cards) == set(health.ISSUE_IDS)
    codes = set()
    for issue, text in cards.items():
        match = re.search(r"\((CS-\d{3})\)$", text["title"])
        assert match, (issue, text["title"])
        assert f"Code {match.group(1)}." in text["description"], issue
        codes.add(match.group(1))
    assert codes == REPAIRS


async def test_the_card_a_fresh_install_raises_shows_its_code(hass):
    """No controller app yet, so no heartbeat: the one card every new install sees first."""
    entry = await _install(hass)
    health.run_health_check(hass, entry)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "engine_offline")
    assert issue is not None
    cards = await _issue_strings(hass)
    assert cards[issue.translation_key]["title"] == "Crop Steering: engine not running (CS-602)"
