"""What the controller's environment tells it about how it runs, and the checks it makes before it starts.

runtime(): the Home Assistant app ("addon") or a standalone container ("container"). The Supervisor
tells the app (config.yaml `environment: F2_RUNTIME: addon`); that counts only together with the
Supervisor's own token and no HA_URL, so no single copied variable makes a container act as the app.

stop_budget(): how long the safe-off on SIGTERM may take (Controller._safe_exit). The Supervisor
waits `timeout: 30` (config.yaml) after SIGTERM before it kills the app, so the app's budget of 25 s
leaves 5 s for the process to end; a container's compose file waits 90 s (`stop_grace_period`), so
with F2_RUNTIME=container its budget is 75 s. Anything else keeps 25 s, as a budget longer than the
stop timeout is cut off part-way. Set it with F2_STOP_BUDGET_S, and keep the stop timeout at least
the budget plus 5 s.

resolve_base(), resolve_token(), preflight(): where Home Assistant's API is, the token to use, and
the checks made before the controller is built. Nothing here switches anything; importing it never
raises or exits, and only preflight() exits or parks.

state_path(), load_options(): where the controller keeps its state (F2_DATA_DIR, /data by default) and
its options: options.json there, with any F2_OPT_<OPTION> environment variable over it. The app's file
is read as it is, because the Supervisor has checked it against config.yaml's schema; a container's
file is checked here against OPTION_TYPES instead, and a value of the wrong type stops it (exit 2).
"""
import json
import math
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

DEFAULT_BASE = "http://supervisor/core/api"
STOP_BUDGET_S = 25.0  # the app: the Supervisor's `timeout: 30` less 5 s
CONTAINER_STOP_BUDGET_S = 75.0  # a container: compose's `stop_grace_period: 90s` less 15 s
# The admin probe writes this one state: only an administrator's token may write a state, and the
# controller writes its heartbeat and status. Nothing reads it.
RUNTIME_ENTITY = "sensor.crop_steering_controller_runtime"
RETRY_S, RETRY_LOG_S = 10.0, 60.0  # Home Assistant not answering yet (booting)
TZ_WAIT_S = 300.0  # how long to wait for Home Assistant's time zone (F2_TZ_WAIT_S)
# A refused token with a record the previous run left: ask again every 60 s for 10 min, then every
# 15 min, because the refusal may come from a proxy in front of Home Assistant that recovers.
PROBE_FAST_S, PROBE_FAST_FOR_S, PROBE_SLOW_S = 60.0, 600.0, 900.0
TOKEN_FILE_CHECK_S = 30.0  # while parked: a new token in HA_TOKEN_FILE starts the controller again


def log(*a):
    print("[Crop Steering Controller]", *a, flush=True)


def _not_addon(env):
    """Why this process is not the Home Assistant app, or None when it is."""
    if env.get("F2_RUNTIME") != "addon":
        return f"F2_RUNTIME is {env.get('F2_RUNTIME') or 'unset'}"
    if not env.get("SUPERVISOR_TOKEN"):
        return "no SUPERVISOR_TOKEN"
    if env.get("HA_URL"):
        return "HA_URL is set"
    return None


def runtime(env):
    """"addon" only with F2_RUNTIME=addon, a SUPERVISOR_TOKEN and no HA_URL; else "container"."""
    return "container" if _not_addon(env) else "addon"


def stop_budget(env):
    """Seconds the safe-off on SIGTERM may take: F2_STOP_BUDGET_S when it is a number above 0, else
    CONTAINER_STOP_BUDGET_S only when F2_RUNTIME=container says so, and STOP_BUDGET_S otherwise. A longer
    budget than the stop timeout gets the safe-off killed part-way, so an app that lost its F2_RUNTIME
    (and so counts as a container) keeps the app's."""
    default = CONTAINER_STOP_BUDGET_S if env.get("F2_RUNTIME") == "container" else STOP_BUDGET_S
    try:
        budget = float(env.get("F2_STOP_BUDGET_S") or default)
    except (TypeError, ValueError):
        return default
    return budget if math.isfinite(budget) and budget > 0 else default


def resolve_base(env):
    """Home Assistant's API address: HA_URL without surrounding spaces or a trailing /, with /api
    added unless it is there; DEFAULT_BASE (the Supervisor's proxy) when HA_URL is unset."""
    url = (env.get("HA_URL") or "").strip().rstrip("/")
    if not url:
        return DEFAULT_BASE
    return url if url.endswith("/api") else url + "/api"


