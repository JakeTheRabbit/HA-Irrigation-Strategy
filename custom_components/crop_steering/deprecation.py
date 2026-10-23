"""Entities kept only so an old install keeps working, which nothing in the system reads any more.

Each one fed a figure of the integration's own that differed from the one the controller steers
with: an EC ratio and an "adjusted re-water point" from a select the controller never reads, and
four settings that only fed them. They are not removed: an operator's automation or script may
still use one, and a removed entity breaks it. They are hidden instead (a new room creates them
hidden, setup hides an old room's), and a room whose automations or scripts still use one gets a
Repairs card (CS-614) naming each, which clears once none does.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.start import async_at_started

from .const import DEPRECATED, DOMAIN
from .health import _iid, _issue

ISSUE = "deprecated_entities"


def _users(hass: HomeAssistant, entity_id: str) -> list[str]:
    """The automations and scripts that name `entity_id`, as an entity or anywhere in their
    configuration (a template included); none while either is not loaded. Dashboards are not
    checked."""
    from homeassistant.components.automation import automations_with_entity
    from homeassistant.components.script import scripts_with_entity
    from homeassistant.helpers.entity_component import DATA_INSTANCES

    users = set(automations_with_entity(hass, entity_id))
    users.update(scripts_with_entity(hass, entity_id))
    for domain in ("automation", "script"):
        component = hass.data.get(DATA_INSTANCES, {}).get(domain)
        for entity in getattr(component, "entities", ()):
            if entity_id in str(getattr(entity, "raw_config", None) or ""):
                users.add(entity.entity_id)
    return sorted(users)


@callback
def check_in_use(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Raise, or clear, the room's card naming each deprecated entity an automation or script uses."""
    head = f"{DOMAIN}_{entry.entry_id}_"
    used = []
    for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        key = str(item.unique_id).removeprefix(head)
        if key not in DEPRECATED.get(item.domain, ()):
            continue
        users = _users(hass, item.entity_id)
        if users:
            used.append(f"- `{item.entity_id}`: used by {', '.join(users)}")
    _issue(
        hass,
        bool(used),
        _iid(ISSUE, entry.data.get("room_slug", "default")),
        ir.IssueSeverity.WARNING,
        {"count": str(len(used)), "entities": "\n".join(used)},
    )


def async_setup_deprecation(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Check once Home Assistant has started, when every automation and script is loaded."""

    @callback
    def _started(_hass: HomeAssistant) -> None:
        check_in_use(hass, entry)

    entry.async_on_unload(async_at_started(hass, _started))
