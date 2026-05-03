from __future__ import annotations

import sys
import types
from enum import Enum

homeassistant = types.ModuleType("homeassistant")
homeassistant.__path__ = []

config_entries = types.ModuleType("homeassistant.config_entries")
const = types.ModuleType("homeassistant.const")
core = types.ModuleType("homeassistant.core")
exceptions = types.ModuleType("homeassistant.exceptions")
helpers = types.ModuleType("homeassistant.helpers")
entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

class ConfigEntry: ...
class HomeAssistant: ...
class ConfigEntryNotReady(Exception): ...
class Platform(str, Enum):
    SENSOR = "sensor"
    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"
    BUTTON = "button"

config_entries.ConfigEntry = ConfigEntry
core.HomeAssistant = HomeAssistant
exceptions.ConfigEntryNotReady = ConfigEntryNotReady
const.Platform = Platform
helpers.entity_registry = entity_registry

sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.config_entries", config_entries)
sys.modules.setdefault("homeassistant.const", const)
sys.modules.setdefault("homeassistant.core", core)
sys.modules.setdefault("homeassistant.exceptions", exceptions)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault("homeassistant.helpers.entity_registry", entity_registry)
