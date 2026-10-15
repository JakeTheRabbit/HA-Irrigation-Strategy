"""Asking each question twice, in two independent phrasings, and acting only when both agree.

Jev's confidence moves with how a question is worded (seen on the first F2 calls: the same state gave
0.84 and 0.72). A judge therefore writes every question as a list of variants; `expand()` sends them all
in one call, and `combine()` averages their calibrated probabilities and says whether they agreed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SEP = "__v"


def expand(questions):
    """{name: [variant, ...]} -> the flat question dict Jev takes: {name__v0: variant, ...}."""
    flat = {}
    for name, variants in questions.items():
        for i, variant in enumerate(variants):
            flat[f"{name}{SEP}{i}"] = variant
    return flat


@dataclass
class Verdict:
    name: str
    kind: str  # "choice" | "noul" | "score"
    label: object  # the choice key, True/False, or the rounded score level
    prob: float  # averaged probability of that label (for a score: its level's probability)
    confidence: float  # the lowest confidence any variant reported
    agreed: bool  # every variant came to the same label
    n: int  # how many variants answered
    value: float | None = None  # a score's averaged value
    probabilities: dict = field(default_factory=dict)
    labels: list = field(default_factory=list)  # each phrasing's own answer

    def firm(self, min_prob=0.6):
        """Both phrasings agree and the averaged probability of the answer is at least `min_prob`."""
        return self.agreed and self.n >= 2 and self.prob >= min_prob

    def firm_in(self, group, min_prob=0.6):
        """Every phrasing's answer is one of `group` (answers that lead to the same action) and their
        averaged probabilities add up to at least `min_prob`. "The slab is full" and "the EC left is the
        feed passing" both mean hand the ramp over: split between them, neither alone is firm."""
        group = {str(g) for g in group}
        return (self.n >= 2 and all(str(x) in group for x in self.labels)
                and sum(self.probabilities.get(g, 0.0) for g in group) >= min_prob)


def _variants(answers, name):
    out = []
    for key, ans in (answers or {}).items():
        base, _, idx = key.partition(SEP)
        if base == name and idx.isdigit() and isinstance(ans, dict):
            out.append(ans)
    return out


def combine(answers, name):
    """One Verdict for question `name` across its variants, or None when none answered usably."""
    vs = _variants(answers, name)
    if not vs:
        return None
    kind = vs[0].get("type") or ("noul" if "noul" in vs[0] else "choice" if "choice" in vs[0] else "score")
    try:
        if kind == "noul":
            ps = [float(v["noul"]) for v in vs]
            avg = sum(ps) / len(ps)
            label = avg >= 0.5
            agreed = all((p >= 0.5) == label for p in ps)
            prob = avg if label else 1.0 - avg
            conf = min(abs(p - 0.5) * 2.0 for p in ps)
            return Verdict(name, kind, label, round(prob, 3), round(conf, 3), agreed, len(vs),
                           probabilities={"true": round(avg, 3), "false": round(1 - avg, 3)},
                           labels=[p >= 0.5 for p in ps])
        probs = {}
        for v in vs:
            for k, p in (v.get("probabilities") or {}).items():
                probs[str(k)] = probs.get(str(k), 0.0) + float(p) / len(vs)
        conf = min(float(v.get("confidence") or 0.0) for v in vs)
        if kind == "choice":
            label = max(probs, key=probs.get) if probs else vs[0].get("choice")
            agreed = all(v.get("choice") == label for v in vs)
            return Verdict(name, kind, label, round(probs.get(label, 0.0), 3), round(conf, 3), agreed,
                           len(vs), probabilities={k: round(p, 3) for k, p in probs.items()},
                           labels=[v.get("choice") for v in vs])
        scores = [float(v["score"]) for v in vs]
        value = sum(scores) / len(scores)
        level = int(round(value))
        agreed = all(int(round(s)) == level for s in scores)
        return Verdict(name, "score", level, round(probs.get(str(level), 0.0), 3), round(conf, 3),
                       agreed, len(vs), value=round(value, 3),
                       probabilities={k: round(p, 3) for k, p in probs.items()},
                       labels=[int(round(x)) for x in scores])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
