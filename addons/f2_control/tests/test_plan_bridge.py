"""The plan-day bridge: today's plan values, applied by the controller while a stale probe holds the plan's own day.

The brain only answers keep_yesterday; a firm "no" makes a catch_up directive from code's own values (the plan's
preview), the envelope admits it or not (test_plan_catch_up_envelope.py), and the controller merges it into the
plan's snapshot through the read path the engine already uses. The plan document, its revision and every number are
untouched. It ends when the plan applies the day itself, when anything about the plan changes, or at the next
lights-on, and a saved one for another day is dropped at load.
"""
import copy
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

import jev_kit as K
import plan_adherence as A
from strategy_runtime import merge_bridge
from test_blind_grace import _Clock, clock  # noqa: F401
from test_plan_task import EDITED, Rig, _choice  # noqa: F401
import brain_bridge
from test_plan_watch import DAY16, DAY17, _plan_cards, _publish_plan, _writes, make_room

pytestmark = pytest.mark.usefixtures("settings_built_in")


@pytest.fixture
def room(monkeypatch):
    return make_room(monkeypatch)


@pytest.fixture(autouse=True)
def healthy(monkeypatch):
    monkeypatch.setattr(brain_bridge, "room_health", lambda c, room, now: ("ok", None))


def _snap(revision=7, zones=None):
    return {"required": True, "error": None, "managed": {1, 2}, "revision": revision, "grow_day": "2026-10-01",
            "zones": zones or {1: {"status": "active", "parameters": dict(DAY17), "applied_day": "2026-10-01"},
                               2: {"status": "active", "parameters": dict(DAY16), "applied_day": "2026-09-30"}}}


def test_merge_bridge_is_pure_and_only_for_its_day_and_revision():
    snap = _snap()
    before = copy.deepcopy(snap)
    bridge = {"day": "2026-10-01", "revision": 7, "zones": {"2": dict(DAY17)}}
    merged = merge_bridge(snap, bridge, "2026-10-01")
    assert snap == before
    assert merged["zones"][2]["parameters"] == DAY17 and merged["zones"][2]["applied_day"] == "2026-10-01"
    assert merged["bridged"] == "2026-10-01" and merged["zones"][1] == snap["zones"][1]
    assert merge_bridge(snap, bridge, "2026-10-02") is snap
    assert merge_bridge(_snap(revision=8), bridge, "2026-10-01")["zones"][2]["parameters"] == DAY16
    assert merge_bridge({**snap, "error": "held"}, bridge, "2026-10-01")["zones"] == snap["zones"]


# ---------------------------------------------------------------- the controller's side of a bridge
def _bridge(c, day=None, revision=7):
    c.rooms[0]._adherence["bridge"] = {"day": day or _Clock.now().date().isoformat(), "revision": revision,
                                       "zones": {"1": dict(DAY17)}, "since": "2026-09-25T14:00", "checked": False}
    c.rooms[0]._adherence["bridge_day"] = day or _Clock.now().date().isoformat()


def test_a_bridge_is_read_back_and_used_until_the_plan_applies_the_day_itself(room):
    c, fake, _calls = room
    _bridge(c)
    c.loop_once(_Clock.now())
    r = c.rooms[0]
    assert r.strategy_snapshot["bridged"] == _Clock.now().date().isoformat()
    assert c._zone_num(r, 1, "p2_vwc_threshold", 0) == DAY17["p2_vwc_threshold"]  # the engine's own read path
    assert r._adherence["bridge"]["checked"] is True
    beat = fake.sets["sensor.crop_steering_ai_heartbeat"][1]
    assert beat["plan_bridged"] is True and beat["plan_day_in_force"] == _Clock.now().date().isoformat()
    assert _writes(fake) == []  # nothing written: the plan's numbers stay as they are
    assert fake.sets["sensor.crop_steering_jev"][1]["plan"]["headline"].startswith(
        "Plan: day 2026-09-25's targets applied by the controller at 14:00")
    # The plan applies the day itself: the bridge ends, with no tripwire, and the plan's own values are in force.
    _Clock.current += timedelta(minutes=1)
    _publish_plan(fake, held=False)
    c.loop_once(_Clock.now())
    assert r._adherence["bridge"] is None and "bridged" not in r.strategy_snapshot
    assert r._adherence["bridge_outcome"] == _Clock.now().date().isoformat()
    assert not [d for d in _plan_cards(fake) if "differ" in d["notification_id"]]
    assert fake.sets["sensor.crop_steering_ai_heartbeat"][1]["plan_bridged"] is False


@pytest.mark.parametrize("change", ["yesterday", "revision", "not_stale"])
def test_a_bridge_ends_when_its_day_or_the_plan_changes(room, change):
    c, fake, _calls = room
    if change == "yesterday":
        _bridge(c, day=(_Clock.now().date() - timedelta(days=1)).isoformat())
    elif change == "revision":
        _bridge(c, revision=6)
    else:
        _bridge(c)
        state, attrs, _ = fake.ha_get("sensor.crop_steering_strategy_plan")
        fake.set_state("sensor.crop_steering_strategy_plan", state, {**attrs, "degraded_kind": "heartbeat"})
    c.loop_once(_Clock.now())
    r = c.rooms[0]
    assert r._adherence["bridge"] is None and "bridged" not in r.strategy_snapshot
    assert c._zone_num(r, 1, "p2_vwc_threshold", 0) == DAY16["p2_vwc_threshold"]


