"""How this controller works, for the Claude brain's cached system prompt: generated from the code, never written by
hand, so it cannot drift from what the controller does.

`render(codes)` builds the brief from the engine's phases and its built-in settings, the setpoint bounds, the AI
assistant's powers and the settings it may write, and the error-code table. The add-on image cannot reach the
repository's docs/, so the brief is written beside this file (controller_brief.md)
by `python controller_brief.py --write` from the repository, and tests/test_controller_brief.py fails when the copy
differs from a fresh render or when a phase, setting, power or error code is missing from it. prompt.block_a()
appends it to the cached block, so it costs one cache write per box and model.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "controller_brief.md")
CODES = os.path.join(HERE, "..", "..", "..", "..", "docs", "error-codes.json")

# What happens downstream when the AI assistant moves a setting it may write (judges: setpoints, targets, shotsize).
EFFECTS = {
    "p1_target_vwc": ("P1, P2", "the ramp aims here (with field capacity, the lower of the two); raising it lengthens "
                      "the ramp and adds ramp shots; the P2 band sits between the re-water point and it; tomorrow's "
                      "P0 dryback is measured from the peak it produces"),
    "field_capacity": ("P1", "caps the ramp's ceiling (min(P1 target, field capacity)); the saturation labels read "
                       "against it; under Auto setpoints it follows the zone's highest readings unless the AI owns it"),
    "p2_vwc_threshold": ("P0, P2", "a maintenance shot fires under it (plus the EC steer's offset); raising it waters "
                         "more often with a shallower dryback, lowering it fewer shots and a deeper dryback; P0 jumps "
                         "to P1 when moisture falls to it"),
    "p3_emergency_vwc_threshold": ("P3", "the rescue floor: a rescue shot fires under it at night; it sits at least 3 "
                                   "points under the re-water point (Home Assistant refuses an order that breaks it)"),
    "vegetative_dryback_target": ("P0, P3", "the relative dryback (peak - VWC) / peak x 100 P0 waits for when the zone "
                                  "is steered vegetative; larger means a later first shot"),
    "generative_dryback_target": ("P0, P3", "the same for a zone steered generative"),
    "p1_initial_shot_size": ("P1", "the first ramp shot, % of the substrate; each next ramp shot adds "
                             "p1_shot_size_increment; bigger reaches the peak in fewer shots but risks runoff"),
    "p2_shot_size": ("P2", "a maintenance shot, % of the substrate; bigger shots drain more and dilute pore EC, "
                     "smaller let it stack; under 3 % shots machine-gun"),
}

PHASE_MACHINE = """\
## How this controller works (generated from the code)

### 1. The phase machine, per zone, each 60 s pass
- Phases: {phases}. A grow-day is one photoperiod: lights-on (number lights_on_hour) starts it, lights-off (number
  lights_off_hour) ends it. The daily water and shot counters reset at the P3 -> P0 change at lights-on.
- Lights-off forces any zone not in P3 to P3. P3 -> P0 at lights-on (or on a new grow-day when a light edge was
  missed); a zone in P1 or P2 on a new grow-day also restarts at P0 with its own budget.
- P0 -> P1 when the first of these holds: moisture at or under the re-water point (p2_vwc_threshold); the dryback
  reaches p0_additional_dryback when positive, otherwise vegetative_dryback_target or generative_dryback_target
  by steering mode; P0 has lasted p0_maximum_wait_time minutes. The additional setting REPLACES the target,
  it is not added. Dryback is relative to the peak since lights-on:
  (peak - VWC) / peak x 100.
- P1 (the ramp): shots of p1_initial_shot_size, growing by p1_shot_size_increment, every p1_time_between_shots
  minutes, until moisture reaches min(p1_target_vwc, field_capacity); then one more shot, and P1 hands over to P2
  when a shot no longer raises the zone's highest reading by p1_rise_pts (the rise rule), after
  p1_maximum_extra_shots extra shots, at p1_maximum_shots, or at the target with the daily budget spent. P1 has no
  time exit: a gated zone waits in P1 and resumes. Below target, after the minimum shots and shot interval,
  {stall} consecutive shots without the required settled rise also end P1, provided the probe is trusted and
  drainage is not backed up. The day's re-water point then follows the stalled reading minus its P2 band.
- P2 (maintenance): a shot of p2_shot_size when moisture falls under the re-water point (with the EC steer's offset
  baked in, clamped between rescue + 3 and the ramp ceiling - 1), at most every p2_time_between_shots minutes. P2 ->
  P3 early only when a dryback started now would end by lights-on (predictive P3), otherwise at lights-off.
