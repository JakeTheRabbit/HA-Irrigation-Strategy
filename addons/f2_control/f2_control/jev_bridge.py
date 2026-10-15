"""The controller's side of Jev: build the brain, feed it each zone's pass, apply what it admits.

Every function here is called inside a try/except in the controller: whatever goes wrong in Jev, the
zone is decided and watered by the base engine exactly as it would be without it (docs/JEV.md).
"""
from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timedelta

from jev.brain import Brain
from jev.client import Asker, Route, Routes, call, call_typesafe
from jev.context import Shot, ZoneContext, ZoneHistory, response, words_response
from jev.doctrine import stage_intent
from jev.judges.dawn import DawnJudge
from jev.judges.dusk import DuskJudge
from jev.judges.night import NightJudge
from jev.judges.probe import ProbeJudge
from jev.judges.ramp import RampJudge
from jev.judges.salt import SaltJudge
from jev.judges.setpoints import CHOICES, SHOT, THRESHOLD, SetpointsJudge
from jev.judges.setpoints import band as setpoint_band
from jev.judges.shot import ShotJudge
from jev.judges.stage import StageJudge
from jev.judges.zones import ZonesJudge
from jev.journal import Journal
from jev.ledger import Ledger
from jev.setpoint_memory import SetpointMemory

ALL = ("dawn", "ramp", "salt", "dusk", "probe", "shot", "night", "zones", "stage", "setpoints")
PENDING_S = 300  # a write Home Assistant has not reflected yet is not an operator's edit for this long
RETRIES = 3  # a write still not read back is sent again this many times, PENDING_S apart and doubling, then failed
REVERT_WINDOW_H = 30  # a rescue shot this soon after a setpoint change puts the old value back
PAUSE_H = 48  # and the zone's setpoints are left alone this long
# Only Jev's own code writes these into /data, so any one of them (empty or unreadable too) says Jev has run here.
JEV_FILES = ("jev_usage.json", "jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json")
PRODUCT = "Crop Steering Controller"  # controller.PRODUCT: the `engine` value on what Jev publishes


def judges():
    return [DawnJudge(), RampJudge(), SaltJudge(), DuskJudge(), ProbeJudge(), ShotJudge(), NightJudge(),
            ZonesJudge(), StageJudge(), SetpointsJudge()]


def routes(options, cf):
    """Every route Jev has, in the order they are tried: TypeSafe direct when its key is set, then Cloudflare's
    /ai/run when its account and token are."""
    account, token, gateway = cf
    found = []
    typesafe = str(options.get("typesafe_api_key") or "").strip()
    if typesafe:
        found.append(Route("TypeSafe", call_typesafe, "typesafe", typesafe))
    if account and token:
        found.append(Route("Cloudflare", call, account, token, gateway or None))
    return found


def has_run(data):
    """True when a file only Jev writes is in `data` (the state file's folder): this install has run Jev before."""
    return any(os.path.lexists(os.path.join(data, name)) for name in JEV_FILES)


