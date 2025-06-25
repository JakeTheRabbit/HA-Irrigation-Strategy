# Refactoring Proposal: Fix Async/Await Issues and Simplify Entity Access

## Problem Statement

The current AppDaemon implementation has critical issues with async/await patterns causing:
- Runtime warnings: `coroutine 'State.get_state' was never awaited`
- Entity states returning async Tasks instead of values
- Sensor fusion module bypassed due to mixing VWC/EC values
- Complex fallback logic throughout the codebase

## Proposed Solution

### Phase 1: Fix Async Entity Access (Priority: Critical)

**Current Problem:**
```python
# Returns Task object instead of value
state = self.get_state(entity_id)  
# Results in: <Task pending name='Task-1313' coro=<ADAPI.get_state()...>
```

**Proposed Fix:**
```python
# Create async-safe wrapper methods
async def _get_entity_state(self, entity_id, attribute=None):
    """Safely get entity state with proper async handling."""
    try:
        if attribute:
            return await self.get_state(entity_id, attribute=attribute)
        return await self.get_state(entity_id)
    except Exception as e:
        self.log(f"Error getting state for {entity_id}: {e}")
        return None

# Use in sync context with run_coroutine_threadsafe
def get_entity_value(self, entity_id, default=None):
    """Synchronous wrapper for entity access."""
    try:
        future = asyncio.run_coroutine_threadsafe(
            self._get_entity_state(entity_id),
            self.AD.loop
        )
        result = future.result(timeout=1.0)
        return result if result is not None else default
    except Exception:
        return default
```

### Phase 2: Fix Sensor Fusion Module

**Current Problem:**
- Mixing VWC and EC values in fusion calculations
- Bypassed with hardcoded metadata

**Proposed Fix:**
```python
class SensorFusion:
    def __init__(self):
        self.vwc_sensors = {}
        self.ec_sensors = {}
    
    def add_vwc_reading(self, sensor_id, value, timestamp):
        """Separate VWC sensor handling."""
        # Validate VWC range (0-100%)
        if 0 <= value <= 100:
            self.vwc_sensors[sensor_id] = {
                'value': value,
                'timestamp': timestamp,
                'reliability': self._calculate_reliability(sensor_id, value)
            }
    
    def add_ec_reading(self, sensor_id, value, timestamp):
        """Separate EC sensor handling."""
        # Validate EC range (0-10 mS/cm typical)
        if 0 <= value <= 10:
            self.ec_sensors[sensor_id] = {
                'value': value,
                'timestamp': timestamp,
                'reliability': self._calculate_reliability(sensor_id, value)
            }
    
    def get_fused_vwc(self):
        """Get weighted average of VWC sensors only."""
        return self._weighted_average(self.vwc_sensors)
    
    def get_fused_ec(self):
        """Get weighted average of EC sensors only."""
        return self._weighted_average(self.ec_sensors)
```

### Phase 3: Simplify Phase State Management

**Current Problem:**
- Phase logic scattered across multiple methods
- Complex nested conditions

**Proposed Fix:**
```python
class PhaseStateMachine:
    """Centralized phase management per zone."""
    
    def __init__(self, zone_id):
        self.zone_id = zone_id
        self.current_phase = "P0"
        self.phase_data = {}
        
    def transition_to(self, new_phase, reason=""):
        """Single point for phase transitions."""
        old_phase = self.current_phase
        self.current_phase = new_phase
        self.phase_data[new_phase] = {
            'entered': datetime.now(),
            'from_phase': old_phase,
            'reason': reason
        }
        return True
    
    def should_transition(self, sensor_data, light_state, config):
        """Centralized transition logic."""
        transitions = {
            'P0': self._check_p0_exit,
            'P1': self._check_p1_exit,
            'P2': self._check_p2_exit,
            'P3': self._check_p3_exit
        }
        return transitions[self.current_phase](sensor_data, light_state, config)
```

### Phase 4: Consolidate Configuration Access

**Current Problem:**
- Configuration spread across env file, HA entities, and hardcoded values

**Proposed Fix:**
```python
class ConfigurationManager:
    """Single source of truth for all configuration."""
    
    def __init__(self, hass, env_file):
        self.hass = hass
        self.env_config = self._load_env_file(env_file)
        self.cache = {}
        self.cache_timeout = 60  # seconds
        
    def get_parameter(self, param_name, zone_id=None):
        """Get parameter with fallback chain."""
        # 1. Check HA entity first
        entity_value = self._get_from_entity(param_name, zone_id)
        if entity_value is not None:
            return entity_value
            
        # 2. Check env file
        env_value = self._get_from_env(param_name, zone_id)
        if env_value is not None:
            return env_value
            
        # 3. Return hardcoded default
        return self._get_default(param_name)
```

