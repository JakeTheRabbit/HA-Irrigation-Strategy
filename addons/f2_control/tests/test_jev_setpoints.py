"""The Setpoints judge: one notch a night on the zone's own P2 shot size or re-water threshold, inside a band
around the operator's value, the operator's edits always winning, and a rescue shot putting a change back.

26 Sep 2026: the old learner walked zone 1's P2 shot from 3 % to 1 % one step a day (30-second shots every 96
seconds) and ratcheted zone 3's targets to 74.5 in four days. These tests pin what makes that impossible now.
"""
import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import jev_bridge
import jev_kit as K
import pytest
import test_auto_setpoints_runtime as asr
from jev import council
from jev.brain import Brain
from jev.client import Asker
from jev.context import Shot, ZoneHistory
from jev.envelope import Directive, admit
from jev.journal import Journal
from jev.judges.setpoints import SHOT, THRESHOLD, SetpointsJudge, band
from jev.ledger import Ledger
from jev.setpoint_memory import SetpointMemory

NIGHT = datetime(2026, 9, 27, 23, 0)  # an hour after lights-off (lights 10:00-22:00)
Z1 = K.params(p2_shot_size=5.0, p2_threshold=30.5, p3_emergency_floor=20.7, p1_target=36.5, field_capacity=40.0)

# Zone 2 of a production room on 4 Oct 2026, before the operator's stopgap, and its learner block as controller 3.8.0 wrote it
# (tests_ha/fixtures/entry_3_8_learned_tent.json); kept here from the retired ratchet-guard tests.
Z2 = dict(p1_target_vwc=29.5, field_capacity=50.0, p2_vwc_threshold=27.5, p3_emergency_vwc_threshold=20.0,
          p2_shot_size=6.0)
SAVED_BY_3_8_0 = {
    "peak_adj": 0.0, "jev": {"day": None, "nudged": [], "asked": None, "last": None, "changed": None},
    "peak": 65.54, "gain": 1.368, "day_rate": 1.621, "night_rate": 0.815, "day_n": 8, "night_n": 8,
    "day_acc": [56.7, 35], "night_acc": [6.5, 8], "hold_days": 0, "day": "2026-10-03", "ramp_start": 44.0,
    "ramp": [{"pct": 2.0, "rise": 2.1, "settled": 46.1, "flat": False},
             {"pct": 2.0, "rise": 1.8, "settled": 47.9, "flat": False}],
    "pending": None, "outcome": "reached", "stalled_at": None, "last_change": "22:02 p2_shot_size 5.5 -> 6",
    "prev_peak": None, "prev_hold": 0, "veto": None,
}


def _sp(**over):
    base = {"enabled": True, "current": {SHOT: 5.0, THRESHOLD: 30.5}, "home": {SHOT: 5.0, THRESHOLD: 30.5},
            "bands": {SHOT: (4.0, 6.0), THRESHOLD: (28.5, 31.5)}, "changed_today": False, "frozen": None,
            "day": "2026-09-27", "last_words": None}
    base.update(over)
    return base


def _ctx(sp=None, now=NIGHT, lights_on=False, phase="P3", **over):
    s = K.snap(phase=phase, vwc=31.2, ec=3.05, ec_settled=3.05, daily_vol=116.2, lights_on=lights_on)
    stage = {"stage": "flower bulk", "days": (22, 42), "steering": "vegetative", "pore_ec_range": (3.5, 6.0),
             "peak": "at or above field capacity", "dryback": "10-15 points", "pore_ec": "3.5-6",
             "runoff": "8-16 %", "move_on_when": "later"}
    return K.ctx(phase, s=s, p=Z1, now=now, lights_on=lights_on, hours_to_on=11.0, hours_to_off=23.0,
                 setpoints=_sp() if sp is None else sp, stage=stage, flower_day=37, steering="vegetative",
                 plants=42, siblings={2: {"litres_per_plant": 1.052}, 3: {"litres_per_plant": 1.388}}, **over)


def _verdict(label, p=0.8, label_b=None):
    a = K.choice_answer(label, {label: p, "keep": round(1 - p, 2)})
    b = None if label_b is None else K.choice_answer(label_b, {label_b: p, "keep": round(1 - p, 2)})
    return {"tomorrow": council.combine(K.both("tomorrow", a, b), "tomorrow")}