def build(options, cf, state_path, log):
    """The brain, or None when Jev is off (no route: no TypeSafe key and no Cloudflare credentials; or `jev_enabled`
    false). Every route it has is used, TypeSafe first, each retried while a failure may pass (jev.client.Routes).

    A TypeSafe key starts it as it is: only the Jev line has that option. Cloudflare credentials alone start it only
    where Jev has run before (has_run): an install updated from a line without Jev may have set them for the Auto
    Setpoints check, and that must not switch an acting brain on."""
    found = routes(options, cf)
    if options.get("jev_enabled", True) is False or not found:
        return None
    data = os.path.dirname(state_path) or "."
    if found[0].name != "TypeSafe" and not has_run(data):
        log("jev: off. The Cloudflare credentials start Jev only on an install that has run it before, and no Jev"
            f" file is in {data}; they still serve the Auto Setpoints check")
        return None
    wanted = str(options.get("jev_judges") or "all").replace(" ", "")
    allowed = set(ALL) if wanted in ("", "all") else set(wanted.split(",")) & set(ALL)
    first = found[0]
    asker = Asker(first.account, first.token, first.gateway, daily_budget=int(options.get("jev_daily_calls", 5000)),
                  transport=Routes(found, tries=int(options.get("jev_retries", 3))),
                  warn_pct=float(options.get("jev_budget_warn_pct", 80)))
    ledger = Ledger(os.path.join(data, "jev_ledger.jsonl"))
    names = [r.name for r in found]
    log(f"jev: on via {' then '.join(names)}, judges {', '.join(sorted(allowed))}, {asker.daily_budget} calls a day")
    brain = Brain(asker, ledger, judges(), allowed=allowed, log=log,
                  reask_max=int(options.get("jev_reask_max", 2)),
                  unsure_below=float(options.get("jev_unsure_below", 0.7)),
                  strict_after=int(options.get("jev_strict_after", 3)),
                  strict_prob=float(options.get("jev_strict_prob", 0.8)))
    brain.routes = names
    brain.journal = Journal(os.path.join(data, "jev_journal.jsonl"))
    brain.setpoints = SetpointMemory(os.path.join(data, "jev_setpoints.json"))
    brain.usage_path = os.path.join(data, "jev_usage.json")
    restore_usage(asker, brain.usage_path)
    brain.flower_start = flower_option(options.get("jev_flower_start"))
    brain.flower_days = int(options.get("jev_flower_days") or 56)
    return brain


def flower_option(value):
    """`jev_flower_start`: one entity or date for every room, or `room=value` pairs, comma separated.
    e.g. "input_datetime.flip" or "default=input_datetime.f2_flip_date, f1=input_datetime.f1_flip_date"."""
    out = {}
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        room, sep, val = part.partition("=")
        out[room.strip() if sep else "*"] = (val if sep else room).strip()
    return out


def flower_day(c, room, now):
    """Day of flower for the room (day 1 = the first day of 12/12), or None when the room doesn't say."""
    brain = c.jev
    val = getattr(brain, "flower_start", {}).get(room.slug) or getattr(brain, "flower_start", {}).get("*")
    if not val:
        return None
    raw = c._jev_read(val) if "." in val and not val[:4].isdigit() else val
    try:
        start = datetime.fromisoformat(str(raw).strip()[:10]).date()
    except (TypeError, ValueError):
        return None
    day = (now.date() - start).days + 1
    return day if day >= 1 else None


def _hist(room, zone):
    store = room.__dict__.setdefault("_jev_hist", {})
    return store.setdefault(zone, ZoneHistory())


def zone_context(c, room, zone, snap, p, now, lights_on):
    st = room.state[zone]
    plants = c._zone_num(room, zone, "plant_count", 0)
    fday = flower_day(c, room, now)
    fdays = getattr(c.jev, "flower_days", 56)
    return ZoneContext(
        flower_day=fday, flower_days=fdays, stage=stage_intent(fday, fdays),
        steering="vegetative" if c._veg(room, zone) else "generative",
        room=room.slug, prefix=room.prefix, zone=zone, title=c._zone_title(room, zone), now=now,
        phase=st["phase"], snap=snap, params=p, history=_hist(room, zone), lights_on=lights_on,
        hours_to_on=c._hours_to(now, room.lights_on_hour), hours_to_off=c._hours_to(now, room.lights_off_hour),
        siblings={z: v for z, v in room.__dict__.get("_jev_sib", {}).items() if z != zone},
        plants=int(plants) if plants and float(plants).is_integer() else None,
        feed_ec=getattr(snap, "feed_ec", None) if snap is not None else None,
        probe_entity=c._fused_id(room.prefix, "vwc", zone, room.zones[zone].get("vwc")),
        # read only in the night, where the Setpoints judge runs: an edit by hand is caught before it is asked
        setpoints=setpoint_view(c, room, zone, p, now) if st["phase"] == "P3" else None,
    )


