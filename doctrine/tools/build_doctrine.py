#!/usr/bin/env python3
"""Build the crop-steering doctrine pack.

One source of truth, doctrine.rules.json, plus the code itself:
  1. validate the rules JSON (ids, evidence classes, source references, the decision catalogue, symptom levers);
  2. audit that every JEV doctrine.py rule is merged or explicitly dropped;
  3. REGENERATE the engine rules from crop_steering_engine/core.py: constants are read from the module and
     every prose statement is backed by a probe that calls decide() and must pass; controller, integration and
     brain-guard statements are checked against their source (the envelope's admit() is called), so the
     brain's doctrine cannot contradict the code;
  4. render the markdown views;
  5. compile the prompt blocks: compiled/sections/* (block A, the same on every install), compiled/arcs/* and
     compiled/substrates/* (block B, chosen per install), and compiled/manifest.json;
  6. strip lint: the public denylist (denylist.public.txt) always, the private one (site-specific, from a CI
     secret) unless explicitly skipped, which only a fork pull request may do;
  7. keep the controller's copy of compiled/ byte-identical when that directory exists.

Usage:  python tools/build_doctrine.py [--repo ROOT] [--core PATH] [--controller PATH] [--jev PATH] [--brain DIR]
            [--bridge PATH] [--auto PATH] [--numbers PATH] [--controller-copy DIR] [--private-denylist PATH]
            [--private-skip REASON] [--check]
--check rebuilds in memory and fails if any committed output (or the controller copy) differs (CI drift guard).
With no path flags the build reads the repository it sits in (doctrine/ at the repository root); --repo or the
per-file flags point it at other code.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DENYLIST = ROOT / "denylist.public.txt"
EVIDENCE = ("research", "vendor", "grower-practice", "product-rule")
SUBSTRATES = ("generic", "rockwool", "coco")
TOPIC_TITLES = {
    "concepts": "Core concepts", "decisions": "Brain decisions (what each acting answer does, and when to give it)",
    "ramp": "P1 ramp", "dryback": "Dryback", "maintenance": "P2 maintenance",
    "ec": "Pore EC", "probe": "Probes and hardware evidence", "stage": "Growth stage", "ripening": "Ripening",
    "closed_loop": "Closed-loop discipline", "substrate": "Substrate", "feed": "Feed and source water",
    "climate": "Climate", "contract": "Brain contract (observer -> planner -> guarded controller -> executor -> audit)",
}
SECTIONS = ("01-role-and-hard-rules.md", "02-engine.md", "03-decisions.md", "04-symptoms.md", "05-doctrine.md")
JUDGE_FILE = {"alerts": "triage.py"}  # the alert-urgency question lives beside the judges, not in judges/
SYMPTOM_CLASS = ("Symptom entries carry no evidence class of their own: they are product-rule, drawn from the "
                 "decision rules and engine facts they cite.")


# ---------------------------------------------------------------- paths
def resolve_paths(a):
    repo = Path(a.repo) if a.repo else ROOT.parent
    if not (repo / "crop-steering-engine").is_dir():
        sys.exit(f"{repo} is not a repository root (no crop-steering-engine/); pass --repo")
    ctrls = sorted(repo.glob("addons/*/*/controller.py"))
    if len(ctrls) != 1:
        sys.exit(f"expected exactly one addons/*/*/controller.py under {repo}, found {len(ctrls)}")
    pkg = ctrls[0].parent
    p = {"core": repo / "crop-steering-engine/src/crop_steering_engine/core.py", "controller": ctrls[0],
         "jev": pkg / "jev" / "doctrine.py", "brain": pkg / "jev", "bridge": pkg / "jev_bridge.py",
         "auto": pkg / "auto_setpoints.py", "numbers": repo / "custom_components/crop_steering/number.py",
         "controller_copy": pkg / "doctrine"}
    for k in p:
        v = getattr(a, k)
        if v:
            p[k] = Path(v)
    return p


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- strip lint
def load_public_denylist(path):
    if not path.exists():
        sys.exit(f"public denylist {path.name} is missing; it ships with the pack and always runs")
    pats = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] not in ("all", "cited"):
            sys.exit(f"{path.name}:{n}: expected SCOPE<TAB>REGEX<TAB>WHY with SCOPE all or cited")
        re.compile(parts[1])
        pats.append(tuple(parts))
    return pats


def load_private_denylist(a):
    """The site-specific list, from a CI secret written to a file. Missing fails loud unless --private-skip."""
    if a.private_skip:
        msg = f"SKIPPED private denylist: {a.private_skip}"
        print(msg, file=sys.stderr)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"- {msg}\n")
        return [], []
    path = Path(a.private_denylist) if a.private_denylist else None
    if path is None or not path.exists() or not path.read_text(encoding="utf-8").strip():
        return [], ["private denylist secret missing: pass --private-denylist FILE (CI writes the secret to it), "
                    "or --private-skip REASON on a fork pull request"]
    return [("all", pat, why) for pat, why in json.loads(path.read_text(encoding="utf-8"))], []


def lint(name, text, patterns, scopes):
    hits = []
    for scope, pat, why in patterns:
        if scope in scopes:
            hits += [f"{name}: {why}: {m.group(0)!r}" for m in re.finditer(pat, text)]
    return hits


# ---------------------------------------------------------------- 1. validate
def validate(doc):
    errs, ids = [], set()
    src = doc["sources"]

    def check_sources(owner, refs):
        errs.extend(f"{owner}: unknown source {s}" for s in refs if s not in src)

    for r in doc["hard_rules"] + doc["rules"]:
        if r["id"] in ids:
            errs.append(f"duplicate id {r['id']}")
        ids.add(r["id"])
        if r["evidence"] not in EVIDENCE:
            errs.append(f"{r['id']}: bad evidence class {r['evidence']}")
        check_sources(r["id"], r["sources"])
        errs.extend(f"{r['id']}: bad substrate {s}" for s in r.get("substrates", []) if s not in SUBSTRATES)
        if r.get("topic") and r["topic"] not in TOPIC_TITLES:
            errs.append(f"{r['id']}: unknown topic {r['topic']}")
    for k, arc in doc["stage_arcs"].items():
        if isinstance(arc, dict):
            check_sources(f"arc {k}", arc.get("sources", []))
    for k, sub in doc["substrates"].items():
        if isinstance(sub, dict):
            check_sources(f"substrate {k}", sub.get("sources", []))
    for v in src.values():
        if v["evidence"] not in EVIDENCE:
            errs.append(f"source {v['title']}: bad evidence class")
    answers = {}
    for d in doc["decisions"]:
        if d["rule"] not in ids:
            errs.append(f"decision {d['judge']}: unknown rule {d['rule']}")
        answers[d["judge"]] = set(d["acting"])  # an ACTS lever must name an answer that acts
    for s in doc["symptom_map"]:
        for lv in s["levers"]:
            if lv["mode"] not in ("ACTS", "ADVISES"):
                errs.append(f"{s['id']}: bad lever mode {lv['mode']}")
            if lv["mode"] == "ACTS":
                # an acting lever must name the decision that offers it and answers that decision has
                judge, _, keys = lv.get("via", "").partition(": ")
                bad = [k for k in keys.split(", ") if k not in answers.get(judge, ())]
                if judge not in answers or bad:
                    errs.append(f"{s['id']} {lv['param']}: ACTS lever needs via '<judge>: <answer>' from the "
                                f"decision catalogue (got {lv.get('via')!r})")
    return errs


# ---------------------------------------------------------------- 2. JEV coverage audit
def jev_refs(jev_path):
    jev = load_module(jev_path, "jev_doctrine_snapshot")
    # JEV keeps its vendor-handbook rules in one second *_RULES table and appends them to RULES per topic.
    extra = [n for n, v in vars(jev).items() if n.endswith("_RULES") and n != "RULES" and isinstance(v, dict)]
    if len(extra) != 1:
        sys.exit(f"expected one vendor rules table beside RULES in {jev_path}, found {extra}")
    vendor = getattr(jev, extra[0])
    refs = []
    for topic, rules in jev.RULES.items():
        n_vendor = len(vendor.get(topic, []))
        refs += [f"jev:{topic}#{i}" for i in range(len(rules) - n_vendor)]
        refs += [f"jev-vendor:{topic}#{i}" for i in range(n_vendor)]
    return refs


def coverage(doc, refs):
    used = set()
    for r in doc["hard_rules"] + doc["rules"]:
        used.update(r.get("merged_from", []))
    for arc in doc["stage_arcs"].values():
        if isinstance(arc, dict):
            used.update(arc.get("merged_from", []))
    used.update(d["ref"] for d in doc.get("dropped", []))
    return [r for r in refs if r not in used], sorted(u for u in used if u not in refs)


# ---------------------------------------------------------------- 3. engine, controller, integration, brain facts
def engine_facts(doc, paths):
    core = load_module(paths["core"], "core_snapshot")
    ZP, ZS, decide = core.ZoneParams, core.ZoneSnapshot, core.decide

    base_p = dict(p1_target=60, p2_threshold=45, p2_shot_size=5, p1_initial=2, p1_incr=0.5, p1_max_shots=12,
                  p1_time_between_min=15, dryback_target=20, p0_max_wait_min=45, ec_target_p0=4, ec_target_p1=5,
                  ec_target_p2=6, p3_emergency_floor=40, p3_emergency_shot=2, max_daily_volume=150,
                  field_capacity=70, max_ec=9, stacking_on=False)
    base_s = dict(vwc=55, ec=5.0, phase="P2", peak_vwc=60, dryback_pct=8, dryback_rate=1.0, shot_count=0,
                  phase_minutes=30, minutes_since_shot=60, daily_vol=10, ec_smooth=5.0, lights_on=True,
                  lights_just_on=False, hours_to_lights_on=14, hours_to_lights_off=8, uptime_min=600, feed_ec=3.0)

    def run(s=None, p=None):
        return decide(ZS(**{**base_s, **(s or {})}), ZP(**{**base_p, **(p or {})}))

    def phase(p=None, **s):
        return run(s, p)[0]

    def same_for_any_target(s):
        outs = {tuple(map(str, run(s, {"dryback_target": dt}))) for dt in (5, 20, 40, 60)}
        return len(outs) == 1

    nums = Path(paths["numbers"]).read_text(encoding="utf-8")
    # number.py takes its entity defaults from its copy of the one defaults table: "key": (entity default, fallback).
    table = (Path(paths["numbers"]).parent / "generated" / "defaults.py").read_text(encoding="utf-8")

    def num_default(key):
        m = re.search(rf'"{key}":\s*\(([0-9.]+),', table)
        return float(m.group(1)) if m else None

    veg_dt, gen_dt, p0_wait = (num_default("vegetative_dryback_target"), num_default("generative_dryback_target"),
                               num_default("p0_maximum_wait_time"))

    probes = [
        ("PH-1", "Lights-off forces any phase other than P3 to P3; nothing strands mid-cycle overnight.",
         all(phase(phase=ph, lights_on=False) == "P3" for ph in ("P0", "P1", "P2"))),
        ("PH-2", "P3 returns to P0 on the lights-on edge, or on the first tick of a new grow-day if the edge was missed.",
         phase(phase="P3", lights_just_on=True) == "P0" and phase(phase="P3", new_grow_day=True) == "P0"),
        ("PH-3", "A zone still in P1 or P2 when a new grow-day begins resets to P0 with fresh counters and budget.",
         phase(phase="P2", new_grow_day=True) == "P0" and phase(phase="P1", new_grow_day=True) == "P0"),
        ("PH-4", "P0 ends at the first of: VWC at or below the P2 threshold (bypass), relative dryback at or above dryback_target, or p0_max_wait_min elapsed.",
         phase(phase="P0", vwc=45) == "P1" and phase(phase="P0", vwc=50, dryback_pct=20) == "P1"
         and phase(phase="P0", vwc=50, phase_minutes=45) == "P1" and phase(phase="P0", vwc=50) == "P0"),
        ("PH-5", f"P1 ends at p1_max_shots, or once the zone has read at or above min(p1_target, field_capacity), at least p1_min_shots have landed, one extra shot has fired, the shot interval has passed and that shot raised the day's peak by less than {core.P1_RISE_PTS:g} points.",
         phase(phase="P1", vwc=50, shot_count=12) == "P2"
         and phase(phase="P1", vwc=60, peak_vwc=61, p1_reached=True, p1_extra_shots=1, p1_peak_before_shot=60.8, shot_count=4) == "P2"
         and phase(phase="P1", vwc=60, peak_vwc=62, p1_reached=True, p1_extra_shots=1, p1_peak_before_shot=60.8, shot_count=4) == "P1"),
        ("PH-6", "P1 has no time-based exit and is not held open by high pore EC: a gate-blocked ramp waits in P1 and resumes.",
         phase(phase="P1", vwc=50, phase_minutes=10_000) == "P1"
         and phase(phase="P1", vwc=60, ec=8.5, peak_vwc=61, p1_reached=True, p1_extra_shots=1, p1_peak_before_shot=60.9, shot_count=4) == "P2"),
        ("PH-7", "Predictive P3: in the last 3 h before lights-off (after 10 min uptime, VWC at or above the rescue floor), P2 hands over early when the points still needed to reach dryback_target from the day's peak, at the measured drying rate (0.1 points/h if unknown), would take at least the hours left until lights-on (and no more than 12 h).",
         phase(phase="P2", vwc=58, peak_vwc=60, hours_to_lights_off=2, hours_to_lights_on=10, dryback_rate=1.0) == "P3"
         and phase(phase="P2", vwc=50, peak_vwc=60, hours_to_lights_off=2, hours_to_lights_on=10, dryback_rate=1.0) == "P2"),
        ("PH-8", "dryback_target changes nothing else: in P1, in P2 more than 3 h before lights-off and in P3, the same readings give the same phase and the same shot whatever its value. It never sets the overnight dryback.",
         all(same_for_any_target(s) for s in (
             {"phase": "P1", "vwc": 50}, {"phase": "P2", "vwc": 44}, {"phase": "P2", "vwc": 55, "ec": 7.5},
             {"phase": "P3", "lights_on": False, "vwc": 39}, {"phase": "P3", "lights_on": False, "vwc": 50},
             {"phase": "P2", "vwc": 30, "peak_vwc": 60, "dryback_pct": 50}))),
        ("PH-9", "With a dark period of 12 h or more the predictive P3 never passes, whatever dryback_target says: P2 waters until lights-off.",
         all(phase({"dryback_target": dt}, phase="P2", vwc=v, peak_vwc=60, dryback_rate=r, hours_to_lights_off=off,
                   hours_to_lights_on=12 + off) == "P2"
             for dt in (2, 5, 10, 20, 40, 60) for v in (45, 52, 58) for r in (0.1, 0.5, 1, 3) for off in (0.25, 1, 2, 3))),
        ("PH-10", "A larger dryback_target can switch the predictive P3 off: once reaching it would take more than 12 h at the measured rate, P2 keeps watering.",
         phase({"dryback_target": 20}, phase="P2", vwc=58, peak_vwc=60, hours_to_lights_off=2, hours_to_lights_on=10) == "P3"
         and phase({"dryback_target": 40}, phase="P2", vwc=58, peak_vwc=60, hours_to_lights_off=2, hours_to_lights_on=10) == "P2"),
        ("IR-1", "Priority 1, anti-lockout: pore EC at or above max_ec flushes in any phase when the feed is dilutive (feed EC below pore EC), the zone is draining and VWC is under field_capacity - 2. Size = p2_shot_size x (1.5 + 0.3 x min(EC excess, 3)). It is cap-exempt.",
         run({"ec": 10.0, "vwc": 50})[2] and run({"ec": 10.0, "vwc": 50})[4].kind == "flush_high_ec"
         and abs(run({"ec": 10.0, "vwc": 50})[3] - round(5 * (1.5 + 1.0 * 0.3), 1)) < 1e-6 and core.CAP_EXEMPT["flush_high_ec"]),
        ("IR-2", "At max_ec with a non-dilutive feed or a backed-up (not draining) zone, the engine BLOCKS rather than adds salt or water; the block self-clears. On a tick that blocks, or holds (IR-3), nothing else fires: not the P3 emergency, the watchdog or the minimum floor.",
         run({"ec": 10.0, "feed_ec": 11.0})[4].kind == "block_high_ec" and run({"ec": 10.0, "backed_up": True})[4].kind == "block_high_ec"
         and run({"ec": 10.0, "feed_ec": 11.0, "phase": "P3", "lights_on": False, "vwc": 30})[4].kind == "block_high_ec"
         and run({"ec": 10.0, "feed_ec": 11.0, "vwc": 44, "minutes_since_shot": 200})[4].kind == "block_high_ec"
         and run({"ec": 10.0, "vwc": 30, "minutes_since_shot": 5, "phase": "P3", "lights_on": False})[4].kind == "hold_high_ec"),
        ("IR-3", f"Anti-short-cycle: an EC correction waits p2_min_interval_min after the last shot (at least {core.EC_SETTLE_MIN:g} min when judged on a settled reading); at max_ec inside that gap the zone HOLDS so the last flush can drain.",
         run({"ec": 10.0, "vwc": 50, "minutes_since_shot": 5})[4].kind == "hold_high_ec"
         and run({"ec": 10.0, "ec_settled": 10.0, "vwc": 50, "minutes_since_shot": 30})[4].kind == "hold_high_ec"),
        ("IR-4", "P0 fires nothing routine: only an EC flush (fixed 10% shot) when pore EC is over 2.5x the P0 target, the feed is dilutive and the interval has passed.",
         not run({"phase": "P0", "vwc": 50, "ec": 5.0})[2] and run({"phase": "P0", "vwc": 50, "ec": 8.5}, {"ec_target_p0": 3})[4].kind == "p0_ec_flush"),
        ("IR-5", "P1 ramp: every p1_time_between_min a shot of p1_initial + p1_incr x shots so far (capped at p1_initial + p1_incr x p1_max_shots, which in practice never binds because P1 ends at p1_max_shots), scaled by ec_adjust against the P1 EC target. Ramp shots, and the extra shot at the target, are cap-exempt.",
         run({"phase": "P1", "vwc": 50, "ec": 5.0, "shot_count": 2})[3] == 3.0
         and run({"phase": "P1", "vwc": 50, "ec": 5.0, "shot_count": 2, "minutes_since_shot": 10})[2] is False
         and core.CAP_EXEMPT["p1_ramp"] and core.CAP_EXEMPT["p1_extra"]),
        ("IR-6", "P2, first match wins: rescue flush at pore EC >= max_ec - 1 (dilutive, under field_capacity - 2, interval ok; 1.5x shot, cap-exempt); dilute at EC > 1.2x the P2 target (dilutive, interval ok; 1.5x shot, inside the budget); top-up when VWC < the P2 threshold (shot scaled by ec_adjust).",
         run({"ec": 8.2, "vwc": 50})[4].kind == "p2_rescue" and run({"ec": 7.5, "vwc": 50})[4].kind == "p2_dilute"
         and run({"ec": 6.0, "vwc": 44})[4].kind == "p2_topup" and not run({"ec": 6.0, "vwc": 50})[2]),
        ("IR-7", "P3 is emergency-only: a p3_emergency_shot when VWC falls below p3_emergency_floor (the rescue floor). Cap-exempt.",
         run({"phase": "P3", "lights_on": False, "vwc": 39})[4].kind == "p3_emergency" and not run({"phase": "P3", "lights_on": False, "vwc": 41})[2]),
        ("IR-8", "Watchdog: with lights on and outside P0, a zone with no water for watchdog_hours that sits under its P2 threshold gets a p2_shot_size shot, even over the daily budget. A probe reading at or above the threshold silences it.",
         run({"vwc": 44, "minutes_since_shot": 200, "daily_vol": 500}, {"max_daily_volume": 150})[4].kind == "watchdog"
         and not run({"vwc": 50, "minutes_since_shot": 600, "daily_vol": 0})[2]),
        ("IR-9", "Minimum daily floor: outside P0 with lights on, a zone behind a straight line from nothing at lights-on to min_daily_volume at min_floor_finish_h before lights-off gets a p2_shot_size shot regardless of VWC, gated only by the drown ceiling and the p2_min_interval_min gap. It never exceeds the budget by construction. With min_daily_volume 0 it never fires.",
         run({"vwc": 55, "daily_vol": 0, "hours_since_lights_on": 6, "hours_to_lights_off": 6}, {"min_daily_volume": 20})[4].kind == "min_daily"
         and not run({"vwc": 91, "daily_vol": 0, "hours_since_lights_on": 6, "hours_to_lights_off": 6}, {"min_daily_volume": 20})[2]
         and not run({"vwc": 55, "daily_vol": 0, "hours_since_lights_on": 6, "hours_to_lights_off": 6})[2]),
        ("IR-10", "Daily budget: once daily_vol reaches max_daily_volume, non-exempt shots (top-up, dilute, P0 flush, floor) are blocked; flush_high_ec, p1_ramp, p1_extra, p2_rescue, p3_emergency and watchdog are exempt.",
         run({"vwc": 44, "daily_vol": 150, "minutes_since_shot": 20})[4].kind == "block_daily_cap"),
        ("IR-11", "While steering is held (a grow plan held, stale or missing) only the water-safety shots run: the P3 emergency, the watchdog and the minimum floor. Phases still move.",
         not run({"vwc": 44, "minutes_since_shot": 20, "steering_held": True})[2]
         and run({"vwc": 44, "minutes_since_shot": 200, "steering_held": True})[4].kind == "watchdog"),
        ("IR-12", "When a settled pore-EC reading is supplied, every EC rule uses it instead of the raw reading.",
         run({"ec": 8.5, "ec_settled": 6.0, "vwc": 50})[4].kind != "p2_rescue"),
        ("IR-13", "With pore EC unknown the zone waters by VWC alone; EC corrections do not fire and the reason says salt protection is unverified.",
         run({"ec": None, "ec_smooth": None, "vwc": 44})[4].kind == "p2_topup" and "EC unknown" in run({"ec": None, "vwc": 44})[4]),
    ]
    if None not in (veg_dt, gen_dt, p0_wait):
        lo = min(veg_dt, gen_dt)
        probes.append((
            "PH-11", f"At the integration's default dryback_target ({gen_dt:g} % generative, {veg_dt:g} % vegetative) a morning drop of a few percent never ends P0: it waits for p0_max_wait_min (default {p0_wait:g} min), the bypass or a brain start.",
            phase({"dryback_target": lo, "p0_max_wait_min": p0_wait}, phase="P0", vwc=55, peak_vwc=58, dryback_pct=5,
                  phase_minutes=p0_wait - 1) == "P0"
            and phase({"dryback_target": lo, "p0_max_wait_min": p0_wait}, phase="P0", vwc=55, peak_vwc=58,
                      dryback_pct=5, phase_minutes=p0_wait) == "P1"))
    else:
        probes.append(("PH-11", "integration dryback defaults not found", False))

    def ratio_table():
        t = 10.0
        return [(r, core.ec_adjust(1.0, r * t, t)) for r in (0.4, 0.6, 0.9, 1.1, 1.3, 1.6)]

    adj = ratio_table()
    ec_adjust_rule = ("ec_adjust multiplies a shot by pore EC / target: "
                      + "; ".join(f"ratio {r:g} -> x{m:g}" for r, m in adj)
                      + " (thresholds: >1.5 x2.0, >1.2 x1.5, >1.0 x1.2, <0.8 x0.7, <0.5 x0.5, else x1).")
    ec_adjust_ok = [m for _, m in adj] == [0.5, 0.7, 1.0, 1.2, 1.5, 2.0]

    ctrl = Path(paths["controller"]).read_text(encoding="utf-8")
    auto = Path(paths["auto"]).read_text(encoding="utf-8")
    bridge = Path(paths["bridge"]).read_text(encoding="utf-8")
    # The Auto Setpoints learner: the controller's _follow_fc and the learner's wanted(), checked in their own source.
    follow = re.search(r"    def _follow_fc\(.*?(?=\n    def )", ctrl, re.S)
    follow = follow.group(0) if follow else ""
    shift = re.search(r"^FC_SHIFT_MIN = ([0-9.]+)$", ctrl, re.M)
    shift = float(shift.group(1)) if shift else None
    blind_follow = re.search(r"for zone, p in blind:\n(?:.*\n){0,4}?.*self\._follow_fc\(room, zone, p, now\)", ctrl)
    ctrl_checks = [
        ("CT-1", "The P2 threshold the engine sees is p2_vwc_threshold plus the controller's EC offset (offset dropped while EC is unknown), clamped between rescue floor + 3 and min(p1_target, field_capacity) - 1.",
         "max(efloor + 3.0, min(min(p1t, fc) - 1.0, p2_thr))" in ctrl),
        ("CT-2", "EC steer (only with EC stacking on, in P2, every 30 min, on the settled EC): step the offset toward +1 when EC > 110% of the P2 target, toward -1 when < 90%, else toward 0, within +/-20% of the base threshold. An optional PID replaces the step.",
         "ec_smooth < ec_target_p2 * 0.90" in ctrl and "ec_smooth > ec_target_p2 * 1.10" in ctrl and "0.20 * base" in ctrl and "p.stacking_on" in ctrl),
        ("CT-3", "At lights-on (P0) the day's counters, peak, EC offset and PID integral reset.",
         'st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, snap.vwc' in ctrl and 'st["ec_offset"], st["last_ec_steer"] = 0.0, None' in ctrl),
        ("CT-4", "Relative dryback the engine compares: (peak - vwc) / peak x 100. The peak restarts at the lights-on reading when the zone enters P0 and then follows the highest reading of the grow-day, so in P0 the figure is the drop since lights-on and later in the day it is the drop from the day's peak.",
         '(st["peak"] - vwc) / st["peak"] * 100' in ctrl and 'if vwc > st["peak"]:' in ctrl
         and 'st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, snap.vwc' in ctrl),
        ("CT-5", "Dead or set-aside probe: after a 15 min grace the zone copies the healthiest sibling's shot (closest p1_target) or, with no sibling, waters every blind_fallback_min (default 90) within its own budget; VWC-driven phase changes wait, time-driven ones still happen.",
         "BLIND_GRACE_MIN = 15" in ctrl and 'o.get("blind_fallback_min", 90)' in ctrl),
        ("CT-6", "Source-water gate, two halves (feed EC, feed pH), each only when its feed sensor is configured and its band is set (feed sensors default to empty): a feed outside its band holds the zone; a dead feed probe holds after feed_grace_min (default 30). External holds apply only when configured (none by default). Offline pump or valve switches hold too.",
         'o.get("feed_grace_min", 30)' in ctrl and "holding (fail-closed)" in ctrl
         and "if room.feed_ec_sensor:" in ctrl and "if room.feed_ph_sensor:" in ctrl and "if lo > 0 or hi > 0:" in ctrl),
        ("CT-7", "SIGTERM closes whatever is in flight, saves state and exits.", "signal.SIGTERM" in ctrl),
        ("CT-8", f"With no live feed EC reading (no feed EC sensor, or its last good reading older than feed_grace_min) the controller hands decide() an assumed feed EC of {core.ZoneSnapshot.__dataclass_fields__['feed_ec'].default:.1f} mS/cm, not a measurement, for every dilutive test.",
         "feed_ec=(feed_ec if feed_ec is not None else 3.0)" in ctrl and core.ZoneSnapshot.__dataclass_fields__["feed_ec"].default == 3.0),
        ("CT-9", "The minimum daily floor is read from a per-zone helper (min_daily_ml_per_plant, made by hand; the integration creates no such setting) times the zone's plant count, defaulting to 0: a fresh install runs with the floor off.",
         re.search(r'zone_\{zone\}_min_daily_ml_per_plant",\s*0\.0,\s*\)\s*\*\s*self\._zone_num\(room, zone, "plant_count", (?:0|FALLBACK\["plant_count"\])\)', ctrl) is not None
         and "min_daily" not in nums),
        ("CT-10", "A zone whose moisture rises with no water going in (a backed-up table) gets the floor set to 0 and no EC correction.",
         "dataclasses.replace(p, min_daily_volume=0.0)" in ctrl and "dataclasses.replace(snap, backed_up=True)" in ctrl),
        ("CT-11", "dryback_target is read from vegetative_dryback_target or generative_dryback_target by the zone's steering mode; the integration's p0_dryback_drop_percent setting is not read by the controller.",
         "_dryback_target\"" in ctrl and "{'vegetative' if veg else 'generative'}_dryback_target" in ctrl
         and "p0_dryback_drop" not in ctrl and '"p0_dryback_drop_percent"' in nums),
        ("CT-12", f"Auto Setpoints is an opt-in room switch (the controller reads a missing one as off) that lets the controller rewrite a zone's own per-zone targets, never while a grow plan owns the room. With it on, every loop: field capacity is set to the zone's highest reading of this grow-day or the one before, and the P1 target to the highest reading of the grow-day before, with no step limit (only the engine's bounds and each number's own min and max); when field capacity moves by {shift if shift is not None else 0:g} point or more in one write, the P2 re-water threshold and the rescue floor (the P3 emergency threshold) move by the same points, down as well as up. It runs for a zone whose probe is dead or set aside too. Nothing is written until a lights-on has kept the day before's peak, nor anything that would leave the ladder inverted (rescue floor + 3 <= threshold < P1 target <= field capacity). A hand edit to field capacity or the P1 target does not stick while the switch is on; one to the threshold or the rescue floor is shifted along with field capacity rather than replaced (CT-13 says when the learner rewrites them itself).",
         shift == 1.0 and 'if not self._on(f"' in follow and '{room.prefix}auto_setpoints", False):' in follow
         and 'getattr(room, "strategy_required", False)' in follow
         and 'return max(st.get("peak") or 0.0, prev), prev' in ctrl and "if prev is None or prev <= 0.0:" in ctrl
         and 'fc = bounded("field_capacity", seen)' in follow and 'target = bounded("p1_target_vwc", min(yday, fc))' in follow
         and "if abs(delta) >= FC_SHIFT_MIN:" in follow and 'new_thr = bounded("p2_vwc_threshold", thr + delta)' in follow
         and 'rescue = bounded("p3_emergency_vwc_threshold", p.p3_emergency_floor + delta)' in follow
         and "if rescue + 3.0 <= new_thr < target <= fc:" in follow and blind_follow is not None
         and 'if ha_get(entity)[0] in (None, "unknown", "unavailable", ""):' in ctrl),
        ("CT-13", "With Auto Setpoints on and field capacity unmoved on that loop, the controller's learner also writes the re-water threshold when no brain Setpoints judge runs (with one running, the P2 shot size and threshold are the judge's, apart from the field-capacity shift in CT-12), and lowers the rescue floor to the threshold - 3 whenever it would otherwise sit less than 3 points under the threshold.",
         'want = auto_setpoints.wanted(learn, current, snap.vwc, st["phase"], ctx, others=judged)' in ctrl
         and "if self._follow_fc(room, zone, p, now):" in ctrl and "writes = enabled and not planned" in ctrl
         and 'if "p2_vwc_threshold" in others:' in auto
         and 'if current["p3_emergency_vwc_threshold"] + 3.0 > thr:' in auto
         and 'want["p3_emergency_vwc_threshold"] = round(thr - 3.0, 1)' in auto
         and "return (SHOT, THRESHOLD) if owns_setpoints(c) else ()" in bridge),
        ("CT-14", "So with Auto Setpoints on, the safety label (zone_safety_status) reads over_saturated whenever the zone matches or beats its highest reading of this grow-day and the one before (each new high), and approaching_saturation within 5 points of it: under the switch those labels say where the zone sits against its own peak, not that it is over-watered.",
         core.zone_safety_status(60.0, 5.0, 60.0, 9.0) == "over_saturated"
         and core.zone_safety_status(55.5, 5.0, 60.0, 9.0) == "approaching_saturation"
         and core.zone_safety_status(54.9, 5.0, 60.0, 9.0) == "safe"
         and 'fc = bounded("field_capacity", seen)' in follow),
    ]

    brain_checks = brain_facts(doc, paths, core, base_p, base_s, ctrl)

    failures = ([pid for pid, _, ok in probes if not ok] + [cid for cid, _, ok in ctrl_checks if not ok]
                + [bid for bid, _, ok in brain_checks if not ok])
    if not ec_adjust_ok:
        failures.append("ec_adjust")
    # No raw source hashes in here: --check compares these facts, so only a change to what the pack states (a value
    # read from the code, or a sentence that stops being true) can make the generated files stale. main() reports
    # the source hashes in the log instead.
    facts = {
        "constants": {"EC_SETTLE_MIN": core.EC_SETTLE_MIN, "P1_RISE_PTS": core.P1_RISE_PTS,
                      "p2_min_interval_min_default": core.ZoneParams.__dataclass_fields__["p2_min_interval_min"].default,
                      "watchdog_hours_default": core.ZoneParams.__dataclass_fields__["watchdog_hours"].default,
                      "drown_ceiling_default": core.ZoneParams.__dataclass_fields__["drown_ceiling"].default,
                      "min_floor_finish_h_default": core.ZoneParams.__dataclass_fields__["min_floor_finish_h"].default},
        "cap_exempt": dict(core.CAP_EXEMPT),
        "param_bounds": {k: list(v) for k, v in core._PARAM_BOUNDS.items()},
        "ec_adjust": ec_adjust_rule,
        "decide_rules": [{"id": pid, "text": t, "verified": ok} for pid, t, ok in probes],
        "controller_rules": [{"id": cid, "text": t, "verified": ok} for cid, t, ok in ctrl_checks],
        "brain_rules": [{"id": bid, "text": t, "verified": ok} for bid, t, ok in brain_checks],
        "helpers": [
            "cross_zone_outliers: a zone under 40% of the cross-zone median daily volume (median >= 5 L, 2+ zones) is flagged as under-drinking.",
            "detect_vmax: P1 ceiling = highest reading once 2 consecutive shots add <= 0.6 points (>= 4 readings); advisory only, it never changes a decision.",
            "pick_sibling: a blind zone copies the healthy zone with the nearest p1_target (ties: lowest zone).",
            "zone_safety_status: over_saturated at VWC >= field_capacity; ec_limit_exceeded at EC >= max_ec; approaching_* within 5 VWC points / 1 mS/cm; ec_unknown when EC is missing. With Auto Setpoints on, field capacity is the zone's own peak (CT-14).",
            "validate_params: out-of-range settings are clamped to the bounds below with a CS-401 alert; p1_min_shots <= p1_max_shots; min_daily_volume <= max_daily_volume.",
            "zone_status_label (the grower's words on the status tile): waiting "
            + ", ".join(f"{ph} '{core.zone_status_label(ph, False, None, False)}'" for ph in core.PHASES)
            + "; while a shot fires " + ", ".join(f"{ph} '{core.zone_status_label(ph, True, None, False)}'" for ph in core.PHASES)
            + f"; a blind zone '{core.zone_status_label('P2', False, None, True)}'.",
        ],
    }
    return facts, failures


def brain_facts(doc, paths, core, base_p, base_s, ctrl):
    """The brain's guard and levers, checked against the code: admit() is called, the rest is read from source."""
    brain = Path(paths["brain"])
    env = load_module(brain / "envelope.py", "envelope_snapshot")
    bridge = Path(paths["bridge"]).read_text(encoding="utf-8")
    judge_src = {d["judge"]: (brain / JUDGE_FILE.get(d["judge"], f"judges/{d['judge']}.py")).read_text(encoding="utf-8")
                 for d in doc["decisions"]}
    now = datetime(2026, 1, 1, 12, 0)

    def ctx(phase, s=None, p=None, **kw):
        c = dict(now=now, phase=phase, lights_on=True, steering="generative", stage=None, hours_to_off=2.0,
                 setpoints=None, snap=core.ZoneSnapshot(**{**base_s, "phase": phase, **(s or {})}),
                 params=core.ZoneParams(**{**base_p, **(p or {})}))
        c.update(kw)
        return SimpleNamespace(**c)

    def ok(kind, value, c, **k):
        return env.admit(env.Directive("t", kind, value, "why", now + timedelta(hours=1)), c, **k)[0]

    # base_p: dryback_target 20 (half = 10), p0_max_wait_min 45 (quarter = 11.25), p1 ceiling 60, floor 40
    dawn = (not ok("advance", "P1", ctx("P0", {"dryback_pct": 8, "phase_minutes": 5}))
            and ok("advance", "P1", ctx("P0", {"dryback_pct": 10, "phase_minutes": 5}))
            and ok("advance", "P1", ctx("P0", {"dryback_pct": 2, "phase_minutes": 12}))
            and not ok("advance", "P1", ctx("P0", {"dryback_pct": 10}, lights_on=False))
            and not ok("advance", "P1", ctx("P0", snap=None))
            and not ok("advance", "P2", ctx("P0", {"dryback_pct": 10})))
    ramp = (not ok("advance", "P2", ctx("P1", {"shot_count": 0, "vwc": 59}))
            and not ok("advance", "P2", ctx("P1", {"shot_count": 2, "vwc": 56}))
            and ok("advance", "P2", ctx("P1", {"shot_count": 1, "vwc": 57}))
            and not ok("advance", "P2", ctx("P1", {"shot_count": 2, "vwc": 57}, {"p1_min_shots": 3})))
    dusk = (ok("advance", "P3", ctx("P2", {"vwc": 50}))
            and not ok("advance", "P3", ctx("P2", {"vwc": 50}, steering="vegetative"))
            and not ok("advance", "P3", ctx("P2", {"vwc": 50}, hours_to_off=3.5))
            and not ok("advance", "P3", ctx("P2", {"vwc": 42.5})) and ok("advance", "P3", ctx("P2", {"vwc": 43})))
    distrust = (not ok("distrust", "stuck", ctx("P2"), confirmed=1, evidence_ok=True)
                and not ok("distrust", "stuck", ctx("P2"), confirmed=2, evidence_ok=False)
                and ok("distrust", "stuck", ctx("P2"), confirmed=2, evidence_ok=True))
    ec_mode = (all(ok("ec_mode", m, ctx("P2")) for m in ("steer", "hold", "decay"))
               and not ok("ec_mode", "hold", ctx("P1")) and not ok("ec_mode", "off", ctx("P2")))
    sp = {"enabled": True, "current": {"p2_shot_size": 5.0}, "bands": {"p2_shot_size": (4.0, 6.0)}}

    def notch(to, **over):
        return ok("setpoint", {"suffix": "p2_shot_size", "from": 5.0, "to": to}, ctx("P3", setpoints={**sp, **over}))

    setpoint = (notch(5.5) and notch(4.5) and not notch(6.0) and not notch(5.5, changed_today=True)
                and not notch(5.5, enabled=False) and not notch(5.5, frozen="2026-01-02T12:00")
                and not notch(5.5, bands={"p2_shot_size": (4.0, 5.2)}))
    advice = ok("alert", {}, ctx("P2")) and ok("push", True, ctx("P2")) and not ok("water", 1, ctx("P2"))
    sp_src = judge_src["setpoints"]
    salt_modes = {"salts_accumulating": "steer", "salt_front_passing": "steer", "feed_changed": "hold",
                  "in_band": "hold", "below_band_vegetative": "hold", "probe_suspect": "decay",
                  "target_unreachable": "decay"}

    def keys_in_code(d):
        src = judge_src[d["judge"]]
        if d["judge"] == "probe":
            return '"tracking": [' in src and "noul(" in src and all(f'"{k}":' in src for k in d["detail"])
        return all(f'"{k}":' in src for k in d["acting"] + d["other"])

    return [
        ("BR-1", "The brain's answers can cause only these directives: advance (a phase forward), distrust (a probe set aside), ec_mode (steer, hold or decay) and setpoint (one notch); alerts and pushes are admitted because they never move water, and anything else is refused.",
         advice and "judge_levers" in bridge),
        ("BR-2", "advance moves only to the next phase, with the lights on and a usable probe. P0 -> P1 needs the drop since lights-on at half of dryback_target or a quarter of p0_max_wait_min gone. P1 -> P2 needs max(1, p1_min_shots) ramp shots and VWC within 3 points of min(p1_target, field_capacity). P2 -> P3 needs at most 3 h to lights-off, a zone not steered vegetative, and VWC at least 3 points above the rescue floor.",
         dawn and ramp and dusk),
        ("BR-3", "distrust needs two agreeing answers in a row plus code's own confirmation; a set-aside zone takes the blind path (CT-5).",
         distrust and 'distrusted[zone] = jev_dirs["distrust"].why' in ctrl and "snap = None" in ctrl),
        ("BR-4", "ec_mode is admitted only in P2. The controller applies it only while EC stacking is on: steer runs the base step or PID, hold keeps the offset, decay halves the offset (and the PID integral) every 30 min.",
         ec_mode and 'ec_mode = getattr(jev_dirs.get("ec_mode"), "value", "steer")' in ctrl
         and 'st["ec_offset"] = round(float(st.get("ec_offset", 0.0)) * 0.5, 2)' in ctrl
         and "(now - les).total_seconds() >= 1800" in ctrl
         and all(f'"{k}": "{m}"' in judge_src["salt"] for k, m in salt_modes.items())),
        ("BR-5", "setpoint moves one 0.5 notch, at most once per zone per grow-day, only with the room's Auto Setpoints switch on (so the learner of CT-12 and CT-13 is always running when a notch is possible) and no grow plan owning the room, never while paused, inside a band around the last value of that number the brain did not write: p2_shot_size within 1 and never under 3; p2_vwc_threshold from 2 under to 1 over, at least the rescue floor + 4 and at most min(p1_target, field_capacity) - 2. Any value the brain did not write, a hand edit or a learner move alike, becomes the band's new centre (the evidence calls it 'your value'). These two numbers are the only ones the brain writes (judge_levers).",
         setpoint and 'SHOT, THRESHOLD = "p2_shot_size", "p2_vwc_threshold"' in sp_src and "STEP = 0.5" in sp_src
         and "SHOT_FLOOR = 3.0" in sp_src and "return max(SHOT_FLOOR, home - 1.0), home + 1.0" in sp_src
         and "lo = max(home - 2.0, params.p3_emergency_floor + 4.0)" in sp_src
         and "hi = min(home + 1.0, min(params.p1_target, params.field_capacity) - 2.0)" in sp_src
         and "return (SHOT, THRESHOLD) if owns_setpoints(c) else ()" in bridge
         and 'enabled = (c._on(f"' in bridge and '{room.prefix}auto_setpoints", False)' in bridge
         and 'and not getattr(room, "strategy_required", False))\n    return {' in bridge
         and 'if not sp.get("enabled")' in sp_src
         and 'expected = rec["written"].get(suffix, rec["home"].get(suffix))' in bridge
         and 'rec["home"][suffix] = v' in bridge and 'f"{label} {cur:g}{unit}{edge}; your value {home:g}' in sp_src),
        ("BR-6", "A P3 rescue shot within 30 h of a setpoint notch puts back the value from before the notch, if nothing has moved that number since, and pauses the brain's notches on that zone for 48 h; the Auto Setpoints learner is not paused.",
         "REVERT_WINDOW_H = 30" in bridge and "PAUSE_H = 48" in bridge and 's.kind == "p3_emergency"' in bridge
         and 'if cur is not None and abs(cur - float(last["to"])) < 1e-6:' in bridge
         and 'float(last["to"]), float(last["from"])' in bridge and "frozen_until" not in ctrl),
        ("BR-7", "Every answer key the decision catalogue names exists in the code's questions.",
         all(keys_in_code(d) for d in doc["decisions"])),
    ]


