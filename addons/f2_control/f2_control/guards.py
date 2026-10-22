"""Every check a shot passes, as one ordered chain per stage (docs/superpowers/specs/2026-10-22-unified-schema.md
section 2.7). The first check that holds wins, as it always did.

  PASS     Controller._blocked: the act loop's checks of a zone that is to fire. gate_report.report() reads the same
           checks a second time without side effects, one entry per key here, in this order
           (tests/test_guard_chain.py holds the two in step).
  PREOPEN  Controller._execute_shot, just before anything opens.
  SIZED    Controller._act_zone, once the shot's size is known.
  QUEUE    Controller._loop_room, with a supply saved in the integration (sensor.crop_steering_supply_config): why a
           zone about to water waited for the zones watered before it this pass. These never hold (ruling R1): a
           check answers Queued or None, the zone waters either way, and the answer is only journaled and shown.
  DOSE, BATCH, RECIPE, RECIPE_DOSE, PH_*   the dosing runner's checks (guards 18-19, calibration_valid and
           dosing_lockout, with the checks they stand among): `owner` is the DosingRunner, `zone` None. See below.
  DOSE_RUN a timed pump run (prime, calibrate; Task 20). Nothing asks it yet.

Each check is the code that stood inline in those methods, moved word for word: the same reads in the same order,
the same alerts, releases and log lines. A check that raises an alert calls the controller method that holds it
(every alert stays in controller.py, where the error-code list is checked). A check returns why it holds, or None.
`check(owner, room, zone, ctx)`: `owner` is the Controller; `ctx` holds the stage's inputs, and a check that works
something out for the code after the chain (the litres of a shot, its length) leaves it in `ctx`.

Guard ids are the spec's. Those the spec has no id for are marked "not in spec". `code` is the CS code the check
raises or names; None when it has none. A check whose hold has a code of its own returns (why, code).
"""
from __future__ import annotations

import math
import sys
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from crop_steering_engine.guards import capacity_ok
from crop_steering_engine.shot_length import raw_seconds, shot_seconds


@dataclass(frozen=True)
class Guard:
    key: str  # the check's own name (for PASS: gate_report's key)
    guard: str  # the spec's guard id
    stage: str  # pass | preopen | sized
    code: str | None
    check: Callable
    quiet: bool = False  # holds without a word: no log line, nothing journaled
    reports: bool = False  # a SIZED hold _act_zone hands back to the act loop to publish: (False, 0.0, why)


@dataclass(frozen=True)
class Queued:
    """A QUEUE check's answer: the zone waits its turn behind `behind` (the zones ahead of it it waits on). Never a
    hold: it waters after them."""

    behind: tuple


def first(owner, stage, room, zone, ctx):
    """(guard, why, code) of the first check of `stage` that holds, or None. Later checks are not asked. `code` is
    the one the check returned with its hold, else the guard's."""
    for g in stage:
        held = g.check(owner, room, zone, ctx)
        if held:
            why, code = held if isinstance(held, tuple) else (held, g.code)
            return g, why, code
    return None


def _m(c):
    """The controller module: its reads, constants and clock, looked up at call time (tests patch them there)."""
    return sys.modules[type(c).__module__]


# ------------------------------------------------------------------------------------------------- PASS (_blocked)
# ctx: reason (the zone's decision this pass).
def _setup(c, room, zone, ctx):
    if getattr(room, "_setup_pending", None):
        return room._setup_pending
    return None


def _archived(c, room, zone, ctx):
    if getattr(room, "setup_active", True) is False:
        return "Room archived in integration setup"
    return None


def _room_on(c, room, zone, ctx):
    if not c._room_active(room):
        return "Room off (nothing growing)"
    return None


def _dosing(c, room, zone, ctx):
    return c._dosing_hold(room)  # every shot, the rescues a plan hold lets through included


def _plan(c, room, zone, ctx):
    m = _m(c)
    reason = ctx.get("reason")
    planned_hold = m.strategy_block(getattr(room, "strategy_snapshot", None), zone)
    if planned_hold:
        if getattr(reason, "kind", None) not in m.PLAN_HOLD_EXEMPT:
            return planned_hold
        m.log(f"[{room.slug}] Z{zone} {planned_hold}: not holding a {reason.kind} shot")
    return None


