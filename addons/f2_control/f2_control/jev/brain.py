"""Runs the judges for every zone on every pass, without waiting for any of them.

On each pass `tick()` asks the judges that are due (in the background), reads the answers that have
arrived, turns each NEW answer into a directive exactly once, puts the standing directive through the
envelope (the zone changes between passes, so admission is checked every pass), records what acted in
the ledger, and returns the admitted directives for the controller to apply. Nothing here raises into the
caller: a broken judge is skipped and logged in `errors`.

When Jev is unsure (an answer to a question the judge decides on, Judge.deciding, under `unsure_below`, two
phrasings that disagree, or one missing) and the answer did not act, the judge is asked again at once with more
evidence (Judge.more_evidence), up to `reask_max` times, before the engine decides alone. A second look re-checks
that answer only: it is dropped once the zone leaves the judge's phase or the answer is older than the judge's
`max_age_min`. After `strict_after` of a judge's calls in a row did not work out for a zone (Ledger.strict), the
judge is on the stricter gate there: an answer acts only when the same call came twice in a row, each answer
within `max_age_min` of the one before, with every deciding phrasing agreed at `strict_prob` or more. Jev keeps
judging throughout. The pass on which a run tips a judge onto the gate adds
an event, for the controller to push CS-707.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import council
from . import journal as jn
from .envelope import admit


@dataclass
class JudgeState:
    last_asked: datetime | None = None
    seen_seq: int | None = None  # the answer already read
    verdicts: dict = field(default_factory=dict)
    directive: object = None  # what that answer asks for (decided once, when it arrived)
    streak: int = 0
    streak_key: object = None
    acted_seq: int | None = None  # the answer the ledger last recorded an action for
    last: dict = field(default_factory=dict)  # what the zone's sensor shows
    reask_due: bool = False  # ask again at once, with more evidence
    reasks: int = 0  # second looks since the judge was last asked on its own cadence
    gate_run: int = 0  # answers in a row making the same sure call, each within max_age_min of the last
    answered_at: float | None = None  # when the latest answer's question was asked


def _label(d):
    """What a directive is filed under in the ledger: its phase or mode, an alert's code, or a setpoint move's
    choice (e.g. "smaller_shots")."""
    if isinstance(d.value, dict):
        return d.value.get("code") or d.value.get("choice")
    return d.value


class Brain:
    def __init__(self, asker, ledger, judges, allowed=None, log=print, reask_max=2, unsure_below=0.7,
                 strict_after=3, strict_prob=0.8):
        self.asker, self.ledger, self.log = asker, ledger, log
        self.judges = [j for j in judges if allowed is None or j.name in allowed]
        self.state: dict[tuple, JudgeState] = {}
        self.errors: dict[str, str] = {}
        self.triage = None
        self.journal = None  # jev.journal.Journal: every decision, for the dashboard's live log
        self.reask_max, self.unsure_below = reask_max, unsure_below
        self.strict_after, self.strict_prob = strict_after, strict_prob
        self.strict: dict[tuple, bool] = {}  # (room, zone, judge) -> on the stricter gate, as of its last pass
        self.events: list[tuple] = []  # ("strict", room, zone, judge): the bridge pushes CS-707 and empties it

    @property
    def enabled(self):
        return self.asker.enabled and bool(self.judges)

    def _st(self, ctx, judge):
        return self.state.setdefault((ctx.room, ctx.zone, judge.name), JudgeState())

    def tick(self, ctx, allowed=None):
        """Admitted directives for this zone on this pass: [(Directive, why)]."""
        out = []
        if not self.enabled:
            return out
        for judge in self.judges:
            if allowed is not None and judge.name not in allowed:
                continue
            try:
                d = self._judge(judge, ctx)
                if d is not None:
                    out.append(d)
            except Exception as e:  # noqa: BLE001 - one broken judge never stops the others or the loop
                self.errors[judge.name] = f"{type(e).__name__}: {e}"[:200]
        try:
            self._outcomes(ctx)
        except Exception as e:  # noqa: BLE001
            self.errors["outcomes"] = f"{type(e).__name__}: {e}"[:200]
        return out

    def _judge(self, judge, ctx):
        st = self._st(ctx, judge)
        key = f"{ctx.room}:{ctx.zone}:{judge.name}"
        strict = self.strict[(ctx.room, ctx.zone, judge.name)] = self.ledger.strict(
            judge.name, ctx.room, ctx.zone, after=self.strict_after)
        last = self.asker.result(key)
        if st.reask_due and (ctx.phase not in judge.phases or last is None
                             or self.asker.clock() - last.at > judge.max_age_min * 60.0):
            st.reask_due = False  # a second look re-checks one answer: not once the zone moved on or it aged out
        reask = st.reask_due and judge.due(ctx, None)  # a second look waits only for the judge's phase and probe
        if (reask or judge.due(ctx, st.last_asked)) and not self.asker.pending(key):
            ev = judge.evidence(ctx)
            record = self.ledger.track(judge.name, ctx.room, ctx.zone)
            if record:
                ev["your_track_record"] = record
            if reask:
                ev["second_look"] = judge.more_evidence(ctx, st.verdicts)
            if self.asker.submit(key, ev, council.expand(judge.questions)):
                st.last_asked = ctx.now
                st.reasks, st.reask_due = (st.reasks + 1 if reask else 0), False
                if reask:
                    self.asker.note("reasks")
        ans = self.asker.result(key)
        if ans is None:
            return None
        new = ans.seq != st.seen_seq
        if new:  # a new answer: decide on it once
            st.seen_seq = ans.seq
            st.verdicts = {q: council.combine(ans.answers, q) for q in judge.questions}
            st.directive = judge.decide(st.verdicts, ctx)
            k = None if st.directive is None else (st.directive.kind, str(_label(st.directive)))
            same = k is not None and k == st.streak_key
            st.streak = st.streak + 1 if same else (1 if k else 0)
            recent = st.answered_at is not None and ans.at - st.answered_at <= judge.max_age_min * 60.0
            sure = k is not None and self._sure(self._deciding(judge, st))
            st.gate_run = st.gate_run + 1 if (sure and same and recent) else (1 if sure else 0)
            st.streak_key, st.answered_at = k, ans.at
            st.reask_due = self._unsure(self._deciding(judge, st)) and st.reasks < self.reask_max
        d = st.directive
        if ctx.phase not in judge.phases:
            st.last = self._shown(st, None, "waiting for its phase")
            if new:
                self._note(ctx, judge, st, d, "waiting", "the zone has left the judge's phase")
            return None
        age = self.asker.clock() - ans.at
        if age > judge.max_age_min * 60.0:
            st.last = self._shown(st, None, "answer too old to act on")
            if new:
                self._note(ctx, judge, st, d, "waiting", "the answer came too late to act on")
            return None
        if d is None:
            st.last = self._shown(st, None, "no action")
            if new:
                self._note(ctx, judge, st, None, "no action", "")
            return None
        if strict and st.gate_run < 2:
            why = f"stricter gate: needs {self.strict_prob:g} and a second look that agrees"
            st.last = self._shown(st, d, f"refused: {why}")
            if new:
                self._note(ctx, judge, st, d, "refused", why)
                st.reask_due = st.reask_due or st.reasks < self.reask_max
            return None
        ok, why = admit(d, ctx, confirmed=st.streak, evidence_ok=judge.evidence_ok(ctx))
        st.last = self._shown(st, d, why if ok else f"refused: {why}")
        if not ok:
            if new:
                self._note(ctx, judge, st, d, "refused", why)
            return None
        if st.acted_seq != ans.seq:
            st.acted_seq = ans.seq
            st.reask_due = False  # an answer that acted is not asked again: one decision, one call in the ledger
            check_at = (ctx.now + timedelta(minutes=judge.outcome_after_min)
                        if judge.outcome_after_min else None)
            self.ledger.record(judge.name, ctx.room, ctx.zone, _label(d), d.kind,
                               evidence={q: (v.label if v else None) for q, v in st.verdicts.items()},
                               check_at=check_at, check=self._check_basis(ctx), at=ctx.now)
            self.log(f"[jev] {ctx.room} Z{ctx.zone} {judge.name}: {d.kind} {_label(d)} ({d.why}; {why})")
            self._note(ctx, judge, st, d, "acted", why)
        return d, why

    @staticmethod
    def _deciding(judge, st):
        """The verdicts the judge's decision rests on (Judge.deciding; every question when it names none)."""
        return [st.verdicts.get(q) for q in (judge.deciding or tuple(st.verdicts))]

    def _unsure(self, verdicts):
        """An answer under `unsure_below`, two phrasings that disagree, or a question one phrasing left unanswered."""
        return any(v is None or v.n < 2 or not v.agreed or v.prob < self.unsure_below for v in verdicts)

    def _sure(self, verdicts):
        """Every phrasing answered and agreed at `strict_prob` or more: sure enough for the stricter gate."""
        return all(v is not None and v.n >= 2 and v.agreed and v.prob >= self.strict_prob for v in verdicts)

    def _note(self, ctx, judge, st, d, result, reason):
        """One line in the journal (the dashboard's live log). Never raises into the pass."""
        if self.journal is None:
            return
        try:
            self.journal.add(jn.decision(ctx.room, ctx.zone, judge.name, ctx.now, st.verdicts, d, result, reason))
        except Exception as e:  # noqa: BLE001 - a log line is never worth a decision
            self.errors["journal"] = f"{type(e).__name__}: {e}"[:200]

    @staticmethod
    def _check_basis(ctx):
        s = ctx.snap
        if s is None:
            return {}
        ec = s.ec_settled if s.ec_settled is not None else s.ec
        return {"vwc": s.vwc, "ec": ec, "daily_vol": s.daily_vol, "phase": ctx.phase}

    def _outcomes(self, ctx):
        by_name = {j.name: j for j in self.judges}
        for entry in self.ledger.due(ctx.now):
            if entry["room"] != ctx.room or entry["zone"] != ctx.zone:
                continue
            judge = by_name.get(entry["judge"])
            result = judge.outcome(entry, ctx) if judge else ("judge no longer runs", False)
            if result is not None:
                was = self.ledger.strict(entry["judge"], ctx.room, ctx.zone, after=self.strict_after)
                self.ledger.resolve(entry["id"], result[0], result[1])
                if not was and self.ledger.strict(entry["judge"], ctx.room, ctx.zone, after=self.strict_after):
                    self.events.append(("strict", ctx.room, ctx.zone, entry["judge"]))
                if self.journal is not None:
                    self.journal.add(jn.outcome(ctx.room, ctx.zone, entry["judge"], ctx.now, entry["label"],
                                                result[0], result[1], of=entry.get("at"),
                                                action=entry.get("action")))

    @staticmethod
    def _shown(st, d, why):
        verdicts = {}
        for q, v in st.verdicts.items():
            if v is not None:
                verdicts[q] = {"answer": v.label, "p": v.prob, "agreed": v.agreed}
        return {"verdicts": verdicts, "directive": None if d is None else f"{d.kind} {_label(d)}",
                "why": why, "streak": st.streak}

    def zone_status(self, room, zone):
        """What the zone's Jev sensor shows: every judge's latest verdicts and what code did."""
        return {name: st.last for (r, z, name), st in self.state.items() if r == room and z == zone and st.last}
