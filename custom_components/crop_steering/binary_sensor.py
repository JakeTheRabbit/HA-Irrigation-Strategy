"""Binary sensors: one per threshold alert rule of the room (spec 2.9, G6).

binary_sensor.crop_steering_rule_<id> is on while its rule fires (or fired and was acknowledged). The
rules live in the site store and site_api.RuleEvaluator runs them. A room with no rules has none.

The sensors come and go with the rules: each room keeps a RuleSensors in hass.data, and a save of the
rules (site_api.SiteStore._save_alert_rules) first awaits every room's removals, then makes every
room's additions. A rule moved to another room so leaves its old room (entity and registry entry)
before its new room adds it under the same unique_id, which therefore never collides. The signal
crop_steering_rules_changed is still sent after a save, for anything else that follows the rules.
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
from .site_api import RULE_STATE, SENSORS, rule_title


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    sensors = RuleSensors(hass, entry, async_add_entities)
    managers = hass.data.setdefault(DOMAIN, {}).setdefault(SENSORS, {})
    managers[entry.entry_id] = sensors
    sensors.add_new()

    @callback
    def forget() -> None:
        managers.pop(entry.entry_id, None)

    entry.async_on_unload(forget)


class RuleSensors:
    """The rule sensors of one room."""

    def __init__(self, hass, entry, async_add_entities):
        self.hass, self.entry, self._add = hass, entry, async_add_entities
        self.room_id = "room:" + room_prefix(entry)
        self.shown: dict[str, CropSteeringRuleSensor] = {}

    def _rules(self) -> dict:
        site = self.hass.data.get(DOMAIN, {}).get("_site")
        return {r["id"]: r for r in (site.rules(self.room_id) if site else [])}

    async def remove_gone(self):
        """Take away the sensors of rules this room no longer has: the entity, then its registry
        entry (so the unique_id is free for the room a rule moved to)."""
        rules = self._rules()
        registry = er.async_get(self.hass)
        for rule_id in [r for r in self.shown if r not in rules]:
            sensor = self.shown.pop(rule_id)
            await sensor.async_remove(force_remove=True)
            if registry.async_get(sensor.entity_id):
                registry.async_remove(sensor.entity_id)

    @callback
    def add_new(self):
        added = []
        for rule_id, rule in self._rules().items():
            if rule_id in self.shown:
                self.shown[rule_id].update_rule(rule)
            else:
                self.shown[rule_id] = CropSteeringRuleSensor(
                    self.entry, rule, rule_title(self.hass, rule)
                )
                added.append(self.shown[rule_id])
        if added:
            self._add(added)


class CropSteeringRuleSensor(BinarySensorEntity):
    """On while a threshold rule fires; its state and the value it last read as attributes."""

    _attr_should_poll = False
    _attr_icon = "mdi:bell-alert-outline"

    def __init__(self, entry, rule, name):
        self._entry = entry
        self._rule = rule
        self._attr_unique_id = f"{DOMAIN}_rule_{rule['id']}"
        self._attr_object_id = f"{DOMAIN}_rule_{rule['id'].lower()}"
        self.entity_id = f"binary_sensor.{self._attr_object_id}"
        self._attr_name = name  # short: "F2 tank level below 30%"

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
        if self.hass is not None:
            self._attr_name = rule_title(self.hass, rule)
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                RULE_STATE.format(self._rule["id"]),
                self.async_write_ha_state,
            )
        )