def _read_token_file(path):
    """(the file's contents without surrounding spaces, None), or ("", what is wrong with it)."""
    if os.path.isdir(path):
        return "", "is a directory"
    try:
        with open(path, encoding="utf-8") as fh:
            token = fh.read().strip()
    except FileNotFoundError:
        return "", "does not exist"
    except (OSError, UnicodeDecodeError):
        return "", "can't be read"
    return (token, None) if token else ("", "is empty")


def resolve_token(env):
    """(token, the variable it came from), or ("", None). The app: SUPERVISOR_TOKEN, then HA_TOKEN.
    A container: HA_TOKEN, then the contents of the file HA_TOKEN_FILE names, then SUPERVISOR_TOKEN."""
    if runtime(env) == "addon":
        order = ("SUPERVISOR_TOKEN", "HA_TOKEN")
    else:
        order = ("HA_TOKEN", "HA_TOKEN_FILE", "SUPERVISOR_TOKEN")
    for name in order:
        value = env.get(name) or ""
        if name == "HA_TOKEN_FILE" and value:
            value = _read_token_file(value)[0]
        if value:
            return value, name
    return "", None


def data_dir(env):
    return env.get("F2_DATA_DIR") or "/data"


def state_path(env):
    """state.json: F2_STATE_PATH (the tests' seam), else in F2_DATA_DIR, else /data/state.json. Every other
    file the controller keeps (dosing_state.json, the AI assistant's jev_* files) lives beside it."""
    return env.get("F2_STATE_PATH") or os.path.join(data_dir(env), "state.json")


def options_path(env):
    return env.get("F2_OPTIONS_PATH") or os.path.join(data_dir(env), "options.json")


def _shot_recorded(doc):
    if not isinstance(doc, dict):
        return True
    blocks = [doc] if any(str(k).isdigit() for k in doc) else doc.values()
    return any(isinstance(b, dict) and b.get("_shot_inflight") is not None for b in blocks)


def _dose_recorded(doc):
    rooms = doc.get("rooms", {}) if isinstance(doc, dict) else None
    if not isinstance(rooms, dict):
        return True
    return any(isinstance(b, dict) and isinstance(b.get("inflight"), dict) for b in rooms.values())


def recorded(state_path):
    """True when the previous run left something that may still be running: a shot in flight in
    state.json, a dose or batch in flight in dosing_state.json beside it, or either file there but
    unreadable (what was running is then not known). A missing file records nothing. Read only:
    nothing is written, renamed or switched."""
    dosing = os.path.join(os.path.dirname(state_path) or ".", "dosing_state.json")
    for path, found in ((state_path, _shot_recorded), (dosing, _dose_recorded)):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return True
        if found(doc):
            return True
    return False


