"""Action types — what an actuator controller proposes.

Per-actuator modules return lists of these. The coordinator gathers,
resolves conflicts, applies safety overrides, and only then emits
hardware commands.

This keeps each actuator's logic pure (input → action proposal) and
testable without HA.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    NOOP = "noop"
    SWITCH_ON = "switch_on"
    SWITCH_OFF = "switch_off"
    HVAC_SETPOINT = "hvac_setpoint"
    HVAC_MODE = "hvac_mode"
    NUMBER_SET = "number_set"


@dataclass
class Action:
    kind: ActionKind
    entity: str
    value: Any = None
    reason: str = ""
    actuator_class: str = ""        # "hvac", "dehu", "humid", "co2", "exhaust"
    severity: str = "normal"        # "normal", "safety", "emergency"
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def noop(cls, reason: str = "") -> "Action":
        return cls(kind=ActionKind.NOOP, entity="", reason=reason)
