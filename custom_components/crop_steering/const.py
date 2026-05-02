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
# The two endpoints below feed:
#   - the legacy `master_crop_steering_app` P0 exit predicate, and
#   - the RootSense IntentResolver, which interpolates between them via the
#     cultivator-intent slider (-100 = pure generative ⇒ DROP_PCT_GEN,
#     +100 = pure vegetative ⇒ DROP_PCT_VEG).
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

# Entity prefixes
ENTITY_PREFIX = "crop_steering"

# Service names
SERVICE_START_IRRIGATION = "start_irrigation"
SERVICE_STOP_IRRIGATION = "stop_irrigation"
SERVICE_SET_PHASE = "set_phase"
SERVICE_TRIGGER_ZONE = "trigger_zone_irrigation"
SERVICE_RECALIBRATE = "recalibrate_sensors"