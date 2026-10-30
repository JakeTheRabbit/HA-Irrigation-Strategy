# Roadmap

Where Crop Steering goes next, written against the current release, **3.18.0**. Plans, not promises: items are ordered by priority, not tied to dates. Every item has a "done means" line, so you can check it yourself when it ships.

**What stays the same:** Crop Steering is free and open source (MIT). It runs locally in Home Assistant, works with the sensors, valves and pumps you already have, and needs no cloud service to water.

## What Crop Steering does, and what it leaves to other tools

Crop Steering does irrigation and fertigation: it reads substrate moisture and EC, decides when and how much each zone should drink (P0 to P3), and runs the pumps, valves and dosing pumps safely.

It does **not** try to be a farm-management platform. Users and roles, task lists, pest management, compliance records and climate control belong in the tools built for them. Crop Steering connects to them instead:

| Area | How Crop Steering connects |
|---|---|
| Users and roles | Home Assistant's own users. Configuration saves need an administrator, and the change history records who made each change. |
| Tasks | Alerts, Repairs cards and the Upgrade report carry error codes that another tool can turn into tasks. |
| Compliance records | The change history, run records, harvests and water totals, exportable. |
| Climate | Lights, HVAC and hold switches are read as inputs and can pause watering; Crop Steering does not drive climate equipment. |

## Now: the next one or two releases

**Prove 3.18 on real water.**

### Field validation of 3.18.0
- **Why it matters:** 3.18 passed automated tests on two Home Assistant versions, a container smoke test and a full page sweep. Software tests are not water. Growers should see it run on real plumbing.
- **Done means:** A published release audit with a full light cycle on real hardware, a catch test per zone (water asked for vs water caught), and fault drills (valve that never opens, kill switch mid-shot, restart mid-shot, dead probe, unreadable feed reading, flow-meter shortfall and leak), each showing the alert it raised.

### Independent dosing-pump backstop
- **Why it matters:** A crashed controller should never leave a dosing pump running.
- **Done means:** A ready-made Home Assistant automation switches any dosing pump off after a maximum run time, on its own, without the controller. System status warns about a dosing pump without one.

### Substrate calibration curves
- **Why it matters:** Different substrates read differently. Per-probe offsets shipped in 3.18; substrate curves come next.
- **Done means:** Each substrate curve is published with its stated error. Matching a handheld reading moves the zone value without a false step alert.

### Docker healthcheck and complete settings
- **Why it matters:** If you run the controller as a plain Docker container, you should see when it stops working. Every setting should also be editable from the app screen.
- **Done means:** Docker shows the controller as healthy or unhealthy from its heartbeat. All controller settings appear in the app options.

### Safety edge cases
- **Why it matters:** A few rare fault orders can still leave a room less protected than it should be.
- **Done means:** Each case has a test that failed before the fix and passes after it.

## Next

**Make it easy to adopt with whatever hardware you own.**

### Hardware compatibility program
- **Why it matters:** Before you buy or wire anything, you should know whether your probes, relays, valves, pumps and flow meters will work.
- **Done means:** A public device list with three clear tiers. **Verified** devices passed a published bench test on real hardware, with date, firmware and evidence. **Community-reported** devices were reported by a grower but not bench-tested. **Should work** devices meet the device contract only. The bench test is a script anyone can run, and a device-report form is open to everyone.

### Device contract
- **Why it matters:** Hardware makers and installers need one page that says what a device must do to be driven safely.
- **Done means:** A versioned contract covers each role: zone valve, pump, main line, moisture/EC probe, feed probe, flow meter, dosing pump and kill switch. It lists the Home Assistant entity types and units allowed, how fast the device must report on and off, and what happens when it goes unavailable. Tested ESPHome and Modbus templates cover pulse flow meters and 4–20 mA pH/EC transmitters.

### First-install wizard and commissioning checklist
- **Why it matters:** Going from an empty Home Assistant to a supervised first shot should not need an expert.
- **Done means:** A fresh install reaches a supervised first shot using only in-product steps, and a recorded run proves it. A per-room commissioning checklist (controller seen, mapping confirmed, catch test per zone, kill switch tested, dosing backstop present) must be all green before you can switch on automatic watering. Probe-placement guidance is linked from probe alerts.

### Stable API and data export
- **Why it matters:** Integrators and other platforms need to know what will not break under them.
- **Done means:** A published list of stable services, entities, events and response fields, with a deprecation policy: at least one release of warnings in Home Assistant Repairs, and removal only in a major release. Response schemas are checked in CI. One room identifier works everywhere. History, runs, water and harvests export as CSV and JSON with a schema version.

### Packaging: Home Assistant app and standalone Docker
- **Why it matters:** Home Assistant OS users and Container/Core users should get the same quality of install, upgrade and rollback.
- **Done means:** Each route has its own install, upgrade and rollback guide. Each release is smoke-tested on both routes from the published artefacts.

### Test coverage
- **Why it matters:** Safety-relevant pages should be tested directly, not only by end-to-end scripts.
- **Done means:** Coverage is reported for every part, with a floor that cannot drop. Component tests cover setup, dosing, calibration and timers.

### Documentation for three readers
- **Done means:** Separate start pages for growers (what crop steering is, your first week), installers (hardware and commissioning) and integrators (API, events, device contract). Each page names the version it was checked against.

### 24-hour light schedules
- **Why it matters:** Veg and mother rooms often run lights 24/0.
- **Done means:** A 24/0 schedule works end to end, with a defined day boundary for phases and daily water totals.

## Later

- **Multi-site view:** a read-only view of status, alerts and water across several facilities, each running its own Home Assistant. No control across sites.
- **Inline (direct) injection dosing:** fertigation without a batch tank, built once a bench rig shows outflow EC holding within ±0.1 mS/cm of target through a flow change.
- **Lovelace card pack:** zone gauge, dryback chart, tank and stock, and timeline strip cards for wall and tablet dashboards.
- **Accessibility:** automated accessibility checks on every dashboard page, with zero serious issues.
- **Internal tidy-up:** smaller, clearer controller modules, with no behaviour change.

## Community

- Issue forms for bugs, device reports and feature requests.
- GitHub Discussions sections for growers, installers and integrators.
- "Good first issue" labels for contributors.
- This roadmap, updated with each release.

Have hardware you want on the list, or a need this roadmap misses? [Open an issue on GitHub](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/issues).

How the parts fit together today: [the system map](docs/SYSTEM_MAP.md).
