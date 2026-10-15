# Jev Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jev is reachable and used as fully as the spec asks: both routes with failover, retries inside 60 s, stale questions dropped, a second look when Jev is unsure, a stricter gate after a bad run, and a 5000-call day with a push at 80 %.

**Architecture:** `jev/client.py` gains a `Routes` transport (TypeSafe direct, then Cloudflare `/ai/run`, each retried while a failure may pass), and its `Asker` gains the budget warning, the stale-question drop and the day's retry, failover and re-ask counts. `jev/brain.py` re-asks unsure answers with `Judge.more_evidence()` and holds a judge to the stricter gate while `Ledger.strict()` says its recent calls went wrong, queuing an event when it goes on. `jev_bridge.py` builds all of it from the add-on options, raises CS-706 and CS-707 through the controller's `_jev_alert`, and publishes the new numbers on `sensor.crop_steering_jev`.

Two parts of the spec's availability need no new code: answers are already cached per question and acted on inside each judge's `max_age_min`, and each call that acted is already marked by its judge's `outcome()` check in the ledger. Plan 4a's Steer judge marks by whether the gap to the line shrank.

**Tech Stack:** Python 3.12 add-on (CI also runs 3.11), pytest, the Jev test kit (`addons/f2_control/tests/jev_kit.py`), the dashboard build (`frontend/`, Vite), the real-Home-Assistant tier (`tests_ha/`).

**Spec:** [docs/superpowers/specs/2026-10-02-dryback-planner-jev-steering-design.md](../specs/2026-10-02-dryback-planner-jev-steering-design.md): "Jev steering" (re-asks, marking and the stricter gate), "Availability", "Settings" rows 7 and 11, and "Delivery and verification" step 2. Shared names: [the roadmap](2026-10-02-dryback-00-roadmap.md).

## Global Constraints

- One change, one branch, one pull request, into `testing`. Never open a pull request into `main`, never push to `testing` or `main`, never merge a pull request, never promote a release.
- Class C3 (add-on options). Not reviewable without a `tests_ha/` test that fails without the change, and a seeded snapshot of an old install in `tests_ha/fixtures/` proving it still loads and nothing moves (docs/RELEASING.md, "The gate").
- Add-on options are read with `o.get("key", default)`, so an old `options.json` still works. A box keeps its own `jev_daily_calls` until its owner changes it.
- Defaults, from the spec: two routes, "3 retries inside 60 s, with backoff", "budget 5000 a day, with a push at 80 %"; unsure is "under 0.7, or the phrasings disagree": "re-ask up to twice with more evidence"; "3 worse calls in a row: stricter gate (0.8 and an agreeing re-ask)", lifted "until two calls in a row close the gap". Jev keeps steering on the stricter gate: no bench, no shadow or advisor run.
- "The code's own rules act only when every route has failed and the last answer has expired." Today those rules are the base engine's.
- Every alert code the controller raises is in `docs/error-codes.json`, written out as a string literal in an `_alert` call in `controller.py` (`tests/test_error_codes.py` reads the source), and belongs to a notification kind (`tests/test_notify_catalog.py`).
- The dashboard bundles `docs/error-codes.json`: CI fails unless the committed dashboard is exactly what `frontend/src` builds.
- A feature branch never touches a version field or a changelog.
- Lint and format: `ruff check .` everywhere; `black --check custom_components/ tests/` (88 columns).
- Docs prose: no em or en dashes.

## Review Focus

1. **Every route down for a long time.** Questions queue behind calls that each take up to a minute per route. When Jev comes back, no answer may be acted on that was asked about the zone as it was minutes ago. Pinned by `test_a_question_left_too_long_in_the_queue_is_dropped_unasked` (Task 2).
2. **A refused key on the first route.** It must not burn the retry window: straight on to the next route, no sleeps. Pinned by `test_a_refused_key_moves_straight_to_the_next_route` (Task 1).
3. **A restart on a day the budget warning already went out, or with a judge already on the stricter gate.** No second CS-706 that day, and no CS-707 for a gate that was entered before the restart. Pinned by `test_an_old_usage_file_loads_and_a_restart_does_not_warn_twice` (Task 2) and `test_the_owner_is_told_once_when_a_judge_goes_on_the_stricter_gate` (Task 3: the push comes from the outcome that tips the run, never from reading the ledger).
4. **One phrasing answering and the other missing.** That is never "sure": it is re-asked, and on the stricter gate it never acts. Pinned by `test_a_single_phrasing_is_asked_again` (Task 3).
5. **An F2 options file from 3.8.0** (TypeSafe key only, `jev_daily_calls: 2000`). Jev must start on the TypeSafe route with the owner's 2000 and every new setting at its default. Pinned by `test_an_old_options_file_keeps_its_budget_and_takes_the_new_defaults` (Task 5) and the seeded `tests_ha` test (Task 5).

## Before you start

Branch from the tip of `testing`, in a worktree of your own:

```bash
git fetch origin
git worktree add ../jev-dryback-02 -b feat/dryback-02-jev-availability origin/testing
cd ../jev-dryback-02
```

Line numbers below are from 3.8.0 (`d3e2e19`). Find each edit by the code it quotes. Test commands, from the repo root:

- add-on suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q`
- root suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q`
- everything CI runs: `bash tests/run_ci.sh`

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `addons/f2_control/f2_control/jev/client.py` | modify | Routes, retries and failover; the Asker's budget warning, stale-question drop and day counts. |
| `addons/f2_control/f2_control/jev/ledger.py` | modify | `strict()`: the stricter gate, read from resolved calls. |
| `addons/f2_control/f2_control/jev/brain.py` | modify | Re-asks; the stricter gate; `events`. |
| `addons/f2_control/f2_control/jev/judges/base.py` | modify | `Judge.more_evidence()`. |
| `addons/f2_control/f2_control/jev_bridge.py` | modify | Build from the options; `runtime_alerts()`; publish the new numbers; keep the new day counts. |
| `addons/f2_control/f2_control/controller.py` | modify | `_jev_alert` raises CS-706 and CS-707. |
| `addons/f2_control/config.yaml`, `addons/f2_control/translations/en.yaml` | modify | Six new options; `jev_daily_calls` 5000. |
| `docs/error-codes.json`, `docs/ERROR_CODES.md` | modify | CS-706, CS-707. |
| `custom_components/crop_steering/notify_catalog.py`, `docs/NOTIFICATIONS.md`, `frontend/src/lib/notify-demo.ts` | modify | Both codes in the `jev` kind. |
| `www/dashboard.html`, `custom_components/crop_steering/www/dashboard.html`, `addons/f2_control/www/public/dashboard.html` | rebuild | The dashboard bundles the catalog. |
| `docs/JEV.md`, `addons/f2_control/DOCS.md`, `README.md` | modify | Routes, the new options, the two codes. |
| `scripts/jev_live_smoke.py` | modify | Keeps its retry by using `Routes`. |
| `addons/f2_control/tests/jev_kit.py` | modify | `ScriptedTransport`. |
| `addons/f2_control/tests/test_jev_routes.py` | create | Routes and the Asker. |
| `addons/f2_control/tests/test_jev_runtime.py`, `addons/f2_control/tests/test_jev_controller.py` | modify | Re-asks, the gate, the bridge. |
| `tests_ha/test_notify_controller.py` | modify | CS-706 and CS-707 reach the phone that ticks Jev. |
| `tests_ha/fixtures/options_3_8_0_f2.json`, `tests_ha/test_upgrade_in_place.py` | create, modify | 3.8.0 options start Jev with the owner's budget. |

---

### Task 1: Routes, retries and failover

**Files:**
- Modify: `addons/f2_control/f2_control/jev/client.py` (the module docstring 1-8; constants after 23; `call` 37-56; `call_typesafe` 73-96)
- Modify: `scripts/jev_live_smoke.py` (22, 231)
- Create: `addons/f2_control/tests/test_jev_routes.py`

**Interfaces:**
- Consumes: the transport contract `fn(account, token, state, questions, gateway=None, timeout=20.0) -> (answers, usage, error)`, which `call` and `call_typesafe` already keep.
- Produces:
  - `NO_REQUESTS`, `NOT_JSON`, `NO_ANSWERS`: the three non-network error strings.
  - `retryable(error: str) -> bool`: HTTP 429 and 5xx, and network faults (any error that is not `HTTP ...` and not one of the three), are worth another try.
  - `Route(name: str, fn, account: str, token: str, gateway: str | None = None)`.
  - `Routes(routes, tries=3, window_s=60.0, sleep=time.sleep, clock=time.monotonic)`: a transport. On success its usage is the route's usage plus `route` (the name), `failover` (True when not the first route) and `retries` (sleeps taken across all routes). On failure the error is `"<name>: <error>; <name>: <error>"`, cut to 200 characters. `Routes.routes` and `Routes.tries` are readable.
  - `call_typesafe` makes one try; retrying is `Routes`' job.

