import appdaemon.plugins.hass.hassapi as hass
import datetime
import time
import json
from collections import deque # For VWC statistics

# Define constants for phases
P0 = "P0"
P1 = "P1"
P2 = "P2"
P3 = "P3"

# Define constants for modes
VEG = "Vegetative"
GEN = "Generative"

class CropSteeringApp(hass.Hass):

    def initialize(self):
        """Initialize the AppDaemon app."""
        self.log("Initializing Crop Steering App")

        # --- Get configuration from apps.yaml ---
        # It's crucial that the keys used here (e.g., 'phase_select') match EXACTLY
        # the keys defined under 'setting_helpers', 'config_helpers', etc. in apps.yaml.
        self.config_helpers = self.args.get("config_helpers", {}) # Maps abstract name to input_text entity_id
        self.setting_helpers = self.args.get("setting_helpers", {}) # Maps abstract name to input_select/datetime/boolean entity_id
        self.output_sensors = self.args.get("output_sensors", {}) # Maps abstract name to sensor entity_id created by this app
        # Store the input_numbers map correctly from apps.yaml args
        self.input_numbers_map = self.args.get("input_numbers", {}) # Maps abstract name (e.g., "p1_max_shots") to input_number entity_id
        self.notification_service = self.args.get("notification_service", None) # e.g., "notify.mobile_app_myphone"

        # --- Internal State Variables ---
        # Assume keys 'phase_select' and 'mode_select' exist in setting_helpers in apps.yaml
        self.current_phase = self.get_state(self.setting_helpers.get("phase_select", "input_select.cs_crop_steering_phase"))
        self.steering_mode = self.get_state(self.setting_helpers.get("mode_select", "input_select.cs_steering_mode"))
        self.vwc_sensor_entities = [] # Populated by _load_config_entities
        self.ec_sensor_entities = [] # Populated by _load_config_entities
        self.pump_switch_entity = None # Populated by _load_config_entities
        self.zone_switch_entities = [] # Populated by _load_config_entities
        self.waste_switch_entity = None # Populated by _load_config_entities

        self.zone_sensor_map = {} # Populated by _load_config_entities

        # EC Stacking State
        self.ec_stacking_enabled = False
        self.ec_stacking_active_phases = []

        self.vwc_values = {} # Store last known good VWC for each sensor
        self.ec_values = {}  # Store last known good EC for each sensor
        self.avg_vwc = None
        self.avg_ec = None
        self.min_vwc = None
        self.max_vwc = None

        # Dryback state
        self.dryback_in_progress = False
        self.dryback_last_peak_vwc = None
        self.dryback_last_peak_time = None
        self.dryback_last_valley_vwc = None
        self.dryback_last_valley_time = None
        self.dryback_potential_peak = None # Store potential peak value before confirming
        self.dryback_potential_valley = None # Store potential valley value before confirming
        self.vwc_history = deque(maxlen=10) # For simple moving average/trend detection

        # Timers / Listener Handles (Store handles to allow cancellation)
        self.listener_handles = []
        self.timer_handles = {} # Store timer handles by name
        # self.last_p1_trigger_minute = -1 # No longer needed with timer-based interval

        # --- Load Initial Configuration ---
        self._load_config_entities() # Reads entity IDs from input_text helpers specified in config_helpers
        # self._load_settings() # Settings (phase/mode) are read directly at init now

        # --- Setup Listeners ---
        # Listen to changes in the input_text helpers that define *which* entities to use
        for config_key, helper_entity_id in self.config_helpers.items():
            if helper_entity_id: # Ensure entity_id is not empty
                handle = self.listen_state(self.config_entity_changed_cb, helper_entity_id, attribute="state", config_key=config_key)
                self.listener_handles.append(handle)
                self.log(f"Listening to config helper: {helper_entity_id} (Key: {config_key})")

        # Listen to changes in setting helpers (selects, datetimes, booleans)
        for setting_key, helper_entity_id in self.setting_helpers.items():
             if helper_entity_id:
                handle = self.listen_state(self.setting_changed_cb, helper_entity_id, attribute="state", setting_key=setting_key)
                self.listener_handles.append(handle)
                self.log(f"Listening to setting helper: {helper_entity_id} (Key: {setting_key})")

        # Listen to changes in input_numbers (parameters)
        for param_key, helper_entity_id in self.input_numbers_map.items(): # Use the correct map
             if helper_entity_id:
                # Use setting_key for consistency in the callback kwargs
                handle = self.listen_state(self.setting_changed_cb, helper_entity_id, attribute="state", setting_key=param_key)
                self.listener_handles.append(handle)
                self.log(f"Listening to parameter helper: {helper_entity_id} (Key: {param_key})")

        # Listen to sensor changes (will be updated when config changes)
        self._setup_sensor_listeners() # This now also stores handles in self.listener_handles

        # Listen to time-based events (assuming keys 'lights_on_time' and 'lights_off_time' in setting_helpers map to the input_datetime helpers)
        lights_on_entity_id = self.setting_helpers.get("lights_on_time", "input_datetime.cs_lights_on_time")
        lights_off_entity_id = self.setting_helpers.get("lights_off_time", "input_datetime.cs_lights_off_time")

        if lights_on_entity_id:
            # Store handle for state change listener
            handle = self.listen_state(self.lights_on_cb, lights_on_entity_id)
            self.listener_handles.append(handle)
            # Also run daily at lights on time
            self._schedule_daily_timer('daily_lights_on', lights_on_entity_id, self.lights_on_cb_daily)

        if lights_off_entity_id:
             # Store handle for state change listener
             handle = self.listen_state(self.lights_off_cb, lights_off_entity_id)
             self.listener_handles.append(handle)
             # Run daily check slightly before lights off for P3 transition
             self._schedule_daily_timer('daily_p3_check', lights_off_entity_id, self.p3_transition_check_cb, offset_minutes=-1)


        # Periodic update/check timer (e.g., every minute)
        # Store handle for periodic timer
        self.timer_handles['periodic_update'] = self.run_every(self.periodic_update_cb, self.datetime(), 60)

        # --- Initial Update ---
        self.log("Initialization complete. Performing initial update.")
        self.update_all_calculations()
        self.update_phase_and_mode() # Set initial phase based on time


    def terminate(self):
        """Clean up resources when AppDaemon stops the app."""
        self.log("Terminating Crop Steering App")
        # Cancel all timers
        for handle in self.timer_handles.values():
            try:
                self.cancel_timer(handle)
            except: # Ignore errors if handle is invalid
                pass
        self.timer_handles = {}
        # Cancel all state listeners
        for handle in self.listener_handles:
            try:
                self.cancel_listen_state(handle)
            except: # Ignore errors if handle is invalid
                pass
        self.listener_handles = []
        self.log("Timers and listeners cancelled.")


    # --- Callback Functions ---

    def config_entity_changed_cb(self, entity, attribute, old, new, kwargs):
        """Callback when a config input_text helper changes."""
        config_key = kwargs.get("config_key", "Unknown") # Use the key passed during listener setup
        self.log(f"Config helper changed ({config_key}): {entity} = {new}")
        self._load_config_entities() # Reload all config entity IDs
        self._setup_sensor_listeners() # Re-setup sensor listeners based on new IDs
        self.update_all_calculations() # Recalculate based on new sensors/config

    def setting_changed_cb(self, entity, attribute, old, new, kwargs):
        """Callback when a setting helper (select, number, datetime, boolean) changes."""
        setting_key = kwargs.get("setting_key", "Unknown") # Key from apps.yaml (e.g., 'phase_select', 'p1_max_shots')
        # Log selectively to avoid noise, especially for input_numbers
        if not entity.startswith("input_number."):
           self.log(f"Setting/Parameter changed ({setting_key}): {entity} = {new}")
        else:
           # Debug log for number changes if needed
           # self.log(f"Parameter changed ({setting_key}): {entity} = {new}", level="DEBUG")
           pass

        # If phase or mode select changes, reload them specifically
        # Assume keys 'phase_select' and 'mode_select' map to the correct input_selects
        phase_select_entity_id = self.setting_helpers.get("phase_select", "input_select.cs_crop_steering_phase")
        mode_select_entity_id = self.setting_helpers.get("mode_select", "input_select.cs_steering_mode")

        if entity == phase_select_entity_id:
            self.current_phase = new
            self.log(f"Phase explicitly changed to: {self.current_phase}")
        elif entity == mode_select_entity_id:
            self.steering_mode = new
            self.log(f"Mode explicitly changed to: {self.steering_mode}")

        # Always recalculate dependent values when any setting/parameter changes
        self.update_all_calculations()
        # Re-evaluate phase transitions and irrigation needs
        self.check_phase_transitions()
        self.check_irrigation_triggers()

        # Reschedule daily timers if time helpers change
        lights_on_entity_id = self.setting_helpers.get("lights_on_time", "input_datetime.cs_lights_on_time")
        lights_off_entity_id = self.setting_helpers.get("lights_off_time", "input_datetime.cs_lights_off_time")
        if entity == lights_on_entity_id:
             self._schedule_daily_timer('daily_lights_on', entity, self.lights_on_cb_daily)
        elif entity == lights_off_entity_id:
             self._schedule_daily_timer('daily_p3_check', entity, self.p3_transition_check_cb, offset_minutes=-1)


    def sensor_update_cb(self, entity, attribute, old, new, kwargs):
        """Callback when a monitored VWC or EC sensor changes."""
        if new is None or new == 'unknown' or new == 'unavailable':
            # self.log(f"Sensor {entity} reported invalid state: {new}", level="DEBUG") # Can be noisy
            # Decide how to handle unavailable sensors (e.g., remove from avg?)
            if entity in self.vwc_values: del self.vwc_values[entity]
            if entity in self.ec_values: del self.ec_values[entity]
        else:
            try:
                value = float(new)
                # Apply validation rules using _get_setting for safety
                # Assumes keys like 'min_valid_vwc' exist in input_numbers map in apps.yaml
                min_vwc = self._get_setting("min_valid_vwc", 0.0)
                max_vwc = self._get_setting("max_valid_vwc", 100.0)
                min_ec = self._get_setting("min_valid_ec", 0.0)
                max_ec = self._get_setting("max_ec", 10.0)

                is_vwc = entity in self.vwc_sensor_entities # More efficient check
                is_ec = entity in self.ec_sensor_entities # More efficient check
                is_zone_sensor = any(entity in sensors for sensors in self.zone_sensor_map.values()) # Check if it's a configured zone sensor

                valid = False
                sensor_type = "Unknown"

                if is_vwc:
                    sensor_type = "VWC"
                    if min_vwc <= value <= max_vwc:
                        self.vwc_values[entity] = value
                        self.vwc_history.append(value) # Add all valid VWC readings to history for better trend
                        valid = True
                elif is_ec:
                    sensor_type = "EC"
                    if min_ec <= value <= max_ec:
                        self.ec_values[entity] = value
                        valid = True
                elif is_zone_sensor:
                    # Determine if zone sensor is VWC or EC
                    is_zone_vwc = any(entity in sensors for key, sensors in self.zone_sensor_map.items() if 'vwc' in key)
                    is_zone_ec = any(entity in sensors for key, sensors in self.zone_sensor_map.items() if 'ec' in key)
                    if is_zone_vwc:
                        sensor_type = "Zone VWC"
                        if min_vwc <= value <= max_vwc:
                            self.vwc_values[entity] = value # Store zone values too
                            valid = True
                    elif is_zone_ec:
                        sensor_type = "Zone EC"
                        if min_ec <= value <= max_ec:
                            self.ec_values[entity] = value # Store zone values too
                            valid = True

                if valid:
                    # Optional: Debug log for valid readings
                    # self.log(f"Valid {sensor_type} reading for {entity}: {value}", level="DEBUG")
                    pass
                else:
                    # Log invalid readings more clearly
                    range_str = f"{min_vwc}-{max_vwc}%" if "VWC" in sensor_type else f"{min_ec}-{max_ec} mS/cm"
                    self.log(f"INVALID {sensor_type} reading: {entity} reported {value}, which is outside the valid range ({range_str}). Ignoring value.", level="WARNING")
                    # Remove from stored values if previously valid
                    if entity in self.vwc_values: del self.vwc_values[entity]
                    if entity in self.ec_values: del self.ec_values[entity]


            except (ValueError, TypeError) as e:
                self.log(f"Could not convert sensor {entity} state '{new}' to float: {e}", level="ERROR")
                if entity in self.vwc_values: del self.vwc_values[entity]
                if entity in self.ec_values: del self.ec_values[entity]

        # Recalculate aggregations and dependent values
        self.update_aggregations()
        self.update_dependent_calculations()
        self.detect_dryback_changes() # Check for peak/valley
        self.check_irrigation_triggers() # Check if irrigation needed based on new values

    def lights_on_cb(self, entity, attribute, old, new, kwargs):
        """Callback when lights on time changes (or daily trigger)."""
        self.log("Lights ON triggered/time changed.")
        self.set_phase(P0) # Always reset to P0 at lights on
        # Reset counters (assuming keys 'p1_shot_count', 'p2_shot_count', 'p3_shot_count' in input_numbers_map map)
        p1_count_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
        p2_count_entity_id = self.input_numbers_map.get("p2_shot_count", "input_number.cs_p2_shot_count")
        p3_count_entity_id = self.input_numbers_map.get("p3_shot_count", "input_number.cs_p3_shot_count")
        if p1_count_entity_id: self.call_service("input_number/set_value", entity_id=p1_count_entity_id, value=0)
        if p2_count_entity_id: self.call_service("input_number/set_value", entity_id=p2_count_entity_id, value=0)
        if p3_count_entity_id: self.call_service("input_number/set_value", entity_id=p3_count_entity_id, value=0)

        # Reset dryback state at lights on
        self.dryback_in_progress = False
        self.dryback_last_peak_vwc = None
        self.dryback_last_peak_time = None
        self.dryback_last_valley_vwc = None
        self.dryback_last_valley_time = None
        self.dryback_potential_peak = None
        self.dryback_potential_valley = None
        self.vwc_history.clear()
        self._set_output_sensor_state("dryback_in_progress", "off")
        self._set_output_sensor_state("dryback_last_peak_vwc", "unknown")
        self._set_output_sensor_state("dryback_last_peak_time", "unknown")
        self._set_output_sensor_state("dryback_last_valley_vwc", "unknown")
        self._set_output_sensor_state("dryback_last_valley_time", "unknown")
        self._set_output_sensor_state("dryback_last_percentage", 0)
        self._set_output_sensor_state("dryback_last_duration", 0)


        self.update_all_calculations()

    def lights_on_cb_daily(self, kwargs):
        """Daily callback exactly at lights on time."""
        self.log("Daily Lights ON check.")
        self.lights_on_cb(self.setting_helpers.get("lights_on_time"), None, None, None, None)

    def lights_off_cb(self, entity, attribute, old, new, kwargs):
        """Callback when lights off time changes."""
        self.log("Lights OFF time changed.")
        # Reschedule P3 transition check timer
        self._schedule_daily_timer('daily_p3_check', entity, self.p3_transition_check_cb, offset_minutes=-1)
        self.update_all_calculations()

    def p3_transition_check_cb(self, kwargs):
        """Callback shortly before lights off to check for P3 transition."""
        self.log("Checking for P3 transition.")
        # Ensure mode is loaded
        if not self.steering_mode: self._load_settings()
        if not self.steering_mode:
             self.log("Steering mode not loaded, cannot check P3 transition.", level="WARNING")
             return

        if self.current_phase == P2:
             # Use the dynamic P3 start time calculation logic
             p3_start_time_iso = self._calculate_p3_start_time_iso()
             if p3_start_time_iso:
                 try:
                     p3_start_dt = self.parse_datetime(p3_start_time_iso)
                     now_dt = self.datetime()

                     # Check if current time is at or after P3 start time today
                     # Handle potential day rollover carefully
                     p3_start_today_dt = now_dt.replace(hour=p3_start_dt.hour, minute=p3_start_dt.minute, second=p3_start_dt.second, microsecond=0)

                     # If P3 start time is later today than now, it must have been yesterday's target
                     if p3_start_today_dt > now_dt:
                         p3_start_effective_dt = p3_start_today_dt - datetime.timedelta(days=1)
                     else: # P3 start time was earlier today
                         p3_start_effective_dt = p3_start_today_dt

                     if now_dt >= p3_start_effective_dt:
                         self.log(f"Time {now_dt} is after calculated P3 start {p3_start_effective_dt}, transitioning.")
                         self.set_phase(P3)
                     else:
                         self.log(f"Time {now_dt} is before calculated P3 start {p3_start_effective_dt}, no transition yet.")

                 except Exception as e:
                     self.log(f"Error comparing time for P3 transition: {e}", level="ERROR")
             else:
                 self.log("Could not calculate P3 start time for transition check.", level="WARNING")


    def periodic_update_cb(self, kwargs):
        """Periodic callback for updates and checks."""
        # self.log("Periodic update triggered.")
        self.update_time_sensors() # Update time-based sensors like minutes_since_lights_on
        self.check_phase_transitions()
        self.check_irrigation_triggers() # Re-evaluate irrigation needs periodically
        self.update_status_outputs() # Update HA sensors created by the app

    # --- Helper Methods ---

    def _schedule_daily_timer(self, timer_key, time_entity, callback, offset_minutes=0):
         """Helper to schedule or reschedule daily timers."""
         if timer_key in self.timer_handles:
             try:
                 self.cancel_timer(self.timer_handles[timer_key])
                 # self.log(f"Cancelled existing timer: {timer_key}") # Debug
             except: # Ignore errors if handle is invalid
                 self.log(f"Could not cancel timer {timer_key}, handle might be invalid.", level="WARNING")


         try:
             time_str = self.get_state(time_entity)
             if not time_str:
                 self.log(f"Time entity {time_entity} has no state, cannot schedule {timer_key}.", level="WARNING")
                 return

             base_time_dt = datetime.datetime.strptime(time_str, '%H:%M:%S').time()
             if offset_minutes != 0:
                 # Apply offset carefully, handling midnight wrap-around
                 offset_time = (datetime.datetime.combine(datetime.date.today(), base_time_dt) + datetime.timedelta(minutes=offset_minutes)).time()
             else:
                 offset_time = base_time_dt

             self.timer_handles[timer_key] = self.run_daily(callback, offset_time)
             self.log(f"Scheduled daily timer '{timer_key}' for {offset_time} based on {time_entity}")
         except Exception as e:
             self.log(f"Error scheduling daily timer '{timer_key}': {e}", level="WARNING")


    def _load_config_entities(self):
        """Load entity IDs from config input_text helpers defined in apps.yaml."""
        self.log("Loading config entities from input_text helpers...")
        # Use the actual input_text entity IDs from variables.yaml as defaults if keys missing in apps.yaml
        self.vwc_sensor_entities = self._get_entity_list_from_helper("config_vwc_sensor_entities", "input_text.cs_config_vwc_sensor_entities")
        self.ec_sensor_entities = self._get_entity_list_from_helper("config_ec_sensor_entities", "input_text.cs_config_ec_sensor_entities")
        self.pump_switch_entity = self.get_state(self.config_helpers.get("config_pump_switch_entity", "input_text.cs_config_pump_switch_entity"))
        self.zone_switch_entities = self._get_entity_list_from_helper("config_zone_switch_entities", "input_text.cs_config_zone_switch_entities")
        self.waste_switch_entity = self.get_state(self.config_helpers.get("config_waste_switch_entity", "input_text.cs_config_waste_switch_entity"))

        # Load zone sensor mappings using keys from variables.yaml as defaults
        self.zone_sensor_map = {}
        for i in range(1, 4): # Zones 1, 2, 3
            for sensor_type in ['vwc', 'ec']:
                for position in ['front', 'back']:
                    # Construct the key expected in config_helpers based on variables.yaml naming
                    config_helper_key = f"config_z{i}_{sensor_type}_{position}"
                    # Construct the default entity ID if the key isn't in apps.yaml
                    default_entity_id = f"input_text.cs_{config_helper_key}" # Construct default ID
                    # Get the entity ID from the helper specified in apps.yaml, or use the default
                    entity_id_helper = self.config_helpers.get(config_helper_key, default_entity_id)
                    entity_id = self.get_state(entity_id_helper)

                    if entity_id:
                        map_key = f"z{i}_{sensor_type}" # e.g., z1_vwc
                        if map_key not in self.zone_sensor_map:
                            self.zone_sensor_map[map_key] = []
                        # Avoid adding duplicates if front/back helper points to same entity
                        if entity_id not in self.zone_sensor_map[map_key]:
                             self.zone_sensor_map[map_key].append(entity_id)

        # Filter out duplicates just in case (redundant with check above, but safe)
        # for key, sensors in self.zone_sensor_map.items():
        #     self.zone_sensor_map[key] = list(set(s for s in sensors if s)) # Keep unique, non-empty

        self.log(f" VWC Sensors: {self.vwc_sensor_entities}")
        self.log(f" EC Sensors: {self.ec_sensor_entities}")
        self.log(f" Pump Switch: {self.pump_switch_entity}")
        self.log(f" Zone Switches: {self.zone_switch_entities}")
        self.log(f" Waste Switch: {self.waste_switch_entity}")
        self.log(f" Zone Sensor Map: {self.zone_sensor_map}")


    def _get_entity_list_from_helper(self, helper_key, default_entity_id=None):
        """Gets a list of entities from a comma-separated input_text helper."""
        helper_entity_id = self.config_helpers.get(helper_key, default_entity_id)
        if not helper_entity_id:
            self.log(f"Config helper key '{helper_key}' not found in apps.yaml and no default provided", level="ERROR")
            return []
        value = self.get_state(helper_entity_id)
        if value:
            return [e.strip() for e in value.split(',') if e.strip()]
        return []

    def _setup_sensor_listeners(self):
        """Set up state listeners for configured sensors."""
        self.log("Setting up sensor listeners...")
        # Cancel existing sensor listeners first
        # Iterate safely while removing items
        indices_to_remove = []
        for i, handle in enumerate(self.listener_handles):
             try:
                 # Simplified listener cancellation
                 self.cancel_listen_state(handle)
                 indices_to_remove.append(i)
             except Exception as e:
                 self.log(f"Error cancelling listener handle {handle}: {e}", level="WARNING")
                 indices_to_remove.append(i) # Remove potentially invalid handle

        # Remove cancelled handles from the list
        for i in sorted(indices_to_remove, reverse=True):
            del self.listener_handles[i]

        all_sensors = set(self.vwc_sensor_entities + self.ec_sensor_entities)
        for sensors in self.zone_sensor_map.values():
            all_sensors.update(s for s in sensors if s) # Add only non-empty sensor IDs

        # Clear current sensor values when listeners are reset
        self.vwc_values = {}
        self.ec_values = {}

        for sensor in all_sensors:
            if sensor: # Ensure not empty string
                 handle = self.listen_state(self.sensor_update_cb, sensor)
                 self.listener_handles.append(handle) # Store handle
                 self.log(f" Listening to {sensor}")
                 # Trigger initial read for the sensor
                 self.sensor_update_cb(sensor, "state", None, self.get_state(sensor), {})


    def _load_settings(self):
         """Load current settings from helpers."""
         # self.log("Loading settings from helpers...") # Can be noisy
         phase_entity = self.setting_helpers.get("phase_select")
         mode_entity = self.setting_helpers.get("mode_select")
         self.current_phase = self.get_state(phase_entity) if phase_entity else P0
         self.steering_mode = self.get_state(mode_entity) if mode_entity else VEG

         # Load EC Stacking settings
         ec_stacking_enabled_entity = self.setting_helpers.get("ec_stacking_enabled", "input_boolean.cs_ec_stacking_enabled")
         ec_stacking_phases_entity = self.setting_helpers.get("ec_stacking_active_phases", "input_text.cs_ec_stacking_active_phases")

         self.ec_stacking_enabled = self.get_state(ec_stacking_enabled_entity) == 'on'
         phases_str = self.get_state(ec_stacking_phases_entity)
         self.ec_stacking_active_phases = [p.strip().upper() for p in phases_str.split(',') if p.strip()] if phases_str else []

         # Ensure defaults if state is invalid
         if not self.current_phase: self.current_phase = P0
         if not self.steering_mode: self.steering_mode = VEG


    def _get_setting(self, setting_name, default=None):
         """Safely get a setting value from the input_numbers map defined in apps.yaml."""
         # Use the stored map from initialize
         entity_id = self.input_numbers_map.get(setting_name)
         if entity_id:
             try:
                 # Use get_state which handles unavailable states better
                 state = self.get_state(entity_id)
                 if state is None or state == 'unknown' or state == 'unavailable':
                      # self.log(f"State of {entity_id} is {state}, using default {default}", level="DEBUG")
                      return default
                 return float(state)
             except (ValueError, TypeError):
                 self.log(f"Invalid value '{state}' for {entity_id}, using default {default}", level="WARNING")
                 return default
         # self.log(f"Setting '{setting_name}' not found in apps.yaml config, using default {default}", level="DEBUG")
         return default

    def update_aggregations(self):
        """Calculate average, min, max VWC/EC from valid sensor readings."""
        # Use only sensors listed in the main aggregation lists for avg/min/max
        valid_vwc_values = {k: v for k, v in self.vwc_values.items() if k in self.vwc_sensor_entities}
        valid_ec_values = {k: v for k, v in self.ec_values.items() if k in self.ec_sensor_entities}

        if valid_vwc_values:
            self.avg_vwc = round(sum(valid_vwc_values.values()) / len(valid_vwc_values), 2)
            self.min_vwc = round(min(valid_vwc_values.values()), 2)
            self.max_vwc = round(max(valid_vwc_values.values()), 2)
        else:
            self.avg_vwc = None
            self.min_vwc = None
            self.max_vwc = None

        if valid_ec_values:
            self.avg_ec = round(sum(valid_ec_values.values()) / len(valid_ec_values), 2)
        else:
            self.avg_ec = None

        # Update zone sensors using potentially different sensor sets
        for zone_key, sensors in self.zone_sensor_map.items():
            zone_type = zone_key.split('_')[1] # vwc or ec
            zone_id = self.output_sensors.get(zone_key) # Get output sensor ID from apps.yaml
            if not zone_id: continue # Skip if not defined in output_sensors

            values = []
            for s_entity in sensors:
                # Check if the sensor entity exists and has a valid value stored
                if zone_type == 'vwc' and s_entity in self.vwc_values:
                    values.append(self.vwc_values[s_entity])
                elif zone_type == 'ec' and s_entity in self.ec_values:
                    values.append(self.ec_values[s_entity])

            if values:
                avg_val = round(sum(values) / len(values), 2 if zone_type == 'ec' else 1)
                self._set_output_sensor_state(zone_key, avg_val, unit="%" if zone_type == 'vwc' else "mS/cm")
            else:
                 self._set_output_sensor_state(zone_key, "unknown")


    def update_dependent_calculations(self):
        """Update sensors whose values depend on other settings or sensors."""
        # EC Ratio
        target_ec = self._calculate_current_ec_target()
        if self.avg_ec is not None and target_ec is not None and target_ec > 0:
            ec_ratio = round(self.avg_ec / target_ec, 2)
        else:
            ec_ratio = 1.0 # Default or unknown
        self._set_output_sensor_state("ec_ratio", ec_ratio)
        self._set_output_sensor_state("current_ec_target", target_ec, unit="mS/cm")

        # Shot Durations (Using keys matching YAML sensor names)
        self._set_output_sensor_state("p1_shot_duration_seconds", self._calculate_shot_duration("p1"), unit="s")
        self._set_output_sensor_state("p2_shot_duration_seconds", self._calculate_shot_duration("p2"), unit="s")
        self._set_output_sensor_state("p3_emergency_shot_duration_seconds", self._calculate_shot_duration("p3_emergency"), unit="s")

        # Adjusted P2 Threshold
        adj_thresh = self._calculate_p2_vwc_threshold_adjusted(ec_ratio)
        self._set_output_sensor_state("p2_vwc_threshold_adjusted", adj_thresh, unit="%")

        # Dynamic Drybacks
        self._set_output_sensor_state("dynamic_p0_dryback", self._get_setting(f"p0_{self.steering_mode.lower()}_dryback_target", 0), unit="%")
        self._set_output_sensor_state("dynamic_p2_dryback", adj_thresh if self.current_phase == P2 else self._get_setting("p2_vwc_threshold", 0), unit="%")
        self._set_output_sensor_state("dynamic_p3_dryback", self._get_setting("p3_emergency_vwc_threshold", 0), unit="%")

        # Dryback calculations
        self._update_dryback_outputs()


    def update_time_sensors(self):
         """Update sensors based on current time."""
         time_since_on_sec = self._calculate_time_since_lights_on()
         time_until_off_sec = self._calculate_time_until_lights_off()

         self._set_output_sensor_state("minutes_since_lights_on", round(time_since_on_sec / 60) if time_since_on_sec is not None else "unknown", unit="min")
         self._set_output_sensor_state("minutes_until_lights_off", round(time_until_off_sec / 60) if time_until_off_sec is not None else "unknown", unit="min")


    def update_status_outputs(self):
         """Update general status sensors like phase description, irrigation status."""
         # Phase Description
         phase_desc = self._calculate_phase_description()
         self._set_output_sensor_state("phase_description", phase_desc)

         # Irrigation Status
         irr_status = self._calculate_irrigation_status()
         self._set_output_sensor_state("irrigation_status", irr_status)

         # Update aggregated sensors
         self._set_output_sensor_state("avg_vwc", self.avg_vwc if self.avg_vwc is not None else "unknown", unit="%")
         self._set_output_sensor_state("avg_ec", self.avg_ec if self.avg_ec is not None else "unknown", unit="mS/cm")
         self._set_output_sensor_state("min_vwc", self.min_vwc if self.min_vwc is not None else "unknown", unit="%")
         self._set_output_sensor_state("max_vwc", self.max_vwc if self.max_vwc is not None else "unknown", unit="%")


    def update_all_calculations(self):
        """Run all calculation updates."""
        self.update_aggregations()
        self.update_dependent_calculations()
        self.update_time_sensors()
        self.update_status_outputs()
        self.detect_dryback_changes()

    def update_phase_and_mode(self):
        """Read current phase and mode from HA"""
        phase_entity = self.setting_helpers.get("phase_select")
        mode_entity = self.setting_helpers.get("mode_select")
        self.current_phase = self.get_state(phase_entity) if phase_entity else P0
        self.steering_mode = self.get_state(mode_entity) if mode_entity else VEG
        # Ensure defaults if state is invalid
        if not self.current_phase: self.current_phase = P0
        if not self.steering_mode: self.steering_mode = VEG
        # self.log(f"Phase updated to: {self.current_phase}, Mode: {self.steering_mode}")


    def set_phase(self, new_phase):
        """Set the crop steering phase."""
        if self.current_phase != new_phase:
            self.log(f"Transitioning from {self.current_phase} to {new_phase}")
            self.current_phase = new_phase
            # Update the input_select in HA
            phase_select_entity = self.setting_helpers.get("phase_select")
            if phase_select_entity:
                self.call_service("input_select/select_option",
                                  entity_id=phase_select_entity,
                                  option=new_phase)
            else:
                 self.log("Phase select helper not configured!", level="ERROR")

            # Update dependent calculations and status
            self.update_all_calculations()
            # Cancel any phase-specific timers if needed
            self._cancel_timers()


    def check_phase_transitions(self):
        """Evaluate conditions for phase transitions."""
        # Ensure current phase and mode are loaded
        if not self.current_phase or not self.steering_mode:
            self.update_phase_and_mode()
            if not self.current_phase or not self.steering_mode:
                # self.log("Cannot check phase transitions: phase or mode not loaded.", level="DEBUG")
                return

        # --- P0 -> P1 Transition ---
        if self.current_phase == P0:
            min_wait_sec = self._get_setting("p0_min_wait_time", 30) * 60
            max_wait_sec = self._get_setting("p0_max_wait_time", 120) * 60
            # Use the dynamic P0 dryback target calculated elsewhere
            dryback_target = self._get_output_sensor_state("dynamic_p0_dryback")
            if dryback_target is None or dryback_target == 'unknown':
                # self.log("P0->P1 check: Dynamic P0 dryback target not available.", level="DEBUG")
                return # Cannot check without target
            dryback_target = self.safe_float(dryback_target, 999)

            time_since_on = self._calculate_time_since_lights_on() # Returns seconds or None

            if time_since_on is None:
                # self.log("P0->P1 check: Cannot calculate time since lights on.", level="DEBUG")
                return # Cannot check without time

            vwc_ok = self.avg_vwc is not None and self.avg_vwc <= dryback_target
            min_wait_ok = time_since_on >= min_wait_sec
            max_wait_ok = time_since_on >= max_wait_sec

            if min_wait_ok and vwc_ok:
                self.log(f"P0->P1: Dryback target {dryback_target}% reached after min wait ({min_wait_sec/60}m). VWC: {self.avg_vwc}%.")
                self.set_phase(P1)
            elif max_wait_ok:
                self.log(f"P0->P1: Max wait time {max_wait_sec/60}m reached. VWC: {self.avg_vwc}%.")
                self.set_phase(P1)

        # --- P1 -> P2 Transition ---
        elif self.current_phase == P1:
             # Get relevant input_number entity IDs using the map
             p1_shots_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
             p1_shots = int(self.safe_float(self.get_state(p1_shots_entity_id), 0))

             max_shots = self._get_setting("p1_max_shots", 6)
             min_shots = self._get_setting("p1_min_shots", 3) # Min shots needed for VWC/EC transition
             target_vwc = self._get_setting("p1_target_vwc", 30)
             flush_ec_target = self._get_setting("ec_target_flush", 0.8)

             # Evaluate conditions
             max_shots_reached = p1_shots >= max_shots
             # Ensure avg_vwc is not None before comparing
             target_vwc_reached = self.avg_vwc is not None and self.avg_vwc >= target_vwc
             # Ensure avg_ec is not None before comparing
             ec_condition_met = self.avg_ec is not None and self.avg_ec <= flush_ec_target
             min_shots_ok = p1_shots >= min_shots

             # Transition logic - Max shots takes precedence
             if max_shots_reached:
                 self.log(f"P1->P2: Max shots ({max_shots}) reached. Transitioning.")
                 self.set_phase(P2)
             # Then check VWC target condition
             elif target_vwc_reached and min_shots_ok:
                 self.log(f"P1->P2: Target VWC ({target_vwc}%) reached after min shots ({min_shots}). VWC: {self.avg_vwc}%. Transitioning.")
                 self.set_phase(P2)
             # Finally check EC reset condition (requires VWC target AND min shots too)
             elif ec_condition_met and target_vwc_reached and min_shots_ok:
                 message = f"P1->P2: EC Reset condition (EC <= {flush_ec_target}) met, VWC >= {target_vwc}%, and min shots ({min_shots}) reached. EC: {self.avg_ec}, VWC: {self.avg_vwc}%. Transitioning."
                 self.log(message)
                 self._send_notification(f"Phase Transition: {message}")
                 self.set_phase(P2)

        # --- P2 -> P3 Transition ---
        elif self.current_phase == P2:
            # This transition is primarily time-based, handled by p3_transition_check_cb
            # Check if the time is right via the daily callback
            pass

        # --- P3 -> P0 Transition ---
        elif self.current_phase == P3:
            # This transition happens at lights on, handled by lights_on_cb_daily
            pass


    def check_irrigation_triggers(self):
        """Check if conditions are met to start an irrigation cycle."""
        # Ensure phase/mode are loaded
        if not self.current_phase or not self.steering_mode:
            self.update_phase_and_mode()
            if not self.current_phase or not self.steering_mode:
                # self.log("Cannot check irrigation triggers: phase or mode not loaded.", level="DEBUG")
                return

        if self.is_irrigation_running():
            # self.log("Irrigation already running, skipping trigger check.")
            return

        if self.current_phase == P1:
            self._check_p1_irrigation()
        elif self.current_phase == P2:
            self._check_p2_irrigation()
        elif self.current_phase == P3:
            self._check_p3_irrigation()


    def is_irrigation_running(self):
        """Check if the configured pump switch is on."""
        # Use the actual pump entity from config helper
        real_pump_entity = self.get_state(self.config_helpers.get("config_pump_switch_entity"))
        if real_pump_entity:
             try:
                 return self.get_state(real_pump_entity) == 'on'
             except Exception as e:
                 self.log(f"Error getting state of real pump {real_pump_entity}: {e}", level="WARNING")
                 return False # Assume off if state cannot be read
        return False

    # --- Phase-Specific Irrigation Logic ---

    def _check_p1_irrigation(self):
        """Check and potentially trigger P1 irrigation."""
        p1_shots_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
        p1_shots = int(self.safe_float(self.get_state(p1_shots_entity_id), 0))
        max_shots = self._get_setting("p1_max_shots", 6)
        interval_minutes = self._get_setting("p1_time_between_shots", 15)

        if p1_shots >= max_shots:
            # self.log("P1 Check: Max shots reached.", level="DEBUG")
            return # Max shots reached

        # More robust interval check using a timer handle
        timer_key = 'p1_next_shot_timer'
        if not self.timer_handles.get(timer_key): # If timer isn't running, it's time for a shot
            self.log(f"P1: Triggering shot {p1_shots + 1} (timer not running).")
            self._run_p1_shot(p1_shots)
            # Schedule the next check after the interval
            if interval_minutes > 0:
                 self.timer_handles[timer_key] = self.run_in(self._p1_interval_timer_cb, interval_minutes * 60, timer_key=timer_key)
                 self.log(f"P1: Scheduled next shot check in {interval_minutes} minutes.")
        # else: # Debugging line
        #     self.log(f"P1 Check: Timer '{timer_key}' is still running. Waiting for interval.", level="DEBUG")

    def _p1_interval_timer_cb(self, kwargs):
        """Callback when the P1 interval timer fires."""
        timer_key = kwargs.get("timer_key")
        if timer_key in self.timer_handles:
            del self.timer_handles[timer_key] # Clear the handle as the timer has fired
        self.log("P1: Interval timer fired. Checking for next shot.")
        # Re-check conditions before firing next shot
        if self.current_phase == P1: # Ensure still in P1
             p1_shots_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
             p1_shots = int(self.safe_float(self.get_state(p1_shots_entity_id), 0))
             max_shots = self._get_setting("p1_max_shots", 6)
             if p1_shots < max_shots:
                 self._check_p1_irrigation() # This will run the shot and reschedule the timer
             else:
                 self.log("P1: Max shots reached after interval timer fired. No further P1 shots.")
        else:
             self.log(f"P1: Interval timer fired, but phase is now {self.current_phase}. No P1 shot.")


    def _run_p1_shot(self, current_shot_count):
        """Execute a P1 irrigation shot."""
        duration = self._calculate_shot_duration("p1")
        if duration <= 0:
            self.log("P1: Calculated shot duration is zero or less, skipping.", level="WARNING")
            return

        shot_size_percent = self._calculate_p1_current_shot_size()
        self.log(f"P1: Running shot {current_shot_count + 1}. Duration: {duration}s, Size: {shot_size_percent}%. VWC: {self.avg_vwc}%, EC: {self.avg_ec}")

        self._start_irrigation(duration)

        # Increment shot count helper *after* starting irrigation
        p1_shot_count_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
        if p1_shot_count_entity_id:
            self.call_service("input_number/set_value",
                              entity_id=p1_shot_count_entity_id,
                              value=current_shot_count + 1)


    def _check_p2_irrigation(self):
        """Check and potentially trigger P2 irrigation."""
        # Safety Check: Prevent irrigation if substrate EC is too high
        max_safe_ec = self._get_setting("substrate_max_ec", 3.5)
        if self.avg_ec is not None and self.avg_ec > max_safe_ec:
            self.log(f"P2: Irrigation SKIPPED. Average Substrate EC ({self.avg_ec} mS/cm) exceeds maximum safe level ({max_safe_ec} mS/cm).", level="WARNING")
            self._send_notification(f"P2 Irrigation Skipped: Substrate EC {self.avg_ec} > Max Safe EC {max_safe_ec}", title="Crop Steering High EC Alert")
            return

        adj_threshold = self._calculate_p2_vwc_threshold_adjusted()
        # Check if average VWC is below the adjusted threshold
        if self.avg_vwc is not None and adj_threshold is not None and self.avg_vwc < adj_threshold:
            self.log(f"P2: Triggering irrigation based on avg VWC. VWC {self.avg_vwc}% < Adjusted Threshold {adj_threshold}%.")
            self._run_p2_shot()
        # Add zone-specific check if needed, based on zone_controls logic
        elif self._check_zone_specific_trigger(P2):
             self.log(f"P2: Triggering irrigation based on specific zone VWC.")
             self._run_p2_shot()


    def _run_p2_shot(self):
        """Execute a P2 irrigation shot."""
        duration = self._calculate_shot_duration("p2")
        if duration <= 0:
            self.log("P2: Calculated shot duration is zero or less, skipping.", level="WARNING")
            return

        ec_ratio = self._get_output_sensor_state("ec_ratio", 1.0)
        adj_threshold = self._calculate_p2_vwc_threshold_adjusted()
        self.log(f"P2: Running shot. Duration: {duration}s. VWC: {self.avg_vwc}%, EC Ratio: {ec_ratio}, Adj Threshold: {adj_threshold}%")

        self._start_irrigation(duration)
        # Increment P2 shot count
        p2_shot_count_entity_id = self.input_numbers_map.get("p2_shot_count", "input_number.cs_p2_shot_count")
        if p2_shot_count_entity_id:
            p2_shots = int(self.safe_float(self.get_state(p2_shot_count_entity_id), 0))
            self.call_service("input_number/set_value",
                              entity_id=p2_shot_count_entity_id,
                              value=p2_shots + 1)


    def _check_p3_irrigation(self):
        """Check and potentially trigger P3 emergency irrigation."""
        emergency_threshold = self._get_setting("p3_emergency_vwc_threshold", 15)
        # Use MIN VWC for P3 check
        if self.min_vwc is not None and self.min_vwc < emergency_threshold:
             self.log(f"P3: Triggering EMERGENCY irrigation based on min VWC. Min VWC {self.min_vwc}% < Threshold {emergency_threshold}%.")
             self._run_p3_shot()
        # Add zone-specific check if needed
        elif self._check_zone_specific_trigger(P3):
             self.log(f"P3: Triggering EMERGENCY irrigation based on specific zone VWC.")
             self._run_p3_shot()


    def _run_p3_shot(self):
        """Execute a P3 emergency irrigation shot."""
        duration = self._calculate_shot_duration("p3_emergency")
        if duration <= 0:
            self.log("P3: Calculated emergency shot duration is zero or less, skipping.", level="WARNING")
            return

        message = f"P3: Running EMERGENCY shot. Duration: {duration}s. Min VWC: {self.min_vwc}%"
        self.log(message, level="WARNING") # Log emergency as warning
        self._send_notification(f"EMERGENCY Irrigation: {message}")
        self._start_irrigation(duration)
        # Increment P3 shot count
        p3_shot_count_entity_id = self.input_numbers_map.get("p3_shot_count", "input_number.cs_p3_shot_count")
        if p3_shot_count_entity_id:
            p3_shots = int(self.safe_float(self.get_state(p3_shot_count_entity_id), 0))
            self.call_service("input_number/set_value",
                              entity_id=p3_shot_count_entity_id,
                              value=p3_shots + 1)

    def _check_zone_specific_trigger(self, phase):
         """Check if any enabled zone needs irrigation based on its own VWC."""
         if phase == P2:
             target_vwc = self._get_output_sensor_state("dynamic_p2_dryback")
         elif phase == P3:
             target_vwc = self._get_output_sensor_state("dynamic_p3_dryback")
         else:
             return False # Only check for P2/P3

         if target_vwc is None or target_vwc == 'unknown': return False
         target_vwc = self.safe_float(target_vwc, 999)

         needs_trigger = False
         for i in range(1, 4): # Check zones 1, 2, 3
             zone_enabled_entity = self.setting_helpers.get(f"zone{i}_enabled_boolean")
             zone_vwc_entity = self.output_sensors.get(f"z{i}_vwc") # Use the AD sensor

             if zone_enabled_entity and zone_vwc_entity:
                 if self.get_state(zone_enabled_entity) == 'on':
                     zone_vwc = self.safe_float(self.get_state(zone_vwc_entity), 999)
                     if zone_vwc < target_vwc:
                         self.log(f"Zone {i} needs irrigation (VWC: {zone_vwc} < Target: {target_vwc})")
                         needs_trigger = True
                         break # Found one zone needing irrigation

         if needs_trigger:
             # Update active zones selector before starting pump
             self._update_active_zones_selector(phase)
             return True
         return False

    def _update_active_zones_selector(self, phase):
         """Update the input_select based on which zones need irrigation."""
         # Assume key 'active_zones_select' maps to input_select.cs_active_irrigation_zones in apps.yaml
         active_zones_entity_id = self.setting_helpers.get("active_zones_select", "input_select.cs_active_irrigation_zones")
         if not active_zones_entity_id:
             self.log("Active zones selector helper ('active_zones_select') not configured in apps.yaml!", level="WARNING")
             return

         if phase == P2:
             target_vwc = self._get_output_sensor_state("dynamic_p2_dryback")
         elif phase == P3:
             target_vwc = self._get_output_sensor_state("dynamic_p3_dryback")
         else: return

         if target_vwc is None or target_vwc == 'unknown': return
         target_vwc = self.safe_float(target_vwc, 999)

         needs_irrigation = [False, False, False] # Zone 1, 2, 3
         for i in range(1, 4):
             # Assume keys like 'zone1_enabled_boolean' exist in setting_helpers map
             zone_enabled_key = f"zone{i}_enabled_boolean"
             # Provide a default entity ID based on common patterns if key not found
             zone_enabled_entity_id = self.setting_helpers.get(zone_enabled_key, f"input_boolean.cs_zone_{i}_enabled") # Default added
             # Use the AppDaemon generated sensor for zone VWC
             zone_vwc_key = f"z{i}_vwc"
             zone_vwc_entity_id = self.output_sensors.get(zone_vwc_key)

             if zone_enabled_entity_id and zone_vwc_entity_id:
                 try: # Add try-except for safety when getting state
                     if self.get_state(zone_enabled_entity_id) == 'on':
                         zone_vwc = self.safe_float(self.get_state(zone_vwc_entity_id), 999)
                         if zone_vwc < target_vwc:
                             needs_irrigation[i-1] = True
                 except Exception as e:
                     self.log(f"Error checking zone {i} enabled status ({zone_enabled_entity_id}): {e}", level="WARNING")
             else:
                 # Log if expected helpers/sensors are missing
                 if not zone_enabled_entity_id: self.log(f"Setting helper key '{zone_enabled_key}' not found for zone {i}", level="WARNING")
                 if not zone_vwc_entity_id: self.log(f"Output sensor key '{zone_vwc_key}' not found for zone {i}", level="WARNING")

         option = "No Zones (Disabled)" # Default value
         # Determine the correct option string based on the boolean list
         if needs_irrigation == [True, True, True]: option = "All Zones"
         elif needs_irrigation == [True, True, False]: option = "Zones 1 & 2"
         elif needs_irrigation == [True, False, True]: option = "Zones 1 & 3"
         elif needs_irrigation == [False, True, True]: option = "Zones 2 & 3"
         elif needs_irrigation == [True, False, False]: option = "Zone 1 Only"
         elif needs_irrigation == [False, True, False]: option = "Zone 2 Only"
         elif needs_irrigation == [False, False, True]: option = "Zone 3 Only"

         # Only update if the calculated option is different from current state
         try:
             current_option = self.get_state(active_zones_entity_id)
             if current_option != option:
                 self.log(f"Setting active zones for {phase} irrigation to: {option}")
                 self.call_service("input_select/select_option", entity_id=active_zones_entity_id, option=option)
         except Exception as e:
             self.log(f"Error updating active zones selector {active_zones_entity_id}: {e}", level="ERROR")


    # --- Irrigation Control ---

    def _start_irrigation(self, duration_seconds):
        """Turns on pump, zone valves, and sets timer to turn off."""
        # Use the actual pump entity from config helper
        real_pump_entity = self.get_state(self.config_helpers.get("config_pump_switch_entity", "input_text.cs_config_pump_switch_entity"))
        if not real_pump_entity:
            self.log("Pump switch entity not configured in input_text!", level="ERROR")
            return
        if self.get_state(real_pump_entity) == 'on':
            self.log("Irrigation already running (real pump is on), cannot start another cycle.", level="WARNING")
            return

        self.log(f"Starting irrigation cycle for {duration_seconds} seconds.")

        # Cancel any existing turn-off timer
        if 'irrigation_off' in self.timer_handles:
            self.cancel_timer(self.timer_handles['irrigation_off'])
            del self.timer_handles['irrigation_off']

        # 1. Turn off waste valve (if configured)
        real_waste_switch = self.get_state(self.config_helpers.get("config_waste_switch_entity", "input_text.cs_config_waste_switch_entity"))
        if real_waste_switch:
            self.log(f"Turning off waste valve: {real_waste_switch}")
            self.call_service("switch/turn_off", entity_id=real_waste_switch)

        # 2. Turn on the main pump/valve
        self.log(f"Turning on pump: {real_pump_entity}")
        self.call_service("switch/turn_on", entity_id=real_pump_entity)

        # 3. Turn on selected zone valves based on input_booleans
        active_zone_switches = []
        # Assume key 'config_zone_switch_entities' maps to input_text.cs_config_zone_switch_entities
        zone_switch_list = self._get_entity_list_from_helper("config_zone_switch_entities", "input_text.cs_config_zone_switch_entities")

        for i in range(1, 4): # Zones 1, 2, 3
            # Assume keys like 'zone1_enabled_boolean' exist in setting_helpers map
            zone_enabled_key = f"zone{i}_enabled_boolean"
            # Provide a default entity ID based on common patterns if key not found
            zone_enabled_entity_id = self.setting_helpers.get(zone_enabled_key, f"input_boolean.cs_zone_{i}_enabled") # Default added

            if zone_enabled_entity_id:
                 try:
                     if self.get_state(zone_enabled_entity_id) == 'on' and len(zone_switch_list) >= i:
                         active_zone_switches.append(zone_switch_list[i-1]) # Use i-1 for 0-based index
                 except Exception as e:
                     self.log(f"Error checking zone {i} enabled status or switch list: {e}", level="WARNING")
            else:
                 self.log(f"Setting helper key '{zone_enabled_key}' not found for zone {i}", level="WARNING")

        if active_zone_switches:
            self.log(f"Turning on zone valves: {active_zone_switches}")
            self.call_service("switch/turn_on", entity_id=active_zone_switches)
        else:
             self.log("No zones enabled, only turning on main pump.", level="WARNING")


        # 4. Set timer to turn everything off
        self.timer_handles['irrigation_off'] = self.run_in(self._stop_irrigation, duration_seconds)
        self.update_status_outputs() # Update status immediately

    def _stop_irrigation(self, kwargs):
        """Turns off pump and all zone valves."""
        self.log("Stopping irrigation cycle.")
        if 'irrigation_off' in self.timer_handles: # Clear timer handle
             del self.timer_handles['irrigation_off']

        real_pump_entity = self.get_state(self.config_helpers.get("config_pump_switch_entity", "input_text.cs_config_pump_switch_entity"))
        zone_switch_list = self._get_entity_list_from_helper("config_zone_switch_entities", "input_text.cs_config_zone_switch_entities")

        # 1. Turn off zone valves
        if zone_switch_list:
            self.log(f"Turning off zone valves: {zone_switch_list}")
            self.call_service("switch/turn_off", entity_id=zone_switch_list)

        # 2. Turn off main pump/valve
        if real_pump_entity:
            self.log(f"Turning off pump: {real_pump_entity}")
            self.call_service("switch/turn_off", entity_id=real_pump_entity)

        self.update_status_outputs() # Update status

    def _cancel_timers(self):
         """Cancel any running timers."""
         if 'irrigation_off' in self.timer_handles:
             try:
                 self.cancel_timer(self.timer_handles['irrigation_off'])
             except: pass # Ignore if handle invalid
             del self.timer_handles['irrigation_off']
         # Cancel other timers if they are used


    # --- Calculation Functions ---

    def _calculate_shot_duration(self, shot_type):
        """Calculate shot duration in seconds based on type (p1, p2, p3_emergency)."""
        flow_rate = self._get_setting("dripper_flow_rate", 0) # L/hr
        substrate_vol = self._get_setting("substrate_volume", 0) # L

        if flow_rate <= 0 or substrate_vol <= 0:
            return 0

        if shot_type == "p1":
            shot_percent = self._calculate_p1_current_shot_size()
        elif shot_type == "p2":
            shot_percent = self._get_setting("p2_shot_size_percent", 0)
        elif shot_type == "p3_emergency":
            shot_percent = self._get_setting("p3_emergency_shot_size_percent", 0)
        else:
            return 0

        if shot_percent <= 0: return 0

        volume_to_add = substrate_vol * (shot_percent / 100.0)
        duration_hours = volume_to_add / flow_rate
        return round(duration_hours * 3600, 1)

    def _calculate_p1_current_shot_size(self):
        """Calculate the current P1 shot size percentage."""
        initial = self._get_setting("p1_initial_shot_size_percent", 0)
        increment = self._get_setting("p1_shot_size_increment_percent", 0)
        p1_shots_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
        shot_count = int(self.safe_float(self.get_state(p1_shots_entity_id), 0))
        max_size = self._get_setting("p1_max_shot_size_percent", 100)
        # Ensure max_size is respected and size is non-negative
        size_percent = max(0, min(initial + (shot_count * increment), max_size))
        return size_percent


    def _calculate_current_ec_target(self):
        """Calculate the current EC target based on phase and mode."""
        phase = self.current_phase
        mode = self.steering_mode.lower() if self.steering_mode else 'vegetative'
        if not phase: phase = P0

        # Construct the entity ID key based on mode and phase
        ec_target_key = f"ec_target_{mode}_{phase.lower()}"
        ec_target = self._get_setting(ec_target_key, None)

        if ec_target is None: # Default if specific target not found
             default_key = "ec_target_veg_p0"
             ec_target = self._get_setting(default_key, 1.6)
             # self.log(f"EC target key '{ec_target_key}' not found, using default '{default_key}': {ec_target}", level="DEBUG")

        return ec_target

    def _calculate_p2_vwc_threshold_adjusted(self, ec_ratio=None):
        """Calculate the EC-adjusted VWC threshold for P2."""
        if ec_ratio is None:
             ec_ratio = self._get_output_sensor_state("ec_ratio", 1.0)
             if ec_ratio == 'unknown': ec_ratio = 1.0 # Handle unknown state

        base_threshold = self._get_setting("p2_vwc_threshold", 25)
        ec_high_thresh = self._get_setting("p2_ec_high_threshold", 1.2)
        ec_low_thresh = self._get_setting("p2_ec_low_threshold", 0.8)
        high_adjust = self._get_setting("p2_vwc_adjustment_high_ec", 2)
        low_adjust = self._get_setting("p2_vwc_adjustment_low_ec", -2)

        # EC Stacking adjustments
        stacking_reduction = 0.0
        if self.ec_stacking_enabled and self.current_phase in self.ec_stacking_active_phases:
            stacking_target_ratio = self._get_setting("cs_ec_stacking_target_ratio", 1.5)
            # Check if current ratio is below the stacking target
            if ec_ratio is not None and ec_ratio != 'unknown' and self.safe_float(ec_ratio, 1.0) < stacking_target_ratio:
                stacking_reduction = self._get_setting("cs_ec_stacking_vwc_reduction", 1.0)
                self.log(f"EC Stacking active: Reducing VWC threshold by {stacking_reduction}% (Current Ratio: {ec_ratio}, Target Ratio: {stacking_target_ratio})", level="DEBUG")

        try:
             # Ensure ec_ratio is float before comparison
             ec_ratio_float = self.safe_float(ec_ratio, 1.0)
             adjusted_threshold = base_threshold # Start with base

             # Apply EC-based adjustments first
             if ec_ratio_float > ec_high_thresh:
                 adjusted_threshold += high_adjust
             elif ec_ratio_float < ec_low_thresh:
                 adjusted_threshold += low_adjust

             # Apply EC Stacking reduction if applicable
             adjusted_threshold -= stacking_reduction

             # Ensure threshold doesn't go below a minimum safe level (e.g., critical VWC)
             critical_vwc = self._get_setting("substrate_critical_vwc", 10) # Get critical VWC setting
             final_threshold = max(adjusted_threshold, critical_vwc) # Don't let threshold drop below critical

             if final_threshold != adjusted_threshold:
                 self.log(f"Adjusted threshold ({adjusted_threshold}%) was below critical VWC ({critical_vwc}%). Using critical VWC as threshold.", level="DEBUG")

             return round(final_threshold, 2)
        except Exception as e:
             self.log(f"Could not calculate adjusted threshold using EC Ratio '{ec_ratio}': {e}", level="WARNING")
             return round(base_threshold, 2) # Fallback to base

    def _calculate_phase_description(self):
        """Generate the friendly description for the current phase."""
        # Simplified example, add details as needed
        if self.current_phase == P0:
            time_since = self._get_output_sensor_state("minutes_since_lights_on", "?")
            return f"P0: Pre-Irrigation Dry Back ({time_since} min)"
        elif self.current_phase == P1:
             p1_shots_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
             p1_shots = self.get_state(p1_shots_entity_id) if p1_shots_entity_id else '?' # Use ? for unknown
             max_shots = self._get_setting("p1_max_shots", 6)
             return f"P1: Ramp-Up Phase (Shot {p1_shots}/{max_shots})"
        elif self.current_phase == P2:
             ec_ratio = self._get_output_sensor_state("ec_ratio", "N/A")
             return f"P2: Maintenance Phase (EC Ratio: {ec_ratio})"
        elif self.current_phase == P3:
             time_until = self._get_output_sensor_state("minutes_until_lights_off", "?")
             return f"P3: Overnight Dry Back ({time_until} min left)"
        else:
            return "Unknown Phase"

    def _calculate_irrigation_status(self):
         """Determine the current irrigation status string."""
         if self.is_irrigation_running():
             duration = 0
             if self.current_phase == P1:
                 duration = self._get_output_sensor_state("p1_shot_duration_seconds", "?") # Use updated key
                 p1_shots_entity_id = self.input_numbers_map.get("p1_shot_count", "input_number.cs_p1_shot_count")
                 p1_shots = self.get_state(p1_shots_entity_id) if p1_shots_entity_id else '?'
                 return f"Irrigating: P1 Shot {p1_shots} ({duration}s)"
             elif self.current_phase == P2:
                 duration = self._get_output_sensor_state("p2_shot_duration_seconds", "?") # Use updated key
                 return f"Irrigating: P2 Maintenance ({duration}s)"
             elif self.current_phase == P3:
                 duration = self._get_output_sensor_state("p3_emergency_shot_duration_seconds", "?") # Use updated key
                 return f"Irrigating: P3 Emergency ({duration}s)"
             else:
                 return "Irrigating" # Generic
         else:
             return "Idle"

    def _calculate_time_since_lights_on(self):
        """Calculate time since lights on in seconds. Returns None on error."""
        lights_on_entity = self.setting_helpers.get("lights_on_time")
        if not lights_on_entity: return None
        try:
            lights_on_time_str = self.get_state(lights_on_entity)
            if not lights_on_time_str: return None
            lights_on_dt = datetime.datetime.strptime(lights_on_time_str, '%H:%M:%S').time()
            now_dt = self.datetime()
            lights_on_today = now_dt.replace(hour=lights_on_dt.hour, minute=lights_on_dt.minute, second=lights_on_dt.second, microsecond=0)
            if lights_on_today > now_dt: # If lights on time is later today, it happened yesterday
                lights_on_today -= datetime.timedelta(days=1)
            return (now_dt - lights_on_today).total_seconds()
        except Exception as e:
            self.log(f"Error calculating time since lights on: {e}", level="WARNING")
            return None

    def _calculate_time_until_lights_off(self):
        """Calculate time until lights off in seconds. Returns None on error."""
        lights_off_entity = self.setting_helpers.get("lights_off_time")
        if not lights_off_entity: return None
        try:
            lights_off_time_str = self.get_state(lights_off_entity)
            if not lights_off_time_str: return None
            lights_off_dt = datetime.datetime.strptime(lights_off_time_str, '%H:%M:%S').time()
            now_dt = self.datetime()
            lights_off_today = now_dt.replace(hour=lights_off_dt.hour, minute=lights_off_dt.minute, second=lights_off_dt.second, microsecond=0)
            if lights_off_today < now_dt: # If lights off time was earlier today, target is tomorrow
                lights_off_today += datetime.timedelta(days=1)
            return (lights_off_today - now_dt).total_seconds()
        except Exception as e:
            self.log(f"Error calculating time until lights off: {e}", level="WARNING")
            return None

    def _calculate_p3_start_time_iso(self):
        """Calculate the ISO timestamp for when P3 should start today/yesterday."""
        lights_off_entity = self.setting_helpers.get("lights_off_time")
        if not lights_off_entity or not self.steering_mode: return None
        try:
            p3_start_offset = self._get_setting(f"p3_{self.steering_mode.lower()}_last_irrigation", 0)
            lights_off_time_str = self.get_state(lights_off_entity)
            if not lights_off_time_str: return None

            lights_off_dt = datetime.datetime.strptime(lights_off_time_str, '%H:%M:%S').time()
            now_dt = self.datetime()
            lights_off_today_dt = now_dt.replace(hour=lights_off_dt.hour, minute=lights_off_dt.minute, second=lights_off_dt.second, microsecond=0)

            # Calculate P3 start datetime relative to today's lights off time
            p3_start_today_dt = lights_off_today_dt - datetime.timedelta(minutes=p3_start_offset)

            # Determine if the relevant P3 start was today or yesterday
            if p3_start_today_dt > now_dt: # If P3 start is later today, the relevant one was yesterday
                p3_start_effective_dt = p3_start_today_dt - datetime.timedelta(days=1)
            else: # P3 start was earlier today
                p3_start_effective_dt = p3_start_today_dt

            return p3_start_effective_dt.isoformat()

        except Exception as e:
            self.log(f"Error calculating P3 start time ISO: {e}", level="ERROR")
            return None


    # --- Dryback Logic ---

    def detect_dryback_changes(self):
        """Detect potential VWC peaks and valleys."""
        if self.avg_vwc is None or len(self.vwc_history) < 2:
            # self.log("Dryback: Not enough VWC data", level="DEBUG")
            return # Not enough data

        current_vwc = self.avg_vwc
        # Use a simple moving average or just the last value from history
        try:
             # Ensure history contains floats
             float_history = [v for v in self.vwc_history if isinstance(v, (int, float))]
             if not float_history: return # No valid history
             previous_vwc_avg = sum(float_history) / len(float_history)
        except Exception as e:
             self.log(f"Error calculating VWC average from history: {e}", level="WARNING")
             return

        peak_threshold = self._get_setting("dryback_peak_detection_threshold", 0.5)
        valley_threshold = self._get_setting("dryback_valley_detection_threshold", 0.5)

        # Potential Peak Detection (VWC starts decreasing)
        if previous_vwc_avg > current_vwc and (previous_vwc_avg - current_vwc) > peak_threshold and not self.dryback_in_progress:
            potential_peak = round(previous_vwc_avg, 1) # Or use actual max over window
            # Only update if it's a new peak (or first peak)
            # Add check: potential peak should be higher than last valley (if exists)
            if self.dryback_last_valley_vwc is None or potential_peak > self.dryback_last_valley_vwc:
                if self.dryback_last_peak_vwc is None or potential_peak != self.dryback_last_peak_vwc:
                    self.log(f"Potential Dryback Peak detected: {potential_peak}% (Prev Avg: {previous_vwc_avg}, Curr: {current_vwc})")
                    self.dryback_potential_peak = potential_peak
                    # Record the time and value of the *actual* peak
                    self.dryback_last_peak_vwc = potential_peak
                    self.dryback_last_peak_time = self.datetime().isoformat()
                    self.dryback_in_progress = True
                    self._set_output_sensor_state("dryback_in_progress", "on", device_class="running") # Update binary sensor
                    self._set_output_sensor_state("dryback_last_peak_vwc", self.dryback_last_peak_vwc, unit="%")
                    self._set_output_sensor_state("dryback_last_peak_time", self.dryback_last_peak_time)


        # Potential Valley Detection (VWC starts increasing)
        elif previous_vwc_avg < current_vwc and (current_vwc - previous_vwc_avg) > valley_threshold and self.dryback_in_progress:
             potential_valley = round(previous_vwc_avg, 1) # Or use actual min over window
             # Only update if it's a new valley (or first valley)
             # Add check: potential valley should be lower than last peak
             if self.dryback_last_peak_vwc is not None and potential_valley < self.dryback_last_peak_vwc:
                 if self.dryback_last_valley_vwc is None or potential_valley != self.dryback_last_valley_vwc:
                     self.log(f"Potential Dryback Valley detected: {potential_valley}% (Prev Avg: {previous_vwc_avg}, Curr: {current_vwc})")
                     self.dryback_potential_valley = potential_valley
                     # Record the time and value of the *actual* valley
                     self.dryback_last_valley_vwc = potential_valley
                     self.dryback_last_valley_time = self.datetime().isoformat()
                     self.dryback_in_progress = False
                     self._set_output_sensor_state("dryback_in_progress", "off", device_class="running") # Update binary sensor
                     self._set_output_sensor_state("dryback_last_valley_vwc", self.dryback_last_valley_vwc, unit="%")
                     self._set_output_sensor_state("dryback_last_valley_time", self.dryback_last_valley_time)
                     # Calculate and record completed dryback
                     self._record_completed_dryback()


    def _update_dryback_outputs(self):
         """Update sensors related to current and last dryback."""
         current_perc = 0
         current_dur = 0
         if self.dryback_in_progress and self.dryback_last_peak_vwc is not None and self.avg_vwc is not None:
             if self.dryback_last_peak_vwc > 0:
                 perc = round(((self.dryback_last_peak_vwc - self.avg_vwc) / self.dryback_last_peak_vwc * 100), 1)
                 current_perc = max(0, perc)
             if self.dryback_last_peak_time:
                 try:
                     peak_dt = self.parse_datetime(self.dryback_last_peak_time)
                     dur_sec = (self.datetime() - peak_dt).total_seconds()
                     current_dur = round(max(0, dur_sec) / 60) # Duration in minutes
                 except Exception as e:
                     # self.log(f"Error parsing peak time for duration: {e}", level="DEBUG")
                     current_dur = 0

         self._set_output_sensor_state("dryback_current_percentage", current_perc, unit="%")
         self._set_output_sensor_state("dryback_current_duration", current_dur, unit="min")

         # Update last completed values (these are set when valley is detected)
         # These are updated in _record_completed_dryback


    def _record_completed_dryback(self):
        """Calculate stats for the completed dryback and record it."""
        if not self.dryback_last_peak_time or not self.dryback_last_valley_time:
            self.log("Cannot record dryback, missing peak or valley time.", level="DEBUG")
            return

        try:
            peak_time_dt = self.parse_datetime(self.dryback_last_peak_time)
            valley_time_dt = self.parse_datetime(self.dryback_last_valley_time)
            duration_sec = (valley_time_dt - peak_time_dt).total_seconds()
            duration_min = round(max(0, duration_sec) / 60)

            peak_vwc = self.dryback_last_peak_vwc
            valley_vwc = self.dryback_last_valley_vwc
            percentage = 0
            if peak_vwc is not None and valley_vwc is not None and peak_vwc > 0:
                 perc = round(((peak_vwc - valley_vwc) / peak_vwc * 100), 1)
                 percentage = max(0, perc)

            # Update sensors for last completed cycle
            self._set_output_sensor_state("dryback_last_percentage", percentage, unit="%")
            self._set_output_sensor_state("dryback_last_duration", duration_min, unit="min")

            # Check against minimums before logging
            min_perc = self._get_setting("dryback_min_percentage", 5)
            min_dur = self._get_setting("dryback_min_duration", 60)

            if percentage >= min_perc and duration_min >= min_dur:
                self.log(f"Logging completed dryback: {percentage}% over {duration_min}min.")
                # Append to history input_text
                # Assume key 'dryback_history_input' maps to input_text.cs_dryback_history
                history_entity_id = self.setting_helpers.get("dryback_history_input", "input_text.cs_dryback_history")
                if history_entity_id:
                    try:
                        current_history_str = self.get_state(history_entity_id)
                        # Handle empty or invalid initial state
                        if current_history_str and current_history_str.startswith('['):
                            history = json.loads(current_history_str)
                        else:
                            history = []
                    except json.JSONDecodeError:
                        self.log(f"Could not decode JSON from {history_entity_id}, starting new list.", level="WARNING")
                        history = []
                    except Exception as e:
                         self.log(f"Error getting/parsing history from {history_entity_id}: {e}", level="ERROR")
                         history = [] # Fallback to empty list

                    new_entry = {
                        'timestamp': time.time(), # Use epoch timestamp
                        'peak_time': self.dryback_last_peak_time,
                        'valley_time': self.dryback_last_valley_time,
                        'peak_vwc': peak_vwc,
                        'valley_vwc': valley_vwc,
                        'percentage': percentage,
                        'duration': duration_min,
                        'phase': self.current_phase # Log phase when valley occurred
                    }
                    history.insert(0, new_entry) # Add to beginning

                    # Prune history if it exceeds max length (e.g., 100 entries)
                    max_history_len = 100 # Make this configurable?
                    if len(history) > max_history_len:
                        history = history[:max_history_len]
                        self.log(f"Dryback history pruned to {max_history_len} entries.", level="DEBUG")

                    try:
                        # Save compact JSON to minimize storage
                        new_history_str = json.dumps(history, separators=(',', ':'))
                        # Check if new string exceeds input_text limit (255 chars)
                        if len(new_history_str) <= 255:
                            self.call_service("input_text/set_value",
                                              entity_id=history_entity_id,
                                              value=new_history_str)
                        else:
                            self.log(f"New dryback history JSON ({len(new_history_str)} chars) exceeds 255 char limit for {history_entity_id}. History not updated.", level="ERROR")
                            # Optionally, try pruning more aggressively here
                    except Exception as e:
                         self.log(f"Error setting history input_text {history_entity_id}: {e}", level="ERROR")
                else:
                    self.log("Dryback history helper ('dryback_history_input') not configured in apps.yaml!", level="WARNING")

            else:
                 self.log(f"Completed dryback ({percentage}%, {duration_min}min) did not meet minimums ({min_perc}%, {min_dur}min). Not logging.")

        except Exception as e:
            self.log(f"Error recording completed dryback: {e}", level="ERROR")


    # --- Output Sensor Handling ---

    def _set_output_sensor_state(self, sensor_key, state, unit=None, friendly_name=None, icon=None, device_class=None):
         """Set the state and attributes of an output sensor."""
         entity_id = self.output_sensors.get(sensor_key)
         if entity_id:
             attributes = {}
             # Get existing attributes to preserve friendly name etc. if already set
             try:
                 existing_attributes = self.get_state(entity_id, attribute="all")
                 if existing_attributes and 'attributes' in existing_attributes:
                     attributes.update(existing_attributes['attributes'])
             except Exception as e:
                 # self.log(f"Could not get existing attributes for {entity_id}: {e}", level="DEBUG")
                 pass # Ignore if sensor doesn't exist yet

             if unit:
                 attributes["unit_of_measurement"] = unit
             if friendly_name:
                 attributes["friendly_name"] = friendly_name
             elif "friendly_name" not in attributes: # Set default friendly name if none exists
                  attributes["friendly_name"] = f"AD CS {sensor_key.replace('_', ' ').title()}"
             if icon:
                 attributes["icon"] = icon
             elif "icon" not in attributes: # Set default icon?
                  # Add logic here to set default icons based on sensor_key if desired
                  pass
             if device_class: # For binary sensors
                 attributes["device_class"] = device_class

             # self.log(f"Setting state for {entity_id}: {state}, Attrs: {attributes}")
             try:
                 # Check if state is significantly different before setting? (Optional)
                 # current_state = self.get_state(entity_id)
                 # if str(current_state) != str(state): # Basic check
                 self.set_state(entity_id, state=state, attributes=attributes)
             except Exception as e:
                 self.log(f"Error setting state for {entity_id}: {e}", level="ERROR")


    def _get_output_sensor_state(self, sensor_key, default=None):
         """Get the state of an output sensor managed by this app."""
         entity_id = self.output_sensors.get(sensor_key)
         if entity_id:
             state = self.get_state(entity_id)
             # Return default if state is None or unknown?
             # return state if state not in [None, 'unknown', 'unavailable'] else default
             return state if state is not None else default # Return None if that's the actual state
         return default

    def _send_notification(self, message, title="Crop Steering Alert"):
        """Send notification if service is configured."""
        if self.notification_service:
            try:
                self.call_service(self.notification_service.replace('.', '/'), title=title, message=message)
                self.log(f"Sent notification: {title} - {message}", level="DEBUG")
            except Exception as e:
                self.log(f"Error sending notification via {self.notification_service}: {e}", level="ERROR")
        else:
            self.log("Notification service not configured in apps.yaml.", level="DEBUG")


    # --- Utility ---
    def safe_float(self, value, default=0.0):
        """Safely convert value to float."""
        if value is None: return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
