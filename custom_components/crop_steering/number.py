"""Crop Steering System number entities."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, CONF_NUM_ZONES, SOFTWARE_VERSION

_LOGGER = logging.getLogger(__name__)

NUMBER_DESCRIPTIONS = [
    # ----- RootSense v3 (added during the main consolidation) -----
    # Cultivator Intent slider feeds the adaptive pillar's IntentResolver.
    NumberEntityDescription(
        key="steering_intent",
        name="Cultivator Intent",
        icon="mdi:tune-variant",
        native_min_value=-100.0,
        native_max_value=100.0,
        native_step=5.0,
        native_unit_of_measurement="bias",
        mode="slider",
    ),
    # ClimateSense day-in-grow offset (operator-set; ticks forward at midnight).
    NumberEntityDescription(
        key="climate_grow_day_offset",
        name="ClimateSense Grow Day Offset",
        icon="mdi:calendar-today",
        native_min_value=0,
        native_max_value=200,
        native_step=1,
        native_unit_of_measurement="days",
        mode="box",
    ),
    # Operator-facing P0 dryback-drop sliders (% point drop FROM peak VWC).
    NumberEntityDescription(
        key="veg_p0_dryback_drop_pct",
        name="Vegetative P0 Dryback Drop %",
        icon="mdi:water-minus",
        native_min_value=2.0,
        native_max_value=40.0,
        native_step=0.5,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="gen_p0_dryback_drop_pct",
        name="Generative P0 Dryback Drop %",
        icon="mdi:water-minus",
        native_min_value=2.0,
        native_max_value=50.0,
        native_step=0.5,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="substrate_volume",
        name="Substrate Volume",
        icon="mdi:cube-outline",
        native_min_value=1.0,
        native_max_value=200.0,
        native_step=0.1,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        mode="box",
    ),
    NumberEntityDescription(
        key="dripper_flow_rate",
        name="Dripper Flow Rate",
        icon="mdi:water-pump",
        native_min_value=0.1,
        native_max_value=50.0,
        native_step=0.1,
        native_unit_of_measurement="L/hr",
        mode="box",
    ),
    NumberEntityDescription(
        key="drippers_per_plant",
        name="Drippers Per Plant",
        icon="mdi:sprinkler",
        native_min_value=1,
        native_max_value=6,
        native_step=1,
        mode="box",
    ),
    NumberEntityDescription(
        key="field_capacity",
        name="Field Capacity",
        icon="mdi:water-percent",
        native_min_value=5.0,
        native_max_value=100.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="maximum_ec",
        name="Maximum EC",
        icon="mdi:lightning-bolt",
        native_min_value=1.0,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    # Lights-on starvation watchdog (lean engine): max dry time before the backstop
    # shot fires. 0 disables it. The AppDaemon lean engine reads this global plus a
    # per-zone override (number.crop_steering_zone_N_watchdog_hours); bounds match its
    # _PARAM_BOUNDS["watchdog_hours"] = (0, 12).
    NumberEntityDescription(
        key="watchdog_hours",
        name="Watchdog Hours",
        icon="mdi:timer-alert",
        native_min_value=0.0,
        native_max_value=12.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.HOURS,
        mode="box",
    ),
    NumberEntityDescription(
        key="vegetative_dryback_target",
        name="Vegetative Dryback Target",
        icon="mdi:water-minus",
        native_min_value=5.0,
        native_max_value=80.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="generative_dryback_target",
        name="Generative Dryback Target", 
        icon="mdi:water-minus",
        native_min_value=5.0,
        native_max_value=70.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p1_target_vwc",
        name="P1 Target VWC",
        icon="mdi:target",
        native_min_value=5.0,
        native_max_value=95.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p2_vwc_threshold",
        name="P2 VWC Threshold",
        icon="mdi:water-alert",
        native_min_value=5.0,
        native_max_value=85.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    # P0 Phase Parameters
    NumberEntityDescription(
        key="p0_minimum_wait_time",
        name="P0 Minimum Wait Time",
        icon="mdi:timer",
        native_min_value=5.0,
        native_max_value=300.0,
        native_step=5.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode="box",
    ),
    NumberEntityDescription(
        key="p0_maximum_wait_time",
        name="P0 Maximum Wait Time",
        icon="mdi:timer-alert",
        native_min_value=30.0,
        native_max_value=600.0,
        native_step=15.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode="box",
    ),
    NumberEntityDescription(
        key="p0_dryback_drop_percent",
        name="P0 Dryback Drop Percent",
        icon="mdi:water-minus",
        native_min_value=2.0,
        native_max_value=40.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    # P1 Phase Parameters
    NumberEntityDescription(
        key="p1_initial_shot_size",
        name="P1 Initial Shot Size",
        icon="mdi:water-pump",
        native_min_value=0.1,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p1_shot_size_increment",
        name="P1 Shot Size Increment",
        icon="mdi:plus",
        native_min_value=0.05,
        native_max_value=10.0,
        native_step=0.05,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p1_maximum_shot_size",
        name="P1 Maximum Shot Size",
        icon="mdi:water-pump-off",
        native_min_value=2.0,
        native_max_value=50.0,
        native_step=0.5,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p1_time_between_shots",
        name="P1 Time Between Shots",
        icon="mdi:timer-outline",
        native_min_value=1.0,
        native_max_value=60.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode="box",
    ),
    NumberEntityDescription(
        key="p1_maximum_shots",
        name="P1 Maximum Shots",
        icon="mdi:counter",
        native_min_value=1.0,
        native_max_value=30.0,
        native_step=1.0,
        mode="box",
    ),
    NumberEntityDescription(
        key="p1_minimum_shots",
        name="P1 Minimum Shots",
        icon="mdi:counter",
        native_min_value=1.0,
        native_max_value=20.0,
        native_step=1.0,
        mode="box",
    ),
    # P2 Phase Parameters
    NumberEntityDescription(
        key="p2_shot_size",
        name="P2 Shot Size",
        icon="mdi:water-pump",
        native_min_value=0.5,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p2_ec_high_threshold",
        name="P2 EC High (ratio x target)",
        icon="mdi:arrow-up-bold",
        native_min_value=0.50,
        native_max_value=3.00,
        native_step=0.05,
        mode="box",
    ),
    NumberEntityDescription(
        key="p2_ec_low_threshold",
        name="P2 EC Low (ratio x target)",
        icon="mdi:arrow-down-bold",
        native_min_value=0.20,
        native_max_value=2.00,
        native_step=0.05,
        mode="box",
    ),
    # P3 Phase Parameters
    NumberEntityDescription(
        key="p3_veg_last_irrigation",
        name="P3 Veg Last Irrigation",
        icon="mdi:timer-sand",
        native_min_value=15.0,
        native_max_value=360.0,
        native_step=15.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode="box",
    ),
    NumberEntityDescription(
        key="p3_gen_last_irrigation",
        name="P3 Gen Last Irrigation",
        icon="mdi:timer-sand",
        native_min_value=30.0,
        native_max_value=600.0,
        native_step=15.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode="box",
    ),
    NumberEntityDescription(
        key="p3_emergency_vwc_threshold",
        name="P3 Emergency VWC Threshold",
        icon="mdi:alert",
        native_min_value=20.0,
        native_max_value=65.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p3_emergency_shot_size",
        name="P3 Emergency Shot Size",
        icon="mdi:water-alert",
        native_min_value=0.1,
        native_max_value=15.0,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    # Blocked-dripper guard: abandon a zone's emergency irrigation for 2h after this many
    # emergency shots in 30 min (the row isn't responding -> likely blocked dripper). Raise it
    # to tolerate more retries; the per-zone Dripper Protection switch disables it entirely.
    NumberEntityDescription(
        key="blocked_dripper_max_shots",
        name="Blocked Dripper Max Shots (30min)",
        icon="mdi:water-alert-outline",
        native_min_value=1,
        native_max_value=20,
        native_step=1,
        mode="box",
    ),
    # EC Target Parameters - CRITICAL MISSING ENTITIES
    NumberEntityDescription(
        key="ec_target_flush",
        name="EC Target Flush",
        icon="mdi:flash",
        native_min_value=0.1,
        native_max_value=15.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_veg_p0",
        name="EC Target Veg P0",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=15.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_veg_p1",
        name="EC Target Veg P1",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=15.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_veg_p2",
        name="EC Target Veg P2",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=15.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_veg_p3",
        name="EC Target Veg P3",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=15.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_gen_p0",
        name="EC Target Gen P0",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_gen_p1",
        name="EC Target Gen P1",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_gen_p2",
        name="EC Target Gen P2",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="ec_target_gen_p3",
        name="EC Target Gen P3",
        icon="mdi:lightning-bolt",
        native_min_value=0.5,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    # Source-Water Quality Gate (global; the veg batch tank feeds every row).
    # The AppDaemon engine blocks irrigation while the live tank pH/EC sit outside
    # these limits. Set an EC limit to 0 to disable that half of the check.
    NumberEntityDescription(
        key="irrigation_ph_min",
        name="Irrigation pH Min",
        icon="mdi:ph",
        native_min_value=3.0,
        native_max_value=9.0,
        native_step=0.05,
        native_unit_of_measurement="pH",
        mode="box",
    ),
    NumberEntityDescription(
        key="irrigation_ph_max",
        name="Irrigation pH Max",
        icon="mdi:ph",
        native_min_value=3.0,
        native_max_value=9.0,
        native_step=0.05,
        native_unit_of_measurement="pH",
        mode="box",
    ),
    NumberEntityDescription(
        key="irrigation_ec_min",
        name="Irrigation EC Min",
        icon="mdi:lightning-bolt-outline",
        native_min_value=0.0,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    NumberEntityDescription(
        key="irrigation_ec_max",
        name="Irrigation EC Max",
        icon="mdi:lightning-bolt",
        native_min_value=0.0,
        native_max_value=20.0,
        native_step=0.1,
        native_unit_of_measurement="mS/cm",
        mode="box",
    ),
    # System-wide Light Schedule (NOT per-zone)
    NumberEntityDescription(
        key="lights_on_hour",
        name="Lights On Hour",
        icon="mdi:weather-sunny",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement="hour",
        mode="box",
    ),
    NumberEntityDescription(
        key="lights_off_hour",
        name="Lights Off Hour",
        icon="mdi:weather-night",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement="hour",
        mode="box",
    ),
]

# Default values (shared by global + per-zone entities).
DEFAULT_VALUES = {
    # RootSense v3 additions
    "steering_intent": 0.0,            # midpoint = balanced
    "climate_grow_day_offset": 0,
    "veg_p0_dryback_drop_pct": 12.0,   # Athena veg default
    "gen_p0_dryback_drop_pct": 22.0,   # Athena generative default
    "substrate_volume": 10.0,
    "dripper_flow_rate": 1.2,
    "drippers_per_plant": 2,
    "field_capacity": 70.0,
    "maximum_ec": 9.0,
    "watchdog_hours": 3.0,
    "vegetative_dryback_target": 50.0,
    "generative_dryback_target": 40.0,
    "p1_target_vwc": 65.0,
    "p2_vwc_threshold": 60.0,
    "p0_minimum_wait_time": 30.0,
    "p0_maximum_wait_time": 120.0,
    "p0_dryback_drop_percent": 15.0,
    "p1_initial_shot_size": 2.0,
    "p1_shot_size_increment": 0.5,
    "p1_maximum_shot_size": 10.0,
    "p1_time_between_shots": 15.0,
    "p1_maximum_shots": 6.0,
    "p1_minimum_shots": 3.0,
    "p2_shot_size": 5.0,
    "p2_ec_high_threshold": 1.2,
    "p2_ec_low_threshold": 0.8,
    "p3_veg_last_irrigation": 120.0,
    "p3_gen_last_irrigation": 180.0,
    "p3_emergency_vwc_threshold": 40.0,
    "p3_emergency_shot_size": 2.0,
    "blocked_dripper_max_shots": 4.0,
    "ec_target_flush": 0.8,
    "ec_target_veg_p0": 3.0,
    "ec_target_veg_p1": 3.0,
    "ec_target_veg_p2": 3.2,
    "ec_target_veg_p3": 3.0,
    "ec_target_gen_p0": 4.0,
    "ec_target_gen_p1": 5.0,
    "ec_target_gen_p2": 6.0,
    "ec_target_gen_p3": 4.5,
    "irrigation_ph_min": 5.8,
    "irrigation_ph_max": 6.2,
    "irrigation_ec_min": 0.0,
    "irrigation_ec_max": 0.0,
    "lights_on_hour": 12,
    "lights_off_hour": 0,
}

# Steering params that ALSO get per-zone overrides (number.crop_steering_zone_N_<...>).
# Hardware/substrate (substrate_volume, dripper_flow_rate, drippers_per_plant) and
# system (lights_*) stay GLOBAL only. field_capacity / maximum_ec / watchdog_hours are
# per-zone here because the lean engine's _zone_num reads the per-zone number.* first and
# falls back to the global — without the per-zone entity those three silently use the
# global/default and the f2 per-zone editor writes number.set_value to a missing entity.
PER_ZONE_STEERING_KEYS = [
    "vegetative_dryback_target", "generative_dryback_target",
    "p0_minimum_wait_time", "p0_maximum_wait_time", "p0_dryback_drop_percent",
    "p1_target_vwc", "p1_initial_shot_size", "p1_shot_size_increment",
    "p1_maximum_shot_size", "p1_time_between_shots", "p1_maximum_shots", "p1_minimum_shots",
    "p2_vwc_threshold", "p2_shot_size", "p2_ec_high_threshold", "p2_ec_low_threshold",
    "p3_veg_last_irrigation", "p3_gen_last_irrigation",
    "p3_emergency_vwc_threshold", "p3_emergency_shot_size",
    "ec_target_flush",
    "ec_target_veg_p0", "ec_target_veg_p1", "ec_target_veg_p2", "ec_target_veg_p3",
    "ec_target_gen_p0", "ec_target_gen_p1", "ec_target_gen_p2", "ec_target_gen_p3",
    "field_capacity", "maximum_ec", "watchdog_hours",
]

_DESC_BY_KEY = {d.key: d for d in NUMBER_DESCRIPTIONS}

# Maps entry.data["parameters"] key → number entity key (where names differ).
# Keys that share the same name on both sides are also listed so the lookup is
# complete and doesn't need a separate "same name" fallback branch.
PARAM_TO_ENTITY_KEY: dict[str, str] = {
    # Substrate
    "substrate_volume": "substrate_volume",
    "dripper_flow_rate": "dripper_flow_rate",
    "drippers_per_plant": "drippers_per_plant",
    "field_capacity": "field_capacity",
    "max_ec": "maximum_ec",
    # P0
    "p0_veg_dryback": "vegetative_dryback_target",
    "p0_gen_dryback": "generative_dryback_target",
    "p0_min_wait": "p0_minimum_wait_time",
    "p0_max_wait": "p0_maximum_wait_time",
    # P1
    "p1_initial_shot_size": "p1_initial_shot_size",
    "p1_shot_increment": "p1_shot_size_increment",
    "p1_max_shot_size": "p1_maximum_shot_size",
    "p1_time_between_shots": "p1_time_between_shots",
    "p1_target_vwc": "p1_target_vwc",
    "p1_max_shots": "p1_maximum_shots",
    "p1_min_shots": "p1_minimum_shots",
    # P2
    "p2_shot_size": "p2_shot_size",
    "p2_vwc_threshold": "p2_vwc_threshold",
    "p2_ec_high_threshold": "p2_ec_high_threshold",
    "p2_ec_low_threshold": "p2_ec_low_threshold",
    # P3
    "p3_veg_last_irrigation": "p3_veg_last_irrigation",
    "p3_gen_last_irrigation": "p3_gen_last_irrigation",
    "p3_emergency_vwc": "p3_emergency_vwc_threshold",
    "p3_emergency_shot_size": "p3_emergency_shot_size",
    # EC targets
    "ec_target_veg_p0": "ec_target_veg_p0",
    "ec_target_veg_p1": "ec_target_veg_p1",
    "ec_target_veg_p2": "ec_target_veg_p2",
    "ec_target_veg_p3": "ec_target_veg_p3",
    "ec_target_gen_p0": "ec_target_gen_p0",
    "ec_target_gen_p1": "ec_target_gen_p1",
    "ec_target_gen_p2": "ec_target_gen_p2",
    "ec_target_gen_p3": "ec_target_gen_p3",
}

# Reverse map: entity key → parsed parameter value (built at setup time).
# Used by CropSteeringNumber to seed its initial value.
def _build_entity_seed(entry_data: dict) -> dict[str, float]:
    """Return {entity_key: value} from the config entry's parsed parameters."""
    params = entry_data.get("parameters", {})
    seed: dict[str, float] = {}
    for param_key, entity_key in PARAM_TO_ENTITY_KEY.items():
        if param_key in params:
            seed[entity_key] = params[param_key]
    return seed


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crop Steering number entities."""
    numbers = []

    # Build a seed map {entity_key: parsed_value} from the config entry's
    # .env parameters.  Empty dict when no parameters were parsed (manual setup).
    entry_seed = _build_entity_seed(entry.data)

    # Add main number entities
    for description in NUMBER_DESCRIPTIONS:
        numbers.append(CropSteeringNumber(entry, description, entity_seed=entry_seed))

    # Get number of zones from config
    config_data = hass.data[DOMAIN][entry.entry_id]
    num_zones = config_data.get(CONF_NUM_ZONES, 1)

    # Add zone-specific number entities
    for zone_num in range(1, num_zones + 1):
        # Pull per-zone tunables from the parsed .env (zones dict), falling back
        # to the legacy hard-coded defaults when absent.
        zone_cfg = entry.data.get("zones", {}).get(zone_num, {})

        # Zone plant count
        numbers.append(CropSteeringNumber(
            entry,
            NumberEntityDescription(
                key=f"zone_{zone_num}_plant_count",
                name=f"Crop Steering Zone {zone_num} Plant Count",
                icon="mdi:sprout",
                native_min_value=1,
                native_max_value=50,
                native_step=1,
                mode="box",
            ),
            zone_num=zone_num,
            default_value=zone_cfg.get("plant_count", 4),
        ))

        # Zone water limits
        numbers.append(CropSteeringNumber(
            entry,
            NumberEntityDescription(
                key=f"zone_{zone_num}_max_daily_volume",
                name=f"Crop Steering Zone {zone_num} Max Daily Volume",
                icon="mdi:water-check",
                native_min_value=0,
                native_max_value=200,
                native_step=0.5,
                native_unit_of_measurement=UnitOfVolume.LITERS,
                mode="box",
            ),
            zone_num=zone_num,
            default_value=zone_cfg.get("max_daily_volume", 20.0),
        ))

        # Zone-specific shot sizes
        numbers.append(CropSteeringNumber(
            entry,
            NumberEntityDescription(
                key=f"zone_{zone_num}_shot_size_multiplier",
                name=f"Crop Steering Zone {zone_num} Shot Size Multiplier",
                icon="mdi:multiplication",
                native_min_value=0.1,
                native_max_value=5.0,
                native_step=0.1,
                native_unit_of_measurement=PERCENTAGE,
                mode="box",
            ),
            zone_num=zone_num,
            default_value=zone_cfg.get("shot_multiplier", 1.0),
        ))

        # Per-zone copy of every steering parameter (AppDaemon falls back to global).
        for _key in PER_ZONE_STEERING_KEYS:
            _g = _DESC_BY_KEY[_key]
            numbers.append(CropSteeringNumber(
                entry,
                NumberEntityDescription(
                    key=f"zone_{zone_num}_{_key}",
                    name=f"Crop Steering Zone {zone_num} {_g.name}",
                    icon=_g.icon,
                    native_min_value=_g.native_min_value,
                    native_max_value=_g.native_max_value,
                    native_step=_g.native_step,
                    native_unit_of_measurement=_g.native_unit_of_measurement,
                    mode="box",
                ),
                zone_num=zone_num,
                default_value=DEFAULT_VALUES.get(_key),
                entity_seed=entry_seed,
            ))

    async_add_entities(numbers)

class CropSteeringNumber(NumberEntity, RestoreEntity):
    """Crop Steering number entity with state restoration."""

    def __init__(
        self,
        entry: ConfigEntry,
        description: NumberEntityDescription,
        zone_num: int = None,
        default_value: float = None,
        entity_seed: dict | None = None,
    ) -> None:
        """Initialize the number entity.

        Initial value priority (highest → lowest):
          1. explicit default_value arg (caller already resolved a per-zone param)
          2. entity_seed[base_key]  — parsed from the .env via PARAM_TO_ENTITY_KEY
          3. DEFAULT_VALUES[key]    — module-level hardcoded fallback
          4. description.native_min_value
        """
        self.entity_description = description
        self._entry = entry
        self._zone_num = zone_num
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        # Set object_id to include crop_steering prefix for entity_id generation
        self._attr_object_id = f"{DOMAIN}_{description.key}"

        if default_value is not None:
            # Caller supplied an explicit value (e.g. zone tunables from .env zones dict).
            self._attr_native_value = default_value
        else:
            # For per-zone steering entities the description key is "zone_N_<base>"; strip
            # the zone prefix so the seed lookup uses the bare entity key.
            base_key = description.key
            if zone_num is not None:
                prefix = f"zone_{zone_num}_"
                if base_key.startswith(prefix):
                    base_key = base_key[len(prefix):]

            seed_value = (entity_seed or {}).get(base_key)
            if seed_value is not None:
                self._attr_native_value = seed_value
            else:
                self._attr_native_value = DEFAULT_VALUES.get(
                    description.key, description.native_min_value
                )

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                # Keep default value if restore fails
                pass

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        if self._zone_num is not None:
            # Zone-specific device
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_zone_{self._zone_num}")},
                name=f"Crop Steering Zone {self._zone_num}",
                manufacturer="Home Assistant Community",
                model="Zone Controller",
                sw_version=SOFTWARE_VERSION,
                via_device=(DOMAIN, self._entry.entry_id),
            )
        else:
            # Main device
            return DeviceInfo(
                identifiers={(DOMAIN, self._entry.entry_id)},
                name="Crop Steering",
                manufacturer="Home Assistant Community",
                model="Professional Irrigation Controller",
                sw_version=SOFTWARE_VERSION,
            )

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        self._attr_native_value = value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if number is available."""
        return True