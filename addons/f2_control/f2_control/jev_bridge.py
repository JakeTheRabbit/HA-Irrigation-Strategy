"""The controller's side of Jev: build the brain, feed it each zone's pass, apply what it admits.

Every function here is called inside a try/except in the controller: whatever goes wrong in Jev, the
zone is decided and watered by the base engine exactly as it would be without it (docs/JEV.md).
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from datetime import datetime, timedelta
from functools import partial

from jev import client as jev_client
from jev.brain import Brain
from jev.client import (DEFAULT_MODEL, PRICES, Asker, Meter, Route, Routes, anthropic_key, call, call_anthropic,
                        call_typesafe, make_client)
from jev.context import Shot, ZoneContext, ZoneHistory, response, words_response
from jev.doctrine import DEFAULT_ARC, ArcInvalid, stage_intent, stage_rows
from jev.doctrine import STAGE_ARC as STAGE_ROWS
from jev.enrich import enrich
from jev.judges.channel import ChannelJudge
from jev.prompt import Prompt
from jev.judges.balance import HARDWARE as ZONES_HARDWARE
from jev.judges.balance import BalanceJudge
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

ALL = ("dawn", "ramp", "salt", "dusk", "probe", "shot", "night", "zones", "stage", "setpoints", "channel", "balance")
PENDING_S = 300  # a write Home Assistant has not reflected yet is not an operator's edit for this long
RETRIES = 3  # a write still not read back is sent again this many times, PENDING_S apart and doubling, then failed
REVERT_WINDOW_H = 30  # a rescue shot this soon after a setpoint change puts the old value back
PAUSE_H = 48  # and the zone's setpoints are left alone this long
# Only Jev's own code writes these into /data, so any one of them (empty or unreadable too) says Jev has run here.
JEV_FILES = ("jev_usage.json", "jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json")
PRODUCT = "Crop Steering Controller"  # controller.PRODUCT: the `engine` value on what Jev publishes
PROVIDERS = ("auto", "rules", "claude_haiku", "jev_legacy")
NOTICES = "brain_notices.json"  # {"cs712": "<release>"}: the retired-route card is shown once a release
# The judges whose answers can act (the rest advise); empty on the panel while the brain cannot act.
ACTING_JUDGES = ("dawn", "ramp", "salt", "dusk", "probe", "setpoints")
FRIENDLY = "AI assistant"


def judges():
    return [DawnJudge(), RampJudge(), SaltJudge(), DuskJudge(), ProbeJudge(), ShotJudge(), NightJudge(),
            ZonesJudge(), StageJudge(), SetpointsJudge(), ChannelJudge(), BalanceJudge()]


def routes(options, cf):
    """Every legacy route Jev has, in the order they are tried: TypeSafe direct when its key is set, then
    Cloudflare's /ai/run when its account and token are."""
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


