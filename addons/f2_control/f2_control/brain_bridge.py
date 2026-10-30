"""The controller's side of the AI assistant: build the brain, feed it each zone's pass, apply what it admits.

Every function here is called inside a try/except in the controller: whatever goes wrong in the AI assistant, the
zone is decided and watered by the base engine exactly as it would be without it (docs/AI_ASSISTANT.md).
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from functools import partial

from brain import client as jev_client
from brain.brain import Brain
from brain.client import (DEFAULT_MODEL, PRICES, Asker, Meter, Route, Routes, anthropic_base_url, anthropic_key,
                        base_url_ok, call_anthropic, make_client, price_key, show_url)
from brain.context import Shot, ZoneContext, ZoneHistory, response, words_response
from brain.doctrine import DEFAULT_ARC, ArcInvalid, stage_intent, stage_rows
from brain.doctrine import STAGE_ARC as STAGE_ROWS
from brain import feed as jev_feed
from brain import journal as jn
from brain.enrich import enrich
from brain.judges.channel import ChannelJudge
from brain.prompt import Prompt
from brain.judges.balance import HARDWARE as ZONES_HARDWARE
from brain.judges.balance import BalanceJudge
from brain.judges.dawn import DawnJudge
from brain.judges.dusk import DuskJudge
from brain.judges.night import NightJudge
from brain.judges.probe import ProbeJudge
from brain.judges.ramp import RampJudge
from brain.judges.salt import SaltJudge
from brain.judges.setpoints import CHOICES, MOVES, SHOT, THRESHOLD, SetpointsJudge
from brain.judges.setpoints import band as setpoint_band
from brain.judges.shot import ShotJudge
from brain.judges import targets as targets_judge
from brain.judges.targets import ShotSizeJudge, TargetsJudge
from brain.judges.stage import StageJudge
from brain.judges.zones import ZonesJudge
from brain.envelope import Directive, admit
from brain.journal import Journal
from brain.ledger import Ledger
from brain import council
from brain import plan_task as jev_plan
from brain import powers as jev_powers
from brain.setpoint_memory import SetpointMemory
import phase_options
from crop_steering_engine.ids import derived_id

ALL = ("dawn", "ramp", "salt", "dusk", "probe", "shot", "night", "zones", "stage", "setpoints", "channel", "balance", "feed", "report", "why",
       "plan", "targets", "shotsize")
# The judges behind the two powers that came with the power switches: always asked, because their power switches (off
# until the owner turns them on) decide whether they act; off, they advise.
POWER_JUDGES = ("targets", "shotsize")
# Every name a judge list could hold when the AI assistant moved to Claude (3.12): the judges then, and the retired
# alert-urgency judge ("alerts", replaced by the decaying re-notify) an old list may still name.
KNOWN_AT_MOVE = frozenset(ALL) | {"alerts"}
# What the old jev_* options are now called: the controller reads each under its new name, the old one as an alias.
OLD_NAMES = {f"ai_{k}": f"jev_{k}" for k in ("judges", "daily_calls", "budget_warn_pct", "reask_max", "unsure_below",
                                             "strict_after", "strict_prob", "flower_start", "flower_days")}
MOVED = "legacy_route_removed"  # BrainStatus.notice: the options name the removed first AI route (CS-712 once)
_upgrade_said = False  # the note about an old jev_judges list read as all is logged once a process
PENDING_S = 300  # a write Home Assistant has not reflected yet is not an operator's edit for this long
RETRIES = 3  # a write still not read back is sent again this many times, PENDING_S apart and doubling, then failed
REVERT_WINDOW_H = 30  # a rescue shot this soon after a setpoint change puts the old value back
PAUSE_H = 48  # and the zone's setpoints are left alone this long
# Only the brain writes these into /data (each keeps the name it was given first, so an old install keeps its
# record), so any one of them (empty or unreadable too) says it has run here.
BRAIN_FILES = ("jev_usage.json", "jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json")
PRODUCT = "Crop Steering Controller"  # controller.PRODUCT: the `engine` value on what the AI assistant publishes
# jev_legacy names the removed first route: an old options.json may still hold it (moved_from_legacy reads it).
PROVIDERS = ("auto", "rules", "claude_haiku", "jev_legacy")
NOTICES = "brain_notices.json"  # {"cs712": "<release>"}: the retired-route card is shown once a release
REPORTS = "brain_report.json"  # {room: {"grow_day", "asked_at", "report"}}: the daily report, across a restart
REPORT_AFTER_H = 3.0  # hours after lights-off: the setpoints judge has had its night window
REPORT_QUESTION = {"report": {"type": "report", "instructions": "Write the report for the grow-day that just ended "
                                                                "with write_report."}}
# The judges whose answers can act (the rest advise); empty on the panel while the brain cannot act.
ACTING_JUDGES = ("dawn", "ramp", "salt", "dusk", "probe", "setpoints", "targets", "shotsize")
# Each acting judge's power (brain.powers): with it off the judge only advises.
JUDGE_POWER = {"dawn": "advance_phase", "dusk": "advance_phase", "ramp": "ramp_control", "salt": "ec_mode",
               "probe": "set_probe_aside", "setpoints": "nudge_setpoints", "targets": "set_targets_from_achievable",
               "shotsize": "tune_shot_sizes"}
AI_BY = "AI assistant"  # the writer the setpoint change log names for a power's write (who: brain, no overlay)
# The Setpoints judge's own writes and put-backs (who: brain, an overlay that expires; who: safety). A pending write
# saved by an older release names its writer "Jev": OURS reads both.
SETPOINTS_BY = "AI setpoints judge"
PUT_BACK_BY = f"{SETPOINTS_BY} (put back)"
OURS = (SETPOINTS_BY, "Jev")
DAYS_KEEP = 7  # grow-days of each zone's scorecard kept for the targets and shot size judges
CHANGES_KEEP = 10  # the AI assistant's own changes kept per zone, with what it expected
FRIENDLY = "AI assistant"
WHY_PER_DAY = 20  # the questions a room may ask the brain a day; each is counted against the budget too
WHY_KEEP = 5  # the answers published, as the integration keeps the questions
WHY_FRESH_H = 1.0  # a question first seen older than this (the controller was away) is not asked
WHY = {"type": "why", "instructions": (
    "The grower asks why the controller or the AI assistant did something, or did not. Their question is the "
    "`question` in operator_text, and `zone_asked_about` says which zone it is about. Answer from this snapshot's "
    "`decisions` (the assistant's decision record for the room, newest first) and its other facts only. "
    "`kill_switch` is the room's kill switch: when it is not on, no zone of the room is watered. `holds_on` lists "
    "each external hold that is on or cannot be read: each one stops every shot. `zones` gives each zone's hold "
    "(`block`) and decision from the controller's last pass. Name the kill switch or the hold when it is the "
    "reason.")}


def judges():
    return [DawnJudge(), RampJudge(), SaltJudge(), DuskJudge(), ProbeJudge(), ShotJudge(), NightJudge(),
            ZonesJudge(), StageJudge(), SetpointsJudge(), ChannelJudge(), BalanceJudge(), TargetsJudge(),
            ShotSizeJudge()]


def option(options, name, default):
    """The option `name` (ai_*), or its old jev_* name: the Supervisor fills the new key in with its default on
    update, so a new key still at its default gives way to a value the operator saved under the old one."""
    new, old = options.get(name), options.get(OLD_NAMES.get(name, ""))
    if new is not None and new != "" and new != default:
        return new
    if old is not None and old != "":
        return old
    return default if new is None or new == "" else new


def has_run(data):
    """True when a file only the AI assistant writes is in `data` (the state file's folder): it has run here."""
    return any(os.path.lexists(os.path.join(data, name)) for name in BRAIN_FILES)


def legacy_settings(options):
    """True when the options still hold settings of the removed first AI route: its Cloudflare or TypeSafe keys."""
    cf = all(str(options.get(k) or "").strip() for k in ("cf_account_id", "cf_api_token"))
    return cf or bool(str(options.get("typesafe_api_key") or "").strip())


def lineage(options, data):
    """True when this install ran the removed first AI route, first match wins: a usage file that names the brain
    which wrote it says so; else any file only the brain writes; else a key only that route had. Never
    `jev_enabled`, which the Supervisor fills in from defaults."""
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
    provider: str  # rules or claude_haiku
    state: str  # rules, rules_no_key, model_invalid, sdk_missing, brain_off, start_failed, acting, dry_run
    words: str
    model: str | None = None
    key_set: bool = False
    deprecated_route: bool = False  # always False now that no retired route runs; the panel keeps the field
    notice: str | None = None  # legacy_route_removed: the options name the removed first route (CS-712 once)
    since: str = ""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def moved_from_legacy(options, data):
    """True when these options chose the removed first AI route: brain_provider jev_legacy, or auto on an install
    that ran it with its settings still saved. Such an install moves to Claude when it has a key, else to rules."""
    provider = str(options.get("brain_provider") or "auto").strip()
    if provider == "jev_legacy":
        return True
    return provider not in ("rules", "claude_haiku") and legacy_settings(options) and lineage(options, data)


def resolve_provider(options, data):
    """The BrainStatus for these options and the /data folder `data`. Pure: no network, never the key's value."""
    provider = str(options.get("brain_provider") or "auto").strip()
    provider = provider if provider in PROVIDERS else "auto"
    model = str(options.get("anthropic_model") or DEFAULT_MODEL).strip()
    key = bool(anthropic_key(options))
    base = anthropic_base_url(options)
    moved = moved_from_legacy(options, data)
    notice = MOVED if moved or legacy_settings(options) else None

    def rules(state, words):
        return BrainStatus("rules", state, words, key_set=key, notice=notice, since=_now())

    if provider == "rules":
        return rules("rules", "Rules.")
    if provider == "claude_haiku" or moved:
        if moved and options.get("jev_enabled", True) is False:
            return rules("brain_off", "Rules (brain off).")
        if not key:
            return rules("rules_no_key", "Rules: no Anthropic key." + (
                " The first AI route was removed: choose claude_haiku and add an Anthropic key." if moved else ""))
        if base and not base_url_ok(base):
            return rules("start_failed", "Rules: anthropic_base_url is not an http or https address. Correct it or "
                                         "make it blank.")
        if price_key(model, routed=bool(base)) is None:
            return rules("model_invalid", f"Rules: this release does not know the price of {model}, so it cannot keep "
                                          f"to your budget. Use {', '.join(PRICES)}"
                                          + (", or one of them after a router prefix (prefix/model)." if base else "."))
        if jev_client.anthropic is None and not base:
            return rules("sdk_missing", "The Claude brain is not available on this device (32-bit ARM). Rules are "
                                        "running.")
        dry = options.get("brain_dry_run") is True
        return BrainStatus("claude_haiku", "dry_run" if dry else "acting",
                           "Claude Haiku, advising only." if dry else "Claude Haiku, acting.", model=model,
                           key_set=True, notice=notice, since=_now())
    return rules("rules", "Rules." if notice else "Rules. Choose Claude Haiku and add a key to turn the brain on.")


def start_failed():
    return BrainStatus("rules", "start_failed", "The brain could not start, so rules are running. The app log says "
                                                "why.", since=_now())


def judge_names(options, log):
    """The judges asked. `ai_judges` is honoured as written: all (the default), or a list of names. The old
    `jev_judges` counts only while ai_judges is all. A list there was written for the first AI route, before the move
    to Claude: when every name in it is one known then, it is read as all, and the log says once which judges that
    adds. A list that names one never known then was not copied from that route's list, and is honoured as a list."""
    global _upgrade_said
    new = str(options.get("ai_judges") or "all").replace(" ", "")
    if new not in ("", "all"):
        return set(new.split(",")) & set(ALL)
    old = [n for n in str(options.get("jev_judges") or "all").replace(" ", "").split(",") if n]
    if not old or old == ["all"]:
        return set(ALL)
    if not set(old) <= KNOWN_AT_MOVE:
        return set(old) & set(ALL)
    added = [j for j in ALL if j not in old]
    if added and not _upgrade_said:
        _upgrade_said = True
        log(f"brain: the old jev_judges list ({', '.join(old)}) is read as all judges, so the AI assistant also "
            f"asks {', '.join(added)}. To ask fewer, list them in ai_judges")
    return set(ALL)


def build(options, state_path, log, status=None):
    """The brain, or None when rules run (BrainStatus says why). Its one route is the Anthropic API (or the router at
    anthropic_base_url) with the key, a Meter for the budget and the cached prompt, retried while a failure may pass
    (brain.client.Routes)."""
    data = os.path.dirname(state_path) or "."
    status = status or resolve_provider(options, data)
    if status.notice == MOVED:
        log("brain: these options name the first AI route, which this release removed"
            + (f", so the AI assistant uses {status.model} with your Anthropic key" if status.provider != "rules"
               else ", so the controller uses its rules until you choose claude_haiku and add an Anthropic key")
            + ". Its old Cloudflare and TypeSafe settings are not used")
    if status.provider == "rules":
        return None
    jev_client.log = log
    allowed = judge_names(options, log) | set(POWER_JUDGES)  # their power switches decide whether they act
    arc = str(options.get("stage_arc") or DEFAULT_ARC).strip()
    try:
        rows, arc_note = stage_rows(arc), None
    except ArcInvalid as e:
        rows, arc_note = (), (f"The stage arc {arc} is not complete in this release ({e}), so no stage arc is used. "
                              "Choose slab_default.")
    dry = options.get("brain_dry_run") is True
    budget = options.get("anthropic_daily_budget_usd")
    budget = 1.0 if budget is None else max(0.0, float(budget))
    warn_pct = float(option(options, "ai_budget_warn_pct", 80))
    meter = Meter(budget, status.model, warn_pct=warn_pct)
    prompt = Prompt(rows, arc if rows else None)
    key, base = anthropic_key(options), anthropic_base_url(options)
    found = [Route("Anthropic", partial(call_anthropic, model=status.model, prompt=prompt, meter=meter,
                                        client=make_client(key, base)), "anthropic", key)]
    asker = Asker("anthropic", key, None, daily_budget=int(option(options, "ai_daily_calls", 5000)),
                  transport=Routes(found, tries=int(options.get("jev_retries", 3))), warn_pct=warn_pct, meter=meter)
    ledger = Ledger(os.path.join(data, "jev_ledger.jsonl"))
    log(f"brain: claude_haiku, model {status.model}, budget US${meter.budget:.2f} until lights-on, key set"
        + (f", through the router at {show_url(base)}" if base else "")
        + (", advising only (dry run)" if dry else "") + f", judges {', '.join(sorted(allowed))}")
    log(prompt.describe())
    brain = Brain(asker, ledger, judges(), allowed=allowed, log=log,
                  reask_max=int(option(options, "ai_reask_max", 2)),
                  unsure_below=float(option(options, "ai_unsure_below", 0.7)),
                  strict_after=int(option(options, "ai_strict_after", 3)),
                  strict_prob=float(option(options, "ai_strict_prob", 0.8)),
                  enrich=enrich, dry_run=dry)
    brain.routes, brain.status, brain.prompt = [r.name for r in found], status, prompt
    brain.arc, brain.arc_rows, brain.arc_note = arc, rows, arc_note
    brain.journal = Journal(os.path.join(data, "jev_journal.jsonl"))
    brain.setpoints = SetpointMemory(os.path.join(data, "jev_setpoints.json"))
    brain.usage_path = os.path.join(data, "jev_usage.json")
    restore_usage(asker, brain.usage_path)
    save_usage(brain)  # names this brain in /data before its first ask: the next start reads it (lineage)
    brain.feed = jev_feed.Feed(asker, feed_meta) if "feed" in allowed else None
    brain.report = "report" in allowed
    brain.report_path = os.path.join(data, REPORTS)
    brain.why = "why" in allowed
    brain.plan = jev_plan.PlanTask(asker, plan_meta) if "plan" in allowed else None
    brain.flower_start = flower_option(option(options, "ai_flower_start", ""))
    brain.flower_days = int(option(options, "ai_flower_days", 56) or 56)
    return brain


def plan_meta(room, now):
    """The "_brain" key of the plan task's question (a room task: it does not pass through Brain)."""
    return {"room": room, "zone": "room", "judge": "plan", "asked": now.isoformat(timespec="minutes"),
            "interlocks": "none: the plan task advises, a person changes the plan",
            "data_quality": "the plan as the integration publishes and previews it, and each zone's phase today"}


def feed_meta(room, now):
    """The "_brain" key of the Feed task's question (a room task: it does not pass through Brain)."""
    return {"room": room, "zone": "room", "judge": "feed", "asked": now.isoformat(timespec="minutes"),
            "interlocks": "none: a feed proposal moves nothing, a person decides",
            "data_quality": "the feed's readings this pass and each zone's latest probe reading"}


def flower_option(value):
    """`ai_flower_start` (old name jev_flower_start): one entity or date for every room, or `room=value` pairs, comma separated.
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
    """The brain's BrainStatus; a brain built without one (a test, a script) is taken as acting."""
    return getattr(brain, "status", None) or BrainStatus("claude_haiku", "acting", "Claude Haiku, acting.")


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
        # the room's sump water-balance estimate, only with the runoff estimator set to ai (controller._watch_runoff)
        **({"runoff_estimate": room._runoff_words} if getattr(room, "_runoff_words", None) else {}),
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
        cultivar=getattr(room, "zone_cultivars", {}).get(zone),
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
        powers=room_powers(c, room, now),
        targets=targets_view(c, room, zone, p, now) if st["phase"] == "P3" else None,
        shots=shots_view(c, room, zone, p, now) if st["phase"] == "P3" else None,
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
    ai_readback(c, room, zone, now)
    guard_setpoints(c, room, zone, now)
    levers = judge_levers(c, room)
    _handover(c, room, zone, p, now, levers)
    # The room's no-touch window: nothing is asked and nothing acts until it ends, the rules carry on; the owner's
    # target powers alone are not held by it (they set tomorrow's settings at night, not today's watering).
    only = set(POWER_JUDGES) if c._no_touch_until(room, now) is not None else None
    if only and not any(j.name in only for j in getattr(c.jev, "judges", ())):
        return {}
    if haiku(c):
        if not c._on(room.enable_flag, False):
            return {}  # the kill switch is off: the engine decides alone, and nothing is asked (it costs money)
        if room_health(c, room, now)[0] != "ok":
            return {}  # stale or impaired readings: the engine decides alone, and nothing is asked (fail-closed)
        c.jev.prompt.use(getattr(r, "substrate", "generic") for r in getattr(c, "rooms", [room]))
    ctx = zone_context(c, room, zone, snap, p, now, lights_on)
    out = {}
    for d, _why in (c.jev.tick(ctx, allowed=only) if only else c.jev.tick(ctx)):
        if d.kind == "alert":
            c._jev_alert(room, zone, d.judge, d.value)
        elif d.kind == "setpoint":
            if d.value.get("suffix") in levers:
                apply_setpoint(c, room, zone, d, ctx, now)
            else:
                _note(c, room, zone, "would act", d.value.get("words", ""), "no action",
                      "the Auto setpoints learner holds this number today")
        elif d.kind in ("targets", "shot_size"):
            apply_values(c, room, zone, d, ctx, now)
        else:
            out[d.kind] = d
    if "distrust" in out and getattr(c.jev, "setpoints", None) is not None:  # today's peak is then not trusted
        _ai(c, room, zone)["distrusted_day"] = c._grow_day_start(room, now).isoformat()
    return out


# ---------- the Setpoints judge's side (docs/AI_ASSISTANT.md) ----------
def owns_setpoints(c):
    """True when the AI assistant's Setpoints judge runs: it then owns each zone's P2 shot size and re-water threshold."""
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
    return (SHOT, THRESHOLD) if _acting_latch(c, room) else ()


def _acting_latch(c, room):
    """Whether the brain holds its numbers in `room` this grow-day: at start whenever it can act, off on the first pass
    it cannot, back only at a lights-on at which it can (lights_on)."""
    held = c.jev.__dict__.setdefault("levers_held", {})
    if room.slug not in held:
        held[room.slug] = can_act(c)  # at start: with the judge whenever the brain can act then
    elif held[room.slug] and not can_act(c):
        held[room.slug] = False
    return held[room.slug]


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
    """The zone's OWN number for `suffix`, or None: the AI assistant never moves a room-level value."""
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

    The operator's own value ("home") is the centre of each band. A value the AI assistant did not write is the operator's:
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
            continue  # the AI assistant's write has not reached Home Assistant yet
        expected = rec["written"].get(suffix, rec["home"].get(suffix))
        if expected is None or abs(v - float(expected)) > 1e-6:
            home = rec["home"].get(suffix)
            # Back on the operator's own value (an AI overlay that ran out or was undone): no edit by hand.
            if expected is not None and (home is None or abs(v - float(home)) > 1e-6):
                _note(c, room, zone, "set by hand", f"{suffix.replace('_', ' ')} {expected:g} -> {v:g}",
                      "acted", "your value is the new centre of the AI assistant's range")
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
        "changed_today": last.get("day") == day, "frozen": frozen, "day": day, **notch_history(c, room, zone, now),
        "last_words": _last_words(last),
    }


