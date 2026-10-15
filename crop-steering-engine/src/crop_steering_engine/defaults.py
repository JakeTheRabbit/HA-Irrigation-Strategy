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
    # P0. The entity defaults are the middle of Athena's overnight dryback ranges
    # (veg 30-40 %, gen 40-50 %, % below the peak); a room set up before keeps its own.
    "vegetative_dryback_target": (35.0, 20),
    "generative_dryback_target": (45.0, 20),
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

# Substrate profiles: the numbers that depend on what a room grows in, keyed by the
# room's substrate select (generic, rockwool, coco). "generic" is exactly what every
# room ran on before the select existed, so a room nobody has set, every upgraded room
# among them, does not move.
#
# - ec_settle_min: minutes after a shot before a pore-EC reading counts as settled.
# - p1_rise_pts: P1 is full when a shot at the target lifts the day's peak by less.
# - p0_ec_flush_ratio, p0_ec_flush_shot: P0 flushes when pore EC is over this multiple
#   of the P0 EC target, with a shot this size (% of substrate).
# - ec_adjust_up, ec_adjust_down: a shot's multiplier by pore EC / its target, the
#   first row that matches: over the ratio, then under it.
# - fc_shift_min: when Auto setpoints moves field capacity by this many points or
#   more, the P2 threshold and the rescue floor move with it.
# - vwc, dryback: what a setting with no value yet starts at (a new room, or a zone
#   added later). A value a room already holds is never replaced.
# - learner: the bounds Auto setpoints and its judge steer within.
# - curve: the day planner's recipe per stage: (peak offset from the knee, overnight
#   dryback % of peak, first shot minutes after lights-on, P1 shot %, P1 gap minutes,
#   P2 shot %, pore-EC range).
# - stage_map: the recipe stages (Veg, Transition, Bulk, Ripen) to curve stages;
#   generative_stages: the curve stages steered generatively (a deeper dryback).
_GENERIC = {
    "ec_settle_min": 45.0,
    "p1_rise_pts": 0.5,
    "p0_ec_flush_ratio": 2.5,
    "p0_ec_flush_shot": 10.0,
    "ec_adjust_up": ((1.5, 2.0), (1.2, 1.5), (1.0, 1.2)),
    "ec_adjust_down": ((0.5, 0.5), (0.8, 0.7)),
    "fc_shift_min": 1.0,
    "vwc": {
        key: ENTITY_DEFAULTS[key]
        for key in (
            "field_capacity",
            "p1_target_vwc",
            "p2_vwc_threshold",
            "p3_emergency_vwc_threshold",
        )
    },
    "dryback": {
        key: ENTITY_DEFAULTS[key]
        for key in ("vegetative_dryback_target", "generative_dryback_target")
    },
    "learner": {
        "p2_shot_range": (1.0, 4.0),  # % of substrate
        "peak_adj_range": (-2.0, 2.0),  # VWC points off the learned peak
        "ec_step": (1.0, 0.5, 0.0, -0.5, -1.0),  # P2 shot change per EC answer, %
        "peak_step": 0.5,  # VWC points per peak answer
        "additional_dryback_pct": 3.0,  # % drop after lights-on before the first shot
    },
    "curve": {
        "veg": (1.0, 25.0, 60, 3.0, 20, 3.0, (3.0, 5.0)),
        "stretch": (0.0, 45.0, 90, 3.0, 20, 1.5, (4.0, 10.0)),
        "bulk": (1.0, 35.0, 60, 4.0, 20, 3.0, (3.5, 6.0)),
        "finish": (1.0, 45.0, 90, 3.0, 20, 3.0, (3.0, 4.0)),
    },
    "stage_map": {
        "Veg": "veg",
        "Transition": "stretch",
        "Bulk": "bulk",
        "Ripen": "finish",
    },
    "generative_stages": ("stretch", "finish"),
}

SUBSTRATE_PROFILES = {
    "generic": _GENERIC,
    # Stone wool: true water content works in about 55-92 % and stops rewetting from
    # the dripper under 25-30 %. Drybacks of 5-15 points (vegetative) and 20-30 points
    # (generative) from a peak near 70 are about 15 % and 35 % of it. It holds almost
    # no buffer, so pore EC runs about 3 in leafy growth and 4.5-6 in flower.
    "rockwool": {
        **_GENERIC,
        "vwc": {
            "field_capacity": 75.0,
            "p1_target_vwc": 70.0,
            "p2_vwc_threshold": 65.0,
            "p3_emergency_vwc_threshold": 40.0,
        },
        "dryback": {
            "vegetative_dryback_target": 15.0,
            "generative_dryback_target": 35.0,
        },
        "curve": {
            "veg": (1.0, 15.0, 60, 3.0, 20, 3.0, (2.5, 3.5)),
            "stretch": (0.0, 35.0, 90, 3.0, 20, 1.5, (4.5, 6.0)),
            "bulk": (1.0, 15.0, 60, 4.0, 20, 3.0, (4.5, 6.0)),
            "finish": (1.0, 35.0, 90, 3.0, 20, 3.0, (3.0, 4.0)),
        },
    },
    # Coco coir: a fifth to a third of it stays air at field capacity, so it reads
    # lower and is hard to drown. Vendor overnight drybacks are 30-40 % (vegetative)
    # and 40-50 % (generative) of the peak. Its exchange capacity buffers salt, so pore
    # EC moves more slowly after a shot.
    "coco": {
        **_GENERIC,
        "ec_settle_min": 60.0,
        "vwc": {
            "field_capacity": 65.0,
            "p1_target_vwc": 60.0,
            "p2_vwc_threshold": 55.0,
            "p3_emergency_vwc_threshold": 30.0,
        },
    },
}
