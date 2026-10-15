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
from homeassistant.helpers.restore_state import async_get as restore_state_data

from .bounds import check_held_values, daily_volume_bound, shot_duration_bound
from .const import (
    DOMAIN,
    CONF_NUM_ZONES,
    CONF_P0_ADDITIONAL_DRYBACK,
    MOISTURE_RANGES,
    SOFTWARE_VERSION,
)
from .generated.defaults import ENTITY_DEFAULTS, SUBSTRATE_PROFILES
from .ladder import LADDER, peak_above_field_capacity, refusal
from .room import restored_state_is_ours, room_prefix, zone_device_name
from .sizing import SIZING_KEYS, configured_sizing, prefer_setup_value

_LOGGER = logging.getLogger(__name__)

NUMBER_DESCRIPTIONS = [
    NumberEntityDescription(
        key="max_shot_duration",
        name="Maximum Shot Duration",
        icon="mdi:timer-lock",
        native_min_value=5,
        native_max_value=3600,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode="box",
    ),
    # How long the pump runs before the main line opens, and the main line before a zone's valve:
    # fixed at 2 s and 1 s until these, for a pump that takes longer to reach pressure. The
    # controller caps each at its maximum here.
    NumberEntityDescription(
        key="pump_prime_time",
        name="Pump Prime Time",
        icon="mdi:pump",
        native_min_value=0,
        native_max_value=20,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode="box",
    ),
    NumberEntityDescription(
        key="main_line_lead_time",
        name="Main Line Lead Time",
        icon="mdi:pipe-valve",
        native_min_value=0,
        native_max_value=10,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode="box",
    ),
    NumberEntityDescription(
        key="substrate_volume",
        name="Substrate Volume",
        icon="mdi:cube-outline",
        # 0.1, as setup (SIZING) and the per-zone entity allow: a 4 in rockwool cube is 0.65 L,
        # which setup accepted and this entity then refused to be set to.
        native_min_value=0.1,
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
        native_max_value=20,  # as setup (SIZING) and the per-zone entity allow
        native_step=1,
        mode="box",
    ),
    NumberEntityDescription(
        key="field_capacity",
        name="Field Capacity",
        icon="mdi:water-percent",
        native_min_value=MOISTURE_RANGES["field_capacity"][0],
        native_max_value=MOISTURE_RANGES["field_capacity"][1],
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
    # shot fires. 0 disables it. The the engine lean engine reads this global plus a
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
        native_min_value=MOISTURE_RANGES["p1_target_vwc"][0],
        native_max_value=MOISTURE_RANGES["p1_target_vwc"][1],
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p2_vwc_threshold",
        name="P2 VWC Threshold",
        icon="mdi:water-alert",
        native_min_value=MOISTURE_RANGES["p2_vwc_threshold"][0],
        native_max_value=MOISTURE_RANGES["p2_vwc_threshold"][1],
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    # P0 Phase Parameters
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
    # Once P1 reads its target it gives one more shot, and another while each raises the settled
    # moisture reading by at least this much, up to the maximum extra shots. The controller falls
    # back to the same 0.5 and 3 when an older integration has no such entities.
    NumberEntityDescription(
        key="p1_rise_pts",
        name="P1 Extra Shot Rise",
        icon="mdi:trending-up",
        native_min_value=0.1,
        native_max_value=5.0,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        mode="box",
    ),
    NumberEntityDescription(
        key="p1_maximum_extra_shots",
        name="P1 Maximum Extra Shots",
        icon="mdi:counter",
        native_min_value=1.0,
        native_max_value=10.0,
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
    # Minutes from the last shot before a P2 top-up may go, so a shot reaches the probe
    # before moisture is judged again. 0 (the default) turns the gap off; the controller
    # falls back to the same 0 when an older integration has no such entity.
    NumberEntityDescription(
        key="p2_time_between_shots",
        name="P2 Time Between Shots",
        icon="mdi:timer-outline",
        native_min_value=0.0,
        native_max_value=60.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode="box",
    ),
    # Minutes from the last shot before an EC correction (a flush or a dilute) or the
    # minimum-daily floor may go, so a shot drains and is read again before the next.
    # 10 (the default) is the gap the controller always used, and falls back to.
    NumberEntityDescription(
        key="ec_min_interval",
        name="EC Correction Minimum Interval",
        icon="mdi:timer-sand",
        native_min_value=1.0,
        native_max_value=120.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
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
        key="p3_emergency_vwc_threshold",
        name="P3 Emergency VWC Threshold",
        icon="mdi:alert",
        native_min_value=MOISTURE_RANGES["p3_emergency_vwc_threshold"][0],
        native_max_value=MOISTURE_RANGES["p3_emergency_vwc_threshold"][1],
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
    # Minutes from the last shot before a P3 emergency shot may go, so a rescue reaches the probe
    # before moisture is judged again. 0 turns the gap off. The controller falls back to the same
    # 10 when an older integration has no such entity.
    NumberEntityDescription(
        key="p3_time_between_shots",
        name="P3 Time Between Shots",
        icon="mdi:timer-outline",
        native_min_value=0.0,
        native_max_value=60.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode="box",
    ),
    # EC Target Parameters - CRITICAL MISSING ENTITIES
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
    # The engine blocks irrigation while the live tank pH/EC sit outside
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
    # CS-311: the sump pump counts as running while its plug reads above this. The controller puts
    # the plug's reading into watts first, whatever unit it reports.
    NumberEntityDescription(
        key="sump_power_threshold_w",
        name="Sump Pump Run Threshold",
        icon="mdi:pump",
        native_min_value=1,
        native_max_value=10000,
        native_step=1,
        native_unit_of_measurement="W",
        mode="box",
    ),
]

# Default values (shared by global + per-zone entities): the entity-default column of the one
# defaults table, which the controller's fallbacks sit beside (generated/defaults.py).
DEFAULT_VALUES = ENTITY_DEFAULTS


def _room_substrate(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """What the room grows in: its substrate select, or the value Home Assistant is about to restore to
    it (the selects and these numbers are set up side by side). generic when neither is known.
    """
    entity_id = f"select.{DOMAIN}_{room_prefix(entry)}substrate"
    state = hass.states.get(entity_id)
    if state is None:
        stored = restore_state_data(hass).last_states.get(entity_id)
        if stored is not None and restored_state_is_ours(entry, stored.state):
            state = stored.state
    value = state.state if state is not None else "generic"
    return value if value in SUBSTRATE_PROFILES else "generic"


def substrate_default(hass: HomeAssistant, entry: ConfigEntry, key: str):
    """The room's substrate profile's starting value for a setting (VWC bands, dryback targets), or None."""
    profile = SUBSTRATE_PROFILES[_room_substrate(hass, entry)]
    return {**profile["vwc"], **profile["dryback"]}.get(key)


# Steering params that ALSO get per-zone overrides (number.crop_steering_zone_N_<...>).
# Hardware/substrate (substrate_volume, dripper_flow_rate, drippers_per_plant) and
# system (lights_*) stay GLOBAL only. field_capacity / maximum_ec / watchdog_hours are
# per-zone here because the lean engine's _zone_num reads the per-zone number.* first and
# falls back to the global — without the per-zone entity those three silently use the
# global/default and the f2 per-zone editor writes number.set_value to a missing entity.
PER_ZONE_STEERING_KEYS = [
    "vegetative_dryback_target",
    "generative_dryback_target",
    "p0_maximum_wait_time",
    "p0_dryback_drop_percent",
    "p1_target_vwc",
    "p1_initial_shot_size",
    "p1_shot_size_increment",
    "p1_time_between_shots",
    "p1_maximum_shots",
    "p1_minimum_shots",
    "p1_rise_pts",
    "p1_maximum_extra_shots",
    "p2_vwc_threshold",
    "p2_shot_size",
    "p2_time_between_shots",
    "ec_min_interval",
    "p3_emergency_vwc_threshold",
    "p3_emergency_shot_size",
    "p3_time_between_shots",
    "ec_target_veg_p0",
    "ec_target_veg_p1",
    "ec_target_veg_p2",
    "ec_target_gen_p0",
    "ec_target_gen_p1",
    "ec_target_gen_p2",
    "field_capacity",
    "maximum_ec",
    "watchdog_hours",
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
    "p0_max_wait": "p0_maximum_wait_time",
    # P1
    "p1_initial_shot_size": "p1_initial_shot_size",
    "p1_shot_increment": "p1_shot_size_increment",
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
    # Photoperiod. The setup wizard has always asked for these and stored them, but they were
    # missing here, so the entities seeded to 12/0 whatever the operator typed: the grow-day,
    # the P3->P0 reset and the overnight dry-back all ran on the wrong clock. A seed only
    # applies to a NEWLY created entity (an existing one restores its own last value), so
    # adding them cannot move the lights schedule of an install that is already running.
    "lights_on_hour": "lights_on_hour",
    "lights_off_hour": "lights_off_hour",
}


def read_ladder(hass, entry, zone=None) -> dict[str, float]:
    """{level: value} of one zone's moisture ladder (zone None: the room-level numbers), as Home
    Assistant holds it now. Found by unique id, so a renamed entity id is still found; a level with
    no number or no numeric state is left out."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    scope = "" if zone is None else f"zone_{zone}_"
    out = {}
    for key in LADDER:
        entity_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{DOMAIN}_{entry.entry_id}_{scope}{key}"
        )
        state = hass.states.get(entity_id) if entity_id else None
        try:
            out[key] = float(state.state)
        except (AttributeError, TypeError, ValueError):
            continue
    return out


async def async_set_numbers(hass, values) -> tuple[int, list]:
    """Write [(entity_id, value)] as one move. A moisture level refused because its neighbour has
    not moved yet is written on a later pass. Returns (how many were written, [(entity_id, error)]
    for each that never was)."""
    written, pending = 0, list(values)
    while pending:
        refused = []
        for entity_id, value in pending:
            try:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": value},
                    blocking=True,
                )
                written += 1
            except Exception as err:  # noqa: BLE001 - reported to the caller
                refused.append((entity_id, value, err))
        if len(refused) == len(pending):
            return written, [(entity_id, err) for entity_id, _v, err in refused]
        pending = [(entity_id, value) for entity_id, value, _err in refused]
    return written, []


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
        configured_zones = config_data.get("zones") or {}
        zone_cfg = (
            configured_zones.get(str(zone_num), configured_zones.get(zone_num, {}))
            or {}
        )

        # Zone plant count
        numbers.append(
            CropSteeringNumber(
                entry,
                NumberEntityDescription(
                    key=f"zone_{zone_num}_plant_count",
                    name=f"Crop Steering Zone {zone_num} Plant Count",
                    icon="mdi:sprout",
                    native_min_value=1,
                    native_max_value=1000,
                    native_step=1,
                    mode="box",
                ),
                zone_num=zone_num,
                default_value=zone_cfg.get(
                    "plant_count", ENTITY_DEFAULTS["plant_count"]
                ),
            )
        )

        # Add only explicitly configured sizing fields. Old installations retain
        # their existing room-global fallback rather than acquiring new defaults.
        for sizing_key in (
            "substrate_volume",
            "drippers_per_plant",
            "dripper_flow_rate",
        ):
            if sizing_key not in zone_cfg:
                continue
            source = _DESC_BY_KEY[sizing_key]
            numbers.append(
                CropSteeringNumber(
                    entry,
                    NumberEntityDescription(
                        key=f"zone_{zone_num}_{sizing_key}",
                        name=f"Crop Steering Zone {zone_num} {source.name}",
                        icon=source.icon,
                        native_min_value=(
                            0.1
                            if sizing_key == "substrate_volume"
                            else source.native_min_value
                        ),
                        native_max_value=(
                            20
                            if sizing_key == "drippers_per_plant"
                            else source.native_max_value
                        ),
                        native_step=source.native_step,
                        native_unit_of_measurement=source.native_unit_of_measurement,
                        mode="box",
                    ),
                    zone_num=zone_num,
                    default_value=zone_cfg[sizing_key],
                )
            )

        # Zone water limits
        numbers.append(
            CropSteeringNumber(
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
                default_value=zone_cfg.get(
                    "max_daily_volume", ENTITY_DEFAULTS["max_daily_volume"]
                ),
            )
        )

        # Minimum daily water: watered whatever the probe reads, so it starts off. It replaces
        # the input_number helper of the same name nothing created; a new entity takes its value.
        min_daily_key = f"zone_{zone_num}_min_daily_ml_per_plant"
        numbers.append(
            CropSteeringNumber(
                entry,
                NumberEntityDescription(
                    key=min_daily_key,
                    name=f"Crop Steering Zone {zone_num} Min Daily Water Per Plant",
                    icon="mdi:water-plus",
                    native_min_value=0,
                    native_max_value=10000,
                    native_step=1,
                    native_unit_of_measurement=UnitOfVolume.MILLILITERS,
                    mode="box",
                ),
                zone_num=zone_num,
                default_value=ENTITY_DEFAULTS["min_daily_ml_per_plant"],
                legacy_helper=f"input_number.{DOMAIN}_{room_prefix(entry)}{min_daily_key}",
            )
        )

        # Per-zone copy of every steering parameter (the engine falls back to global).
        for _key in PER_ZONE_STEERING_KEYS:
            _g = _DESC_BY_KEY[_key]
            numbers.append(
                CropSteeringNumber(
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
                )
            )

        # P0 additional dryback, per zone only: P0 ends once moisture is this % below the highest
        # reading since lights-on. 0 is off (P0 waits for the dryback target, as before).
        numbers.append(
            CropSteeringNumber(
                entry,
                NumberEntityDescription(
                    key=f"zone_{zone_num}_p0_additional_dryback",
                    name=f"Crop Steering Zone {zone_num} P0 Additional Dryback",
                    icon="mdi:water-minus",
                    native_min_value=0.0,
                    native_max_value=40.0,
                    native_step=0.5,
                    native_unit_of_measurement=PERCENTAGE,
                    mode="box",
                ),
                zone_num=zone_num,
                default_value=entry.data.get(CONF_P0_ADDITIONAL_DRYBACK, 0.0),
            )
        )

    # Each number reads its siblings for a limit that follows the zone's size (bounds.py).
    room = {number.entity_description.key: number for number in numbers}
    for number in numbers:
        number._room = room
    hass.data[DOMAIN].setdefault("_numbers", {})[entry.entry_id] = room
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
        legacy_helper: str | None = None,
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
        self._legacy_helper = legacy_helper
        self._setup_value = None
        self._setup_revision = 0
        self._room = {}
        if zone_num is not None:
            sizing, revision = configured_sizing(entry, zone_num)
            key = description.key.removeprefix(f"zone_{zone_num}_")
            if key in SIZING_KEYS and key in sizing:
                self._setup_value = sizing[key]
                self._setup_revision = revision
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{description.key}"
        self._attr_name = description.name
        # Set object_id to include crop_steering prefix for entity_id generation
        self._attr_object_id = f"{DOMAIN}_{room_prefix(entry)}{description.key}"
        # Home Assistant ignores _attr_object_id and would name a NEW entity from its friendly name
        # (number.p1_target_vwc). Existing installs keep the id the registry already holds.
        self.entity_id = f"number.{self._attr_object_id}"

        # For per-zone steering entities the description key is "zone_N_<base>"; strip
        # the zone prefix so the seed lookup uses the bare entity key.
        base_key = description.key
        if zone_num is not None:
            prefix = f"zone_{zone_num}_"
            if base_key.startswith(prefix):
                base_key = base_key[len(prefix) :]
        seed_value = (entity_seed or {}).get(base_key)
        if default_value is not None:
            # Caller supplied an explicit value (e.g. zone tunables from .env zones dict).
            self._attr_native_value = default_value
        elif seed_value is not None:
            self._attr_native_value = seed_value
        else:
            self._attr_native_value = DEFAULT_VALUES.get(
                description.key, description.native_min_value
            )
        # A setting still at the table's value (nothing seeded or given for it) starts at the room's
        # substrate profile instead, once the room's choice can be read (async_added_to_hass).
        self._substrate_key = (
            base_key
            if seed_value is None
            and base_key in DEFAULT_VALUES
            and self._attr_native_value == DEFAULT_VALUES[base_key]
            else None
        )

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None and self._legacy_helper:
            # First start of this entity: keep the value its old helper held (manifest
            # after_dependencies sets input_number up first).
            helper = self.hass.states.get(self._legacy_helper)
            try:
                self._attr_native_value = float(helper.state)
            except (AttributeError, ValueError, TypeError):
                pass
        restored = last_state is not None and restored_state_is_ours(
            self._entry, last_state
        )
        if not restored and self._substrate_key is not None:
            # A setting with no value yet: the room's substrate profile (generic = the table).
            value = substrate_default(self.hass, self._entry, self._substrate_key)
            if value is not None:
                self._attr_native_value = value
        # A state left behind by a DELETED room is not this room's: keep the wizard's answer.
        if restored:
            if self._setup_value is not None and prefer_setup_value(
                last_state.attributes, self._setup_revision, self._setup_value
            ):
                self._attr_native_value = self._setup_value
                return
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                # Keep default value if restore fails
                pass

    def _sizing(self, zone, key):
        """A zone's sizing setting: its own number, else the room's."""
        number = self._room.get(f"zone_{zone}_{key}") or self._room.get(key)
        return None if number is None else number.native_value

    @property
    def zone_bound(self) -> float | None:
        """The limit that follows the zone's size, or None for a setting with a fixed one."""
        key = self.entity_description.key
        if key == f"zone_{self._zone_num}_max_daily_volume":
            return daily_volume_bound(
                self._sizing(self._zone_num, "plant_count"),
                self._sizing(self._zone_num, "substrate_volume"),
            )
        if key == "max_shot_duration":
            zones = [
                int(k.split("_")[1]) for k in self._room if k.endswith("_plant_count")
            ]
            bounds = [
                shot_duration_bound(
                    self._sizing(zone, "substrate_volume"),
                    self._sizing(zone, "drippers_per_plant"),
                    self._sizing(zone, "dripper_flow_rate"),
                )
                for zone in zones
            ]
            bounds = [bound for bound in bounds if bound is not None]
            return max(bounds) if bounds else None
        return None

    @property
    def native_max_value(self) -> float:
        bound = self.zone_bound
        return self.entity_description.native_max_value if bound is None else bound

    @property
    def extra_state_attributes(self):
        if self._setup_value is not None:
            return {
                "setup_revision": self._setup_revision,
                "setup_value": self._setup_value,
            }
        return {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        if self._zone_num is not None:
            # Zone-specific device
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_zone_{self._zone_num}")},
                name=zone_device_name(self._entry, self._zone_num),
                manufacturer="Home Assistant Community",
                model="Zone Controller",
                sw_version=SOFTWARE_VERSION,
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
        """Update the value. A moisture level that breaks the ladder's order is refused
        (ladder.py); a recipe stage is judged as one set before any of it is written."""
        key = self.entity_description.key
        if self._zone_num is not None:
            key = key.removeprefix(f"zone_{self._zone_num}_")
        if key in LADDER:
            current = read_ladder(self.hass, self._entry, self._zone_num)
            why = refusal(current, {key: float(value)})
            if why:
                from homeassistant.exceptions import ServiceValidationError

                raise ServiceValidationError(
                    f"{self.name} not changed: {why}. Move the other level first."
                )
            if peak_above_field_capacity(current, {key: float(value)}):
                _LOGGER.warning(
                    "%s: the peak target is above field capacity; the ramp stops at field capacity",
                    self.entity_id,
                )
        self._attr_native_value = value
        self.async_write_ha_state()
        # A setting brought within its limit, or a zone's size changed, can clear the card.
        check_held_values(self.hass, self._entry, self._room.values())

    @property
    def available(self) -> bool:
        """Return if number is available."""
        return True