# ------------------------------------------------------------------ the bands
def test_the_shot_band_never_goes_under_three_percent():
    assert band(SHOT, 5.0, Z1) == (4.0, 6.0)
    assert band(SHOT, 3.5, Z1) == (3.0, 4.5)
    assert band(SHOT, 3.0, Z1) == (3.0, 4.0)


def test_the_threshold_band_keeps_off_the_rescue_floor_and_the_ramp_ceiling():
    assert band(THRESHOLD, 30.5, Z1) == (28.5, 31.5)  # zone 1 on 27 Sep
    z2 = K.params(p3_emergency_floor=20.0, p1_target=29.5, field_capacity=50.0)
    assert band(THRESHOLD, 27.0, z2) == (25.0, 27.5)  # 2 under zone 2's ramp ceiling
    tight = K.params(p3_emergency_floor=26.0, p1_target=40.0, field_capacity=42.0)
    assert band(THRESHOLD, 30.5, tight)[0] == 30.0  # 4 above the rescue floor


# ------------------------------------------------------------------ when it is asked
def test_asked_once_early_in_the_night_and_only_when_it_may_act():
    j = SetpointsJudge()
    assert j.due(_ctx(), None)
    assert not j.due(_ctx(), NIGHT - timedelta(hours=1))  # already asked tonight
    four_hours_in = K.ctx("P3", s=K.snap(phase="P3"), lights_on=False, hours_to_on=8.0, hours_to_off=20.0,
                          setpoints=_sp())
    assert not j.due(four_hours_in, None)  # the first three hours of the night only
    for sp in (_sp(enabled=False), _sp(frozen="2026-09-29T23:00:00"), _sp(changed_today=True), _sp(current={})):
        assert not j.due(_ctx(sp=sp), None)
    assert not j.due(_ctx(phase="P2", lights_on=True), None)


# ------------------------------------------------------------------ what it may ask for
def test_a_firm_answer_is_one_notch_on_one_setting():
    d = SetpointsJudge().decide(_verdict("smaller_shots"), _ctx())
    assert d.kind == "setpoint" and d.value["suffix"] == SHOT and (d.value["from"], d.value["to"]) == (5.0, 4.5)
    assert d.value["words"] == "P2 shot 5% -> 4.5%" and d.value["choice"] == "smaller_shots"
    d = SetpointsJudge().decide(_verdict("later_rewater"), _ctx())
    assert d.value["suffix"] == THRESHOLD and d.value["to"] == 30.0


def test_keep_unsure_or_split_answers_ask_for_nothing():
    for v in (_verdict("keep"), _verdict("insufficient_evidence"), _verdict("smaller_shots", p=0.5),
              _verdict("smaller_shots", label_b="bigger_shots")):
        assert SetpointsJudge().decide(v, _ctx()) is None


def _two(label_a, label_b, probs):
    a, b = K.choice_answer(label_a, dict(probs)), K.choice_answer(label_b, dict(probs))
    return {"tomorrow": council.combine(K.both("tomorrow", a, b), "tomorrow")}


def test_a_firm_direction_acts_on_the_lever_both_phrasings_picked():
    """Live, 28 Sep: zone 1's heavy day read smaller shots 0.47, the rest mostly on re-watering later."""
    probs = {"smaller_shots": 0.47, "later_rewater": 0.33, "keep": 0.2}
    d = SetpointsJudge().decide(_two("smaller_shots", "smaller_shots", probs), _ctx())
    assert d is not None and d.value["choice"] == "smaller_shots"
    assert SetpointsJudge().decide(_two("smaller_shots", "later_rewater", probs), _ctx()) is None  # lever split


# ------------------------------------------------------------------ what code admits
def _d(frm, to, suffix=SHOT, now=NIGHT):
    return Directive("setpoints", "setpoint", {"suffix": suffix, "from": frm, "to": to, "choice": "x", "words": "w"},
                     "why", now + timedelta(minutes=30))


def test_the_envelope_admits_one_notch_inside_the_band():
    assert admit(_d(5.0, 4.5), _ctx()) == (True, "one notch inside its range around your value")


