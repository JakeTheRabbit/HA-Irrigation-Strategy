# Troubleshooting

| Symptom | Check and action |
| --- | --- |
| Workspace requests an integration update | Update the integration including its bundled www/dashboard.html, restart HA and refresh the page. |
| Plan cannot arm | Check controller capability/heartbeat, plan validation, sensor freshness and explicit limits. Save the draft before arming. |
| Plan is armed but not active | It becomes eligible at the next local lights-on boundary. Arming never enables the engine. |
| Active plan is held or in error | Read the plan/controller error. Restore valid fresh data; use disarm for an explicit return to manual targets at a boundary. Do not bypass the required-plan latch. |
| Mapping save is rejected | Confirm the affected engine and implicated hardware are readable and OFF. Check entity domains/units, duplicate valves and revision conflicts. |
| Mapping saved but controller has old data | Compare setup revision with controller acknowledgement. Wait for rediscovery and inspect app logs. |
| Room/zone disappeared | Check Rooms & setup for archived entries. Restore the same ID; do not reuse IDs for different equipment. |
| No recorded EC line | Confirm mapped EC entities are recorded in HA Recorder and have data in the selected time range. A target line is not a sensor history. |
| Shot volume disagrees with observation | Verify litres per plant, plant count, drippers/plant and actual L/h; run a catch test. Inspect duration caps and physical pressure/flow. |
| Source code change did not reach controller | Use Update/Rebuild. Restarting an existing container keeps its old image. |
| Hardware fault remains latched | All implicated engines and shared hardware must be OFF before recovery; inspect the actual fault first. |
| Embedded theme does not match | Use the integration's same-origin sidebar and Follow Home Assistant. Cross-origin standalone pages cannot read parent theme variables. |
| Live connection failed | Reauthenticate HA or configure the explicit connection in Settings. The app does not silently switch to demo data. |

Use [INSTALL.md](INSTALL.md) for repository links and commissioning steps. The public repository must contain the intended revision before guided installation can obtain it. Browser or unit-test success does not prove that an older deployed image has changed.
