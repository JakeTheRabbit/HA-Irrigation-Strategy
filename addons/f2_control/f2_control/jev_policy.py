"""Jev (TypeSafe System One) as the JUDGE behind the setpoint supervisor, via Cloudflare's AI REST API.

Jev never fires a shot and never writes a number. It reads a pre-digested situation
(setpoint_supervisor.evidence) and answers typed questions; verdicts() turns the answers into small,
bounded nudges that the supervisor applies to the zone's setpoints:

  ec_steer    which way pore EC should be pushed  -> P2 shot size up (flush) or down (stack)
  peak_fit    does the peak target fit the ramp   -> peak target down / keep / up
  guards      is the probe believable, is water landing -> freeze every setpoint if not

Jev cannot do arithmetic and knows no crop-steering doctrine, so every comparison arrives already
made and each question carries its rule in words. Any failure returns None and the supervisor's
arithmetic carries on alone: nothing ever waits on a cloud API.
"""
import requests

URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run"
MODEL = "typesafe/jev"

# ---- the tuning surface ----
MIN_CONFIDENCE = 0.7  # below this a verdict is ignored
GUARD_VETO = 0.5  # delivery_failure / runaway >= this, or probe_trust <= 1 - this, freezes the setpoints
EC_STEP = {0: 1.0, 1: 0.5, 2: 0.0, 3: -0.5, 4: -1.0}  # P2 shot size change, in % of substrate
PEAK_STEP = {"lower_peak": -0.5, "keep": 0.0, "raise_peak": 0.5}  # VWC points

QUESTIONS = {
    "ec_steer": {
        "type": "score",
        "instructions": "Which way should pore EC be steered? Doctrine: bigger maintenance shots force "
        "runoff, and runoff pulls pore EC towards the feed EC; smaller shots and deeper drybacks let pore "
        "EC stack up. Keep pore EC inside the stage range.",
        "criteria": [
            "Pore EC is far above the stage range: flush hard",
            "Pore EC is above the range, or inside it and climbing towards the top: flush a little",
            "Pore EC is inside the range and steady: hold",
            "Pore EC is below the range, or inside it and sinking towards the bottom: stack a little",
            "Pore EC is far below the stage range: stack hard",
        ],
    },
    "peak_fit": {
        "type": "choice",
        "instructions": "Does the peak VWC target fit what the morning ramp is showing?",
        "criteria": {
            "lower_peak": "VWC stalls short of the peak target while the last shots respond weakly: the target is above what this substrate holds",
            "keep": "VWC reaches the peak target and settles there, or the ramp has not run yet today",
            "raise_peak": "VWC reaches the target easily and shots at the top still respond normally: the substrate can hold more",
            "insufficient_evidence": "The state does not support any of the other answers",
        },
    },
    "probe_trust": {
        "type": "noul",
        "instructions": "Is the VWC probe responding believably to irrigation shots? If no shots are listed, answer yes.",
    },
    "delivery_failure": {
        "type": "noul",
        "instructions": "Are shots being fired while VWC stays far below the peak target and does not respond, "
        "as if water is not reaching this probe?",
    },
}


def parse(payload):
    """Cloudflare wraps TypeSafe's body as result.result.answers. Anything else -> None."""
    try:
        answers = payload["result"]["result"]["answers"]
        return answers if isinstance(answers, dict) and answers else None
    except (KeyError, TypeError):
        return None


def call(account, token, state, gateway=None, timeout=5.0):
    """One Jev evaluation. Returns the answers dict, or None on ANY failure (fail open)."""
    headers = {"Authorization": f"Bearer {token}"}
    if gateway:
        headers["cf-aig-gateway-id"] = gateway
    body = {"model": MODEL, "input": {"state": state, "questions": QUESTIONS}}
    try:
        resp = requests.post(URL.format(account=account), json=body, headers=headers, timeout=timeout)
        return parse(resp.json()) if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def verdicts(answers, min_confidence=MIN_CONFIDENCE, veto=GUARD_VETO):
    """answers -> {"freeze": reason or None, "p2_shot_delta": %, "peak_delta": pts, "why": [...]}, or None."""
    if not answers:
        return None
    fail = (answers.get("delivery_failure") or {}).get("noul")
    trust = (answers.get("probe_trust") or {}).get("noul")
    if fail is not None and fail >= veto:
        return {"freeze": f"delivery failure {fail:.2f}", "p2_shot_delta": 0.0, "peak_delta": 0.0, "why": []}
    if trust is not None and trust <= 1.0 - veto:
        return {"freeze": f"probe trust {trust:.2f}", "p2_shot_delta": 0.0, "peak_delta": 0.0, "why": []}
    out = {"freeze": None, "p2_shot_delta": 0.0, "peak_delta": 0.0, "why": []}
    ec = answers.get("ec_steer") or {}
    if ec.get("score") is not None and (ec.get("confidence") or 0.0) >= min_confidence:
        level = int(round(ec["score"]))
        out["p2_shot_delta"] = EC_STEP.get(level, 0.0)
        out["why"].append(f"ec_steer level {level} ({ec['confidence']:.2f})")
    peak = answers.get("peak_fit") or {}
    if peak.get("choice") in PEAK_STEP and (peak.get("confidence") or 0.0) >= min_confidence:
        out["peak_delta"] = PEAK_STEP[peak["choice"]]
        out["why"].append(f"peak_fit {peak['choice']} ({peak['confidence']:.2f})")
    return out