def _last_words(last):
    if not last:
        return None
    return (f"{last.get('at', '')[:16].replace('T', ' ')}: {last.get('words')}"
            + (" (did not reach Home Assistant)" if last.get("failed")
               else " (put back after a rescue shot)" if last.get("reverted") else ""))


def _pending(suffix, frm, to, by, now, ledger_id=None):
    """A write to read back: sent once now, again RETRIES times, PENDING_S apart and doubling, while it has not landed.
    `ledger_id`: the ledger row the write carries out, named again by each write sent again."""
    out = {"suffix": suffix, "from": frm, "to": to, "by": by, "at": now.isoformat(timespec="seconds"),
           "tries": 0, "next": (now + timedelta(seconds=PENDING_S)).isoformat(timespec="seconds")}
    if ledger_id:
        out["ledger_id"] = ledger_id
    return out


def _ledger_id(c, room, zone, d, now):
    """The id of the ledger row the brain recorded for this directive on this pass (Brain._judge), as a string, or None
    (a dry run records none, nor does an answer already acted on). The write names it in its claim, so the
    integration's target.changed carries it, and the row's ai.outcome finds that change (changes.py)."""
    at = now.isoformat(timespec="seconds")
    for e in reversed(list(getattr(getattr(c.jev, "ledger", None), "entries", None) or ())):
        if isinstance(e, dict) and (e.get("judge"), e.get("room"), e.get("zone"), e.get("action"), e.get("at")) == (
                d.judge, room.slug, zone, d.kind, at):
            return str(e["id"])
    return None