# ---------------------------------------------------------------- 4. renderers
def hdr(doc, title, intro=""):
    return (f"<!-- GENERATED by tools/build_doctrine.py from doctrine.rules.json. Do not edit by hand. -->\n"
            f"# {title}\n\nDoctrine {doc['doctrine_version']}. {intro}\n\n")


def src_tag(r):
    return f"`{r['evidence']}` · " + ", ".join(r["sources"])


def md_hard(doc):
    out = hdr(doc, "Role and hard rules", "These go first in the cached system prompt.")
    out += "## Role\n\n" + doc["role"] + "\n\n## Hard rules\n\n"
    out += "".join(f"- **{r['id']}** {r['text']} ({src_tag(r)})\n" for r in doc["hard_rules"])
    out += "\n## Diagnose before steering\n\n| Step | Check | Answer |\n|---|---|---|\n"
    out += "".join(f"| {d['step']}. {d['name']} | {d['check']} | {d['answer']} |\n" for d in doc["diagnose_order"])
    return out


def fact_lines(facts, key):
    return "".join(f"- **{r['id']}** {r['text']}\n" for r in facts[key])


def md_engine(doc, facts):
    out = hdr(doc, "Engine rules (regenerated from decide())",
              "Every statement under 'decide()' is checked by calling the engine during the build, and every "
              "brain-guard statement by calling the envelope's admit(); a statement that stops being true fails the "
              "build. The hashes of the code files checked are printed in the build log, not kept here, so an edit "
              "that changes nothing this file states needs no regeneration.")
    out += ("**Boundary:** the controller runs the engine for every zone each minute, a shot fires only when a "
            "rule is due, and the engine decides alone whenever the brain is "
            "silent or refused. The brain's acting answers only bring a phase forward, choose the EC steer's mode, "
            "set a probe aside, or notch the maintenance shot size or re-water threshold (see the brain's guard).\n\n")
    out += "## decide(), in priority order\n\n" + fact_lines(facts, "decide_rules")
    out += f"\n## Shot scaling\n\n- {facts['ec_adjust']}\n\n## Controller (IO shell) and integration facts\n\n"
    out += fact_lines(facts, "controller_rules")
    out += "\n## The brain's guard (envelope) and levers\n\n" + fact_lines(facts, "brain_rules")
    out += "\n## Helpers\n\n" + "".join(f"- {h}\n" for h in facts["helpers"])
    out += "\n## Cap exemptions (shot kind -> may exceed the daily budget)\n\n"
    out += "| kind | exempt |\n|---|---|\n" + "".join(f"| {k} | {'yes' if v else 'no'} |\n" for k, v in facts["cap_exempt"].items())
    out += "\n## Parameter bounds the engine clamps to\n\n| param | min | max |\n|---|---|---|\n"
    out += "".join(f"| {k} | {lo:g} | {hi:g} |\n" for k, (lo, hi) in facts["param_bounds"].items())
    out += "\n## Constants\n\n" + "".join(f"- {k} = {v:g}\n" for k, v in facts["constants"].items())
    return out