## Implementation Plan

1. **Week 1**: Fix async/await issues in master_crop_steering_app.py ✅ COMPLETED
2. **Week 2**: Refactor sensor fusion to properly separate VWC/EC ✅ COMPLETED
3. **Week 3**: Implement PhaseStateMachine for cleaner phase logic ✅ COMPLETED
4. **Week 4**: Create ConfigurationManager for unified config access

## Progress Update

### Phase 1: Async/Await Fixes ✅ COMPLETED

**What was done:**
1. Created `BaseAsyncApp` class following AppDaemon best practices
   - Implements thread-safe entity access with `get_entity_value()` and `set_entity_value()`
   - Provides async variants for use in async callbacks
   - Includes entity caching for performance
   - Handles Task object detection and fallback

2. Refactored `master_crop_steering_app.py` to inherit from `BaseAsyncApp`
   - Replaced all `self.get_state()` with `self.get_entity_value()`
   - Replaced all sync `self.set_state()` with `self.set_entity_value()`
   - Updated async methods to use `await self.async_set_entity_value()`
   - Maintained all existing functionality while fixing async issues

**Key learnings from AppDaemon documentation:**
- AppDaemon already handles async internally for most operations
- It's "almost never" advantageous to use async in AppDaemon apps
- Use `self.create_task()` instead of `asyncio.create_task()`
- Direct state access works fine in sync contexts
- Task objects indicate async context mismatch

### Phase 2: Sensor Fusion Fixes ✅ COMPLETED

**What was done:**
1. Fixed sensor type tracking in `IntelligentSensorFusion`
   - Added `sensor_types` dictionary to track VWC vs EC sensors
   - Modified `add_reading()` to store sensor type
   - Updated `_perform_sensor_fusion()` to only fuse sensors of same type

2. Added proper validation ranges
   - VWC sensors: 0-100% (percentage of water content)
   - EC sensors: 0-20 mS/cm (electrical conductivity)
   - Range validation in `_detect_outlier()` method

3. Created type-specific fusion methods
   - `get_fused_vwc()` - Returns fused VWC value only
   - `get_fused_ec()` - Returns fused EC value only
   - `get_sensor_count_by_type()` - Count active sensors by type

4. Updated master app to use sensor fusion properly
   - Removed bypass code that was using raw values
   - Now properly marks sensors as 'vwc' or 'ec' type
   - Uses fused values with fallback to simple average

**Key improvements:**
- No more mixing of VWC (0-100%) and EC (0-10 mS/cm) values
- Proper statistical fusion within sensor types
- Maintains sensor reliability and outlier detection
- Clear separation of concerns

### Phase 3: Phase State Machine Implementation ✅ COMPLETED

**What was done:**
1. Created `phase_state_machine.py` module
   - Enum-based phase definitions (P0_MORNING_DRYBACK, P1_RAMP_UP, etc.)
   - Clean state transitions with validation
   - Per-zone state tracking with dedicated data classes
   - Thread-safe operation with proper locking

2. Implemented structured phase data
   - `P0Data`: Peak VWC, dryback percentage, max duration tracking
   - `P1Data`: Shot history, progressive sizing, VWC recovery tracking
   - `P2Data`: Field capacity, irrigation count, EC/VWC trends
   - `P3Data`: Emergency shot tracking, overnight dryback predictions

3. Integrated state machines into master app
   - Replaced zone_phases/zone_phase_data dictionaries with ZoneStateMachine instances
   - Added backward compatibility properties for existing code
   - Updated phase transition logic to use state machine transitions
   - Added automatic phase checking in irrigation decision loop

4. Implemented phase callbacks
   - On-enter callbacks for phase initialization
   - On-exit callbacks for cleanup
   - Transition callbacks for specific phase changes
   - Proper logging of all state changes

**Key improvements:**
- Centralized phase logic in one place
- Clear state transitions with validation
- Better debugging with comprehensive state tracking
- Type-safe phase handling with enums
- Maintains backward compatibility

## Benefits

- Eliminate runtime warnings and async errors
- Restore sensor fusion functionality
- Cleaner, more maintainable code
- Easier to debug and extend
- Better separation of concerns

## Testing Requirements

- Test with actual Home Assistant instance
- Verify all entity state access works correctly
- Confirm sensor fusion produces accurate results
- Validate phase transitions occur at correct times
- Check configuration fallback chain works properly

## Backwards Compatibility

- All existing configuration files remain valid
- Entity names unchanged
- External behavior identical (just internal cleanup)