"""Constants for the Crop Steering System integration."""

DOMAIN = "crop_steering"

# Every stored journal event is re-fired on the bus under this type (journal_api.py).
EVENT_JOURNAL = "crop_steering_event"

# The default room's kill switch on an installation from before the setup wizard: a helper the
# operator made by hand, and the controller app's shipped `enable_flag` option. A room made by the
# wizard stops on its own Engine Enabled switch instead. Named here once; room.room_gate decides.
LEGACY_KILL_SWITCH = "input_boolean.f2_control_enabled"

# Where a Repairs card's "Learn more" link goes: every card carries a CS code, explained there.
REPAIRS_DOCS_URL = "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/ERROR_CODES.md"

# Configuration keys
CONF_NUM_ZONES = "num_zones"
# The P0 additional dryback (%) each zone of a room starts with. A room set up from this release on
# stores it; a room set up before has none, so its zones start at 0 (off) and P0 is unchanged.
CONF_P0_ADDITIONAL_DRYBACK = "p0_additional_dryback"
NEW_ROOM_P0_ADDITIONAL_DRYBACK = 3.0

# Zone configuration
MIN_ZONES = 1
MAX_ZONES = 24  # No practical limit — env parser auto-detects zones
DEFAULT_NUM_ZONES = 1

# Calculation constants
SECONDS_PER_HOUR = 3600
PERCENTAGE_TO_RATIO = 0.01
DEFAULT_EC_RATIO = 1.0
DEFAULT_EC_FALLBACK = 3.0
VWC_ADJUSTMENT_PERCENT = 5.0

# Combining a zone's probes. The ranges are the ones the controller refuses a zone reading outside
# of, and the age is the controller's own: a probe that has not reported for longer is set aside
# while another probe in the zone is still reporting.
PROBE_RANGE = {"vwc": (0.0, 100.0), "ec": (0.0, 20.0)}
PROBE_STALE_SECONDS = 20 * 60
# How a zone's probes become its one reading, chosen per zone for moisture and EC apart. Median is
# the first option, so the default. Lowest and Highest let one probe steer the zone, so they need
# PROBE_EXTREME_MIN probes that agree; with fewer the zone steers on the Median (CS-502).
PROBE_METHODS = ["Median", "Average", "Lowest", "Highest"]
PROBE_EXTREME_MIN = 3
# A probe further from the zone's median than the larger of this many units and this share of the
# median reads something no probe beside it agrees with (pulled out of its cube, in a puddle).
PROBE_FAR = {"vwc": (15.0, 0.4), "ec": (1.0, 0.4)}
# What each EC probe measures, chosen per probe: the EC of the water in the substrate's pores, or
# the bulk EC of substrate and water together, which reads lower. unknown is the first option, so
# the default, and fuses as before; a zone never combines a bulk with a pore reading (CS-504).
EC_TYPES = ["unknown", "pore", "bulk"]

# The four moisture levels, (lowest, highest) %: each setting accepts exactly this, and grow plans,
# Auto setpoints and the engine (crop-steering-engine _PARAM_BOUNDS) use the same range, so the
# engine never clips a value its setting accepted (tests_ha/test_moisture_ranges.py). The tops are
# 100 because the order between the levels bounds the water, not a fixed number. The floors are the
# engine's long-standing ones: they catch a slipped digit (6.5 for 65).
MOISTURE_RANGES = {
    "p1_target_vwc": (20.0, 100.0),
    "p2_vwc_threshold": (10.0, 100.0),
    "field_capacity": (40.0, 100.0),
    "p3_emergency_vwc_threshold": (10.0, 65.0),
}


# Software version - single source of truth
SOFTWARE_VERSION = "3.17.0"

# Crop steering phases (P0-P3 only, Manual removed)
PHASES = ["P0", "P1", "P2", "P3"]
# A zone's Set Phase select: Keep (no request), or the phase the controller moves the zone to once
SET_PHASE_OPTIONS = ["Keep", *PHASES]
# How Water today reads, in the dashboard and the controller's vitals notification: each zone's
# total, or what each of its plants got. The controller matches "Per plant" by these words.
WATER_TODAY_VIEWS = ["Zone total", "Per plant"]
# How a room's runoff leaves it. The controller watches for a table backing up (CS-310) unless the
# room drains freely, and matches "free_drain" by this id. Unknown, the first, is every room that has
# not said, which is watched as before.
DRAINAGE_TYPES = ["unknown", "flood_table", "free_drain"]
# The runoff estimator (the controller's sump water balance): off, shadow (published only), shown_alerts (also
# CS-314 when a grow-day's balance does not close), ai (also in the AI assistant's evidence). Each includes the ones
# before it; none waters from the estimate.
RUNOFF_ESTIMATOR_MODES = ["off", "shadow", "shown_alerts", "ai"]
# The shot check (the controller's code-only shot table): off (the AI shot judge only), the table on
# the zone page, or the table plus CS-701 from code when the AI assistant is off.
SHOT_CHECK_MODES = ["off", "table", "table_and_alert"]
# A room's no-touch window: Off, or how long the AI assistant asks nothing and changes nothing there
# (an operator sampling or visiting). The controller matches these words and sets Off when it ends.
NO_TOUCH_OPTIONS = ["Off", "1 h", "Until lights-on", "24 h"]
# What the AI assistant may do in a room: one switch per power, switch.crop_steering_<prefix>ai_power_<key>.
# (key, friendly name, default). Each power that acted before the switches existed is ON, so a room
# updated in place keeps what its AI assistant did; a new power is OFF until the owner turns it on.
# With a power off its judge still runs and advises; the controller refuses to act on it. The
# controller reads the same keys and defaults (its brain package, powers.py) and takes a missing switch as its default.
AI_POWERS = (
    ("advance_phase", "AI power: start the next phase early", True),
    ("ramp_control", "AI power: end the morning ramp", True),
    ("set_probe_aside", "AI power: set a probe aside", True),
    ("ec_mode", "AI power: change the EC steer", True),
    ("nudge_setpoints", "AI power: adjust maintenance watering", True),
    ("plan_catch_up", "AI power: apply today's plan day", True),
    (
        "set_targets_from_achievable",
        "AI power: set targets from what a zone reaches",
        False,
    ),
    ("tune_shot_sizes", "AI power: tune shot sizes", False),
)
STEERING_MODES = ["Vegetative", "Generative"]
# What the room grows in, published in its descriptor for the controller. "generic" (the default,
# and what every upgraded room reads) changes nothing; the ids match the doctrine pack's substrates.
SUBSTRATES = ["generic", "rockwool", "coco"]