def _unwritable(folder):
    """Why nothing can be saved in `folder` (as state.json is: a temporary file, then os.replace), or
    None when it can."""
    probe = os.path.join(folder, ".f2-write-check")
    try:
        with open(probe + ".tmp", "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.replace(probe + ".tmp", probe)
        os.remove(probe)
    except OSError as e:
        return e.strerror or type(e).__name__
    return None


def _follows(zone):
    """True when this process's local time keeps `zone` (musl runs a name it does not know as UTC)."""
    try:
        offset = datetime.now(ZoneInfo(zone)).utcoffset()
    except Exception:
        return False
    return offset is not None and time.localtime().tm_gmtoff == int(offset.total_seconds())


def _adopt(zone):
    """Run this process on `zone` and say whether it took."""
    try:
        ZoneInfo(zone)
    except Exception:
        return False
    os.environ["TZ"] = zone
    if hasattr(time, "tzset"):
        time.tzset()
    return _follows(zone)


def _shown(base):
    """`base` for the log, without any user name or password in it."""
    parts = urlsplit(base)
    if "@" not in parts.netloc:
        return base
    return parts._replace(netloc="***@" + parts.netloc.rsplit("@", 1)[1]).geturl()


def _why(error):
    """What a failed request says about the way to Home Assistant, for the log."""
    text = repr(error)
    if isinstance(error, requests.exceptions.SSLError):
        return "TLS error: Home Assistant's certificate is not trusted here (set REQUESTS_CA_BUNDLE)"
    if isinstance(error, requests.exceptions.Timeout):
        return "no answer in time"
    if any(s in text for s in ("NameResolution", "Name does not resolve", "Name or service not known",
                               "Temporary failure in name resolution", "nodename nor servname")):
        return "the host name does not resolve here (in HA_URL, use Home Assistant's IP address)"
    return f"not reachable ({type(error).__name__})"


def _positive(value, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and number > 0 else default


def next_probe(waited):
    """Seconds after the first refusal at which to ask again: every 60 s for 10 min, then every 15 min."""
    if waited < PROBE_FAST_FOR_S:
        return (math.floor(waited / PROBE_FAST_S) + 1) * PROBE_FAST_S
    return PROBE_FAST_FOR_S + (math.floor((waited - PROBE_FAST_FOR_S) / PROBE_SLOW_S) + 1) * PROBE_SLOW_S


def _refusal(request, status):
    if status == 403:
        return (f"Home Assistant refuses this machine, probably an IP ban: {request} -> HTTP 403. Remove "
                "this machine's address from ip_bans.yaml and restart Home Assistant.")
    if request.startswith("POST"):
        return (f"the token's user must be an administrator: {request} -> HTTP {status}. Make that user "
                "an administrator, or use a long-lived access token of one.")
    return (f"HA rejected the token: {request} -> HTTP {status}. Put a valid long-lived access token of a "
            "Home Assistant administrator in HA_TOKEN_FILE (or HA_TOKEN).")


class _Preflight:
    def __init__(self, env, http, sleep, clock, version):
        self.env, self.http, self.sleep, self.clock, self.version = env, http, sleep, clock, version
        self.base = resolve_base(env)
        self.token, self.source = resolve_token(env)
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def stop(self, why):
        """A setting that is wrong before Home Assistant is ever asked: say so and exit 2."""
        log(why)
        sys.exit(2)

    def addon(self):
        """The app: say how it runs and whether Home Assistant answers, never more. The controller is
        then built exactly when it always was."""
        log(f"runtime: addon | stop budget: {stop_budget(self.env):g} s | base: {_shown(self.base)}"
            f" | token: {self.source or 'absent'}")
        try:
            r = self.http.get(self.base + "/", headers=self.headers, timeout=5)
            log(f"Home Assistant: GET {_shown(self.base)}/ -> HTTP {r.status_code}")
        except requests.RequestException as e:
            log(f"Home Assistant: GET {_shown(self.base)}/ -> {_why(e)}")

    def container(self, close_only):
        why = _not_addon(self.env)
        named = self.env.get("F2_RUNTIME") == "container"
        log("runtime: container" + ("" if named else f" (not the app: {why})"))
        log(f"stop budget: {stop_budget(self.env):g} s")
        # Settings that are wrong before Home Assistant is asked: exit 2, no request sent.
        path = self.env.get("HA_TOKEN_FILE")
        if not self.env.get("HA_TOKEN") and path:
            problem = _read_token_file(path)[1]
            if problem:
                self.stop(f"HA_TOKEN_FILE {path} {problem}: put only the long-lived access token of a "
                          "Home Assistant administrator in it")
        if not self.token:
            self.stop("no Home Assistant token: set HA_TOKEN_FILE to a file holding the long-lived access "
                      "token of a Home Assistant administrator (or set HA_TOKEN)")
        log(f"token: {self.source}" + (" (outside the Home Assistant app)" if self.source == "SUPERVISOR_TOKEN"
                                       else ""))
        if not (self.env.get("HA_URL") or "").strip():
            self.stop("HA_URL is not set: set it to Home Assistant's own address, e.g. "
                      "http://<home-assistant-ip>:8123")
        parts = urlsplit(self.base)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            self.stop(f"HA_URL {_shown(self.base)} is not an http:// or https:// address")
        log(f"base: {_shown(self.base)}")
        self.state_path = state_path(self.env)
        folder = os.path.dirname(self.state_path) or "."
        problem = _unwritable(folder)
        if problem:
            self.stop(f"data folder {folder} is not writable ({problem}): the shot-in-flight record and the "
                      "rest of the state are saved there")
        try:
            load_options(self.env)
        except OptionsError as e:
            self.stop(str(e))
        self.zone = self.env.get("TZ") or ""
        if self.zone and not _follows(self.zone):
            self.stop(f"TZ={self.zone} is not a time zone this image knows: set it to Home Assistant's "
                      "zone (e.g. Europe/Berlin), or leave it empty to follow Home Assistant")
        self.reach(close_only)

    def reach(self, close_only):
        """Ask Home Assistant until it accepts this token as an administrator's. A refusal parks."""
        parked_at, said = None, None
        while True:
            refused = self.ask_all()
            if refused is None:
                return
            if refused != said:
                log(_refusal(*refused))
                said = refused
            if not recorded(self.state_path):
                log("parked: nothing the last run started is recorded, so nothing more is sent to Home "
                    "Assistant until the token changes or the controller is restarted")
                self.park()
            if refused[0].startswith("POST") and refused[1] == 401 and close_only is not None:
                log("the last run left a shot or a dose recorded: closing it with this token, then parked")
                close_only()
                self.park()
            if parked_at is None:
                log("parked: the last run left a shot or a dose recorded, so Home Assistant is asked again "
                    "every 60 s for 10 min, then every 15 min")
                parked_at = self.clock()
            due = parked_at + next_probe(self.clock() - parked_at)
            while due > self.clock():
                self.sleep(min(due - self.clock(), TOKEN_FILE_CHECK_S))
                self.new_token()

    def ask_all(self):
        """None when Home Assistant accepts every request, else the refused (request, status)."""
        shown = _shown(self.base)
        r = self.ask("GET", "/")
        if r.status_code in (401, 403):
            return f"GET {shown}/", r.status_code
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code != 200 or not isinstance(body, dict) or body.get("message") != "API running.":
            self.stop(f"HA_URL does not point at Home Assistant's API: GET {shown}/ -> HTTP {r.status_code}"
                      " without Home Assistant's answer. Use Home Assistant's own address and port.")
        if not self.zone:
            refused = self.adopt_zone()
            if refused:
                return refused
        r = self.ask("POST", "/states/" + RUNTIME_ENTITY,
                     {"state": "container", "attributes": {"controller_version": self.version}})
        if r.status_code in (401, 403):
            return f"POST {shown}/states/{RUNTIME_ENTITY}", r.status_code
        if r.status_code not in (200, 201):
            self.stop(f"HA_URL does not point at Home Assistant's API: POST {shown}/states/{RUNTIME_ENTITY}"
                      f" -> HTTP {r.status_code}")
        return None

    def ask(self, method, path, data=None):
        """One request, sent again every 10 s while Home Assistant can't be reached or answers 5xx."""
        logged = None
        while True:
            try:
                if method == "GET":
                    r = self.http.get(self.base + path, headers=self.headers, timeout=8)
                else:
                    r = self.http.post(self.base + path, headers=self.headers, json=data, timeout=8)
                if r.status_code < 500:
                    return r
                why = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                why = _why(e)
            if logged is None or self.clock() - logged >= RETRY_LOG_S:
                log(f"Home Assistant is not answering yet ({method} {_shown(self.base)}{path}: {why}); "
                    "trying again every 10 s")
                logged = self.clock()
            self.sleep(RETRY_S)

    def adopt_zone(self):
        """Run on Home Assistant's time zone (TZ is empty), never on UTC by default: exit 2 when it can't
        be read in F2_TZ_WAIT_S. A refused token is returned like any other refusal."""
        until = self.clock() + _positive(self.env.get("F2_TZ_WAIT_S"), TZ_WAIT_S)
        logged = None
        while True:
            zone, why = None, None
            try:
                r = self.http.get(self.base + "/config", headers=self.headers, timeout=8)
                if r.status_code in (401, 403):
                    return f"GET {_shown(self.base)}/config", r.status_code
                body = r.json() if r.status_code == 200 else None
                zone = body.get("time_zone") if isinstance(body, dict) else None
                why = f"HTTP {r.status_code}" if r.status_code != 200 else "no time_zone in its answer"
            except (requests.RequestException, ValueError) as e:
                why = _why(e) if isinstance(e, requests.RequestException) else "an answer that is not JSON"
            if zone and _adopt(str(zone)):
                log(f"timezone: adopted Home Assistant's zone {zone}")
                self.zone = str(zone)
                return None
            if zone:
                why = f"its zone {zone} is not one this image knows"
            if self.clock() >= until:
                self.stop(f"could not read Home Assistant's time zone ({why}); set TZ in .env to it")
            if logged is None or self.clock() - logged >= RETRY_LOG_S:
                log(f"waiting for Home Assistant's time zone ({why}); trying again every 10 s")
                logged = self.clock()
            self.sleep(RETRY_S)

    def park(self):
        """Send nothing more. A new token in HA_TOKEN_FILE exits 0, so the restart policy starts the
        controller again on it; SIGTERM exits at once."""
        while True:
            self.sleep(TOKEN_FILE_CHECK_S)
            self.new_token()

    def new_token(self):
        if self.source != "HA_TOKEN_FILE":
            return
        token = _read_token_file(self.env["HA_TOKEN_FILE"])[0]
        if token and token != self.token:
            log("HA_TOKEN_FILE has a new token: starting again with it")
            sys.exit(0)


def preflight(close_only=None, env=None, *, version="unknown", http=requests, sleep=time.sleep,
              clock=time.monotonic):
    """Check, before the controller is built, that it can run safely (nothing here switches anything).

    The app: one GET of Home Assistant's API, logged, whatever the answer; nothing else.

    A container: a missing token, a bad HA_TOKEN_FILE, an unset or non-http HA_URL, a data folder that
    can't be written and a TZ this image does not know each exit 2 before Home Assistant is asked.
    Then `GET <base>/` must answer Home Assistant's "API running." (while it can't be reached or
    answers 5xx it is asked again every 10 s; any other answer exits 2), an empty TZ adopts Home
    Assistant's zone, and the admin probe writes RUNTIME_ENTITY. When all are accepted it returns.

    A 401 or 403 never exits: exiting would hand the retry to the restart policy, which sends the
    same refused token again on every start and walks into Home Assistant's IP ban. It parks: one
    log line names the request, the answer and the fix. With nothing recorded by the previous run
    nothing more is sent. With a shot or dose recorded (recorded()), whatever was running may still
    be, and the refusal may come from a proxy that recovers, so the refused requests are sent again
    every 60 s for 10 min, then every 15 min, and once accepted it carries on as above, so the
    controller is built and closes what is recorded. A token that works but is not an
    administrator's, with a record, calls `close_only` once (it closes the recorded hardware with
    this token and switches nothing on), then parks. A changed HA_TOKEN_FILE exits 0; SIGTERM exits
    0 at once."""
    env = os.environ if env is None else env
    check = _Preflight(env, http, sleep, clock, version)
    if runtime(env) == "addon":
        check.addon()
        return
    main = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)) if main else None
    try:
        check.container(close_only)
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


