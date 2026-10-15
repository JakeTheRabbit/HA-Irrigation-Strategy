"""One table of setting defaults, shared by the integration and the controller.

Also the one table of device units, further down: how a reading from a probe or a power
plug becomes the unit the system steers in.

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
    # The sump pump's power above which it counts as running (W), for CS-311. The
    # controller falls back to its own SUMP_RUN_W, the same 20 W it always compared with.
    "sump_power_threshold_w": (20.0, None),
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