def _named(ledger_id):
    """_auto_write's ledger_id keyword, only when there is one (a write the ledger holds no row for is as before)."""
    return {"ledger_id": ledger_id} if ledger_id else {}


def ledger_events(entry, what=None):
    """The journal events one ledger row mirrors (spec 3, Judgement): "record" its ai.judgement, "resolve" its ai.outcome
    once its check is known, None both (the backfill) -> [(kind, Outbox.emit keywords)]. Each id is derived from the
    row, so a row is the same event live or backfilled, and correlation.ledger_id is the row's id."""
    out = []
    ledger_id = str(entry["id"])

    def utc(at):  # a ledger time is the pass's wall clock with no zone: its id never depends on the box's zone
        return at if at.tzinfo else at.replace(tzinfo=timezone.utc)

    common = {"zone": entry.get("zone"), "actor": "ai", "detail": entry.get("judge"),
              "correlation": {"ledger_id": ledger_id}}
    if what in (None, "record"):
        at = datetime.fromisoformat(entry["at"])
        out.append(("ai.judgement", {
            **common, "now": at, "event_id": derived_id(utc(at), f"ledger:{ledger_id}"),
            "outcome": "refused" if entry.get("action") == "refused" else "ok",
            "data": {"judge": entry.get("judge"), "label": entry.get("label"), "action": entry.get("action"),
                     "power": JUDGE_POWER.get(entry.get("judge")), "evidence": entry.get("evidence") or {}}}))
    result = entry.get("outcome")
    if what in (None, "resolve") and isinstance(result, dict):
        known = datetime.fromisoformat(result.get("at") or entry.get("check_at") or entry["at"])
        out.append(("ai.outcome", {
            **common, "now": known, "event_id": derived_id(utc(known), f"ledger:{ledger_id}:outcome"),
            "data": {"what": result.get("what"), "good": bool(result.get("good"))}}))
    return out


def journal_ledger(c):
    """Mirror the AI assistant's ledger into the controller's journal outbox (Ledger.listener): each row as it is
    recorded and each check as it is written back, into the room the row names (a slug, mapped to its prefix). A row
    for a room no longer here is left out. Only a local append (journal_out.Outbox.emit), never a wait."""
    ledger = getattr(getattr(c, "jev", None), "ledger", None)
    if ledger is None or getattr(c, "journal", None) is None:
        return

    def mirror(what, entry):
        room = next((r for r in list(getattr(c, "rooms", None) or ()) if r.slug == entry.get("room")), None)
        if room is not None:
            for kind, kw in ledger_events(entry, what):
                c.journal.emit(room.prefix, kind, **kw)

    ledger.listener = mirror


def readback(c, room, zone, now):
    """Read back the zone's number after a AI assistant write (SF-25): landed, it is done; an edit by hand since then is the
    operator's (setpoint_view); still the old value or unreadable, it is sent again with a doubling wait, and after
    RETRIES it is recorded as failed and the AI assistant's memory goes back to the value Home Assistant still holds."""
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
    # The AI assistant's own move stops when the operator stops automatic targets; a put-back restores theirs, so it never does
    allowed = pend["by"] not in OURS or (owns_setpoints(c) and not getattr(room, "strategy_required", False)
                                      and c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False))
    if allowed and pend["tries"] < RETRIES:
        pend["tries"] += 1
        pend["next"] = (now + timedelta(seconds=PENDING_S * 2 ** pend["tries"])).isoformat(timespec="seconds")
        learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
        c._auto_write(room, zone, suffix, frm, to, learn, now, by=pend["by"], **_named(pend.get("ledger_id")))
        mem.save()
        return
    rec["pending"] = None
    rec["written"][suffix] = frm  # what Home Assistant still holds is not an edit by hand
    last = rec.get("last") or {}
    if pend["by"] in OURS and last.get("suffix") == suffix and last.get("to") == to:
        last["failed"] = True
    mem.save()
    why = (f"Home Assistant still shows {frm:g} after {pend['tries'] + 1} tries" if allowed
           else "automatic targets were switched off before it landed")
    _note(c, room, zone, "write failed", f"{suffix.replace('_', ' ')} {frm:g} -> {to:g}", "failed", why)


def notch_history(c, room, zone, now):
    """The notch budget's history for a zone from the ledger (envelope.notch_budget): `notches`, the (at, suffix,
    step) moves made, and `setbacks`, when a move was refused or a move's check came back bad. Read with defaults:
    an entry without a time is skipped, and an outcome without its own time counts from check_at."""
    notches, setbacks = [], []
    for e in list(getattr(getattr(c.jev, "ledger", None), "entries", None) or ()):
        if e.get("judge") != "setpoints" or e.get("room") != room.slug or e.get("zone") != zone:
            continue
        try:
            at = datetime.fromisoformat(e.get("at") or "")
            outcome = e.get("outcome") if isinstance(e.get("outcome"), dict) else {}
            bad = outcome and outcome.get("good") is False
            known = datetime.fromisoformat(outcome.get("at") or e.get("check_at") or e["at"]) if bad else None
        except (TypeError, ValueError):
            continue
        if e.get("action") == "setpoint" and e.get("label") in MOVES:
            notches.append((at, MOVES[e["label"]][0], abs(MOVES[e["label"]][1])))
        elif e.get("action") == "refused":
            setbacks.append(at)
        if known is not None:
            setbacks.append(known)
    return {"notches": notches, "setbacks": setbacks}


