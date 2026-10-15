"""Shared helpers for the Jev tests: a zone context with history, and Jev answers as Cloudflare returns them."""
from __future__ import annotations

import dataclasses
import os
from datetime import datetime, timedelta

from crop_steering_engine import ZoneParams, ZoneSnapshot
from jev.context import Shot, ZoneContext, ZoneHistory

NOW = datetime(2026, 9, 27, 13, 0)


def has_run(state_path=None):
    """Make the test's /data one Jev has run in (jev_bridge.has_run): an empty ledger, a file only Jev writes."""
    data = os.path.dirname(state_path or os.environ["F2_STATE_PATH"])
    open(os.path.join(data, "jev_ledger.jsonl"), "a").close()
    return data


def params(**over):
    base = dict(
        p1_target=40.0, p2_threshold=33.0, p2_shot_size=5.0, p1_initial=3.0, p1_incr=0.4, p1_max_shots=8,
        p1_time_between_min=15.0, dryback_target=20.0, p0_max_wait_min=120.0, ec_target_p0=3.0,
        ec_target_p1=4.5, ec_target_p2=4.5, p3_emergency_floor=25.0, p3_emergency_shot=3.0,
        max_daily_volume=150.0, field_capacity=42.0, max_ec=9.0, stacking_on=True, p1_min_shots=2,
    )
    base.update(over)
    return ZoneParams(**base)


def snap(**over):
    base = dict(
        vwc=36.0, ec=4.4, phase="P2", peak_vwc=38.0, dryback_pct=5.0, dryback_rate=0.5, shot_count=4,
        phase_minutes=60.0, minutes_since_shot=30.0, daily_vol=40.0, ec_smooth=4.4, lights_on=True,
        lights_just_on=False, hours_to_lights_on=15.0, hours_to_lights_off=9.0, uptime_min=600.0,
        feed_ec=3.0, ec_settled=4.4,
    )
    base.update(over)
    return ZoneSnapshot(**base)


def history(points=(), shots=()):
    """points: [(minutes_before_NOW, vwc, ec)], shots: [(minutes_before_NOW, seconds, pre_vwc, pre_ec, kind)]."""
    h = ZoneHistory()
    for m, v, e in sorted(points, key=lambda x: -x[0]):
        h.add_reading(NOW - timedelta(minutes=m), v, e)
    for m, secs, pv, pe, kind in sorted(shots, key=lambda x: -x[0]):
        h.add_shot(Shot(NOW - timedelta(minutes=m), secs, secs * 0.05, kind, pv, pe))
    return h


_DEFAULT = object()


def ctx(phase="P2", s=_DEFAULT, p=None, h=None, now=NOW, **over):
    """A zone context; `s=None` is a zone with no usable probe."""
    s = snap(phase=phase) if s is _DEFAULT else s
    base = dict(room="default", prefix="", zone=1, title="Zone 1", now=now, phase=phase, snap=s,
                params=p or params(), history=h or history(), lights_on=True, hours_to_on=15.0,
                hours_to_off=s.hours_to_lights_off if s is not None else 9.0, feed_ec=3.0,
                probe_entity="sensor.row1_vwc")
    base.update(over)
    return ZoneContext(**base)


def choice_answer(label, probs=None, confidence=0.8):
    probs = probs or {label: confidence}
    return {"type": "choice", "choice": label, "confidence": confidence, "probabilities": probs}


def noul_answer(p):
    return {"type": "noul", "noul": p}


def score_answer(score, probs=None, confidence=0.8):
    return {"type": "score", "score": score, "confidence": confidence,
            "probabilities": probs or {str(int(round(score))): confidence}}


def both(name, answer, answer_b=None):
    """The two council phrasings of `name` answered with `answer` (and `answer_b` for the second)."""
    return {f"{name}__v0": answer, f"{name}__v1": answer_b if answer_b is not None else answer}


class FakeTransport:
    """Stands in for jev.client.call: returns `answers` (or an error) and records what was asked."""

    def __init__(self, answers=None, error=None):
        self.answers, self.error, self.calls = answers, error, []

    def __call__(self, account, token, state, questions, gateway=None, timeout=20.0):
        self.calls.append({"state": state, "questions": questions})
        if self.error:
            return None, None, self.error
        return dict(self.answers or {}), {"input_tokens": 900}, None


class ScriptedTransport(FakeTransport):
    """Answers each call with the next of `answers` in turn; the last one repeats."""

    def __init__(self, *answers):
        super().__init__(answers[0] if answers else None)
        self.script = list(answers)

    def __call__(self, account, token, state, questions, gateway=None, timeout=20.0):
        if self.script:
            self.answers = self.script.pop(0)
        return super().__call__(account, token, state, questions, gateway, timeout)



def replace(s, **over):
    return dataclasses.replace(s, **over)
