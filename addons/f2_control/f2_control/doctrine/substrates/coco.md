## Substrate table for this install
Selected by the install's substrate option. 'generic' is the default for a fresh install: relative-only, no absolute moisture bands. Numbers are starting ranges (SUB-01), never limits; the engine's own bounds and the envelope still apply.

### Substrate `coco`: Coco coir (pots, bags, pre-filled blocks) (VND-IRRIGATION, VND-COCO, GL-COCO, ABAD2005, NOGUERA2003)

Basis: Vendor coco guidance states drybacks as RELATIVE % of peak. The overnight bands are compared with the zone's observed overnight dryback (code computes it from the zone's own peak); they are not values for dryback_target. The after-lights-on figure (1-5 %) is the morning drop that P0's dryback_target is compared with (DRY-02).

- **properties**: air_at_fc_pct about 20-30; buffer moderate cation exchange; holds Ca/Mg until charged; input_ph 5.8-6.2; prep pre-buffer with a Ca/Mg feed unless sold pre-buffered; hydrate pre-buffered coco with feed from the first wetting
- **shots**: p1_shot_pct_of_substrate 2-6; p1_spacing_min 15-30; first_shot_after_lights_on_min 30-120
- **dryback_relative**: overnight_vegetative 30-40; overnight_generative 40-50; after_lights_on_additional 1-5
- **pore_ec_by_stage**: veg 3-5; veg_building_to_flip 4-5; stretch 4-10; bulk 3.5-6; finish 3-4
- **runoff_pct**: vegetative 8-16; generative 1-7
- **caution**: Coco buffers salt, so pore EC climbs more gently than in rockwool; the practitioner guide warns beginners off running rockwool-level pore EC in coco. Start at the low end of each vendor band and move up on the zone's own response.

Start up:
- Wet the dry medium slowly with small shots until a little runoff (about 2%) appears; that is field capacity.
- Vendor start-up runs young plants on the ramp and overnight only, adding maintenance shots once the daily dryback passes about 25% relative. The engine cannot do this: it always runs P2 after the ramp. The nearest lever is a lower P2 threshold, never turning P2 off (RMP-10).
- Expect roughly half the peak to dry back over the first few days after transplant before the next full irrigation (vendor figure; the engine tops up in P2 whenever VWC falls below the threshold, so it cannot wait for this, RMP-10).

| See | Cause | Do |
|---|---|---|
| EC climbing daily, plant sulking | salt build-up, too hard a dryback or too little flush | bigger P2 shots; slow feed-EC trim (advice) |
| VWC barely drops all day | over-watering or the plant not drinking (cold, dark, sick) | fewer or smaller shots; check roots, temperature, light |
| early Ca/Mg spotting | unbuffered coco | pre-charge; Ca/Mg in early feeds (advice) |
| wilting between shots | dryback has become drought | water sooner; smaller dryback |

### Doctrine for coco only
SUB-04 [research] Coco keeps roughly a fifth to a third of its volume as air at field capacity, so it is hard to drown; its exchange capacity buffers feed swings but holds back calcium and magnesium until charged (unless sold pre-buffered). (ABAD2005, NOGUERA2003, GL-COCO, VND-COCO)
