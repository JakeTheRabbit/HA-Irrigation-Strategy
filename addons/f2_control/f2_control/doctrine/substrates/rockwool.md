## Substrate table for this install
Selected by the install's substrate option. 'generic' is the default for a fresh install: relative-only, no absolute moisture bands. Numbers are starting ranges (SUB-01), never limits; the engine's own bounds and the envelope still apply.

### Substrate `rockwool`: Stone wool slabs and blocks (GL-ROCKWOOL, GL-SLAB, GL-LAW, VND-IRRIGATION)

Basis: Moisture numbers are TRUE water content; a probe may read far from them until calibrated to the slab (PRB-07). Compare via the zone's own peak. Dryback bands are the daily and overnight dryback, compared with the zone's observed dryback, never values for dryback_target (DRY-02).

- **properties**: air_when_soaked_pct about 10; buffer almost none (what you feed is what roots get); input_ph 5.5-6; prep starts alkaline; condition before planting; root_zone_temp_c 20-26
- **moisture_true_wc**: working_band_pct 55-92; full_mark learned per slab from about 5 agreeing waterings; recovery_floor_pct 25-30
- **shots**: p1_shot_pct_of_substrate 2-6; p1_shot_common_pct 3-5; p1_spacing_min 15-30; lift_per_shot_points 2-5
- **dryback_points**: vegetative 5-15; generative 20-30; young_plants 5-10; overnight_adds 5-15
- **pore_ec**: leafy_growth about 3.0; flower 4.5-6; healthy_daily_range 2-6; note a feed near 3 can read above 5 in the block by late afternoon
- **runoff_pct**: general 10-20; vegetative_vendor 8-16; generative_vendor 1-7

| See | Cause | Do |
|---|---|---|
| runoff high but moisture hardly climbs | water bypassing the block (channels, a dry centre, a badly seated block) | check the block, feed more slowly or rewet by hand; do not add volume |
| pore EC climbing day over day | too little runoff | bigger or more P2 shots |
| EC rising right after a flush | salt front still passing | flush more |
| EC below target | over-flushing | cut shot size, or let the zone dry further between shots |
| ramp stalls short of the P1 target | a target above what the block can hold, a blocked dripper, or not enough ramp shots | run a catch test and find the real achievable peak |
| zones uneven | emitter flow or placement | catch-test near/mid/far, flush lines |

### Doctrine for rockwool only
RMP-03 [grower-practice] Each shot should lift water content roughly 2-5 points: enough for the probe to register, not so much that it drains straight out. (GL-ROCKWOOL)
PRB-11 [vendor] In rockwool, insert rods horizontally at mid-height of the slab beside a middle block (not under it), housing flush, no air gaps, clear of drain holes and ends; in a block, low in the block. (GL-ROCKWOOL, VND-IRRIGATION)
SUB-03 [grower-practice] Rockwool holds almost no nutrient buffer and only about a tenth air when soaked, so what is fed is what the roots get within the hour and mistakes show fast. (GL-LAW, GL-ROCKWOOL)
SUB-07 [grower-practice] A block and its slab exchange water only through their contact face: no plastic bridging it. A transplant stalling on a wet slab usually has a dry or out-of-contact block. (GL-SLAB)
