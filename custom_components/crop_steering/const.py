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
# IMPORTANT: in this codebase "dryback" is always the *drop* from peak VWC,
# expressed as percentage points. e.g. peak=70%, valley=58% ⇒ dryback = 12.
# It is NOT the VWC value the substrate dries down *to*.
#
# The two endpoints below feed the cultivator-intent slider, which interpolates
# between them (-100 = pure generative ⇒ DROP_PCT_GEN, +100 = pure vegetative
# ⇒ DROP_PCT_VEG).
#
# Defaults reflect Athena cannabis guidance (10-15% veg, 20-25% gen). They are
# *only* defaults; the values are surfaced as HA `number` entities so the
# cultivator can override per cultivar at any time without touching code:
#
#   number.crop_steering_veg_p0_dryback_drop_pct   (range 5-40)
#   number.crop_steering_gen_p0_dryback_drop_pct   (range 5-50)
#
# The legacy entities `number.crop_steering_veg_dryback_target` /
# `number.crop_steering_gen_dryback_target` are kept as aliases for backward
# compatibility (see number.py) but emit a deprecation warning in the log.
DEFAULT_VEG_P0_DRYBACK_DROP_PCT = 12.0
DEFAULT_GEN_P0_DRYBACK_DROP_PCT = 22.0

# Legacy aliases — kept so existing dashboards / env files continue to load.
# Numerically these used to mean "% drop from peak"; the previous defaults of
# 50 / 40 were too aggressive under that semantic and are corrected here.
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
SOFTWARE_VERSION = "2.3.1"

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
    "Custom"
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
            "p1_target_vwc": 70.0, "p2_vwc_threshold": 60.0,
            "generative_dryback_target": 15.0, "p0_dryback_drop_percent": 12.0,
            "ec_target_gen_p1": 2.0, "ec_target_gen_p2": 2.5,
            "maximum_ec": 7.0, "p2_shot_size": 5.0,
        },
        "Transition": {
            "p1_target_vwc": 66.0, "p2_vwc_threshold": 56.0,
            "generative_dryback_target": 22.0, "p0_dryback_drop_percent": 18.0,
            "ec_target_gen_p1": 2.6, "ec_target_gen_p2": 3.0,
            "maximum_ec": 8.0, "p2_shot_size": 5.0,
        },
        "Bulk": {
            "p1_target_vwc": 62.0, "p2_vwc_threshold": 50.0,
            "generative_dryback_target": 32.0, "p0_dryback_drop_percent": 24.0,
            "ec_target_gen_p1": 3.0, "ec_target_gen_p2": 3.5,
            "maximum_ec": 9.0, "p2_shot_size": 6.0,
        },
        "Ripen": {
            "p1_target_vwc": 58.0, "p2_vwc_threshold": 46.0,
            "generative_dryback_target": 42.0, "p0_dryback_drop_percent": 30.0,
            "ec_target_gen_p1": 3.4, "ec_target_gen_p2": 4.0,
            "maximum_ec": 10.0, "p2_shot_size": 6.0,
        },
        # Custom starts as a copy of Bulk; the operator edits it freely.
        "Custom": {
            "p1_target_vwc": 62.0, "p2_vwc_threshold": 50.0,
            "generative_dryback_target": 32.0, "p0_dryback_drop_percent": 24.0,
            "ec_target_gen_p1": 3.0, "ec_target_gen_p2": 3.5,
            "maximum_ec": 9.0, "p2_shot_size": 6.0,
        },
    },
}

# Entity prefixes
ENTITY_PREFIX = "crop_steering"

# Service names
SERVICE_START_IRRIGATION = "start_irrigation"
SERVICE_STOP_IRRIGATION = "stop_irrigation"
SERVICE_SET_PHASE = "set_phase"
SERVICE_TRIGGER_ZONE = "trigger_zone_irrigation"
SERVICE_RECALIBRATE = "recalibrate_sensors"