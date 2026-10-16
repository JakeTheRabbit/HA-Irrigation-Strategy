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
  reaches its target (vegetative_dryback_target or generative_dryback_target by the zone's steering mode, plus
  p0_additional_dryback); P0 has lasted p0_maximum_wait_time minutes. Dryback is relative to the peak:
  (peak - VWC) / peak x 100.
- P1 (the ramp): shots of p1_initial_shot_size, growing by p1_shot_size_increment, every p1_time_between_shots
  minutes, until moisture reaches min(p1_target_vwc, field_capacity); then one more shot, and P1 hands over to P2
  when a shot no longer raises the zone's highest reading by p1_rise_pts (the rise rule), after
  p1_maximum_extra_shots extra shots, at p1_maximum_shots, or at the target with the daily budget spent. P1 has no
  time exit: a gated zone waits in P1 and resumes.
- P2 (maintenance): a shot of p2_shot_size when moisture falls under the re-water point (with the EC steer's offset
  baked in, clamped between rescue + 3 and the ramp ceiling - 1), at most every p2_time_between_shots minutes. P2 ->
  P3 early only when a dryback started now would end by lights-on (predictive P3), otherwise at lights-off.
- P3 (night): only a rescue shot of p3_emergency_shot_size when moisture falls under the rescue floor
  (p3_emergency_vwc_threshold), at most every p3_time_between_shots minutes.
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
1. The room's kill switch (engine switch) and any hold entity: off or unreadable, no valve opens.
2. The source-water gate: feed pH and EC inside their bands, a dead probe holds the shot.
3. Hardware sequencing: pump prime (pump_prime_time), main line (main_line_lead_time), zone valve, then the reverse;
   valve close is read back, and a failed read-back stops the pump and aborts the shot.
4. The max-run latch: shots that keep running into the room's longest shot latch the zone (CS-312).
5. The duplicate-controller lease: another controller's heartbeat holds the room for {dup} s.
6. The EC step rule: in P2 the EC steer moves the re-water offset by steps, at most once per ec_min_interval minutes.
7. Plan adherence: an armed grow plan owns the room's targets; drift from it raises CS-713.
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


def render(codes):
    """The brief, from the code and the error-code table `codes` ([{code, title, meaning, watering}, ...])."""
    from crop_steering_engine.core import CAP_EXEMPT, PHASES

    import setpoint_supervisor  # beside the controller

    from . import powers

    import controller  # its constants: the blind grace and the duplicate-controller hold

    blind, dup = controller.BLIND_GRACE_MIN, controller.DUPLICATE_HOLD_S
    out = [PHASE_MACHINE.format(phases=" -> ".join(PHASES), blind=blind, dup=dup,
                                exempt=", ".join(sorted(CAP_EXEMPT)))]
    out += ["### 4. The settings: each zone's own number for the setting, else the room's, else the controller's "
            "built-in value shown here", ""]
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
            "each setting's range. Dry run (brain_dry_run): every acting answer is journalled 'would act', nothing is "
            "written.", "", "### 7. Error codes: what each means, and what the controller does", ""]
    for c in codes:
        meaning = _first(c.get("meaning"))
        does = _first(c.get("watering"))
        out.append(f"- {c['code']} {c.get('title', '')}: {meaning}" + (f" Does: {does}" if does else ""))
    return "\n".join(out) + "\n"


def _first(text):
    """The first sentence of `text`."""
    text = " ".join(str(text or "").split())
    i = text.find(". ")
    return text if i < 0 else text[: i + 1]


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


if __name__ == "__main__":  # python -m jev.controller_brief --write, from addons/f2_control/f2_control
    from jev import controller_brief as me

    text = me.render(me.load_codes())
    if "--write" in sys.argv:
        with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