def lever_words(x):
    s = f"{x['mode']} {x['param']} {x.get('direction', '')}".strip()
    return s + (f" (via {x['via']})" if x.get("via") else "")


def decision_rows(doc):
    out = ("| Judge | Question | Asked | Acting answers -> effect | Answers that act on nothing | Code's guard |\n"
           "|---|---|---|---|---|---|\n")
    for d in doc["decisions"]:
        acting = ", ".join(d["acting"]) or "none"
        out += (f"| {d['judge']} | {d['question']} | {d['asked']} | {acting} -> {d['effect']} | "
                f"{', '.join(d['other']) or '-'} | {d['guard']} ({d['rule']}) |\n")
    return out


def md_playbook(doc):
    out = hdr(doc, "Diagnosis playbook", "The decisions the brain is asked, materiality, symptom to lever.")
    out += "## The decisions the brain is asked\n\n" + decision_rows(doc)
    out += "\n## When a signal is worth acting on\n\n| Signal | Material when |\n|---|---|\n"
    out += "".join(f"| {m['signal']} | {m['material_when']} |\n" for m in doc["materiality"])
    out += "\nNot material: hold. Two candidates on the same lever: one decision. Already handled by the engine: hold.\n\n"
    out += ("## Symptom -> lever\n\n`ACTS` = an answer the brain may give, named by its decision and answer key; code "
            "and the envelope do the rest. `ADVISES` = a recommendation for a person. " + SYMPTOM_CLASS + "\n\n")
    for s in doc["symptom_map"]:
        out += f"### {s['id']} {s['symptom']}\n\nRule out first: {s['first']}\n\n"
        for lv in s["levers"]:
            bits = [lv["param"]] + ([lv["direction"]] if lv.get("direction") else []) + ([f"({lv['step']})"] if lv.get("step") else [])
            via = f" via `{lv['via']}`" if lv.get("via") else ""
            out += f"- `{lv['mode']}` {' '.join(bits)}{via}" + (f": {lv['why']}" if lv.get("why") else "") + "\n"
        if s.get("never"):
            out += f"- Never: {s['never']}\n"
        out += "\n"
    out += "## Engine parameter -> integration setting\n\n" + doc["param_map"]["_note"] + "\n\n| engine | setting |\n|---|---|\n"
    out += "".join(f"| {k} | {v} |\n" for k, v in doc["param_map"].items() if not k.startswith("_"))
    return out