def test_the_envelope_refuses_everything_else():
    cases = [
        (_d(5.0, 4.5), _sp(enabled=False), "Auto setpoints is off"),
        (_d(5.0, 4.5), _sp(frozen="2026-09-29T23:00:00"), "paused after a safety revert"),
        (_d(5.0, 4.5), _sp(changed_today=True), "one change per zone per grow-day"),
        (_d(5.0, 4.0), _sp(), "one notch at a time"),
        (_d(5.0, 4.5), _sp(current={SHOT: 5.5, THRESHOLD: 30.5}), "changed since the AI assistant was asked"),
        (_d(4.0, 3.5), _sp(current={SHOT: 4.0, THRESHOLD: 30.5}), "outside its range 4-6"),
        (_d(30.5, 30.0, suffix="p1_target_vwc"), _sp(), "not a setting the AI assistant may move"),
    ]
    for d, sp, why in cases:
        ok, reason = admit(d, _ctx(sp=sp))
        assert not ok and why in reason, (why, reason)


# ------------------------------------------------------------------ what Jev is shown
def _today():
    """Readings through today (lights on 10:00) and four maintenance shots, all before NIGHT (23:00)."""
    h = ZoneHistory()
    for m in range(780, 0, -5):
        h.add_reading(NIGHT - timedelta(minutes=m), 31.0, 2.8 if m > 400 else 3.05)
    for m in (700, 560, 420, 90):
        h.add_shot(Shot(NIGHT - timedelta(minutes=m), 260, 12.0, "p2_topup", 30.4, 3.0))
    return h


def test_the_evidence_is_plain_words_with_the_ranges_and_the_room():
    e = SetpointsJudge().evidence(_ctx(h=_today()))
    assert e["water_per_plant_today"] == "2767 mL, 199% of the room's median zone (1388 mL)"
    assert e["maintenance_shots_today"] == "4, 48.0 L in all, about 260 s each"
    assert e["settings_now"][0] == "P2 shot size 5%; your value 5, may move 4-6"
    assert e["settings_now"][1] == "re-waters under 30.5% VWC; your value 30.5, may move 28.5-31.5"
    assert e["pore_ec_today"] == "from 2.80 at lights-on to 3.05 mS/cm now; the stage asks 3.5-6"
    # the lever's direction is doctrine, so code states it (live, without these Jev split 0.45 / 0.35 between
    # smaller and bigger shots on zone 1's heavy day; with them, smaller shots at 0.94)
    assert e["pore_ec_calls_for"].startswith("less runoff") and e["water_calls_for"].startswith("less water")
    assert e["shots_today"] == 4 and e["safety_shots_today"] == "none"
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", k) for k in e)


# ------------------------------------------------------------------ the bridge: memory, edits, writes, reverts
class _Controller:
    def __init__(self, tmp_path, numbers=None, auto="on"):
        asker = Asker("acct", "tok", transport=K.FakeTransport({}), threaded=False)
        self.jev = Brain(asker, Ledger(None), [SetpointsJudge()], log=lambda *a: None)
        self.jev.journal = Journal(None)
        self.jev.setpoints = SetpointMemory(str(tmp_path / "sp.json"))
        self.numbers = numbers or {SHOT: 5.0, THRESHOLD: 30.5}
        self.auto, self.writes, self.alerts, self.events = auto, [], [], []

    def _jev_read(self, entity):
        if entity.endswith("auto_setpoints"):
            return self.auto
        return next((str(v) for s, v in self.numbers.items() if entity.endswith(f"zone_1_{s}")), None)

    def _on(self, entity, default=False):
        return self.auto == "on" if entity.endswith("auto_setpoints") else default

    @staticmethod
    def _grow_day_start(room, now):
        return (now if now.hour >= 10 else now - timedelta(days=1)).date()

    def _auto_write(self, room, zone, suffix, old, value, learn, now, by="auto"):
        self.writes.append((zone, suffix, old, value, by))
        return True

    def _alert(self, key, code, title, message, room=None, zone=None):
        self.alerts.append((key, code, message))

    def _notify_event(self, event, room, zone, *detail):
        self.events.append((event, zone, detail))


def _room():
    return SimpleNamespace(slug="default", prefix="", state={1: {}}, strategy_required=False)