# ------------------------------------------------------------------ options
# The type of every option the controller reads: config.yaml's `schema:` (a test keeps the two equal),
# plus feed_grace_min and blind_fallback_min, which the code reads but the schema does not offer, and
# zones and hardware, which only a test or hand-built rig writes, in the file. "?" marks an option the
# app may leave out; "password" is a secret, never logged or echoed.
OPTION_TYPES = {
    "num_zones": "int",
    "lights_on_hour": "float",
    "lights_off_hour": "float",
    "enable_flag": "str",
    "notify_service": "str?",
    "notify_min": "float",
    "instance_name": "str?",
    "feed_ec_sensor": "str?",
    "feed_ph_sensor": "str?",
    "sump_power_sensor": "str?",
    "sump_silent_hours": "float?",
    "hold_entities": "[str]",
    "substrate_l": "float",
    "flow_lps": "float",
    "loop_seconds": "float",
    "rediscover_seconds": "float",
    "brain_provider": "list(auto|rules|claude_haiku|jev_legacy)?",
    "stage_arc": "list(slab_default)?",
    "anthropic_api_key": "password?",
    "anthropic_model": "str?",
    "anthropic_base_url": "str?",
    "anthropic_daily_budget_usd": "float(0,1000)?",
    "brain_dry_run": "bool?",
    "ai_judges": "str?",
    "ai_daily_calls": "int?",
    "ai_budget_warn_pct": "int?",
    "ai_reask_max": "int?",
    "ai_unsure_below": "float?",
    "ai_strict_after": "int?",
    "ai_strict_prob": "float?",
    "ai_flower_start": "str?",
    "ai_flower_days": "int?",
    "cf_account_id": "str?",
    "cf_api_token": "password?",
    "cf_gateway_id": "str?",
    "typesafe_api_key": "password?",
    "jev_enabled": "bool?",
    "jev_judges": "str?",
    "jev_daily_calls": "int?",
    "jev_budget_warn_pct": "int?",
    "jev_retries": "int?",
    "jev_reask_max": "int?",
    "jev_unsure_below": "float?",
    "jev_strict_after": "int?",
    "jev_strict_prob": "float?",
    "jev_flower_start": "str?",
    "jev_flower_days": "int?",
    "feed_grace_min": "float",
    "blind_fallback_min": "float",
    "zones": "dict",
    "hardware": "dict",
}
SECRET_KEYS = frozenset(k for k, t in OPTION_TYPES.items() if t.rstrip("?") == "password")
ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_TRUE, _FALSE = ("true", "1", "yes", "on"), ("false", "0", "no", "off")
_JSON_TYPE = {bool: "true or false", int: "a number", float: "a number", str: "a string", list: "a list",
              dict: "an object", type(None): "null"}


