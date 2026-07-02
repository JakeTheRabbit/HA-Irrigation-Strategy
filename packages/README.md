# Packages — facility-specific examples, not required

The YAML under `packages/` (and `deploy/`) is the **original F2 facility's** Home
Assistant package config, kept as a worked reference. It is **not needed** by the
crop-steering integration or the f2-control add-on, and it is **not portable**:

- `packages/irrigation/10_mapping.yaml` maps that facility's ESPHome/probe devices
  (`sensor.environmentals_*`, `sensor.substrate_*`) and unconditionally creates helpers
  for **6 tables** — wrong for any other zone count.
- `packages/f2_pump_modes.yaml`, `deploy/*.yaml` reference that facility's pump/valve
  entity ids.

A normal install does **not** copy these. The integration creates all the entities you
need through its config-flow wizard, and the f2-control add-on reads the pump/mainline/
valves you map there. Only borrow from these files if you are hand-building HA templates
and want a starting point — and expect to rewrite every entity id for your own hardware.

The repo-root `config.yaml` is likewise an **example** HA configuration (it `!include`s
this `packages/` dir); it is not something you drop onto a real HA install verbatim.