def tick(c, room, zone, snap, p, now, lights_on):
    """Record this pass's reading, run the judges, raise their alerts, apply a setpoint move.
    -> {kind: Directive} for the controller's pass (advance, distrust, ec_mode)."""
    _hist(room, zone).add_reading(now, snap.vwc, snap.ec)
    readback(c, room, zone, now)
    guard_setpoints(c, room, zone, now)
    ctx = zone_context(c, room, zone, snap, p, now, lights_on)
    out = {}
    for d, _why in c.jev.tick(ctx):
        if d.kind == "alert":
            c._jev_alert(room, zone, d.judge, d.value)
        elif d.kind == "setpoint":
            apply_setpoint(c, room, zone, d, ctx, now)
        else:
            out[d.kind] = d
    return out


# ---------- the Setpoints judge's side (docs/JEV.md) ----------
def owns_setpoints(c):
    """True when Jev's Setpoints judge runs: it then owns each zone's P2 shot size and re-water threshold."""
    brain = getattr(c, "jev", None)
    return brain is not None and any(j.name == "setpoints" for j in getattr(brain, "judges", ()))


def judge_levers(c):
    """The zone numbers the Setpoints judge writes, or () when it does not run. The base engine's own Auto Setpoints
    learner writes the others (controller._auto_tick), so each lever has exactly one writer."""
    return (SHOT, THRESHOLD) if owns_setpoints(c) else ()


def _zone_number(c, room, zone, suffix):
    """The zone's OWN number for `suffix`, or None: Jev never moves a room-level value."""
    raw = c._jev_read(f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}")
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def _note(c, room, zone, verdict, action, result, reason):
    journal = getattr(c.jev, "journal", None)
    if journal is not None:
        journal.add({"t": datetime.now().isoformat(timespec="seconds"), "room": room.slug, "zone": zone,
                     "judge": "setpoints", "title": "Setpoints", "kind": "decision", "verdict": verdict,
                     "p": None, "agreed": None, "action": action, "result": result, "reason": reason[:120]})


def setpoint_view(c, room, zone, p, now):
    """What the Setpoints judge may move on this zone tonight (ZoneContext.setpoints), or None.

    The operator's own value ("home") is the centre of each band. A value Jev did not write is the operator's:
    it becomes the new home, so an edit by hand always wins and the band follows it."""
    mem = getattr(getattr(c, "jev", None), "setpoints", None)
    if mem is None or not owns_setpoints(c):
        return None
    rec = mem.zone(room.slug, zone)
    current, changed = {}, False
    pending = rec.get("pending") or {}
    # a write still being read back (readback) is never an edit; one an older memory left waits PENDING_S
    fresh = pending and ("to" in pending or (now - datetime.fromisoformat(pending["at"])).total_seconds() < PENDING_S)
    for suffix in (SHOT, THRESHOLD):
        v = _zone_number(c, room, zone, suffix)
        if v is None:
            continue
        current[suffix] = v
        if fresh and pending.get("suffix") == suffix and abs(v - pending["from"]) < 1e-6:
            continue  # Jev's write has not reached Home Assistant yet
        expected = rec["written"].get(suffix, rec["home"].get(suffix))
        if expected is None or abs(v - float(expected)) > 1e-6:
            home = rec["home"].get(suffix)
            # Back on the operator's own value (an AI overlay that ran out or was undone): no edit by hand.
            if expected is not None and (home is None or abs(v - float(home)) > 1e-6):
                _note(c, room, zone, "set by hand", f"{suffix.replace('_', ' ')} {expected:g} -> {v:g}",
                      "acted", "your value is the new centre of Jev's range")
            rec["home"][suffix] = v
            rec["written"].pop(suffix, None)
            changed = True
    if pending and not fresh:
        rec["pending"], changed = None, True
    if changed:
        mem.save()
    last = rec.get("last") or {}
    day = c._grow_day_start(room, now).isoformat()
    frozen = rec.get("frozen_until")
    frozen = frozen if frozen and datetime.fromisoformat(frozen) > now else None
    enabled = (c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)
               and not getattr(room, "strategy_required", False))
    return {
        "enabled": bool(enabled), "current": current, "home": dict(rec["home"]),
        "bands": {s: setpoint_band(s, rec["home"][s], p) for s in current},
        "changed_today": last.get("day") == day, "frozen": frozen, "day": day,
        "last_words": _last_words(last),
    }