def apply_setpoint(c, room, zone, d, ctx, now):
    """Write one admitted notch to the zone's own number and remember it."""
    v = d.value
    mem = c.jev.setpoints
    rec = mem.zone(room.slug, zone)
    learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
    ledger_id = _ledger_id(c, room, zone, d, now)
    wrote = c._auto_write(room, zone, v["suffix"], float(v["from"]), float(v["to"]), learn, now, by=SETPOINTS_BY,
                          **_named(ledger_id))
    rec["written"][v["suffix"]] = float(v["to"])
    rec["pending"] = _pending(v["suffix"], float(v["from"]), float(v["to"]), SETPOINTS_BY, now, ledger_id)
    rec["last"] = {"suffix": v["suffix"], "from": float(v["from"]), "to": float(v["to"]),
                   "at": now.isoformat(timespec="seconds"), "day": (ctx.setpoints or {}).get("day"),
                   "words": v["words"], "choice": v["choice"], "reverted": False}
    mem.save()
    # For the phones that tick the AI assistant (docs/NOTIFICATIONS.md): no card, a push only, with Keep and Undo for the
    # number written (an AI overlay in the integration).
    c._notify_event("jev_setpoint", room, zone, v["words"],
                    f"{CHOICES.get(v['choice'], v['choice'])} the AI assistant's Setpoints judge, {d.why}.",
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
    if cur is not None and abs(cur - float(last["to"])) < 1e-6:  # still the AI assistant's value: put the operator's back
        learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
        c._auto_write(room, zone, last["suffix"], float(last["to"]), float(last["from"]), learn, now,
                      by=PUT_BACK_BY)
        rec["written"][last["suffix"]] = float(last["from"])
        rec["pending"] = _pending(last["suffix"], float(last["to"]), float(last["from"]), PUT_BACK_BY, now)
    last["reverted"] = True
    rec["frozen_until"] = (now + timedelta(hours=PAUSE_H)).isoformat(timespec="seconds")
    mem.save()
    why = f"a rescue shot at {rescue.start:%H:%M} after '{last['words']}'"
    _note(c, room, zone, "safety revert", f"put back: {last['suffix'].replace('_', ' ')} {last['to']:g} -> "
          f"{last['from']:g}", "acted", f"{why}; paused {PAUSE_H} h")
    c._alert(f"auto_{room.slug}_z{zone}", "CS-404", "automatic targets paused",
             f"The AI assistant changed the water of this zone ({last['words']}). The controller put the change "
             f"back, because {why}. The AI assistant does not change the setpoints of this zone for {PAUSE_H} h. "
             "The shots continue with your own values.",
             room=room, zone=zone)


def advance(c, room, zone, snap, d, now, p=None):
    """Move the zone forward one phase as the AI assistant judged, with the bookkeeping the engine does itself (a ramp handed
    over while it stalls re-waters under what it reached: Controller._record_phase)."""
    st = room.state[zone]
    if st["phase"] == "P0" and p is not None and snap.phase_minutes < getattr(p, "p0_min_wait_min", 0.0):
        return snap  # the room's P0 minimum wait binds the AI assistant too: a person's floor is always respected
    was, st["phase"] = st["phase"], d.value
    c._record_phase(room, zone, st, was, d.value, now, f"the AI assistant's {d.judge} judge: {d.why}", snap, p)
    st["last_phase_change"] = now
    if d.value == "P1":
        st["shots"] = 0
    c._save_state()
    c._notify_event("phase", room, zone, was, d.value, f"the AI assistant's {d.judge} judge: {d.why}")
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
    room._jev_params = params  # this pass's params, for the setpoints published with the zone's AI assistant sensor


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
    """The usage file, named for the brain that writes it (lineage reads `provider` first). Never the key."""
    path = getattr(brain, "usage_path", None)
    s = brain.asker.stats
    data = {k: s.get(k) for k in USAGE_KEYS}
    data["provider"] = getattr(getattr(brain, "status", None), "provider", "claude_haiku")
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
    """What the dashboard shows of the Setpoints judge for a zone: the operator's values, the AI assistant's range around them,
    the current values, the last move and any pause. None without the AI assistant's Setpoints judge or this pass's params."""
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


def route_card(c, room):
    """CS-712, once a release (only once Home Assistant has the card): the options still name the first AI route,
    which this release removed. The card says what runs instead and what to change."""
    if not _route_card_due(c):
        return
    status = getattr(c, "brain_status", None)
    if status is not None and status.provider == "claude_haiku":
        words = ("The first AI route of the AI assistant was removed. This room now uses Claude with your Anthropic "
                 "API key, with every judge. The water does not change. To stop this message, remove the old "
                 "Cloudflare and TypeSafe options and set brain_provider to claude_haiku.")
    else:
        words = ("The first AI route of the AI assistant was removed, so the controller uses its own rules. To turn "
                 "the AI assistant on again, set brain_provider to claude_haiku and add your Anthropic API key. The "
                 "old Cloudflare and TypeSafe options are not used.")
    if c._jev_alert(room, None, "route", {"code": "CS-712", "title": "the first AI route was removed",
                                          "message": words}):
        _route_card_shown(c)


def runtime_alerts(c, room):
    """CS-706 once a day when the AI assistant's calls reach the warning share of the budget (or once a window when the Claude
    brain's spend reaches it), CS-707 when one of this room's zones has a judge go on the stricter gate
    (Brain.events), CS-708 once a window when the Claude brain's budget is spent, CS-709 when its key is refused or it
    stops answering, and CS-712 when the options name the removed first route. A card Home Assistant could not take is raised again."""
    brain, asker = c.jev, c.jev.asker
    meter = getattr(asker, "meter", None)
    if asker.take_warning() or (meter is not None and meter.take("warn")):
        c._jev_alert(room, None, "budget", {
            "code": "CS-706", "title": "the AI assistant used most of the calls of today",
            "message": (f"The AI assistant made {asker.stats.get('calls')} of its {asker.daily_budget} calls today, "
                        "for all rooms. When it uses all the calls, the rules of the controller decide. If this "
                        "occurs on a usual day, increase ai_daily_calls in the controller options."
                        if meter is None else
                        f"The AI assistant used most of its AI budget of US${meter.budget:.2f} until the next "
                        "lights-on. When it spends the budget, the rules of the controller decide until then.")})
    mine = [e for e in brain.events if e[1] == room.slug]
    brain.events = [e for e in brain.events if e[1] != room.slug]
    for _kind, _room, zone, judge in mine:
        c._jev_alert(room, zone, judge, {
            "code": "CS-707", "title": "the AI assistant uses the stricter gate for this zone",
            "message": (f"The {judge} judge of the AI assistant made {brain.strict_after} calls in sequence for this "
                        "zone that were not correct. Until 2 calls in sequence are correct, the judge acts only "
                        f"when its two questions agree at {brain.strict_prob:g} or more and a second look gives the "
                        "same answer. The AI assistant continues to judge. When it is not sure enough, the rules of "
                        "the controller act.")})
    if meter is not None:
        if meter.take("spent") and not c._jev_alert(room, None, "spent", {
                "code": "CS-708", "title": "the AI assistant used its AI budget",
                "message": (f"The AI assistant used its AI budget of US${meter.budget:.2f} until the next lights-on. "
                            "Until then, the controller uses its own rules, including the Auto setpoints learner. "
                            "If this occurs on a usual day, increase anthropic_daily_budget_usd in the controller "
                            "options.")}):
            meter.again("spent")
        if meter.take("brain") and not c._jev_alert(room, None, "brain", {
                "code": "CS-709", "title": "the AI assistant is not available",
                "message": ("The AI assistant cannot reach Claude. " + _STATE_WORDS.get(meter.state(), "It does "
                            "not answer.") + " The controller uses its own rules.")}):
            meter.again("brain")
    if _status(brain).notice == MOVED:
        route_card(c, room)


_STATE_WORDS = {
    "budget_spent": "It spent the AI budget of today. Rules until the next lights-on.",
    "paused": "Anthropic told it to wait. Rules until Anthropic answers again.",
    "unavailable": "Anthropic does not answer. Rules for 1 h, then it tries again.",
    "auth_failed": "Anthropic refused the API key. Rules until the controller restarts with a valid key.",
    "model_invalid": "Anthropic does not know the model. Rules until the controller restarts.",
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
    powers = room_powers(c, room, now)
    no_touch = c._no_touch_until(room, now)
    out = {"provider": status.provider, "model": status.model, "mode": "dry_run" if brain.dry_run else "acting",
           "state": state, "state_words": words, "notice": status.notice, "key_set": status.key_set,
           "deprecated_route": status.deprecated_route, "fallback_since": getattr(brain, "_fallback_since", None),
           "no_touch_until": no_touch.isoformat(timespec="minutes") if no_touch else None,
           "stage_arc": {"id": getattr(brain, "arc", DEFAULT_ARC), "in_force": bool(getattr(brain, "arc_rows", STAGE_ROWS)),
                         "words": getattr(brain, "arc_note", None)},
           "judges_acting": [j for j in built if j in ACTING_JUDGES and health == "ok"
                             and jev_powers.allowed(powers, JUDGE_POWER.get(j))] if acting else [],
           "judges_advising": [j for j in built if j not in ACTING_JUDGES]
           + (["feed"] if getattr(brain, "feed", None) else [])
           + (["report"] if getattr(brain, "report", False) else [])
           + (["why"] if getattr(brain, "why", False) else [])
           + (["plan"] if getattr(brain, "plan", None) else []),
           **powers_published(c, room, now)}
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
                   cache_savings_estimate_usd=snap.get("cache_savings_estimate_usd"),
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
        attrs = {"judges": status, "strict": strict, "friendly_name": f"Zone {zone} AI assistant", "engine": PRODUCT}
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
            "stage": stage_info(c, room, now), **panel(c, room, now), "plan": room.__dict__.get("_plan_panel"),
            "friendly_name": FRIENDLY, "engine": PRODUCT})
    journal = getattr(brain, "journal", None)
    if journal is not None:
        entries = journal.recent(room.slug)
        ha_set(f"sensor.crop_steering_{room.prefix}jev_log", headline(entries[0] if entries else None),
               {"entries": entries, "friendly_name": "AI assistant decisions", "engine": PRODUCT})
    feed_task(c, room, now)
    report_task(c, room, now, ha_set)


def _plan_note(c, room, verdict, drift, action, reason, why, result="advised"):
    journal = getattr(c.jev, "journal", None)
    if journal is not None:
        journal.add({"t": datetime.now().isoformat(timespec="seconds"), "room": room.slug, "zone": drift.zone,
                     "judge": "plan", "title": "Plan", "kind": "decision",
                     "verdict": "no answer" if verdict is None else str(verdict.label).replace("_", " "),
                     "p": None if verdict is None else verdict.prob,
                     "agreed": None if verdict is None else verdict.agreed, "action": action[:80],
                     "result": result, "reason": reason[:120], "why": why or ""})


def plan_task(c, room, now, view, drifts):
    """The plan task's pass for the room (brain/plan_task.py), under the Claude brain only: an answer that came in is
    read once and picks the suggestion the panel shows for its drift; the room is asked about the highest drift the
    brain may be asked about when it is due, with the kill switch on, no no-touch window and fresh readings (SF-26).
    -> {class: (suggestion, why, action)} for the panel, or None. Never a write, never an arm, edit or disarm."""
    brain = getattr(c, "jev", None)
    task = getattr(brain, "plan", None)
    if task is None or not haiku(c):
        return None
    rec = task.record(room.slug, view.expected_day.isoformat())
    asked = [d for d in drifts if d.ask]
    ans = task.answer(rec)
    if ans is not None and rec["drift"] is not None:
        drift = rec["drift"]
        verdict = council.combine(ans.answers, "cause")
        index, why = jev_plan.pick(verdict, drift)
        suggestion = drift.suggestions[index] if index < len(drift.suggestions) else drift.suggestions[0]
        rec["notes"][drift.cls] = (suggestion, why, "advise")
        rec["reask_due"] = jev_plan.unsure(verdict) and not rec["reasked"]
        _plan_note(c, room, verdict, drift, suggestion, "a suggestion for a person: nothing is changed"
                   if index or why else "unsure: the drift's own suggestion stands", why)
        keep = council.combine(ans.answers, "keep_yesterday")
        if keep is not None:
            _plan_keep(c, room, now, view, rec, drift, keep)
    _plan_catch_up(c, room, now, view, rec)
    _plan_outcomes(c, room, now)
    target = asked[0] if asked else None
    if (target is not None and c._on(room.enable_flag, False) and c._no_touch_until(room, now) is None
            and room_health(c, room, now)[0] == "ok" and task.due(rec, target, now, view.lights_on_at)):
        extra = {"phase_log": (getattr(room, "_adherence", None) or {}).get("phase_log"),
                 "holds": _plan_holds(c, room),
                 "recent_plan_events": [f"{e.get('t', '')[11:16]} {e.get('verdict')}: {e.get('action')}"
                                        for e in (brain.journal.recent(room.slug, 30) if brain.journal else [])
                                        if e.get("judge") == "plan"][:3]}
        state = jev_plan.evidence(view, target, extra)
        record = brain.ledger.track("plan", room.slug, "room")
        if record:
            state["your_track_record"] = record
        if rec["reask_due"] and rec["cls"] == target.cls:
            state["second_look"] = {"why_again": "your last answer was unsure, or your two readings of it disagreed"}
        questions = dict(jev_plan.QUESTIONS)
        if _bridge_candidate(c, room, view, target):
            questions.update(jev_plan.KEEP)
        if task.ask(rec, state, questions, now):
            rec["cls"], rec["drift"] = target.cls, target
    live = {d.cls for d in drifts}
    return {cls: note for cls, note in rec["notes"].items() if cls in live}


