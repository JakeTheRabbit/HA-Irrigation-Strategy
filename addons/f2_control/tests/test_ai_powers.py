"""The AI assistant's powers (docs/AI_ASSISTANT.md, "Powers"): one switch per power per room says what the AI assistant may
change. Off, its judge still runs and advises, and the envelope refuses to act; a missing switch is the power's
default, so an install from before the switches does what it did. Two new powers, off until the owner turns them on:
the AI assistant sets a zone's targets, and its shot sizes, itself; code writes its values as given, clamped only to
each setting's own range, with its reason and expected result in the change log."""
import functools
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import controller
import jev_bridge
import jev_kit as K
from jev import council
from jev import powers as pw
from jev.brain import Brain
from jev.client import Asker
from jev.envelope import Directive, admit, cools_down
from jev.journal import Journal
from jev.judges import targets as tg
from jev.ledger import Ledger
from jev.setpoint_memory import SetpointMemory
from test_controller import _build, _desc

NIGHT = datetime(2026, 9, 27, 23, 0)  # an hour after lights-off (lights 10:00-22:00)
P1, FC, THR, RESCUE = tg.P1, tg.FC, tg.THR, tg.RESCUE
LADDER = {FC: 52.0, P1: 50.0, THR: 45.0, RESCUE: 30.0}


def _d(kind, value, judge="t"):
    return Directive(judge, kind, value, "why", NIGHT + timedelta(hours=1))


# ------------------------------------------------------------------ the powers
def test_every_power_that_acted_before_defaults_on_and_the_new_ones_off():
    assert [k for k, _d, _w in pw.POWERS] == ["advance_phase", "ramp_control", "set_probe_aside", "ec_mode",
                                              "nudge_setpoints", "plan_catch_up", "set_targets_from_achievable",
                                              "tune_shot_sizes"]
    assert {k for k, on in pw.DEFAULTS.items() if not on} == {"set_targets_from_achievable", "tune_shot_sizes"}
    assert pw.entity("tent_", "ec_mode") == "switch.crop_steering_tent_ai_power_ec_mode"


def test_the_integration_names_the_same_powers_and_defaults():
    import ast
    import pathlib

    src = (pathlib.Path(controller.__file__).parents[3] / "custom_components" / "crop_steering" / "const.py")
    tree = ast.parse(src.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "AI_POWERS")
    assert [(k, on) for k, _name, on in ast.literal_eval(node.value)] == [(k, on) for k, on, _w in pw.POWERS]


def test_each_directive_needs_its_power():
    assert pw.power_of(_d("advance", "P1", "dawn")) == "advance_phase"
    assert pw.power_of(_d("advance", "P3", "dusk")) == "advance_phase"
    assert pw.power_of(_d("advance", "P2", "ramp")) == "ramp_control"
    assert [pw.power_of(_d(k, None)) for k in ("distrust", "ec_mode", "setpoint", "catch_up", "targets", "shot_size",
                                               "alert", "push")] == [
        "set_probe_aside", "ec_mode", "nudge_setpoints", "plan_catch_up", "set_targets_from_achievable",
        "tune_shot_sizes", None, None]


def test_unread_or_missing_powers_are_their_defaults():
    assert pw.allowed(None, "ec_mode") and not pw.allowed(None, "tune_shot_sizes")
    assert pw.allowed({}, "advance_phase") and pw.allowed({"advance_phase": None}, "advance_phase")
    assert not pw.allowed({"advance_phase": False}, "advance_phase") and pw.allowed({"tune_shot_sizes": True},
                                                                                     "tune_shot_sizes")
    assert pw.read(lambda e, default: default, "") == pw.DEFAULTS  # no switch at all: today's behaviour