def test_the_first_look_takes_the_operators_values_as_the_centre(tmp_path):
    c, room = _Controller(tmp_path), _room()
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT)
    assert sp["enabled"] and sp["home"] == {SHOT: 5.0, THRESHOLD: 30.5}
    assert sp["bands"] == {SHOT: (4.0, 6.0), THRESHOLD: (28.5, 31.5)} and not sp["changed_today"]
    assert SetpointMemory(str(tmp_path / "sp.json")).zone("default", 1)["home"] == {SHOT: 5.0, THRESHOLD: 30.5}


def test_an_edit_by_hand_always_wins_and_moves_the_band(tmp_path):
    c, room = _Controller(tmp_path), _room()
    jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT)
    c.numbers[SHOT] = 6.0
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT)
    assert sp["home"][SHOT] == 6.0 and sp["bands"][SHOT] == (5.0, 7.0)
    top = c.jev.journal.recent("default")[0]
    assert top["verdict"] == "set by hand" and top["action"] == "p2 shot size 5 -> 6"


def test_a_move_is_written_once_and_is_not_mistaken_for_an_edit(tmp_path):
    c, room = _Controller(tmp_path), _room()
    ctx = _ctx(sp=jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT))
    d = SetpointsJudge().decide(_verdict("smaller_shots"), ctx)
    jev_bridge.apply_setpoint(c, room, 1, d, ctx, NIGHT)
    assert c.writes == [(1, SHOT, 5.0, 4.5, "AI setpoints judge")]
    # The phones that tick Jev hear of it (docs/NOTIFICATIONS.md): a push, no card.
    [(event, zone, (words, why, _entity))] = c.events
    assert (event, zone, words) == ("jev_setpoint", 1, "P2 shot 5% -> 4.5%")
    assert why.startswith("Smaller maintenance shots tomorrow") and "smaller_shots (p=" in why
    assert c.alerts == []
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(minutes=1))  # HA still shows 5.0
    assert sp["home"][SHOT] == 5.0 and sp["changed_today"]
    c.numbers[SHOT] = 4.5  # HA reflects the write
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(minutes=2))
    assert sp["home"][SHOT] == 5.0 and sp["current"][SHOT] == 4.5 and "P2 shot 5% -> 4.5%" in sp["last_words"]
    tomorrow = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(days=1))
    assert not tomorrow["changed_today"]


def test_a_move_written_names_its_number_on_the_push_for_keep_and_undo(tmp_path):
    """The phone gets Keep and Undo for the number Jev wrote (an AI overlay in the integration); a move not
    written (no per-zone number) names none."""
    c, room = _Controller(tmp_path), _room()
    c._auto_write = lambda *a, **k: True
    ctx = _ctx(sp=jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT))
    jev_bridge.apply_setpoint(c, room, 1, SetpointsJudge().decide(_verdict("smaller_shots"), ctx), ctx, NIGHT)
    [(event, zone, (words, _why, entity))] = c.events
    assert (event, zone, entity) == ("jev_setpoint", 1, f"number.crop_steering_zone_1_{SHOT}")


def test_a_move_that_went_back_to_the_operators_value_is_not_an_edit_by_hand(tmp_path):
    """The AI's overlay ran out or was undone (the integration's overlays.py): the operator's value is back."""
    c, room = _Controller(tmp_path), _room()
    ctx = _ctx(sp=jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT))
    jev_bridge.apply_setpoint(c, room, 1, SetpointsJudge().decide(_verdict("smaller_shots"), ctx), ctx, NIGHT)
    c.numbers[SHOT] = 4.5
    jev_bridge.readback(c, room, 1, NIGHT + timedelta(minutes=5))  # the write landed
    jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(minutes=10))
    c.numbers[SHOT] = 5.0  # put back to the operator's own value
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(days=2))
    assert sp["home"][SHOT] == 5.0 and sp["current"][SHOT] == 5.0
    assert all(row["verdict"] != "set by hand" for row in c.jev.journal.recent("default"))
    assert SHOT not in SetpointMemory(str(tmp_path / "sp.json")).zone("default", 1)["written"]