def md_rules(doc, evidence=None, title="Doctrine rules", intro="Merged and de-duplicated. Priority 1 = core.", topics=None):
    out = hdr(doc, title, intro)
    for topic, t_title in TOPIC_TITLES.items():
        if topics is not None and topic not in topics:
            continue
        rs = [r for r in doc["rules"] if r["topic"] == topic and (evidence is None or r["evidence"] == evidence)]
        if not rs:
            continue
        out += f"## {t_title}\n\n"
        for r in rs:
            sub = f" [{', '.join(r['substrates'])} only]" if r.get("substrates") else ""
            out += f"- **{r['id']}** (p{r['priority']}){sub} {r['text']} — {src_tag(r)}"
            if r.get("conflict"):
                out += f" *Conflict:* {r['conflict']}"
            if r.get("note"):
                out += f" *Note:* {r['note']}"
            out += "\n"
        out += "\n"
    return out


def fmt(v):
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return f"{v[0]:g}-{v[1]:g}"
    if isinstance(v, dict):
        return "; ".join(f"{k} {fmt(x)}" for k, x in v.items())
    if isinstance(v, list):
        return "; ".join(fmt(x) for x in v)
    return "" if v is None else str(v)


def md_arc(doc, key):
    arc = doc["stage_arcs"][key]
    out = f"### Stage arc `{key}`: {arc['title']} ({', '.join(arc['sources'])})\n\n"
    if arc.get("why_default"):
        out += f"Default because: {arc['why_default']}\n\n"
    cols = ["stage", "flower_days", "steering", "peak", "dryback_points", "dryback_relative_vendor", "pore_ec", "runoff_pct", "move_on_when", "notes"]
    cols = [c for c in cols if any(c in s for s in arc["stages"])]
    out += "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    out += "".join("| " + " | ".join(fmt(s.get(c)) for c in cols) + " |\n" for s in arc["stages"])
    return out + "\n"