def _last_words(last):
    if not last:
        return None
    return (f"{last.get('at', '')[:16].replace('T', ' ')}: {last.get('words')}"
            + (" (did not reach Home Assistant)" if last.get("failed")
               else " (put back after a rescue shot)" if last.get("reverted") else ""))


def _pending(suffix, frm, to, by, now):
    """A write to read back: sent once now, again RETRIES times, PENDING_S apart and doubling, while it has not landed."""
    return {"suffix": suffix, "from": frm, "to": to, "by": by, "at": now.isoformat(timespec="seconds"),
            "tries": 0, "next": (now + timedelta(seconds=PENDING_S)).isoformat(timespec="seconds")}


def readback(c, room, zone, now):
    """Read back the zone's number after a Jev write (SF-25): landed, it is done; an edit by hand since then is the
    operator's (setpoint_view); still the old value or unreadable, it is sent again with a doubling wait, and after
    RETRIES it is recorded as failed and Jev's memory goes back to the value Home Assistant still holds."""
    mem = getattr(getattr(c, "jev", None), "setpoints", None)
    rec = None if mem is None else mem.zone(room.slug, zone)
    pend = (rec or {}).get("pending") or {}
    if "to" not in pend:
        return  # nothing to read back, or a pending write an older memory left (setpoint_view times it out)
    suffix, frm, to = pend["suffix"], float(pend["from"]), float(pend["to"])
    cur = _zone_number(c, room, zone, suffix)
    if cur is not None and abs(cur - frm) > 1e-6:
        rec["pending"] = None  # landed, or set by hand since: either way nothing is left to send
        mem.save()
        return
    if now < datetime.fromisoformat(pend["next"]):
        return
    # Jev's own move stops when the operator stops automatic targets; a put-back restores theirs, so it never does
    allowed = pend["by"] != "Jev" or (owns_setpoints(c) and not getattr(room, "strategy_required", False)
                                      and c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False))
    if allowed and pend["tries"] < RETRIES:
        pend["tries"] += 1
        pend["next"] = (now + timedelta(seconds=PENDING_S * 2 ** pend["tries"])).isoformat(timespec="seconds")
        learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
        c._auto_write(room, zone, suffix, frm, to, learn, now, by=pend["by"])
        mem.save()
        return
    rec["pending"] = None
    rec["written"][suffix] = frm  # what Home Assistant still holds is not an edit by hand
    last = rec.get("last") or {}
    if pend["by"] == "Jev" and last.get("suffix") == suffix and last.get("to") == to:
        last["failed"] = True
    mem.save()
    why = (f"Home Assistant still shows {frm:g} after {pend['tries'] + 1} tries" if allowed
           else "automatic targets were switched off before it landed")
    _note(c, room, zone, "write failed", f"{suffix.replace('_', ' ')} {frm:g} -> {to:g}", "failed", why)


