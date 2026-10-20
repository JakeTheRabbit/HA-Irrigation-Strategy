"""Stand-ins for the Anthropic SDK in the lean harness (it has no SDK, and no test reaches the network): a client whose
messages.create() answers from a script, the SDK's error shapes, and tool-call answers as the API returns them."""
from __future__ import annotations

from types import SimpleNamespace

SENTINEL = "sk-ant-SENTINEL-0123456789abcdef"


class APIStatusError(Exception):
    def __init__(self, status_code, message="", retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})


class AuthenticationError(APIStatusError):
    def __init__(self, message=""):
        super().__init__(401, message)


class RateLimitError(APIStatusError):
    def __init__(self, message="", retry_after=None):
        super().__init__(429, message, retry_after)


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


def usage(uncached=800, w5m=1500, w1h=0, read=35450, out=345):
    return SimpleNamespace(input_tokens=uncached, cache_creation_input_tokens=w5m + w1h, cache_read_input_tokens=read,
                           output_tokens=out,
                           cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=w5m, ephemeral_1h_input_tokens=w1h))


def tool(name, **args):
    return SimpleNamespace(type="tool_use", name=name, input=args)


def choice(snap, qid, pick, probs, confidence=0.8, rationale="the probe says so"):
    return tool("answer_choice", snapshot_id=snap, question_id=qid, choice=pick,
                probabilities=[{"key": k, "p": p} for k, p in probs.items()], confidence=confidence,
                rationale=rationale)


def yes_no(snap, qid, p, confidence=0.8, rationale="it tracks"):
    return tool("answer_yes_no", snapshot_id=snap, question_id=qid, p_yes=p, confidence=confidence,
                rationale=rationale)


def message(*blocks, stop="tool_use", category=None, use=None):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=use or usage(),
                           stop_details=SimpleNamespace(category=category) if stop == "refusal" else None)


class FakeClient:
    """`script` items are messages, exceptions to raise, or callables(request) -> either; the last one repeats."""

    def __init__(self, *script):
        self.script, self.requests = list(script), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if callable(item) and not isinstance(item, type):
            item = item(request)
        if isinstance(item, BaseException):
            raise item
        return item


class FakePrompt:
    """The shape brain.prompt.Prompt has, with a fixed snapshot id."""

    snap = "default:z1:dusk:2026-09-27T13:00:abcd"

    def evidence(self, state):
        return self.snap, "<snapshot>evidence</snapshot>"

    def questions(self, snap_id, lane_index, lane):
        return f"<questions lane={lane_index}>{sorted(lane)}</questions>"

    def request(self, model, evidence, questions, max_tokens):
        return {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": [
            {"type": "text", "text": evidence}, {"type": "text", "text": questions}]}]}

    def max_tokens(self, lane):
        return 2048


DUSK = {"enter_p3_now": "stop", "continue_p2": "carry on", "insufficient_evidence": "unknown"}
QUESTIONS = {"dusk_call__v0": {"type": "choice", "instructions": "stop now?", "criteria": DUSK},
             "dusk_call__v1": {"type": "choice", "instructions": "should it stop?", "criteria": DUSK}}
STATE = {"phase": "P2", "_brain": {"room": "default", "zone": 1, "judge": "dusk", "asked": "2026-09-27T13:00"}}
GOOD = {"enter_p3_now": 0.7, "continue_p2": 0.2, "insufficient_evidence": 0.1}


def answering(prompt=None):
    """A request callable that answers the lane's own question id with GOOD."""
    snap = (prompt or FakePrompt()).snap

    def answer(request):
        text = request["messages"][0]["content"][1]["text"]
        qid = "dusk_call__v1" if "lane=1" in text else "dusk_call__v0"
        return message(choice(snap, qid, "enter_p3_now", GOOD))
    return answer


FUSED_PROBE = "sensor.crop_steering_vwc_zone_1"  # what controller._fused_id gives the probe judge's context


def scenarios(**over):
    """[(judge, ctx)]: every built judge with a context it can build evidence from, the probe's real fused id and a
    flower day on the default arc."""
    import brain_bridge
    import jev_kit as K
    from brain.doctrine import stage_intent

    points = [(m, 38.0 - m * 0.01, 4.4) for m in range(0, 180, 5)]
    shots = [(40, 30.0, 36.5, 4.3, "p2"), (100, 30.0, 36.0, 4.3, "p2")]
    out = []
    for judge in brain_bridge.judges():
        phase = judge.phases[0]
        base = dict(flower_day=10, stage=stage_intent(10), steering="generative", probe_entity=FUSED_PROBE,
                    h=K.history(points, shots), plants=4,
                    siblings={2: {"litres_per_plant": 2.5, "litres_per_plant_words": "2500 mL a plant today"},
                              3: {"litres_per_plant": 2.2, "litres_per_plant_words": "2200 mL a plant today"}})
        base.update(over)
        out.append((judge, K.ctx(phase, **base)))
    return out


def judging(picks=None, p_yes=0.5, sure=0.9):
    """A request callable that answers every question in the lane: a choice question with `picks[<name>]` (else
    insufficient_evidence when it is allowed, else its first key), a yes/no question with `p_yes`."""
    import re

    picks = picks or {}

    def answer(request):
        text = request["messages"][0]["content"][1]["text"]
        snap = re.search(r'snapshot_id="([^"]+)"', text).group(1)
        blocks = []
        for qid, kind, body in re.findall(r'<question id="([^"]+)" kind="([^"]+)">(.*?)</question>', text, re.S):
            if kind == "yes_no":
                blocks.append(yes_no(snap, qid, p_yes))
                continue
            keys = re.findall(r"^- ([a-z_0-9]+):", body, re.M)
            name = qid.split("__v")[0]
            pick = picks.get(name) or ("insufficient_evidence" if "insufficient_evidence" in keys else keys[0])
            rest = (1.0 - sure) / max(1, len(keys) - 1)
            blocks.append(choice(snap, qid, pick, {k: (sure if k == pick else rest) for k in keys}))
        return message(*blocks)
    return answer


class FakeSDK:
    """Stands in for the anthropic module: Anthropic(**kw) hands back `client` and records how it was built."""

    def __init__(self, client):
        self.client, self.built = client, []

    def Anthropic(self, **kw):  # noqa: N802 - the SDK's own name
        self.built.append(kw)
        return self.client
