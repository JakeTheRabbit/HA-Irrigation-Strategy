# Scene catalogue

Generated from each scene's `doc`. See src/scenes/<Name>.tsx `example` for exact props.

## AckReceipt

Save configuration is posting a letter; Mapping acknowledged is the receipt. Left: a Home Assistant 'Crop Steering setup' screen showing the revision; a cursor clicks Save configuration and an envelope stamped with the revision arcs over to the Controller box (which shows a live heartbeat — 'alive' — the whole time). The Controller reads it, then (acknowledged) a green ACK receipt flies back and the screen's status turns 'Mapping acknowledged · rev N'; or (not acknowledged) no receipt comes, the return route pulses amber with a '?', status reads 'Saved · waiting for receipt' with an hourglass and the chip says 'No receipt yet: keep Watering OFF'. props: {showRevision?:true (false hides the revision number everywhere: screen row, envelope seal, receipt, status texts), revision?:12, acknowledged?:true}. steps: [Save pressed, letter arrives at Controller, receipt returns (or waiting state shown)].

## Analogy

Two-card "this is like that" analogy: left an everyday object, right the crop-steering idea, a drawn arrow ("is like") between, and optional mapping rows (left term → right term) underneath. Every icon is a live flat SVG drawing with gentle motion. Icons (either side): ${ICONS}. ('contact' = phone showing a contact, 'phone-contact' = same phone ringing, 'person' = waving person, 'handover' = two people passing a clipboard, 'lightswitch' = bulb + ON/OFF switch, 'trolley' = shopping trolley, 'pot' = mini cut-away pot with plant, 'probe' = substrate block with probe + glowing sensing zone, 'zone' = three pots on one drip line, 'setting' = slider with a % value, 'ec' = water drop with salt crystals, 'graph' = dryback saw-tooth, 'app' = screen with a drawing chart line (its corner text comes from value, e.g. 'VWC'; none by default).) props: {left:{icon,label,value?,gauge?}, right:{icon,label,value?,gauge?}, (value?: text shown on number icons — thermometer (no number unless given, e.g. '22°'), setting (default animated %), postit (default '60%'), bank (default '$'), dashboard (default 'km/h'); gauge?: dashboard only, 'speed' (default speedometer) | 'fuel' (E→F fuel gauge)), mappings?:[{from,to}] (max 3, keep each under ~30 chars), joiner?:'is like'}. steps: [left card, right card + arrow, then one per mapping].

## BlendSlider

Steering slider as a dimmer: vegetative endpoint card (leafy plant) on the left, generative endpoint card (flowering plant) on the right, a 0–100 track with a knob and a live value bubble that counts as the knob glides; the blend formula 'a + (b − a) × fraction = result' and its four steps appear when the knob settles. props: {label:'Maximum wait', unit:'min', a:30 (vegetative), b:50 (generative), positions:[50,25,75]}. steps: one per position — the knob moves to positions[i] at steps[i] (starts at 0).

## Calc

Step-by-step worked calculation. props: {heading?, lines:[{expr:'60 − 45 = 15', note?:'percentage points'}], answer?}. steps: one spoken phrase per line, then one for the answer.

## CalendarPlan

