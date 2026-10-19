# Equipment and setup: start with one zone

This is a functional buying and commissioning guide. It specifies what each part must do, not a promise that any product bearing a familiar name will work. Verify the exact model, interface, firmware and electrical/hydraulic ratings before buying. Reuse suitable existing equipment after checking it.

## Three levels of equipment

| Level | What you need | What it lets you learn |
| --- | --- | --- |
| Explore without hardware | Phone/computer, browser and the [demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1); optional spare medium, jug and tray | Measurements, graph, drafts, recipes and program navigation; no physical commissioning |
| One-zone moisture control | Dedicated supported HA host, network, compatible VWC measurement, controllable and safely installed water path, known emitters/plant count, physical protection and measuring tools | Observe moisture, test delivery and commission basic sensor-driven irrigation |
| Full water-and-EC learning kit | The above plus identified root-zone EC measurement, feed EC/pH checking, air temperature/RH and useful tank/feed monitoring | Interpret conductivity in context and use the corresponding mapped features |

EC is important to understanding root-zone management, but an EC probe is not required for every software watering function. The controller can water from moisture with EC rules paused when root-zone EC is unavailable. Do not invent or substitute feed EC to fill a missing pore-water EC mapping.

## Functional bill of materials

Quantities below describe one initial hydraulic zone, not a universal sensor-density prescription.

| Function / starting quantity | Before you buy or reuse it | Required now or later? |
| --- | --- | --- |
| Always-on host / 1 | Choose supported Raspberry Pi HAOS or dedicated supported x86-64/Intel NUC HAOS. Provide appropriate PSU, storage, cooling/enclosure and recovery access. Back up any existing drive before installation. | Required; one host can serve multiple zones |
| Network / 1 reliable connection | Router/switch, Ethernet and access from your setup computer. Use local device integrations where supported; document addresses and any cloud dependency. | Required; use Ethernet for the beginner installation |
| HA software stack / 1 | HAOS, HACS, Crop Steering integration and compatible Crop Steering Controller app. Use the paired release instructions. The dashboard is bundled; do not start by building Lovelace YAML. | Required for this taught route |
| VWC probe / at least 1 representative location initially | Exact medium suitability, calibration, installation orientation/contact, read frequency, temperature range, HA entity, units and electrical interface. One probe does not establish uniformity across the zone. Expand sampling as needed. | Required for moisture control |
| Sensor bridge/interface / as needed | Only if the probe does not integrate directly. Verify sensor supply, protocol, signal voltage and bridge support. Buy a documented assembled route first if you cannot validate the electronics. | Conditional |
| Root-zone EC measurement / as appropriate | Identify whether it is bulk EC, derived pore-water EC or another method. Verify transformations, moisture/temperature limits and units. TEROS 12 bulk EC is not automatically a direct pore-water EC measurement. | Needed for full EC learning; not a substitute for VWC |
| Air temperature and humidity / 1 representative location initially | Avoid direct spray, radiant heating and unrepresentative air pockets. Check units, timestamps and placement. More locations may be needed. | Recommended for interpreting demand |
| Water source/reservoir / 1 | Enough usable capacity, suitable water quality, safe refill/overflow arrangements and access for inspection. Follow the feed supplier's instructions separately. | Required water function; reuse appropriate infrastructure |
| Pump / only if the supply needs one | Required duty, flow/pressure curve at operating load, dry-run protection, manufacturer instructions and correctly rated starting/control hardware. | Conditional: do not add a pump to a suitable pressurised supply just for the diagram |
| Filter, pressure regulation, backflow/siphon provisions / as designed | Match emitter and supply requirements. Confirm applicable plumbing requirements with a competent installer. A check valve alone is not proof of every required protection. | Installation dependent; resolve before water testing |
| Zone valve and controller / 1 initial zone | Normally closed/fail-closed where appropriate, voltage/current, pressure range, water compatibility and HA-supported control. Verify behaviour on loss of power and communications. | Required controlled zone function |
| Pipe, dripline, fittings and emitters / based on layout | Compatible pressure and flow, drippers per plant, actual count, end flushing and accessible leak inspection. Record emitter model and nominal flow, then measure it. | Required |
| Safe electrical control / each output | Certified/enclosed equipment appropriate to local requirements. Check inductive/start loads and pump control inputs. A domestic smart plug's headline resistive rating is insufficient evidence. | Required; professional installation where applicable |
| Physical isolation and independent protection | Accessible electrical/water shutdown, pump dry-run protection, containment/flood provisions and safe drainage. Decide the response to sensor/network/controller failure. | Required installation design; software switches are not emergency isolation |
| Commissioning tools / 1 set | Suitable measuring jug or scale, catch cups, stopwatch, tray, labels, layout sheet and a way to observe all tested outlets. Use appropriate hygiene and spill precautions. | Required for physical proof |
| Feed EC/pH checking | Suitable meters, manufacturer calibration/storage supplies and clean sampling tools. Distinguish feed from root-zone data. | Recommended for nutrient solution management |
| Tank level/EC/pH/temperature entities | Calibrated level scale and identified instruments; know which are real readings, estimates and float switches. | Useful monitoring; do not infer a pump interlock from a dashboard card |
| Verified flow meter, runoff collection, extra probes, UPS | Check meter placement/range/pulses and data interpretation; size UPS and define outage behaviour. | Later improvements based on a known problem |
| Thermal camera, CO₂ control, automated dosing, AI/MCP | Each adds separate commissioning, safety and interpretation work. | Optional advanced modules, not starter requirements |