def test_a_rescue_shot_after_a_change_puts_it_back_and_pauses_the_zone(tmp_path):
    c, room = _Controller(tmp_path), _room()
    ctx = _ctx(sp=jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT))
    jev_bridge.apply_setpoint(c, room, 1, SetpointsJudge().decide(_verdict("later_rewater"), ctx), ctx, NIGHT)
    c.numbers[THRESHOLD] = 30.0
    jev_bridge.guard_setpoints(c, room, 1, NIGHT + timedelta(hours=2))  # nothing has happened yet
    assert len(c.writes) == 1
    jev_bridge._hist(room, 1).add_shot(Shot(NIGHT + timedelta(hours=4), 120, 5.0, "p3_emergency", 20.5, 3.0))
    jev_bridge.guard_setpoints(c, room, 1, NIGHT + timedelta(hours=4, minutes=5))
    assert c.writes[-1] == (1, THRESHOLD, 30.0, 30.5, "AI setpoints judge (put back)")
    assert c.alerts and c.alerts[-1][1] == "CS-404" and "03:00" in c.alerts[-1][2]
    c.numbers[THRESHOLD] = 30.5  # Home Assistant reflects the put-back
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(hours=5))
    assert sp["frozen"] and "put back" in sp["last_words"]
    jev_bridge.guard_setpoints(c, room, 1, NIGHT + timedelta(hours=6))  # once only
    assert len(c.writes) == 2 and c.jev.journal.recent("default")[0]["verdict"] == "safety revert"


def _moved(tmp_path):
    c, room = _Controller(tmp_path), _room()
    ctx = _ctx(sp=jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT))
    jev_bridge.apply_setpoint(c, room, 1, SetpointsJudge().decide(_verdict("smaller_shots"), ctx), ctx, NIGHT)
    return c, room, c.jev.setpoints.zone("default", 1)


def test_a_write_that_lands_is_read_back_and_never_sent_again(tmp_path):
    c, room, rec = _moved(tmp_path)
    c.numbers[SHOT] = 4.5
    jev_bridge.readback(c, room, 1, NIGHT + timedelta(minutes=1))
    assert rec["pending"] is None
    jev_bridge.readback(c, room, 1, NIGHT + timedelta(hours=2))
    assert c.writes == [(1, SHOT, 5.0, 4.5, "AI setpoints judge")]


def test_a_pending_write_an_older_release_saved_as_jev_is_still_the_judges_own(tmp_path):
    """3.12 named the Setpoints judge's writer "Jev" in jev_setpoints.json: after the update it is resent and, once
    it fails, marked failed exactly as a write saved by this release."""
    c, room, rec = _moved(tmp_path)
    rec["pending"]["by"] = "Jev"
    rec["last"]["to"] = 4.5
    for minutes in (4, 5, 15, 35, 75):
        jev_bridge.readback(c, room, 1, NIGHT + timedelta(minutes=minutes))
    assert len(c.writes) == 4 and {w[4] for w in c.writes} == {"AI setpoints judge", "Jev"}
    assert rec["pending"] is None and rec["last"].get("failed") is True


def test_a_write_that_does_not_land_is_sent_again_backing_off_then_recorded_as_failed(tmp_path):
    c, room, rec = _moved(tmp_path)  # Home Assistant keeps showing 5.0
    for minutes, sent in ((4, 1), (5, 2), (14, 2), (15, 3), (35, 4), (74, 4)):
        jev_bridge.readback(c, room, 1, NIGHT + timedelta(minutes=minutes))
        assert len(c.writes) == sent, minutes
        sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(minutes=minutes))
        assert sp["home"][SHOT] == 5.0  # the old value is never taken for an edit by hand while it is retried
    assert set(c.writes) == {(1, SHOT, 5.0, 4.5, "AI setpoints judge")}
    jev_bridge.readback(c, room, 1, NIGHT + timedelta(minutes=75))
    assert len(c.writes) == 4 and rec["pending"] is None and rec["written"][SHOT] == 5.0
    top = c.jev.journal.recent("default")[0]
    assert (top["verdict"], top["action"], top["result"]) == ("write failed", "p2 shot size 5 -> 4.5", "failed")
    assert "still shows 5 after 4 tries" in top["reason"]
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(minutes=76))
    assert sp["home"][SHOT] == 5.0 and sp["last_words"].endswith("(did not reach Home Assistant)")
    assert c.jev.journal.recent("default")[0]["verdict"] == "write failed"  # and not "set by hand"
    assert SetpointMemory(str(tmp_path / "sp.json")).zone("default", 1)["last"]["failed"]


