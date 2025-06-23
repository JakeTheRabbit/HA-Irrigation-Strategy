# Per-Zone Phase Transition Implementation Summary

## Key Changes Implemented

### 1. Per-Zone Phase Tracking
- Each zone now operates independently through P0→P1→P2→P3 cycles
- Added `zone_phases` dictionary to track each zone's current phase
- Added `zone_phase_data` to track zone-specific data (P0 start time, peak VWC, last irrigation time)

### 2. P3 Logic Corrected
- P3 is now correctly implemented as the final dryback period AFTER the last P2 irrigation
- P3 only irrigates in true emergencies (VWC < 35% critical threshold)
- Normal P3 operation allows dryback without irrigation

### 3. ML-Based P3 Timing
The `_should_zone_start_p3` method implements intelligent P3 timing:
- Uses ML-predicted dryback rate per zone
- Calculates hours needed to achieve target dryback by morning
- Starts P3 when: `hours_until_lights_on <= hours_needed_for_dryback`
- Also checks if zone just received its final P2 irrigation

### 4. Zone-Specific Last Irrigation Tracking
- Updated `_execute_irrigation_shot` to record last irrigation time per zone
- Used in P3 timing logic to determine if zone won't need water again before morning

## Phase Transition Logic Per Zone

### P3 → P0 (Lights Off)
- Trigger: When lights turn off (12am)
- All zones transition to P0 simultaneously
- Records peak VWC for dryback calculations

### P0 → P1 (Dryback Complete)
- Trigger: Zone achieves dryback target OR safety timeout
- Each zone transitions independently
- Primary: `((peak_vwc - current_vwc) / peak_vwc) * 100 >= dryback_target`
- Safety: `elapsed_time >= p0_max_wait_time`

### P1 → P2 (Recovery Complete)
- Trigger: Zone VWC reaches recovery target
- Each zone transitions independently
- Condition: `zone_vwc >= p1_target_vwc`

### P2 → P3 (Start Final Dryback)
- Trigger: ML-predicted optimal timing OR just completed final P2 irrigation
- Each zone transitions independently based on:
  1. ML prediction: Time needed to achieve target dryback by morning
  2. Post-irrigation check: Zone won't need water again before lights off

## Irrigation Logic Per Phase

### P0 (Night Dryback)
- No irrigation - letting substrate dry

### P1 (Ramp-Up)
- Irrigate when: `zone_vwc < (p1_target_vwc × 0.9)`
- Small shots to gradually rehydrate

### P2 (Maintenance)
- Irrigate when: `zone_vwc < p2_vwc_threshold`
- Standard maintenance shots

### P3 (Final Dryback)
- Normal: No irrigation - controlled dryback to morning
- Emergency only: `zone_vwc < 35%` (critical wilting threshold)

## Key Benefits
1. Each zone optimizes independently based on its specific conditions
2. No wasted water on zones that don't need it
3. ML learns each zone's behavior separately
4. P3 timing adapts to achieve perfect morning dryback per zone