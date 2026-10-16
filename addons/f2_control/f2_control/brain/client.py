"""Asking the AI assistant (Claude, over the Anthropic API or an Anthropic-compatible router) without ever making the
loop wait.

`Asker.submit()` queues a question set and returns at once; a single background worker calls Claude and
stores the answers under the caller's key. The control loop only ever reads `Asker.result()`: an answer
from an earlier pass, or None. Every failure (no credentials, budget spent, timeout, HTTP error, an
envelope that doesn't parse, a question that waited too long) is recorded and yields no answer, so the
caller carries on as the base engine would. `Routes` tries its route, retrying a failure that may pass.
"""
from __future__ import annotations

import json
import math
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

from .scrub import scrub

try:
    import requests
except ImportError:  # the lean test harness stubs it; the add-on image installs it
    requests = None
try:
    import anthropic
except ImportError:  # armv7 images skip the SDK, and the lean test harness has none: the brain runs rules
    anthropic = None

NO_REQUESTS = "requests not installed"
NOT_JSON = "response is not JSON"
NO_ANSWERS = "no answers in the response"


# ---------- Claude over the Anthropic API (brain_provider: claude_haiku) ----------
API_URL = "https://api.anthropic.com"  # given explicitly: a stray ANTHROPIC_BASE_URL can never send the key elsewhere
DEFAULT_MODEL = "claude-haiku-5-5"
BAD_OUTPUT = "model answer failed validation"
REFUSED = "refused"
BUDGET = "budget spent"
NO_SDK = "anthropic not installed"
PAUSED = "brain paused"
NO_CONTEXT = "no brain context"
INTERNAL = "brain transport error"
LANE_TIMEOUT_S = 15.0
MAX_TEXT = 300  # a model's rationale, line or answer, as the journal keeps it
HA_STATE_MAX = 255  # a Home Assistant state's length limit (the report's headline is one)
LONG_PROMPT = 100_000  # Haiku's dearer rate card applies to a prompt above this many tokens
# US$ per million tokens: input, output, cache read, 5-minute and 1-hour cache writes. This is also the model
# allowlist: a model with no row is never called, so every call the Meter charges is priced at the row of the model
# that billed it, and no unknown model can be under-priced.
PRICES = {
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "read": 0.01, "w5m": 0.125, "w1h": 0.20,
                         "long": {"in": 0.50, "out": 2.50, "read": 0.05, "w5m": 0.625, "w1h": 1.00}},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "read": 0.20, "w5m": 2.50, "w1h": 4.00},
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "read": 0.20, "w5m": 5.00, "w1h": 8.00},
}
ERROR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error",
               404: "not_found_error", 413: "request_too_large", 422: "invalid_request_error",
               429: "rate_limit_error", 529: "overloaded_error"}
_KEY_RUN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_keys: set = set()
log = print  # brain_bridge.build() points this at the controller's log


def anthropic_key(options):
    """The anthropic_api_key option, stripped. Empty (the default) is no key."""
    return str(options.get("anthropic_api_key") or "").strip()


def anthropic_base_url(options):
    """The anthropic_base_url option, stripped, without a trailing slash. Empty (the default) is the Anthropic API."""
    return str(options.get("anthropic_base_url") or "").strip().rstrip("/")