def _hardware_fault(c, room, zone, ctx):
    return c._hardware_fault_block(room)


def _max_run(c, room, zone, ctx):
    return c._max_run_hold(room, zone)  # releases a latch whose switch moved


def _valve_mapped(c, room, zone, ctx):
    if not room.hw["valves"].get(zone):
        return (
            "no hardware mapped — set this zone's valve (and the pump and mainline, if the room "
            "has them) in the Crop Steering integration (or the add-on `hardware` option)"
        )
    return None


def _plumbing(c, room, zone, ctx):
    return c._plumbing_gate(room)  # CS-202


def _switchable(c, room, zone, ctx):
    return c._switchable_gate(room, zone)  # CS-313


def _kill_switch(c, room, zone, ctx):
    m = _m(c)
    if not c._on(m.room_gate(room), False):
        return f"{m.PRODUCT} disabled (kill switch off)"
    return None


def _retired(c, room, zone, ctx):
    retired = getattr(room, "_retired_off", None)
    if retired:  # switched off in their place this pass; the switch may not read OFF yet
        return f"{' and '.join(retired)} off: engine switch switched off in its place"
    return None


def _zone_on(c, room, zone, ctx):
    # A zone switch that can't be read holds the zone, as the kill switch does: whether the zone
    # is paused can't be known, and when every one reads unavailable the integration itself is
    # not running (not loaded, disabled, Home Assistant in safe mode), so its overrides can't be
    # read either. A shot already running still ends only on a definite OFF (_wait_shot).
    m = _m(c)
    zone_switch = f"switch.crop_steering_{room.prefix}zone_{zone}_enabled"
    state = m.ha_get(zone_switch)[0]
    if state in (None, "unknown", "unavailable", ""):
        return f"{zone_switch} unreadable (reads neither on nor off)"
    if str(state).lower() not in m.ON_STATES:
        return "zone disabled"
    return None


def _manual_override(c, room, zone, ctx):
    if c._on(f"switch.crop_steering_{room.prefix}zone_{zone}_manual_override", False):
        return "manual override"
    return None


def _external_holds(c, room, zone, ctx):
    # External operator holds (tank dosing / manual fill / flush) are configurable
    # (c.hold_entities, empty by default) — an install without them never holds here.
    # One that can't be read (missing, unknown, unavailable) holds too, as an unreadable zone
    # switch does: whether its tank is being dosed or filled can't be known. A shot already
    # running still ends only on a definite ON (_wait_shot). One Home Assistant answers it does
    # not have (404, a typo or a deleted helper) says so: no wait makes that one readable.
    m = _m(c)
    for f in c.hold_entities:
        state = m.ha_get(f)[0]
        if state is None and m.ha_get_status(f)[0] == 404:
            return m.hold_missing(f)
        if state in (None, "unknown", "unavailable", ""):
            return f"external hold {f} unreadable (reads neither on nor off)"
        if str(state).lower() in m.ON_STATES:
            return f"external hold ({f.split('.')[-1]})"
    return None


def _waste(c, room, zone, ctx):
    return c._waste_hold(room)  # CS-316


def _settings(c, room, zone, ctx):
    return c._settings_hold(room, zone)


def _tank(c, room, zone, ctx):
    return c._tank_hold(room)  # (why, CS-901 or CS-902); only with a tank level mapped


def _feed_ec(c, room, zone, ctx):
    return c._feed_ec_gate(room, zone, ctx.get("reason"))


def _feed_ph(c, room, zone, ctx):
    return c._feed_ph_gate(room, zone, ctx.get("reason"))


def _online(c, room, zone, ctx):
    # Last, once nothing else holds the zone: a switch that reads neither on nor off (its device
    # offline, Home Assistant still starting) accepts a command without switching and cannot be read
    # back after the shot. On 25 Sep 2026 a shot opened onto an offline pump, could not be confirmed
    # closed, and latched a hold that stopped the room for 7 hours. Nothing is opened until the
    # whole feed path reads again, and nothing latches.
    m = _m(c)
    hw = room.hw
    offline = [e for e in (hw.get("pump"), hw.get("mainline"), hw["valves"].get(zone))
               if e and str(m.hw_get(e)[0]).lower() not in ("on", "off")]
    if offline:
        return f"{', '.join(offline)} offline (reads neither on nor off)"
    return None