Calendar grid of grow days for one zone: profile cards are dragged from a tray onto day ranges (blocks fill day by day; uncovered days turn red-dashed once saved), then a SAVED·still a draft stamp, then Arm plan with a clock counting the hours to next lights-on, then Active (grid glows, today dot). A separate Watering switch card stays on throughout ('Arming never touches it'). props: {zone?:'Zone 1', zones?:[{name:'Zone A', start?:1}] (optional, 2–3 zones sharing the same profile blocks: each zone gets its own lane inside every day cell, labelled 'Zone A · Bulk'; start = the day that zone's block day 1 lands on, default 1, so a later-planted zone is shifted right; header reads 'Zone A + Zone B · grow plan'; omit for the single-zone default), days?:14 (7–21), blocks:[{days:[1,7], label:'Early flower'}] (max 5), stages?:['assign','save','arm','active'] (any ordered subset), armAt?:'15:00', lightsOn?:'06:00'}. steps: one per stage, in stages order (blocks share the assign step, dragged one after another).

## CatchTest

Commissioning catch test: supply → riser → three zone valves; zone 1's valve opens, water runs through its drippers into separate catch cups while a stopwatch times the run and each cup counts up in mL; the other zones get green 'dry' ticks; the valve closes and an eye checks the outlet ('water stopped ✓'); a card converts each cup mL → L/h (mL ÷ 1000 × 3600 ÷ s) and flags uneven delivery. props: {cups:[30,33,37], seconds:30, otherZonesDry?:true, showStop?:true, decimals?:2 (L/h decimals; 1 gives '3.6')}. steps: [valve opens / run starts, other zones stay dry, valve closes + stop check (run ends here), convert cups to L/h].

## Checklist

Clipboard checklist; each item is ticked as it is spoken (green ✓), or marked amber ? (state 'unknown') or red × (state 'fail'); a tally on the right counts confirmed / unknown / failed. props: {title, items:[{text, state?:'ok'|'unknown'|'fail'}]} (max 7; rows and font auto-shrink so long items wrap and still fit the clipboard). The tally counts each item the moment its mark appears. steps: one spoken phrase per item.

## Compare

Two columns side by side (Measured vs Reference, Budget vs Statement, Do vs Don't, Saved vs Draft) with a pulsing 'vs' badge; items slide in as spoken; optional verdict banner lands last. props: {left:{title, icon? (built-in name or emoji; other scenes' icon names like setting/probe/pot/app/graph/zone map to the nearest built-in, any other unknown word shows a neutral note icon), tone?:'good'|'bad'|'warn'|'water'|'neutral'|'ec', items:[string ≤40 chars] (max 5)}, right:{same}, verdict? (≤70 chars), order?:'columns'(default: all left, then all right)|'pairs'(left1,right1,left2…)}. tone good/bad gives ✓/× bullets. steps: one per item in that order, then one for the verdict.

## DayGraph

The main root-zone chart. Time axis left→right, shaded night band with moon (day gets a sun; when the graph starts/ends near lights-off the narrow day stretch drops its label so labels never overlap), blue VWC line (% on left axis) drawn progressively, optional orange EC line (mS/cm on right axis), shot event markers (filled dots; `held` = rings), dashed planning reference vs solid measured line, horizontal threshold lines that can slide from value to `to` while the measured line stays put, optional highlight bubble with read-across guides, optional 'now' marker and hatched missing-data gap (white-backed grey hatching + dashed edges, visible over night shading). props: {hours?:24, start?:0 (clock hour at the left edge; hours below start wrap to next day, e.g. 30 = 06:00 tomorrow), nightFrom?, nightTo?, vwc:[[h,v]...], vwc2?:[[h,v]...] (second VWC line, green dotted, drawn with the first), vwc2Label?:'VWC · second' (its legend text), ec?:[[h,v]...], ecName?:'Bulk EC', ecPlan?:[[h,v]...] (dashed orange EC plan line on the EC axis, legend 'EC plan', drawn with the plan step), plan?:[[h,v]...], shots?:[h...], held?:[h...], thresholds?:[{label, value, to?, axis?:'vwc'|'ec', showValue?:boolean (append ' · value%' to the pill; default true unless the label already contains the number)}] (pills that would overlap are stacked apart automatically), highlight?:{h, text, line?:'vwc'|'ec'}, gap?:[h1,h2], now?:h, vwcRange?:[lo,hi], ecRange?:[lo,hi]}. steps: [axes, VWC line, EC line, shot markers, plan line, threshold appears, threshold moves to `to`, highlight].

## DecisionTree

Troubleshooting flow, auto-laid-out top to bottom (tidy tree from the edges). Questions (? badge), actions (wrench) and stop nodes (red, e.g. 'Physical shutdown first'); a gold token runs down each edge of the spoken path and lights the next node; other branches dim at the end. props: {nodes:[{id, text (≤45 chars), kind:'question'|'action'|'stop'}], edges:[{from, to, label? ('Yes'/'No', ≤14 chars)}], path:[ids from root]}. Keep ≤ 4 levels and ≤ 4 leaves. steps: one spoken phrase per path node.

## Define

Definition card for a new term. props: {term, meaning, example?, abbrev?}. steps: [phrase when meaning is said, phrase when example is said]. Use the FIRST time a term appears.

## DripperFlow

Drippers as small taps: a row of potted plants on a drip line, each dripper dripping into its own catch cup while a stopwatch runs and a live 'per plant' total counts up; a calculation strip builds flow → shot volume → zone volume. props: {plants:12, drippersPerPlant:2, lph:4, seconds:30, showZone?:true, uneven?:[mL per cup...] (catch test: cups end at those levels, low ones turn amber), decimals?:3 (litre decimals in line 2), mlDecimals?:0 (mL decimals everywhere, e.g. decimals:4 + mlDecimals:1 → '0.0667 L = 66.7 mL'), mode?:'flow' (flow calculation only: drippers drip, no cups/mL/stopwatch, right side shows 'N L/h per plant', strip shows line 1 only; seconds still required but unused)}. Shows up to 4 plants. steps: [line 1 'N drippers × L/h = per plant', line 2 '× s ÷ 3600 = L = mL', line 3 '× plants = L per zone' (if showZone)].