class OptionsError(ValueError):
    """An option that can't be used: the message names the file or variable and the key, never the value."""


def _choices(kind):
    found = re.fullmatch(r"list\((.*)\)", kind)
    return found.group(1).split("|") if found else None


def _ranged(kind):
    """A Supervisor number type with its range, e.g. float(0,1000) -> ("float", (0.0, 1000.0)); else (kind, None)."""
    found = re.fullmatch(r"(int|float)\(([-\d.]+),([-\d.]+)\)", kind)
    return (found.group(1), (float(found.group(2)), float(found.group(3)))) if found else (kind, None)


def _outside(bounds, number):
    """Why `number` is outside a range type's `bounds`, or None."""
    if bounds and not bounds[0] <= number <= bounds[1]:
        return f"expected a number from {bounds[0]:g} to {bounds[1]:g}"
    return None


def _expected(kind):
    if _choices(kind):
        return "one of " + ", ".join(_choices(kind))
    return {"int": "a whole number", "float": "a number", "bool": "true or false", "[str]": "a list of entity ids",
            "dict": "an object"}.get(kind, "text")


def _not_entity_ids(items):
    bad = [i for i in items if i and not ENTITY_ID.match(i)]
    return f"{bad[0]!r} is not an entity id" if bad else None


def _file_value_problem(kind, value):
    """Why a JSON value from a container's options file is not of `kind`, or None when it is."""
    kind, bounds = _ranged(kind.rstrip("?"))
    if _choices(kind):
        ok = value in _choices(kind)
    else:
        ok = {
            "int": isinstance(value, int) and not isinstance(value, bool),
            "float": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
            "bool": isinstance(value, bool),
            "dict": isinstance(value, dict),
            "[str]": isinstance(value, list) and all(isinstance(i, str) for i in value),
        }.get(kind, isinstance(value, str))
    if not ok:
        hint = '; write ["input_boolean.a", "input_boolean.b"]' if kind == "[str]" else ""
        return f"expected {_expected(kind)}, got {_JSON_TYPE.get(type(value), 'something else')}{hint}"
    return _not_entity_ids(value) if kind == "[str]" else _outside(bounds, value)


