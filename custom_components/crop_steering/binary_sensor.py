"""Binary sensors: one per threshold alert rule of the room (spec 2.9, G6).

binary_sensor.crop_steering_rule_<id> is on while its rule fires (or fired and was acknowledged). The
rules live in the site store and site_api.RuleEvaluator runs them; the sensors come and go with the
rules on the dispatcher signal crop_steering_rules_changed. A room with no rules has none.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from . import alert_rules
from .const import DOMAIN
from .room import room_prefix
from .site_api import RULE_STATE, RULES_CHANGED


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    room_id = "room:" + room_prefix(entry)
    shown: dict[str, CropSteeringRuleSensor] = {}

    @callback
    def sync(*_):
        site = hass.data.get(DOMAIN, {}).get("_site")
        rules = {r["id"]: r for r in (site.rules(room_id) if site else [])}
        registry = er.async_get(hass)
        for rule_id in [r for r in shown if r not in rules]:
            sensor = shown.pop(rule_id)
            if registry.async_get(sensor.entity_id):
                registry.async_remove(sensor.entity_id)  # removes the entity too
            else:
                hass.async_create_task(sensor.async_remove(force_remove=True))
        added = []
        for rule_id, rule in rules.items():
            if rule_id in shown:
                shown[rule_id].update_rule(rule)
            else:
                shown[rule_id] = CropSteeringRuleSensor(entry, rule)
                added.append(shown[rule_id])
        if added:
            async_add_entities(added)

    sync()
    entry.async_on_unload(async_dispatcher_connect(hass, RULES_CHANGED, sync))


class CropSteeringRuleSensor(BinarySensorEntity):
    """On while a threshold rule fires; its state and the value it last read as attributes."""

    _attr_should_poll = False
    _attr_icon = "mdi:bell-alert-outline"

    def __init__(self, entry, rule):
        self._entry = entry
        self._rule = rule
        self._attr_unique_id = f"{DOMAIN}_rule_{rule['id']}"
        self._attr_object_id = f"{DOMAIN}_rule_{rule['id'].lower()}"
        self.entity_id = f"binary_sensor.{self._attr_object_id}"
        self._attr_name = alert_rules.summary_sentence(rule)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})

    def _evaluator(self):
        site = self.hass.data.get(DOMAIN, {}).get("_site")
        return getattr(site, "alerts", None)

    def _state(self) -> dict:
        evaluator = self._evaluator()
        return evaluator.states.get(self._rule["id"], {}) if evaluator else {}

    @property
    def is_on(self) -> bool:
        return self._state().get("state") in alert_rules.ON

    @property
    def extra_state_attributes(self) -> dict:
        state = self._state()
        fired = state.get("fired_at") if self.is_on else None
        return {
            "rule_id": self._rule["id"],
            "room_id": self._rule["room_id"],
            "source": self._rule["source"],
            "op": self._rule["op"],
            "threshold": self._rule["threshold"],
            "unit": self._rule["unit"],
            "state": state.get("state")
            or ("armed" if self._rule.get("active", True) else "draft"),
            "firing_since": fired.isoformat() if fired else None,
        }

    @callback
    def update_rule(self, rule):
        self._rule = rule
        self._attr_name = alert_rules.summary_sentence(rule)
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                RULE_STATE.format(self._rule["id"]),
                self.async_write_ha_state,
            )
        )