## DrybackBars

Dryback as a balance: a start glass and an end glass of water (VWC scale on each). The end glass drains from the start level to the end level while droplets rise off it, a bracket measures the fall in points ('15 points'), then (showRelative) the fallen slice is hatched on the start glass and a pie fills to the fall as a share of the start ('25% of the start'). props: {start:60, end:45, unit?:'% VWC', showRelative?:true, startLabel?, endLabel?}. steps: [start reading, end reading (drain), points bracket, relative share].

## FlowSteps

Horizontal process of 3–6 rounded steps joined by animated arrows; a gold token travels each arrow and the next step glows as it is spoken; finished steps get a green tick. Optional loop-back arrow under the row. props: {title?, steps:[{label (≤14 chars), icon (built-in: draft review apply readback restore shield preserve search check cross water clock lock calendar alert stop power probe plug chart save person question note wrench eye arm sun ruler — or an emoji), note? (≤60 chars, shown under the row while that step is active)}], loop?:boolean, loopLabel?}. steps: one spoken phrase per step, then one for the loop-back (if loop).

## HostSetup

Preparing the host computer in four numbered panels: 1 Parts (Raspberry Pi board or small PC, 64 GB card / internal disk, power supply, Ethernet cable) · 2 Write the image (laptop running Imager/Disks, the right drive ticked, the 1 TB photo drive crossed out, amber 'This erases the selected drive' warning, progress bar to 'Write finished') · 3 Boot on Ethernet (board LEDs flicker, cable to router with data pulses) · 4 Open in a browser (types homeassistant.local:8123, then 'Welcome home!'). props: {device?:'pi'|'pc' (default pi), cardLabel?:string (Parts-panel storage caption, default '64 GB card' / 'Internal disk', e.g. '32 GB or more'), stages?:('parts'|'write'|'boot'|'browser')[] (default all; omitted panels are not drawn and the remaining panels are re-laid out side by side, scaled up and centred — one panel shows large in the middle)}. steps: one per entry of stages, in order. The write panel needs ~90 frames after its step to finish its progress bar.

## LinesLegend

Teaches the three chart lines: saved reference (grey dashed), draft (green dashed, dragged by one step) and the measured trace (solid blue, never moves); labels pop with pointers; then a Review changes card (old → new), Apply 1 change → 'Applying and verifying' → green 'Readback ✓', and the saved line moves to the new value. props: {from:30, to:31, unit?:'%', showReview?:true, setting?:'Rescue floor', room?:'Room A'}. steps: [saved+measured labels, draft drag, review card, apply click, readback] (only the first two if showReview:false).

## MeasurementMap

Where an EC reading came from: side view of the water's journey — mixing tank (feed EC) → pipe and dripper → pot with a probe in the substrate (bulk EC; a zoom bubble shows the water between substrate pieces = pore-water EC) → drain cup (runoff EC) → lab jar (extract EC). Water flows continuously; each place lights up with a label (and optional value) at its step, the latest one pulsing orange; unlit places stay dimmed. props: {highlight:['feed','bulk','pore','runoff','extract'] (any subset, in reveal order), values?:{feed:'2.0', runoff:'2.4', ...}, unit?:'mS/cm'}. steps: one per highlight entry.

## OneOwner

One owner per output: an old timer (left) and the new Crop Steering Controller (right) are both wired to one zone valve. Conflict: pulses run down both wires, 'OPEN!' / 'CLOSE!' bubbles alternate, the valve flickers open/closed and shakes under a red clash burst. Resolved: scissors cut the timer's wire (greyed, 'link removed'), the Controller's wire turns green ('sole owner'), green check over a calmly cycling valve. props: {stage?:'conflict'|'resolved'|'both' (default both)}. steps: [conflict appears, resolve (only used when stage='both')].

## PhaseDay

The grow-day as a timeline from lights-on to next lights-on: sun/moon sky strip, a VWC trace drawn phase by phase with water-drop shots, and four phase bands P0 (morning wait), P1 (refill shots stepping up), P2 (maintain: a shot each time VWC touches the re-water threshold), P3 (overnight dryback, Rescue floor, optional rescue shot). Phase widths are schematic. props: {highlight?:'P0'|'P1'|'P2'|'P3'|'all' (omitted = the newest revealed phase is emphasised), lightsOn:'06:00', lightsOff:'18:00', showFloor?:true, showRescue?:false, only?:'P0'|'P1'|'P2'|'P3' (show just that phase: its band, trace and sky span the full width on their own, no clock axis; steps: [that phase])}. steps: [P0 said, P1 said, P2 said, P3 said] — each phase band + its part of the trace appears at its step.