PASS = tuple(Guard(key, guard, "pass", code, check) for key, guard, code, check in (
    ("setup", "setup_behind", None, _setup),
    ("archived", "kill_switch", None, _archived),
    ("room_on", "kill_switch", None, _room_on),
    ("dosing", "dosing_hold", None, _dosing),
    ("plan", "plan_hold", None, _plan),
    ("hardware_fault", "hardware_latch", "CS-301", _hardware_fault),
    ("max_run", "hardware_latch", "CS-312", _max_run),
    ("valve_mapped", "plumbing", None, _valve_mapped),
    ("plumbing", "plumbing", "CS-202", _plumbing),
    ("switchable", "plumbing", "CS-313", _switchable),
    ("kill_switch", "kill_switch", None, _kill_switch),
    ("retired", "kill_switch", None, _retired),
    ("zone_on", "zone_paused", None, _zone_on),
    ("manual_override", "manual_override", None, _manual_override),
    ("external_holds", "external_hold", None, _external_holds),  # not in spec
    ("waste", "waste_closed", "CS-316", _waste),
    ("settings", "settings_loaded", None, _settings),  # not in spec
    ("tank", "tank_min", "CS-901", _tank),
    ("feed_ec", "source_water", None, _feed_ec),
    ("feed_ph", "source_water", None, _feed_ph),
    ("online", "plumbing", None, _online),
))


# -------------------------------------------------------------------------------- PREOPEN (_execute_shot)
# ctx: duration_s, size_pct, flow_lps, plan_exempt, steering. Leaves "litres", the shot's nominal litres.
def _pre_hardware_fault(c, room, zone, ctx):
    return c._hardware_fault_block(room)


def _pre_auth(c, room, zone, ctx):
    if _m(c)._GATE.state is not None:
        return "Home Assistant refuses this controller's token"
    return None


def _pre_inflight(c, room, zone, ctx):
    if getattr(room, "shot_inflight", None):
        return "an interrupted shot's hardware is not accounted for yet"
    return None


def _pre_plumbing(c, room, zone, ctx):
    return _m(c).plumbing_hold(room.hw)  # never open a valve on a room whose declared pump is not there to run


def _pre_switchable(c, room, zone, ctx):
    undrivable = c._undrivable(room, zone)
    if undrivable:  # never sent a command (_blocked raises CS-313 for it)
        return f"{', '.join(undrivable)} can't be switched"
    return None


def _pre_plan(c, room, zone, ctx):
    # A shot a plan hold never stops (PLAN_HOLD_EXEMPT) does not wait on the plan here either.
    return None if ctx["plan_exempt"] else c._strategy_preflight(room, zone, _m(c).datetime.now())


def _pre_switch_backoff(c, room, zone, ctx):
    # A zone whose pump, main line or valve has not switched on for several shots in a row is tried at
    # most once every SWITCH_ON_BACKOFF_MIN, rescue shots too: a dead valve delivers no rescue water,
    # and retrying it each pass would short-cycle the pump. An operator's Test Shot (the only shot with
    # steering off) is not held: it is how a repair is checked.
    m = _m(c)
    retry_at = m._switch_on_retry_at(room.state[zone]) if ctx["steering"] else None
    if retry_at is not None and m.datetime.now() < retry_at:
        return (f"its pump, main line or valve did not switch on "
                f"{room.state[zone]['on_failures']['count']} shots in a row; next try at {retry_at:%H:%M}")
    return None


def _pre_tank_short(c, room, zone, ctx):
    # Freeze hydraulic sizing before opening hardware. Editing plant count,
    # substrate or dripper configuration mid-shot must not rewrite its litres.
    flow_lps, duration_s, size_pct = ctx["flow_lps"], ctx["duration_s"], ctx["size_pct"]
    ctx["litres"] = (flow_lps * duration_s if flow_lps is not None
                     else size_pct / 100.0 * c._substrate_l(room, zone))
    # the plan-ahead half of the reservoir minimum: _tank_plan asks for the refill
    return c._tank_short(room, zone, ctx["litres"])


def _pre_waste(c, room, zone, ctx):
    if not c._close_waste(room, zone):  # Close for each shot: a waste valve still open, nothing opens
        return "the waste valve did not close"
    return None