- P3 (night): only a rescue shot of p3_emergency_shot_size when moisture falls under the rescue floor
  (p3_emergency_vwc_threshold), at most every p3_time_between_shots minutes. With P3 dryback hold enabled,
  budgeted hold shots can also keep moisture at the overnight target; they are not daily-cap exempt.
- A probe that stops reading (stale, flat, out of range) makes the zone blind after {blind} minutes: it copies a
  healthy sibling's shots or, with none, gets a timed shot every blind_fallback_min minutes inside its daily cap. When
  the probe reads again the zone resumes from its own reading in the phase it is in.

### 2. Shot sizing
- Shot litres = substrate litres per plant x plants x shot % / 100. Flow L/s = plants x drippers per plant x L/h per
  dripper / 3600. Duration = litres / flow, then the room's safety cap on a shot's length. Positive flow is required:
  no hidden clamp.
- Daily caps: max_daily_volume per zone (rescue and the safety shots are exempt: {exempt}); the minimum-daily floor
  and the lights-on watchdog (watchdog_hours) still fire.

### 3. Gates and safety layers, in order, each fail-closed
1. The duplicate-controller lease holds the whole room for {dup} s before per-zone gates run.
2. Setup pending, archived room, or room off; dosing hold; plan hold (only its named safety exemptions pass).
3. Hardware fault latch (CS-301), then max-run latch (CS-312). After {max_run} consecutive shots cut to the
   maximum duration, max-run latches only with its switch enabled (off by default); otherwise it reports.
   A latched zone gets no shots, including rescues.