def base_url_ok(url):
    """True for an http or https address with a host (and a valid port, if any)."""
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for a port that is not a number
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def show_url(url):
    """The address as the log shows it: scheme, host, port and path, never a user name or password."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}{f':{parts.port}' if parts.port else ''}{parts.path}"


def price_key(model, routed=False):
    """The PRICES row that `model` is billed at, or None. Through a router (`routed`), "<prefix>/<model>" is billed at
    the row of <model>."""
    if model in PRICES:
        return model
    prefix, _sep, name = str(model).rpartition("/")
    return name if routed and prefix and name in PRICES else None


def make_client(key, base_url=""):
    """The one client, or None without a key, or without the SDK for the API itself. The key and the address are
    given explicitly, so no environment variable can pick another credential or host, and the client never retries:
    Routes does. With `base_url` (a router), a RouterClient sends the requests there."""
    if not key or (anthropic is None and not base_url):
        return None
    _keys.add(key)
    if base_url:
        return RouterClient(key, base_url)
    return anthropic.Anthropic(api_key=key, base_url=API_URL, max_retries=0)


ANTHROPIC_VERSION = "2023-06-01"


class APITimeoutError(Exception):
    """The router did not answer in time (classify() reads the name, as for the SDK's own error)."""


class APIConnectionError(Exception):
    """The router could not be reached, or the connection dropped."""


class ConnectError(Exception):
    """The cause of an error raised before anything was sent: maybe_billed() reads the name, as for httpx's own."""


class APIStatusError(Exception):
    """The router answered with an HTTP error: classify() reads the status code and the retry-after header."""

    def __init__(self, status_code, response=None):
        super().__init__(f"HTTP {status_code}")
        self.status_code, self.response = status_code, response


def tool_name(name, offered):
    """A router's name for a tool call -> the request's own tool name. A router can add a suffix to the name
    ("answer_choice" comes back as "answer_choice_ide"): a name that starts with "<offered tool>_" is that tool
    (the longest that matches). Any other name stays as it is, so validate_answer() refuses it."""
    if not isinstance(name, str) or name in offered:
        return name
    found = [t for t in offered if isinstance(t, str) and name.startswith(t + "_")]
    return max(found, key=len) if found else name


class RouterClient:
    """The Messages API through an Anthropic-compatible router (anthropic_base_url), over requests. It has the SDK's
    messages.create() and its error shapes, so call_anthropic() and classify() use it as they use the SDK. A router
    can add a line after the JSON message ("data: [DONE]"), so the first JSON object of the body is the message; a
    body with no JSON object is a message with no answer, charged as an estimate."""

    def __init__(self, key, base_url, post=None):
        self.url = base_url.rstrip("/") + "/v1/messages"
        self._headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
                         "content-type": "application/json"}
        self._post = post
        self.messages = self

    def __repr__(self):
        return f"RouterClient({show_url(self.url)!r})"  # never the key

    def create(self, timeout=LANE_TIMEOUT_S, **request):
        post = self._post or (requests.post if requests is not None else None)
        if post is None:
            raise APIConnectionError(NO_REQUESTS)
        try:
            resp = post(self.url, json=request, headers=self._headers, timeout=timeout)
        except Exception as e:  # noqa: BLE001 - mapped to the SDK's shapes; classify() keeps only the name
            name, text = type(e).__name__, str(e)
            unsent = name == "ConnectTimeout" or "NewConnectionError" in text or "NameResolutionError" in text
            kind = APITimeoutError if "Timeout" in name else APIConnectionError
            raise kind(name) from (ConnectError(name) if unsent else e)
        if resp.status_code != 200:
            raise APIStatusError(resp.status_code, resp)
        try:
            body = json.JSONDecoder().raw_decode(resp.content.decode("utf-8", "replace").lstrip())[0]
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return SimpleNamespace(content=[], stop_reason=None, usage=estimate(request), stop_details=None)
        offered = {t.get("name") for t in request.get("tools") or () if isinstance(t, dict)}
        blocks = [SimpleNamespace(**{**b, "name": tool_name(b.get("name"), offered)} if b.get("type") == "tool_use"
                                  else b)
                  for b in body.get("content") or () if isinstance(b, dict)]
        details = body.get("stop_details")
        return SimpleNamespace(content=blocks, stop_reason=body.get("stop_reason"), usage=body.get("usage") or {},
                               stop_details=SimpleNamespace(**details) if isinstance(details, dict) else None)


def redact(text, key=None):
    """`text` with the key, any key make_client() was given and any `sk-ant-` run taken out."""
    text = str(text)
    for k in sorted(_keys | ({key} if key else set()), key=len, reverse=True):
        if len(k) >= 8:
            text = text.replace(k, "<key>")
    return _KEY_RUN.sub("<key>", text)


def _n(obj, name):
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def tokens(usage):
    """(uncached input, 5-minute cache write, 1-hour cache write, cache read, output) from an API usage block. With no
    split of the cache writes, all of them are priced at the 1-hour rate: the safe side."""
    split = usage.get("cache_creation") if isinstance(usage, dict) else getattr(usage, "cache_creation", None)
    if split is not None:
        w5m, w1h = _n(split, "ephemeral_5m_input_tokens"), _n(split, "ephemeral_1h_input_tokens")
    else:
        w5m, w1h = 0, _n(usage, "cache_creation_input_tokens")
    return (_n(usage, "input_tokens"), w5m, w1h, _n(usage, "cache_read_input_tokens"), _n(usage, "output_tokens"))


