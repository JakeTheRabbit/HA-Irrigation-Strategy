"""Ask the real brain every judge's questions on realistic zone situations, and check its answers.

    ANTHROPIC_API_KEY=<sk-ant-...> python scripts/brain_live_smoke.py      (Claude, brain_provider claude_haiku)

A developer's tool, run by hand with a person's own key (and in the staging soak before a release): it calls
api.anthropic.com, and nothing in the app runs it. Each scenario builds a zone context the
way the controller does, runs the judge's own evidence (through the enrichment hook on Claude) and questions,
combines the two council phrasings, and prints the verdict next to what an experienced grower would expect. On
Claude it also prints the prompt's cached size (count_tokens) and each call's cache reads, which prove the prefix
caches. Nothing here touches Home Assistant or any hardware.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addons/f2_control/f2_control"), str(ROOT / "addons/f2_control/tests")]

import jev_kit as K  # noqa: E402
from brain import council  # noqa: E402
from brain.client import DEFAULT_MODEL, Asker, Meter, Route, Routes, call_anthropic, make_client  # noqa: E402
from brain.context import Shot, ZoneHistory  # noqa: E402
from brain.doctrine import STAGE_ARC, stage_intent  # noqa: E402
from brain.enrich import enrich  # noqa: E402
from brain.envelope import admit  # noqa: E402
from brain.prompt import Prompt  # noqa: E402
from brain.judges.dawn import DawnJudge  # noqa: E402
from brain.judges.dusk import DuskJudge  # noqa: E402
from brain.judges.night import NightJudge  # noqa: E402
from brain.judges.probe import ProbeJudge  # noqa: E402
from brain.judges.ramp import RampJudge  # noqa: E402
from brain.judges.salt import SaltJudge  # noqa: E402
from brain.judges.setpoints import SHOT, THRESHOLD, SetpointsJudge, band  # noqa: E402
from brain.judges.shot import ShotJudge  # noqa: E402
from brain.judges.stage import StageJudge  # noqa: E402
from brain.judges.zones import ZonesJudge  # noqa: E402


def ramp_feed_front():
    pts = [(m, 36.0 + min(4.5, (90 - m) * 0.06), 4.6 + (0.9 if m < 25 else 0.3)) for m in range(90, -1, -1)]
    h = K.history(pts, shots=[(80, 150, 36.0, 4.5, "p1_ramp"), (55, 150, 37.6, 4.7, "p1_ramp"),
                              (30, 150, 39.2, 5.0, "p1_ramp")])
    s = K.snap(phase="P1", vwc=40.4, shot_count=3, minutes_since_shot=20, ec=5.9, ec_settled=5.9)
    return K.ctx("P1", s=s, h=h, p=K.params(p1_target=40.0, field_capacity=42.0, ec_target_p1=4.5))


def ramp_still_climbing():
    pts = [(m, 30.0 + (60 - m) * 0.08, 4.4) for m in range(60, -1, -1)]
    h = K.history(pts, shots=[(50, 150, 30.2, 4.4, "p1_ramp"), (25, 150, 32.3, 4.4, "p1_ramp")])
    s = K.snap(phase="P1", vwc=34.8, shot_count=2, minutes_since_shot=22, ec=4.5, ec_settled=4.5)
    return K.ctx("P1", s=s, h=h, p=K.params(p1_target=40.0, field_capacity=42.0))


def probe_stuck():
    h = K.history([(m, 31.4, 3.0) for m in range(240, -1, -1)],
                  shots=[(200, 300, 31.4, 3.0, "p2_topup"), (120, 300, 31.4, 3.0, "p2_topup"),
                         (40, 300, 31.4, 3.0, "p2_topup")])
    return K.ctx("P2", s=K.snap(vwc=31.4, ec=3.0), h=h,
                 siblings={2: {"rise": 1.6, "rise_words": "10:40 p2_topup shot of 300 s: retained +1.6 points (normal)"},
                           3: {"rise": 1.3, "rise_words": "10:40 p2_topup shot of 300 s: retained +1.3 points (normal)"}})


def probe_healthy():
    pts, v = [], 34.0
    for m in range(240, -1, -1):
        v -= 0.012
        if m in (200, 120, 40):
            v += 1.5
        pts.append((m, round(v, 2), 3.2))
    h = K.history(pts, shots=[(200, 300, 33.5, 3.2, "p2_topup"), (120, 300, 33.4, 3.2, "p2_topup"),
                              (40, 300, 33.3, 3.2, "p2_topup")])
    return K.ctx("P2", s=K.snap(vwc=pts[-1][1], ec=3.2), h=h,
                 siblings={2: {"rise": 1.5, "rise_words": "retained +1.5 points (normal)"}})


def salt_front_passing():
    pts = [(m, 36.0, 4.4 + (240 - m) * 0.006) for m in range(240, -1, -1)]
    h = K.history(pts, shots=[(180, 400, 34.0, 4.6, "p2_dilute"), (90, 400, 34.5, 5.0, "p2_dilute")])
    s = K.snap(vwc=36.0, ec=5.8, ec_settled=5.8, feed_ec=2.4)
    return K.ctx("P2", s=s, h=h, feed_ec=2.4, p=K.params(ec_target_p2=4.5))


def dusk_ready(flower_day=12, steering="generative"):
    h = K.history([(m, 38.0 - (180 - m) * 0.004, 4.3) for m in range(180, -1, -1)],
                  shots=[(170, 300, 36.5, 4.3, "p2_topup")])
    s = K.snap(vwc=37.3, hours_to_lights_off=2.0, peak_vwc=38.5, minutes_since_shot=170, shot_count=9)
    return K.ctx("P2", s=s, h=h, hours_to_off=2.0, flower_day=flower_day, stage=stage_intent(flower_day),
                 steering=steering)


def dusk_bulk():
    return dusk_ready(flower_day=37, steering="vegetative")


def stage_mismatch():
    pts = []
    for m in range(0, 26 * 60, 10):
        t = K.NOW - timedelta(minutes=m)
        v = 36.0 if t.hour >= 10 and t.date() == K.NOW.date() else (38.0 if 12 <= t.hour < 22 else 31.0)
        pts.append((m, v, 4.6))
    s = K.snap(ec=4.6, ec_settled=4.6)
    return K.ctx("P2", s=s, h=K.history(pts), hours_to_on=21.0, hours_to_off=9.0, flower_day=37,
                 stage=stage_intent(37), steering="generative", plants=42)


def ramp_real_salt():
    pts = [(m, 36.0 + min(4.5, (150 - m) * 0.04), 7.4 - (150 - m) * 0.002) for m in range(150, -1, -1)]
    h = K.history(pts, shots=[(140, 150, 36.0, 7.4, "p1_ramp"), (110, 150, 37.4, 7.3, "p1_ramp"),
                              (80, 150, 38.8, 7.3, "p1_ramp"), (50, 150, 40.1, 7.2, "p1_flush")])
    s = K.snap(phase="P1", vwc=40.6, shot_count=4, minutes_since_shot=50, ec=7.1, ec_settled=7.1)
    return K.ctx("P1", s=s, h=h, feed_ec=3.0, p=K.params(p1_target=40.0, field_capacity=42.0, ec_target_p1=4.5),
                 flower_day=37, stage=stage_intent(37), steering="vegetative")


def dawn_drinking():
    h = K.history([(m, 38.0 - (70 - m) * 0.05, 4.2) for m in range(70, -1, -1)])
    s = K.snap(phase="P0", vwc=34.5, peak_vwc=38.0, dryback_pct=9.2, phase_minutes=70, shot_count=0)
    return K.ctx("P0", s=s, h=h, p=K.params(dryback_target=15.0, p0_max_wait_min=180))


def shots_not_landing():
    h = K.history([(m, 30.2, 3.1) for m in range(150, -1, -1)],
                  shots=[(110, 300, 30.2, 3.1, "p2_topup"), (50, 300, 30.2, 3.1, "p2_topup")])
    return K.ctx("P2", s=K.snap(vwc=30.2, ec=3.1, minutes_since_shot=45), h=h,
                 siblings={2: {"rise": 1.7, "rise_words": "retained +1.7 points (normal)"}})


def zone_wet_spot():
    h = K.history([(m, 39.0 - (120 - m) * 0.003, 4.0) for m in range(120, -1, -1)])
    s = K.snap(vwc=38.7, daily_vol=18.0, dryback_rate=0.15)
    sib = {2: {"litres_per_plant": 0.95, "litres_per_plant_words": "950 mL a plant today",
               "vwc_words": "VWC 33.0%, drying 0.60 points an hour", "threshold_words": "re-waters under 33.0%, shot 5.0%"},
           3: {"litres_per_plant": 0.9, "litres_per_plant_words": "900 mL a plant today",
               "vwc_words": "VWC 32.5%, drying 0.55 points an hour", "threshold_words": "re-waters under 33.0%, shot 5.0%"}}
    return K.ctx("P2", s=s, h=h, siblings=sib, plants=42)


def night_step():
    pts = [(m, 30.0 - (240 - m) * 0.005, 3.5) for m in range(240, 11, -1)] + [(m, 26.4, 3.5) for m in range(11, -1, -1)]
    h = K.history(pts)
    s = K.snap(phase="P3", vwc=26.4, lights_on=False, hours_to_lights_off=0.0, hours_to_lights_on=6.0)
    return K.ctx("P3", s=s, h=h, lights_on=False, hours_to_off=20.0, hours_to_on=6.0,
                 p=K.params(p3_emergency_floor=25.0))


NIGHT = datetime(2026, 9, 27, 23, 0)  # an hour after lights-off (lights 10:00-22:00), when Setpoints is asked


def _setpoint_day(ec_start, ec_now, shots, litres, rise):
    """Readings from lights-on (10:00) to NIGHT and the day's maintenance shots, each retaining `rise` points."""
    h = ZoneHistory()
    for m in range(780, 0, -5):
        h.add_reading(NIGHT - timedelta(minutes=m), 31.0, round(ec_start + (ec_now - ec_start) * (780 - m) / 780, 2))
    for m in shots:
        h.add_shot(Shot(NIGHT - timedelta(minutes=m), 260, litres, "p2_topup", round(31.0 - rise, 2), ec_start))
    return h