def apply_setpoint(c, room, zone, d, ctx, now):
    """Write one admitted notch to the zone's own number and remember it."""
    v = d.value
    mem = c.jev.setpoints
    rec = mem.zone(room.slug, zone)
    learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
    c._auto_write(room, zone, v["suffix"], float(v["from"]), float(v["to"]), learn, now, by="Jev")
    rec["written"][v["suffix"]] = float(v["to"])
    rec["pending"] = _pending(v["suffix"], float(v["from"]), float(v["to"]), "Jev", now)
    rec["last"] = {"suffix": v["suffix"], "from": float(v["from"]), "to": float(v["to"]),
                   "at": now.isoformat(timespec="seconds"), "day": (ctx.setpoints or {}).get("day"),
                   "words": v["words"], "choice": v["choice"], "reverted": False}
    mem.save()
    # For the phones that tick Jev (docs/NOTIFICATIONS.md): no card, a push only.
    c._notify_event("jev_setpoint", room, zone, v["words"],
                    f"{CHOICES.get(v['choice'], v['choice'])} Jev's Setpoints judge, {d.why}.")


def guard_setpoints(c, room, zone, now):
    """A rescue shot soon after a setpoint change puts the old value back and pauses the zone (CS-404)."""
    mem = getattr(getattr(c, "jev", None), "setpoints", None)
    if mem is None:
        return
    rec = mem.zone(room.slug, zone)
    last = rec.get("last")
    if not last or last.get("reverted"):
        return
    at = datetime.fromisoformat(last["at"])
    if now - at > timedelta(hours=REVERT_WINDOW_H):
        return
    rescue = next((s for s in _hist(room, zone).shots if s.start >= at and s.kind == "p3_emergency"), None)
    if rescue is None:
        return
    cur = _zone_number(c, room, zone, last["suffix"])
    if cur is not None and abs(cur - float(last["to"])) < 1e-6:  # still Jev's value: put the operator's back
        learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
        c._auto_write(room, zone, last["suffix"], float(last["to"]), float(last["from"]), learn, now,
                      by="Jev (put back)")
        rec["written"][last["suffix"]] = float(last["from"])
        rec["pending"] = _pending(last["suffix"], float(last["to"]), float(last["from"]), "Jev (put back)", now)
    last["reverted"] = True
    rec["frozen_until"] = (now + timedelta(hours=PAUSE_H)).isoformat(timespec="seconds")
    mem.save()
    why = f"a rescue shot at {rescue.start:%H:%M} after '{last['words']}'"
    _note(c, room, zone, "safety revert", f"put back: {last['suffix'].replace('_', ' ')} {last['to']:g} -> "
          f"{last['from']:g}", "acted", f"{why}; paused {PAUSE_H} h")
    c._alert(f"auto_{room.slug}_z{zone}", "CS-404", "automatic targets paused",
             f"Jev's change to this zone's watering ({last['words']}) was put back, because {why}. Jev leaves "
             f"this zone's setpoints alone for {PAUSE_H} hours; watering carries on with your own values.",
             room=room, zone=zone)


def advance(c, room, zone, snap, d, now):
    """Move the zone forward one phase as Jev judged, with the bookkeeping the engine does itself."""
    st = room.state[zone]
    was, st["phase"] = st["phase"], d.value
    c._record_phase(room, zone, st, was, d.value, now, f"Jev's {d.judge} judge: {d.why}")
    st["last_phase_change"] = now
    if d.value == "P1":
        st["shots"] = 0
    c._save_state()
    c._notify_event("phase", room, zone, was, d.value, f"Jev's {d.judge} judge: {d.why}")
    return dataclasses.replace(snap, phase=d.value, phase_minutes=0.0,
                               **({"shot_count": 0} if d.value == "P1" else {}))


def shot_started(room, zone, snap, kind):
    room.__dict__.setdefault("_jev_shot", {})[zone] = (
        datetime.now(), kind, None if snap is None else snap.vwc, None if snap is None else snap.ec)


def shot_counted(room, zone, litres):
    start = room.__dict__.get("_jev_shot", {}).pop(zone, None)
    if start is None:
        return
    t0, kind, pre_v, pre_e = start
    _hist(room, zone).add_shot(Shot(t0, (datetime.now() - t0).total_seconds(), float(litres or 0.0),
                                    str(kind or "shot"), pre_v, pre_e))