def cost(usage, model):
    """US$ for one response, at the price row of the model that billed it."""
    uncached, w5m, w1h, read, out = tokens(usage)
    row = PRICES[price_key(model, routed=True)]
    if uncached + w5m + w1h + read > LONG_PROMPT:
        row = row.get("long", row)
    return (uncached * row["in"] + w5m * row["w5m"] + w1h * row["w1h"] + read * row["read"]
            + out * row["out"]) / 1e6


class Meter:
    """The Claude brain's spend until the next lights-on, and every reason it may not ask now. The worker thread
    charges it while the control loop reads it, so every method takes its lock.

    A window opens at a lights-on, at least WINDOW_MIN_H after the last one opened (one reset a day with staggered
    rooms); a window opened at start closes at the first lights-on, and any window closes WINDOW_MAX_H after it
    opened (24 h light). `can_spend()` is the budget and the latches, checked before every call; `state()` adds a
    429/529 pause, which stops new asks once the routes stop retrying."""

    WINDOW_MIN_H = 20.0
    WINDOW_MAX_H = 24.0
    UNAVAILABLE_S = 3600.0
    DECLINE_AFTER = 3  # refusals in a row for one judge mark it declined

    def __init__(self, budget_usd, model=DEFAULT_MODEL, clock=time.time, warn_pct=80):
        self._lock = threading.Lock()
        self.budget, self.model, self.clock = max(0.0, float(budget_usd)), model, clock
        self.warn_pct = float(warn_pct)
        self.latched = None  # "auth_failed" or "model_invalid": no ask until the controller starts again
        self.paused_until = self.unavailable_until = None
        self._bad, self.runs, self.declined, self._events = 0, {}, set(), []
        self._open(clock(), "start")

    def _open(self, now, by):
        self.window_start, self.opened_by = now, by
        self.spent, self.calls, self.warned, self.spent_said = 0.0, 0, False, False
        self.tokens = {"uncached": 0, "cache_read": 0, "cache_write": 0, "output": 0}

    def _state(self, now):
        if now - self.window_start >= self.WINDOW_MAX_H * 3600.0:
            self._open(now, "timer")
        if self.latched:
            return self.latched
        if self.unavailable_until and now < self.unavailable_until:
            return "unavailable"
        if self.spent >= self.budget:
            return "budget_spent"
        if self.paused_until and now < self.paused_until:
            return "paused"
        return None

    def state(self):
        """None while the brain may ask, else why not: budget_spent, paused, unavailable, auth_failed or
        model_invalid."""
        with self._lock:
            return self._state(self.clock())

    def can_spend(self):
        """Another call may start: within budget and not latched (a pause only stops new asks)."""
        with self._lock:
            return self._state(self.clock()) in (None, "paused")

    def live(self):
        """The brain can act: may ask now, and the Setpoints judge has not declined."""
        with self._lock:
            return self._state(self.clock()) is None and "setpoints" not in self.declined

    def charge(self, usage, model=None):
        """Count one billed response -> its cost in US$."""
        uncached, w5m, w1h, read, out = tokens(usage)
        spent = cost(usage, model or self.model)
        with self._lock:
            self._state(self.clock())
            self.spent += spent
            self.calls += 1
            for k, v in (("uncached", uncached), ("cache_write", w5m + w1h), ("cache_read", read), ("output", out)):
                self.tokens[k] += v
            if not self.warned and self.budget > 0 and self.spent * 100.0 >= self.budget * self.warn_pct:
                self.warned = True
                self._events.append("warn")
            if not self.spent_said and self.spent >= self.budget:
                self.spent_said = True
                self._events.append("spent")
        return spent

    def latch(self, kind):
        with self._lock:
            if self.latched is None:
                self._events.append("brain")
            self.latched = kind

    def pause(self, seconds):
        with self._lock:
            self.paused_until = max(self.paused_until or 0.0, self.clock() + float(seconds))

    def bad_request(self):
        """Three refused requests in a row make the brain unavailable for an hour."""
        with self._lock:
            self._bad += 1
            if self._bad >= 3:
                self._bad, self.unavailable_until = 0, self.clock() + self.UNAVAILABLE_S
                self._events.append("brain")

    def good(self):
        with self._lock:
            self._bad = 0

    def refused(self, judge, category=None):
        with self._lock:
            self.runs[judge] = self.runs.get(judge, 0) + 1
            if self.runs[judge] >= self.DECLINE_AFTER:
                self.declined.add(judge)

    def answered(self, judge):
        with self._lock:
            self.runs[judge] = 0
            self.declined.discard(judge)

    def lights_on(self, now=None):
        """A room's lights came on -> True when that opened a new window."""
        with self._lock:
            now = self.clock() if now is None else now
            if self.opened_by == "start" or now - self.window_start >= self.WINDOW_MIN_H * 3600.0:
                self._open(now, "lights_on")
                return True
            return False

    def again(self, event):
        """Raise `event` again on a later pass (its card did not reach Home Assistant)."""
        with self._lock:
            self._events.append(event)

    def take(self, event):
        """True once for each "warn" (CS-706), "spent" (CS-708) and "brain" (CS-709) since it was last taken."""
        with self._lock:
            if event in self._events:
                self._events = [e for e in self._events if e != event]
                return True
            return False

    def snapshot(self):
        """Everything the usage file and the brain panel keep. Never the key."""
        with self._lock:
            state = self._state(self.clock())
            return {"window_start": self.window_start, "opened_by": self.opened_by, "cost_usd": round(self.spent, 6),
                    "budget_usd": self.budget, "calls": self.calls, "uncached_tokens": self.tokens["uncached"],
                    "cached_tokens": self.tokens["cache_read"], "cache_write_tokens": self.tokens["cache_write"],
                    "output_tokens": self.tokens["output"], "paused_until": self.paused_until,
                    "warned": self.warned, "spent_said": self.spent_said, "refusal_runs": dict(self.runs),
                    "declined": sorted(self.declined), "state": state, "model": self.model}

    def restore(self, saved):
        """Carry a window across a restart when it is under 30 h old; a latch is never carried (a restart, the usual
        result of a new key, tries once more)."""
        with self._lock:
            try:
                start = float(saved["window_start"])
            except (KeyError, TypeError, ValueError):
                return False
            if not 0 <= self.clock() - start < 30 * 3600.0:
                return False
            self._open(start, str(saved.get("opened_by") or "start"))
            self.spent = float(saved.get("cost_usd") or 0.0)
            self.calls = int(saved.get("calls") or 0)
            self.tokens = {"uncached": int(saved.get("uncached_tokens") or 0),
                           "cache_read": int(saved.get("cached_tokens") or 0),
                           "cache_write": int(saved.get("cache_write_tokens") or 0),
                           "output": int(saved.get("output_tokens") or 0)}
            self.warned, self.spent_said = bool(saved.get("warned")), bool(saved.get("spent_said"))
            self.paused_until = saved.get("paused_until") or None
            self.runs = {str(k): int(v) for k, v in (saved.get("refusal_runs") or {}).items()}
            self.declined = {j for j, n in self.runs.items() if n >= self.DECLINE_AFTER}
            return True


