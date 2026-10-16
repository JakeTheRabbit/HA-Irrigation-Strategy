"""The room's opt-in protective settings (docs/DOSING.md, pH auto-correct and Light dimming; CS-211).

Each switch starts OFF on a new room and on an updated one, so nothing changes until a person turns it
on, and the shots-held alert's hours start at 0 (off). The controller app reads these by entity id; a
controller that finds one missing (an older integration) treats it as off and uses the default here,
which is the same as its own (addons/f2_control/f2_control/ph_correct.py and dry_dim.py; a test keeps
them equal).
"""

from __future__ import annotations

# key, name, icon
SWITCHES = (
    ("ph_auto_correct", "pH auto-correct", "mdi:ph"),
    ("dry_dim", "Dim lights on dry substrate", "mdi:lightbulb-on-50"),
)

# key, name, icon, low, high, step, unit, default
NUMBERS = (
    (
        "ph_correct_dose_s",
        "pH auto-correct dose length",
        "mdi:timer-outline",
        1,
        30,
        1,
        "s",
        5,
    ),
    (
        "ph_correct_max_tries",
        "pH auto-correct doses a try",
        "mdi:counter",
        1,
        3,
        1,
        None,
        2,
    ),
    (
        "ph_correct_mix_min",
        "pH auto-correct mix after a dose",
        "mdi:rotate-3d-variant",
        2,
        30,
        1,
        "min",
        5,
    ),
    (
        "ph_correct_daily_max",
        "pH auto-correct doses a day",
        "mdi:calendar-today",
        1,
        10,
        1,
        None,
        3,
    ),
    (
        "ph_correct_margin",
        "pH auto-correct stop inside the band",
        "mdi:ph",
        0.0,
        0.5,
        0.05,
        "pH",
        0.1,
    ),
    (
        "dry_dim_floor_vwc",
        "Dim lights below VWC",
        "mdi:water-percent-alert",
        1,
        60,
        0.5,
        "%",
        15,
    ),
    ("dry_dim_level_pct", "Dim lights to", "mdi:brightness-6", 30, 90, 5, "%", 50),
    ("dry_dim_after_min", "Dim lights after", "mdi:timer-sand", 1, 120, 1, "min", 10),
    (
        "dry_dim_max_h",
        "Dim lights for at most",
        "mdi:timer-alert-outline",
        0.5,
        12,
        0.5,
        "h",
        4,
    ),
    (
        "held_alert_hours",
        "Shots held alert",
        "mdi:alarm-light-outline",
        0,
        72,
        0.5,
        "h",
        0,
    ),
)