def jev_lineage(options, data):
    """JEV lineage evidence, first match wins (haiku-brain-design 4.3): a usage file that names the brain which wrote
    it says so (claude_haiku does not count); else any file only Jev writes; else a TypeSafe key, an option only the
    Jev line ever had. Never `jev_enabled`, which the Supervisor fills in from defaults."""
    try:
        with open(os.path.join(data, "jev_usage.json"), encoding="utf-8") as fh:
            saved = json.load(fh)
        provider = saved.get("provider") if isinstance(saved, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        provider = None
    if provider:
        return provider == "jev_legacy"
    return has_run(data) or bool(str(options.get("typesafe_api_key") or "").strip())


@dataclasses.dataclass(frozen=True)
class BrainStatus:
    """Which brain runs and why, decided once at start (resolve_provider); the brain panel says it in every case."""
    provider: str  # rules, claude_haiku or jev_legacy
    state: str  # rules, rules_no_key, model_invalid, sdk_missing, brain_off, start_failed, acting, dry_run, legacy
    words: str
    model: str | None = None
    key_set: bool = False
    deprecated_route: bool = False
    notice: str | None = None  # cloudflare_route_retired: Cloudflare settings no brain uses now (CS-712 once)
    since: str = ""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def resolve_provider(options, cf, data):
    """The BrainStatus for these options and the /data folder `data`. Pure: no network, never the key's value."""
    provider = str(options.get("brain_provider") or "auto").strip()
    provider = provider if provider in PROVIDERS else "auto"
    model = str(options.get("anthropic_model") or DEFAULT_MODEL).strip()
    key = bool(anthropic_key(options))
    legacy = bool(routes(options, cf))

    def rules(state, words, notice=None):
        return BrainStatus("rules", state, words, key_set=key, notice=notice, since=_now())

    if provider == "rules":
        return rules("rules", "Rules.")
    if provider == "claude_haiku":
        if not key:
            return rules("rules_no_key", "Rules: no Anthropic key.")
        if model not in PRICES:
            return rules("model_invalid", f"Rules: this release does not know the price of {model}, so it cannot keep "
                                          f"to your budget. Use {', '.join(PRICES)}.")
        if jev_client.anthropic is None:
            return rules("sdk_missing", "The Claude brain is not available on this device (32-bit ARM). Rules are "
                                        "running.")
        dry = options.get("brain_dry_run") is True
        return BrainStatus("claude_haiku", "dry_run" if dry else "acting",
                           "Claude Haiku, advising only." if dry else "Claude Haiku, acting.", model=model,
                           key_set=True, since=_now())
    if options.get("jev_enabled", True) is False:
        return rules("brain_off", "Rules (brain off).")
    if provider == "jev_legacy":
        if not legacy:
            return rules("rules_no_key", "Rules: no Jev credentials.")
        return BrainStatus("jev_legacy", "legacy", "Jev (retired route). Switch to Claude Haiku.", key_set=key,
                           deprecated_route=True, since=_now())
    if legacy and jev_lineage(options, data):
        return BrainStatus("jev_legacy", "legacy", "Jev (retired route, still running). Switch to Claude Haiku.",
                           key_set=key, deprecated_route=True, since=_now())
    if legacy:
        return rules("rules", "Rules.", notice="cloudflare_route_retired")
    return rules("rules", "Rules. Choose Claude Haiku and add a key to turn the brain on.")


def start_failed():
    return BrainStatus("rules", "start_failed", "The brain could not start, so rules are running. The app log says "
                                                "why.", since=_now())


def build(options, cf, state_path, log, status=None):
    """The brain, or None when rules run (BrainStatus says why). Under claude_haiku its one route is the Anthropic
    API with the key, a Meter for the budget and the cached prompt; under jev_legacy every legacy route it has,
    TypeSafe first, each retried while a failure may pass (jev.client.Routes), exactly as before."""
    data = os.path.dirname(state_path) or "."
    status = status or resolve_provider(options, cf, data)
    if status.provider == "rules":
        if status.notice == "cloudflare_route_retired":
            log("jev: off. The Cloudflare credentials start Jev only on an install that has run it before, and no Jev"
                f" file is in {data}; set brain_provider to jev_legacy to keep the old route")
        return None
    jev_client.log = log
    wanted = str(options.get("jev_judges") or "all").replace(" ", "")
    allowed = set(ALL) if wanted in ("", "all") else set(wanted.split(",")) & set(ALL)
    haiku = status.provider == "claude_haiku"
    if not haiku:
        allowed.discard("balance")  # its answer reaches the setpoints judge only through the Claude route's evidence
    arc = str(options.get("stage_arc") or DEFAULT_ARC).strip()
    try:
        rows, arc_note = stage_rows(arc), None
    except ArcInvalid as e:
        rows, arc_note = (), (f"The stage arc {arc} is not complete in this release ({e}), so no stage arc is used. "
                              "Choose slab_default.")
    dry = options.get("brain_dry_run") is True
    meter = prompt = None
    if status.provider == "claude_haiku":
        budget = options.get("anthropic_daily_budget_usd")
        budget = 1.0 if budget is None else max(0.0, float(budget))
        meter = Meter(budget, status.model, warn_pct=float(options.get("jev_budget_warn_pct", 80)))
        prompt = Prompt(rows, arc if rows else None)
        key = anthropic_key(options)
        found = [Route("Anthropic", partial(call_anthropic, model=status.model, prompt=prompt, meter=meter,
                                            client=make_client(key)), "anthropic", key)]
    else:
        found = routes(options, cf)
    first = found[0]
    asker = Asker(first.account, first.token, first.gateway, daily_budget=int(options.get("jev_daily_calls", 5000)),
                  transport=Routes(found, tries=int(options.get("jev_retries", 3))),
                  warn_pct=float(options.get("jev_budget_warn_pct", 80)), meter=meter)
    ledger = Ledger(os.path.join(data, "jev_ledger.jsonl"))
    names = [r.name for r in found]
    if meter is not None:
        log(f"brain: claude_haiku, model {status.model}, budget US${meter.budget:.2f} until lights-on, key set"
            + (", advising only (dry run)" if dry else "") + f", judges {', '.join(sorted(allowed))}")
        log(prompt.describe())
    else:
        log(f"jev: on via {' then '.join(names)}, judges {', '.join(sorted(allowed))}, {asker.daily_budget} calls a "
            "day (deprecated; brain_provider: claude_haiku replaces it)" + (", advising only (dry run)" if dry else ""))
    brain = Brain(asker, ledger, judges(), allowed=allowed, log=log,
                  reask_max=int(options.get("jev_reask_max", 2)),
                  unsure_below=float(options.get("jev_unsure_below", 0.7)),
                  strict_after=int(options.get("jev_strict_after", 3)),
                  strict_prob=float(options.get("jev_strict_prob", 0.8)),
                  enrich=enrich if haiku else None, dry_run=dry)
    brain.routes, brain.status, brain.prompt = names, status, prompt
    brain.arc, brain.arc_rows, brain.arc_note = arc, rows, arc_note
    brain.journal = Journal(os.path.join(data, "jev_journal.jsonl"))
    brain.setpoints = SetpointMemory(os.path.join(data, "jev_setpoints.json"))
    brain.usage_path = os.path.join(data, "jev_usage.json")
    restore_usage(asker, brain.usage_path)
    save_usage(brain)  # names this brain in /data before its first ask: the next start reads it (jev_lineage)
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


def haiku(c):
    """True when the brain is the Claude route."""
    return getattr(getattr(getattr(c, "jev", None), "status", None), "provider", None) == "claude_haiku"


def _status(brain):
    """The brain's BrainStatus; a brain built without one (a test, a script) is a legacy brain."""
    return getattr(brain, "status", None) or BrainStatus("jev_legacy", "legacy", "Jev.")


def _setting(c, room, zone, suffix):
    """The zone's own number for `suffix`, else the room's, else None: read as it is, never defaulted."""
    for scope in (f"zone_{zone}_", ""):
        v = c._num_or_none(f"number.crop_steering_{room.prefix}{scope}{suffix}")
        if v is not None:
            return v
    return None


def _judge(brain, name):
    return next((j for j in getattr(brain, "judges", ()) if j.name == name), None)


def zones_hardware(c, room, zone, now):
    """The hardware cause the zones judge named for the zone since lights-on (firm, as its alert needs), or None."""
    st = getattr(c.jev, "state", {}).get((room.slug, zone, "zones"))
    v = st.verdicts.get("why_different") if st is not None else None
    if v is None or st.last_asked is None or v.label not in ZONES_HARDWARE or not v.firm_in(ZONES_HARDWARE, 0.6):
        return None
    since_on = timedelta(hours=(24.0 - c._hours_to(now, room.lights_on_hour)) % 24.0)
    return v.label if now - st.last_asked <= since_on else None


def room_balance(c, room, zone, now):
    """The balance judge's latest answer for the zone in words, for tonight's setpoints judge, or None."""
    judge = _judge(c.jev, "balance")
    return None if judge is None else judge.words(room.slug, zone, now)


def brain_context(c, room, zone, snap, now):
    """What only the controller knows about the zone, for the Claude brain's evidence (ZoneContext.brain)."""
    plants = _setting(c, room, zone, "plant_count")
    zone_on = c._on(f"switch.crop_steering_{room.prefix}zone_{zone}_enabled", True)
    settled = getattr(snap, "ec_settled", None) is not None
    return {
        "zone_config": {"plants": int(plants) if plants else None,
                        "drippers_per_plant": _setting(c, room, zone, "drippers_per_plant"),
                        "dripper_flow_l_per_h": _setting(c, room, zone, "dripper_flow_rate"),
                        "substrate_l_per_plant": _setting(c, room, zone, "substrate_volume"),
                        "substrate": getattr(room, "substrate", "generic")},
        "interlocks": (f"kill switch {'on' if c._on(room.enable_flag, False) else 'off: no valve opens'}; zone "
                       f"switch {'on' if zone_on else 'off'}"),
        "data_quality": ("a usable moisture reading this pass; pore EC "
                         + ("settled since the last shot" if settled else "not settled since the last shot")),
        "arc": getattr(c.jev, "arc", None), "arc_note": getattr(c.jev, "arc_note", None),
        "zones_hardware": zones_hardware(c, room, zone, now), "room_balance": room_balance(c, room, zone, now),
    }


def zone_context(c, room, zone, snap, p, now, lights_on):
    st = room.state[zone]
    plants = c._zone_num(room, zone, "plant_count", 0)
    fday = flower_day(c, room, now)
    fdays = getattr(c.jev, "flower_days", 56)
    return ZoneContext(
        flower_day=fday, flower_days=fdays, stage=stage_intent(fday, fdays, getattr(c.jev, "arc_rows", STAGE_ROWS)),
        brain=brain_context(c, room, zone, snap, now) if haiku(c) else None,
        steering="vegetative" if c._veg(room, zone) else "generative",
        room=room.slug, prefix=room.prefix, zone=zone, title=c._zone_title(room, zone), now=now,
        phase=st["phase"], snap=snap, params=p, history=_hist(room, zone), lights_on=lights_on,
        hours_to_on=c._hours_to(now, room.lights_on_hour), hours_to_off=c._hours_to(now, room.lights_off_hour),
        siblings={z: v for z, v in room.__dict__.get("_jev_sib", {}).items() if z != zone},
        plants=int(plants) if plants and float(plants).is_integer() else None,
        substrate_l=c._substrate_l(room, zone),
        feed_ec=getattr(snap, "feed_ec", None) if snap is not None else None,
        probe_entity=c._fused_id(room.prefix, "vwc", zone, room.zones[zone].get("vwc")),
        channel=channel_words(c.jev, room.slug, zone, now),
        # read only in the night, where the Setpoints judge runs: an edit by hand is caught before it is asked
        setpoints=setpoint_view(c, room, zone, p, now) if st["phase"] == "P3" else None,
    )


def channel_words(brain, room, zone, now):
    """The channel judge's latest answer for the zone, for the probe judge's evidence, or None."""
    judge = next((j for j in getattr(brain, "judges", ()) if j.name == "channel"), None)
    return None if judge is None else judge.words(room, zone, now)


def room_health(c, room, now):
    """The room's data health (gap SF-26), read once a pass: ("ok", None), else ("impaired", words) when an enabled
    zone's moisture reading is stale or missing, or ("critical", words) when no enabled zone has a fresh one. On the
    Claude route anything but ok asks nothing (stale data fails closed) and the brain panel says why."""
    held = room.__dict__.get("_brain_health")
    if held and held[0] == now:
        return held[1]
    zones = [z for z in room.zones if c._on(f"switch.crop_steering_{room.prefix}zone_{z}_enabled", True)]
    stale = [z for z in zones
             if c._read_sensor(c._fused_id(room.prefix, "vwc", z, room.zones[z].get("vwc")), "vwc") is None]
    if not stale:
        out = ("ok", None)
    else:
        which = ("no zone has a" if len(stale) == len(zones) else
                 ", ".join(c._zone_title(room, z) for z in stale) + (" has no" if len(stale) == 1 else " have no"))
        out = ("critical" if len(stale) == len(zones) else "impaired",
               f"Readings too old to judge: {which} fresh moisture reading. The AI stays out until the probes "
               "report again; the rules keep watering.")
    room._brain_health = (now, out)
    return out


def tick(c, room, zone, snap, p, now, lights_on):
    """Record this pass's reading, run the judges, raise their alerts, apply a setpoint move.
    -> {kind: Directive} for the controller's pass (advance, distrust, ec_mode)."""
    _hist(room, zone).add_reading(now, snap.vwc, snap.ec)
    readback(c, room, zone, now)
    guard_setpoints(c, room, zone, now)
    levers = judge_levers(c, room)
    _handover(c, room, zone, p, now, levers)
    if haiku(c):
        if not c._on(room.enable_flag, False):
            return {}  # the kill switch is off: the engine decides alone, and nothing is asked (it costs money)
        if room_health(c, room, now)[0] != "ok":
            return {}  # stale or impaired readings: the engine decides alone, and nothing is asked (fail-closed)
        c.jev.prompt.use(getattr(r, "substrate", "generic") for r in getattr(c, "rooms", [room]))
    ctx = zone_context(c, room, zone, snap, p, now, lights_on)
    out = {}
    for d, _why in c.jev.tick(ctx):
        if d.kind == "alert":
            c._jev_alert(room, zone, d.judge, d.value)
        elif d.kind == "setpoint":
            if d.value.get("suffix") in levers:
                apply_setpoint(c, room, zone, d, ctx, now)
            else:
                _note(c, room, zone, "would act", d.value.get("words", ""), "no action",
                      "the Auto setpoints learner holds this number today")
        else:
            out[d.kind] = d
    return out


# ---------- the Setpoints judge's side (docs/JEV.md) ----------
def owns_setpoints(c):
    """True when Jev's Setpoints judge runs: it then owns each zone's P2 shot size and re-water threshold."""
    brain = getattr(c, "jev", None)
    return brain is not None and any(j.name == "setpoints" for j in getattr(brain, "judges", ()))


def can_act(c):
    """The brain may act: dry run off, and (on the Claude route) within budget, not paused, latched or unavailable,
    and its Setpoints judge not declining. The legacy route has no Meter: there only dry run stops it."""
    brain = getattr(c, "jev", None)
    if brain is None or getattr(brain, "dry_run", False):
        return False
    meter = getattr(brain.asker, "meter", None)
    return meter is None or meter.live()


def judge_levers(c, room=None):
    """The zone numbers the Setpoints judge writes, or () when it does not run or, for `room`, while the brain cannot
    act. The base engine's own Auto Setpoints learner writes the others (controller._auto_tick), so each lever has
    exactly one writer. The levers leave on the first pass the brain cannot act and come back only at a lights-on
    at which it can (lights_on), so a short pause never flips their writer within a grow-day."""
    if not owns_setpoints(c):
        return ()
    if room is None:
        return (SHOT, THRESHOLD)
    held = c.jev.__dict__.setdefault("levers_held", {})
    if room.slug not in held:
        held[room.slug] = can_act(c)  # at start: with the judge whenever the brain can act then
    elif held[room.slug] and not can_act(c):
        held[room.slug] = False
    return (SHOT, THRESHOLD) if held[room.slug] else ()


def _handover(c, room, zone, p, now, levers):
    mem = getattr(c.jev, "setpoints", None)
    if mem is None or not owns_setpoints(c):
        return
    held = mem.zone(room.slug, zone).get("held")
    if not levers and not held:
        hold_levers(c, room, zone, p, now)
    elif levers and held:
        hand_back(c, room, zone, p, now)


def hold_levers(c, room, zone, p, now):
    """The learner takes the levers: remember the judge's values and the grower's (home), once per hold."""
    mem = c.jev.setpoints
    rec = mem.zone(room.slug, zone)
    rec["held"] = {"at": now.isoformat(timespec="seconds"), "shot": _zone_number(c, room, zone, SHOT),
                   "threshold": _zone_number(c, room, zone, THRESHOLD), "home": dict(rec["home"]),
                   "field_capacity": float(p.field_capacity)}
    mem.save()


def _written(mem, rec, suffix, old, value, now):
    rec["written"][suffix] = float(value)
    rec["pending"] = {"suffix": suffix, "from": float(old), "at": now.isoformat(timespec="seconds")}
    mem.save()


def learner_wrote(c, room, zone, suffix, old, value, now):
    """The Auto setpoints learner wrote one of the judge's levers while it holds them: not an edit by hand, and the
    grower's value (the band's centre) stays where it is."""
    mem = getattr(getattr(c, "jev", None), "setpoints", None)
    if mem is not None and owns_setpoints(c):
        _written(mem, mem.zone(room.slug, zone), suffix, old, value, now)


def fc_moved(c, room, zone, old, value, now):
    """Field capacity moved the re-water threshold during a hold (controller._follow_fc): the band follows it."""
    mem = getattr(getattr(c, "jev", None), "setpoints", None)
    if mem is None or not owns_setpoints(c):
        return
    rec = mem.zone(room.slug, zone)
    if not rec.get("held"):
        return
    if THRESHOLD in rec["home"]:
        rec["home"][THRESHOLD] = round(float(rec["home"][THRESHOLD]) + float(value) - float(old), 2)
    _written(mem, rec, THRESHOLD, old, value, now)
    _note(c, room, zone, "moved with field capacity", f"re-water threshold {old:g} -> {value:g}", "acted",
          "the range moves with field capacity")


def hand_back(c, room, zone, p, now):
    """The levers come back to the judge: put the threshold where the judge can work from, writing at most once.
    The value held before the hold, only when neither the grower's value nor field capacity moved since; clamped
    into the judge's band (inside the ladder) and the number's own limits; never a write that breaks the ladder
    rescue + 3 <= threshold < P1 target <= field capacity. The shot size has no rules writer: it is left as it is."""
    mem = c.jev.setpoints
    rec = mem.zone(room.slug, zone)
    held = rec.pop("held", None) or {}
    mem.save()
    cur = _zone_number(c, room, zone, THRESHOLD)
    enabled = (c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)
               and not getattr(room, "strategy_required", False))
    if cur is None or not enabled:
        return
    home = float(rec["home"].get(THRESHOLD, cur))
    was = float((held.get("home") or {}).get(THRESHOLD, home))
    moved = abs(home - was) >= 0.05 or abs(float(p.field_capacity) - float(held.get("field_capacity", 0))) >= 0.05
    target = cur if moved or held.get("threshold") is None else float(held["threshold"])
    lo, hi = setpoint_band(THRESHOLD, home, p)
    value, why = None, ""
    if lo > hi:
        why = "the judge's range is empty"
    else:
        value = c._zone_bounded(room, zone, THRESHOLD, min(hi, max(lo, target)))
        if not lo - 1e-9 <= value <= hi + 1e-9:
            value, why = None, "the number's own limits sit outside the judge's range"
        elif not p.p3_emergency_floor + 3.0 <= value < p.p1_target <= p.field_capacity:
            value, why = None, "it would break the ladder"
        elif abs(value - cur) < 0.05:
            value, why = None, "already inside the judge's range"
    if value is None:
        _note(c, room, zone, "levers back", f"kept {cur:g}", "no action", why)
        return
    learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
    if c._auto_write(room, zone, THRESHOLD, cur, value, learn, now, by="brain: levers back"):
        _written(mem, rec, THRESHOLD, cur, value, now)
        _note(c, room, zone, "levers back", f"re-water threshold {cur:g} -> {value:g}", "acted",
              "the judge works from here")


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
    wrote = c._auto_write(room, zone, v["suffix"], float(v["from"]), float(v["to"]), learn, now, by="Jev")
    rec["written"][v["suffix"]] = float(v["to"])
    rec["pending"] = _pending(v["suffix"], float(v["from"]), float(v["to"]), "Jev", now)
    rec["last"] = {"suffix": v["suffix"], "from": float(v["from"]), "to": float(v["to"]),
                   "at": now.isoformat(timespec="seconds"), "day": (ctx.setpoints or {}).get("day"),
                   "words": v["words"], "choice": v["choice"], "reverted": False}
    mem.save()
    # For the phones that tick Jev (docs/NOTIFICATIONS.md): no card, a push only, with Keep and Undo for the
    # number written (an AI overlay in the integration).
    c._notify_event("jev_setpoint", room, zone, v["words"],
                    f"{CHOICES.get(v['choice'], v['choice'])} Jev's Setpoints judge, {d.why}.",
                    *([f"number.crop_steering_{room.prefix}zone_{zone}_{v['suffix']}"] if wrote else []))


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
    """Today's row of the install's stage arc for the room, as numbers the dashboard can draw, or None."""
    brain = c.jev
    days = getattr(brain, "flower_days", 56)
    day = flower_day(c, room, now)
    st = stage_intent(day, days, getattr(brain, "arc_rows", STAGE_ROWS))
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
    """Today's call count survives a controller restart: the asker starts from what was saved, if it is today's. The
    Claude brain's spend survives it too, by its window (Meter.restore); a file from before has none: zero."""
    try:
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        if saved.get("day") == datetime.fromtimestamp(asker.clock()).date().isoformat():
            asker.stats.update({k: saved[k] for k in USAGE_KEYS if k in saved})
        if getattr(asker, "meter", None) is not None and isinstance(saved.get("meter"), dict):
            asker.meter.restore(saved["meter"])
    except (OSError, ValueError, AttributeError, TypeError):
        pass  # no usable file: the day's count starts from zero, as before