def test_switching_automatic_targets_off_stops_the_retries(tmp_path):
    c, room, rec = _moved(tmp_path)
    c.auto = "off"
    jev_bridge.readback(c, room, 1, NIGHT + timedelta(minutes=5))
    assert len(c.writes) == 1 and rec["pending"] is None
    assert "switched off" in c.jev.journal.recent("default")[0]["reason"]


def test_an_edit_by_hand_during_the_retries_ends_them(tmp_path):
    c, room, rec = _moved(tmp_path)
    c.numbers[SHOT] = 5.5
    jev_bridge.readback(c, room, 1, NIGHT + timedelta(minutes=5))
    assert len(c.writes) == 1 and rec["pending"] is None
    assert jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(minutes=6))["home"][SHOT] == 5.5


def test_a_pending_write_an_older_memory_left_still_loads_and_times_out(tmp_path):
    old = {"default:1": {"home": {SHOT: 5.0}, "written": {SHOT: 4.5},
                         "pending": {"suffix": SHOT, "from": 5.0, "at": NIGHT.isoformat()}}}
    (tmp_path / "sp.json").write_text(json.dumps(old))
    c, room = _Controller(tmp_path), _room()
    jev_bridge.readback(c, room, 1, NIGHT + timedelta(hours=1))
    assert c.writes == []
    sp = jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT + timedelta(hours=1))
    assert sp["home"][SHOT] == 5.0 and c.jev.setpoints.zone("default", 1)["pending"] is None


def test_the_whole_loop_through_the_brain_logs_and_files_the_move(tmp_path):
    c, room = _Controller(tmp_path), _room()
    answer = K.choice_answer("smaller_shots", {"smaller_shots": 0.8, "keep": 0.2})
    c.jev.asker.transport = K.FakeTransport(K.both("tomorrow", answer))
    c.jev.asker.clock = lambda: NIGHT.timestamp()
    ctx = _ctx(sp=jev_bridge.setpoint_view(c, room, 1, Z1, NIGHT))
    [(d, why)] = c.jev.tick(ctx)
    assert d.kind == "setpoint" and why == "one notch inside its range around your value"
    top = c.jev.journal.recent("default")[0]
    assert top["title"] == "Setpoints" and top["action"] == "P2 shot 5% -> 4.5%" and top["result"] == "acted"
    assert c.jev.ledger.entries[-1]["label"] == "smaller_shots"


# ------------------------------------------------------------------ how it turned out
def test_the_outcome_asks_whether_water_or_ec_moved_the_way_the_change_meant():
    j = SetpointsJudge()
    entry = {"label": "smaller_shots", "check": {"daily_vol": 116.0, "ec": 3.0}}
    what, good = j.outcome(entry, _ctx())  # 116.2 L the next day: no less water, EC 3.05 not toward 3.5 by 0.05
    assert not good and "water 116 -> 116 L" in what
    later = K.ctx("P3", s=K.snap(phase="P3", daily_vol=90.0, ec_settled=3.4), setpoints=_sp(),
                  stage={"pore_ec_range": (3.5, 6.0)})
    assert j.outcome(entry, later)[1]


# ------------------------------------------------------------------ each lever has one writer
# With the Setpoints judge running, the P2 shot size and re-water threshold are its own and the base engine's Auto
# Setpoints learner keeps the rest. Until 4 Oct 2026 the learner wrote nothing at all once the judge ran, so nothing
# wrote the P1 target: zone 2 sat at 29.5 from 26 Sep while its probe read 42-44 % at lights-on, and P1 never ramped.
JUDGE = dict(K.HAIKU)
Z2 = {f"number.crop_steering_zone_1_{s}": (str(v), {}) for s, v in Z2.items()}  # zone 2, as the rig's zone 1
LIGHTS_ON = datetime(2026, 10, 4, 10, 0)
LEARNER, JUDGED = ("p1_target_vwc", "field_capacity"), (SHOT, THRESHOLD)  # the rescue floor is nobody's


@pytest.fixture(autouse=True)
def _claude(monkeypatch):
    """The brain these rigs start is the Claude route, answering nothing unless a test says otherwise."""
    K.sdk(monkeypatch, K.FakeTransport({}))