- [ ] **Step 1: Write the failing tests**

Create `addons/f2_control/tests/test_jev_routes.py`:

```python
"""Jev's routes and its asker: TypeSafe direct, then Cloudflare's /ai/run, each retried while a failure may pass
and inside a window, any failure moving on to the next route; the day's budget warning, a question that waited too
long, and the day's counts (docs/JEV.md, Availability)."""
import jev_kit as K
from jev import client
from jev.client import NO_ANSWERS, NO_REQUESTS, NOT_JSON, Route, Routes, retryable

ANSWERS = {"q__v0": K.noul_answer(0.9)}


class FakeClock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


class Flaky:
    """A route that fails with `errors` in turn, then answers; each call takes `takes` seconds on `clock`."""

    def __init__(self, *errors, clock=None, takes=0.0):
        self.errors, self.calls, self.clock, self.takes = list(errors), [], clock, takes

    def __call__(self, account, token, state, questions, gateway=None, timeout=20.0):
        self.calls.append((account, token, gateway))
        if self.clock is not None:
            self.clock.t += self.takes
        if self.errors:
            return None, None, self.errors.pop(0)
        return dict(ANSWERS), {"input_tokens": 900}, None


def _routes(*fns, tries=3, clock=None):
    clock = clock or FakeClock()
    named = [Route(name, fn, f"{name}-acct", f"{name}-key") for name, fn in zip(("TypeSafe", "Cloudflare"), fns)]
    return Routes(named, tries=tries, sleep=clock.sleep, clock=clock), clock


def test_what_is_worth_another_try():
    for error in ("HTTP 429: slow down", "HTTP 500: boom", "HTTP 503: busy", "HTTP 529: overloaded",
                  "ReadTimeout: read timed out", "ConnectionError: refused"):
        assert retryable(error), error
    for error in ("HTTP 400: bad", "HTTP 401: bad key", "HTTP 403: no", "HTTP 404: none",
                  NOT_JSON, NO_ANSWERS, NO_REQUESTS):
        assert not retryable(error), error


def test_a_server_error_is_tried_again_with_backoff_then_answers():
    ts = Flaky("HTTP 503: busy", "HTTP 529: overloaded")
    send, clock = _routes(ts)
    answers, usage, error = send("ignored", "ignored", {"s": 1}, {"q__v0": {}})
    assert error is None and answers == ANSWERS and len(ts.calls) == 3
    assert (usage["route"], usage["failover"], usage["retries"], usage["input_tokens"]) == ("TypeSafe", False, 2, 900)
    assert clock.slept == [2.0, 4.0]
    assert ts.calls[0] == ("TypeSafe-acct", "TypeSafe-key", None)  # each route uses its own credentials


def test_a_refused_key_moves_straight_to_the_next_route():
    ts, cf = Flaky("HTTP 401: bad key"), Flaky()
    send, clock = _routes(ts, cf)
    answers, usage, error = send("", "", {}, {})
    assert error is None and len(ts.calls) == 1 and len(cf.calls) == 1
    assert (usage["route"], usage["failover"], usage["retries"]) == ("Cloudflare", True, 0)
    assert clock.slept == []


def test_three_server_errors_then_the_next_route():
    ts, cf = Flaky("HTTP 500: a", "HTTP 502: b", "HTTP 503: c"), Flaky()
    send, _clock = _routes(ts, cf)
    answers, usage, error = send("", "", {}, {})
    assert len(ts.calls) == 3 and len(cf.calls) == 1
    assert (usage["route"], usage["failover"], usage["retries"]) == ("Cloudflare", True, 2)


def test_timeouts_stop_once_another_try_would_pass_the_window():
    clock = FakeClock()
    ts = Flaky("ReadTimeout: 20 s", "ReadTimeout: 20 s", "ReadTimeout: 20 s", clock=clock, takes=20.0)
    send, _ = _routes(ts, clock=clock)
    answers, usage, error = send("", "", {}, {}, timeout=20.0)
    assert answers is None and len(ts.calls) == 2  # 20 s, a 2 s wait, 20 s: a third try could end past 60 s
    assert error == "TypeSafe: ReadTimeout: 20 s"


def test_every_route_failing_names_each_one():
    send, _clock = _routes(Flaky("HTTP 401: bad key"), Flaky("HTTP 403: no access"))
    answers, usage, error = send("", "", {}, {})
    assert (answers, usage) == (None, None)
    assert error == "TypeSafe: HTTP 401: bad key; Cloudflare: HTTP 403: no access"


def test_typesafe_direct_makes_one_try(monkeypatch):
    """The TypeSafe call no longer retries a 429 itself: Routes retries every route alike."""
    posts = []

    class Resp:
        status_code, text = 429, "slow down"

    class Requests:
        @staticmethod
        def post(*args, **kwargs):
            posts.append(1)
            return Resp()

    monkeypatch.setattr(client, "requests", Requests)
    monkeypatch.setattr(client.time, "sleep", lambda s: posts.append(f"slept {s}"))
    assert client.call_typesafe("typesafe", "key", {}, {})[2] == "HTTP 429: slow down"
    assert posts == [1]
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_jev_routes.py -q`
Expected: collection error, `ImportError: cannot import name 'NO_ANSWERS' from 'jev.client'`.

- [ ] **Step 3: Write the transport**

In `addons/f2_control/f2_control/jev/client.py`, replace the module docstring:

```python
"""Asking Jev (TypeSafe System One) without ever making the loop wait, over every route the app has to it:
TypeSafe's own API and Cloudflare's AI REST API.

`Asker.submit()` queues a question set and returns at once; a single background worker calls Jev and
stores the answers under the caller's key. The control loop only ever reads `Asker.result()`: an answer
from an earlier pass, or None. Every failure (no credentials, budget spent, timeout, HTTP error, an
envelope that doesn't parse, a question that waited too long) is recorded and yields no answer, so the
caller carries on as the base engine would. `Routes` tries each route in turn, retrying a failure that may
pass.
"""
```

After `MODEL = "typesafe/jev"`, add the three error strings:

```python
URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run"
MODEL = "typesafe/jev"
NO_REQUESTS = "requests not installed"
NOT_JSON = "response is not JSON"
NO_ANSWERS = "no answers in the response"
```

Replace `call` with:

```python
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
```

Replace `call_typesafe` with, and add after it:

```python
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
```

In `scripts/jev_live_smoke.py`, keep the smoke run's retry by sending through `Routes`. Change the import (line 22):

```python
from jev.client import Asker, Route, Routes, call_typesafe  # noqa: E402
```

and the asker (line 231):

```python
        asker = Asker("typesafe", key, None, threaded=False, timeout=60,
                      transport=Routes([Route("TypeSafe", call_typesafe, "typesafe", key)]))
```

- [ ] **Step 4: Run the tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_jev_routes.py addons/f2_control/tests/test_jev_runtime.py -q`
Expected: all pass (`test_jev_routes.py`: 7).

Run: `ruff check scripts/jev_live_smoke.py addons/f2_control/f2_control/jev/client.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add addons/f2_control/f2_control/jev/client.py addons/f2_control/tests/test_jev_routes.py scripts/jev_live_smoke.py
git commit -m "Reach Jev over every route it has, retrying what may pass" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The asker's budget warning, stale questions and day counts

**Files:**
- Modify: `addons/f2_control/f2_control/jev/client.py` (the `Asker` class, 108-188)
- Modify: `addons/f2_control/f2_control/jev_bridge.py` (`USAGE_KEYS`, 359)
- Test: `addons/f2_control/tests/test_jev_routes.py`

**Interfaces:**
- Consumes: `Routes` usage keys `route`, `failover`, `retries` (Task 1).
- Produces:
  - `Asker(account, token, gateway=None, daily_budget=5000, transport=call, threaded=True, clock=time.time, timeout=20.0, warn_pct=80, max_wait_s=300.0)`.
  - `Asker.stats` keys, reset each day except `route`: `day`, `calls`, `errors`, `input_tokens`, `last_error`, `last_call`, `retries`, `failovers`, `reasks`, `warned`, `route`.
  - `Asker.note(stat: str) -> None`; `Asker.take_warning() -> bool`.
  - A queued job is `(key, state, questions, asked_at)`.
  - `jev_bridge.USAGE_KEYS` adds `retries`, `failovers`, `reasks`, `warned`, so a restart keeps them for the day.

