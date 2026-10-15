"""What the controller's environment tells it about how it runs, and the checks it makes before it starts.

runtime(): the Home Assistant app ("addon") or a standalone container ("container"). The Supervisor
tells the app (config.yaml `environment: F2_RUNTIME: addon`); that counts only together with the
Supervisor's own token and no HA_URL, so no single copied variable makes a container act as the app.

stop_budget(): how long the safe-off on SIGTERM may take (Controller._safe_exit). The Supervisor
waits `timeout: 30` (config.yaml) after SIGTERM before it kills the app, so the app's budget of 25 s
leaves 5 s for the process to end; a container's compose file waits 90 s (`stop_grace_period`), so
its budget is 75 s. Raise the stop timeout with F2_STOP_BUDGET_S, never to less than the budget
plus 5 s.

resolve_base(), resolve_token(), preflight(): where Home Assistant's API is, the token to use, and
the checks made before the controller is built. Nothing here switches anything; importing it never
raises or exits, and only preflight() exits or parks.
"""
import json
import math
import os
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
    print("[f2-control]", *a, flush=True)


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
    STOP_BUDGET_S for the app and CONTAINER_STOP_BUDGET_S for a container."""
    default = STOP_BUDGET_S if runtime(env) == "addon" else CONTAINER_STOP_BUDGET_S
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


def _state_path(env):
    return env.get("F2_STATE_PATH") or "/data/state.json"


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
        return "the name in HA_URL does not resolve here (use Home Assistant's IP address)"
    return f"not reachable ({type(error).__name__})"


def _positive(value, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and number > 0 else default


def _next_probe(waited):
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
        self.state_path = _state_path(self.env)
        folder = os.path.dirname(self.state_path) or "."
        problem = _unwritable(folder)
        if problem:
            self.stop(f"data folder {folder} is not writable ({problem}): the shot-in-flight record and the "
                      "rest of the state are saved there")
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
            due = parked_at + _next_probe(self.clock() - parked_at)
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
