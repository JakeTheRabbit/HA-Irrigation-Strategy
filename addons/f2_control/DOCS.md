# Crop Steering Controller

This companion app runs the P0–P3 irrigation decision loop and sequences mapped pump/valve entities. Install the Crop Steering integration first; it owns room configuration, sensor mapping and grow-plan storage.

## Install and configure

Follow the [installation guide](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md). After installing this app, review Configuration, start it, and open the integration's **Crop Steering** sidebar page. The ingress dashboard is also available. Both serve the same native workspace.

Use **Rooms & setup** for mapping and per-zone sizing. Keep engines off while commissioning. Fresh installations create engine controls; existing mapped enable flags are preserved. The legacy default-room helper may still be input_boolean.f2_control_enabled. The room descriptor/heartbeat identifies the actual flag; do not create a second one blindly.

## Plans and operation

The **Grow plan** page supports per-zone day/week schedules and explicit vegetative/generative profiles. Saving is draft-only; arming makes a plan eligible at the next local lights-on boundary. It does not enable the engine. Active plans supply atomic versioned targets. Missing or expired required plans hold irrigation, including after restart.

The controller retains source-water/interlock gates, duration/daily-volume caps and hardware state readback. Shared-hardware faults latch until implicated engines and hardware are off. State readback is not proof of physical delivery; verify sensors and actual flow on site.

## Visible targets and water

Manual setpoints show saved and draft VWC/EC curves beside the selected phase. Compare runs overlays retained readings with daily target illustrations or earlier runs aligned by grow age. Stored references are timestamped; Recorder retention determines the available historical data.

Water cards distinguish total substrate capacity from all-plant zone litres and average mL per plant. The runtime calculator includes whole-second timing, the minimum shot and duration cap. Phase estimates also disclose engine parameter limits. New delivery counters use configured flow captured per shot and elapsed runtime, including partial aborts; historical totals are preserved.

## Updating

Update the integration and this app together. Use **Update** or **Rebuild** to include new Python code; restarting an old image does not rebuild it. Preserve persistent data and export plans before upgrades. See the installation guide for rollback instructions.

The display name is Crop Steering Controller. The existing f2_control slug remains stable for upgrade compatibility. Use controller 0.13.3 with integration 2.16.1. Local browser/unit checks do not constitute a live HA installation test.