def arc_keys(doc):
    return [k for k in doc["stage_arcs"] if not k.startswith("_") and k != "default"]


def md_arcs(doc):
    out = hdr(doc, "Stage arcs", doc["stage_arcs"]["_note"])
    return out + "".join(md_arc(doc, k) for k in arc_keys(doc))


def md_sub(doc, key):
    s = doc["substrates"][key]
    out = f"### Substrate `{key}`: {s['title']} ({', '.join(s['sources'])})\n\n"
    if s.get("basis"):
        out += f"Basis: {s['basis']}\n\n"
    for k, v in s.items():
        if k not in ("title", "sources", "basis", "troubleshooting", "rules", "start_up"):
            out += f"- **{k}**: {fmt(v)}\n"
    for k in ("rules", "start_up"):
        if s.get(k):
            out += f"\n{k.replace('_', ' ').capitalize()}:\n" + "".join(f"- {x}\n" for x in s[k])
    if s.get("troubleshooting"):
        out += "\n| See | Cause | Do |\n|---|---|---|\n"
        out += "".join(f"| {t['see']} | {t['cause']} | {t['do']} |\n" for t in s["troubleshooting"])
    return out + "\n"


def md_subs(doc):
    out = hdr(doc, "Substrate tables", doc["substrates"]["_note"])
    return out + "".join(md_sub(doc, k) for k in SUBSTRATES)