## PlantBalance

Vegetative vs generative growth on one illustrated plant (cutaway pot): roots, leaves and shoots glow green; flowers glow gold. A see-saw (Vegetative ↔ Generative) tilts when a 'bias' weight lands on one side, and keeps gently rocking; both kinds of growth stay on the plant. props: {tilt:'veg'|'gen'|'balanced', labels?:{veg?, gen?, message?:'A bias is an influence, not a switch', sub?}}. steps: [vegetative parts named, generative parts named, the tilt/bias, the message].

## Points

Numbered key points revealed in order. props: {heading?, items:[{text, icon? (emoji)}]} (max 5, ≤ 60 chars each). steps: one spoken phrase per item.

## PotCrossSection

Signature cut-away pot of substrate: irregular solid particles, water films + saturated water (blue) and air gaps (white), optional roots/plant and probe, tray below catching drips. props: {mode:'fill'|'drain'|'dry'|'static' (default static), from?:0-1, to?:0-1 (water level, 1 = saturated; defaults fill .25→.65, drain 1→.6, dry .65→.35, static .6), secs?:4 (length of the water change), showRoots?, showProbe? (adds probe + glowing sensing region), arrows?:['drainage','evaporation','uptake','oxygen'], labels?:true (Solid/Water/Air callouts), caption?}. fill = water pours in from an emitter, a wetting front descends, displaced air bubbles up, then excess drips into the tray and the pot settles at `to`. drain = water drips out, air bubbles re-enter from the top. dry = films thin slowly. steps: [water change starts, then one per arrow in order, then Solid, Water, Air if labels].

## ProbeZone

One probe in a row of pots (side view, cut-away, drip line with drippers dripping into every pot). Water spreads from each dripper so the near side is wetter. props: {pots?:5, probeAt?: index (default middle), show?:['region','dripper','airgap','uneven'] (default region, dripper, uneven), reading?:'62%' (null or '' hides the probe reading badge), callout?:'The reading only describes here'}. region = glowing sensing zone around the needles + callout; dripper = pulse at the probe pot's dripper + 'Wetter'/'Drier' labels; airgap = magnifier showing air pockets round the needles + 'Air gap: reads too dry' warning; uneven = other pots shift to different wetness and show '?' + 'Same zone, other pots: wetter or drier?'. steps: one per `show` item, in the order given.

## ReadingAge

How old is a reading? A wall clock shows 'now' (sweeping second hand); each probe's reading card slides in with its last-update time, its age counts up quickly ('4 h old', full value ~1.2 s after the card appears), the clock shades the wedge from the reading time to now, and colour runs green → amber → red with a STALE stamp past staleAfter minutes. Optional units check panel: '0.45 m³/m³ × 100 = 45%' ✓ vs '0.45%' ✗. props: {now:'14:00', readings:[{name:'Probe A', at:'10:00', value?:'48%'}, ...], staleAfter?:60 (minutes), units?:{value:'0.45', unit:'m³/m³'}}. steps: one per reading card, then one for the units check.

## SafetyStop

Software OFF vs physical isolation. Left: a phone whose Watering switch flips ON→OFF ('a request to software'); the Controller pauses ('no shots') and its command line to the pump is blocked. Then an old timer lights up and still drives the pump (red pulses, pump spins, water drips, red '!'). Finally the isolation switch turns OFF with a padlock + LOCKED tag and the hand valve closes: power beyond the isolator goes dead, pump and water stop, green check. Bottom pill states each verdict. Schematic only — no wiring steps. props: {room?:string (phone label, default 'Room A'), stages?:('software'|'bypass'|'physical')[] (default all; stages:['physical'] alone hides the phone + Controller and shows only the power → isolation switch → pump → hand valve panel, large and centred, pill 'Power is still live to the pump' → 'Isolated and locked')}. steps: one per entry of stages, in order.

## SaltWater

