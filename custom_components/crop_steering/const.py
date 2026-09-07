"""Constants for the Crop Steering System integration."""

DOMAIN = "crop_steering"

# Configuration keys
CONF_PUMP_SWITCH = "pump_switch"
CONF_MAIN_LINE_SWITCH = "main_line_switch"
CONF_ZONE_SWITCHES = "zone_switches"
CONF_VWC_SENSORS = "vwc_sensors"
CONF_EC_SENSORS = "ec_sensors"
CONF_NUM_ZONES = "num_zones"
CONF_ENV_FILE_PATH = "env_file_path"

# Zone configuration
MIN_ZONES = 1
MAX_ZONES = 24  # No practical limit — env parser auto-detects zones
DEFAULT_NUM_ZONES = 1

# Default values (Athena method)
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_SUBSTRATE_VOLUME = 10.0
DEFAULT_DRIPPER_FLOW_RATE = 2.0
DEFAULT_FIELD_CAPACITY = 70.0
DEFAULT_MAX_EC = 9.0

# ---------------------------------------------------------------------------
# P0 dryback configuration
# ---------------------------------------------------------------------------
# Controller dryback is relative to detected peak VWC:
# (peak - current VWC) / peak * 100. A 20% dryback from 60% VWC ends at
# 48% VWC (a 12 percentage-point drop). VWC targets are absolute percentages;
# dryback rates are VWC percentage points/hour and need explicit conversion.
# These constants are defaults for separate legacy numbers, not synchronized
# entity aliases or the Grow Plan endpoint settings. Existing restored values
# remain unchanged. The Grow Plan uses its explicit per-zone endpoint ranges.
DEFAULT_VEG_P0_DRYBACK_DROP_PCT = 12.0
DEFAULT_GEN_P0_DRYBACK_DROP_PCT = 22.0

# Python constant aliases retained for source compatibility. The HA number
# entities created from them are independent controls; writes do not fan out.
DEFAULT_VEG_DRYBACK_TARGET = DEFAULT_VEG_P0_DRYBACK_DROP_PCT  # legacy alias
DEFAULT_GEN_DRYBACK_TARGET = DEFAULT_GEN_P0_DRYBACK_DROP_PCT  # legacy alias
DEFAULT_P1_TARGET_VWC = 65.0
DEFAULT_P2_VWC_THRESHOLD = 60.0

# Calculation constants
SECONDS_PER_HOUR = 3600
PERCENTAGE_TO_RATIO = 0.01
DEFAULT_EC_RATIO = 1.0
DEFAULT_EC_FALLBACK = 3.0
VWC_ADJUSTMENT_PERCENT = 5.0

# Status thresholds
VWC_DRY_THRESHOLD = 40
VWC_SATURATED_THRESHOLD = 70

# Software version - single source of truth
SOFTWARE_VERSION = "2.13.0"

# Crop steering phases (P0-P3 only, Manual removed)
PHASES = ["P0", "P1", "P2", "P3"]
STEERING_MODES = ["Vegetative", "Generative"]

# Growth stages (for growth_stage select entity)
GROWTH_STAGES = ["Vegetative", "Generative", "Transition"]

# Crop types (updated with Athena)
CROP_TYPES = [
    "Cannabis_Athena",
    "Cannabis_Hybrid",
    "Cannabis_Indica",
    "Cannabis_Sativa",
    "Tomato",
    "Lettuce",
    "Basil",
    "Custom",
]

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

# Entity prefixes
ENTITY_PREFIX = "crop_steering"

# Service names — the single source of truth for the domain's registered services.
# These MUST match the keys of the SERVICES dict in services.py.
SERVICE_TRANSITION_PHASE = "transition_phase"
SERVICE_EXECUTE_IRRIGATION_SHOT = "execute_irrigation_shot"
SERVICE_CHECK_TRANSITION_CONDITIONS = "check_transition_conditions"
SERVICE_SET_MANUAL_OVERRIDE = "set_manual_override"
SERVICE_CUSTOM_SHOT = "custom_shot"
SERVICE_APPLY_RECIPE = "apply_recipe"
SERVICE_SAVE_RECIPE = "save_recipe"