def _setpoint_ctx(p, h, daily, ec, siblings, vwc=31.2):
    sp = {"enabled": True, "current": {SHOT: p.p2_shot_size, THRESHOLD: p.p2_threshold},
          "home": {SHOT: p.p2_shot_size, THRESHOLD: p.p2_threshold},
          "bands": {SHOT: band(SHOT, p.p2_shot_size, p), THRESHOLD: band(THRESHOLD, p.p2_threshold, p)},
          "changed_today": False, "frozen": None, "day": "2026-09-27", "last_words": None}
    s = K.snap(phase="P3", vwc=vwc, ec=ec, ec_settled=ec, daily_vol=daily, lights_on=False)
    return K.ctx("P3", s=s, p=p, h=h, now=NIGHT, lights_on=False, hours_to_on=11.0, hours_to_off=23.0,
                 setpoints=sp, stage=stage_intent(37), flower_day=37, steering="vegetative", plants=42,
                 siblings=siblings)


def setpoints_zone1_heavy():
    """Zone 1 on 27 Sep 2026: 116 L (235 % of the room), pore EC 3.05 under the bulk band, weak retention."""
    p = K.params(p2_shot_size=5.0, p2_threshold=30.5, p3_emergency_floor=20.7, p1_target=36.5, field_capacity=40.0)
    shots = (700, 640, 580, 520, 460, 400, 340, 280, 220, 160, 90)
    h = _setpoint_day(2.8, 3.05, shots, 116.2 / len(shots), rise=0.6)
    return _setpoint_ctx(p, h, 116.2, 3.05, {2: {"litres_per_plant": 1.052, "rise_words": "retained +1.4 points (normal)"},
                                             3: {"litres_per_plant": 1.388, "rise_words": "retained +1.6 points (normal)"}})