@pytest.mark.parametrize("kind,value,judge,ctx_over", [
    ("advance", "P2", "ramp", {"phase": "P1", "s": K.snap(phase="P1", shot_count=3, vwc=40.0)}),
    ("ec_mode", "hold", "salt", {"phase": "P2"}),
    ("distrust", "stuck", "probe", {"phase": "P2"}),
])
def test_a_power_switched_off_turns_an_admitted_directive_into_advice(kind, value, judge, ctx_over):
    over = dict(ctx_over)
    phase = over.pop("phase")
    ctx = K.ctx(phase, **over)
    d = Directive(judge, kind, value, "why", ctx.now + timedelta(minutes=30))
    assert admit(d, ctx, confirmed=2, evidence_ok=True)[0]  # on by default
    power = pw.power_of(d)
    ok, why = admit(d, K.ctx(phase, powers={power: False}, **over), confirmed=2, evidence_ok=True)
    assert not ok and why.endswith("advice only") and "has not given the AI assistant the power" in why
    assert not cools_down(why)  # a power off is the owner's choice, not a move that was wrong
    other = {k: False for k in pw.DEFAULTS if k != power}
    assert admit(d, K.ctx(phase, powers=other, **over), confirmed=2, evidence_ok=True)[0]


def test_alerts_need_no_power():
    off = {k: False for k in pw.DEFAULTS}
    assert admit(_d("alert", {"code": "CS-701"}), K.ctx("P2", now=NIGHT, powers=off))[0]


# ------------------------------------------------------------------ the values the AI assistant sets
def _values_answer(values, expected="the zone reaches 58 tomorrow", confidence=0.8):
    return {"type": "values", "values": {k: {"value": v, "reason": f"because {k}"} for k, v in values.items()},
            "expected": expected, "confidence": confidence, "rationale": "the scorecard says so"}


def test_set_values_is_checked_against_the_questions_own_settings_only():
    from jev.client import validate_answer

    lane = {"targets__v0": tg.values("q", {P1: "peak", RESCUE: "floor"})}

    def call(**args):
        base = {"snapshot_id": "s", "question_id": "targets__v0", "values": [], "expected_outcome": "x",
                "confidence": 0.7, "rationale": "r"}
        return validate_answer(SimpleNamespace(name="set_values", input={**base, **args}), "s", lane)

    qid, got = call(values=[{"key": P1, "value": 71.5, "reason": "it reached 72"},
                            {"key": RESCUE, "value": 12.0, "reason": "drier stage"}])
    assert qid == "targets__v0" and got["values"] == {P1: {"value": 71.5, "reason": "it reached 72"},
                                                      RESCUE: {"value": 12.0, "reason": "drier stage"}}
    assert got["expected"] == "x" and call(values=[])[1]["values"] == {}  # none: keep them all
    assert call(values=[{"key": FC, "value": 60, "reason": "r"}]) is None  # not this question's setting
    assert call(values=[{"key": P1, "value": float("nan"), "reason": "r"}]) is None
    assert call(values=[{"key": P1, "value": True, "reason": "r"}]) is None


def test_a_values_answer_is_one_firm_reading_never_asked_again():
    v = council.combine({"targets__v0": _values_answer({P1: 58.0})}, "targets")
    assert (v.kind, v.label, v.n, v.values[P1]["value"], v.expected) == ("values", "set", 1, 58.0,
                                                                         "the zone reaches 58 tomorrow")
    brain = Brain(Asker("a", "t", transport=K.FakeTransport({}), threaded=False), Ledger(None), [], log=print)
    assert not brain._unsure([v]) and brain._sure([v])
    assert council.combine({"targets__v0": _values_answer({})}, "targets").label == "keep"


def _view(current=None, power=True, **over):
    v = {"current": dict(current or LADDER), "limits": {k: (10.0, 100.0) for k in (current or LADDER)}, "days": [],
         "changes": [], "plan": None, "power": power, "changed_today": False, "day": "2026-09-27"}
    v.update(over)
    return v