def save_usage(brain):
    """The usage file, named for the brain that writes it (jev_lineage reads `provider` first). Never the key."""
    path = getattr(brain, "usage_path", None)
    s = brain.asker.stats
    data = {k: s.get(k) for k in USAGE_KEYS}
    data["provider"] = getattr(getattr(brain, "status", None), "provider", "jev_legacy")
    meter = getattr(brain.asker, "meter", None)
    if meter is not None:
        data["meter"] = {k: v for k, v in meter.snapshot().items() if k != "state"}
    key = json.dumps(data, sort_keys=True, default=str)
    if not path or brain.__dict__.get("_usage_saved") == key:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
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


def _release():
    return getattr(sys.modules.get("controller"), "CONTROLLER_VERSION", "unknown")


def _notices_path(c):
    return os.path.join(os.path.dirname(getattr(c, "_state_path", "") or "") or ".", NOTICES)


def _route_card_due(c):
    """CS-712 shows once a release: not when brain_notices.json says it was shown for this one."""
    try:
        with open(_notices_path(c), encoding="utf-8") as fh:
            return json.load(fh).get("cs712") != _release()
    except (OSError, ValueError, AttributeError):
        return True


def _route_card_shown(c):
    try:
        tmp = _notices_path(c) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"cs712": _release()}, fh)
        os.replace(tmp, _notices_path(c))
    except OSError:
        pass