def setpoints_on_course():
    """In line with the room, EC 4.8 inside 3.5-6, shots retaining normally."""
    p = K.params(p2_shot_size=5.0, p2_threshold=30.5, p3_emergency_floor=20.7, p1_target=36.5, field_capacity=40.0)
    shots = (620, 480, 330, 180, 70)
    h = _setpoint_day(4.6, 4.8, shots, 50.0 / len(shots), rise=1.5)
    return _setpoint_ctx(p, h, 50.0, 4.8, {2: {"litres_per_plant": 1.10, "rise_words": "retained +1.5 points (normal)"},
                                           3: {"litres_per_plant": 1.25, "rise_words": "retained +1.4 points (normal)"}})


def setpoints_thirsty():
    """43 % of the room's water, EC 6.8 over the bulk band and climbing, moisture ending low."""
    p = K.params(p2_shot_size=5.0, p2_threshold=27.0, p3_emergency_floor=20.0, p1_target=33.0, field_capacity=40.0)
    shots = (560, 300, 120)
    h = _setpoint_day(6.2, 6.8, shots, 19.0 / len(shots), rise=1.5)
    return _setpoint_ctx(p, h, 19.0, 6.8, {2: {"litres_per_plant": 1.05, "rise_words": "retained +1.4 points (normal)"},
                                           3: {"litres_per_plant": 1.10, "rise_words": "retained +1.5 points (normal)"}},
                         vwc=26.2)