def _decide(values, view=None, powers=None, judge=None):
    judge = judge or tg.TargetsJudge()
    attr = "targets" if judge.kind == "targets" else "shots"
    ctx = K.ctx("P3", now=NIGHT, lights_on=False, hours_to_on=11.0, hours_to_off=23.0,
                powers={"set_targets_from_achievable": True, "tune_shot_sizes": True} if powers is None else powers,
                **{attr: view or _view()})
    v = council.combine({f"{judge.question}__v0": _values_answer(values)}, judge.question)
    return judge.decide({judge.question: v}, ctx), ctx


def test_with_its_power_on_any_values_it_sets_are_admitted_as_given():
    # a 12-point jump, the rescue floor moved, an inverted ladder: no limit of code's own applies to the power
    d, ctx = _decide({P1: 62.0, RESCUE: 22.0, THR: 63.0})
    assert d.kind == "targets" and d.value["values"] == {P1: 62.0, RESCUE: 22.0, THR: 63.0}
    assert d.value["expected"] == "the zone reaches 58 tomorrow" and d.value["reasons"][RESCUE] == f"because {RESCUE}"
    assert admit(d, ctx) == (True, "the owner's power: written as given, inside each setting's own range")
    d2, ctx2 = _decide({P1: 62.0}, view=_view(changed_today=False, plan="a grow plan owns this room's targets"))
    assert admit(d2, ctx2)[0]  # the plan is evidence for the AI to follow, not a gate


def test_with_its_power_off_it_only_advises():
    d, ctx = _decide({P1: 58.0}, powers={})  # missing switch: the default, off
    ok, why = admit(d, ctx)
    assert not ok and why.endswith("advice only")
    d, ctx = _decide({ss_key: 4.0 for ss_key in (tg.P2S,)}, view=_view({tg.P1S: 3.0, tg.P2S: 5.0}),
                     powers={"tune_shot_sizes": False}, judge=tg.ShotSizeJudge())
    assert d.kind == "shot_size" and not admit(d, ctx)[0]


def test_only_its_own_settings_and_numbers_are_admitted_and_keep_is_no_directive():
    d, ctx = _decide({P1: 58.0})
    bad = Directive("targets", "targets", {**d.value, "values": {"maximum_ec": 9.0}}, "x", d.expires)
    assert admit(bad, ctx) == (False, "only this question's own settings may be set")
    assert _decide({})[0] is None


def test_the_judge_asks_once_a_night_with_each_settings_value_and_range():
    judge = tg.TargetsJudge()
    ctx = K.ctx("P3", now=NIGHT, lights_on=False, hours_to_on=11.0, hours_to_off=23.0, targets=_view())
    assert judge.due(ctx, None) and not judge.due(ctx, NIGHT - timedelta(hours=1))
    assert not judge.due(K.ctx("P3", now=NIGHT, lights_on=False, targets=_view(changed_today=True)), None)
    crit = judge.questions_for(ctx)["targets"][0]["criteria"]
    assert set(crit) == set(LADDER) and "now 50, its range 10-100" in crit[P1]
    assert judge.questions["targets"][0]["type"] == "values"


# ------------------------------------------------------------------ the scorecard
DAY = {"day": "2026-09-26", "trusted": True, "why": None,
       "p0": {"target": 20.0, "actual": 14.5, "hit": False}, "p1": {"target": 50.0, "top": 52.1, "shots": 4, "hit": True},
       "p2": {"ec": 6.6, "band": [3.5, 6.0], "hit": False}, "p3": {"rescues": 0, "hit": True},
       "uniformity": {"ratio": 1.04, "hit": True}}


def test_the_scorecard_says_each_goal_hit_or_missed_and_by_how_much():
    line = tg.scorecard_line(DAY)
    assert "P0 dryback 14.5% at the ramp's start against a 20% target (missed by -5.5)" in line
    assert "P1 peak 52.1% against the 50% target in 4 shots (hit)" in line
    assert "P2 pore EC 6.60 against the stage's 3.5-6 (missed by +0.60)" in line
    assert "P3 no rescue shot (hit)" in line and "water per plant 104% of the room's typical zone (hit)" in line
    assert tg.hits(DAY) == (3, 2)