def md_sources(doc):
    out = hdr(doc, "Sources and evidence classes", "Sources marked unpublished (owner notes, design papers, a course "
              "synthesis) cannot be checked by a reader; they are cited so the trail is complete.")
    out += "| class | meaning |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in doc["evidence_classes"].items())
    out += "\n| id | source | class | licence |\n|---|---|---|---|\n"
    for k, v in doc["sources"].items():
        where = v.get("url") or v.get("where")
        out += f"| {k} | {v['title']}{f' ({where})' if where else ''} | {v['evidence']} | {v['licence']} |\n"
    return out


# ---------------------------------------------------------------- 5. compiled prompt blocks
def rule_line(r):
    return f"{r['id']} [{r['evidence']}] {r['text']} ({', '.join(r['sources'])})"


def compile_sections(doc, facts):
    """Block A: the same on every install, in SECTIONS order. Substrate-limited rules go to block B."""
    v = doc["doctrine_version"]
    s1 = [f"# Crop-steering brain: doctrine {v}", "", "## Role", doc["role"], "", "## Hard rules (override everything below)"]
    s1 += [f"{r['id']}. {r['text']}" for r in doc["hard_rules"]]
    s1 += ["", "## Diagnose order"] + [f"{d['step']}. {d['name']}: check {d['check']} -> {d['answer']}" for d in doc["diagnose_order"]]
    s1 += ["", "## Material signals (else hold)"] + [f"- {m['signal']}: {m['material_when']}" for m in doc["materiality"]]
    s2 = ["## What the engine does (decide(); verified against the code)", doc["units_note"]]
    s2 += [f"- {r['text']}" for r in facts["decide_rules"]] + [f"- {facts['ec_adjust']}"]
    s2 += [f"- {r['id']} {r['text']}" for r in facts["controller_rules"]]  # ids: rules cite CT-12 to CT-14
    s2 += ["", "## The brain's guard (envelope) and levers (verified against the code)"]
    s2 += [f"- {r['id']} {r['text']}" for r in facts["brain_rules"]]  # ids: the decision rules cite them
    s2 += [f"- {h}" for h in facts["helpers"]]
    s2 += ["- Engine bounds: " + ", ".join(f"{k} {lo:g}-{hi:g}" for k, (lo, hi) in facts["param_bounds"].items())]
    s3 = ["## The decisions you are asked (acting answers go through the envelope; everything else advises)"]
    # The request lists every question's keys; here only what acts, and how (guards: BR-* in 02-engine).
    for d in doc["decisions"]:
        if d["acting"]:
            rest = " Any other answer acts on nothing." if d["other"] else ""
            s3 += [f"- {d['judge']} / {d['question']}, asked {d['asked']}. Acting: {', '.join(d['acting'])} -> "
                   f"{d['effect']}.{rest} See {d['rule']}."]
    advice = [d for d in doc["decisions"] if not d["acting"]]
    s3 += ["- Advice only, never moves water: " + "; ".join(f"{d['judge']} / {d['question']} ({d['effect']})"
                                                            for d in advice) + "."]
    s3 += ["", f"### {TOPIC_TITLES['decisions']}"] + [rule_line(r) for r in doc["rules"] if r["topic"] == "decisions"]
    s4 = ["## Symptom -> lever (ACTS = an answer you may give, via its decision; ADVISES = say it, a person decides)",
          SYMPTOM_CLASS]
    for s in doc["symptom_map"]:
        lv = "; ".join(lever_words(x) for x in s["levers"])
        s4 += [f"- {s['symptom']}. First rule out: {s['first']} Levers: {lv}." + (f" Never: {s['never']}" if s.get("never") else "")]
    s4 += ["", "## Engine parameter -> setting", doc["param_map"]["_note"]]
    s4 += [f"- {k}: {v}" for k, v in doc["param_map"].items() if not k.startswith("_")]
    s5 = ["## Doctrine (id [evidence] text; sources)",
          "Evidence: research > vendor > grower-practice for agronomy; product-rule always wins on what the software does."]
    for topic, t_title in TOPIC_TITLES.items():
        rs = [r for r in doc["rules"] if r["topic"] == topic and topic != "decisions" and not r.get("substrates")]
        if rs:
            s5 += [f"### {t_title}"] + [rule_line(r) for r in rs]
    return {f"compiled/sections/{name}": "\n".join(body) + "\n" for name, body in zip(SECTIONS, (s1, s2, s3, s4, s5))}