@pytest.fixture
def ramp_clock(monkeypatch):
    asr._Clock.current = datetime(2026, 9, 19, 11, 0)
    monkeypatch.setattr(asr.controller, "datetime", asr._Clock)


def _zone_2(auto="on", plan=False, numbers=Z2):
    """Zone 2 with what its learner had learned by 4 Oct, loaded from the block controller 3.8.0 saved."""
    c, fake, room = asr._rig(auto=auto, numbers=numbers, options=JUDGE)
    room.state[1]["learn"] = c._apply_saved_zone(c._fresh_zone(), {"learn": SAVED_BY_3_8_0})["learn"]
    room.strategy_required = plan
    return c, fake, room


def _day(c, fake, room, entry_vwc=44.0, p2_passes=8, ramp=()):
    """A grow-day through the controller's own pass, a minute apart: lights-on in P0, P1 entered at `entry_vwc`
    with a 2 % ramp shot through the controller's own shot hook for each of `ramp` (what each retained, read 21
    minutes on), then P2."""
    now, vwc = LIGHTS_ON, entry_vwc
    for phase, reading in (("P0", 44.0), ("P1", entry_vwc)):
        room.state[1]["phase"], asr._Clock.current = phase, now
        asr._tick(c, fake, room, reading, now)
        now += timedelta(minutes=1)
    for rise in ramp:
        c._advance_shot_counters(room, 1, 2.0)
        vwc, now = round(vwc + rise, 2), now + timedelta(minutes=21)
        asr._Clock.current = now
        asr._tick(c, fake, room, vwc, now)
    room.state[1]["phase"] = "P2"
    for _ in range(p2_passes):
        asr._Clock.current = now
        asr._tick(c, fake, room, 52.0, now)
        now += timedelta(minutes=1)


def _sent(fake, suffix=None):
    return [d["value"] if suffix else d["entity_id"] for dom, svc, d in fake.calls
            if (dom, svc) == ("number", "set_value")
            and (suffix is None or d["entity_id"] == f"number.crop_steering_zone_1_{suffix}")]


def test_the_learner_never_writes_the_judges_levers_nor_the_rescue_level(ramp_clock):
    c, fake, room = _zone_2(numbers={**Z2, "number.crop_steering_zone_1_p3_emergency_vwc_threshold": ("26", {})})
    _day(c, fake, room, p2_passes=150)  # well over an hour of P2, where the old hourly judge moved the shot
    assert _sent(fake, THRESHOLD) == [] and _sent(fake, SHOT) == []  # its band wanted 57.3: not its lever
    assert _sent(fake, "p3_emergency_vwc_threshold") == []  # the rescue level is the operator's, even 1.5 under
    # the judge's 27.5
    assert fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]["jev"] == "disabled"


@pytest.mark.parametrize("why", ["switch off", "plan owns the room"])
def test_the_switch_and_an_armed_plan_still_stop_every_write(ramp_clock, why):
    c, fake, room = _zone_2(auto="off" if why == "switch off" else "on", plan=why == "plan owns the room")
    _day(c, fake, room)
    assert _sent(fake) == []
    state, attrs = fake.sets["sensor.crop_steering_zone_1_auto_setpoints"]
    assert state == ("off" if why == "switch off" else "frozen")


def test_the_published_attributes_say_which_writer_owns_which_lever(ramp_clock):
    c, fake, room = _zone_2()
    _day(c, fake, room)
    attrs = fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]
    number = "number.crop_steering_zone_1_"
    assert sorted(attrs["managed"]) == sorted(number + s for s in LEARNER + JUDGED)
    owners = attrs["managed_by"]
    assert {owners[number + s] for s in JUDGED} == {"the AI assistant's Setpoints judge, one notch a night"}
    # the zone's own highest readings set these two, not the learner (6 Oct 2026)
    assert owners[number + "p1_target_vwc"] == "the zone's highest reading of the grow-day before"
    assert owners[number + "field_capacity"] == "the zone's highest reading of this grow-day or the one before"
    # without the judge the learner owns the threshold too, and the shot size is nobody's
    c, fake, room = asr._rig()
    asr._flat_ramp(c, fake, room)
    owners = fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]["managed_by"]
    assert owners[number + THRESHOLD] == "Auto setpoints learner" and number + SHOT not in owners