def _bridge_candidate(c, room, view, drift):
    """Whether the brain is asked keep_yesterday too: a missed plan day that changes targets, held by a stale probe,
    once a photoperiod, outside a cool-down."""
    adh = getattr(room, "_adherence", None) or {}
    cool = adh.get("cooldown_until")
    return (drift.cls in jev_plan.BRIDGE_CLASSES and bool(drift.extra.get("zones"))
            and view.attrs.get("degraded_kind") == "probe_stale"
            and adh.get("bridge_day") != view.expected_day.isoformat()
            and not (cool and datetime.fromisoformat(cool) > view.now))


def _plan_keep(c, room, now, view, rec, drift, keep):
    """A keep_yesterday answer: a firm no (and on the stricter gate, a second within 45 min) makes the catch_up
    directive from code's own values; anything else keeps the plan's day where it is."""
    no = jev_plan.catch_up_says_no(keep)
    strict = c.jev.ledger.strict("plan", room.slug, "room")
    if no and strict:
        last, rec["keep_no_at"] = rec.get("keep_no_at"), now
        no = last is not None and now - last <= timedelta(minutes=jev_plan.STRICT_WITHIN_MIN)
    why = (keep.notes or [""])[0]
    if not no:
        _plan_note(c, room, keep, drift, "keep yesterday's targets", "the plan's day waits for the reading", why)
        return
    rec["directive"] = Directive("plan", "catch_up", {
        "day": view.expected_day.isoformat(), "revision": view.attrs.get("revision"),
        "zones": {z: dict(v) for z, v in drift.extra["zones"].items()}},
        f"keep_yesterday: no ({why})"[:200], now + timedelta(minutes=45))
    rec["directive_verdict"] = keep


def _plan_context(c, room, now, view):
    snap = getattr(room, "strategy_snapshot", None) or {}
    adh = getattr(room, "_adherence", None) or {}
    rt = room.__dict__.get("_plan_rt") or {}
    kind = view.attrs.get("degraded_kind")
    hold = _plan_holds(c, room)
    if getattr(room, "_setup_pending", None) or not c._room_active(room) or c._dosing_hold(room):
        hold = "; ".join(x for x in (hold if hold != "none" else "", "setup, room or dosing hold") if x)
    cool = adh.get("cooldown_until")
    rows = view.in_force()
    return jev_plan.PlanContext(
        now=now, status=view.status, required=bool(snap.get("required")), error=snap.get("error"),
        managed=tuple(sorted(snap.get("managed") or ())), room_zones=tuple(sorted(room.zones)),
        revision=view.attrs.get("revision"), expected_day=view.expected_day.isoformat(),
        in_force_days={z: r.get("applied_day") or view.attrs.get("grow_day") for z, r in rows.items()},
        parameters={z: r.get("parameters") for z, r in rows.items()},
        preview=(view.preview or {}).get("today") or {}, degraded_kind=kind, degraded_since=rt.get("degraded_since"),
        lights_on=view.lights_on, lights_on_at=view.lights_on_at, lights_off_at=view.lights_off_at,
        busy=bool(getattr(c, "_busy", False) or getattr(room, "shot_inflight", None)),
        room_hold=None if hold == "none" else hold, health=room_health(c, room, now)[0],
        no_touch=c._no_touch_until(room, now) is not None,
        cooldown_until=datetime.fromisoformat(cool) if cool else None, bridge_day=adh.get("bridge_day"),
        powers=room_powers(c, room, now))


def _plan_catch_up(c, room, now, view, rec):
    """A catch_up directive the brain's firm no made, put through the envelope each pass until it acts or runs
    out (45 min). Dry run journals "would act". Acting stores the bridge (the controller merges it into the plan's
    snapshot on the next pass, controller._bridged), and raises the CS-713 card that says so."""
    d = rec.get("directive")
    if d is None:
        return
    drift = rec.get("drift")
    ok, why = admit(d, _plan_context(c, room, now, view))
    if not ok:
        if why == "expired" or now > d.expires:
            rec["directive"] = None
            _plan_note(c, room, rec.get("directive_verdict"), drift, "catch up today's plan day", why, "",
                       "refused")
        elif not rec.get("refused_said"):
            rec["refused_said"] = True
            _plan_note(c, room, rec.get("directive_verdict"), drift, "catch up today's plan day", why, "",
                       "refused")
        rec["notes"][drift.cls] = (rec["notes"].get(drift.cls, (drift.suggestions[0], "", ""))[0],
                                   f"refused: {why}", "advise")
        return
    rec["directive"] = None
    words = (f"The controller applied the targets of day {d.value['day']} for "
             + ", ".join(view.titles.get(int(z)) or f"zone {z}" for z in d.value["zones"]))
    if getattr(c.jev, "dry_run", False):
        rec["notes"][drift.cls] = (words + " (advising only: not applied).", d.why, "would act")
        _plan_note(c, room, rec.get("directive_verdict"), drift, "catch up today's plan day", why, d.why,
                   "would act")
        return
    adh = room.__dict__.setdefault("_adherence", {})
    adh["bridge"] = {"day": d.value["day"], "revision": d.value["revision"],
                     "zones": {str(z): v for z, v in d.value["zones"].items()},
                     "since": now.isoformat(timespec="minutes"), "checked": False}
    adh["bridge_day"] = d.value["day"]
    room._strategy_batch_invalid = True  # this pass fires nothing more; the next one runs on the bridged targets
    c._save_state()
    c.jev.ledger.record("plan", room.slug, "room", "catch_up", "catch_up", evidence={"why": d.why},
                        check_at=now + timedelta(hours=6), check={"day": d.value["day"],
                                                                 "zones": sorted(d.value["zones"])}, at=now)
    c.jev.log(f"[plan] {room.slug} bridged day {d.value['day']} for zones {sorted(d.value['zones'])}: {d.why}")
    reason = view.attrs.get("degraded_reason") or "a stale probe"
    c._jev_alert(room, None, "plan_bridge", {
        "code": "CS-713", "title": "the controller applied the plan targets of today",
        "message": (f"{words} at {now:%H:%M}, while the plan waits for this: {reason}. The targets stay until the "
                    f"plan applies day {d.value['day']} itself, or until the next lights-on. The controller did not "
                    "change the plan.")})
    rec["notes"][drift.cls] = (words + f" at {now:%H:%M}.", d.why, "acted")
    _plan_note(c, room, rec.get("directive_verdict"), drift, "catch up today's plan day", why, d.why, "acted")


def _plan_outcomes(c, room, now):
    """A catch-up's check, 6 h after it acted: good when the plan caught up, or the zones ran without a rescue
    shot; a bad one rests the catch-up for 7 days (the cool-down)."""
    for entry in c.jev.ledger.due(now):
        if entry.get("judge") != "plan" or entry.get("room") != room.slug:
            continue
        at = datetime.fromisoformat(entry["at"])
        zones = (entry.get("check") or {}).get("zones") or ()
        rescues = [z for z in zones for s in _hist(room, int(z)).shots if s.start >= at and s.kind == "p3_emergency"]
        adh = room.__dict__.setdefault("_adherence", {})
        caught = adh.get("bridge_outcome") == (entry.get("check") or {}).get("day")
        good = caught or not rescues
        what = ("the plan applied the day itself" if caught else
                "no rescue shot since" if good else f"a rescue shot on zone {rescues[0]}")
        c.jev.ledger.resolve(entry["id"], what, good, at=now)
        if not good:
            adh["cooldown_until"] = (now + timedelta(days=7)).isoformat(timespec="minutes")
            c._save_state()
        journal = getattr(c.jev, "journal", None)
        if journal is not None:
            journal.add(jn.outcome(room.slug, None, "plan", now, "catch_up", what, good, of=entry.get("at"),
                                   action="catch_up"))


def _plan_holds(c, room):
    """What holds the whole room now, in words: the kill switch, a hardware latch, a held plan."""
    holds = [] if c._on(room.enable_flag, False) else ["the kill switch is off: no valve opens"]
    if getattr(room, "hardware_fault", None):
        holds.append("a hardware fault has latched")
    snap = getattr(room, "strategy_snapshot", None) or {}
    if snap.get("error"):
        holds.append(f"the plan holds its steering: {snap['error']}")
    return "; ".join(holds) or "none"


def _band(band, unit):
    lo, hi, unread = band
    if unread:
        return f"can't be read ({unread})"
    if lo > 0 and hi > 0:
        return f"{lo:g} to {hi:g}{unit}"
    return f"at least {lo:g}{unit}" if lo > 0 else f"at most {hi:g}{unit}" if hi > 0 else "none set"


def feed_facts(c, room, now):
    """What the Feed task is shown: the feed's EC and pH against their bands, and each zone's latest pore EC against
    its maintenance target."""
    feed = c._read_feed_ec(room)
    facts = {"feed_ec": "not reading" if feed is None else f"{feed:.2f} mS/cm",
             "feed_ec_band": _band(c._feed_band(room, "ec"), " mS/cm")}
    if room.feed_ph_sensor:
        ph = c._read_feed_ph(room)
        facts["feed_ph"] = "not reading" if ph is None else f"{ph:.2f}"
        facts["feed_ph_band"] = _band(c._feed_band(room, "ph"), "")
    params, zones = room.__dict__.get("_jev_params") or {}, {}
    for zone in room.zones:
        h = room.__dict__.get("_jev_hist", {}).get(zone)
        ec = next((r[2] for r in reversed(h.readings) if r[2] is not None), None) if h else None
        p = params.get(zone)
        words = "pore EC not reading" if ec is None else f"pore EC {ec:.2f} mS/cm"
        if p is not None and p.ec_target_p2 > 0:
            words += f", maintenance target {p.ec_target_p2:.2f} mS/cm"
        zones[f"zone {zone}"] = words + (", vegetative" if c._veg(room, zone) else ", generative")
    facts["zones"] = zones
    st = stage_info(c, room, now)
    if st:
        facts["stage"] = f"flower day {st['day']} of about {st['days']}: {st['name']}, steering {st['steering']}"
    return facts