def test_the_evidence_shows_its_earlier_changes_with_what_it_expected_and_what_followed():
    change = {"judge": "targets", "day": "2026-09-25", "values": {P1: [48.0, 50.0]}, "expected": "P1 reaches 50"}
    view = _view(days=[dict(DAY, day="2026-09-25"), DAY], changes=[change])
    e = tg.TargetsJudge().evidence(K.ctx("P3", now=NIGHT, lights_on=False, targets=view))
    assert e["your_earlier_changes"] == [
        "2026-09-25: you set p1_target_vwc 48 -> 50; you expected: P1 reaches 50; what followed: "
        + tg.scorecard_line(DAY)]
    assert len(e["scorecard"]) == 2 and e["goal"].startswith("each grow-day: P0 reaches")
    assert e["your_power"].startswith("on: code writes what you set")


class _Controller:
    """The controller methods the bridge's power code uses, over an in-memory set of zone numbers."""

    def __init__(self, tmp_path, numbers=None, powers=None, ranges=None, refuse=()):
        asker = Asker("acct", "tok", transport=K.FakeTransport({}), threaded=False)
        self.jev = Brain(asker, Ledger(None), [tg.TargetsJudge(), tg.ShotSizeJudge()], log=lambda *a: None)
        self.jev.journal = Journal(None)
        self.jev.setpoints = SetpointMemory(str(tmp_path / "sp.json"))
        self.numbers = dict(numbers or {**LADDER, tg.GEN_DB: 20.0, tg.P1S: 3.0, tg.P2S: 5.0})
        self.powers = {"set_targets_from_achievable": True, "tune_shot_sizes": True, **(powers or {})}
        self.ranges, self.refuse = dict(ranges or {}), set(refuse)
        self.writes, self.claims, self.events = [], [], []

    def _jev_read(self, entity):
        return next((str(v) for s, v in self.numbers.items() if entity.endswith(f"zone_1_{s}")), None)

    def _on(self, entity, default=False):
        key = entity.rsplit("ai_power_", 1)[-1]
        return self.powers.get(key, default) if "ai_power_" in entity else default

    def _number_range(self, room, zone, suffix):
        return self.ranges.get(suffix, (10.0, 100.0))

    @staticmethod
    def _veg(room, zone):
        return False

    @staticmethod
    def _grow_day_start(room, now):
        return (now if now.hour >= 10 else now - timedelta(days=1)).date()

    def _auto_write(self, room, zone, suffix, old, value, learn, now, by="auto", reason=None, expected=None):
        if suffix in self.refuse:
            self.refuse.discard(suffix)  # refused once (the ladder's order), taken after the others
            return False
        self.writes.append((suffix, old, value, by))
        self.claims.append((suffix, reason, expected))
        self.numbers[suffix] = value
        return True

    def _notify_event(self, event, room, zone, *detail):
        self.events.append((event, zone, detail))


def _room():
    st = {"learn": {"outcome": "reached", "gain": 1.0}, "fc_follow": {"peak": 52.1}, "ec_settled": 6.6,
          "night_hist": [{"date": "2026-09-27", "dryback_pct": 14.5, "night_shots": 0}],
          "plateau_hist": [{"date": "2026-09-27", "value": 52.0, "how": "rise rule", "shots": 4}]}
    return SimpleNamespace(slug="default", prefix="", strategy_required=False, lights_on_hour=10, zones={1: {}},
                           state={1: st}, _jev_sib={1: {"litres_per_plant": 1.04}, 2: {"litres_per_plant": 1.0}})


def _params():
    return K.params(p1_target=50.0, field_capacity=52.0, p2_threshold=45.0, p3_emergency_floor=30.0,
                    dryback_target=20.0)