def _pre_dosing(c, room, zone, ctx):
    with c._shot_lock:  # a batch holds rooms under this lock (see _shot_running)
        making = c._dosing_hold(room)
        if not making:
            c._busy = True
            c._shot_room = room  # the room whose shot is in flight right now (see _safe_off)
    return making


PREOPEN = (
    Guard("hardware_fault", "hardware_latch", "preopen", "CS-301", _pre_hardware_fault, quiet=True),
    Guard("auth", "auth", "preopen", None, _pre_auth),
    Guard("inflight", "inflight", "preopen", None, _pre_inflight),
    Guard("plumbing", "plumbing", "preopen", "CS-202", _pre_plumbing),
    Guard("switchable", "plumbing", "preopen", "CS-313", _pre_switchable),
    Guard("plan", "plan_hold", "preopen", None, _pre_plan),
    Guard("switch_backoff", "switch_backoff", "preopen", None, _pre_switch_backoff),  # not in spec (#208)
    Guard("tank_short", "tank_min", "preopen", "CS-901", _pre_tank_short),
    Guard("waste_close", "waste_closed", "preopen", "CS-316", _pre_waste),
    Guard("dosing", "dosing_hold", "preopen", None, _pre_dosing),  # last: passing it marks the shot in flight
)


# ------------------------------------------------------------------------------------------- SIZED (_act_zone)
# ctx: reason, size, test, p, st, snap. Leaves flow, raw_dur, max_dur, and the shot's size and dur.
def _sizing(c, room, zone, ctx):
    ctx["flow"], ctx["substrate"], why = c._shot_sizing(room, zone)  # CS-204
    return why


def _max_shot(c, room, zone, ctx):
    m = _m(c)
    reason = ctx["reason"]
    timed = ctx["test"] or getattr(reason, "kind", None) == "timer"  # a test shot or a timer slot asks for seconds
    raw_dur = (float(getattr(reason, "seconds", m.TEST_SHOT_S)) if timed
               else raw_seconds(ctx["size"], ctx["substrate"], ctx["flow"]))
    ctx["raw_dur"] = raw_dur
    ctx["max_dur"] = max_dur = c._room_duration_cap(room)  # #201: the last good cap through a read blip (CS-203)
    if max_dur is None:
        return "maximum shot length not valid"
    # Hydraulic sizing determines nominal runtime; the room's duration
    # limit bounds every physical shot independently of its requested volume.
    ctx["dur"] = shot_seconds(raw_dur, max_dur)
    if raw_dur > max_dur:
        c._alert_shot_cut(room, zone, raw_dur, max_dur)  # CS-306: it runs, cut
    return None


def _daily_cap(c, room, zone, ctx):
    # A shot that is not exempt from the daily budget gets only what is left of it (22 Sep: a
    # 607 s, ~28 L flush fired with ~2 L of an 80 L budget left). Copied / blind-schedule
    # decisions are never exempt either (their Reason, or plain text, is not cap_exempt).
    m = _m(c)
    p, st, reason, flow, dur = ctx["p"], ctx["st"], ctx["reason"], ctx["flow"], ctx["dur"]
    if p is not None and not getattr(reason, "cap_exempt", False):
        left_l = p.max_daily_volume - float(st.get("daily_vol") or 0.0)
        allowed = int(left_l / flow) if left_l > 0 else 0
        if allowed < m.MIN_SHOT_S:
            held = f"BLOCK daily-cap ({max(left_l, 0.0):.2f} L left)"
            c._alert_daily_cap(room, zone, st, ctx["snap"] is None, held)  # CS-205
            m.log(f"[{room.slug}] Z{zone} {st['phase']} hold — {held}: would {reason}")
            return held
        if dur > allowed:
            m.log(f"[{room.slug}] Z{zone} shot clipped {dur}s -> {allowed}s: {left_l:.2f} L of the daily budget left")
            ctx["size"], ctx["dur"] = round(ctx["size"] * allowed / dur, 2), allowed
    return None


SIZED = (
    Guard("sizing", "shot_sizing", "sized", "CS-204", _sizing),  # not in spec
    Guard("max_shot", "max_shot", "sized", "CS-203", _max_shot),  # not in spec (#201)
    Guard("daily_cap", "daily_cap", "sized", "CS-205", _daily_cap, reports=True),
)


