## Title: Refactor AppDaemon modules to fix async/await issues and restore sensor fusion

## Description

The current AppDaemon implementation has critical async/await issues causing runtime warnings and preventing proper entity state access. Additionally, the sensor fusion module is bypassed due to mixing VWC and EC values. This refactoring will fix these core issues to make the system more reliable.

## Current Problems

1. **Async/Await Issues**
   - `RuntimeWarning: coroutine 'State.get_state' was never awaited`
   - Entity states return Task objects instead of values
   - Causes cascading failures throughout the system

2. **Sensor Fusion Bypass**
   - Module mixes VWC (0-100%) and EC (0-10 mS/cm) values incorrectly
   - Currently bypassed with hardcoded fallback values
   - Reduces system accuracy and reliability

3. **Complex State Management**
   - Phase logic scattered across multiple methods
   - Difficult to debug phase transitions
   - No clear state machine pattern

## Proposed Solutions

### 1. Async-Safe Entity Access (Week 1)
```python
# Create proper async wrappers
async def _get_entity_state(self, entity_id, attribute=None):
    """Safely get entity state with proper async handling."""
    try:
        if attribute:
            return await self.get_state(entity_id, attribute=attribute)
        return await self.get_state(entity_id)
    except Exception as e:
        self.log(f"Error getting state for {entity_id}: {e}")
        return None
```

### 2. Fix Sensor Fusion (Week 2)
- Separate VWC and EC sensor processing
- Implement proper validation ranges
- Restore weighted averaging functionality

### 3. Implement Phase State Machine (Week 3)
- Centralize phase transition logic
- Clear state management per zone
- Easier debugging and testing

## Success Criteria

- [ ] No more async/await runtime warnings in logs
- [ ] Entity states return actual values, not Task objects
- [ ] Sensor fusion actively processing readings (not bypassed)
- [ ] Clean phase transitions with clear logging
- [ ] All existing functionality preserved

## Implementation Plan

**Phase 1 (High Priority)**: Fix async/await in master_crop_steering_app.py
- Estimated time: 1 week
- Risk: Low (internal refactoring only)

**Phase 2 (Medium Priority)**: Restore sensor fusion functionality  
- Estimated time: 1 week
- Risk: Medium (affects sensor readings)

**Phase 3 (Low Priority)**: Implement state machine pattern
- Estimated time: 1 week
- Risk: Low (improves code organization)

## Testing Requirements

- [ ] Test with actual Home Assistant + AppDaemon setup
- [ ] Verify no async warnings in logs
- [ ] Confirm sensor readings are properly fused
- [ ] Validate all phase transitions work correctly
- [ ] Check backwards compatibility with existing configs

## Additional Context

This refactoring focuses on fixing core architectural issues without changing external behavior. The system will work identically from a user perspective but with much better reliability and maintainability.

**Note**: This is achievable within a month with focused effort on one module at a time.

## Labels
- `refactoring`
- `bug`
- `enhancement`
- `appdaemon`