def feed_task(c, room, now):
    """The Feed task's pass for the room (brain/feed.py): in a room whose feed EC sensor is mapped, asked once a grow-day
    an hour after lights-on with the kill switch on; a firm proposal is a CS-711 card for a person. Never a write."""
    task = getattr(c.jev, "feed", None)
    if task is None or not room.feed_ec_sensor:
        return
    ans = task.answer(room.slug)
    if ans is not None:
        v = jev_feed.verdict(ans)
        label = jev_feed.proposal(v)
        note = (v.notes or [None])[0] if v is not None else None
        journal = getattr(c.jev, "journal", None)
        if journal is not None:
            journal.add({"t": datetime.now().isoformat(timespec="seconds"), "room": room.slug, "zone": None,
                         "judge": "feed", "title": "Feed", "kind": "decision",
                         "verdict": "no answer" if v is None else str(v.label), "p": None if v is None else v.prob,
                         "agreed": None if v is None else v.agreed,
                         "action": "CS-711: a proposal for a person" if label else "no proposal",
                         "result": "advised", "reason": "the feed is never changed by the brain", "why": note or ""})
        if label:
            c._jev_alert(room, None, "feed", {
                "code": "CS-711", "title": "the AI assistant proposes a feed change",
                "message": " ".join(filter(None, (jev_feed.WORDS[label], note, "The controller changed nothing. A "
                                                  "person decides if the feed changes, and makes the change.")))})
    day = c._grow_day_start(room, now).isoformat()
    since_on = (24.0 - c._hours_to(now, room.lights_on_hour)) % 24.0
    if (task.due(room.slug, day) and c._lights_on(room, now) and since_on >= jev_feed.AFTER_H
            and c._on(room.enable_flag, False) and c._no_touch_until(room, now) is None
            and room_health(c, room, now)[0] == "ok"):  # stale readings ask nothing (SF-26)
        task.ask(room.slug, day, feed_facts(c, room, now), now)


def _reports(brain):
    """Each room's report record, read from /data once; a missing or damaged file is no report yet."""
    if "_reports" not in brain.__dict__:
        try:
            with open(brain.report_path, encoding="utf-8") as fh:
                saved = json.load(fh)
            brain._reports = {k: v for k, v in saved.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError, TypeError):
            brain._reports = {}
    return brain._reports


def _save_reports(brain):
    try:
        tmp = brain.report_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(brain._reports, fh)
        os.replace(tmp, brain.report_path)
    except OSError:
        pass  # the report is still published; a restart may ask for it again


def report_evidence(c, room, now, day):
    """The grow-day that just ended, as the report task's evidence: each zone's counters (they reset at the next
    lights-on), its siblings' words and the room's decisions since lights-on began the grow-day."""
    zones = []
    for zone in room.zones:
        st = room.state[zone]
        plants = c._zone_num(room, zone, "plant_count", 0)
        z = {"zone": zone, "phase_now": st.get("phase"), "shots": st.get("shots"),
             "water_l": round(st.get("daily_vol") or 0.0, 3), "peak_vwc": st.get("peak"),
             "pore_ec_settled": st.get("ec_settled"), "vwc_at_lights_off": (st.get("night") or {}).get("off_vwc")}
        if plants and plants >= 1:
            z["water_per_plant_l"] = round((st.get("daily_vol") or 0.0) / plants, 3)
        z.update({k: v for k, v in room.__dict__.get("_jev_sib", {}).get(zone, {}).items() if k.endswith("_words")})
        zones.append(z)
    start = (datetime.fromisoformat(day) + timedelta(hours=room.lights_on_hour)).isoformat(timespec="seconds")
    journal = getattr(c.jev, "journal", None)
    decisions = [{k: e.get(k) for k in ("t", "zone", "judge", "verdict", "action", "result")}
                 for e in (journal.recent(room.slug, 100) if journal is not None else []) if str(e.get("t")) >= start]
    return {"grow_day": day, "local_time": f"{now:%H:%M}", "zones": zones, "decisions": decisions[::-1][-40:],
            "_brain": {"room": room.slug, "zone": "room", "judge": "report",
                       "asked": now.isoformat(timespec="minutes"), "stage": stage_info(c, room, now)}}


def report_task(c, room, now, ha_set):
    """The room's daily grower report (haiku-brain-design section 5, ADVISES): asked once a grow-day, REPORT_AFTER_H
    after lights-off so the setpoints judge has had its window, and only when the budget lets a new ask start
    (Asker.submit). The answer is published on its own sensor and kept in /data, so a restart neither asks again nor
    loses it; the last report stays up until the next one comes back."""
    brain = c.jev
    if not getattr(brain, "report", False):
        return
    reports = _reports(brain)
    rec = reports.setdefault(room.slug, {})
    key = f"report:{room.slug}"
    ans = brain.asker.result(key)
    got = (ans.answers or {}).get("report") if ans is not None else None
    if got and rec.get("asked_at") is not None and ans.at >= rec["asked_at"] and (
            (rec.get("report") or {}).get("grow_day") != rec.get("grow_day")):
        rec["report"] = {**got, "grow_day": rec.get("grow_day"), "generated_at": now.isoformat(timespec="seconds"),
                         "cost_usd": (ans.usage or {}).get("cost_usd")}
        _save_reports(brain)
    day = c._grow_day_start(room, now).isoformat()
    since_off = (now.hour + now.minute / 60.0 - room.lights_off_hour) % 24.0
    if (rec.get("grow_day") != day and not c._lights_on(room, now) and since_off >= REPORT_AFTER_H
            and not brain.asker.pending(key) and c._on(room.enable_flag, False)
            and c._no_touch_until(room, now) is None and room_health(c, room, now)[0] == "ok"):
        asked_at = brain.asker.clock()
        if brain.asker.submit(key, report_evidence(c, room, now, day), REPORT_QUESTION):
            rec.update(grow_day=day, asked_at=asked_at)
            _save_reports(brain)
    r = rec.get("report")
    if r:
        ha_set(f"sensor.crop_steering_{room.prefix}brain_report", r.get("headline") or "no report",
               {"grow_day": r.get("grow_day"), "zones": r.get("zones"), "watch": r.get("watch"),
                "generated_at": r.get("generated_at"), "cost_usd": r.get("cost_usd"), "friendly_name": "Daily report",
                "engine": PRODUCT})


def publish_rules(c, room, now, ha_set):
    """With no brain built, the brain panel still says why rules run (every BrainStatus rules case), and each zone's
    sensor says rules: a state written over REST replaces every attribute, so nothing from an earlier brain shows.
    The decision log is left as it is (its entries are history). CS-712 once when the options name the removed route."""
    status = getattr(c, "brain_status", None) or start_failed()
    ha_set(f"sensor.crop_steering_{room.prefix}jev", "rules", {
        "provider": "rules", "state": status.state, "state_words": status.words, "key_set": status.key_set,
        "model": None, "mode": None, "fallback_since": status.since, "deprecated_route": status.deprecated_route,
        "notice": status.notice, "judges_acting": [], "stage": None, "plan": room.__dict__.get("_plan_panel"),
        **powers_published(c, room, now), "friendly_name": FRIENDLY, "engine": PRODUCT})
    for zone in room.zones:
        ha_set(f"sensor.crop_steering_{room.prefix}zone_{zone}_jev", "rules",
               {"judges": {}, "strict": [], "provider": "rules", "friendly_name": f"Zone {zone} AI assistant",

                "engine": PRODUCT})
    if status.notice == MOVED:
        route_card(c, room)


def lights_on(c, room, now):
    """A room's lights came on: the Claude brain's budget window may start again (Meter.lights_on), and the
    Setpoints judge's levers come back for this room when the brain can act now (hand_back runs on each zone's
    next pass)."""
    brain = c.jev
    meter = getattr(brain.asker, "meter", None)
    if meter is not None:
        meter.lights_on(now.timestamp())
    if (owns_setpoints(c) or _judge(brain, "targets") is not None) and can_act(c):
        brain.__dict__.setdefault("levers_held", {})[room.slug] = True