# ------------------------------------------------------------------------------------------- QUEUE (_loop_room)
# ctx: lph (the zone's demand in L/h, None unknown), ahead [(zone, lph)] (the zones watered before it this pass),
# pump {max_flow_lph, max_concurrent_zones} (its row of the supply, {} when not listed), groups {zone: group}.
def _pump_capacity(c, room, zone, ctx):
    pump, ahead = ctx["pump"], ctx["ahead"]
    running = [lph or 0.0 for _z, lph in ahead]
    if capacity_ok(running, ctx["lph"] or 0.0, pump.get("max_flow_lph"), pump.get("max_concurrent_zones") or 1):
        return None
    return Queued(tuple(z for z, _lph in ahead))


def _exclusive_group(c, room, zone, ctx):
    group = ctx["groups"].get(zone)
    behind = tuple(z for z, _lph in ctx["ahead"] if group is not None and ctx["groups"].get(z) == group)
    return Queued(behind) if behind else None


QUEUE = (
    Guard("pump_capacity", "pump_capacity", "queue", None, _pump_capacity),
    Guard("exclusive_group", "exclusive_group", "queue", None, _exclusive_group),  # recorded only (R1)
)


# ------------------------------------------------------------------------------------------- DOSING (dosing_runner)
# `owner` is the DosingRunner (its controller is owner.c), `zone` None; _m(owner) is dosing_runner. Each stage is the
# checks one runner method made inline, moved word for word, in their order: the same reads, the same words.
class Why(str):
    """A refusal's words, which also name the guard and code that refused (`hit` is first()'s answer). A runner check
    that answers in words (_dose_check, _batch_check) still answers a string; the caller that journals reads
    .guard and .code."""

    def __new__(cls, hit):
        g, why, code = hit
        words = super().__new__(cls, why)
        words.guard, words.code = g.guard, code
        return words


# DOSE (DosingRunner._dose_check), every dose: ctx pump, ml, profile. Leaves flow.
def _dose_calibrated(r, room, zone, ctx):
    return r._uncalibrated(ctx["pump"], ctx["profile"])


def _dose_amount(r, room, zone, ctx):
    pump, ml = ctx["pump"], ctx["ml"]
    ctx["flow"] = r._device(pump["flow_entity"], "flow")[0]
    if (isinstance(ml, bool) or not isinstance(ml, (int, float)) or not math.isfinite(ml)
            or not 0 < ml <= float(pump.get("max_ml") or 0)):
        fmt = _m(r)._fmt
        return f"{fmt(ml)} mL is not more than 0 and at most {fmt(pump.get('max_ml'))} mL"
    return None


def _dose_too_long(r, room, zone, ctx):
    pump, ml, flow, profile = ctx["pump"], ctx["ml"], ctx["flow"], ctx["profile"]
    if ml / flow > profile["max_dose_s"]:
        return r._too_long(pump, ml, flow, profile)
    return None


def _dose_pump_dosing(r, room, zone, ctx):
    pump = ctx["pump"]
    dosing = r._dosing(pump)[0]
    if dosing is True:
        return f"{pump['name']} already reads dosing"
    if dosing is None:  # it could not be watched
        return f"{pump['name']}'s dosing state ({pump['dosing_entity']}) can't be read"
    return None


def _dose_by_hand(r, room, zone, ctx):
    pump = ctx["pump"]
    if str(r._hw_state(pump["power_entity"])).strip().lower() == "on":
        return f"{pump['name']} is running by hand"  # its power is its motor's own switch
    return None


DOSE = (
    Guard("calibrated", "calibration_valid", "dose", None, _dose_calibrated),
    Guard("amount", "dose_amount", "dose", None, _dose_amount),  # not in spec
    Guard("too_long", "dose_amount", "dose", None, _dose_too_long),  # not in spec
    Guard("pump_dosing", "dosing_lockout", "dose", None, _dose_pump_dosing),
    Guard("by_hand", "dosing_lockout", "dose", None, _dose_by_hand),
)


# BATCH (DosingRunner._batch_check, before its recipe): ctx batch.
def _batch_fault(r, room, zone, ctx):
    if r.c._hardware_fault_block(room):
        return "the room has a hardware fault latched"
    return None


def _batch_hold(r, room, zone, ctx):
    hold = ctx["batch"].get("hold_entity")
    if hold:
        state = r._state(hold)
        if _m(r)._dead(state):
            return f"{hold} can't be read"
        if state.strip().lower() == "on":
            return f"{hold} is on already: something else is dosing"
    return None


