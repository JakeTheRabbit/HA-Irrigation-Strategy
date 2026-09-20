"""How a room is plumbed: which switches stand between the water and a zone valve.

The operator DECLARES it; nothing guesses it. 2.18.0 made the pump and main-line optional by
inference (no pump mapped = the room has no pump), which is right for a tent on one smart plug
and silently wrong for a pumped room whose pump mapping was cleared or never filled in: the
controller opened the valve, ran no pump, and counted the shot as delivered.

A room that has never declared a layout (every install from before this) publishes the same
descriptor it always did and is driven exactly as before. PURE: no Home Assistant imports.
"""

from __future__ import annotations

# layout -> (has a pump switch, has a main-line valve). The controller runs in its own container
# and cannot import this, so it carries the same table (addons/f2_control/f2_control/controller.py);
# addons/f2_control/tests/test_declared_plumbing.py pins the two together.
PLUMBING_LAYOUTS = {
    "valves_only": (False, False),
    "pump_valves": (True, False),
    "mainline_valves": (False, True),
    "pump_mainline_valves": (True, True),
}

# Plain-English names, used in messages an operator reads.
LABELS = {
    "valves_only": "zone valves only",
    "pump_valves": "a pump, then zone valves",
    "mainline_valves": "a main-line valve, then zone valves",
    "pump_mainline_valves": "a pump, a main-line valve, then zone valves",
}

_STAGES = (
    ("pump_switch", 0, "pump"),
    ("main_line_switch", 1, "main-line valve"),
)


def infer(hardware) -> str:
    """The layout a room's mapped switches already imply. Used only to PREFILL a form for a room
    that has never declared one; what the operator then saves is a declaration, not a guess.
    """
    hardware = hardware or {}
    pump, mainline = bool(hardware.get("pump_switch")), bool(
        hardware.get("main_line_switch")
    )
    return next(
        name for name, needs in PLUMBING_LAYOUTS.items() if needs == (pump, mainline)
    )


def problems(layout, hardware) -> list[str]:
    """Every way the mapped switches contradict the declared layout, in words an operator can
    act on. Empty when they agree, and empty when nothing is declared."""
    if not layout:
        return []
    if layout not in PLUMBING_LAYOUTS:
        return [
            f"Unknown plumbing layout {layout!r}; choose one of: "
            + ", ".join(PLUMBING_LAYOUTS)
        ]
    hardware = hardware or {}
    found = []
    chosen = f"The plumbing for this room is set to [{LABELS[layout]}]"
    for key, index, label in _STAGES:
        mapped, needed = hardware.get(key) or "", PLUMBING_LAYOUTS[layout][index]
        if needed and not mapped:
            found.append(
                f"{chosen}, but no {label} switch is chosen. Choose the {label} switch, "
                f"or change the plumbing if the room has no {label}"
            )
        elif mapped and not needed:
            found.append(
                f"{chosen}, but a {label} switch is mapped ({mapped}). Clear the {label} "
                f"switch, or change the plumbing to one with a {label}"
            )
    return found