SCENARIOS = [
    ("ramp: at the ceiling, EC up only from the feed", RampJudge(), ramp_feed_front, "ramp_state",
     {"ec_is_feed_front", "slab_full"}),
    ("ramp: still climbing strongly", RampJudge(), ramp_still_climbing, "ramp_state", {"keep_ramping"}),
    ("probe: flat for 4 h through three shots, siblings rose", ProbeJudge(), probe_stuck, "tracking", {False}),
    ("probe: rises 1.5 a shot, dries between", ProbeJudge(), probe_healthy, "tracking", {True}),
    ("salt: EC climbing after dilute shots, feed lower", SaltJudge(), salt_front_passing, "salt_cause",
     {"salt_front_passing", "salts_accumulating"}),
    ("dusk: 2 h to lights-off, flower setting (generative)", DuskJudge(), dusk_ready, "dusk_call", {"enter_p3_now"}),
    ("dusk: same zone, flower bulk (vegetative): must not stop early", DuskJudge(), dusk_bulk, "dusk_call",
     "no early stop"),
    ("stage: generative steering in flower bulk", StageJudge(), stage_mismatch, "arc", "steering flagged"),
    ("ramp: at the ceiling with real salt (settled EC high, feed lower)", RampJudge(), ramp_real_salt, "ramp_state",
     {"real_salt", "slab_full"}),
    ("dawn: 70 min in, drying steadily, 9% of 15%", DawnJudge(), dawn_drinking, "dawn_call",
     {"start_ramp_now", "keep_drying"}),
    ("shot: two shots, no rise, sibling rose", ShotJudge(), shots_not_landing, "landing", {"not_reaching_zone"}),
    ("zones: half the siblings' water, probe reads high", ZonesJudge(), zone_wet_spot, "why_different",
     {"probe_wet_spot", "plants_drinking_less"}),
    ("night: a 3.4-point step at 2 AM", NightJudge(), night_step, "night_drop", {"probe_fault"}),
    ("setpoints: zone 1 of 27 Sep, 235% of the room's water, EC under the bulk band", SetpointsJudge(),
     setpoints_zone1_heavy, "tomorrow", {"smaller_shots", "later_rewater"}),
    ("setpoints: on course, water in line, EC inside the band", SetpointsJudge(), setpoints_on_course, "tomorrow",
     {"keep"}),
    ("setpoints: 43% of the room's water, EC over the band, ending dry", SetpointsJudge(), setpoints_thirsty,
     "tomorrow", {"bigger_shots", "sooner_rewater"}),
]


def claude(key):
    """The Claude route exactly as brain_bridge.build() makes it, with a Meter and the cached prompt."""
    model = os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    prompt, meter, client = Prompt(STAGE_ARC, "slab_default"), Meter(5.0, model), make_client(key)
    if client is None:
        sys.exit("the anthropic SDK is not installed: pip install -r addons/f2_control/requirements-brain.txt")
    counted = client.messages.count_tokens(model=model, system=prompt.system, tools=prompt.tools,
                                           messages=[{"role": "user", "content": "size"}])
    print(f"{prompt.describe()}; tools and blocks A and B: {counted.input_tokens} tokens by count_tokens")
    route = Route("Anthropic", partial(call_anthropic, model=model, prompt=prompt, meter=meter, client=client),
                  "anthropic", key)
    return Asker("anthropic", key, threaded=False, timeout=60, transport=Routes([route]), meter=meter), meter


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("set ANTHROPIC_API_KEY")
    asker, meter = claude(os.environ["ANTHROPIC_API_KEY"])
    good = 0
    for title, judge, build, question, expect in SCENARIOS:
        ctx = build()
        key = f"smoke:{judge.name}:{title}"
        evidence = judge.evidence(ctx)
        if meter is not None:
            evidence = enrich(ctx, judge, evidence)
        asker.submit(key, evidence, council.expand(judge.questions))
        ans = asker.result(key)
        if meter is not None and ans is not None:
            print(f"      cache read {ans.usage.get('cache_read_input_tokens')} of {ans.usage.get('input_tokens')} "
                  f"input tokens, US${ans.usage.get('cost_usd', 0):.5f}")
        if ans is None:
            print(f"FAIL  {title}: no answer ({asker.stats['last_error']})")
            continue
        v = council.combine(ans.answers, question)
        d = judge.decide({q: council.combine(ans.answers, q) for q in judge.questions}, ctx)
        admitted, why = admit(d, ctx, confirmed=2, evidence_ok=True) if d is not None else (False, "no directive")
        if expect == "no early stop":  # judged on what code lets happen, not on the AI assistant's label
            ok = not (admitted and d.kind == "advance")
        elif expect == "steering flagged":
            ok = d is not None and d.kind == "alert" and "steering, but the stage calls for" in d.value["message"]
        else:
            ok = v is not None and v.label in expect
        good += ok
        acted = f"{d.kind} {d.value}" if d is not None else None
        print(f"{'ok  ' if ok else 'MISS'}  {title}: {v.label} p={v.prob:.2f} agreed={v.agreed} "
              f"-> {acted} [{'admitted' if admitted else 'refused: ' + why}]  (expected {expect})")
    total = len(SCENARIOS)
    print(f"\n{good}/{total} as a grower would expect; {asker.stats['calls']} calls, "
          f"{asker.stats['input_tokens']} input tokens, {asker.stats['errors']} errors"
          + ("" if meter is None else f", US${meter.snapshot()['cost_usd']:.4f} spent"))
    return 0 if good == total else 1


if __name__ == "__main__":
    sys.exit(main())