def _batch_full_sensor(r, room, zone, ctx):
    batch = ctx["batch"]
    if batch.get("fill_valve") and r._full(batch) is None:
        return "the tank's full sensor can't be read"
    return None


def _batch_mix_power(r, room, zone, ctx):
    batch = ctx["batch"]
    if (batch.get("mix_pump") and float(batch.get("mix_min_w") or 0) > 0
            and not batch.get("mix_power_sensor")):
        return "the mix pump has a minimum power but no power sensor to read it"
    return None


BATCH = (
    Guard("hardware_fault", "hardware_latch", "batch", "CS-301", _batch_fault),
    Guard("hold", "dosing_lockout", "batch", None, _batch_hold),
    Guard("full_sensor", "tank_overfill", "batch", None, _batch_full_sensor),
    Guard("mix_power", "dosing_lockout", "batch", None, _batch_mix_power),
)


# RECIPE (each recipe line): ctx item, pumps. Leaves pump, and ml as read (before it is made whole).
def _recipe_pump(r, room, zone, ctx):
    item = ctx["item"]
    ctx["pump"] = pump = ctx["pumps"].get(item.get("pump"))
    if pump is None:
        return f"the recipe doses {item.get('pump')}, which is not set up"
    return None


def _recipe_ml(r, room, zone, ctx):
    item, pump = ctx["item"], ctx["pump"]
    ml = item.get("ml") or 0
    if item.get("ml_entity"):  # it wins over the fixed mL, and is never replaced by it
        ml = r._device(item["ml_entity"], "volume")[0]
        if ml is None:
            return f"the recipe amount for {pump['name']} can't be read"
    ctx["ml"] = ml
    return None


RECIPE = (
    Guard("recipe_pump", "recipe", "batch", None, _recipe_pump),  # not in spec
    Guard("recipe_ml", "recipe", "batch", None, _recipe_ml),  # not in spec
)


# RECIPE_DOSE (each recipe line not skipped): ctx pump, ml (whole), profile. Leaves flow.
def _recipe_max_ml(r, room, zone, ctx):
    pump, ml = ctx["pump"], ctx["ml"]
    if ml > float(pump.get("max_ml") or 0):
        fmt = _m(r)._fmt
        return f"{fmt(ml)} mL of {pump['name']} is more than its {fmt(pump['max_ml'])} mL"
    return None


def _recipe_too_long(r, room, zone, ctx):
    pump, ml, profile = ctx["pump"], ctx["ml"], ctx["profile"]
    ctx["flow"] = flow = r._device(pump["flow_entity"], "flow")[0]
    if ml / flow > profile["max_dose_s"]:
        return r._too_long(pump, ml, flow, profile)
    return None


RECIPE_DOSE = (
    Guard("max_ml", "dose_amount", "batch", None, _recipe_max_ml),  # not in spec
    Guard("calibrated", "calibration_valid", "batch", None, _dose_calibrated),
    Guard("too_long", "dose_amount", "batch", None, _recipe_too_long),  # not in spec
)


# pH auto-correct (DosingRunner._ph_tick, once the tank needs correcting), four stages in this order: PH_LOCK holds,
# PH_SETUP refuses (_ph_refuse, CS-809), PH_WAIT holds (it waits, without a word), PH_DOSE refuses (CS-809).
# ctx config, way. Leaves fill, pump, s, left, flow, ml.
def _ph_latch(r, room, zone, ctx):
    ctx["fill"] = fill = r._ph_fill(ctx["config"])
    with r._lock:
        latch = deepcopy(r._ph_block(room)["latch"])
    if latch:
        if fill is None or _m(r)._dead(fill) or fill == latch.get("fill"):
            return "pH auto-correct is locked until a person switches it off or the tank is filled again"
        r._ph_unlatch(room, "the tank was filled again")
    return None


def _ph_pump(r, room, zone, ctx):
    way = ctx["way"]
    ctx["pump"] = next((p for p in ctx["config"]["pumps"] if p.get("ph_role") == _m(r).ph_correct.ROLES[way]), None)
    if ctx["pump"] is None:
        return f"no dosing pump has the pH {way} role (Equipment > Dosing, Dosing setup)"
    return None