# Growth stages (for growth_stage select entity)
GROWTH_STAGES = ["Vegetative", "Generative", "Transition"]

# ---------------------------------------------------------------------------
# Named-stage recipes
# ---------------------------------------------------------------------------
# A recipe is a small DATA table (growth stage -> the handful of setpoints that
# actually change by stage). Selecting a stage *applies* its row into the
# existing per-zone `number.crop_steering_*` entities the engine already reads —
# no new per-stage entities (that sprawl is what produced fat-finger setpoints),
# no engine change. Stored server-side per room via the HA Store helper.
RECIPE_STORAGE_VERSION = 1
RECIPE_STAGES = ["Veg", "Transition", "Bulk", "Ripen", "Custom"]

# The curated knobs a stage drives. Each exists both globally
# (`number.crop_steering_<param>`) and per zone
# (`number.crop_steering_zone_N_<param>`); apply writes whichever exist.
RECIPE_PARAMS = [
    "p1_target_vwc",
    "p2_vwc_threshold",
    "generative_dryback_target",
    "p0_dryback_drop_percent",
    "ec_target_gen_p1",
    "ec_target_gen_p2",
    "maximum_ec",
    "p2_shot_size",
]

# Sane cannabis starting defaults: veg -> ripen drops VWC targets, deepens the
# dryback, and climbs EC + the EC ceiling (the generative push). Starting points
# the grower tunes — never claimed as optimal.
DEFAULT_RECIPE = {
    "version": RECIPE_STORAGE_VERSION,
    "active_stage": "Veg",
    "stages": {
        "Veg": {
            "p1_target_vwc": 70.0,
            "p2_vwc_threshold": 60.0,
            "generative_dryback_target": 15.0,
            "p0_dryback_drop_percent": 12.0,
            "ec_target_gen_p1": 2.0,
            "ec_target_gen_p2": 2.5,
            "maximum_ec": 7.0,
            "p2_shot_size": 5.0,
        },
        "Transition": {
            "p1_target_vwc": 66.0,
            "p2_vwc_threshold": 56.0,
            "generative_dryback_target": 22.0,
            "p0_dryback_drop_percent": 18.0,
            "ec_target_gen_p1": 2.6,
            "ec_target_gen_p2": 3.0,
            "maximum_ec": 8.0,
            "p2_shot_size": 5.0,
        },
        "Bulk": {
            "p1_target_vwc": 62.0,
            "p2_vwc_threshold": 50.0,
            "generative_dryback_target": 32.0,
            "p0_dryback_drop_percent": 24.0,
            "ec_target_gen_p1": 3.0,
            "ec_target_gen_p2": 3.5,
            "maximum_ec": 9.0,
            "p2_shot_size": 6.0,
        },
        "Ripen": {
            "p1_target_vwc": 58.0,
            "p2_vwc_threshold": 46.0,
            "generative_dryback_target": 42.0,
            "p0_dryback_drop_percent": 30.0,
            "ec_target_gen_p1": 3.4,
            "ec_target_gen_p2": 4.0,
            "maximum_ec": 10.0,
            "p2_shot_size": 6.0,
        },
        # Custom starts as a copy of Bulk; the operator edits it freely.
        "Custom": {
            "p1_target_vwc": 62.0,
            "p2_vwc_threshold": 50.0,
            "generative_dryback_target": 32.0,
            "p0_dryback_drop_percent": 24.0,
            "ec_target_gen_p1": 3.0,
            "ec_target_gen_p2": 3.5,
            "maximum_ec": 9.0,
            "p2_shot_size": 6.0,
        },
    },
}

# Service names — the single source of truth for the domain's registered services.
# These MUST match the keys of the SERVICES dict in services.py.
SERVICE_SET_MANUAL_OVERRIDE = "set_manual_override"
SERVICE_APPLY_RECIPE = "apply_recipe"
SERVICE_SAVE_RECIPE = "save_recipe"

# A zone's P2 mode (select zone_N_p2_mode): the first is the default, moisture-driven P2 as always.
# The controller maps them to the engine's p2_mode moisture / timed / timed_guarded.
P2_MODES = ["Moisture", "Timed", "Timed with guards"]
# What waters a zone (select zone_N_irrigation_mode): the first is the default, the engine as always;
# timer runs the room's timer programs (timers_api.py) and off waters nothing.
IRRIGATION_MODES = ["steering", "timer", "off"]
# Which automatic writers the room's Max setpoint move per day holds; the first is the default.
SETPOINT_STEP_SCOPES = ["Auto setpoints", "Auto setpoints and AI"]