def test_a_night_records_the_zones_card_once_from_its_own_records(tmp_path, monkeypatch):
    monkeypatch.setattr(jev_bridge, "stage_info", lambda c, room, now: {"pore_ec": [3.5, 6.0]})
    c, room = _Controller(tmp_path), _room()
    view = jev_bridge.targets_view(c, room, 1, _params(), NIGHT)
    (day,) = view["days"]
    assert {k: day[k] for k in ("day", "trusted")} == {"day": "2026-09-27", "trusted": True}
    assert day["p0"] == {"target": 20.0, "actual": 14.5, "hit": False}
    assert day["p1"] == {"target": 50.0, "top": 52.1, "shots": 4, "hit": True}
    assert day["p2"] == {"ec": 6.6, "band": [3.5, 6.0], "hit": False}
    assert day["p3"] == {"rescues": 0, "hit": True} and day["uniformity"]["hit"]
    assert set(view["current"]) == {FC, P1, THR, RESCUE, tg.GEN_DB}  # the zone's own steering mode's dryback
    jev_bridge.targets_view(c, room, 1, _params(), NIGHT + timedelta(minutes=30))
    assert len(jev_bridge._ai(c, room, 1)["days"]) == 1  # once a grow-day
    room.state[1]["fc_follow"]["peak"] = None  # a CS-310 day is recorded as not trusted
    jev_bridge._ai(c, room, 1)["day_recorded"] = None
    assert "CS-310" in jev_bridge.targets_view(c, room, 1, _params(), NIGHT)["days"][-1]["why"]


def test_the_values_are_written_as_given_from_the_top_with_reason_and_expected_result(tmp_path):
    c, room = _Controller(tmp_path), _room()
    view = jev_bridge.targets_view(c, room, 1, _params(), NIGHT)
    d, ctx = _decide({FC: 62.0, P1: 60.0, THR: 54.0, RESCUE: 25.0}, view=view)
    jev_bridge.apply_values(c, room, 1, d, ctx, NIGHT)
    by = "AI assistant (targets)"
    assert c.writes == [(FC, 52.0, 62.0, by), (P1, 50.0, 60.0, by), (THR, 45.0, 54.0, by), (RESCUE, 30.0, 25.0, by)]
    assert all(reason == f"because {k}" and expected == "the zone reaches 58 tomorrow" for k, reason, expected in
               c.claims)
    [(event, _zone, (words, why))] = c.events
    assert event == "jev_setpoint" and "p3 emergency vwc threshold 30 -> 25" in words and "58 tomorrow" in why
    [change] = jev_bridge._ai(c, room, 1)["changes"]
    assert change["values"][P1] == [50.0, 60.0] and change["expected"] == "the zone reaches 58 tomorrow"
    assert jev_bridge.targets_view(c, room, 1, _params(), NIGHT + timedelta(minutes=5))["changed_today"]


def test_lowering_writes_from_the_bottom_and_a_refused_write_is_taken_after_the_others(tmp_path):
    c, room = _Controller(tmp_path, refuse={THR}), _room()
    view = jev_bridge.targets_view(c, room, 1, _params(), NIGHT)
    d, ctx = _decide({FC: 48.0, P1: 46.0, THR: 41.0}, view=view)
    jev_bridge.apply_values(c, room, 1, d, ctx, NIGHT)
    assert [w[0] for w in c.writes] == [P1, FC, THR]  # the threshold, refused first, went in after the others


def test_a_value_outside_its_own_range_is_clamped_to_it_and_the_clamp_is_logged(tmp_path):
    c, room = _Controller(tmp_path, ranges={P1: (20.0, 55.0)}), _room()
    view = jev_bridge.targets_view(c, room, 1, _params(), NIGHT)
    d, ctx = _decide({P1: 70.0}, view=view)
    jev_bridge.apply_values(c, room, 1, d, ctx, NIGHT)
    assert c.writes == [(P1, 50.0, 55.0, "AI assistant (targets)")]
    assert "asked 70, clamped to its range" in c.claims[0][1]
    note = next(e for e in c.jev.journal.recent("default") if e["verdict"] == "clamped")
    assert note["action"] == "p1 target vwc 70 -> 55"