Do not publish an unverified universal shopping cart or price. For a purchase-ready kit, the producer must fill in exact locally available models and pass the compatibility sheet below. No exact new sensor, relay or smart-plug model is endorsed by this pack.

### Host choice

**Raspberry Pi route:** follow the [official HA guide](https://www.home-assistant.io/installation/raspberrypi/). At research time it suggests Pi 4 or 5 with at least 2 GB RAM, an appropriate power supply and at least a 32 GB card; check the live guide before buying. Provide the other listed installation accessories and stable Ethernet. Do not power the Pi from an arbitrary computer USB port. Use a supported storage route rather than improvising boot media in the beginner video.

**Intel NUC / x86-64 route:** follow the [official generic x86-64 HAOS guide](https://www.home-assistant.io/installation/generic-x86-64/). Confirm the exact machine meets the current requirements and can be dedicated to HAOS. Installing the image erases the selected destination. A NUC is an example form factor, not proof that every unit's firmware/storage is supported.

Choose one route. Both rejoin at HA onboarding; there is no need to buy both hosts. Existing working supported installations need not be reinstalled just to follow the course.

## Draw the real system

```text
Water path A — existing suitable pressurised supply
Supply → required filtration/regulation/protection → zone valve → emitters → pots → drainage

Water path B — reservoir with pump
Reservoir → pump + required protections → filtration/regulation → zone valve → emitters → pots → drainage

Control and evidence
Probe → compatible interface → HA sensor entity → Crop Steering Controller
Operator's reviewed configuration → HA integration → Controller → mapped output → physical equipment
                                                        │
Actual sensor readings + output feedback + water check ←─┘
```

The physical order and fittings must suit the actual design and manufacturers' instructions; these are functional diagrams, not construction drawings. Air/climate readings add context. Tank feed chemistry is a separate measurement from root-zone chemistry.

**One owner for every physical output.** Record whether Crop Steering, another HA automation, an external irrigation controller or a dosing controller owns each pump and valve. Resolve conflicting control before commissioning. In a migration, do not leave two independent controllers able to run the same output.

### Compatibility sheet — complete before C4/C6

| Item | Record |
| --- | --- |
| Host / OS / backup location | Exact model, installed versions, recovery steps |
| Probe and medium | Exact probe/firmware, medium, approved installation and calibration/reference method |
| Sensor interface | Supply voltage, signal/protocol, electrical protection, bridge model/firmware and source documentation |
| HA entities | ID, friendly name, physical location, quantity, units, update interval, acceptable data age |
| EC interpretation | Feed/bulk/pore-water/extract, conversion method if any, validity range |
| Output hardware | Valve/pump model, ratings, control interface, fail behaviour, physical isolator |
| Output ownership | One owning controller; disabled/reassigned conflicting automations |
| Sizing | Plants, substrate litres/plant, drippers/plant, measured L/h per emitter, tested pressure |
| Lighting and time | Local timezone, configured room lights-on/off hours, actual lighting schedule and observed agreement; identify which system owns the lights |
| Protection | Dry-run/flood/siphon/backflow arrangements, responsible installer and test method |

### Optional TEROS 12 / Atom Lite demonstration

The existing project tutorial contains an owner-confirmed working genuine TEROS 12 assembly and a GPIO26 bridge configuration. That is a filming reference, not a universal wiring diagram. Verify the exact probe documentation, SDI-12 interface, voltage protection, power supply, firmware and pin assignment before reproducing it. Do not infer wire functions from colour or connect an unverified probe signal straight to a GPIO. Use the documented assembled route in the beginner core; put verified DIY details in a separately reviewed appendix. Successful communication does not prove substrate calibration or valid pore-water EC conversion.

## Installation and commissioning sequence

Use the current [installation guide](../../INSTALL.md) for commands and exact release steps. The course supplies the explanation and evidence to collect, rather than a second installation procedure that silently drifts.

1. **Prepare recovery and isolation.** Back up existing configuration off the host. Identify the physical shutdown and water isolation. Keep automatic engines disabled; physically isolate hazardous outputs as the installation requires. Unknown output status is not OFF.
2. **Install the host if needed.** Select the correct dedicated storage device before writing HAOS. Complete onboarding, timezone, accounts and network access. Record where the backup is and how it would be restored.
3. **Prove sensor ingestion.** Add the supported device/interface and check the actual entity, units, freshness and placement. Compare a reference or independent check appropriate to the measurement. An implausible reading is a diagnostic issue, not a reason to rewrite a target.
4. **Prove output identity safely.** A competent installer confirms electrical and plumbing suitability. Begin with low-risk indication/test loads where appropriate. Name equipment after physical room/zone labels. Never use a live crop as the first wiring test.
5. **Install both Crop Steering components.** Use compatible integration and Controller versions; create the room and verify discovery/heartbeat with engines disabled. A UI loading is not proof of a running Controller.
6. **Map one zone and its real topology.** In Equipment → Setup choose Zone valves only or Pump then zone valves as applicable. Map correct sensor/control domains and units. Enter sizing. Set and verify the room's local lights-on/off hours against the actual lighting schedule and observed lights; record the timezone and which system controls the lights. The irrigation clock does not prove the lights follow it. Review/save and wait for Mapping acknowledged. Resolve errors rather than bypassing a hold.
7. **Prepare the equipment wet test.** Keep Crop Steering's Watering switch OFF through steps 7–10. With a competent person present, arrange a safe discharge into collection, contain spills, watch intended and unintended outlets, and agree physical shutdown. Only remove isolation needed for the specifically supervised test. Do not use a blanket fail-test that could deadhead a pump or flood a room.
8. **Run one bounded equipment-level catch test.** Use the equipment manufacturer's safe commissioning procedure under the installer's control, with an agreed duration and shutdown. This is **not a Crop Steering test shot**: Watering OFF blocks the Controller's test shots as well as ordinary and rescue shots. Equipment/manual controls can still operate independently of that switch; that is why physical isolation matters. Observe the actual outlet, pressure where relevant and intended pump/valve sequence. Verify other zones stay dry. Record actual runtime and catch volumes from several representative emitters. If there is no suitable safe equipment-level test procedure, stop here and have the installer provide one; do not bypass a Controller lockout.
9. **Stop and prove cessation.** Observe actual water stopping, no unwanted siphon and the intended pump/valve state. Test installed independent protections using the manufacturers' safe procedures. Communications/power failure behaviour needs an installation-specific test plan; do not simulate faults by randomly pulling wires or power under load.
10. **Calculate and correct.** Compare measured flow with the configured estimate. Investigate uneven delivery, clogged emitters, leaks or pressure differences before treating a zone average as representative. Re-test after corrections and record results.
11. **Review before automatic operation.** Check fresh probes, acknowledged mapping, correct room, verified local lighting hours/timezone, credible operator-selected targets, confirmed flow/stopping, independent protections and recovery access. All must pass. If anything fails, leave automatic operation disabled and physically isolate as required.
12. **Supervise the first Controller cycle.** Only after all checks pass, use an approved local recipe, not this course's illustrative numbers. Under the responsible operator's control, review room/zone readiness and enable the selected room's Watering for this supervised commissioning stage; follow the current release's documented controls and confirm readback. Enabling permits eligible Controller shots, including safety watering; it is not a harmless connectivity test. Observe the actual phase, first event, stopping, event record and next action, with safe collection and physical shutdown available. Finish in the explicitly agreed commissioned state; if any check fails, disable Watering and isolate as required. Expand one proven zone at a time, repeating the checks for each mapped output.

### Measured-flow example

A 4 L/h emitter nominally delivers about 33.3 mL in 30 seconds. Catch each emitter separately during a controlled test; total volume is useful, but cannot reveal a blocked emitter hidden by a high-flow neighbour. Three catches of 30, 33 and 37 mL correspond to 3.6, 3.96 and 4.44 L/h. Those are observations to investigate against the design and measurement uncertainty, not a universal pass/fail tolerance.

Use the workbook's blank commissioning record for actual results. Do not enter these example catches as calibration values for a real zone.