def _ph_mix_pump(r, room, zone, ctx):
    if not ctx["config"]["batch"].get("mix_pump"):
        return "the batch tank has no mixing pump set up, and a dose is never made into a tank that is not mixed"
    return None


def _ph_mix_power(r, room, zone, ctx):
    batch = ctx["config"]["batch"]
    if float(batch.get("mix_min_w") or 0) > 0 and not batch.get("mix_power_sensor"):
        return "the mixing pump has a minimum power but no power sensor to read it"
    return None


def _ph_calibrated(r, room, zone, ctx):
    return r._uncalibrated(ctx["pump"], _m(r)._profile(ctx["config"]))


def _ph_hold(r, room, zone, ctx):
    hold = ctx["config"]["batch"].get("hold_entity")
    if hold and str(r._state(hold)).strip().lower() != "off":
        return f"{hold} does not read off: something else is dosing, or it can't be read"
    return None


def _ph_mixing(r, room, zone, ctx):
    mix = ctx["config"]["batch"]["mix_pump"]
    if r._hw_state(mix) != "off":
        return f"{mix} does not read off: the tank is being mixed or pumped already"
    return None


def _ph_fault(r, room, zone, ctx):
    return r.c._hardware_fault_block(room)


def _ph_duplicate(r, room, zone, ctx):
    if r.c.duplicate_hold(room):
        return "another controller is driving this room"
    return None


def _ph_daily_max(r, room, zone, ctx):
    ctx["s"] = s = r._ph_settings(room)
    with r._lock:
        block = r._ph_block(room)
        used = block["doses"] if block["day"] == r._today() else 0
    ctx["left"] = left = int(s["daily_max"]) - used
    if left <= 0:
        return f"the {int(s['daily_max'])} doses a day it may give are used"
    return None


def _ph_dose_ml(r, room, zone, ctx):
    pump, s = ctx["pump"], ctx["s"]
    ctx["flow"] = flow = r._device(pump["flow_entity"], "flow")[0]
    ctx["ml"] = ml = _m(r).ph_correct.dose_ml(s["dose_s"], flow, float(pump.get("max_ml") or 0))
    if ml <= 0:
        return f"a {s['dose_s']:g} s dose of {pump['name']} is less than 1 mL"
    return None


PH_LOCK = (Guard("latch", "dosing_lockout", "ph", "CS-809", _ph_latch),)
PH_SETUP = (
    Guard("ph_pump", "dosing_lockout", "ph", "CS-809", _ph_pump),
    Guard("mix_pump", "dosing_lockout", "ph", "CS-809", _ph_mix_pump),
    Guard("mix_power", "dosing_lockout", "ph", "CS-809", _ph_mix_power),
    Guard("calibrated", "calibration_valid", "ph", "CS-809", _ph_calibrated),
)
PH_WAIT = (
    Guard("hold", "dosing_lockout", "ph", None, _ph_hold),
    Guard("mixing", "dosing_lockout", "ph", None, _ph_mixing),
    Guard("hardware_fault", "hardware_latch", "ph", "CS-301", _ph_fault),
    Guard("duplicate", "duplicate_controller", "ph", None, _ph_duplicate),  # not in spec
)
PH_DOSE = (
    Guard("daily_max", "dosing_lockout", "ph", "CS-809", _ph_daily_max),
    Guard("dose_ml", "dose_amount", "ph", "CS-809", _ph_dose_ml),  # not in spec
)


# DOSE_RUN: a timed run of one pump's power (Task 20's prime and calibrate). ctx pump, profile, action, batch.
def _run_inflight(r, room, zone, ctx):
    if getattr(room, "shot_inflight", None):
        return "a shot is in flight in this room"
    return None


def _run_calibrated(r, room, zone, ctx):
    if ctx["action"] == "calibrate":  # the calibration run is how a pump gets its flow
        return None
    return r._uncalibrated(ctx["pump"], ctx["profile"])


DOSE_RUN = (
    Guard("hardware_fault", "hardware_latch", "dose_run", "CS-301", _ph_fault),
    Guard("inflight", "inflight", "dose_run", None, _run_inflight),
    Guard("calibrated", "calibration_valid", "dose_run", None, _run_calibrated),
    Guard("hold", "dosing_lockout", "dose_run", None, _batch_hold),
)