def _asked_at(question):
    """When the question was asked, as an aware time, or None."""
    try:
        at = datetime.fromisoformat(str(question.get("at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else at.astimezone()


def why_facts(gates, zone=None):
    """The plain words a rules answer can give from the controller's gates (Controller._why_gates): a kill switch
    that is not on, each hold that is on or cannot be read, and the hold the zone asked about met. "" when none."""
    if not gates:
        return ""
    out = []
    ks = gates.get("kill_switch") or {}
    if ks.get("state") in ("off", "unreadable"):
        out.append(f"The kill switch of this room ({ks.get('name')}) is "
                   + ("off" if ks["state"] == "off" else "unreadable") + ", so no zone is watered.")
    for h in gates.get("holds_on") or []:
        out.append(f"The hold {h.get('name')} " + ("is on" if h.get("state") == "on" else "cannot be read")
                   + ", which stops every shot.")
    try:
        z = int(zone)
    except (TypeError, ValueError):
        z = None
    block = ((gates.get("zones") or {}).get(z) or {}).get("block")
    if block:
        out.append(f"Zone {z} is held: {block}.")
    return " ".join(out)


def _stalls_words(c, room, now):
    """Each zone whose ramp ended stalled this grow-day, in words (Controller._record_phase), or "none"."""
    out = {}
    for z in room.zones:
        s = c._p1_stall_today(room, room.state[z], now)
        if s:
            out[z] = (f"P1 ended stalled at {s['at']:.1f}%: the ramp shots did not raise moisture, so the zone "
                      f"re-waters at {s['rewater']:g}% until the next lights-on")
    return out or "none"


def why_state(c, room, question, now, gates=None):
    """The evidence for one why question: the grower's words (sent as operator text), the room's decision record,
    each zone's phase and today's stage, what stops the room being watered (gates: the kill switch, the holds that
    are on, each zone's hold this pass), with the "_brain" key the Claude route needs."""
    journal = getattr(c.jev, "journal", None)
    keep = ("t", "zone", "judge", "title", "kind", "verdict", "p", "agreed", "action", "result", "reason", "why")
    decisions = [{k: e[k] for k in keep if e.get(k) is not None}
                 for e in (journal.recent(room.slug, 15) if journal is not None else [])]
    return {"question": question["question"], "zone_asked_about": question.get("zone") or "the whole room",
            "decisions": decisions or "no decisions recorded yet", "local_time": f"{now:%H:%M}",
            "phases": {z: room.state[z].get("phase") for z in room.zones}, "stage_today": stage_info(c, room, now),
            "ramps_stalled_today": _stalls_words(c, room, now),
            **({"kill_switch": gates["kill_switch"], "holds_on": gates["holds_on"] or "none",
                "zones": gates["zones"]} if gates else {}),
            "_brain": {"room": room.slug, "zone": "room", "judge": "why", "asked": now.isoformat(timespec="minutes"),
                       "siblings": room.__dict__.get("_jev_sib") or {},
                       "interlocks": "a question, not a decision: nothing is changed by the answer",
                       "data_quality": "the decision record as the controller keeps it"}}


def why_task(c, room, now, ha_get, ha_set, gates=None):
    """Ask why (haiku-brain-design section 5): each question the integration keeps for this room
    (sensor..._brain_questions) is asked of the brain once, at most WHY_PER_DAY a day, and answered on
    sensor..._brain_answers (the last WHY_KEEP, by the question's id). Under any brain but Claude Haiku, a question
    the brain cannot ask, and one it could not answer, are answered with why not; under rules the answer also says
    what stops the room being watered (why_facts), when something does. `gates` is the controller's
    Controller._why_gates for this pass, called only when a question needs it. Never changes a setting."""
    brain = getattr(c, "jev", None)
    book = c.__dict__.setdefault("_why", {}).setdefault(room.slug, {"answers": None, "day": None, "asked": 0,
                                                                      "sent": set()})
    out_id = f"sensor.crop_steering_{room.prefix}brain_answers"
    if book["answers"] is None:  # first pass: what was published before a restart stays answered
        old = ha_get(out_id)[1].get("answers")
        old = old if isinstance(old, list) else []
        book["answers"] = [a for a in old if isinstance(a, dict) and isinstance(a.get("id"), str)][-WHY_KEEP:]
    if book["day"] != now.date().isoformat():
        book.update(day=now.date().isoformat(), asked=0)
    asked = ha_get(f"sensor.crop_steering_{room.prefix}brain_questions")[1].get("questions")
    done, pending = {a["id"] for a in book["answers"]}, []
    on = brain is not None and getattr(brain, "why", False)

    def answer(q, words, cannot, grounded=()):
        book["answers"] = (book["answers"] + [{
            "id": q["id"], "question": q["question"], "zone": q.get("zone"), "asked_at": q.get("at"),
            "answered_at": now.isoformat(timespec="seconds"), "answer": words, "grounded_in": list(grounded),
            "cannot_answer": bool(cannot)}])[-WHY_KEEP:]
        book["sent"].discard(q["id"])

    for q in asked if isinstance(asked, list) else []:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str) or q["id"] in done:
            continue
        q = {**q, "question": str(q.get("question") or "")[:300]}
        if not on:
            status = getattr(brain, "status", None) if brain is not None else getattr(c, "brain_status", None)
            facts = why_facts(gates() if gates is not None else None, q.get("zone"))
            answer(q, "Only the Claude Haiku brain answers questions. This room: "
                   + getattr(status, "words", "Rules.") + (" " + facts if facts else ""), not facts,
                   ("kill_switch", "holds_on", "zones") if facts else ())
            continue
        key = f"why:{room.slug}:{q['id']}"
        if q["id"] not in book["sent"]:
            at = _asked_at(q)
            if at is None or (now.astimezone() - at).total_seconds() > WHY_FRESH_H * 3600:
                answer(q, "Not asked: the question waited too long for the controller.", True)
                continue
            if book["asked"] >= WHY_PER_DAY:
                answer(q, f"Not asked: this room has asked its {WHY_PER_DAY} questions today.", True)
                continue
            meter = getattr(brain.asker, "meter", None)
            if not brain.asker.submit(key, why_state(c, room, q, now, gates() if gates is not None else None),
                                      {"why": dict(WHY)}):
                answer(q, "Not asked: " + _STATE_WORDS.get(meter.state() if meter is not None else None,
                                                           "the AI assistant cannot ask now."), True)
                continue
            book["asked"] += 1
            book["sent"].add(q["id"])
        got = brain.asker.result(key)
        if got is not None:
            w = got.answers.get("why") or {}
            answer(q, w.get("answer") or "No answer.", w.get("cannot_answer", True), w.get("grounded_in") or ())
        elif brain.asker.pending(key):
            pending.append(q["id"])
        else:
            answer(q, "The AI assistant could not answer: " + str(brain.asker.stats.get("last_error") or "no answer"),
                   True)
    ha_set(out_id, "asking" if pending else ("answered" if book["answers"] else "none"),
           {"answers": book["answers"], "pending": pending, "asked_today": book["asked"],
            "daily_limit": WHY_PER_DAY, "friendly_name": "AI assistant answers", "engine": PRODUCT})


# ---------- the AI assistant's powers (docs/AI_ASSISTANT.md, "Powers") ----------
def room_powers(c, room, now=None):
    """{power: on} for the room, read from its switches once a pass (a missing switch is the power's default);
    `now` None reads this pass's, once read."""
    held = room.__dict__.get("_ai_powers")
    if held and (held[0] == now or now is None):
        return held[1]
    on = getattr(c, "_on", None)
    out = jev_powers.read(on, room.prefix) if on is not None else dict(jev_powers.DEFAULTS)
    room._ai_powers = (now, out)
    return out


def powers_published(c, room, now):
    """The brain sensor's `powers` (each power, on or off, and its default) and `powers_active` (those on)."""
    rows = jev_powers.published(room_powers(c, room, now))
    return {"powers": rows, "powers_active": [r["key"] for r in rows if r["on"]]}


def _ai(c, room, zone):
    """The powers' memory for a zone, in jev_setpoints.json beside the Setpoints judge's (brain.setpoint_memory)."""
    rec = c.jev.setpoints.zone(room.slug, zone)
    ai = rec.get("ai") if isinstance(rec.get("ai"), dict) else None
    if ai is None:
        ai = rec["ai"] = {}
    for k, v in (("written", {}), ("pending", []), ("days", []), ("changes", [])):
        if not isinstance(ai.get(k), type(v)):
            ai[k] = v
    return ai


def _owned(c, room, judge, power):
    brain = getattr(c, "jev", None)
    if brain is None or _judge(brain, judge) is None:
        return False
    return jev_powers.allowed(room_powers(c, room), power) and bool(_acting_latch(c, room))


def targets_owned(c, room):
    """True when the AI assistant sets the room's ladder itself: the targets judge runs, the room's
    set_targets_from_achievable power is on and the brain can act. The Auto setpoints learner and the follower of the
    highest readings then write none of field capacity, the P1 target and the re-water threshold
    (controller._auto_tick); with the power off, they do as before."""
    return _owned(c, room, "targets", "set_targets_from_achievable")


def shots_owned(c, room):
    """True when the AI assistant sets the room's shot sizes itself (tune_shot_sizes on, the brain able to act)."""
    return _owned(c, room, "shotsize", "tune_shot_sizes")


def _day_start(c, room, now):
    day0 = c._grow_day_start(room, now)
    day0 = day0 if isinstance(day0, datetime) else datetime.combine(day0, datetime.min.time())
    return day0 + timedelta(hours=room.lights_on_hour)


def _for_day(items, day):
    return next((e for e in reversed(items or []) if isinstance(e, dict) and str(e.get("date")) == day), None)


def record_day(c, room, zone, p, now):
    """Once a grow-day, at night: the zone's scorecard for the grow-day that is ending, against each phase's goal.
    P0: the dryback at the ramp's start (zone_history's morning record) against the dryback target; P1: the highest
    trusted reading against the peak target, and the ramp's shots; P2: the settled pore EC against the stage's band;
    P3: rescue shots the night before; uniformity: water per plant against the room's typical zone. A day is trusted
    only with a trusted peak (no blind or set-aside probe, no CS-310 day) and a ramp that responded."""
    ai = _ai(c, room, zone)
    day = c._grow_day_start(room, now).isoformat()
    if ai.get("day_recorded") == day:
        return
    st = room.state[zone]
    learn = st.get("learn") if isinstance(st.get("learn"), dict) else {}
    counted = (st.get("fc_follow") or {}).get("peak")
    why = ("moisture rose from below (CS-310)" if counted is None else "no trusted reading" if not counted
           else "the probe was set aside" if ai.get("distrusted_day") == day
           else "the ramp did not respond as a ramp should" if learn.get("outcome") == "suspect" else None)
    night = _for_day(st.get("night_hist"), day) or {}
    plateau = _for_day(st.get("plateau_hist"), day) or {}
    target_db = float(getattr(p, "dryback_target", 0.0) or 0.0)
    actual_db = night.get("dryback_pct")
    top = round(float(counted), 2) if counted else plateau.get("value")
    stage = stage_info(c, room, now) if getattr(c, "jev", None) is not None else None
    band = (stage or {}).get("pore_ec") or None
    ec = st.get("ec_settled")
    sib = room.__dict__.get("_jev_sib") or {}
    lpp = sorted(v["litres_per_plant"] for v in sib.values() if v.get("litres_per_plant"))
    mine = (sib.get(zone) or {}).get("litres_per_plant")
    typical = lpp[len(lpp) // 2] if lpp else None
    ratio = round(mine / typical, 2) if mine and typical else None
    entry = {
        "day": day, "trusted": why is None, "why": why,
        "p0": {"target": target_db, "actual": None if actual_db is None else round(float(actual_db), 1),
               "hit": None if actual_db is None or not target_db
               else abs(float(actual_db) - target_db) <= max(2.0, 0.2 * target_db)},
        "p1": {"target": round(float(p.p1_target), 2), "top": top, "shots": plateau.get("shots"),
               "hit": None if not top else float(top) >= float(p.p1_target) - 0.5},
        "p2": {"ec": None if ec is None else round(float(ec), 2), "band": list(band) if band else None,
               "hit": None if ec is None or not band else band[0] <= float(ec) <= band[1]},
        "p3": {"rescues": night.get("night_shots"),
               "hit": None if night.get("night_shots") is None else not night["night_shots"]},
        "uniformity": {"ratio": ratio, "hit": None if ratio is None else 0.85 <= ratio <= 1.15},
    }
    ai["days"] = ([d for d in ai["days"] if isinstance(d, dict) and d.get("day") != day] + [entry])[-DAYS_KEEP:]
    ai["day_recorded"] = day
    c.jev.setpoints.save()


def _view(c, room, zone, p, now, judge, keys, power):
    """What a values judge may set on the zone tonight: each setting's value now and its own range, the scorecard,
    the AI assistant's earlier changes, the grow plan's intent and whether its power is on."""
    brain = getattr(c, "jev", None)
    if brain is None or _judge(brain, judge) is None or getattr(brain, "setpoints", None) is None:
        return None
    record_day(c, room, zone, p, now)
    ai = _ai(c, room, zone)
    current = {k: v for k in keys if (v := _zone_number(c, room, zone, k)) is not None}
    if not current:
        return None  # no per-zone numbers on this install: room-level values are the operator's, never ours
    day = c._grow_day_start(room, now).isoformat()
    plan = ("a grow plan owns this room's targets: follow the plan's values for today's stage"
            if getattr(room, "strategy_required", False) else None)
    return {"current": current, "limits": {k: c._number_range(room, zone, k) for k in current},
            "days": list(ai["days"]), "changes": [x for x in ai["changes"] if x.get("judge") == judge],
            "plan": plan, "power": jev_powers.allowed(room_powers(c, room, now), power),
            "changed_today": ai.get(f"changed_{judge}") == day, "day": day}


def targets_view(c, room, zone, p, now):
    """What the targets judge may set tonight (ZoneContext.targets): the ladder, the rescue floor and the dryback
    target of the zone's steering mode."""
    db = targets_judge.VEG_DB if c._veg(room, zone) else targets_judge.GEN_DB
    view = _view(c, room, zone, p, now, "targets", (*targets_judge.LADDER_KEYS, db), "set_targets_from_achievable")
    if view is not None and hasattr(c, "_step_limit_all") and c._step_limit_all(room):  # the room's daily limit holds the AI too (opt-in)
        view["daily_limit"] = c._step_limit(room)
    return view


def shots_view(c, room, zone, p, now):
    """What the shot size judge may set tonight (ZoneContext.shots), with the zone's learned shot response."""
    view = _view(c, room, zone, p, now, "shotsize", (targets_judge.P1S, targets_judge.P2S), "tune_shot_sizes")
    if view is not None:
        learn = room.state[zone].get("learn") if isinstance(room.state[zone].get("learn"), dict) else {}
        view["gain"] = learn.get("gain")
    return view


def _power_note(c, room, zone, judge, verdict, action, result, reason):
    journal = getattr(c.jev, "journal", None)
    if journal is not None:
        journal.add({"t": datetime.now().isoformat(timespec="seconds"), "room": room.slug, "zone": zone,
                     "judge": judge, "title": {"targets": "Targets", "shotsize": "Shot size"}.get(judge, judge),
                     "kind": "decision", "verdict": verdict, "p": None, "agreed": None, "action": action[:80],
                     "result": result, "reason": reason[:120]})


def _tell_setpoints(c, room, zone, suffix, old, value, now):
    """A power moved one of the Setpoints judge's two numbers: its range moves with it (as with field capacity), so
    the move is not taken for an edit by hand."""
    mem = getattr(c.jev, "setpoints", None)
    if mem is None or not owns_setpoints(c) or suffix not in (SHOT, THRESHOLD):
        return
    rec = mem.zone(room.slug, zone)
    if suffix in rec["home"]:
        rec["home"][suffix] = round(float(rec["home"][suffix]) + value - old, 2)
    _written(mem, rec, suffix, old, value, now)


def apply_values(c, room, zone, d, ctx, now):
    """Write the values the AI assistant set, as given: each clamped only to its own range (the clamp is logged), the
    ladder written from the top when the peak rises and from the bottom when it falls, so Home Assistant's own order
    check takes each write; a write it refuses is tried again after the others, and one it refuses still is logged.
    Each write names its reason and the expected result in the room's setpoint change log, is read back, and the
    change is announced once."""
    v = d.value
    judge = d.judge
    view = (ctx.targets if judge == "targets" else ctx.shots) or {}
    ai = _ai(c, room, zone)
    by = f"{AI_BY} ({'targets' if judge == 'targets' else 'shot sizes'})"
    ledger_id = _ledger_id(c, room, zone, d, now)
    plan, clamped, stepped = {}, {}, {}
    for k, asked in v["values"].items():
        lo, hi = c._number_range(room, zone, k)
        val = round(min(hi, max(lo, float(asked))), 2)
        if abs(val - float(asked)) > 1e-9:
            clamped[k] = float(asked)
        cur = float(view["current"][k])
        left = c._step_allowance(room, zone, k, now) if judge == "targets" and hasattr(c, "_step_allowance") else None
        if left is not None and abs(val - cur) > left + 1e-9:  # the room's daily limit holds the AI too (opt-in)
            stepped[k], val = val, phase_options.clamp_step(cur, val, left)
        plan[k] = (cur, val)
    if stepped:
        # The ladder still holds after clamping (rescue + 3 <= threshold < peak target <= field capacity), else none
        # of the ladder moves tonight.
        tj = targets_judge
        after = {k: plan[k][1] if k in plan else _zone_number(c, room, zone, k) for k in tj.LADDER_KEYS}
        if None not in after.values() and not (after[tj.RESCUE] + 3.0 <= after[tj.THR] < after[tj.P1]
                                                <= after[tj.FC]):
            for k in (tj.FC, tj.P1, tj.THR):
                if k in plan:
                    plan[k] = (plan[k][0], plan[k][0])
        for k, asked in stepped.items():
            _power_note(c, room, zone, judge, "clamped by the daily limit",
                        f"{k.replace('_', ' ')} {asked:g} -> {plan[k][1]:g}", "acted",
                        "the room's Max setpoint move per day holds the AI assistant too")
    rising = plan.get(targets_judge.P1, (0.0, 0.0))[1] >= plan.get(targets_judge.P1, (0.0, 0.0))[0]
    ladder = [k for k in targets_judge.LADDER_KEYS if k in plan]
    order = (ladder if rising else ladder[::-1]) + [k for k in plan if k not in ladder]
    todo, wrote = [k for k in order if abs(plan[k][1] - plan[k][0]) >= 0.005], []
    while todo:
        left = []
        for k in todo:
            old, new = plan[k]
            reason = (v["reasons"].get(k) or "") + (f" (asked {clamped[k]:g}, clamped to its range)" if k in clamped
                                                    else "")
            if k in stepped:
                reason = (reason + " " if reason else "") + "(clamped by the daily limit)"
            if c._auto_write(room, zone, k, old, new, {}, now, by=by, reason=reason or None,
                             expected=v.get("expected") or None, **_named(ledger_id)):
                if judge == "targets" and hasattr(c, "_step_count"):
                    c._step_count(room, zone, k, old, new, now)
                wrote.append(k)
                ai["written"][k] = new
                ai["pending"] = [w for w in ai["pending"] if w.get("suffix") != k] + [
                    _pending(k, old, new, by, now, ledger_id)]
                _tell_setpoints(c, room, zone, k, old, new, now)
            else:
                left.append(k)
        if len(left) == len(todo):
            for k in left:
                _power_note(c, room, zone, judge, "write refused", f"{k.replace('_', ' ')} {plan[k][0]:g} -> "
                            f"{plan[k][1]:g}", "failed", "Home Assistant did not take it")
            break
        todo = left
    for k, asked in clamped.items():
        _power_note(c, room, zone, judge, "clamped", f"{k.replace('_', ' ')} {asked:g} -> {plan[k][1]:g}", "acted",
                    "outside the setting's own range: written at its edge")
    if wrote:
        ai["changes"] = (ai["changes"] + [{
            "judge": judge, "day": view.get("day"), "at": now.isoformat(timespec="seconds"),
            "values": {k: list(plan[k]) for k in wrote}, "reasons": {k: v["reasons"].get(k) for k in wrote},
            "expected": v.get("expected"), "confidence": v.get("confidence"), "clamped": clamped}])[-CHANGES_KEEP:]
        ai[f"changed_{judge}"] = view.get("day")
        words = ", ".join(f"{k.replace('_', ' ')} {plan[k][0]:g} -> {plan[k][1]:g}" for k in wrote)
        c._notify_event("jev_setpoint", room, zone, words,
                        f"The AI assistant set this itself, with the power the owner gave it. Expected: "
                        f"{v.get('expected') or 'not said'}.")
    c.jev.setpoints.save()


def ai_readback(c, room, zone, now):
    """Read back every write a power made (SF-25): landed, it is done; still the old value at its time, it is sent
    again with a doubling wait, RETRIES times, then recorded as failed."""
    mem = getattr(getattr(c, "jev", None), "setpoints", None)
    if mem is None:
        return
    ai = _ai(c, room, zone)
    if not ai["pending"]:
        return
    keep = []
    for w in ai["pending"]:
        cur = _zone_number(c, room, zone, w["suffix"])
        frm, to = float(w["from"]), float(w["to"])
        if cur is not None and abs(cur - frm) > 0.005:
            continue  # landed, or set by hand since: nothing left to send
        if now < datetime.fromisoformat(w["next"]):
            keep.append(w)
            continue
        if w["tries"] < RETRIES:
            w["tries"] += 1
            w["next"] = (now + timedelta(seconds=PENDING_S * 2 ** w["tries"])).isoformat(timespec="seconds")
            c._auto_write(room, zone, w["suffix"], frm, to, {}, now, by=w["by"], **_named(w.get("ledger_id")))
            keep.append(w)
            continue
        ai["written"][w["suffix"]] = frm
        judge = "shotsize" if w["suffix"] in (targets_judge.P1S, targets_judge.P2S) else "targets"
        _power_note(c, room, zone, judge, "write failed", f"{w['suffix'].replace('_', ' ')} {frm:g} -> {to:g}",
                    "failed", f"Home Assistant still shows {frm:g} after {w['tries'] + 1} tries")
    ai["pending"] = keep
    mem.save()