- [ ] **Step 1: Write the failing tests**

Append to `addons/f2_control/tests/test_jev_routes.py`, and add `import json` and `from jev.client import Asker` to its imports:

```python
def test_the_asker_warns_once_a_day_at_80_percent_of_the_budget():
    day = {"t": K.NOW.timestamp()}
    a = Asker("acct", "tok", transport=K.FakeTransport(ANSWERS), threaded=False, daily_budget=5, warn_pct=80,
              clock=lambda: day["t"])
    for i in range(3):
        assert a.submit(f"k{i}", {}, {}) and not a.take_warning()
    assert a.submit("k3", {}, {}) and a.take_warning()  # the 4th call of 5 is 80 %
    assert not a.take_warning()
    assert a.submit("k4", {}, {}) and not a.take_warning() and a.stats["warned"]
    day["t"] += 86400  # the next day starts again
    assert a.submit("k5", {}, {}) and a.stats["calls"] == 1 and not a.stats["warned"]


def test_a_question_left_too_long_in_the_queue_is_dropped_unasked():
    now = {"t": K.NOW.timestamp()}
    t = K.FakeTransport(ANSWERS)
    a = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: now["t"], max_wait_s=300)
    a._pending.add("k")
    a._run(("k", {}, {}, now["t"] - 301))  # asked 301 s ago: the worker was stuck behind failing calls
    assert t.calls == [] and a.result("k") is None and not a.pending("k")
    assert a.stats["errors"] == 1 and "dropped unasked" in a.stats["last_error"]


def test_the_asker_counts_retries_failovers_and_second_looks():
    ts, cf = Flaky("HTTP 503: busy", "HTTP 401: bad key"), Flaky()
    send, _clock = _routes(ts, cf)
    a = Asker("acct", "tok", transport=send, threaded=False, clock=lambda: K.NOW.timestamp())
    assert a.submit("k1", {}, {})  # TypeSafe: busy, a retry, then a refused key: Cloudflare answers
    assert a.submit("k2", {}, {})  # TypeSafe answers
    a.note("reasks")
    assert (a.stats["retries"], a.stats["failovers"], a.stats["reasks"]) == (1, 1, 1)
    assert a.stats["route"] == "TypeSafe" and a.daily_budget == 5000


def test_an_old_usage_file_loads_and_a_restart_does_not_warn_twice(tmp_path):
    import jev_bridge

    path = tmp_path / "jev_usage.json"
    today = K.NOW.date().isoformat()
    path.write_text(json.dumps({"day": today, "calls": 41, "errors": 0, "input_tokens": 9, "last_error": None}))
    a = Asker("acct", "tok", transport=K.FakeTransport(ANSWERS), threaded=False, clock=lambda: K.NOW.timestamp())
    jev_bridge.restore_usage(a, str(path))  # 3.8.0's file: no retries, failovers, reasks or warned
    assert (a.stats["calls"], a.stats["retries"], a.stats["warned"]) == (41, 0, False)
    path.write_text(json.dumps({"day": today, "calls": 4100, "warned": True}))
    b = Asker("acct", "tok", transport=K.FakeTransport(ANSWERS), threaded=False, clock=lambda: K.NOW.timestamp())
    jev_bridge.restore_usage(b, str(path))
    assert b.submit("k", {}, {}) and not b.take_warning()  # warned before the restart: not again today
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_jev_routes.py -q`
Expected: 4 failed: `TypeError: Asker.__init__() got an unexpected keyword argument 'warn_pct'` (and `'max_wait_s'`), `AttributeError: 'Asker' object has no attribute 'note'`, `KeyError: 'retries'`.

- [ ] **Step 3: Write the asker**

In `addons/f2_control/f2_control/jev/client.py`, replace the `Asker` class with:

```python
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
            self._results[key] = Answer(answers, self.clock(), usage, self._seq)
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
```

In `addons/f2_control/f2_control/jev_bridge.py`, keep the new day counts across a restart:

```python
USAGE_KEYS = ("day", "calls", "errors", "input_tokens", "last_error", "retries", "failovers", "reasks", "warned")
```

- [ ] **Step 4: Run the Jev tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_jev_routes.py addons/f2_control/tests/test_jev_runtime.py addons/f2_control/tests/test_jev_triage.py -q`
Expected: all pass (`test_jev_routes.py`: 11).

- [ ] **Step 5: Commit**

```bash
git add addons/f2_control/f2_control/jev/client.py addons/f2_control/f2_control/jev_bridge.py addons/f2_control/tests/test_jev_routes.py
git commit -m "Warn at 80 % of Jev's calls, drop stale questions, count retries and failovers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Second looks and the stricter gate

**Files:**
- Modify: `addons/f2_control/f2_control/jev/ledger.py` (after `track`, 63-75)
- Modify: `addons/f2_control/f2_control/jev/judges/base.py` (after `outcome`, 80-82)
- Modify: `addons/f2_control/f2_control/jev/brain.py` (whole file)
- Modify: `addons/f2_control/tests/jev_kit.py` (after `FakeTransport`)
- Test: `addons/f2_control/tests/test_jev_runtime.py`

**Interfaces:**
- Consumes: `Asker.note("reasks")` (Task 2); `council.Verdict` fields `agreed`, `prob`, `n`, `label`.
- Produces:
  - `Ledger.strict(judge, room, zone, after=3, clear=2) -> bool`.
  - `Judge.more_evidence(ctx, verdicts) -> dict`, sent as `evidence["second_look"]`.
  - `Brain(asker, ledger, judges, allowed=None, log=print, reask_max=2, unsure_below=0.7, strict_after=3, strict_prob=0.8)`; attributes of the same names; `Brain.strict` `{(room, zone, judge): bool}`; `Brain.events` `[("strict", room, zone, judge)]`, which the bridge empties (Task 5).
  - `JudgeState.reask_due: bool`, `JudgeState.reasks: int`.
  - `jev_kit.ScriptedTransport(*answers)`: answers each call with the next in turn; the last repeats.

- [ ] **Step 1: Add the scripted transport to the test kit**

In `addons/f2_control/tests/jev_kit.py`, after `FakeTransport`:

```python
class ScriptedTransport(FakeTransport):
    """Answers each call with the next of `answers` in turn; the last one repeats."""

    def __init__(self, *answers):
        super().__init__(answers[0] if answers else None)
        self.script = list(answers)

    def __call__(self, account, token, state, questions, gateway=None, timeout=20.0):
        if self.script:
            self.answers = self.script.pop(0)
        return super().__call__(account, token, state, questions, gateway, timeout)
```

- [ ] **Step 2: Write the failing tests**

Append to `addons/f2_control/tests/test_jev_runtime.py`:

```python
# ------------------------------------------------------------------ second looks and the stricter gate
UNSURE = K.both("ramp_state", K.choice_answer("slab_full", {"slab_full": 0.5, "keep_ramping": 0.5}))
SURE = K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.85, "keep_ramping": 0.15}))
FAIRLY = K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.75, "keep_ramping": 0.25}))


def _brain(t, ledger=None, judge=None):
    asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: K.NOW.timestamp())
    return Brain(asker, ledger or Ledger(None), [judge or RampJudge()], log=lambda *a: None)


def _bad_run(led, judge="ramp", n=3):
    for _ in range(n):
        led.resolve(led.record(judge, "default", 1, "P2", "advance"), "moisture fell back", False)


def test_an_unsure_answer_is_asked_again_with_more_evidence_and_the_sure_one_acts():
    t = K.ScriptedTransport(UNSURE, SURE)
    brain = _brain(t)
    assert brain.tick(_ramp_ctx()) == []  # unsure: nothing acts
    out = brain.tick(_ramp_ctx())  # the same minute: asked again at once, not after the 15-minute cadence
    assert [(d.kind, d.value) for d, _ in out] == [("advance", "P2")]
    assert len(t.calls) == 2 and "second_look" not in t.calls[0]["state"]
    look = t.calls[1]["state"]["second_look"]
    assert look["your_last_answer"]["ramp_state"] == {"answer": "slab_full", "p": 0.5, "agreed": True}
    assert brain.asker.stats["reasks"] == 1


def test_jev_is_asked_again_at_most_twice_then_the_engine_decides():
    t = K.ScriptedTransport(UNSURE)
    brain = _brain(t)
    for _ in range(5):
        assert brain.tick(_ramp_ctx()) == []
    assert len(t.calls) == 3 and brain.asker.stats["reasks"] == 2  # the question and two second looks


def test_two_phrasings_that_disagree_are_asked_again():
    split = K.both("ramp_state",
                   K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.9, "keep_ramping": 0.1}),
                   K.choice_answer("keep_ramping", {"ec_is_feed_front": 0.2, "keep_ramping": 0.8}))
    t = K.ScriptedTransport(split)
    brain = _brain(t)
    brain.tick(_ramp_ctx())
    brain.tick(_ramp_ctx())
    assert len(t.calls) == 2


def test_a_single_phrasing_is_asked_again():
    one = {"ramp_state__v0": K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.95, "keep_ramping": 0.05})}
    t = K.ScriptedTransport(one)
    brain = _brain(t)
    assert brain.tick(_ramp_ctx()) == [] and brain.tick(_ramp_ctx()) == []
    assert len(t.calls) == 2


def test_the_stricter_gate_comes_after_three_bad_calls_and_lifts_after_two_good():
    led = Ledger(None)
    _bad_run(led, n=2)
    assert not led.strict("ramp", "default", 1)
    _bad_run(led, n=1)
    assert led.strict("ramp", "default", 1) and not led.strict("ramp", "default", 2)  # per zone
    led.resolve(led.record("ramp", "default", 1, "P2", "advance"), "held", True)
    assert led.strict("ramp", "default", 1)  # one good call is not enough
    led.resolve(led.record("ramp", "default", 1, "P2", "advance"), "held", True)
    assert not led.strict("ramp", "default", 1)


def test_on_the_stricter_gate_a_sure_answer_waits_for_a_second_look_that_agrees():
    led = Ledger(None)
    _bad_run(led)
    t = K.ScriptedTransport(SURE, SURE)
    brain = _brain(t, led)
    assert brain.tick(_ramp_ctx()) == []  # 0.85, but no second look yet
    assert brain.zone_status("default", 1)["ramp"]["why"].startswith("refused: stricter gate")
    out = brain.tick(_ramp_ctx())  # the second look agrees: it acts
    assert [(d.kind, d.value) for d, _ in out] == [("advance", "P2")] and len(t.calls) == 2
    assert brain.strict == {("default", 1, "ramp"): True}


def test_on_the_stricter_gate_an_answer_under_0_8_never_acts():
    led = Ledger(None)
    _bad_run(led)
    t = K.ScriptedTransport(FAIRLY)
    brain = _brain(t, led)
    for _ in range(4):
        assert brain.tick(_ramp_ctx()) == []
    assert len(t.calls) == 3  # the question and two second looks, all at 0.75


def test_the_owner_is_told_once_when_a_judge_goes_on_the_stricter_gate():
    class Graded(RampJudge):
        def outcome(self, entry, ctx):
            return "moisture fell back", False

    led = Ledger(None)
    for _ in range(3):
        led.record("ramp", "default", 1, "P2", "advance", check_at=K.NOW - timedelta(minutes=1), check={})
    brain = _brain(K.FakeTransport({}), led, Graded())
    brain.tick(_ramp_ctx())
    assert brain.events == [("strict", "default", 1, "ramp")] and led.strict("ramp", "default", 1)
    brain.tick(_ramp_ctx())
    assert brain.events == [("strict", "default", 1, "ramp")]  # once, when the run tipped over
    assert _brain(K.FakeTransport({}), led).events == []  # a restart reads the gate, it does not push again
```

- [ ] **Step 3: Run them to see them fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_jev_runtime.py -q`
Expected: 8 failed (no second look is asked; `AttributeError: 'Ledger' object has no attribute 'strict'`; `AttributeError: 'Brain' object has no attribute 'events'`).

- [ ] **Step 4: Read the gate from the ledger**

In `addons/f2_control/f2_control/jev/ledger.py`, after `track`:

```python
    def strict(self, judge, room, zone, after=3, clear=2):
        """True while this judge, for this zone, is on the stricter gate: `after` calls in a row that did not work out
        put it there, and `clear` in a row that did take it off. Read from the resolved calls, so a restart keeps it."""
        with self._lock:
            done = [bool(e["outcome"]["good"]) for e in self.entries if e["judge"] == judge
                    and e["room"] == room and e["zone"] == zone and e.get("outcome")]
        on, bad, good = False, 0, 0
        for ok in done:
            bad, good = (0, good + 1) if ok else (bad + 1, 0)
            if bad >= after:
                on = True
            elif on and good >= clear:
                on = False
        return on
```

- [ ] **Step 5: Give every judge a second look**

In `addons/f2_control/f2_control/jev/judges/base.py`, after `outcome`:

```python
    def more_evidence(self, ctx, verdicts) -> dict:
        """What a second look adds when the last answer was unsure: that answer, and the sibling zones. A judge with
        more to show (the last few days, the doctrine) adds to it."""
        return {
            "why_again": "your last answer was unsure, or your two readings of it disagreed: look again with this",
            "your_last_answer": {q: {"answer": v.label, "p": v.prob, "agreed": v.agreed}
                                 for q, v in verdicts.items() if v is not None},
            "sibling_zones": dict(ctx.siblings or {}),
        }