def siblings(c, room, snaps, params, now):
    """Each zone's water per plant, reading and latest settled shot, for its siblings' judges next pass."""
    out = {}
    for zone in room.zones:
        v = {}
        plants = c._zone_num(room, zone, "plant_count", 0)
        if plants and plants >= 1:
            lpp = room.state[zone]["daily_vol"] / plants
            v["litres_per_plant"] = lpp
            v["litres_per_plant_words"] = f"{lpp * 1000:.0f} mL a plant today"
        s, p = snaps.get(zone), params.get(zone)
        if s is not None:
            v["vwc_words"] = f"VWC {s.vwc:.1f}%, drying {s.dryback_rate:.2f} points an hour"
        if p is not None:
            v["threshold_words"] = f"re-waters under {p.p2_threshold:.1f}%, shot {p.p2_shot_size:.1f}%"
        h = room.__dict__.get("_jev_hist", {}).get(zone)
        if h and h.shots:
            settled = [r for r in (response(h, sh, now) for sh in h.shots) if r.settled and r.retained is not None]
            if settled:
                v["rise"] = settled[-1].retained
                v["rise_words"] = words_response(settled[-1])
        if v:
            out[zone] = v
    room._jev_sib = out
    room._jev_params = params  # this pass's params, for the setpoints published with the zone's Jev sensor


def stage_info(c, room, now):
    """Today's row of the stage arc for the room, as numbers the dashboard can draw, or None."""
    brain = c.jev
    days = getattr(brain, "flower_days", 56)
    day = flower_day(c, room, now)
    st = stage_intent(day, days)
    if not st:
        return None
    return {"day": day, "days": days, "name": st["stage"], "steering": st["steering"],
            "stage_days": list(st.get("days") or []), "peak": st.get("peak"),
            "pore_ec": list(st.get("pore_ec_range") or []), "dryback_points": list(st.get("dryback_points") or []),
            "runoff_pct": list(st.get("runoff_pct") or [])}


def headline(entry):
    """The log sensor's state: its newest entry in one line."""
    if not entry:
        return "no decisions yet"
    what = entry.get("action") or entry.get("result") or ""
    zone = f"Z{entry['zone']} " if entry.get("zone") is not None else ""
    return f"{entry['t'][11:16]} {zone}{entry['title']}: {entry['verdict']} -> {what}"[:255]


USAGE_KEYS = ("day", "calls", "errors", "input_tokens", "last_error", "retries", "failovers", "reasks", "warned")


def restore_usage(asker, path):
    """Today's call count survives a controller restart: the asker starts from what was saved, if it is today's."""
    try:
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        if saved.get("day") == datetime.fromtimestamp(asker.clock()).date().isoformat():
            asker.stats.update({k: saved[k] for k in USAGE_KEYS if k in saved})
    except (OSError, ValueError, AttributeError, TypeError):
        pass  # no usable file: the day's count starts from zero, as before


def save_usage(brain):
    path = getattr(brain, "usage_path", None)
    s = brain.asker.stats
    key = tuple(s.get(k) for k in USAGE_KEYS)
    if not path or s.get("day") is None or brain.__dict__.get("_usage_saved") == key:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({k: s.get(k) for k in USAGE_KEYS}, fh)
        os.replace(tmp, path)
        brain._usage_saved = key
    except OSError:
        pass


def setpoints_published(c, room, zone, now, managed):
    """What the dashboard shows of the Setpoints judge for a zone: the operator's values, Jev's range around them,
    the current values, the last move and any pause. None without Jev's Setpoints judge or this pass's params."""
    mem = getattr(c.jev, "setpoints", None)
    p = (room.__dict__.get("_jev_params") or {}).get(zone)
    if mem is None or p is None or not owns_setpoints(c):
        return None
    rec = mem.zone(room.slug, zone)
    offset = float(room.state[zone].get("ec_offset") or 0.0)  # the EC steer's offset is baked into the threshold
    current = {SHOT: round(float(p.p2_shot_size), 2), THRESHOLD: round(float(p.p2_threshold) - offset, 2)}
    home = {s: float(rec["home"].get(s, v)) for s, v in current.items()}
    frozen = rec.get("frozen_until")
    last = rec.get("last") or {}
    return {
        "managed": bool(managed), "home": home, "current": current,
        "range": {s: [round(x, 2) for x in setpoint_band(s, home[s], p)] for s in current},
        "last": _last_words(last),
        "paused_until": frozen if frozen and datetime.fromisoformat(frozen) > now else None,
    }


