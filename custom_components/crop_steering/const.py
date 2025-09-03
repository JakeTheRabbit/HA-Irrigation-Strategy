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
MAX_ZONES = 6
DEFAULT_NUM_ZONES = 1

# Default values (Athena method)
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_SUBSTRATE_VOLUME = 10.0
DEFAULT_DRIPPER_FLOW_RATE = 2.0
DEFAULT_FIELD_CAPACITY = 70.0
DEFAULT_MAX_EC = 9.0
DEFAULT_VEG_DRYBACK_TARGET = 50.0
DEFAULT_GEN_DRYBACK_TARGET = 40.0
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

# Crop steering phases
PHASES = ["P0", "P1", "P2", "P3", "Manual"]
STEERING_MODES = ["Vegetative", "Generative"]

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