def route_card(c, room, legacy):
    """CS-712, once a release (only once Home Assistant has the card): the retired Jev routes."""
    if not _route_card_due(c):
        return
    if legacy:
        words = ("This room's AI assistant still runs on a retired Jev route. It keeps working, but it gets no new "
                 "features. Choose Claude Haiku (brain_provider: claude_haiku and your Anthropic key) to move on.")
    else:
        words = ("Your Cloudflare settings are no longer used unless you choose them. The brain now runs on Claude "
                 "Haiku, or on rules with no key. To keep the old Jev route, set the brain to jev_legacy.")
    if c._jev_alert(room, None, "route", {"code": "CS-712", "title": "the AI assistant's Jev route is retired",
                                          "message": words}):
        _route_card_shown(c)


def runtime_alerts(c, room):
    """CS-706 once a day when Jev's calls reach the warning share of the budget (or once a window when the Claude
    brain's spend reaches it), CS-707 when one of this room's zones has a judge go on the stricter gate
    (Brain.events), CS-708 once a window when the Claude brain's budget is spent, CS-709 when its key is refused or it
    stops answering, and CS-712 on a retired route. A card Home Assistant could not take is raised again."""
    brain, asker = c.jev, c.jev.asker
    meter = getattr(asker, "meter", None)
    if asker.take_warning() or (meter is not None and meter.take("warn")):
        c._jev_alert(room, None, "budget", {
            "code": "CS-706", "title": "Jev has used most of today's calls",
            "message": (f"Jev has made {asker.stats.get('calls')} of its {asker.daily_budget} calls today, across "
                        "every room. Once they are spent, the engine's own rules decide until midnight. Raise "
                        "jev_daily_calls in the app's options if this happens on an ordinary day."
                        if meter is None else
                        f"The AI assistant has used most of its budget of US${meter.budget:.2f} until the next "
                        "lights-on. Once it is spent, the engine's own rules decide until then.")})
    mine = [e for e in brain.events if e[1] == room.slug]
    brain.events = [e for e in brain.events if e[1] != room.slug]
    for _kind, _room, zone, judge in mine:
        c._jev_alert(room, zone, judge, {
            "code": "CS-707", "title": "Jev is on the stricter gate for this zone",
            "message": (f"Jev's {judge} judge made {brain.strict_after} calls in a row for this zone that did not "
                        f"work out. Until two in a row do, it acts only when both phrasings agree at "
                        f"{brain.strict_prob:g} or more and a second look gives the same answer. Jev keeps judging; "
                        "whenever it is not sure enough, the engine's own rules act.")})
    if meter is not None:
        if meter.take("spent") and not c._jev_alert(room, None, "spent", {
                "code": "CS-708", "title": "the AI assistant has used its budget",
                "message": (f"The AI assistant has used its budget of US${meter.budget:.2f} until the next lights-on. "
                            "The engine is running on its own rules, the Auto setpoints learner included, until "
                            "then. Raise anthropic_daily_budget_usd in the app's options if this happens on an "
                            "ordinary day.")}):
            meter.again("spent")
        if meter.take("brain") and not c._jev_alert(room, None, "brain", {
                "code": "CS-709", "title": "the AI assistant is not available",
                "message": ("The AI assistant cannot reach Claude: " + _STATE_WORDS.get(meter.state(), "it is not "
                            "answering.") + " The engine is running on its own rules.")}):
            meter.again("brain")
    if _status(brain).deprecated_route:
        route_card(c, room, legacy=True)