def runtime_alerts(c, room):
    """CS-706 once a day when Jev's calls reach the warning share of the budget, and CS-707 when one of this room's
    zones has a judge go on the stricter gate (Brain.events)."""
    brain, asker = c.jev, c.jev.asker
    if asker.take_warning():
        c._jev_alert(room, None, "budget", {
            "code": "CS-706", "title": "Jev has used most of today's calls",
            "message": (f"Jev has made {asker.stats.get('calls')} of its {asker.daily_budget} calls today, across "
                        "every room. Once they are spent, the engine's own rules decide until midnight. Raise "
                        "jev_daily_calls in the app's options if this happens on an ordinary day.")})
    mine = [e for e in brain.events if e[1] == room.slug]
    brain.events = [e for e in brain.events if e[1] != room.slug]
    for _kind, _room, zone, judge in mine:
        c._jev_alert(room, zone, judge, {
            "code": "CS-707", "title": "Jev is on the stricter gate for this zone",
            "message": (f"Jev's {judge} judge made {brain.strict_after} calls in a row for this zone that did not "
                        f"work out. Until two in a row do, it acts only when both phrasings agree at "
                        f"{brain.strict_prob:g} or more and a second look gives the same answer. Jev keeps judging; "
                        "whenever it is not sure enough, the engine's own rules act.")})


def publish(c, room, now, ha_set):
    brain = c.jev
    runtime_alerts(c, room)
    s = brain.asker.stats
    managed = None
    if owns_setpoints(c):
        managed = (c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)
                   and not getattr(room, "strategy_required", False))
    for zone in room.zones:
        status = brain.zone_status(room.slug, zone)
        acting = sorted(n for n, v in status.items() if v.get("directive") and not str(v.get("why", "")).startswith("refused"))
        strict = sorted(j for (r, z, j), on in brain.strict.items() if on and r == room.slug and z == zone)
        attrs = {"judges": status, "strict": strict, "friendly_name": f"Zone {zone} Jev", "engine": PRODUCT}
        sp = setpoints_published(c, room, zone, now, managed)
        if sp is not None:
            attrs["setpoints"] = sp
        ha_set(f"sensor.crop_steering_{room.prefix}zone_{zone}_jev", ", ".join(acting) or "watching", attrs)
    save_usage(brain)
    ha_set(f"sensor.crop_steering_{room.prefix}jev", "error" if s.get("last_error") and not s.get("last_call") else "on",
           {"calls_today": s.get("calls"), "daily_budget": brain.asker.daily_budget,
            "input_tokens_today": s.get("input_tokens"), "errors_today": s.get("errors"),
            "last_error": s.get("last_error"), "retries_today": s.get("retries"),
            "failovers_today": s.get("failovers"), "reasks_today": s.get("reasks"),
            "routes": list(getattr(brain, "routes", [])), "last_route": s.get("route"),
            "judges": sorted(j.name for j in brain.judges), "judge_errors": dict(brain.errors),
            "stage": stage_info(c, room, now), "friendly_name": "Jev", "engine": PRODUCT})
    journal = getattr(brain, "journal", None)
    if journal is not None:
        entries = journal.recent(room.slug)
        ha_set(f"sensor.crop_steering_{room.prefix}jev_log", headline(entries[0] if entries else None),
               {"entries": entries, "friendly_name": "Jev decisions", "engine": PRODUCT})