def compile_block_b(doc):
    out = {}
    for k in arc_keys(doc):
        out[f"compiled/arcs/{k}.md"] = "## Stage arc for this install\n" + doc["stage_arcs"]["_note"] + "\n\n" + md_arc(doc, k)
    for k in SUBSTRATES:
        body = "## Substrate table for this install\n" + doc["substrates"]["_note"] + "\n\n" + md_sub(doc, k)
        rs = [r for r in doc["rules"] if k in r.get("substrates", [])]
        if rs:
            body += f"### Doctrine for {k} only\n" + "".join(rule_line(r) + "\n" for r in rs)
        out[f"compiled/substrates/{k}.md"] = body
    return out


def estimate_tokens(text):
    # No tokenizer offline: bracket with two common English heuristics for Claude-family tokenizers.
    return {"chars": len(text), "words": len(text.split()), "tokens_est_low": round(len(text) / 4.0),
            "tokens_est_high": round(len(text) / 3.3)}


def manifest(doc, facts, compiled, jev_count):
    a_files = [f"sections/{n}" for n in SECTIONS]
    block_a = "".join(compiled[f"compiled/{f}"] for f in a_files)
    per_install = {}
    for arc in arc_keys(doc):
        for sub in SUBSTRATES:
            b = compiled[f"compiled/arcs/{arc}.md"] + compiled[f"compiled/substrates/{sub}.md"]
            per_install[f"{arc}+{sub}"] = estimate_tokens(block_a + b)
    return {
        "doctrine_version": doc["doctrine_version"],
        "block_a": a_files,
        "block_b": {"arcs": {k: f"arcs/{k}.md" for k in arc_keys(doc)},
                    "arcs_note": "a preview and drift check: the prompt renders the arc table from the rows the "
                                 "judges use, and a test checks these files' numbers against them",
                    "substrates": {k: f"substrates/{k}.md" for k in SUBSTRATES},
                    "order": "the install's arc file(s), then its substrate file(s), each sorted by id"},
        "defaults": {"stage_arc": doc["stage_arcs"]["default"], "substrate": doc["substrates"]["default"]},
        "files": {k[len("compiled/"):]: {"sha256": hashlib.sha256(v.encode("utf-8")).hexdigest(), **estimate_tokens(v)}
                  for k, v in sorted(compiled.items())},
        "estimates": {"block_a": estimate_tokens(block_a), "block_a_plus_b": per_install},
        "rule_counts": {"hard_rules": len(doc["hard_rules"]), "rules": len(doc["rules"]),
                        "by_evidence": {e: sum(1 for r in doc["rules"] + doc["hard_rules"] if r["evidence"] == e) for e in EVIDENCE},
                        "jev_rules_audited": jev_count,
                        "statements_verified": sum(len(facts[k]) for k in ("decide_rules", "controller_rules", "brain_rules")) + 1},
    }


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="repository root; derives every code path below")
    for k in ("core", "controller", "jev", "brain", "bridge", "auto", "numbers"):
        ap.add_argument(f"--{k}")
    ap.add_argument("--controller-copy", dest="controller_copy", help="the controller's copy of compiled/")
    ap.add_argument("--private-denylist", default=os.environ.get("DOCTRINE_PRIVATE_DENYLIST"))
    ap.add_argument("--private-skip", metavar="REASON", help="only where no secret exists (a fork pull request, a "
                    "contributor's machine): skip the private list, and say so")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    paths = resolve_paths(a)

    doc = json.loads((ROOT / "doctrine.rules.json").read_text(encoding="utf-8"))
    problems = validate(doc)
    refs = jev_refs(paths["jev"])
    missing, unknown = coverage(doc, refs)
    problems += [f"JEV rule not merged or dropped: {m}" for m in missing]
    problems += [f"merged_from names a JEV rule that does not exist: {u}" for u in unknown]
    facts, failures = engine_facts(doc, paths)
    problems += [f"statement no longer true of the code: {f}" for f in failures]

    outputs = {
        "00-role-and-hard-rules.md": md_hard(doc),
        "02-engine-rules.md": md_engine(doc, facts),
        "03-diagnosis-playbook.md": md_playbook(doc),
        "04-doctrine-rules.md": md_rules(doc),
        "05-stage-arcs.md": md_arcs(doc),
        "06-substrates.md": md_subs(doc),
        "07-brain-contract.md": md_rules(doc, None, "Brain contract and decisions",
                                         "What each acting answer does, and the observer -> planner -> guarded "
                                         "controller -> executor -> audit contract the brain must honour.",
                                         topics=("decisions", "contract")),
        "08-research-principles.md": md_rules(doc, "research", "Research principles (incl. Bugbee / USU)", "Only rules whose evidence class is research, paraphrased with citations."),
        "09-sources.md": md_sources(doc),
        "engine-rules.generated.json": json.dumps(facts, indent=2) + "\n",
    }
    compiled = compile_sections(doc, facts) | compile_block_b(doc)
    man = manifest(doc, facts, compiled, len(refs))
    compiled["compiled/manifest.json"] = json.dumps(man, indent=2) + "\n"
    outputs |= compiled

    # ---- strip lint: public always, private unless a fork pull request skips it
    public = load_public_denylist(PUBLIC_DENYLIST)
    private, errs = load_private_denylist(a)
    problems += errs
    every = public + private
    for name, text in outputs.items():
        scopes = ("all",) if name == "09-sources.md" else ("all", "cited")  # 09 is the citation registry itself
        problems += lint(name, text, every, scopes)
    no_registry = json.dumps({k: v for k, v in doc.items() if k != "sources"}, ensure_ascii=False)
    problems += lint("doctrine.rules.json", (ROOT / "doctrine.rules.json").read_text(encoding="utf-8"), every, ("all",))
    problems += lint("doctrine.rules.json (outside sources)", no_registry, every, ("cited",))
    for name in ["README.md"] + [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "tools").rglob("*.py"))]:
        problems += lint(name, (ROOT / name).read_text(encoding="utf-8"), every, ("all", "cited"))
    problems += lint(PUBLIC_DENYLIST.name, PUBLIC_DENYLIST.read_text(encoding="utf-8"), private, ("all",))
    if (ROOT / "vendor-snapshot").exists():
        problems.append("vendor-snapshot/ is inside the pack; move it out (it holds site text and must not ship)")

    # ---- committed outputs, stale compiled files, and the controller's copy of compiled/
    stale = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "compiled").rglob("*"))
             if p.is_file() and p.relative_to(ROOT).as_posix() not in outputs]
    copy = paths["controller_copy"]
    want_copy = {k[len("compiled/"):]: v for k, v in compiled.items()}
    if a.check:
        for name, text in outputs.items():
            f = ROOT / name
            if not f.exists() or f.read_bytes() != text.encode("utf-8"):
                problems.append(f"stale generated file: {name} (run tools/build_doctrine.py)")
        problems += [f"generated file no longer produced: {s} (run tools/build_doctrine.py)" for s in stale]
    else:
        for name, text in outputs.items():
            f = ROOT / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8", newline="\n")
        for s in stale:
            (ROOT / s).unlink()
    if copy is not None and Path(copy).is_dir():
        copy = Path(copy)
        have = {p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_file()}
        if a.check:
            problems += [f"controller doctrine copy differs: {n}" for n, text in sorted(want_copy.items())
                         if n not in have or (copy / n).read_bytes() != text.encode("utf-8")]
            problems += [f"controller doctrine copy has an extra file: {n}" for n in sorted(have - set(want_copy))]
        else:
            for n, text in want_copy.items():
                (copy / n).parent.mkdir(parents=True, exist_ok=True)
                (copy / n).write_text(text, encoding="utf-8", newline="\n")
            for n in have - set(want_copy):
                (copy / n).unlink()
        print(f"controller doctrine copy: {'checked' if a.check else 'written'} ({copy})")
    else:
        print("controller doctrine copy: none yet, skipped")

    # Report only, never written to a generated file: which code this run was checked against.
    checked = {k: sha(paths[k])[:12] for k in ("core", "controller", "bridge", "auto", "numbers")}
    checked["envelope"] = sha(Path(paths["brain"]) / "envelope.py")[:12]
    line = "checked against: " + ", ".join(f"{k} {v}" for k, v in checked.items())
    print(line)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"- doctrine {line}\n")
    print(json.dumps({"rule_counts": man["rule_counts"], "estimates": man["estimates"]}, indent=2))
    if problems:
        print("\nPROBLEMS:\n" + "\n".join(problems))
        return 1
    print("\nOK: rules valid, all JEV rules accounted for, code statements verified, strip lint clean"
          + (" (private list skipped)" if a.private_skip else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