_STATE_WORDS = {
    "budget_spent": "Spent today's budget. Rules until the next lights-on.",
    "paused": "Anthropic asked it to wait. Rules until it answers again.",
    "unavailable": "Anthropic is not answering. Rules for an hour, then it tries again.",
    "auth_failed": "The Anthropic key was refused. Rules until the app restarts with a working key.",
    "model_invalid": "Anthropic does not know the model. Rules until the app restarts.",
}


def panel(c, room, now):
    """The brain panel's attributes (haiku-brain-design section 13): which brain, whether it can act now and why
    not, and the Claude brain's spend. `key_set` is the only word about the key."""
    brain = c.jev
    status = _status(brain)
    meter = getattr(brain.asker, "meter", None)
    snap = meter.snapshot() if meter is not None else {}
    state = snap.get("state") or status.state
    if state == "budget_spent" and meter is not None and meter.budget == 0:
        words = "The budget is 0, so the brain never asks. Rules are running."
    elif state == "budget_spent":
        words = f"Spent US${snap['cost_usd']:.2f} of US${meter.budget:.2f}. Rules until the next lights-on."
    else:
        words = _STATE_WORDS.get(state, status.words)
    health, health_words = room_health(c, room, now) if haiku(c) else ("ok", None)
    if health != "ok" and state in ("acting", "dry_run"):
        state, words = "stale_data", health_words
    acting = can_act(c)
    if acting:
        brain._fallback_since = None
    elif not getattr(brain, "_fallback_since", None):
        brain._fallback_since = now.isoformat(timespec="seconds")
    built = sorted(j.name for j in brain.judges)
    out = {"provider": status.provider, "model": status.model, "mode": "dry_run" if brain.dry_run else "acting",
           "state": state, "state_words": words, "notice": status.notice, "key_set": status.key_set,
           "deprecated_route": status.deprecated_route, "fallback_since": getattr(brain, "_fallback_since", None),
           "stage_arc": {"id": getattr(brain, "arc", DEFAULT_ARC), "in_force": bool(getattr(brain, "arc_rows", STAGE_ROWS)),
                         "words": getattr(brain, "arc_note", None)},
           "judges_acting": [j for j in built if j in ACTING_JUDGES and health == "ok"] if acting else [],
           "judges_advising": [j for j in built if j not in ACTING_JUDGES]}
    if haiku(c):
        out["room_health"] = health
    entries = brain.journal.recent(room.slug, 1) if getattr(brain, "journal", None) is not None else []
    if entries:
        e = entries[0]
        out["last_decision"] = {"time": e.get("t"), "zone": e.get("zone"), "judge": e.get("judge"),
                                "answer": e.get("verdict"), "p": e.get("p"), "agreed": e.get("agreed"),
                                "result": e.get("result"), "why": e.get("why")}
    if meter is not None:
        start = datetime.fromtimestamp(snap["window_start"])
        elapsed = max((now - start).total_seconds() / 86400.0, 1 / 24)
        read, write, unc = snap["cached_tokens"], snap["cache_write_tokens"], snap["uncached_tokens"]
        out.update(budget_usd=meter.budget, spent_usd=snap["cost_usd"], cost_usd_today=snap["cost_usd"],
                   budget_left_usd=round(max(0.0, meter.budget - snap["cost_usd"]), 6),
                   projected_usd=round(snap["cost_usd"] / min(elapsed, 1.0), 4),
                   window_started=start.isoformat(timespec="seconds"),
                   resets_at=(now + timedelta(hours=c._hours_to(now, room.lights_on_hour))).isoformat(
                       timespec="minutes"),
                   tokens_today={"uncached": unc, "cache_read": read, "cache_write": write,
                                 "output": snap["output_tokens"]},
                   cache_hit_ratio=round(read / (read + write + unc), 3) if read + write + unc else None,
                   declined=snap["declined"])
    return out