def _coerced(kind, text):
    """An environment value (always a string) as `kind` -> (value, None), or (None, why it is not)."""
    kind, bounds = _ranged(kind.rstrip("?"))
    if kind == "int":
        found = re.fullmatch(r"[+-]?\d+", text.strip())
        return (int(found.group(0)), None) if found else (None, "expected a whole number")
    if kind == "float":
        try:
            number = float(text)
        except ValueError:
            number = math.nan
        if not math.isfinite(number):
            return None, "expected a number"
        return (None, _outside(bounds, number)) if _outside(bounds, number) else (number, None)
    if kind == "bool":
        word = text.strip().lower()
        return (word in _TRUE, None) if word in _TRUE + _FALSE else (None, "expected true or false")
    if kind == "[str]":
        if not text.strip().startswith("["):
            return [i.strip() for i in text.split(",") if i.strip()], None
        try:
            items = json.loads(text)
        except ValueError:
            items = None
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            return items, None
        return None, "expected a JSON list of entity ids"
    if _choices(kind):
        return (text, None) if text in _choices(kind) else (None, f"expected {_expected(kind)}")
    return text, None


def _read_options_file(path, container, log):
    """The options file. The app's as it is ({} when it is missing or can't be read, as always). A
    container's checked against OPTION_TYPES: unknown keys named and dropped, a null optional dropped."""
    try:
        with open(path, encoding="utf-8") as fh:
            opts = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError):
        if container:
            raise OptionsError(f"options file {path}: not readable") from None
        return {}
    except ValueError as e:
        if container:
            where = f" (line {e.lineno}, column {e.colno})" if hasattr(e, "lineno") else ""
            raise OptionsError(f"options file {path}: not valid JSON{where}") from None
        return {}
    if not container:
        return opts
    if not isinstance(opts, dict):
        raise OptionsError(f"options file {path}: expected a JSON object")
    name, checked = os.path.basename(path), {}
    for key, value in opts.items():
        kind = OPTION_TYPES.get(key)
        if kind is None:
            if log:
                log(f"option {key} ({name}): unknown, ignored")
            continue
        if value is None and kind.endswith("?"):
            continue
        problem = _file_value_problem(kind, value)
        if problem:
            raise OptionsError(f"option {key} ({name}): {problem}")
        checked[key] = value
    return checked