def test_a_write_that_does_not_land_is_sent_again_then_recorded_as_failed(tmp_path):
    c, room = _Controller(tmp_path), _room()
    view = jev_bridge.targets_view(c, room, 1, _params(), NIGHT)
    d, ctx = _decide({P1: 51.0}, view=view)
    jev_bridge.apply_values(c, room, 1, d, ctx, NIGHT)
    c.numbers[P1] = 50.0  # Home Assistant keeps showing the old value
    for minutes in (5, 15, 35, 80):
        jev_bridge.ai_readback(c, room, 1, NIGHT + timedelta(minutes=minutes))
        c.numbers[P1] = 50.0
    jev_bridge.ai_readback(c, room, 1, NIGHT + timedelta(hours=3))
    assert len(c.writes) > 1 and jev_bridge._ai(c, room, 1)["pending"] == []
    assert any(e["verdict"] == "write failed" for e in c.jev.journal.recent("default"))


def test_dry_run_only_reports_what_it_would_set(tmp_path):
    asker = Asker("a", "t", transport=K.FakeTransport({"targets__v0": _values_answer({P1: 58.0})}), threaded=False,
                  clock=lambda: NIGHT.timestamp())
    brain = Brain(asker, Ledger(None), [tg.TargetsJudge()], log=lambda *a: None, dry_run=True)
    brain.journal = Journal(None)
    ctx = K.ctx("P3", s=K.snap(phase="P3", lights_on=False), now=NIGHT, lights_on=False, hours_to_on=11.0,
                hours_to_off=23.0, targets=_view(), powers={"set_targets_from_achievable": True})
    assert brain.tick(ctx) == []
    assert brain.journal.recent("default")[0]["result"] == "would act"
    brain.dry_run = False
    brain.state.clear()
    [(d, _why)] = brain.tick(ctx)
    assert d.kind == "targets" and d.value["values"] == {P1: 58.0}


def test_the_brain_sensor_publishes_the_powers(tmp_path):
    c, room = _Controller(tmp_path, powers={"ec_mode": False}), _room()
    out = jev_bridge.powers_published(c, room, NIGHT)
    rows = {r["key"]: (r["on"], r["default"]) for r in out["powers"]}
    assert rows["ec_mode"] == (False, True) and rows["tune_shot_sizes"] == (True, False)
    assert "ec_mode" not in out["powers_active"] and "advance_phase" in out["powers_active"]


# ------------------------------------------------------------------ inside the real controller
KILL = "input_boolean.kill"
NOON = datetime(2026, 9, 27, 13, 0)


def _states(**extra):
    return {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: ("on", {}), "switch.crop_steering_room_active": ("on", {}),
        "switch.crop_steering_zone_1_enabled": ("on", {}),
        "sensor.crop_steering_vwc_zone_1": ("40.5", {"unit_of_measurement": "%"}),
        "sensor.crop_steering_ec_zone_1": ("6.5", {"unit_of_measurement": "mS/cm"}),
        "number.crop_steering_p1_target_vwc": ("40", {}), "number.crop_steering_field_capacity": ("42", {}),
        "number.crop_steering_p2_vwc_threshold": ("33", {}),
        "number.crop_steering_lights_on_hour": ("10", {}), "number.crop_steering_lights_off_hour": ("22", {}),
        **extra,
    }