def publish(c, room, now, ha_set):
    brain = c.jev
    runtime_alerts(c, room)
    s = brain.asker.stats
    managed = None
    if owns_setpoints(c):
        managed = (bool(judge_levers(c, room)) and c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)
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
            "stage": stage_info(c, room, now), **panel(c, room, now), "friendly_name": FRIENDLY,
            "engine": PRODUCT})
    journal = getattr(brain, "journal", None)
    if journal is not None:
        entries = journal.recent(room.slug)
        ha_set(f"sensor.crop_steering_{room.prefix}jev_log", headline(entries[0] if entries else None),
               {"entries": entries, "friendly_name": "Jev decisions", "engine": PRODUCT})


def publish_rules(c, room, now, ha_set):
    """With no brain built, the brain panel still says why rules run (every BrainStatus rules case), and each zone's
    sensor says rules: a state written over REST replaces every attribute, so nothing from an earlier brain shows.
    The decision log is left as it is (its entries are history). CS-712 once when Cloudflare settings are unused."""
    status = getattr(c, "brain_status", None) or start_failed()
    ha_set(f"sensor.crop_steering_{room.prefix}jev", "rules", {
        "provider": "rules", "state": status.state, "state_words": status.words, "key_set": status.key_set,
        "model": None, "mode": None, "fallback_since": status.since, "deprecated_route": status.deprecated_route,
        "notice": status.notice, "judges_acting": [], "stage": None, "friendly_name": FRIENDLY,
        "engine": PRODUCT})
    for zone in room.zones:
        ha_set(f"sensor.crop_steering_{room.prefix}zone_{zone}_jev", "rules",
               {"judges": {}, "strict": [], "provider": "rules", "friendly_name": f"Zone {zone} Jev",
                "engine": PRODUCT})
    if status.notice == "cloudflare_route_retired":
        route_card(c, room, legacy=False)


def lights_on(c, room, now):
    """A room's lights came on: the Claude brain's budget window may start again (Meter.lights_on), and the
    Setpoints judge's levers come back for this room when the brain can act now (hand_back runs on each zone's
    next pass)."""
    brain = c.jev
    meter = getattr(brain.asker, "meter", None)
    if meter is not None:
        meter.lights_on(now.timestamp())
    if owns_setpoints(c) and can_act(c):
        brain.__dict__.setdefault("levers_held", {})[room.slug] = True
