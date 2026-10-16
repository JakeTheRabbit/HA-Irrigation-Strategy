"""Every switch, select and number a room has is on the Features page (frontend/src/lib/features.json).

The page is built from that registry. A setting entity added to the integration without an entry
there would exist in Home Assistant and nowhere in the dashboard, which is how the P3 dryback hold,
EC stacking and the AI pause shipped with no control. This fails first. It also fails for an entry
whose entity no new room has (a feature that quietly disappeared), and for an entry whose default is
not what a new room starts at.
"""

import json
import re
from pathlib import Path

from homeassistant.helpers import entity_registry as er

from custom_components.crop_steering.generated.defaults import ENTITY_DEFAULTS
from test_setup_entry import _install

REGISTRY = json.loads(
    (Path(__file__).resolve().parents[1] / "frontend/src/lib/features.json").read_text(encoding="utf-8")
)
PREFIX = "crop_steering_tent_"
DOMAINS = ("switch", "select", "number")


def _controls():
    for feature in REGISTRY["features"]:
        for control in ([feature["master"]] if feature.get("master") else []) + feature["settings"]:
            yield control


def _registered():
    """(domain, key) of each entity the registry names, zone keys as zone_N_<key>."""
    keys = set()
    for c in _controls():
        if c["scope"] in ("room", "room+zone"):
            keys.add((c["domain"], c["key"]))
        if c["scope"] in ("zone", "room+zone"):
            keys.add((c["domain"], f"zone_N_{c['key']}"))
    return keys


def _room_entities(hass):
    """(domain, key) -> entity ids of the new room's setting entities, zone numbers as N."""
    found = {}
    for entry in er.async_get(hass).entities.values():
        domain, _, object_id = entry.entity_id.partition(".")
        if domain in DOMAINS and object_id.startswith(PREFIX):
            key = re.sub(r"^zone_\d+_", "zone_N_", object_id[len(PREFIX):])
            found.setdefault((domain, key), []).append(entry.entity_id)
    return found


def _internal(domain, key):
    return any(
        i["domain"] == domain and (i["key"] == key or (i["key"].endswith("*") and key.startswith(i["key"][:-1])))
        for i in REGISTRY["internal"]
    )


async def test_every_setting_entity_of_a_new_room_has_a_registry_entry(hass):
    await _install(hass)
    found = _room_entities(hass)
    assert found, "the room created no setting entities"
    missing = sorted(
        f"{domain}.{key}"
        for domain, key in found
        if (domain, key) not in _registered() and not _internal(domain, key)
    )
    assert missing == [], f"add these to frontend/src/lib/features.json: {missing}"


async def test_every_registry_entry_is_an_entity_of_a_new_room(hass):
    await _install(hass)
    found = _room_entities(hass)
    optional = {
        ("number", f"zone_N_{c['key']}") for c in _controls() if c.get("zoneOptional")
    }
    ghosts = sorted(f"{d}.{k}" for d, k in _registered() - optional if (d, k) not in found)
    assert ghosts == [], f"registered but never created: {ghosts}"


async def test_each_default_is_what_a_new_room_starts_at(hass):
    await _install(hass)
    found = _room_entities(hass)
    wrong = []
    for c in _controls():
        default = c["default"]
        if c["domain"] == "number":
            # The one defaults table (generated/defaults.py) is the source; the wizard's answers
            # (sizing, lights) seed a new room's own values.
            if ENTITY_DEFAULTS.get(c["key"]) is not None:
                if ENTITY_DEFAULTS[c["key"]] != default:
                    wrong.append((c["key"], default, ENTITY_DEFAULTS[c["key"]]))
                continue
            # A setting outside the table (the opt-in protective settings): the new room's value.
            for entity_id in found.get(("number", c["key"]), []):
                if float(hass.states.get(entity_id).state) != float(default):
                    wrong.append((entity_id, default, hass.states.get(entity_id).state))
            continue
        key = c["key"] if c["scope"] != "zone" else f"zone_N_{c['key']}"
        for entity_id in found.get((c["domain"], key), []):
            state = hass.states.get(entity_id).state
            expected = ("on" if default else "off") if c["domain"] == "switch" else default
            if default is None or c["key"] in ("drainage", "substrate"):
                continue  # a state, not a setting (watering, holds), or the setup wizard's answer
            if state != expected:
                wrong.append((entity_id, expected, state))
    assert wrong == []