@pytest.fixture
def brain_with(monkeypatch):
    def make(answers, states, now=NOON, haiku=False):
        import brain_kit as B
        from jev import client as jc

        transport = K.FakeTransport(answers)
        monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: transport)
        monkeypatch.setattr(jev_bridge, "Asker", functools.partial(Asker, threaded=False, clock=lambda: now.timestamp()))
        monkeypatch.setattr(jc, "anthropic", B.FakeSDK(B.FakeClient()))
        opts = {"num_zones": 1, "enable_flag": KILL, "brain_provider": "claude_haiku", "anthropic_api_key": B.SENTINEL}
        c, fake = _build(opts, states=states)
        return c, fake
    return make


def _ramp(c):
    st = c.rooms[0].state[1]
    st.update(phase="P1", shots=3, last_shot=NOON - timedelta(minutes=20),
              last_phase_change=NOON - timedelta(minutes=70), last_daily_reset=NOON.date())


HANDOVER = K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8, "real_salt": 0.2}))


def test_a_missing_switch_keeps_todays_behaviour_and_the_powers_are_published(brain_with):
    c, fake = brain_with(HANDOVER, _states())
    _ramp(c)
    c.loop_once(NOON)
    assert c.rooms[0].state[1]["phase"] == "P2"  # ramp_control's default: on
    room = fake.sets["sensor.crop_steering_jev"][1]
    assert [r["key"] for r in room["powers"]] == [k for k, _d, _w in pw.POWERS]
    assert set(room["powers_active"]) == {k for k, on in pw.DEFAULTS.items() if on}
    assert "ramp" in room["judges_acting"]


def test_switching_a_power_off_stops_it_acting_and_its_judge_advises(brain_with):
    c, fake = brain_with(HANDOVER, _states(**{"switch.crop_steering_ai_power_ramp_control": ("off", {})}))
    _ramp(c)
    c.loop_once(NOON)
    assert c.rooms[0].state[1]["phase"] == "P1"  # the base engine: at the ceiling, but EC holds P1
    shown = fake.sets["sensor.crop_steering_zone_1_jev"][1]["judges"]["ramp"]
    assert shown["why"].startswith("refused") and shown["why"].endswith("advice only")
    entry = c.jev.journal.recent("default")[0]
    assert entry["judge"] == "ramp" and entry["result"] == "refused"
    room = fake.sets["sensor.crop_steering_jev"][1]
    assert "ramp" not in room["judges_acting"] and "ramp_control" not in room["powers_active"]


def test_with_the_targets_power_on_the_learner_leaves_the_ladder_to_the_ai(brain_with):
    numbers = {f"number.crop_steering_zone_1_{s}": (str(v), {"min": 10, "max": 100}) for s, v in LADDER.items()}
    states = _states(**numbers, **{"switch.crop_steering_auto_setpoints": ("on", {}),
                                   "switch.crop_steering_ai_power_set_targets_from_achievable": ("on", {})})
    c, fake = brain_with({}, states, now=NIGHT, haiku=True)
    room = c.rooms[0]
    assert jev_bridge.targets_owned(c, room)
    st = room.state[1]
    st["peak_prev"], st["fc_follow"]["peak"] = 58.0, 58.0  # the follower would raise field capacity...
    c._auto_tick(room, 1, SimpleNamespace(vwc=50.0, ec=5.0, dryback_rate=0.0, backed_up=False),
                 SimpleNamespace(p1_target=50.0, field_capacity=52.0, p3_emergency_floor=30.0, p2_shot_size=5.0,
                                 dryback_target=12.0, p0_max_wait_min=60.0, p1_initial=3.0,
                                 p1_time_between_min=20.0, ec_target_p1=4.5, ec_target_p2=5.5), False, NIGHT)
    writes = [d for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value")]
    assert writes == []  # ...but the AI owns the ladder: the learner writes none of it
    managed = fake.sets["sensor.crop_steering_zone_1_auto_setpoints"][1]["managed_by"]
    assert managed["number.crop_steering_zone_1_p1_target_vwc"] == "the AI assistant, with the owner's power"
    assert managed["number.crop_steering_zone_1_p3_emergency_vwc_threshold"] == "the AI assistant, with the owner's power"
