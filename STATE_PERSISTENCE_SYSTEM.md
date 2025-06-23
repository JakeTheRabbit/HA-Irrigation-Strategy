# State Persistence System for AppDaemon Restarts

## Problem Addressed

**Before Implementation:**
When AppDaemon restarted, the crop steering system would:
- ❌ Reset all zones to P2 (maintenance phase)
- ❌ Lose P0 dryback timing and peak VWC data
- ❌ Reset daily/weekly water usage to 0
- ❌ Lose last irrigation times
- ❌ Lose ML training progress
- ❌ Reset phase transition context

**This caused major issues:**
- Plants could get emergency irrigation when they didn't need it
- Water usage tracking would reset mid-day
- P0 dryback calculations would be invalid
- System would lose knowledge of recent irrigation events

## Solution Implemented

### 1. Persistent State File
**Location:** `/config/crop_steering_state.json`
**Format:** JSON for human readability and debugging
**Saves:** Every 5 minutes + after critical events

### 2. Critical Data Saved
```json
{
  "timestamp": "2024-01-15T14:32:00.123456",
  "version": "2.1.0",
  "zone_phases": {
    "1": "P1",
    "2": "P2", 
    "3": "P0",
    "4": "P3"
  },
  "zone_phase_data": {
    "1": {
      "p0_start_time": "2024-01-15T12:00:00.000000",
      "p0_peak_vwc": 68.5,
      "last_irrigation_time": "2024-01-15T14:30:00.000000"
    }
  },
  "zone_water_usage": {
    "1": {
      "daily_total": 12.5,
      "weekly_total": 85.2,
      "daily_count": 5,
      "last_reset_daily": "2024-01-15",
      "last_reset_weekly": "2024-01-13"
    }
  },
  "last_irrigation_time": "2024-01-15T14:30:00.000000"
}
```

### 3. Smart State Recovery

#### A. File-Based Recovery (Primary)
- Loads complete state from JSON file
- Validates timestamps and data integrity
- Handles version compatibility

#### B. HA Sensor Fallback (Secondary)
- If file missing/corrupt, reads from HA sensors
- Gets zone phases from `sensor.crop_steering_zone_X_phase`
- Reconstructs basic state from available data

#### C. Intelligent Validation (Tertiary)
- Checks if restored state makes logical sense
- Examples:
  - Lights off but zone in P2 → Fix to P0
  - Zone in P0 for >2 hours with lights on → Move to P1
  - Water usage from wrong date → Reset counters

### 4. Auto-Save Triggers

#### Periodic Save (Every 5 minutes)
```python
self.run_every(self._save_persistent_state, 'now+60', 300)
```

#### Critical Event Saves (Immediate)
- **After irrigation completion** - Preserves water usage and timing
- **After phase transitions** - Preserves zone states
- **Before system shutdown** (if possible)

## Recovery Process Flow

```
AppDaemon Restart
       ↓
1. Initialize defaults
       ↓
2. Try load state file → Success? → Restore & validate
       ↓                      ↓
3. File missing/corrupt   State validated
       ↓                      ↓
4. Try HA sensor fallback → Recovery complete
       ↓
5. Intelligent validation
       ↓
6. System ready with restored state
```

## Benefits After Implementation

### ✅ **Seamless Restarts**
- Zones maintain correct phases
- Water tracking continues accurately
- No false emergency irrigation
- P0 dryback calculations remain valid

### ✅ **Data Integrity**
- Daily water usage preserved mid-day
- Weekly totals continue across restarts
- Last irrigation times remembered
- ML learning progress maintained

### ✅ **Smart Recovery**
- Multiple fallback mechanisms
- Validates restored data for consistency
- Handles version changes gracefully
- Self-corrects impossible states

### ✅ **Downtime Tracking**
```
🔄 System recovered after 45 seconds of downtime
```

## Example Recovery Logs

```
📂 Loading state from version 2.1.0
✅ Restored zone phases: {1: 'P1', 2: 'P2', 3: 'P0', 4: 'P3'}
✅ Restored zone phase data for 4 zones
✅ Restored water usage for 4 zones
✅ Restored last irrigation time: 2024-01-15 14:30:00
🔧 Zone 3: Lights on and long P0 duration, moving to P1
✅ State validation complete
🔄 System recovered after 45 seconds of downtime
```

## File Maintenance

### Automatic Cleanup
- Version compatibility checks
- Handles corrupted files gracefully
- Self-heals from inconsistent states

### Manual Management
```bash
# View current state
cat /config/crop_steering_state.json

# Backup state
cp /config/crop_steering_state.json /config/crop_steering_state_backup.json

# Reset state (forces defaults)
rm /config/crop_steering_state.json
```

## Error Handling

### File Corruption
- JSON parse errors → Falls back to HA sensors
- Missing fields → Uses defaults for missing data
- Invalid dates → Resets affected counters

### HA Sensor Unavailable
- Missing phase sensors → Uses P2 default
- Invalid phase values → Validates and corrects
- No sensor data → Smart guessing based on time

### Version Incompatibility
- Older versions → Migrates data format
- Newer versions → Uses compatible subset
- Unknown versions → Treats as defaults

## Implementation Impact

**Before:** 🚨 System blind after restart, potential plant stress
**After:** 🎯 Seamless operation, <1 minute to full recovery

The state persistence system ensures the crop steering system is truly production-ready for commercial operations where uptime and data integrity are critical.