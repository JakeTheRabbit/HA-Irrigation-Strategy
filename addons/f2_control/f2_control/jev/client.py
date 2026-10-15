"""Asking Jev (TypeSafe System One) without ever making the loop wait, over every route the app has to it:
TypeSafe's own API and Cloudflare's AI REST API.

`Asker.submit()` queues a question set and returns at once; a single background worker calls Jev and
stores the answers under the caller's key. The control loop only ever reads `Asker.result()`: an answer
from an earlier pass, or None. Every failure (no credentials, budget spent, timeout, HTTP error, an
envelope that doesn't parse, a question that waited too long) is recorded and yields no answer, so the
caller carries on as the base engine would. `Routes` tries each route in turn, retrying a failure that may
pass.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

try:
    import requests
except ImportError:  # the lean test harness stubs it; the add-on image installs it
    requests = None

URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run"
MODEL = "typesafe/jev"
NO_REQUESTS = "requests not installed"
NOT_JSON = "response is not JSON"
NO_ANSWERS = "no answers in the response"


def parse(payload):
    """Cloudflare wraps TypeSafe's body as result.result: (answers, usage). Anything else: (None, None)."""
    try:
        body = payload["result"]["result"]
        answers = body["answers"]
    except (KeyError, TypeError):
        return None, None
    if not isinstance(answers, dict) or not answers:
        return None, None
    return answers, body.get("usage") or {}


def call(account, token, state, questions, gateway=None, timeout=20.0):
    """One Jev evaluation -> (answers, usage, error). Never raises."""
    if requests is None:
        return None, None, NO_REQUESTS
    headers = {"Authorization": f"Bearer {token}"}
    if gateway:
        headers["cf-aig-gateway-id"] = gateway
    body = {"model": MODEL, "input": {"state": state, "questions": questions}}
    try:
        resp = requests.post(URL.format(account=account), json=body, headers=headers, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - a network fault of any kind is a missing answer
        return None, None, f"{type(e).__name__}: {e}"[:200]
    if resp.status_code != 200:
        return None, None, f"HTTP {resp.status_code}: {resp.text[:160]}"
    try:
        answers, usage = parse(resp.json())
    except ValueError:
        return None, None, NOT_JSON
    if answers is None:
        return None, None, NO_ANSWERS
    return answers, usage, None


TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_MODEL = "jev-latest"


def parse_typesafe(payload):
    """TypeSafe's own API answers at the top level: (answers, usage). Anything else: (None, None)."""
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict) or not answers:
        return None, None
    return answers, payload.get("usage") or {}


def call_typesafe(account, token, state, questions, gateway=None, timeout=20.0):
    """One Jev evaluation straight from TypeSafe with a TypeSafe API key (`token`; `account` and
    `gateway` are unused) -> (answers, usage, error). Never raises. One try: Routes retries."""
    if requests is None:
        return None, None, NO_REQUESTS
    headers = {"Authorization": f"Bearer {token}"}
    body = {"model": TYPESAFE_MODEL, "state": state, "questions": questions}
    try:
        resp = requests.post(TYPESAFE_URL, json=body, headers=headers, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - a network fault of any kind is a missing answer
        return None, None, f"{type(e).__name__}: {e}"[:200]
    if resp.status_code != 200:
        return None, None, f"HTTP {resp.status_code}: {resp.text[:160]}"
    try:
        answers, usage = parse_typesafe(resp.json())
    except ValueError:
        return None, None, NOT_JSON
    if answers is None:
        return None, None, NO_ANSWERS
    return answers, usage, None


def retryable(error):
    """A rate limit, a server error or a network fault may pass, so it is worth another try. A refused key, a bad
    request or a reply that does not parse will not pass by waiting."""
    if error.startswith("HTTP "):
        code = error[5:8]
        return code == "429" or code.startswith("5")
    return error not in (NO_REQUESTS, NOT_JSON, NO_ANSWERS)


@dataclass
class Route:
    """One way to reach Jev: `fn` is `call` (Cloudflare /ai/run) or `call_typesafe` (TypeSafe direct)."""

    name: str
    fn: object
    account: str
    token: str
    gateway: str | None = None


class Routes:
    """Jev's transport over every route it has to the same model, tried in order. A route gets `tries` tries while
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
    """Background Jev calls, keyed by the caller. `transport` is a `Routes` in the add-on and a fake in tests;
    `threaded=False` runs each submission at once (tests, and one-shot scripts). The day's calls stop at
    `daily_budget`, and take_warning() is true once a day when they reach `warn_pct` of it. A question that waited
    more than `max_wait_s` in the queue (behind calls that were failing) is dropped unasked: its evidence is stale."""

    def __init__(self, account, token, gateway=None, daily_budget=5000, transport=call,
                 threaded=True, clock=time.time, timeout=20.0, warn_pct=80, max_wait_s=300.0):
        self.account, self.token, self.gateway = account, token, gateway
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
            threading.Thread(target=self._work, name="jev-asker", daemon=True).start()

    @property
    def enabled(self):
        return bool(self.account and self.token)

    def _roll_day(self):
        day = datetime.fromtimestamp(self.clock()).date().isoformat()
        if self.stats["day"] != day:
            self.stats.update(day=day, calls=0, errors=0, input_tokens=0, retries=0, failovers=0, reasks=0,
                              warned=False)

    def submit(self, key, state, questions):
        """Queue one evaluation. False when Jev is off, the day's budget is spent, or `key` is in flight."""
        if not self.enabled:
            return False
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
        """Count one of today's events (e.g. "reasks") in the stats the Jev sensor shows."""
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
            self.stats["last_error"] = str(error)[:200]

    def result(self, key):
        """The latest answer for `key`, or None."""
        with self._lock:
            return self._results.get(key)

    def pending(self, key):
        with self._lock:
            return key in self._pending