Salted water explains EC. A glass of water; at each step a spoon tips salt crystals in, they sink and dissolve into + / − ions that wander through the water, and a conductivity meter with two probes counts up to the next reading while charge dots flow faster along its cables. Optional comparison glass on the left with its own reading. props: {readings:[0.2,1.0,2.0], unit?:'mS/cm', labels?:['Tap water','+1 spoon','+2 spoons'], compare?:{label:'Plain water', reading:0.0, display?:string ('' hides its pill)}, display?:[string per reading] (meter shows that word instead of the number, e.g. ['low','higher']; unit hidden), labelsOnly?:false (true = no number/unit on the meter or compare pill), readings may also be words directly (['low','higher']) — salt amount then ramps by position}. steps: one per reading (readings[i] is reached at steps[i]; the first is shown from the start).

## ScreenTour

Real app screenshot in a browser frame; the camera eases (Ken Burns) to each region in turn, dims the rest, draws a gold highlight box and a numbered callout. props: {src:'img/screens/demo-overview-r3.png', focus:[{x,y,w,h,label}] in IMAGE pixels, size?:[w,h] (auto for bundled screens), url?, zoom?(max, default 2.2; automatically capped so the screenshot is never shown above ~1.6× its native pixels — small images zoom less)}. Screen sizes: 1280×720 for overview, selected-room, zone-detail, currentday, calendar, equipment-setup, probes, tank-and-feed, history-compare, ai-assistant; 984×500 calendar-profile-grid & endpoint-profiles; 934×500 probe-mapping; 521×296 currentday-graph; 618×160 settings-defaultview. steps: one spoken phrase per focus (camera starts moving on it). Keep labels ≤ 40 chars.

## SpongeDemo

Kitchen-sponge lifecycle hanging over a sink. Stages: 'dry' (pale, holes hold air) → 'soaked' (dunked into the basin, lifted dark and dripping = saturation) → 'drained' (no squeezing; drips slow and stop over ~2.5 s, water still held = container capacity) → 'note' (a Post-it beside it; if note.to is given the number is crossed out and rewritten while the sponge stays exactly the same). A numbered stage tracker sits on top and a caption under the sink. props: {stages?:['dry','soaked','drained','note'], note?:{from:'60%', to?:'70%', label?:'Water level'}, captions?:{dry?,soaked?,drained?,note?}}. steps: one per stage (when it starts), then one more for the note change if note.to is set.

## SystemMap

The five jobs of an automated system as connected cards: PLAN (host computer running Home Assistant, containing two SEPARATE boxes — the Crop Steering integration and the Controller app — with a 'Two separate parts, both on the host' pill), MEASURE (moisture/EC probe in a pot + optional bridge), SUPPLY (tank → valve → dripper), SWITCH (relay), PROTECT (physical shutdown + independent protection). Data pulses run probe → bridge → integration ↔ controller → relay → valve, and the valve opens/drips in 2 s cycles. props: {highlight?:('host'|'integration'|'controller'|'probe'|'bridge'|'switch'|'shutdown'|'supply')[] (others dim, highlighted get a gold ring), showDataFlow?:true}. steps: [plan, measure, supply, switch, protect, data flow starts].

## Title

Big title card. props: {title, subtitle?, eyebrow?}. Use to open a section or name a new idea.

## VolumeGrid

VWC as equal boxes: a sample split into `total` boxes (default 10; >12 wraps to two rows). Water boxes fill one by one with rippling water, then solid boxes (substrate blobs), then air boxes (drifting bubbles); a legend counts each kind and a big live counter reads e.g. '6 / 10 = 60% VWC'. If neither solid nor air is given, the non-water boxes show '?' ("Not water" — use it for 'what VWC does not tell you'). Optional litres line: '5 L × 0.6 = 3 L of water' with a filling jug. props: {total?, water, solid?, air?, litres?: sample litres, label?: heading}. steps: [water starts filling, solid (or ? boxes) start, air starts, litres line].

## WaterPath

Plumbing diagram built part by part: supply tank → backflow preventer → (optional) pump → filter → pressure regulator → zone valve → drip line with drippers into pots → drainage tray to drain; 'backflow' also marks the anti-siphon at the high point. Water then flows along the pipe, drips fall. props: {parts?:('supply'|'pump'|'filter'|'regulator'|'valve'|'drippers'|'drain'|'backflow')[] (default all; omit 'pump' for a pressurised supply; with a subset the drawn diagram is re-centred and shrunk if needed so nothing runs off the stage), flow?:true, stop?:boolean}. steps: one per entry of parts, in the order given (each part appears when named), then (if stop) one for the stop — valve turns red, STOP sign, flow ceases, drips taper and a large eye label 'Watch the drippers stop' (38 px, two lines) sits just above the drippers watching the outlet until dry ('No more drips' + check).
