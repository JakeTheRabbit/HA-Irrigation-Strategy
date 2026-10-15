"""One table of setting defaults, shared by the integration and the controller.

Also the one table of device units, further down: how a reading from a probe, a power
plug or a dosing pump becomes the unit the system steers in.

Pure data and one pure function, with no imports, so every layer can carry it. This file is the source,
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
    # The pump runs this long before the main line opens, and the main line this long
    # before a zone's valve. Seconds; the waits were fixed at 2 and 1 before these.
    "pump_prime_time": (2.0, 2.0),
    "main_line_lead_time": (1.0, 1.0),
    "max_daily_volume": (20.0, 150),  # litres per zone per grow-day
    # mL per plant per grow-day, 0 = off. The controller falls back to the old
    # input_number helper of the same name, then to 0.
    "min_daily_ml_per_plant": (0.0, None),
    # Substrate limits
    "field_capacity": (70.0, 70),
    "maximum_ec": (9.0, 9),
    "watchdog_hours": (3.0, 3),
    # P0
    # A new room's overnight dryback: the middle of the common ranges (vegetative 30-40%,
    # generative 40-50%, % below the peak). A room set up before keeps its own (restored),
    # the old 50/40 included.
    "vegetative_dryback_target": (35.0, 20),
    "generative_dryback_target": (45.0, 20),
    "p0_maximum_wait_time": (120.0, 45),
    # Per zone only: the integration starts a new room's zones at 3 and an updated room's at 0
    # (off), so the entity column does not apply; the controller falls back to 0, off.
    "p0_additional_dryback": (None, 0),
    "p0_dryback_drop_percent": (15.0, None),
    # P1
    "p1_target_vwc": (65.0, 60),
    "p1_initial_shot_size": (2.0, 2),
    "p1_shot_size_increment": (0.5, 0.5),
    "p1_time_between_shots": (15.0, 15),
    "p1_maximum_shots": (6.0, 12),
    "p1_minimum_shots": (3.0, 0),
    # The rise an extra P1 shot must give to keep P1 going, and how many extra shots P1 may
    # give once it has read its target (the engine's P1_RISE_PTS and P1_MAX_EXTRA_SHOTS).
    "p1_rise_pts": (0.5, 0.5),
    "p1_maximum_extra_shots": (3.0, 3),
    # P2
    "p2_vwc_threshold": (60.0, 45),
    "p2_shot_size": (5.0, 5),
    # Minutes from the last shot before a P2 top-up may go: 0 is off, as top-ups always went.
    "p2_time_between_shots": (0.0, 0.0),
    "ec_min_interval": (10.0, 10.0),
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
    # Source-water bands (0 = that band is off). A new room's pH band; a room that
    # already has these numbers keeps its own (restored), so an update never moves it.
    "irrigation_ph_min": (5.5, None),
    "irrigation_ph_max": (6.5, None),
    "irrigation_ec_min": (0.0, None),
    "irrigation_ec_max": (0.0, None),
    # Photoperiod
    "lights_on_hour": (12, None),
    "lights_off_hour": (0, None),
    # The sump pump's power above which it counts as running (W), for CS-311. The
    # controller falls back to its own SUMP_RUN_W, the same 20 W it always compared with.
    "sump_power_threshold_w": (20.0, None),
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

# Device units. Every number read from a device (a moisture or EC probe, a feed probe, a
# thermometer, a power plug) is put into its quantity's canonical unit through this table, by
# the integration and the controller alike, so the two can never read one probe differently.
#
# - canonical: the unit the system steers in.
# - convert: each recognised unit -> (offset, multiply, divide), so that
#   canonical = (reading + offset) * multiply / divide. Only exact conversions are listed.
# - refused: units that look convertible and are not, with the reason an operator needs.
# - plausible: the range of a sane reading in the canonical unit. A reading whose unit is not
#   recognised, or that has none, is taken in the canonical unit inside this range (as installs
#   older than unit checks always were read) and set aside outside it.
#
# A unit is matched with its spaces removed, first exactly and then in lower case, so "mW" is a
# milliwatt while "MW" is not recognised. A volume fraction becomes a percentage only when the
# probe says m³/m³: a reading with no unit is taken as percent, never guessed from its size.
UNITS = {
    "vwc": {
        "canonical": "%",
        "convert": {
            "%": (0.0, 1, 1),
            "m³/m³": (0.0, 100, 1),
            "m3/m3": (0.0, 100, 1),
        },
        "refused": {},
        "plausible": (0.0, 100.0),
    },
    "ec": {
        "canonical": "mS/cm",
        "convert": {
            "ms/cm": (0.0, 1, 1),
            "ds/m": (0.0, 1, 1),
            "µs/cm": (0.0, 1, 1000),  # micro sign, U+00B5
            "μs/cm": (0.0, 1, 1000),  # Greek mu, U+03BC: what many integrations emit
            "us/cm": (0.0, 1, 1000),
        },
        "refused": {
            "ppm": "ppm depends on the meter's 500 or 700 scale, which a sensor does not "
            "report; use the probe's EC reading instead",
            "ppt": "ppt depends on the meter's conversion scale; use the probe's EC reading "
            "instead",
        },
        "plausible": (0.0, 20.0),
    },
    "ph": {
        "canonical": "pH",
        "convert": {"ph": (0.0, 1, 1), "": (0.0, 1, 1)},
        "refused": {},
        "plausible": (0.0, 14.0),
    },
    "temperature": {
        "canonical": "°C",
        "convert": {
            "°c": (0.0, 1, 1),
            "°f": (-32.0, 5, 9),
            "k": (-273.15, 1, 1),
        },
        "refused": {},
        "plausible": (-10.0, 60.0),
    },
    "power": {
        "canonical": "W",
        "convert": {
            "w": (0.0, 1, 1),
            "kw": (0.0, 1000, 1),
            "mW": (0.0, 1, 1000),
        },
        "refused": {},
        "plausible": (0.0, 10000.0),
    },
    # A dosing pump's volume number and a recipe amount. The dosing runner reads a unit this table
    # does not know as mL whatever the number, as it always did (its own checks bound every dose).
    "volume": {
        "canonical": "mL",
        "convert": {"ml": (0.0, 1, 1), "l": (0.0, 1000, 1)},
        "refused": {},
        "plausible": (0.0, 100000.0),
    },
    # A dosing pump's calibrated flow; read as mL/s when its unit is not known, as it always was.
    "flow": {
        "canonical": "mL/s",
        "convert": {
            "ml/s": (0.0, 1, 1),
            "ml/min": (0.0, 1, 60),
            "l/h": (0.0, 1000, 3600),
        },
        "refused": {},
        "plausible": (0.0, 1000.0),
    },
    # A tank level sensor's distance to the water (ultrasonic or radar), turned into a level by the
    # room's full and empty distances. Setup refuses a unit this table does not know.
    "distance": {
        "canonical": "mm",
        "convert": {
            "mm": (0.0, 1, 1),
            "cm": (0.0, 10, 1),
            "m": (0.0, 1000, 1),
            "in": (0.0, 254, 10),
            "ft": (0.0, 3048, 10),
        },
        "refused": {},
        "plausible": (0.0, 10000.0),
    },
}


def to_canonical(quantity, value, unit):
    """A device reading in its quantity's canonical unit, and how its unit was taken.

    (value, "recognised"): the unit converts exactly. (None, "refused"): the unit has no exact
    conversion. (value, "unrecognised"): an unknown or missing unit, inside the plausible range,
    taken as the canonical unit. (None, "implausible"): the same, outside that range.
    """
    table = UNITS[quantity]
    key = "".join(str(unit or "").split())
    for candidate in (key, key.lower()):
        if candidate in table["convert"]:
            offset, multiply, divide = table["convert"][candidate]
            return (value + offset) * multiply / divide, "recognised"
        if candidate in table["refused"]:
            return None, "refused"
    low, high = table["plausible"]
    if low <= value <= high:
        return value, "unrecognised"
    return None, "implausible"


# Upper limits that follow a zone's size, for the two settings a fixed limit cannot
# fit: a big zone needs more than a small one. An edit above the limit is refused. A
# value a room already holds above it is kept and used, never moved, and listed in
# Repairs. Each limit is never below its floor, so every entity default fits.
#
# - max_daily_volume (litres per zone per grow-day): this many times the zone's
#   substrate, plants x litres per plant.
# - max_shot_duration (seconds, one per room): the time the slowest zone's drippers
#   take to deliver this many times its substrate (plant count cancels out).
ZONE_BOUNDS = {
    "max_daily_volume": {"substrate_multiple": 4.0, "floor": 20.0},
    "max_shot_duration": {"substrate_multiple": 1.0, "floor": 900.0},
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