def _options_from_env(env, container, log):
    """Every F2_OPT_<OPTION>, as its option's type, and for a password F2_OPT_<OPTION>_FILE (the file's
    contents) when F2_OPT_<OPTION> is not set. A value that can't be used stops a container
    (OptionsError) and is left out of the app's options, with a log line."""
    names = {"F2_OPT_" + key.upper(): key for key in OPTION_TYPES}
    files = {name + "_FILE": key for name, key in names.items() if key in SECRET_KEYS}
    found = {}

    def refuse(message):
        if container:
            raise OptionsError(message)
        if log:
            log(message + "; ignored")

    for var in sorted(v for v in env if v.startswith("F2_OPT_") and v not in files):
        key = names.get(var)
        if key is None or OPTION_TYPES[key] == "dict":
            if log:
                log(f"option {var}: " + ("unknown, ignored" if key is None else "set it in the options file; ignored"))
            continue
        value, why = _coerced(OPTION_TYPES[key], env[var])
        if why:
            why += "" if key in SECRET_KEYS else f", got {env[var]!r}"
        elif OPTION_TYPES[key] == "[str]" and container:
            why = _not_entity_ids(value)
        if why:
            refuse(f"option {var}: {why}")
        else:
            found[key] = value
    for var, key in sorted(files.items()):
        if key in found or not env.get(var):
            continue
        value, problem = _read_token_file(env[var])
        if problem and problem != "is empty":
            refuse(f"option {var}: file not readable")
        else:
            found[key] = value
    if "anthropic_api_key" not in found and env.get("ANTHROPIC_API_KEY"):  # the usual name, below F2_OPT_* only
        found["anthropic_api_key"] = env["ANTHROPIC_API_KEY"]
    return found


def describe(path, from_file, from_env):
    """The options log line: where they came from, the names taken from the environment, and every
    secret only as <set> or <unset>."""
    opts = {**from_file, **from_env}
    secrets = ", ".join(f"{k}={'<set>' if opts.get(k) else '<unset>'}" for k in sorted(SECRET_KEYS))
    from_env_part = f" + env ({', '.join(sorted(from_env))})" if from_env else ""
    return f"options: {path} ({len(from_file)} keys){from_env_part} | {secrets}"


def load_options(env, log=None):
    """The controller's options: the file at options_path() with every F2_OPT_<OPTION> over it.

    The app (runtime "addon"): the file exactly as the Supervisor wrote it, or {} when it is missing or
    can't be read, as always; with no F2_OPT_* set (the Supervisor sets none) that is all. A container:
    nobody has checked its file, so a file that can't be read, is not a JSON object or holds a value of
    the wrong type (OPTION_TYPES), and an environment value that can't be used, raise OptionsError,
    naming the key and never the value; unknown keys are named and dropped. A missing file is {} in
    both."""
    container = runtime(env) == "container"
    path = options_path(env)
    from_file = _read_options_file(path, container, log)
    from_env = _options_from_env(env, container, log)
    if log:
        log(describe(path, from_file if isinstance(from_file, dict) else {}, from_env))
    if not from_env:
        return from_file
    return {**(from_file if isinstance(from_file, dict) else {}), **from_env}
