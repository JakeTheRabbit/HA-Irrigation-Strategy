"""One table of setting defaults, shared by the integration and the controller.

Pure data with no imports, so every layer can carry it. This file is the source,
crop-steering-engine/src/crop_steering_engine/defaults.py. Two byte-for-byte copies
ship: the controller's vendored engine and the integration's
custom_components/crop_steering/generated/defaults.py (Home Assistant installs the
integration on its own, so it cannot import the engine). Edit the source, then copy
it over both; tests/test_generated_copies.py fails while any copy differs. The
integration's copy is linted with black, so keep this file black-clean.

Each setting has two columns:

- entity default: what a new setting entity starts at, and what setup offers a new
  room.
- controller fallback: what the controller uses when neither the zone's nor the
  room's setting can be read (around a Home Assistant restart, or a setting an
  older integration does not have).

Some settings have different values in the two columns, and that is deliberate.
The controller fallbacks are the values installed controllers already use, so
making the columns agree would change how upgraded rooms water whenever a setting
cannot be read. That is a change of its own, announced in the changelog, never a
side effect of tidying this table.

None means the column does not apply: the integration has no such setting, or the
controller does not fall back to a fixed value for it.
"""

# setting: (entity default, controller fallback)
DEFAULTS = {
    # Sizing. Generic starting values, not any one room's: setup shows them for the
    # operator to check. The controller falls back to its substrate_l option for the
    # substrate and to the room's own setting for the dripper flow.
    "substrate_volume": (10.0, None),  # litres per plant
    "dripper_flow_rate": (1.2, None),  # litres per hour per dripper
    "drippers_per_plant": (2, 1),
    "plant_count": (4, 0),
    "max_shot_duration": (900, None),  # seconds
    "max_daily_volume": (20.0, 150),  # litres per zone per grow-day
    # Substrate limits
    "field_capacity": (70.0, 70),
    "maximum_ec": (9.0, 9),
    "watchdog_hours": (3.0, 3),
    # P0
    "vegetative_dryback_target": (50.0, 20),
    "generative_dryback_target": (40.0, 20),
    "p0_maximum_wait_time": (120.0, 45),
    "p0_dryback_drop_percent": (15.0, None),
    # P1
    "p1_target_vwc": (65.0, 60),
    "p1_initial_shot_size": (2.0, 2),
    "p1_shot_size_increment": (0.5, 0.5),
    "p1_time_between_shots": (15.0, 15),
    "p1_maximum_shots": (6.0, 12),
    "p1_minimum_shots": (3.0, 0),
    # P2
    "p2_vwc_threshold": (60.0, 45),
    "p2_shot_size": (5.0, 5),
    "p2_time_between_shots": (0.0, 0.0),
    "p2_ec_high_threshold": (1.2, None),
    "p2_ec_low_threshold": (0.8, None),
    # P3
    "p3_emergency_vwc_threshold": (40.0, 40),
    "p3_emergency_shot_size": (2.0, 2),
    "p3_time_between_shots": (10.0, 10.0),
    # EC targets (the controller's fallbacks are the same in either steering mode)
    "ec_target_veg_p0": (3.0, 4),
    "ec_target_veg_p1": (3.0, 5),
    "ec_target_veg_p2": (3.2, 6),
    "ec_target_veg_p3": (3.0, None),
    "ec_target_gen_p0": (4.0, 4),
    "ec_target_gen_p1": (5.0, 5),
    "ec_target_gen_p2": (6.0, 6),
    "ec_target_gen_p3": (4.5, None),
    # Source-water bands (0 = that band is off)
    "irrigation_ph_min": (5.8, None),
    "irrigation_ph_max": (6.2, None),
    "irrigation_ec_min": (0.0, None),
    "irrigation_ec_max": (0.0, None),
    # Photoperiod
    "lights_on_hour": (12, None),
    "lights_off_hour": (0, None),
    # Controller-only: the highest VWC the minimum-daily floor may water a zone up to
    "min_floor_drown_ceiling": (None, 90),
}

ENTITY_DEFAULTS = {
    key: pair[0] for key, pair in DEFAULTS.items() if pair[0] is not None
}
CONTROLLER_FALLBACKS = {
    key: pair[1] for key, pair in DEFAULTS.items() if pair[1] is not None
}

# What setup offers for a new room's sizing, marked as generic until changed.
SIZING_DEFAULTS = {
    key: ENTITY_DEFAULTS[key]
    for key in (
        "substrate_volume",
        "plant_count",
        "drippers_per_plant",
        "dripper_flow_rate",
    )
}