def test_a_bridge_survives_a_restart_and_still_counts_once_a_photoperiod(room, tmp_path):
    c, fake, _calls = room
    _bridge(c)
    c.loop_once(_Clock.now())
    saved = json.loads(open(c._state_path, encoding="utf-8").read())["default"]["_adherence"]
    assert saved["bridge"]["day"] == saved["bridge_day"] == _Clock.now().date().isoformat()
    c._load_state()
    assert c.rooms[0]._adherence["bridge_day"] == _Clock.now().date().isoformat()


# ---------------------------------------------------------------- the brain's side: keep_yesterday
HELD_ATTRS = {"revision": 7, "grow_day": "2026-10-01", "degraded_kind": "probe_stale",
              "degraded_reason": "Zone 2 VWC is unavailable or stale",
              "zones": [{"zone_id": 1, "day": 17, "status": "active", "profile_id": "finish", "bias": 70,
                         "parameters": DAY17, "applied_day": "2026-10-01"},
                        {"zone_id": 2, "day": 16, "status": "active", "profile_id": "bulk", "bias": 70,
                         "parameters": DAY16, "applied_day": "2026-09-30", "held": "Zone 2 VWC is stale"}]}


def _held_view(minutes):
    from test_plan_adherence import NOW, _row, view
    return view(attrs=HELD_ATTRS, now=NOW + timedelta(minutes=minutes),
                preview={"today": {z: {**_row(z, params=DAY17), "errors": []} for z in (1, 2)}})


class BridgeRig(Rig):
    def __init__(self, answers, dry=False):
        super().__init__(answers)
        self.jev.dry_run, self.jev.log = dry, lambda *a: None
        self._busy, self.saved, self.cards = False, 0, []
        self.room.zones = {1: {}, 2: {}}
        self.room.strategy_snapshot = {"required": True, "error": None, "managed": {1, 2}}
        self.adh = self.room._adherence

    def _room_active(self, room):
        return True

    def _dosing_hold(self, room):
        return None

    def _save_state(self):
        self.saved += 1

    def _jev_alert(self, room, zone, judge, alert):
        self.cards.append(alert)
        return True


def _keep(p_yes_a, p_yes_b=None):
    return {**K.both("cause", _choice("reading_holds_plan")),
            **K.both("keep_yesterday", {"type": "noul", "noul": p_yes_a, "confidence": 0.8},
                     {"type": "noul", "noul": p_yes_a if p_yes_b is None else p_yes_b, "confidence": 0.8})}


def _run(rig, minutes):
    for m in minutes:
        out = rig.run(_held_view(m))
    return out


def test_a_firm_no_bridges_the_held_zone_with_the_plans_own_values():
    rig = BridgeRig([_keep(0.1)])
    notes = _run(rig, (0, 31, 41, 42))
    [call] = rig.transport.calls
    assert {"keep_yesterday__v0", "keep_yesterday__v1"} <= set(call["questions"])
    assert "why_not_moved_on" in call["state"] and "change_today" in call["state"]
    assert rig.adh["bridge"]["zones"] == {"2": DAY17} and rig.adh["bridge"]["revision"] == 7
    assert rig.adh["bridge_day"] == "2026-10-01" and rig.cards[0]["code"] == "CS-713"
    assert notes["transition_missed"][2] == "acted"
    assert rig.jev.ledger.entries[-1]["action"] == "catch_up"


@pytest.mark.parametrize("answer", [_keep(0.9), _keep(0.1, 0.6), _keep(0.4)])
def test_anything_but_a_firm_no_keeps_yesterdays_targets(answer):
    rig = BridgeRig([answer])
    _run(rig, (0, 31, 41, 42))
    assert rig.adh["bridge"] is None and rig.cards == []


def test_dry_run_says_it_would_act_and_changes_nothing():
    rig = BridgeRig([_keep(0.1)], dry=True)
    notes = _run(rig, (0, 31, 41, 42))
    assert rig.adh["bridge"] is None and notes["transition_missed"][2] == "would act"


def test_only_once_a_photoperiod_and_never_while_cooling_down():
    rig = BridgeRig([_keep(0.1)])
    rig.adh["bridge_day"] = "2026-10-01"
    _run(rig, (0, 31, 41, 42))
    assert "keep_yesterday__v0" not in rig.transport.calls[0]["questions"]
    rig = BridgeRig([_keep(0.1)])
    rig.adh["cooldown_until"] = "2026-10-05T00:00"
    _run(rig, (0, 31, 41, 42))
    assert rig.adh["bridge"] is None


def test_the_envelope_refuses_it_during_a_shot_and_it_runs_out():
    rig = BridgeRig([_keep(0.1)])
    rig._busy = True
    _run(rig, (0, 31, 41, 42, 100))
    assert rig.adh["bridge"] is None
    assert any(e.get("result") == "refused" for e in rig.jev.journal.entries)


def test_a_rules_room_bridges_nothing():
    rig = BridgeRig([_keep(0.1)])
    rig.jev.status = SimpleNamespace(provider="rules")
    assert _run(rig, (0, 31, 41, 42)) is None
    assert rig.transport.calls == [] and rig.adh["bridge"] is None
    assert A.panel(_held_view(42), A.detect(_held_view(42), A.fresh()))["drifts"][0]["action"] == "advise"