```

- [ ] **Step 6: Ask again when unsure, and hold the gate**

Replace `addons/f2_control/f2_control/jev/brain.py` with:

```python
"""Runs the judges for every zone on every pass, without waiting for any of them.

On each pass `tick()` asks the judges that are due (in the background), reads the answers that have
arrived, turns each NEW answer into a directive exactly once, puts the standing directive through the
envelope (the zone changes between passes, so admission is checked every pass), records what acted in
the ledger, and returns the admitted directives for the controller to apply. Nothing here raises into the
caller: a broken judge is skipped and logged in `errors`.

When Jev is unsure (an answer under `unsure_below`, two phrasings that disagree, or one missing) the judge is
asked again at once with more evidence (Judge.more_evidence), up to `reask_max` times, before the engine decides
alone. After `strict_after` of a judge's calls in a row did not work out for a zone (Ledger.strict), the judge is
on the stricter gate there: an answer acts only when the same call came twice in a row and every phrasing agreed
at `strict_prob` or more. Jev keeps judging throughout. The pass on which a run tips a judge onto the gate adds
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
            st.streak = st.streak + 1 if (k is not None and k == st.streak_key) else (1 if k else 0)
            st.streak_key = k
            st.reask_due = self._unsure(st.verdicts) and st.reasks < self.reask_max
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
        if strict and not self._sure_enough(st):
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
            check_at = (ctx.now + timedelta(minutes=judge.outcome_after_min)
                        if judge.outcome_after_min else None)
            self.ledger.record(judge.name, ctx.room, ctx.zone, _label(d), d.kind,
                               evidence={q: (v.label if v else None) for q, v in st.verdicts.items()},
                               check_at=check_at, check=self._check_basis(ctx), at=ctx.now)
            self.log(f"[jev] {ctx.room} Z{ctx.zone} {judge.name}: {d.kind} {_label(d)} ({d.why}; {why})")
            self._note(ctx, judge, st, d, "acted", why)
        return d, why

    def _unsure(self, verdicts):
        """An answer under `unsure_below`, two phrasings that disagree, or a question one phrasing left unanswered."""
        return any(v is None or v.n < 2 or not v.agreed or v.prob < self.unsure_below for v in verdicts.values())

    def _sure_enough(self, st):
        """On the stricter gate: the same call came twice in a row, and every phrasing agreed at `strict_prob`."""
        return st.streak >= 2 and all(v is not None and v.n >= 2 and v.agreed and v.prob >= self.strict_prob
                                      for v in st.verdicts.values())

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
```

- [ ] **Step 7: Run every Jev test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q -k jev`
Expected: all pass. An older Jev test that now fails asked something unsure and expected exactly one call: read it before changing it, and say in the commit message which test changed and why.

- [ ] **Step 8: Commit**

```bash
git add addons/f2_control/f2_control/jev/ledger.py addons/f2_control/f2_control/jev/judges/base.py addons/f2_control/f2_control/jev/brain.py addons/f2_control/tests/jev_kit.py addons/f2_control/tests/test_jev_runtime.py
git commit -m "Ask Jev again when it is unsure, and hold a judge to a stricter gate after a bad run" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: CS-706 and CS-707, from the controller to the phone

**Files:**
- Modify: `addons/f2_control/f2_control/controller.py` (`_jev_alert`, 2654-2668)
- Modify: `docs/error-codes.json` (the CS-7 group; after CS-705)
- Regenerate: `docs/ERROR_CODES.md`
- Modify: `custom_components/crop_steering/notify_catalog.py` (the `jev` kind), `docs/NOTIFICATIONS.md` (its `jev` row), `frontend/src/lib/notify-demo.ts` (its `jev` kind)
- Rebuild: the three committed dashboards
- Test: `tests_ha/test_notify_controller.py`; the existing `tests/test_error_codes.py` and `tests/test_notify_catalog.py`

**Interfaces:**
- Consumes: `Controller._alert(key, code, title, message, room=None, zone=None, quiet=True)`.
- Produces: `Controller._jev_alert(room, zone, judge, alert)` accepts `zone=None` (a room-wide alert, key `jev_<judge>_<slug>`) and the codes CS-706 and CS-707; both codes are in the `jev` notification kind.

- [ ] **Step 1: Write the failing real-Home-Assistant test**

Append to `tests_ha/test_notify_controller.py`:

```python
async def test_jevs_own_alerts_reach_the_phone_that_ticks_jev(
    hass, hass_admin_user, controller_for, monkeypatch
):
    """CS-706 (most of the day's calls used) and CS-707 (a zone on the stricter gate) are in the
    jev kind: the phone that ticks Jev gets both, the tablet that ticks only emergencies and
    hardware gets neither."""
    await _install(hass)
    staff = await _staff(hass)
    received, doc = await _set_up(hass, hass_admin_user, staff)
    phone, tablet = doc["config"]["recipients"]
    await _call(
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=1,
        recipients=[{**phone, "kinds": ["jev"]}, tablet],
    )
    await hass.async_block_till_done()
    c, fake, _clock = controller_for({"notify_service": "notify/mobile_app_old_phone"})
    import controller

    def answered(domain, service, data, timeout=12):
        fake.calls.append((domain, service, dict(data)))
        return 200, {"sent_to": [STAFF_PHONE], "error": None}

    monkeypatch.setattr(controller, "ha_service_response", answered)
    room = c.rooms[0]
    c._jev_alert(
        room,
        1,
        "ramp",
        {"code": "CS-707", "title": "Jev is on the stricter gate", "message": "Bad run."},
    )
    c._jev_alert(
        room,
        None,
        "budget",
        {"code": "CS-706", "title": "Jev has used most of today's calls", "message": "4000."},
    )
    strict, budget = _asked(fake)
    assert (strict["code"], strict["key"], budget["code"], budget["key"]) == (
        "CS-707",
        "jev_ramp_default_z1",
        "CS-706",
        "jev_budget_default",
    )
    for asked, words in ((strict, "Bad run."), (budget, "4000.")):
        answer = await hass.services.async_call(
            DOMAIN, "notify", asked, blocking=True, return_response=True
        )
        assert answer == {"sent_to": [STAFF_PHONE], "error": None}
        assert received[STAFF_PHONE][-1]["message"].startswith(words)
```

- [ ] **Step 2: Run it to see it fail**

Run it in WSL, as plan 1 Task 4 describes (`~/ha-venv`; check `wsl -d Ubuntu -- free -g` first, and use CI instead with under 3 GB free):

```bash
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/Github/jev-dryback-02 && ~/ha-venv/bin/python -m pytest tests_ha/test_notify_controller.py -q'
```

Expected: the new test fails. Before the controller change `_jev_alert` refuses both codes, so `_asked(fake)` is empty: `ValueError: not enough values to unpack`.

- [ ] **Step 3: Raise the two codes**

In `addons/f2_control/f2_control/controller.py`, replace `_jev_alert` with:

```python
    def _jev_alert(self, room, zone, judge, alert):
        """An alert one of Jev's judges, or Jev's runtime, raised (docs/JEV.md). Only these codes exist: a judge can
        never raise anything the error-code list does not explain. `zone` None is a room-wide alert."""
        key = f"jev_{judge}_{room.slug}" + ("" if zone is None else f"_z{zone}")
        code, title, message = alert.get("code"), alert.get("title", ""), alert.get("message", "")
        if code == "CS-701":
            self._alert(key, "CS-701", title, message, room=room, zone=zone)
        elif code == "CS-702":
            self._alert(key, "CS-702", title, message, room=room, zone=zone)
        elif code == "CS-703":
            self._alert(key, "CS-703", title, message, room=room, zone=zone)
        elif code == "CS-705":
            self._alert(key, "CS-705", title, message, room=room, zone=zone)
        elif code == "CS-706":
            self._alert(key, "CS-706", title, message, room=room, zone=zone)
        elif code == "CS-707":
            self._alert(key, "CS-707", title, message, room=room, zone=zone)
        else:
            log("jev alert refused: not in the error-code list", judge, code)
```

- [ ] **Step 4: Explain them in the list, and route them**

In `docs/error-codes.json`, change the CS-7 group's detail:

```json
    {
      "prefix": "CS-7",
      "name": "Jev",
      "detail": "Jev's judgements about a zone (advice, a probe it set aside), and how Jev itself is doing: its calls running low, a judge on the stricter gate (docs/JEV.md)."
    },
```

and insert these two entries right after CS-705 (the list stays sorted):

```json
    {
      "code": "CS-706",
      "title": "Jev has used most of today's calls",
      "source": "notification",
      "severity": "warning",
      "meaning": "Jev has been asked the warning share (80 % by default) of its daily call budget, across every room. Once the budget is spent, Jev is not asked again until midnight.",
      "watering": "Carries on as normal. Once the budget is spent, the engine's own rules decide every zone until midnight.",
      "causes": [
        "More zones or judges than the budget was set for.",
        "Many second looks: Jev was often unsure today.",
        "The budget option is still at an older, lower value."
      ],
      "fixes": [
        "Raise jev_daily_calls in the app's options, then restart the app.",
        "Check reasks_today and errors_today on the Jev sensor: many of either show what used the calls."
      ]
    },
    {
      "code": "CS-707",
      "title": "Jev is on the stricter gate for this zone",
      "source": "notification",
      "severity": "warning",
      "meaning": "Several of one Jev judge's calls in a row for this zone (three by default) did not work out when they were checked. Until two in a row do, that judge acts only when both phrasings agree at 0.8 or more (the default) and a second look gives the same answer.",
      "watering": "Carries on. Jev keeps judging the zone; whenever it is not sure enough, the engine's own rules act, as they do without Jev.",
      "causes": [
        "A probe or sensor misleading the judge.",
        "Conditions the judge has not met before, such as a new stage or a changed room.",
        "A setting that works against the judge's calls."
      ],
      "fixes": [
        "Read the zone's Jev log on the dashboard: the calls and how each was checked.",
        "Check the zone's probe and settings."
      ]
    },
```

Regenerate the readable page:

```bash
python scripts/render_error_codes.py
```

In `custom_components/crop_steering/notify_catalog.py`, the `jev` kind:

```python
        "id": "jev",
        "name": "Jev",
        "detail": "Jev's advice about a zone, its automatic targets paused, Jev moving a "
        "setting, its calls running low, and a zone on its stricter gate",
        "codes": _codes("CS-404 CS-501 CS-702 CS-705 CS-706 CS-707"),
        "events": ("jev_setpoint",),
```

In `docs/NOTIFICATIONS.md`, the `jev` row:

```markdown
| `jev` | Jev | CS-501, CS-702, CS-705, CS-706, CS-707, CS-404, and Jev moving a setting (new event, no card) |
```

In `frontend/src/lib/notify-demo.ts`, the demo's `jev` kind:

```ts
    codes: ["CS-501", "CS-702", "CS-705", "CS-706", "CS-707", "CS-404"],
```

- [ ] **Step 5: Rebuild the dashboard**

The dashboard bundles `docs/error-codes.json`, so it is rebuilt and committed:

```bash
cd frontend && bun install && bun run test && bun run build && cd ..
git status --short www custom_components/crop_steering/www addons/f2_control/www
```

Expected: vitest passes, the build writes the three dashboards, and all three show as modified with identical contents (`sha256sum` on them prints one hash). If CI's "Committed dashboard is exactly what the source builds" step later differs, rebuild with CI's own recipe, `npm ci --prefix frontend && npm run build --prefix frontend`, and commit that output.

- [ ] **Step 6: Run the code checks and the real-Home-Assistant test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_error_codes.py tests/test_notify_catalog.py -q`
Expected: all pass. Before Step 4 `test_every_notification_code_is_explained_and_every_explained_code_is_raised` fails, because the controller raises two codes the list does not explain.

Run: `black --check custom_components/ tests/`
Expected: unchanged.

Run the WSL command from Step 2 again. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add addons/f2_control/f2_control/controller.py docs/error-codes.json docs/ERROR_CODES.md custom_components/crop_steering/notify_catalog.py docs/NOTIFICATIONS.md frontend/src/lib/notify-demo.ts www/dashboard.html custom_components/crop_steering/www/dashboard.html addons/f2_control/www/public/dashboard.html tests_ha/test_notify_controller.py
git commit -m "Add CS-706 and CS-707 and send them to the phones that tick Jev" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Build it from the options, push, publish, document

**Files:**
- Modify: `addons/f2_control/f2_control/jev_bridge.py` (imports, 14; `build`, 44-73; `publish`, 405-436)
- Modify: `addons/f2_control/config.yaml` (options 51, schema 78), `addons/f2_control/translations/en.yaml` (after `jev_daily_calls`, 128-132)
- Modify: `docs/JEV.md` (Failing safe, Configuration, What Jev can raise), `addons/f2_control/DOCS.md` (the Jev options), `README.md` (the "Cap what it can spend" row)
- Create: `tests_ha/fixtures/options_3_8_0_f2.json`; modify `tests_ha/test_upgrade_in_place.py`
- Test: `addons/f2_control/tests/test_jev_runtime.py`, `addons/f2_control/tests/test_jev_controller.py`

**Interfaces:**
- Consumes: `Route`, `Routes`, `Asker(warn_pct=...)`, `Asker.take_warning()` (Tasks 1 and 2); `Brain(reask_max, unsure_below, strict_after, strict_prob)`, `Brain.events`, `Brain.strict` (Task 3); `Controller._jev_alert` with CS-706 and CS-707 (Task 4).
- Produces:
  - `jev_bridge.routes(options, cf) -> list[Route]`; `build()` sets `brain.routes` (names, in order).
  - `jev_bridge.runtime_alerts(c, room)`, called by `publish()` on every pass.
  - `sensor.crop_steering_{prefix}jev` attributes add `daily_budget`, `routes`, `last_route`, `retries_today`, `failovers_today`, `reasks_today`; `sensor.crop_steering_{prefix}zone_{n}_jev` attributes add `strict` (the judges on the stricter gate for that zone).
  - Options `jev_daily_calls` (5000), `jev_budget_warn_pct` (80), `jev_retries` (3), `jev_reask_max` (2), `jev_unsure_below` (0.7), `jev_strict_after` (3), `jev_strict_prob` (0.8).

- [ ] **Step 1: Write the failing tests**

In `addons/f2_control/tests/test_jev_runtime.py`, replace `test_a_typesafe_key_is_used_before_cloudflare` with:

```python
def test_every_route_jev_has_is_used_typesafe_first():
    import jev_bridge
    from jev.client import Routes, call, call_typesafe

    both = jev_bridge.build({"typesafe_api_key": "apikey_x"}, ("acct", "tok", ""), "/tmp/state.json", lambda *a: None)
    assert isinstance(both.asker.transport, Routes) and both.routes == ["TypeSafe", "Cloudflare"]
    assert [(r.fn, r.token) for r in both.asker.transport.routes] == [(call_typesafe, "apikey_x"), (call, "tok")]
    cf_only = jev_bridge.build({}, ("acct", "tok", ""), "/tmp/state.json", lambda *a: None)
    assert cf_only.routes == ["Cloudflare"] and cf_only.asker.daily_budget == 5000
    assert jev_bridge.build({}, ("", "", ""), "/tmp/state.json", lambda *a: None) is None


def test_an_old_options_file_keeps_its_budget_and_takes_the_new_defaults():
    import jev_bridge

    f2_3_8_0 = {"typesafe_api_key": "apikey_x", "jev_enabled": True, "jev_judges": "all",
                "jev_daily_calls": 2000, "jev_flower_start": "", "jev_flower_days": 56}
    brain = jev_bridge.build(f2_3_8_0, ("", "", ""), "/tmp/state.json", lambda *a: None)
    assert brain.routes == ["TypeSafe"] and brain.asker.daily_budget == 2000
    assert (brain.reask_max, brain.unsure_below, brain.strict_after, brain.strict_prob) == (2, 0.7, 3, 0.8)
    assert (brain.asker.warn_pct, brain.asker.transport.tries) == (80, 3)
```

In `addons/f2_control/tests/test_jev_controller.py`, the bridge now builds its transport with `Routes`, so the fixtures stand in for `Routes` instead of passing a transport to `Asker`. In the `jev_with` fixture replace the two `monkeypatch.setattr(jev_bridge, "Asker", ...)` lines with:

```python
        monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: transport)
        monkeypatch.setattr(jev_bridge, "Asker", functools.partial(
            Asker, threaded=False, clock=lambda: NOW.timestamp()))
```

and in `test_the_options_choose_the_judges` replace its `monkeypatch.setattr(jev_bridge, "Asker", ...)` with:

```python
    monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: K.FakeTransport({}))
    monkeypatch.setattr(jev_bridge, "Asker", functools.partial(Asker, threaded=False))
```

Then append:

```python
def _created(fake, code):
    return [d["notification_id"] for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and f"({code})" in d["title"]]


def test_the_jev_sensor_shows_the_routes_the_budget_and_the_stricter_gate(jev_with):
    c, fake = jev_with({})
    _p1_zone(c)  # in its ramp: nothing fires, so the pass takes no shot time
    for _ in range(3):
        c.jev.ledger.resolve(c.jev.ledger.record("ramp", "default", 1, "P2", "advance"), "fell back", False)
    c.loop_once(NOW)
    room = fake.sets["sensor.crop_steering_jev"][1]
    assert room["routes"] == ["Cloudflare"] and room["daily_budget"] == 5000
    assert {"last_route", "retries_today", "failovers_today", "reasks_today"} <= set(room)
    assert fake.sets["sensor.crop_steering_zone_1_jev"][1]["strict"] == ["ramp"]


def test_jev_pushes_once_when_todays_calls_reach_80_percent(jev_with):
    c, fake = jev_with({})
    _p1_zone(c)  # in its ramp, so the Ramp judge is asked: the day's first call
    c.jev.asker.daily_budget = 1  # and that call is all of the budget
    c.loop_once(NOW)
    assert _created(fake, "CS-706") == ["f2_jev_budget_default"]
    c.loop_once(NOW + timedelta(minutes=1))
    assert len(_created(fake, "CS-706")) == 1


def test_jev_pushes_when_a_judge_goes_on_the_stricter_gate(jev_with):
    c, fake = jev_with({})
    _p1_zone(c)
    c.jev.events.append(("strict", "default", 1, "ramp"))
    c.loop_once(NOW)
    assert _created(fake, "CS-707") == ["f2_jev_ramp_default_z1"] and c.jev.events == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_jev_runtime.py addons/f2_control/tests/test_jev_controller.py -q`
Expected: the five new tests fail (`AttributeError: 'Brain' object has no attribute 'routes'`, `AttributeError: <module 'jev_bridge'> does not have the attribute 'Routes'` from the fixtures, `KeyError: 'routes'`).

- [ ] **Step 3: Build from the options**

In `addons/f2_control/f2_control/jev_bridge.py`, the import:

```python
from jev.client import Asker, Route, Routes, call, call_typesafe
```

Replace `build` with:

```python
def routes(options, cf):
    """Every route Jev has, in the order they are tried: TypeSafe direct when its key is set, then Cloudflare's
    /ai/run when its account and token are."""
    account, token, gateway = cf
    found = []
    typesafe = str(options.get("typesafe_api_key") or "").strip()
    if typesafe:
        found.append(Route("TypeSafe", call_typesafe, "typesafe", typesafe))
    if account and token:
        found.append(Route("Cloudflare", call, account, token, gateway or None))
    return found


def build(options, cf, state_path, log):
    """The brain, or None when Jev is off (no route: no TypeSafe key and no Cloudflare credentials; or `jev_enabled`
    false). Every route it has is used, TypeSafe first, each retried while a failure may pass (jev.client.Routes)."""
    found = routes(options, cf)
    if options.get("jev_enabled", True) is False or not found:
        return None
    wanted = str(options.get("jev_judges") or "all").replace(" ", "")
    allowed = set(ALL) if wanted in ("", "all") else set(wanted.split(",")) & set(ALL)
    first = found[0]
    asker = Asker(first.account, first.token, first.gateway, daily_budget=int(options.get("jev_daily_calls", 5000)),
                  transport=Routes(found, tries=int(options.get("jev_retries", 3))),
                  warn_pct=float(options.get("jev_budget_warn_pct", 80)))
    data = os.path.dirname(state_path) or "."
    ledger = Ledger(os.path.join(data, "jev_ledger.jsonl"))
    names = [r.name for r in found]
    log(f"jev: on via {' then '.join(names)}, judges {', '.join(sorted(allowed))}, {asker.daily_budget} calls a day")
    brain = Brain(asker, ledger, judges(), allowed=allowed, log=log,
                  reask_max=int(options.get("jev_reask_max", 2)),
                  unsure_below=float(options.get("jev_unsure_below", 0.7)),
                  strict_after=int(options.get("jev_strict_after", 3)),
                  strict_prob=float(options.get("jev_strict_prob", 0.8)))
    brain.routes = names
    brain.journal = Journal(os.path.join(data, "jev_journal.jsonl"))
    brain.setpoints = SetpointMemory(os.path.join(data, "jev_setpoints.json"))
    brain.usage_path = os.path.join(data, "jev_usage.json")
    restore_usage(asker, brain.usage_path)
    brain.triage = Triage(asker) if "alerts" in allowed else None
    brain.flower_start = flower_option(options.get("jev_flower_start"))
    brain.flower_days = int(options.get("jev_flower_days") or 56)
    return brain
```

- [ ] **Step 4: Push and publish**

In `jev_bridge.py`, add before `publish`:

```python
def runtime_alerts(c, room):
    """CS-706 once a day when Jev's calls reach the warning share of the budget, and CS-707 when one of this room's
    zones has a judge go on the stricter gate (Brain.events)."""
    brain, asker = c.jev, c.jev.asker
    if asker.take_warning():
        c._jev_alert(room, None, "budget", {
            "code": "CS-706", "title": "Jev has used most of today's calls",
            "message": (f"Jev has made {asker.stats.get('calls')} of its {asker.daily_budget} calls today, across "
                        "every room. Once they are spent, the engine's own rules decide until midnight. Raise "
                        "jev_daily_calls in the app's options if this happens on an ordinary day.")})
    mine = [e for e in brain.events if e[1] == room.slug]
    brain.events = [e for e in brain.events if e[1] != room.slug]
    for _kind, _room, zone, judge in mine:
        c._jev_alert(room, zone, judge, {
            "code": "CS-707", "title": "Jev is on the stricter gate for this zone",
            "message": (f"Jev's {judge} judge made {brain.strict_after} calls in a row for this zone that did not "
                        f"work out. Until two in a row do, it acts only when both phrasings agree at "
                        f"{brain.strict_prob:g} or more and a second look gives the same answer. Jev keeps judging; "
                        "whenever it is not sure enough, the engine's own rules act.")})
```

Replace `publish` with:

```python
def publish(c, room, now, ha_set):
    brain = c.jev
    runtime_alerts(c, room)
    s = brain.asker.stats
    managed = None
    if owns_setpoints(c):
        managed = (c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)
                   and not getattr(room, "strategy_required", False))
    for zone in room.zones:
        status = brain.zone_status(room.slug, zone)
        acting = sorted(n for n, v in status.items() if v.get("directive") and not str(v.get("why", "")).startswith("refused"))
        strict = sorted(j for (r, z, j), on in brain.strict.items() if on and r == room.slug and z == zone)
        attrs = {"judges": status, "strict": strict, "friendly_name": f"Zone {zone} Jev", "engine": "f2-control"}
        sp = setpoints_published(c, room, zone, now, managed)
        if sp is not None:
            attrs["setpoints"] = sp
        ha_set(f"sensor.crop_steering_{room.prefix}zone_{zone}_jev", ", ".join(acting) or "watching", attrs)
    save_usage(brain)
    ha_set(f"sensor.crop_steering_{room.prefix}jev", "error" if s.get("last_error") and not s.get("last_call") else "on",
           {"calls_today": s.get("calls"), "daily_budget": brain.asker.daily_budget,
            "input_tokens_today": s.get("input_tokens"), "errors_today": s.get("errors"),
            "last_error": s.get("last_error"), "retries_today": s.get("retries"),
            "failovers_today": s.get("failovers"), "reasks_today": s.get("reasks"),
            "routes": list(getattr(brain, "routes", [])), "last_route": s.get("route"),
            "judges": sorted(j.name for j in brain.judges), "judge_errors": dict(brain.errors),
            "stage": stage_info(c, room, now), "friendly_name": "Jev", "engine": "f2-control"})
    journal = getattr(brain, "journal", None)
    if journal is not None:
        entries = journal.recent(room.slug)
        ha_set(f"sensor.crop_steering_{room.prefix}jev_log", headline(entries[0] if entries else None),
               {"entries": entries, "friendly_name": "Jev decisions", "engine": "f2-control"})
```

- [ ] **Step 5: The options**

In `addons/f2_control/config.yaml`, under `options:`:

```yaml
  jev_daily_calls: 5000
  jev_budget_warn_pct: 80
  jev_retries: 3
  jev_reask_max: 2
  jev_unsure_below: 0.7
  jev_strict_after: 3
  jev_strict_prob: 0.8
  jev_flower_start: ""
```

and under `schema:`:

```yaml
  jev_daily_calls: int?
  jev_budget_warn_pct: int?
  jev_retries: int?
  jev_reask_max: int?
  jev_unsure_below: float?
  jev_strict_after: int?
  jev_strict_prob: float?
  jev_flower_start: str?
```

In `addons/f2_control/translations/en.yaml`, replace the `jev_daily_calls` entry with:

```yaml
  jev_daily_calls:
    name: Jev calls a day
    description: >-
      The most calls Jev gets in a day across every room (default 5000). Once spent,
      the engine decides alone until midnight.
  jev_budget_warn_pct:
    name: Warn at this share of Jev's calls (%)
    description: >-
      When the day's calls reach this share of the budget above (default 80), the app
      raises CS-706, once that day.
  jev_retries:
    name: Tries per Jev route
    description: >-
      How many times each route to Jev is tried while it is busy, failing or slow
      (default 3), inside 60 seconds. A refused key moves straight on to the next route.
  jev_reask_max:
    name: Second looks when Jev is unsure
    description: >-
      When an answer is under the sureness below, or its two phrasings disagree, Jev is
      asked again with more evidence, up to this many times (default 2). Then the engine
      decides.
  jev_unsure_below:
    name: Jev is unsure below
    description: >-
      An answer with a probability under this (default 0.7) is unsure, and is asked again.
  jev_strict_after:
    name: Bad calls before the stricter gate
    description: >-
      After this many of a judge's calls in a row did not work out for a zone (default 3),
      that judge acts there only when it is very sure and a second look agrees, until two
      calls in a row work. The app raises CS-707.
  jev_strict_prob:
    name: Sureness on the stricter gate
    description: >-
      How sure an answer must be to act on the stricter gate (default 0.8).
```

- [ ] **Step 6: The docs**

In `docs/JEV.md`, "Failing safe": replace its paragraph with:

```markdown
Jev is optional at every level: no TypeSafe key and no Cloudflare credentials, `jev_enabled` off, a judge left out of
`jev_judges`, the daily budget spent, every route down, or an answer that fails to parse: each means that judge's
decisions are the base engine's, unchanged. Jev is reached over every route it has, TypeSafe direct first and then
Cloudflare's `/ai/run`; each is tried up to `jev_retries` times inside 60 seconds while its failure may pass (a busy
or failing server, a timeout), and a refused key moves straight on. A question that waited more than five minutes
behind failing calls is dropped unasked, because its evidence is stale. When Jev is unsure (an answer under
`jev_unsure_below`, or two phrasings that disagree) it is asked again with more evidence, up to `jev_reask_max`
times, before the engine decides. After `jev_strict_after` of a judge's calls in a row did not work out for a zone,
that judge is on the stricter gate there: it acts only when both phrasings agree at `jev_strict_prob` or more and a
second look gives the same call, until two calls in a row work. Jev keeps judging throughout.
```

In its configuration table, replace the `jev_daily_calls` row with:

```markdown
| `jev_daily_calls` | 5000 | The day's call budget across rooms. |
| `jev_budget_warn_pct` | 80 | CS-706 once a day when the calls reach this share of the budget. |
| `jev_retries` | 3 | Tries per route, inside 60 seconds, while a failure may pass. |
| `jev_reask_max` | 2 | Second looks, with more evidence, when Jev is unsure. |
| `jev_unsure_below` | 0.7 | Under this probability, or with phrasings that disagree, an answer is unsure. |
| `jev_strict_after` | 3 | Bad calls in a row before a judge is on the stricter gate for a zone (CS-707). |
| `jev_strict_prob` | 0.8 | How sure an answer must be to act on the stricter gate. |
```

and in the `typesafe_api_key` row, replace "Used when set." with "Tried first when set; Cloudflare, when set too, is the second route."

In "What Jev can raise", replace the first sentence's list with:

```markdown
Seven codes, in their own group of the error-code list (docs/ERROR_CODES.md): **CS-701** water isn't reaching a
zone, **CS-702** a zone's water per plant is out of line, **CS-703** an overnight low looks like a probe fault,
**CS-704** Jev set a zone's probe aside, **CS-705** a zone is off its stage's arc, **CS-706** Jev has used most of
today's calls, **CS-707** a judge is on the stricter gate for a zone. The controller raises them through one method with each code written
out, so a judge can never raise anything the list does not explain.
```

In `addons/f2_control/DOCS.md`, replace the option bullets under `## Jev` (from `typesafe_api_key` to `jev_flower_days`) with:

```markdown
- `typesafe_api_key`: a TypeSafe API key (`apikey_...`). Tried first when set.
- `cf_account_id` and `cf_api_token`, with `cf_gateway_id` optional: or Jev through Cloudflare Workers AI (with a TypeSafe key as well, Cloudflare is the second route). The token needs the **Workers AI** permission: dash.cloudflare.com, My Profile, API Tokens, Create Token, Workers AI template.
- `jev_enabled`: off runs the plain engine even with a key set.
- `jev_judges`: the judges that may act, `all` or a list such as `dawn,ramp,salt,dusk,probe,shot,night,zones,stage,setpoints,alerts`.
- `jev_daily_calls`: the day's call budget across rooms (5000); `jev_budget_warn_pct` raises CS-706 at 80 % of it.
- `jev_retries`, `jev_reask_max`, `jev_unsure_below`, `jev_strict_after`, `jev_strict_prob`: how hard the app tries to reach Jev (3 tries per route), how often it asks again when Jev is unsure (twice, under 0.7), and when a judge goes on the stricter gate (3 bad calls in a row; then it needs 0.8 and an agreeing second look).
- `jev_flower_start`: each room's first day of 12/12, as a date or an input_datetime, for every room or as `room=value` pairs, so Jev knows today's stage.
- `jev_flower_days`: the cultivar's flowering length (56).
```

In `README.md`, the "Cap what it can spend" row:

```markdown
| Cap what it can spend | App option `jev_daily_calls` (5,000 by default; CS-706 at 80 %). Once the day's calls are spent, the rest of that day's decisions are the plain engine's. |
```

- [ ] **Step 7: The seeded 3.8.0 options**

Create `tests_ha/fixtures/options_3_8_0_f2.json`, F2's app options as 3.8.0 saved them, the TypeSafe key replaced:

```json
{
 "_about": "F2's controller app options as 3.8.0 saved them in /data/options.json (2 Oct 2026), the TypeSafe key replaced. 3.8.0 had no second route, retries, re-asks or stricter gate, and a 2000-call budget.",
 "options": {
  "num_zones": 3,
  "lights_on_hour": 10,
  "lights_off_hour": 22,
  "enable_flag": "input_boolean.f2_control_enabled",
  "notify_service": "script/crop_steering_push",
  "notify_min": 30,
  "instance_name": "Crop Steering",
  "feed_ec_sensor": "",
  "feed_ph_sensor": "",
  "sump_power_sensor": "default=sensor.f2_sump_pump_power",
  "sump_silent_hours": 3,
  "hold_entities": [],
  "substrate_l": 5,
  "flow_lps": 0.02,
  "loop_seconds": 60,
  "rediscover_seconds": 300,
  "cf_account_id": "",
  "cf_api_token": "",
  "cf_gateway_id": "",
  "typesafe_api_key": "apikey_seeded",
  "jev_enabled": true,
  "jev_judges": "all",
  "jev_daily_calls": 2000,
  "jev_flower_start": "",
  "jev_flower_days": 56
 }
}
```

In `tests_ha/test_upgrade_in_place.py`, after the test plan 1 added (or after `test_the_controller_carries_straight_on_after_the_upgrade_without_a_disarm_cycle` if plan 1 is not in this branch):

```python
async def test_3_8_0_app_options_keep_their_jev_budget_and_take_the_new_defaults(
    hass, controller_for
):
    """F2's 3.8.0 options (tests_ha/fixtures/options_3_8_0_f2.json) start Jev on the TypeSafe
    route with the owner's 2000 calls, and every new setting at its default."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    options = fixture("options_3_8_0_f2.json")["options"]
    c, _fake, _clock = controller_for(options)
    assert c.jev is not None and c.jev.routes == ["TypeSafe"]
    assert c.jev.asker.daily_budget == 2000  # the owner's value stays until the owner changes it
    settings = (c.jev.reask_max, c.jev.unsure_below, c.jev.strict_after, c.jev.strict_prob)
    assert settings == (2, 0.7, 3, 0.8)
    assert (c.jev.asker.warn_pct, c.jev.asker.transport.tries) == (80, 3)
```

- [ ] **Step 8: Run everything touched**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q`
Expected: all pass.

Run: `yamllint addons/f2_control/config.yaml addons/f2_control/translations/en.yaml`
Expected: no output.

Run the real-Home-Assistant tier as in Task 4 Step 2, for `tests_ha/test_upgrade_in_place.py tests_ha/test_notify_controller.py`. Expected: all pass; the new upgrade test fails before Step 3 with `AttributeError: 'Brain' object has no attribute 'routes'`.

- [ ] **Step 9: Commit**

```bash
git add addons/f2_control/f2_control/jev_bridge.py addons/f2_control/config.yaml addons/f2_control/translations/en.yaml docs/JEV.md addons/f2_control/DOCS.md README.md addons/f2_control/tests/test_jev_runtime.py addons/f2_control/tests/test_jev_controller.py tests_ha/fixtures/options_3_8_0_f2.json tests_ha/test_upgrade_in_place.py
git commit -m "Build Jev from the new options, push CS-706 and CS-707, publish routes and counts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The whole branch, and the pull request

**Files:** none changed.

- [ ] **Step 1: Run everything CI runs**

Run: `bash tests/run_ci.sh`
Expected: `ALL CHECKS PASSED`, or, with the real-Home-Assistant tier run separately in WSL, `bash tests/run_ci.sh --allow-skip` ending `PARTIAL: real Home Assistant tier skipped` and nothing else failed.

- [ ] **Step 2: Push the branch and open the pull request into `testing`**

```bash
git push -u origin feat/dryback-02-jev-availability
gh pr create --repo JakeTheRabbit/HA-Crop-Steering-Jev --base testing --head feat/dryback-02-jev-availability \
  --title "Jev availability: both routes, retries, second looks, the stricter gate (dryback planner, step 2)" --body-file pr-body.md
```

`pr-body.md` (outside the repository):

```markdown
Step 2 of the dryback planner: docs/superpowers/plans/2026-10-02-dryback-00-roadmap.md.

- **Both routes.** TypeSafe direct first, then Cloudflare `/ai/run` when its account and token are set. Each route gets 3 tries inside 60 s while a failure may pass (429, 5xx, a timeout); a refused key moves straight on.
- **Stale questions.** A question that waited more than 5 minutes behind failing calls is dropped unasked.
- **Second looks.** An answer under 0.7, or with phrasings that disagree, is asked again at once with more evidence (the last answer, the sibling zones), up to twice.
- **The stricter gate.** After 3 calls in a row of one judge did not work out for a zone, that judge acts there only at 0.8 with an agreeing second look, until two calls in a row work. Read from the ledger, so it survives a restart. CS-707 when a judge goes on it.
- **Budget.** 5000 a day by default, CS-706 at 80 %. A box keeps its own `jev_daily_calls` until its owner changes it.
- `sensor.crop_steering_jev` shows the routes, the budget and today's retries, failovers and second looks; each zone's Jev sensor lists the judges on the stricter gate.

**Class: C3** (add-on options). Seeded snapshot: `tests_ha/fixtures/options_3_8_0_f2.json` (`tests_ha/test_upgrade_in_place.py::test_3_8_0_app_options_keep_their_jev_budget_and_take_the_new_defaults`). Real-Home-Assistant routing test: `tests_ha/test_notify_controller.py::test_jevs_own_alerts_reach_the_phone_that_ticks_jev`. Both fail without this change.

After installing on F2: set `jev_daily_calls` to 5000 in the app's options (it stays 2000 until then), and set `cf_account_id` and `cf_api_token` for the second route (F2 has the TypeSafe key only).

Soak checks (7 days on staging):
- `retries_today` and `failovers_today` move only when a route really failed (compare `last_error`);
- `reasks_today` stays a small share of `calls_today`;
- fault drill: a wrong TypeSafe key with Cloudflare set moves every call to Cloudflare, no alert storm; both wrong: errors counted, watering unchanged;
- rollback rehearsal: 3.8.0 starts with these options present (it ignores keys it does not read).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 3: Leave it for the owner**

Do not merge. Report the pull request's address and its CI result.