4. Missing valve mapping, incompatible plumbing, or an actuator that cannot be driven.
5. Room kill switch off or unreadable; a retired switch off; zone switch off or unreadable; manual override.
6. External hold entities: ON or unreadable holds. OFF releases a hold. Then settings hold and tank hold.
7. Source-water EC gate, then pH gate, when mapped and configured. Dead probes hold after their grace period.
8. An offline pump, mainline or zone valve: no actuation until every mapped device is readable.
Hardware sequencing after admission: pump prime (pump_prime_time), main line (main_line_lead_time), zone valve,
then shutdown in reverse. Read-back failure stops the pump and aborts the shot.
EC steering runs in P2 only with ec_stacking_enabled on: every 30 minutes the offset steps toward +1, -1 or zero,
clamped to +/-20% of re-water. The salt power can hold or halve it. ec_min_interval spaces EC-correction shots,
not the offset steps. An armed plan owns its targets; drift raises CS-713.
"""


def _settings():
    from crop_steering_engine.defaults import CONTROLLER_FALLBACKS

    return dict(sorted(CONTROLLER_FALLBACKS.items()))


def writable():
    """Every setting the AI assistant may write, by power."""
    from .judges.setpoints import SHOT, THRESHOLD
    from .judges.targets import SHOT_QUESTIONS, TARGET_QUESTIONS

    return {"nudge_setpoints": [SHOT, THRESHOLD],
            "set_targets_from_achievable": list(TARGET_QUESTIONS["targets"][0]["criteria"]),
            "tune_shot_sizes": list(SHOT_QUESTIONS["shot_sizes"][0]["criteria"])}


def restored_modes(core, shell):
    """Optional rules only when their runtime capability exists in the built image.

    This generator can land before the restoration packs. An older engine/controller emits no
    instructions for modes it cannot run; the final merged-source rebuild adds the supported rules.
    Neutral defaults leave the phase machine and interlocks described above in force.
    """
    fields = getattr(core.ZoneParams, "__dataclass_fields__", {})
    cls = shell.Controller
    out = []
    if "p0_min_wait_min" in fields:
        out.append(
            "- P0 minimum wait (p0_minimum_wait, default 0/off): before that many minutes in P0, "
            "normal dryback completion, stall exit, timeout and an AI dawn advance do not start P1. "
            "The engine's low-moisture bypass still starts P1 when VWC is at or below p2_vwc_threshold. "
            "The minimum is clamped to the maximum wait; it never prevents safety checks or an EC flush."
        )
    if "p0_stall_exit" in fields:
        out.append(
            "- P0 stall exit (p0_stall_exit switch, default off): after "
            f"{core.P0_STALL_AFTER_MIN:g} minutes in P0, a dryback below {core.P0_STALL_RATE_FLOOR:g} "
            "VWC points/hour, or projected to miss the maximum wait, can start P1. The minimum wait "
            "still applies. Never classify a backed-up table or a suspect/flat/bypassed probe as "
            "a stalled dryback; no positive peak means no stall verdict."
        )
    if "p2_mode" in fields:
        out.append(
            "- P2 mode (zone p2_mode select, default Moisture): Moisture retains the normal top-up rule. "
            "Timed uses p2_timed_interval_min since the last delivered shot and waits until "
            "p2_timed_first_hours after lights-on; p2_timed_shot_size 0 uses p2_shot_size. Timed with "
            "guards keeps the moisture-triggered top-up as a floor rescue and skips a timer slot "
            "at or above min(p1_target_vwc, field_capacity - 2). The floor rescue is a budgeted "
            "p2_topup, not a daily-cap exemption. Plain Timed has no moisture top-up; both modes "
            "retain EC correction priority, the daily cap and every hardware/feed interlock."
        )
    if "p2_end_h_before_off" in fields:
        out.append(
            "- Timed P2 end (p2_end_hours_before_off, default 0/off): a positive value replaces "
            "predictive P3 and sends a zone in P1 or P2 to P3 that many hours before lights-off, "
            "independent of moisture. Lights-off still forces P3 and its emergency floor remains "
            "available; a zero value retains predictive P3."
        )
    if "ec_flush_target" in fields:
        out.append(
            "- EC flush target (ec_flush_target, default 0/off): a fired EC correction can latch "
            "a flush episode. In P2 it continues with budgeted p2_dilute shots toward the settled "
            f"pore EC target, never below feed EC + {core.EC_FLUSH_FEED_MARGIN:g} mS/cm. Continuation "
            "requires dilutive feed, drainage, VWC below field capacity - 2 and the EC correction "
            "settling/minimum interval. The episode clears at its goal, when switched off, at "
            "lights-off or a new grow-day; existing high-EC rescue triggers keep their own rules."
        )
    if "p2_dilute_ratio" in fields:
        out.append(
            "- Zone P2 dilute ratios apply only with the room's use_p2_ec_thresholds switch on "
            f"(default off). Otherwise the dilute trigger remains {core.P2_DILUTE_RATIO:g} times "
            "the P2 EC target. Changing the ratio changes when dilution triggers; it does not "
            "bypass the correction interval, drainage, feed or budget checks."
        )
    extra_bounds = getattr(core, "_PARAM_BOUNDS", {}).get("p1_max_extra_shots", (1, 10))
    if extra_bounds[1] > 10:
        out.append(
            f"- Maximum extra ramp shots accepts {extra_bounds[0]:g}-{extra_bounds[1]:g}. Extra shots "
            "still count inside p1_maximum_shots and the daily cap. Increasing the extra-shot "
            "setting alone cannot extend a ramp already stopped by its maximum total shots."
        )
    if hasattr(cls, "_step_limit_all"):
        out.append(
            "- Max setpoint move per day (setpoint_max_step_per_day, default 1 VWC point) limits "
            "the highest-reading follower by default. With setpoint_step_limit_applies_to set "
            "to Auto setpoints and AI, the same per-grow-day ledger also clips learner and AI "
            "target moves for field capacity, P1 peak and P2 re-water; exhausted allowance "
            "prevents further movement. The ladder must still validate after clipping. This "
            "does not limit shot-size writes or move the rescue floor. Zero removes this "
            "movement limit, not any watering interlock or daily water cap."
        )
    if hasattr(cls, "_rescue_past_dead_probe"):
        out.append(
            "- Rescues past a dead feed probe (rescue_past_dead_feed_probe, default off): only "
            "p3_emergency and watchdog shots can pass the dead EC/pH probe gate while this "
            "switch reads ON. A routine shot or an out-of-band reading still holds. This "
            "never skips the kill switch, dosing/external holds, plan rules, tank minimum, "
            "hardware faults, max-run latch or the shot kind's normal daily-cap policy."
        )
    if hasattr(cls, "_waste_rule"):
        out.append(
            "- Waste valve rule (waste_valve_rule, default Off): no mapped valve or a confirmed "
            "absent legacy policy keeps the old Off behavior. Check closed requires the waste "
            "valve to read OFF before a shot. Close for each shot closes it before the pump "
            "primes and verifies readback; a refused/unverified close starts no shot. An "
            "unreadable or invalid policy holds rather than silently disabling the interlock; "
            "a disappeared previously seen policy also holds. Under an enabled policy a "
            "waste valve seen ON during delivery aborts the shot. The controller never opens it."
        )
    if hasattr(cls, "_watch_rescues"):
        out.append(
            "- Rescue misses (rescue_miss_action, default Off): Alert counts rescue shots whose "
            "settled moisture fails to rise and tells the grower after rescue_miss_count "
            "consecutive misses. This is hardware/probe evidence, never permission to abandon "
            "or hold watering; a subsequent moisture rise clears the miss run."
        )
    if hasattr(cls, "_watch_tank_estimate"):
        out.append(
            "- Estimated tank level (tank_size_l, default 0/off): only without a mapped level "
            "sensor, count shot litres from the last confirmed/manual fill. Configured flow "
            "is not measured delivery. Low-estimate alerts never drive the reservoir hold."
        )
    if hasattr(cls, "_watch_runoff"):
        out.append(
            "- Sump water balance (runoff_estimator, default off): model runoff and condensate "
            "from sump cycles, feed history, mapped AC/dehumidifier runtime and substrate-water "
            "change. Use the sealed-room daily closure only when its water-balance assumptions "
            "hold. Output is a room-wide or shared-sump estimate with fit/error evidence, "
            "not a measured zone catch and not measured transpiration. A shared sump cannot "
            "be attributed to an individual room or zone without separable evidence. Learning "
            "or unresolvable output is unknown, not zero. Only ai mode adds the estimate as a "
            "hint to AI evidence; shown/shown_alerts do not. Closure/fit warnings do not water, "
            "hold or move settings. A recommendation still needs repeated zone evidence and "
            "the normal enabled power/envelope; this estimate grants no authority to act."
        )
    if not out:
        return []
    return ["", "### 3a. Restored optional modes and evidence", "",
            "The phase and gate descriptions above are the default behavior. These supported "
            "options change it only when explicitly enabled; when the evidence omits a setting, "
            "do not assume it is on.", *out, ""]


def render(codes):
    """The brief, from the code and the error-code table `codes` ([{code, title, meaning, watering}, ...])."""
    from crop_steering_engine.core import CAP_EXEMPT, PHASES, P1_STALL_SHOTS
    from crop_steering_engine import core

    import setpoint_supervisor  # beside the controller

    from . import powers

    import controller  # its constants: the blind grace and the duplicate-controller hold

    blind, dup = controller.BLIND_GRACE_MIN, controller.DUPLICATE_HOLD_S
    out = [PHASE_MACHINE.format(phases=" -> ".join(PHASES), blind=blind, dup=dup,
                                stall=P1_STALL_SHOTS,
                                max_run=controller.MAX_RUN_IN_A_ROW,
                                exempt=", ".join(sorted(k for k, enabled in CAP_EXEMPT.items() if enabled)))]
    out += restored_modes(core, controller)
    out += ["### 4. The settings: each zone's own number for the setting, else the room's, else the controller's "
            "built-in fallback shown here (these are not the fresh-room defaults)", ""]
    out += [f"- {k}: {v:g}" + (f" (range {lo:g}-{hi:g})" if (b := setpoint_supervisor.BOUNDS.get(k)) and
                                (lo := b[0]) is not None and (hi := b[1]) is not None else "")
            for k, v in _settings().items()]
    out += ["", "### 5. What the AI assistant may write, and what moves downstream", ""]
    for power, keys in writable().items():
        out.append(f"- power {power}:")
        for k in keys:
            phase, effect = EFFECTS[k]
            lo_hi = setpoint_supervisor.BOUNDS.get(k)
            rng = f" range {lo_hi[0]:g}-{lo_hi[1]:g} (and the entity's own min/max);" if lo_hi else ""
            out.append(f"  - {k} ({phase}):{rng} {effect}")
    out += ["", "### 6. The AI assistant's powers (one switch per power in each room, ai_power_<key>)", ""]
    out += [f"- {k} (default {'on' if d else 'off'}): {w}" for k, d, w in powers.POWERS]
    out += ["- Off: the judge still asks and its answer is advice in the decision log. On: it acts through the "
            "envelope; set_targets_from_achievable and tune_shot_sizes write the values set as given, clamped only to "
            "the intersection of engine bounds and the entity range. HA refuses rescue + 3 > re-water or "
            "re-water >= peak. Power writes are lasting, not expiring overlays; the targets power stops the "
            "Auto Setpoints follower. Values questions are read once and confidence does not gate writes: "
            "omit uncertain values. Dry run or paused AI changes: nothing acts.", "",
            "### 7. Error codes: what each means, and what the controller does", ""]
    for c in codes:
        meaning = _first(c.get("meaning"))
        does = _first(c.get("watering"))
        out.append(f"- {c['code']} {c.get('title', '')}: {meaning}" + (f" Does: {does}" if does else ""))
    return "\n".join(out) + "\n"


def _first(text):
    """Keep the complete meaning and response, normalised to one line."""
    return " ".join(str(text or "").split())


def load_codes(path=CODES):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["codes"]


def read(path=OUT):
    """The generated brief the image carries, or "" when it is missing."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


if __name__ == "__main__":  # python -m brain.controller_brief --write, from addons/f2_control/f2_control
    from brain import controller_brief as me

    text = me.render(me.load_codes())
    if "--write" in sys.argv:
        with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