def _retry_after(e):
    try:
        return float(e.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None


def classify(e, meter=None):
    """A key-free error string for an exception from the SDK call, built from the status code and the API's error type
    only (never the message or a response body), and what it does to the Meter: a refused key latches auth_failed, an
    unknown model model_invalid, a 429 or 529 pauses it, three bad requests in a row make it unavailable for an
    hour."""
    status = getattr(e, "status_code", None)
    if isinstance(status, int):
        if meter is not None:
            if status in (401, 403):
                meter.latch("auth_failed")
            elif status == 404:
                meter.latch("model_invalid")
            elif status in (429, 529):
                meter.pause(_retry_after(e) or 60.0)
            elif status in (400, 413, 422):
                meter.bad_request()
        return f"HTTP {status}: {ERROR_TYPES.get(status, 'api_error')}"
    name = type(e).__name__
    if "Timeout" in name:
        return "APITimeoutError"
    if "Connection" in name:
        return "APIConnectionError"
    return name[:60]  # an unknown transport fault: worth another try


def maybe_billed(e):
    """An SDK error from a request the API may have taken and billed: no HTTP status came back (a timeout, a dropped
    connection, a reply that would not parse) and the connection was not refused before anything was sent."""
    if isinstance(getattr(e, "status_code", None), int):
        return False  # the API answered with an error, which is not billed
    return type(e.__cause__).__name__ not in ("ConnectError", "ConnectTimeout")


def estimate(request):
    """A usage block for a request whose reply was never read, on the dear side: one prompt token for every two
    characters sent, all at the 1-hour cache-write rate (the dearest prompt rate), and all of max_tokens as output."""
    return {"cache_creation_input_tokens": len(json.dumps(request, default=str)) // 2,
            "output_tokens": int(request.get("max_tokens") or 0)}


def _clean(text):
    """A model's text as the journal keeps it: one line, no control characters, no entity id or key, at most
    MAX_TEXT."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text))
    return redact(scrub(" ".join(text.split())))[:MAX_TEXT]


def _unit(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0.0 <= x <= 1.0


def validate_answer(block, snap_id, lane):
    """(question id, the council's answer) for one tool call that passes every check, or None: the right tool for the
    question's type, this lane's snapshot id and one of its question ids, a choice among that question's own keys and
    the arg-max of probabilities over those keys that sum to about 1, and every number between 0 and 1."""
    name, args = getattr(block, "name", None), getattr(block, "input", None)
    if not isinstance(args, dict) or args.get("snapshot_id") != snap_id:
        return None
    if name == "write_report":
        qid = next((q for q, v in lane.items() if isinstance(v, dict) and v.get("type") == "report"), None)
        return None if qid is None else _report(qid, args)
    if name == "answer_why":  # the why task's one question: no question id, no confidence
        qid = next((k for k, v in lane.items() if isinstance(v, dict) and v.get("type") == "why"), None)
        grounded = args.get("grounded_in")
        if qid is None or not isinstance(args.get("answer"), str) or not isinstance(args.get("cannot_answer"), bool):
            return None
        return qid, {"type": "why", "answer": _clean(args["answer"]), "cannot_answer": args["cannot_answer"],
                     "grounded_in": [_clean(g)[:80] for g in grounded if isinstance(g, str)][:10]
                     if isinstance(grounded, list) else []}
    qid = args.get("question_id")
    variant = lane.get(qid) if isinstance(qid, str) else None
    conf = args.get("confidence")
    if not isinstance(variant, dict) or not _unit(conf):
        return None
    why = _clean(args.get("rationale") or "")
    if variant.get("type") == "values" or name == "set_values":
        return _values(qid, variant, name, args, float(conf), why)
    if variant.get("type") == "noul" and name == "answer_yes_no":
        p = args.get("p_yes")
        return (qid, {"type": "noul", "noul": float(p), "confidence": float(conf), "rationale": why}) if _unit(p) else None
    if variant.get("type") != "choice" or name != "answer_choice" or not isinstance(args.get("probabilities"), list):
        return None
    keys, choice, probs = list(variant.get("criteria") or {}), args.get("choice"), {}
    for item in args["probabilities"]:
        k, p = (item.get("key"), item.get("p")) if isinstance(item, dict) else (None, None)
        if k not in keys or k in probs or not _unit(p):
            return None
        probs[k] = float(p)
    total = sum(probs.values())
    if choice not in keys or not 0.9 <= total <= 1.1:
        return None
    probs = {k: probs.get(k, 0.0) / total for k in keys}
    if probs[choice] < max(probs.values()) - 1e-9:
        return None  # an answer that contradicts its own probabilities is not a vote
    return qid, {"type": "choice", "choice": choice, "probabilities": probs, "confidence": float(conf),
                 "rationale": why}


def _values(qid, variant, name, args, conf, why):
    """(question id, the settings set) for a set_values call, or None: only that question's own settings, each a
    finite number with its reason; an empty list keeps every setting. The values are not limited here: the owner's
    power hands them to code as they are (code clamps each to its own range only)."""
    if variant.get("type") != "values" or name != "set_values" or not isinstance(args.get("values"), list):
        return None
    keys, got = set(variant.get("criteria") or {}), {}
    for item in args["values"]:
        k, v = (item.get("key"), item.get("value")) if isinstance(item, dict) else (None, None)
        if k not in keys or k in got or not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return None
        got[k] = {"value": float(v), "reason": _clean(item.get("reason") or "")}
    return qid, {"type": "values", "values": got, "expected": _clean(args.get("expected_outcome") or ""),
                 "confidence": conf, "rationale": why}


def _report(qid, args):
    """(question id, the report) for a write_report call, or None. Every string is cleaned like a rationale; the
    headline becomes a Home Assistant state, so it stays within HA_STATE_MAX characters; at most three watch items."""
    headline, zones, watch = args.get("headline"), args.get("zones"), args.get("watch")
    if not isinstance(headline, str) or not isinstance(zones, list) or not isinstance(watch, list):
        return None
    lines = [{"zone": z["zone"], "line": _clean(z["line"])} for z in zones
             if isinstance(z, dict) and isinstance(z.get("zone"), int) and not isinstance(z.get("zone"), bool)
             and isinstance(z.get("line"), str)]
    items = [_clean(w) for w in watch if isinstance(w, str)]
    return qid, {"type": "report", "headline": _clean(headline)[:HA_STATE_MAX], "zones": lines,
                 "watch": [w for w in items if w][:3]}


def split_lanes(questions):
    """{"<q>__v<i>": variant} -> {i: {"<q>__v<i>": variant}}: lane i carries every question's phrasing i, so each
    reader sees one wording. A key with no phrasing index (a room task) is lane 0."""
    lanes = {}
    for qid, variant in questions.items():
        _base, sep, idx = qid.rpartition("__v")
        lanes.setdefault(int(idx) if sep and idx.isdigit() else 0, {})[qid] = variant
    return lanes


def empty_usage(model):
    return {"input_tokens": 0, "uncached_input_tokens": 0, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_5m": 0, "cache_creation_1h": 0, "output_tokens": 0,
            "cost_usd": 0.0, "calls": 0, "model": model, "refusals": 0, "lanes_answered": 0}


def add_usage(total, usage, model):
    uncached, w5m, w1h, read, out = tokens(usage)
    total["input_tokens"] += uncached + w5m + w1h + read
    total["uncached_input_tokens"] += uncached
    total["cache_creation_input_tokens"] += w5m + w1h
    total["cache_creation_5m"] += w5m
    total["cache_creation_1h"] += w1h
    total["cache_read_input_tokens"] += read
    total["output_tokens"] += out
    total["cost_usd"] = round(total["cost_usd"] + cost(usage, model), 8)
    total["calls"] += 1


def call_anthropic(account, token, state, questions, gateway=None, timeout=20.0, *,
                   model=DEFAULT_MODEL, prompt=None, meter=None, client=None):
    """One brain evaluation over the Anthropic API -> (answers, usage, error). Never raises.

    `token` (the key) only ever built `client`; `account` and `gateway` are unused. `state` is the judge's evidence
    with the "_brain" key the enrichment hook added (none: NO_CONTEXT, nothing is sent). Lane i carries every
    question's phrasing i, one request each, the evidence block built once and cached between them. Every response
    is charged to the Meter before it is read, and a request that failed once it may have been sent is charged an
    estimate (estimate()), so a run of timeouts still spends the budget. One lane answering is an answer (the council sees one phrasing and
    counts it unsure); once any lane was billed, the error returned is never one Routes retries, so a call is never
    billed twice."""
    if client is None:
        return None, None, NO_SDK
    if not isinstance(state, dict) or "_brain" not in state:
        return None, None, NO_CONTEXT
    try:
        snap_id, evidence = prompt.evidence(state)
        judge = str(state["_brain"].get("judge") or "brain")
        answers, usage, errors, billed = {}, empty_usage(model), [], False
        for i, lane in sorted(split_lanes(questions).items()):
            if meter is not None and not meter.can_spend():
                errors.append(BUDGET)
                break
            request = prompt.request(model, evidence, prompt.questions(snap_id, i, lane), prompt.max_tokens(lane))
            try:
                msg = client.messages.create(**request, timeout=min(timeout, LANE_TIMEOUT_S))
            except Exception as e:  # noqa: BLE001 - classify() maps every SDK error to a key-free string
                if meter is not None and maybe_billed(e):
                    meter.charge(estimate(request), model)  # counted as billed, so retries stay inside the budget
                errors.append(redact(classify(e, meter), token))
                break
            billed = True
            if meter is not None:
                meter.charge(msg.usage, model)  # first, so no fault in the bookkeeping below leaves it uncounted
                meter.good()
            add_usage(usage, msg.usage, model)
            if msg.stop_reason == "refusal":
                usage["refusals"] += 1
                category = getattr(getattr(msg, "stop_details", None), "category", None)
                log(f"[brain] {judge}: the model declined to answer ({category})")
                if meter is not None:
                    meter.refused(judge, category)
                errors.append(REFUSED)
                continue
            got = {}
            for block in msg.content or ():
                found = validate_answer(block, snap_id, lane) if getattr(block, "type", None) == "tool_use" else None
                if found is not None and found[0] not in got:
                    got[found[0]] = found[1]
            answers.update(got)
            if got:
                usage["lanes_answered"] += 1
                if meter is not None:
                    meter.answered(judge)
            else:
                errors.append(BAD_OUTPUT)
        if billed:  # the cached system prompt at work: cache reads should climb from the second call on
            log(f"[brain] {judge}: cache read {usage['cache_read_input_tokens']} tokens, written "
                f"{usage['cache_creation_input_tokens']}, uncached {usage['uncached_input_tokens']}"
                + (f"; read today {meter.tokens['cache_read']}" if meter is not None else ""))
        if answers:
            return answers, usage, None
        if billed:
            return None, None, next((e for e in reversed(errors) if not retryable(e)), BAD_OUTPUT)
        return None, None, errors[-1] if errors else BAD_OUTPUT
    except Exception as e:  # noqa: BLE001 - the transport never raises; the name goes to the log, never back
        log(f"[brain] transport error: {type(e).__name__}")
        return None, None, INTERNAL


def retryable(error):
    """A rate limit, a server error or a network fault may pass, so it is worth another try. A refused key, a bad
    request or a reply that does not parse will not pass by waiting."""
    if error.startswith("HTTP "):
        code = error[5:8]
        return code == "429" or code.startswith("5")
    return not error.startswith((NO_REQUESTS, NOT_JSON, NO_ANSWERS, BAD_OUTPUT, REFUSED, BUDGET, NO_SDK, PAUSED,
                                 NO_CONTEXT, INTERNAL))


@dataclass
class Route:
    """One way to reach the AI assistant: `fn` is `call_anthropic` with its client, model, prompt and meter bound."""

    name: str
    fn: object
    account: str
    token: str = field(repr=False)
    gateway: str | None = None


class Routes:
    """The AI assistant's transport over every route it has to the same model, tried in order. A route gets `tries` tries while
    its failure may pass (retryable), 2 s and then 4 s apart, and no try starts that could end more than `window_s`
    after the route's first; any other failure moves straight on to the next route. It runs on the Asker's worker,
    so the control loop never waits for it. Its usage says which route answered, whether that was a failover, and
    how many retries it took."""

    def __init__(self, routes, tries=3, window_s=60.0, sleep=time.sleep, clock=time.monotonic):
        self.routes = list(routes)
        self.tries, self.window_s, self.sleep, self.clock = max(1, int(tries)), float(window_s), sleep, clock

    def __call__(self, account, token, state, questions, gateway=None, timeout=20.0):
        errors, retries = [], 0
        for i, r in enumerate(self.routes):
            start = self.clock()
            for attempt in range(self.tries):
                answers, usage, error = r.fn(r.account, r.token, state, questions, gateway=r.gateway, timeout=timeout)
                if error is None and answers:
                    return answers, {**(usage or {}), "route": r.name, "failover": i > 0, "retries": retries}, None
                error = error or NO_ANSWERS
                wait = 2.0 * 2 ** attempt
                if (attempt + 1 >= self.tries or not retryable(error)
                        or self.clock() - start + wait + timeout > self.window_s):
                    break
                self.sleep(wait)
                retries += 1
            errors.append(f"{r.name}: {error}")
        return None, None, "; ".join(errors)[:200]


@dataclass
class Answer:
    answers: dict
    at: float  # epoch seconds the question was asked: the answer is about the zone as it was then
    usage: dict = field(default_factory=dict)
    seq: int = 0  # unique per answer: two answers arriving in the same second are still two


class Asker:
    """Background AI assistant calls, keyed by the caller. `transport` is a `Routes` in the add-on and a fake in tests;
    `threaded=False` runs each submission at once (tests, and one-shot scripts). The day's calls stop at
    `daily_budget`, and take_warning() is true once a day when they reach `warn_pct` of it. A question that waited
    more than `max_wait_s` in the queue (behind calls that were failing) is dropped unasked: its evidence is stale."""

    def __init__(self, account, token, gateway=None, daily_budget=5000, transport=None,
                 threaded=True, clock=time.time, timeout=20.0, warn_pct=80, max_wait_s=300.0, meter=None):
        self.account, self.token, self.gateway, self.meter = account, token, gateway, meter
        self.daily_budget, self.transport, self.clock, self.timeout = daily_budget, transport, clock, timeout
        self.warn_pct, self.max_wait_s = warn_pct, max_wait_s
        self._warn = False
        self._results: dict[str, Answer] = {}
        self._pending: set[str] = set()
        self._seq = 0
        self._lock = threading.Lock()
        self.stats = {"day": None, "calls": 0, "errors": 0, "input_tokens": 0, "last_error": None,
                      "last_call": None, "retries": 0, "failovers": 0, "reasks": 0, "warned": False, "route": None}
        self._queue = None
        if threaded and self.enabled:
            self._queue = queue.Queue()
            threading.Thread(target=self._work, name="brain-asker", daemon=True).start()

    def __repr__(self):
        return f"Asker(account={self.account!r}, calls={self.stats.get('calls')})"

    @property
    def enabled(self):
        return bool(self.account and self.token)

    def _roll_day(self):
        day = datetime.fromtimestamp(self.clock()).date().isoformat()
        if self.stats["day"] != day:
            self.stats.update(day=day, calls=0, errors=0, input_tokens=0, retries=0, failovers=0, reasks=0,
                              warned=False)

    def submit(self, key, state, questions):
        """Queue one evaluation. False when the AI assistant is off, the day's budget is spent, or `key` is in flight."""
        if not self.enabled or (self.meter is not None and self.meter.state() is not None):
            return False  # off, or the Claude brain's budget, pause or latch says no new ask
        with self._lock:
            self._roll_day()
            if key in self._pending or self.stats["calls"] >= self.daily_budget:
                return False
            self._pending.add(key)
            self.stats["calls"] += 1
            if not self.stats["warned"] and self.stats["calls"] * 100 >= self.daily_budget * self.warn_pct:
                self.stats["warned"] = self._warn = True
        job = (key, state, questions, self.clock())
        if self._queue is None:
            self._run(job)
        else:
            self._queue.put(job)
        return True

    def note(self, stat):
        """Count one of today's events (e.g. "reasks") in the stats the AI assistant sensor shows."""
        with self._lock:
            self._roll_day()
            self.stats[stat] = self.stats.get(stat, 0) + 1

    def take_warning(self):
        """True once: the first time today's calls reach `warn_pct` of the budget (the controller pushes CS-706)."""
        with self._lock:
            warn, self._warn = self._warn, False
            return warn

    def _work(self):
        while True:
            job = self._queue.get()
            try:
                self._run(job)
            except Exception as e:  # noqa: BLE001 - the worker must outlive any one call
                self._fail(job[0], f"{type(e).__name__}: {e}")

    def _run(self, job):
        key, state, questions, asked = job
        waited = self.clock() - asked
        if waited > self.max_wait_s:
            self._fail(key, f"dropped unasked: it waited {waited:.0f} s in the queue")
            return
        if self.meter is not None and not self.meter.can_spend():
            self._fail(key, BUDGET)
            return
        answers, usage, error = self.transport(self.account, self.token, state, questions,
                                               gateway=self.gateway, timeout=self.timeout)
        if error or answers is None:
            self._fail(key, error or "no answers")
            return
        usage = usage or {}
        with self._lock:
            self._pending.discard(key)
            self._seq += 1
            self._results[key] = Answer(answers, asked, usage, self._seq)
            self.stats["input_tokens"] += int(usage.get("input_tokens") or 0)
            self.stats["retries"] += int(usage.get("retries") or 0)
            self.stats["failovers"] += 1 if usage.get("failover") else 0
            self.stats["route"] = usage.get("route") or self.stats["route"]
            self.stats["last_call"] = self.clock()

    def _fail(self, key, error):
        with self._lock:
            self._pending.discard(key)
            self.stats["errors"] += 1
            self.stats["last_error"] = redact(error, self.token)[:200]

    def result(self, key):
        """The latest answer for `key`, or None."""
        with self._lock:
            return self._results.get(key)

    def pending(self, key):
        with self._lock:
            return key in self._pending
