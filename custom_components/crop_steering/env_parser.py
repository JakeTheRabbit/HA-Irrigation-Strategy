"""Parse crop_steering.env configuration file.

Supports two sensor formats per zone:

  Legacy (front/back pair):
    ZONE_1_VWC_FRONT=sensor.vwc_zone_1_front
    ZONE_1_VWC_BACK=sensor.vwc_zone_1_back

  Flexible (comma-separated list of any length):
    ZONE_1_VWC_SENSORS=sensor.substrate_1_vwc
    ZONE_1_VWC_SENSORS=sensor.a,sensor.b,sensor.c

If both formats are present, VWC_SENSORS/EC_SENSORS take priority.
The integration averages all valid readings regardless of count.
"""

import logging
import os
import re
from typing import Any, Dict

_LOGGER = logging.getLogger(__name__)


def load_env_config(config_dir: str) -> Dict[str, Any]:
    """Load and parse crop_steering.env from the HA config directory.

    Returns a dict with keys:
        num_zones: int
        zones: {zone_num: {zone_switch, vwc_sensors, ec_sensors, ...}}
        hardware: {pump_switch, main_line_switch, ...}
        parameters: {substrate_volume, dripper_flow_rate, ...}
        features: {ec_stacking, analytics, ...}
    """
    env_path = os.path.join(config_dir, "crop_steering.env")
    if not os.path.exists(env_path):
        raise FileNotFoundError(f"crop_steering.env not found at {env_path}")

    raw = _parse_env_file(env_path)

    zones = _parse_zones(raw)
    hardware = _parse_hardware(raw)
    parameters = _parse_parameters(raw)
    features = _parse_features(raw)

    return {
        "num_zones": len(zones),
        "zones": zones,
        "hardware": hardware,
        "parameters": parameters,
        "features": features,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_env_file(path: str) -> Dict[str, str]:
    """Read KEY=VALUE pairs, skip comments and blanks."""
    config: Dict[str, str] = {}
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value:
                config[key] = value
    return config


def _split_sensors(value: str) -> list[str]:
    """Split a comma-separated sensor list, stripping whitespace."""
    return [s.strip() for s in value.split(",") if s.strip()]


def _parse_zones(raw: Dict[str, str]) -> Dict[int, Dict[str, Any]]:
    """Detect and parse all ZONE_N_* entries.

    Supports:
      ZONE_N_VWC_SENSORS=a,b,c   (preferred, any count)
      ZONE_N_VWC_FRONT=a          (legacy, converted to list)
      ZONE_N_VWC_BACK=b           (legacy, appended to list)
    Same pattern for EC.
    """
    zone_nums = set()
    pattern = re.compile(r"ZONE_(\d+)_")
    for key in raw:
        m = pattern.match(key)
        if m:
            zone_nums.add(int(m.group(1)))

    zones: Dict[int, Dict[str, Any]] = {}
    for n in sorted(zone_nums):
        switch = raw.get(f"ZONE_{n}_SWITCH", "")
        if not switch:
            _LOGGER.warning("Zone %d has no SWITCH entry, skipping", n)
            continue

        # --- VWC sensors ---
        vwc_sensors: list[str] = []
        if raw.get(f"ZONE_{n}_VWC_SENSORS"):
            vwc_sensors = _split_sensors(raw[f"ZONE_{n}_VWC_SENSORS"])
        else:
            # Legacy front/back
            if raw.get(f"ZONE_{n}_VWC_FRONT"):
                vwc_sensors.append(raw[f"ZONE_{n}_VWC_FRONT"])
            if raw.get(f"ZONE_{n}_VWC_BACK"):
                vwc_sensors.append(raw[f"ZONE_{n}_VWC_BACK"])

        # --- EC sensors ---
        ec_sensors: list[str] = []
        if raw.get(f"ZONE_{n}_EC_SENSORS"):
            ec_sensors = _split_sensors(raw[f"ZONE_{n}_EC_SENSORS"])
        else:
            if raw.get(f"ZONE_{n}_EC_FRONT"):
                ec_sensors.append(raw[f"ZONE_{n}_EC_FRONT"])
            if raw.get(f"ZONE_{n}_EC_BACK"):
                ec_sensors.append(raw[f"ZONE_{n}_EC_BACK"])

        if not vwc_sensors:
            _LOGGER.warning("Zone %d has no VWC sensors, skipping", n)
            continue
        if not ec_sensors:
            _LOGGER.warning("Zone %d has no EC sensors, skipping", n)
            continue

        zones[n] = {
            "zone_number": n,
            "zone_switch": switch,
            # New flexible format — always a list
            "vwc_sensors": vwc_sensors,
            "ec_sensors": ec_sensors,
            # Legacy keys kept for backwards compat with sensor.py
            "vwc_front": vwc_sensors[0] if vwc_sensors else "",
            "vwc_back": vwc_sensors[1] if len(vwc_sensors) > 1 else "",
            "ec_front": ec_sensors[0] if ec_sensors else "",
            "ec_back": ec_sensors[1] if len(ec_sensors) > 1 else "",
            # Per-zone tunables
            "plant_count": int(raw.get(f"ZONE_{n}_PLANT_COUNT", "4")),
            "max_daily_volume": float(raw.get(f"ZONE_{n}_MAX_DAILY_VOLUME", "20.0")),
            "shot_multiplier": float(raw.get(f"ZONE_{n}_SHOT_MULTIPLIER", "1.0")),
        }

        _LOGGER.info(
            "Zone %d: switch=%s, %d VWC sensor(s), %d EC sensor(s)",
            n, switch, len(vwc_sensors), len(ec_sensors),
        )

    return zones


def _parse_hardware(raw: Dict[str, str]) -> Dict[str, str]:
    """Extract hardware entity IDs."""
    return {
        "pump_switch": raw.get("PUMP_SWITCH", ""),
        "main_line_switch": raw.get("MAIN_LINE_SWITCH", ""),
        "waste_switch": raw.get("WASTE_SWITCH", ""),
        "light_entity": raw.get("LIGHT_ENTITY", ""),
        "lights_on_time": raw.get("LIGHTS_ON_TIME", ""),
        "lights_off_time": raw.get("LIGHTS_OFF_TIME", ""),
        "temperature_sensor": raw.get("TEMPERATURE_SENSOR", ""),
        "humidity_sensor": raw.get("HUMIDITY_SENSOR", ""),
        "vpd_sensor": raw.get("VPD_SENSOR", ""),
        "water_level_sensor": raw.get("WATER_LEVEL_SENSOR", ""),
        "notification_service": raw.get("NOTIFICATION_SERVICE", ""),
    }


def _parse_parameters(raw: Dict[str, str]) -> Dict[str, Any]:
    """Extract substrate, phase, and EC parameters."""
    def _f(key: str, default: float) -> float:
        return float(raw.get(key, str(default)))

    def _i(key: str, default: int) -> int:
        return int(raw.get(key, str(default)))

    return {
        # Substrate
        "substrate_volume": _f("SUBSTRATE_VOLUME_LITERS", 10.0),
        "dripper_flow_rate": _f("DRIPPER_FLOW_RATE_LPH", 2.0),
        "drippers_per_plant": _i("DRIPPERS_PER_PLANT", 2),
        "field_capacity": _f("SUBSTRATE_FIELD_CAPACITY", 70.0),
        "max_ec": _f("SUBSTRATE_MAX_EC", 9.0),
        # Crop
        "default_crop_type": raw.get("DEFAULT_CROP_TYPE", "Cannabis_Athena"),
        "default_steering_mode": raw.get("DEFAULT_STEERING_MODE", "Vegetative"),
        # P0
        "p0_veg_dryback": _f("P0_VEG_DRYBACK_TARGET", 50),
        "p0_gen_dryback": _f("P0_GEN_DRYBACK_TARGET", 40),
        "p0_min_wait": _i("P0_MIN_WAIT_TIME", 30),
        "p0_max_wait": _i("P0_MAX_WAIT_TIME", 120),
        # P1
        "p1_initial_shot_size": _f("P1_INITIAL_SHOT_SIZE_PERCENT", 2.0),
        "p1_shot_increment": _f("P1_SHOT_SIZE_INCREMENT", 0.5),
        "p1_max_shot_size": _f("P1_MAX_SHOT_SIZE_PERCENT", 10.0),
        "p1_time_between_shots": _i("P1_TIME_BETWEEN_SHOTS", 15),
        "p1_target_vwc": _f("P1_TARGET_VWC", 65),
        "p1_max_shots": _i("P1_MAX_SHOTS", 10),
        "p1_min_shots": _i("P1_MIN_SHOTS", 3),
        # P2
        "p2_shot_size": _f("P2_SHOT_SIZE_PERCENT", 2.0),
        "p2_vwc_threshold": _f("P2_VWC_THRESHOLD", 60),
        "p2_ec_high_threshold": _f("P2_EC_HIGH_THRESHOLD", 1.2),
        "p2_ec_low_threshold": _f("P2_EC_LOW_THRESHOLD", 0.8),
        # P3
        "p3_veg_last_irrigation": _i("P3_VEG_LAST_IRRIGATION", 120),
        "p3_gen_last_irrigation": _i("P3_GEN_LAST_IRRIGATION", 180),
        "p3_emergency_vwc": _f("P3_EMERGENCY_VWC_THRESHOLD", 40),
        "p3_emergency_shot_size": _f("P3_EMERGENCY_SHOT_SIZE_PERCENT", 2.0),
        # EC targets
        "ec_target_veg_p0": _f("EC_TARGET_VEG_P0", 3.0),
        "ec_target_veg_p1": _f("EC_TARGET_VEG_P1", 3.0),
        "ec_target_veg_p2": _f("EC_TARGET_VEG_P2", 3.2),
        "ec_target_veg_p3": _f("EC_TARGET_VEG_P3", 3.0),
        "ec_target_gen_p0": _f("EC_TARGET_GEN_P0", 4.0),
        "ec_target_gen_p1": _f("EC_TARGET_GEN_P1", 5.0),
        "ec_target_gen_p2": _f("EC_TARGET_GEN_P2", 6.0),
        "ec_target_gen_p3": _f("EC_TARGET_GEN_P3", 4.5),
    }


def _parse_features(raw: Dict[str, str]) -> Dict[str, bool]:
    """Extract feature flags."""
    def _b(key: str, default: bool = False) -> bool:
        val = raw.get(key, str(default)).lower()
        return val in ("true", "1", "yes", "on")

    return {
        "ec_stacking": _b("ENABLE_EC_STACKING"),
        "analytics": _b("ENABLE_ANALYTICS", True),
        "ml_features": _b("ENABLE_ML_FEATURES"),
        "mqtt_monitoring": _b("ENABLE_MQTT_MONITORING"),
    }
