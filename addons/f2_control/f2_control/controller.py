# -*- coding: utf-8 -*-
"""Crop Steering Controller: the standalone crop-steering controller (a Home Assistant add-on).

The synchronous I/O shell: ONE sync process, plain REST polling of HA, no asyncio, no
coroutine trap. Imports the pure crop-steering-engine for decisions; this file is
the thin IO shell (read sensors -> decide -> drive valves with readback) plus
durable state, status republish, a 30-min vitals notification, and a hard kill-switch.

Multi-room (Stage 2): the engine drives EVERY configured room. The default room is
un-prefixed (entity ids exactly as a single-room install) and is built from the add-on
options. Additional rooms are discovered from the integration's published
`sensor.crop_steering_<prefix>engine_config` descriptors; each is a fully self-contained
control loop — own zones, hardware (pump/mainline/valves), kill switch, feed gate,
photoperiod and durable state, namespaced `crop_steering_<slug>_*`. New rooms are
fail-safe OFF until their per-room kill switch is turned on. The rooms share only this
one process (one shot fires at a time) and the notify service.

Talks to HA through the Supervisor proxy (http://supervisor/core/api) with the
auto-injected SUPERVISOR_TOKEN as the app, or as a standalone container to HA_URL with HA_TOKEN(_FILE)
(runtime_env). Safe-offs the hardware on exit.
"""
import dataclasses
import json
import math
import os
import re
import signal
import sys
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
import auto_setpoints
import curve_tracker
import dosing_runner
import jev_bridge
import jev_policy
import runtime_env
import setpoint_supervisor
import zone_history
from strategy_runtime import parse_snapshot, parameter_override, strategy_block

from crop_steering_engine import (
    EC_SETTLE_MIN,
    Reason,
    decide,
    waiting_for,
    ZoneParams,
    ZoneSnapshot,
    validate_params,
    pick_sibling,
    feed_grace_ok,
    cross_zone_outliers,
    detect_vmax,
    zone_safety_status,
    system_safety_status,
    zone_status_label,
    settled_reading,
)
from crop_steering_engine.core import SETTLED_VWC_MIN
# What _zone_num falls back to when neither the zone's nor the room's setting can be read: the
# controller column of the one defaults table, pinned to the values installed controllers use.
from crop_steering_engine.defaults import CONTROLLER_FALLBACKS as FALLBACK
# Every number read from a device goes through the one device-unit table (_device).
from crop_steering_engine.defaults import UNITS, to_canonical
# What depends on what a room grows in (its substrate select): "generic" is what every room ran on before.
from crop_steering_engine.defaults import SUBSTRATE_PROFILES

# The product's name, in every text a user reads: the log, the `engine` attribute's value and the
# kill-switch hold. Machine ids (the app slug, sensor.f2_control_vitals, /data files) keep theirs.
PRODUCT = "Crop Steering Controller"

# ---------------------------------------------------------------- HA REST (Supervisor proxy, or HA_URL)
BASE = runtime_env.resolve_base(os.environ)
TOKEN = runtime_env.resolve_token(os.environ)[0]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
_S = requests.Session()  # the main loop's
_LOCAL = threading.local()


def _session():
    """The calling thread's own requests.Session: the main loop's is _S, and any other thread (the
    dosing thread, dosing_runner.py) gets one of its own. A Session is not safe to share between
    threads, and the dosing thread reads every second while a shot's reads run on the main loop."""
    if threading.current_thread() is threading.main_thread():
        return _S
    session = getattr(_LOCAL, "session", None)
    if session is None:
        session = _LOCAL.session = requests.Session()
    return session


def log(*a):
    print(f"[{PRODUCT}]", *a, flush=True)


class _AuthGate:
    """What a 401 or 403 from Home Assistant does to the requests below (runtime_env.preflight checks the
    token before the controller is built; this is for one refused later).

    The app: nothing, apart from one log line every 10 min at most; its requests go through the
    Supervisor's proxy, which never bans it. A standalone container: Home Assistant counts every refused
    request as a failed login and may ban the machine, so the gate closes and requests are not sent:
      * "all" (a 401 or 403 on a read or a service call, or a 403 on a state write): nothing is sent but
        this process's own close of what it has on (own(): the shot in flight's valve, main line and
        pump, and the running dose's or batch's hardware): each its one turn_off, and reads of those
        back until the first is refused. The shot ends at _wait_shot's next check, a dose or batch the
        way it ends when the app stops, and the main loop parks (Controller._park_refused). The refusal
        may come from a proxy in front of Home Assistant that recovers, so any accepted answer opens
        the gate again.
      * "writes" (a 401 on a state write only: the token's user is no longer an administrator): state
        writes are not sent; reads and service calls are, so the shot in flight closes as usual.
    A request the gate holds back returns its function's usual failure, with no request sent."""

    LOG_EVERY_S = 600.0

    def __init__(self):
        self.container = runtime_env.runtime(os.environ) == "container"
        self.state = None  # None (open), "all" or "writes"
        self.own = lambda: ()  # set by the Controller: what this process has switched on now
        self._lock = threading.Lock()
        self._sent = set()  # what has had its one turn_off while closed
        self._read_refused = False
        self._probe = None  # the one read the park sends (Controller._park_refused)
        self._logged = None  # the app: when the last refusal was logged

    def allows(self, kind, entity=None):
        """Whether a request may be sent: kind "read" (of one entity), "off" (a turn_off), "write" (a
        state), or "other"."""
        with self._lock:
            if self.state is None:
                return True
            if self.state == "writes":
                return kind != "write"
            if kind == "read" and entity is not None and entity == self._probe:
                return True
            if kind == "off" and entity in set(self.own()) - self._sent:
                self._sent.add(entity)
                return True
            return kind == "read" and entity in self._sent and not self._read_refused

    def saw(self, kind, status, request):
        """Note Home Assistant's answer to a request that was sent."""
        refused = status in (401, 403)
        with self._lock:
            if not self.container:
                now = time.monotonic()
                if refused and (self._logged is None or now - self._logged >= self.LOG_EVERY_S):
                    self._logged = now
                    log(f"Home Assistant rejected a request: {request} -> HTTP {status}")
                return
            if not refused:
                if self.state == "all" and status is not None and status < 500:
                    self.state = None
                    log("Home Assistant refused a request, then accepted one: probably a proxy in front of it")
                return
            if kind == "write" and status == 401 and self.state is None:
                self.state = "writes"
                log(f"Home Assistant refused a state write: {request} -> HTTP 401. The token's user must be "
                    "an administrator: the shot in flight is closed, then the controller waits.")
            elif self.state != "all":
                self.state, self._sent, self._read_refused = "all", set(), False
                log(f"Home Assistant refused a request: {request} -> HTTP {status}. Only the close of what "
                    "this controller has on is sent; then it waits, asking again while anything is recorded.")
            elif kind == "read":
                self._read_refused = True

    def probe(self, entity):
        """One read of `entity` while closed: the park's question whether Home Assistant accepts again."""
        self._probe = entity
        try:
            return ha_get(entity)
        finally:
            self._probe = None


_GATE = _AuthGate()


class HAState(tuple):
    """What ha_get returns: (state, attributes, last_updated), unpacked exactly as it always was, plus
    `last_changed`: when the state VALUE last changed, as Home Assistant reports it (None if unknown).
    `served_at` (ha_get_status only): Home Assistant's own time of the answer, from its Date header."""

    served_at = None

    def __new__(cls, state=None, attributes=None, last_updated=None, last_changed=None):
        obj = super().__new__(cls, (state, {} if attributes is None else attributes, last_updated))
        obj.last_changed = last_changed
        return obj


def ha_get(entity, timeout=8):
    """Return (state_str, attributes, last_updated_iso) or (None, {}, None); see HAState."""
    if not _GATE.allows("read", entity):
        return HAState()
    try:
        r = _session().get(f"{BASE}/states/{entity}", headers=HDR, timeout=timeout)
        _GATE.saw("read", r.status_code, f"GET {BASE}/states/{entity}")
        if r.status_code != 200:
            return HAState()
        d = r.json()
        return HAState(d.get("state"), d.get("attributes", {}), d.get("last_updated"), d.get("last_changed"))
    except Exception:
        return HAState()


def ha_get_status(entity, timeout=8):
    """(HTTP status, HAState) of one entity: the status ha_get drops, 404 for a state Home Assistant
    does not have, None when nothing answered. Its HAState carries `served_at`."""
    if not _GATE.allows("read", entity):
        return None, HAState()
    try:
        r = _session().get(f"{BASE}/states/{entity}", headers=HDR, timeout=timeout)
        _GATE.saw("read", r.status_code, f"GET {BASE}/states/{entity}")
        if r.status_code != 200:
            return r.status_code, HAState()
        d = r.json()
        found = HAState(d.get("state"), d.get("attributes", {}), d.get("last_updated"), d.get("last_changed"))
        try:
            found.served_at = parsedate_to_datetime(r.headers.get("Date"))
        except (TypeError, ValueError):
            pass
        return 200, found
    except Exception:
        return None, HAState()


def _aware(stamp):
    """An ISO timestamp -> timezone-aware datetime, or None (missing, malformed or naive)."""
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def ha_get_all():
    """Return the full /api/states list (or [] on failure). Used once at startup for
    multi-room discovery — find every sensor.crop_steering_*engine_config descriptor."""
    if not _GATE.allows("other"):
        return []
    try:
        r = _session().get(f"{BASE}/states", headers=HDR, timeout=12)
        _GATE.saw("other", r.status_code, f"GET {BASE}/states")
        if r.status_code != 200:
            return []
        return r.json() or []
    except Exception:
        return []


def ha_history(entity, since, timeout=12):
    """Every state `entity` has had from `since` (an aware datetime) to now, oldest first, as
    [(state, last_changed_iso), ...]; the first is the state it was already in at `since`.
    None when Home Assistant can't say: unreachable, an error, or nothing recorded for it."""
    if not _GATE.allows("other"):
        return None
    try:
        r = _session().get(
            f"{BASE}/history/period/{since.isoformat()}",
            headers=HDR,
            params={
                "filter_entity_id": entity,
                "end_time": datetime.now(timezone.utc).isoformat(),
                "minimal_response": "",
                "no_attributes": "",
            },
            timeout=timeout,
        )
        _GATE.saw("other", r.status_code, f"GET {BASE}/history/period")
        if r.status_code != 200:
            return None
        rows = (r.json() or [[]])[0]
        return [(row.get("state"), row.get("last_changed")) for row in rows] or None
    except Exception:
        return None


def ha_call(domain, service, *, timeout=12, **data):
    kind = "off" if service == "turn_off" else "other"
    if not _GATE.allows(kind, data.get("entity_id")):
        return False
    try:
        r = _session().post(
            f"{BASE}/services/{domain}/{service}", headers=HDR, json=data, timeout=timeout
        )
        _GATE.saw(kind, r.status_code, f"POST {BASE}/services/{domain}/{service}")
        if r.status_code >= 300:
            log("call_service FAILED", domain, service, "HTTP", r.status_code)
            return False
        return True
    except Exception as e:
        log("call_service failed", domain, service, e)
        return False


def ha_service_response(domain, service, data, timeout=12):
    """Call a service asking for its answer (?return_response, for a service that answers when asked:
    crop_steering.stock_draw) -> (HTTP status, the service's answer), or (None, None) when Home
    Assistant can't be reached. The status tells a refusal (4xx: sending it again changes nothing)
    from a failure worth trying again."""
    if not _GATE.allows("other"):
        return None, None
    try:
        r = _session().post(
            f"{BASE}/services/{domain}/{service}", headers=HDR, json=data,
            params={"return_response": ""}, timeout=timeout,
        )
    except Exception as e:
        log("call_service failed", domain, service, e)
        return None, None
    _GATE.saw("other", r.status_code, f"POST {BASE}/services/{domain}/{service}")
    if r.status_code >= 300:
        log("call_service FAILED", domain, service, "HTTP", r.status_code)
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body.get("service_response") if isinstance(body, dict) else None


def ha_fire(event, data, timeout=4):
    """Fire a Home Assistant event, best effort -> True when Home Assistant took it."""
    try:
        r = _session().post(f"{BASE}/events/{event}", headers=HDR, json=data, timeout=timeout)
        return r.status_code < 300
    except Exception:
        return False


def ha_set(entity, state, attributes=None, timeout=8):
    """Write a state -> Home Assistant's HTTP status, or None when it was not sent or not answered."""
    if not _GATE.allows("write"):
        return None
    try:
        r = _session().post(
            f"{BASE}/states/{entity}",
            headers=HDR,
            json={"state": state, "attributes": attributes or {}},
            timeout=timeout,
        )
    except Exception:
        return None
    _GATE.saw("write", r.status_code, f"POST {BASE}/states/{entity}")
    return r.status_code


# ---------------------------------------------------------------- config (defaults; override via options.json or F2_OPT_*)
def load_options():
    """The add-on options: /data/options.json as the Supervisor wrote it, or a container's own (checked)
    with F2_OPT_<OPTION> over it (runtime_env.load_options)."""
    return runtime_env.load_options(os.environ, log)


def read_controller_version(module_dir=None):
    """This app's own version, from the config.yaml it was BUILT from: the very file Supervisor
    reads, so there is no second number to keep in step. The Dockerfile copies it next to this
    module as addon.yaml; in a source checkout it is one directory up. "unknown" rather than a
    guess when neither is readable."""
    here = module_dir or os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "addon.yaml"), os.path.join(here, os.pardir, "config.yaml")):
        try:
            with open(path, encoding="utf-8") as fh:
                found = re.search(r"""^version:\s*["']?([^"'\s#]+)""", fh.read(), re.M)
        except OSError:
            continue
        if found:
            return found.group(1)
    return "unknown"


CONTROLLER_VERSION = read_controller_version()

# config.yaml's shipped lights option. It matches the facility this was first written for, so a
# legacy room may rely on it; on a wizard-made room it is a value nobody chose.
SHIPPED_LIGHTS = (10.0, 22.0)

# A zone with no usable moisture reading, by why: title and the advice that fits. The codes and
# their full entries live in docs/error-codes.json with every other code.
_PROBE_ALERTS = {
    "CS-101": (
        "moisture reading hasn't changed",
        "This is normal for a cube with no plant in it: nothing is drinking, so the number "
        "doesn't move. With a plant in it, check the probe is still in its cube: one pulled out "
        "reads steady too. Watering goes back to normal by itself once the reading changes (this "
        "notification stays until you dismiss it); in an empty room, switching Room Active off "
        "stops these notifications.",
    ),
    "CS-102": (
        "moisture sensor not reporting",
        "Check the probe is powered and online, and that the zone's moisture sensor is mapped "
        "correctly in Rooms & setup.",
    ),
    "CS-103": (
        "moisture reading out of range",
        "Check the probe's calibration, and that the sensor mapped to this zone reports moisture "
        "in %.",
    ),
    "CS-503": (
        "moisture probe set aside for its unit",
        "Map this zone to the probe's moisture reading in % (or m³/m³), or correct the sensor's "
        "unit in its own integration. The probe counts again as soon as its reading can be used.",
    ),
}

# What follows a shot cancelled before its water started (CS-302, CS-303, CS-304): _execute_shot's
# error cleanup switches off everything the shot may have opened and latches a hardware hold unless
# it all reads back OFF, which it can't while Home Assistant is unreachable.
_CANCELLED_SHOT_CLEANUP = (
    "The controller switches off the pump, main line and valve and checks they read OFF. If that "
    "can't be confirmed (Home Assistant unreachable, or a switch offline), it latches a hardware "
    "hold (CS-301) and nothing on this hardware is watered until the hold is cleared; otherwise "
    "the next shot is tried as normal."
)

# Switch read-back after a close: see Controller._confirm_switches.
CONFIRM_FIRST_READ_S, CONFIRM_POLL_S, CONFIRM_TIMEOUT_S = 1.0, 0.5, 6.0
CONFIRM_RETRY_S = 10.0  # a second read-back, after OFF is sent again to what still reads on

# The safe-off on SIGTERM (Controller._safe_exit) runs inside runtime_env.stop_budget(). Dosing keeps
# STOP_DOSING_S of it (a fifth at most) for its own offs while a dose or batch has anything recorded.
# Each room with a shot recorded gets an equal share of the rest (see _Stop).
STOP_DOSING_S = 5.0


class _Stop:
    """A part of the stop's budget: it ends at `until` on the monotonic clock. A read inside it waits only
    as long as leaves time for the `keep` switch-offs it may prove, each as long as the slowest Home
    Assistant call of this stop so far (`slowest`, shared by every part of one stop), and the second's
    pause after a valve's off; a read that could not come back in what that leaves is not made. So a
    slow Home Assistant costs reads, never the offs they prove, and a call is never cut shorter than
    Home Assistant is answering."""

    def __init__(self, until, slowest=None, keep=0):
        self.until, self.keep = until, keep
        self.slowest = [0.0] if slowest is None else slowest

    def keeping(self, keep):
        """This part, keeping time for `keep` offs after each read."""
        return _Stop(self.until, self.slowest, keep)

    def timeout(self, default, keep=None):
        """A read's timeout, or None when it would not come back in time (it is not made)."""
        keep = self.keep if keep is None else keep
        left, took = self.until - time.monotonic(), self.slowest[0]
        # Nothing timed yet: this read and the offs after it share what is left equally.
        free = (left - keep * took - (1.0 if keep > 1 else 0.0)) if took else left / (keep + 1)
        timeout = min(default, free)
        return timeout if timeout > 0 and timeout >= took else None

    def off_timeout(self, default, keep):
        """An off's timeout: as a read's, keeping time for the `keep` offs after it, else all that is left
        (the valve's off comes before the main line's, and that before the pump's); None when none is."""
        timeout = self.timeout(default, keep)
        if timeout is None:
            left = self.until - time.monotonic()
            timeout = min(default, left) if left > 0 else None
        return timeout

    def timed(self, call, *args, **kwargs):
        began = time.monotonic()
        try:
            return call(*args, **kwargs)
        finally:
            self.slowest[0] = max(self.slowest[0], time.monotonic() - began)


def _read(entity, deadline=None):
    """hw_get, inside the stop's `deadline` (a _Stop) when there is one: a read that no longer fits is
    not made and reads as unknown."""
    if deadline is None:
        return hw_get(entity)
    timeout = deadline.timeout(8)
    return HAState() if timeout is None else deadline.timed(hw_get, entity, timeout=timeout)


def _switch_off(entity, deadline=None, keep=0):
    """A switch's (or valve's) off, inside the stop's `deadline` when there is one, keeping time for `keep`
    offs after it -> whether Home Assistant took it. One that no longer fits is not sent."""
    if deadline is None:
        return hw_call(entity, False)
    timeout = deadline.off_timeout(12, keep)
    return timeout is not None and deadline.timed(hw_call, entity, False, timeout=timeout)


def _history(entity, since, deadline=None):
    if deadline is None:
        return hw_history(entity, since)
    timeout = deadline.timeout(12)
    return None if timeout is None else deadline.timed(hw_history, entity, since, timeout=timeout)


def _pause(seconds, deadline=None):
    time.sleep(seconds if deadline is None else max(0.0, min(seconds, deadline.until - time.monotonic())))


# How a switch failed to read OFF after a close (Controller._close_failures), in the words the
# hardware fault (CS-301) names it with: in its notification, its log line and the zone's status.
CLOSE_FAILURES = {
    "refused": "was not switched off: Home Assistant returned an error",
    "on": f"still read ON {CONFIRM_TIMEOUT_S + CONFIRM_RETRY_S:g} s after it was switched off",
    "unavailable": "read unavailable: Home Assistant could not reach it",
    "unknown": "read unknown instead of OFF",
    "unreadable": "could not be read from Home Assistant",
    "late": f"reported OFF only after the {CONFIRM_TIMEOUT_S + CONFIRM_RETRY_S:g} s check",
}

# The shortest shot the controller runs, in seconds (a shot sized shorter is lengthened to this).
MIN_SHOT_S = 5

# The minimum daily water stops once moisture is this many VWC points above field capacity.
MIN_FLOOR_FC_MARGIN = 5.0

# A probe unreadable for less than this many minutes is a blip (Home Assistant restarting, a sensor
# reconnecting): its zone gets no timer shot and no probe alert until it has been out this long.
BLIND_GRACE_MIN = 15
# The duplicate-controller guard (Controller.duplicate_hold): a room holds for this many seconds of this
# process's monotonic clock after the last pass that saw another controller write its heartbeat, and at
# start a heartbeat Home Assistant stamped less than this long ago counts as fresh.
DUPLICATE_HOLD_S = 180
# System Enabled and Auto Irrigation Enabled each stopped every shot, as the room's engine switch
# does, but less well: a shot already running carried on. The engine switch is the one switch now.
# While either still exists and reads off, the controller switches the engine switch off in its
# place, so a room someone stopped with one of them stays stopped (_carry_retired_switches).
RETIRED_SWITCHES = (
    ("system_enabled", "System Enabled"),
    ("auto_irrigation_enabled", "Auto Irrigation Enabled"),
)

# How each kind of on/off device a zone valve, main line or pump can be is opened, closed and read back:
# domain -> (open service, close service, open state, closed state). Every open, close and read-back of
# that hardware goes through it (hw_call, hw_get). A mapped entity of any other domain is never sent a
# command: its zone is held with CS-313 (_undrivable).
ACTUATORS = {
    "switch": ("turn_on", "turn_off", "on", "off"),
    "input_boolean": ("turn_on", "turn_off", "on", "off"),
    "valve": ("open_valve", "close_valve", "open", "closed"),
}


def hw_call(entity, on, **timeout):
    """Open (on=True) or close one zone valve, main line or pump -> whether Home Assistant took it.
    One whose domain is not in ACTUATORS is not sent anything, and that is a failure."""
    domain = entity.split(".", 1)[0]
    row = ACTUATORS.get(domain)
    return bool(row) and ha_call(domain, row[0] if on else row[1], entity_id=entity, **timeout)


def hw_state(entity, state):
    """A state of `entity` in on/off words: its domain's open state reads "on" and its closed state "off".
    Anything else (unavailable, opening, a domain not in ACTUATORS) is returned as it is."""
    row = ACTUATORS.get(entity.split(".", 1)[0])
    return {row[2]: "on", row[3]: "off"}.get(state, state) if row else state


def hw_get(entity, timeout=8):
    """ha_get for a zone valve, main line or pump, its state in on/off words (hw_state)."""
    read = ha_get(entity, timeout=timeout)
    return HAState(hw_state(entity, read[0]), read[1], read[2], getattr(read, "last_changed", None))


def hw_history(entity, since, **timeout):
    """ha_history for a zone valve, main line or pump, each state in on/off words (hw_state)."""
    rows = ha_history(entity, since, **timeout)
    return rows and [(hw_state(entity, state), stamp) for state, stamp in rows]


# What Controller._on reads as ON. A hold (hold_entities) in one of these states stops a shot starting
# (_blocked) and ends one in flight (_wait_shot): the same test, so the two can never disagree.
ON_STATES = ("on", "true", "open", "1", "home")

# The most the room's Pump Prime Time and Main Line Lead Time may make a shot wait, in seconds: the
# top of each setting.
PUMP_PRIME_MAX_S, MAIN_LINE_LEAD_MAX_S = 20.0, 10.0


def _lead_time(value, default, top):
    """A Pump Prime Time or Main Line Lead Time read, as the seconds to wait: from 0 to `top`, and
    `default` for a value that is not a number."""
    return max(0.0, min(top, value)) if math.isfinite(value) else float(default)


# A switch a shot opened changed state inside this window of the shot's recorded start, in seconds:
# the pump prime and the main-line lead (at most 20 s and 10 s) and, at worst, a slow Home Assistant
# acknowledging each command. A switch that changed outside it was already on, or has been touched by
# a person since, unless its recorded history shows only Home Assistant losing it and finding it
# again (_on_since_shot).
INFLIGHT_OPEN_WINDOW_S = (-5.0, 60.0)


def _on_since_shot(history, started):
    """Has a switch been ON since the shot opened it? -> True / False, or None when its history can't tell.

    `history` is ha_history's [(state, last_changed), ...] from the start of the opening window. The shot
    opened the switch if it turned ON inside INFLIGHT_OPEN_WINDOW_S of `started`. It stays the shot's
    while nothing but "unavailable" or "unknown" comes after: a Home Assistant restart or the switch
    reconnecting moves last_changed to that moment without anyone touching the switch. ON before the
    shot, first ON after the window, or an OFF after the shot opened it is a person's."""
    if not history or started is None:
        return None
    lo, hi = INFLIGHT_OPEN_WINDOW_S
    opened = False
    for state, stamp in history:
        when = _aware(stamp)
        if when is None:
            return None
        offset = (when - started).total_seconds()
        if state == "on":
            if offset < lo:
                return False  # already on before the shot
            if offset <= hi:
                opened = True
            elif not opened:
                return False  # first switched on after the shot
        elif state == "off":
            if opened:
                return False  # switched off since the shot opened it
        elif state not in ("unavailable", "unknown"):
            return None
    return True if opened else None

# The shots a plan hold never stops, by decide()'s Reason.kind. A plan decides how a zone is steered, not
# whether a starving zone gets water: while the plan is held, stale or missing, routine steering waits
# (decide() is asked for the rescues alone: ZoneSnapshot.steering_held), but the P3 emergency, the
# lights-on watchdog and the minimum-daily floor still fire, and so do a blind zone's safety schedule and
# its copy of a sibling's rescue, and a test shot a person asked for (its zone's Test Shot button). Every
# other gate (kill switch, faults, zone switches, source water, the daily budget) still applies to them.
PLAN_HOLD_EXEMPT = frozenset(
    {"p3_emergency", "watchdog", "min_daily", "blind_fallback", "blind_copy_rescue", "test_shot"}
)
TEST_SHOT_S = 10  # how long a zone's Test Shot waters it
# A Test Shot press older than this when the controller sees it is not acted on: the person testing is
# watching the drippers, and a shot long after they asked for it tests nothing for them.
TEST_REQUEST_S = 600.0

# A setting (a room's number) unreadable for fewer than this many passes is still loading: while Home Assistant
# starts or the integration reloads, its numbers are missing for a moment, and a shot sized on a guess is no shot.
# Every shot kind waits that long, as long as CS-402 waits before it says a setting is missing. After it, a
# setting runs on the last value read since the controller started, else on its built-in value (CS-402).
SETTINGS_WAIT_PASSES = 3
# The settings that size a zone's water. One never read since the controller started holds that zone, its
# rescues included (_settings_hold): a built-in plant count or daily limit is a guess at how much water goes in.
# Every other zone, and every other missing setting, carries on.
WATER_SIZING = ("substrate_volume", "plant_count", "drippers_per_plant", "dripper_flow_rate", "max_daily_volume")

# Who gets which phone push is the integration's, for the whole site (docs/NOTIFICATIONS.md): it publishes how
# many phones are set up, and the watering-stopped threshold, here. Read at most once a minute.
NOTIFY_CONFIG = "sensor.crop_steering_notify_config"
NOTIFY_CONFIG_S = 60.0
# How long crop_steering.notify may take to push to the phones: what a push to notify_service always could.
NOTIFY_TIMEOUT_S = 12
# The most one loop spends sending its phase changes and Jev's moves: they are only news, and the loop is not.
EVENTS_BUDGET_S = 10.0
# The codes whose severity is critical in docs/error-codes.json (tests/test_error_codes.py keeps the two equal):
# their push is urgent, a high-priority one on a phone whose row asks for that.
CRITICAL_CODES = frozenset({"CS-201", "CS-202", "CS-203", "CS-204", "CS-207", "CS-301", "CS-308", "CS-310",
                            "CS-311", "CS-402", "CS-601", "CS-606", "CS-801"})
# How often a standing alert pushes again, by its severity in docs/error-codes.json (tests/test_error_codes.py
# keeps INFO_CODES equal to the info codes): a critical code, or a warning that means a zone is not being watered,
# every 30 minutes for as long as it lasts; any other warning after 15 minutes, then 1, 2 and 4 hours, then every
# 8 hours; an info code once. Each episode starts the schedule again: an alert cleared (or not raised for
# ALERT_EPISODE_GAP_S) and raised again, or raised under another code. Held in memory only: a restart pushes once.
NOT_WATERING_CODES = frozenset({"CS-206", "CS-208", "CS-209", "CS-602"})
INFO_CODES = frozenset({"CS-205", "CS-305", "CS-403", "CS-501", "CS-702", "CS-705"})
WARNING_REPUSH_MIN = (15, 60, 120, 240, 480)
ALERT_EPISODE_GAP_S = 3600
# CS-310: a zone's moisture rising by BACKUP_RISE_PTS within BACKUP_WINDOW_MIN while no water went in, its valve
# closed for BACKUP_GRACE_MIN before (the wetting front of a shot keeps rising a while): water coming up from below,
# a table that isn't draining. Backtested on a production room's 22-30 Sep 2026 readings: the two real episodes (one
# zone filling from a stopped sump, 28 Sep 21:19 and 29 Sep 12:09) and nothing else. Cleared after BACKUP_CLEAR_MIN
# without a rise. Not watched in a room whose Drainage select says free_drain: nothing there can back up.
BACKUP_RISE_PTS, BACKUP_WINDOW_MIN, BACKUP_GRACE_MIN, BACKUP_CLEAR_MIN = 3.0, 60.0, 45.0, 60.0
# Field capacity follows the zone's highest readings (_follow_fc). When it moves by this many points or more, the P2
# re-water threshold moves with it; a smaller move is field capacity only. The rescue (P3 emergency) floor never moves.
# The room's substrate profile sets it (fc_shift_min); this is the generic profile's.
FC_SHIFT_MIN = SUBSTRATE_PROFILES["generic"]["fc_shift_min"]
# The most the follower moves any one setpoint in a grow-day, in points: a drifting probe or a flood can only drag the
# ladder this far a day.
FC_STEP_MAX = 1.0
FC_LADDER = ("field_capacity", "p1_target_vwc", "p2_vwc_threshold")  # what the follower moves
# The Vmax advisory's P1 wet-up series is kept in state.json (per zone) with at most this many readings.
VMAX_SERIES_MAX = 40
# CS-311: the sump pump a room drains to (option sump_power_sensor) drawing no power for SUMP_SILENT_H while the
# room is on. Observed on a production room: its sump ran every 1 to 1.5 hours, day and night, 22-28 Sep 2026 (its
# longest gap 2.37 h) and then not at all for 41.6 h: its tables backed up. Checked every SUMP_CHECK_MIN from Home
# Assistant's history, as a run lasts about a minute and a loop could miss it; a run is more than the room's Sump
# Pump Run Threshold, or SUMP_RUN_W where the integration has no such setting (compared in W, whatever unit the
# plug reports: _device_history).
SUMP_SILENT_H, SUMP_CHECK_MIN, SUMP_RUN_W = 3.0, 5.0, 20.0
# CS-312: a zone whose last MAX_RUN_IN_A_ROW shots were all cut to the room's maximum shot length (CS-306 each) keeps
# asking for more water than a shot may give, as a probe stuck dry does all day. With the room's max-run latch switch
# ON the zone is latched until its Repairs card is fixed; OFF, or absent (an older integration), it is only reported.
MAX_RUN_IN_A_ROW = 3
# The default room's kill switch on an installation from before the setup wizard: a helper the operator
# made by hand, and this app's shipped `enable_flag` option (config.yaml). A room made by the wizard stops
# on its own engine switch, named by its setup. Named here once; room_gate() is the rule.
LEGACY_ENABLE_FLAG = "input_boolean.f2_control_enabled"


def _pct_or_none(value):
    """A saved percentage (0-100) -> float, anything else -> None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and 0.0 <= v <= 100.0 else None


def room_option(value):
    """An option naming one entity for every room ("*"), or `room=entity` pairs, comma separated."""
    out = {}
    for part in str(value or "").split(","):
        name, sep, entity = part.strip().partition("=")
        if part.strip():
            out[name.strip() if sep else "*"] = (entity if sep else name).strip()
    return out
# CS-209: hours with the lights on, a zone in P1 or P2 and no shot in the room: the integration's idle_hours,
# kept inside 1 to 12, else 3.
IDLE_HOURS, IDLE_HOURS_RANGE = 3.0, (1.0, 12.0)

# A room's choice of how Water today reads, select.crop_steering_<prefix>water_today_view. The integration
# offers ["Zone total", PER_PLANT] (WATER_TODAY_VIEWS in its const.py); the vitals follow it.
PER_PLANT = "Per plant"

# What a room grows in, published as the descriptor's `substrate` from its substrate select. The
# integration offers the same ids (SUBSTRATES in its const.py). An integration from before the select
# publishes none, and a value this controller does not know reads as "generic": nothing changes.
SUBSTRATES = tuple(SUBSTRATE_PROFILES)


def _profile(room):
    """The room's substrate profile (defaults.SUBSTRATE_PROFILES): generic unless the room chose another."""
    return SUBSTRATE_PROFILES.get(getattr(room, "substrate", "generic"), SUBSTRATE_PROFILES["generic"])


_SIGN = {"<": "<", "<=": "≤", ">": ">", ">=": "≥"}


def _num(value):
    """A threshold or a reading for people: at most two decimals, none that are zero."""
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "?"


def next_text(conditions, at):
    """What would move a zone next, in one line: the engine's own conditions (waiting_for, as published on
    sensor.crop_steering_<prefix>zone_N_waiting_for_app) in the words of the dashboard's "Next:"
    (frontend/src/lib/waiting-for.ts waitingText). `at` is when they were worked out, a local time: a wait
    ends `in_min` after it. "" when there is nothing to say."""
    items = [c for c in conditions or [] if isinstance(c, dict)]

    def find(rule):
        return next((c for c in items if c.get("rule") == rule), None)

    def when(item):
        minutes = (item or {}).get("in_min")
        return (at + timedelta(minutes=minutes)).strftime("%H:%M") if minutes else None

    def test(item, unit, label):
        return f"{label} {_SIGN.get(item.get('op'), item.get('op'))} {_num(item.get('value'))}{unit}"

    def reading(item, unit):
        return "" if item.get("now") is None else f" (now {_num(item['now'])}{unit})"

    def more(count, word):
        return f"{count} more {word}{'' if count == 1 else 's'}"

    timeout = find("p0_timeout")
    if timeout:
        # Whichever moisture level drying reaches first: the trigger, or the P3 dryback's level.
        levels = [c for c in (find("p0_bypass"), find("p0_dryback")) if c and c.get("value") is not None]
        first = max(levels, key=lambda c: c["value"], default=None)
        by = when(timeout)
        text = f"P1 by {by}" if by else "P1 now"
        return text + (f", or sooner at {test(first, '%', 'VWC')}{reading(first, '%')}" if first else "")
    done = find("p1_done")
    if done:
        parts = []
        ramp = find("p1_ramp")
        if ramp:
            below = ramp.get("now") is not None and ramp["now"] < (ramp.get("value") or 0)
            due = when(ramp)
            parts.append(
                f"ramp shot {'at ' + due if due else 'due'} (VWC {_num(ramp['now'])}% under {_num(ramp.get('value'))}%)"
                if below
                else f"ramp shot when {test(ramp, '%', 'VWC')}{reading(ramp, '%')}"
            )
        shots = f" after {more(done['shots_left'], 'shot')}" if done.get("shots_left") else ""
        ec = ""
        if done.get("ec_max") is not None:
            ec = f" with pwEC ≤ {_num(done['ec_max'])}" + (
                "" if done.get("ec_now") is None else f" (now {_num(done['ec_now'])})"
            )
        most = (find("p1_max_shots") or {}).get("shots_left")
        parts.append(
            f"P2 at {test(done, '%', 'VWC')}{shots}{ec}" + (f", or after {more(most, 'ramp shot')}" if most else "")
        )
        return " · ".join(parts)
    topup, off = find("p2_topup"), find("lights_off")
    if topup or off:
        # A held plan leaves the routine shots out: then only lights-off is left.
        dilute = find("p2_dilute")
        parts = [
            f"shot when {test(topup, '%', 'VWC')}{reading(topup, '%')}" if topup else None,
            f"dilution if {test(dilute, '', 'pwEC')}{reading(dilute, '')}" if dilute else None,
            # By, not at: in its last three hours P2 moves early when the night is too short to dry.
            f"P3 by {when(off) or 'lights-off'}" if off else None,
        ]
        return " · ".join(part for part in parts if part)
    rescue = find("p3_emergency")
    if rescue:
        on = find("lights_on")
        parts = [
            f"rescue shot if {test(rescue, '%', 'VWC')}{reading(rescue, '%')}",
            f"P0 at {when(on) or 'lights-on'}" if on else None,
        ]
        return " · ".join(part for part in parts if part)
    return ""

# How a room is plumbed, as DECLARED in the integration's setup and published as the descriptor's
# `plumbing`: layout -> (has a pump switch, has a main-line valve). The integration carries the same
# table (custom_components/crop_steering/plumbing.py); tests/test_plumbing.py pins the two together.
PLUMBING_LAYOUTS = {
    "valves_only": (False, False),
    "pump_valves": (True, False),
    "mainline_valves": (False, True),
    "pump_mainline_valves": (True, True),
}


def with_plumbing(hw, descriptor):
    """Carry a declared layout into a room's hardware map. A room that never declared one keeps
    exactly the map it always had, so an install from before declared plumbing behaves (and
    fingerprints) as it did."""
    if (descriptor or {}).get("plumbing"):
        hw["plumbing"] = descriptor["plumbing"]
    return hw


def plumbing_hold(hw):
    """Why a room must not be watered given the plumbing it DECLARED, or None.

    Undeclared (every install set up before this existed): None - pump and main-line are used when
    mapped and skipped when not, as before. Declared: the switches have to match the declaration.
    Without this, a pumped room whose pump mapping was cleared (or lost) looked exactly like a
    one-switch tent: the valve opened, no pump ran, and the shot was counted as delivered while
    the plants got nothing. A declaration turns that silent dry run into a hold with a reason.
    """
    layout = (hw or {}).get("plumbing")
    if not layout:
        return None
    needs = PLUMBING_LAYOUTS.get(layout)
    if needs is None:
        return (
            f"setup declares a plumbing layout this controller does not know ({layout!r}) - not "
            "watering on a guess; update the controller app to match the integration"
        )
    for key, needed, label in (
        ("pump", needs[0], "pump"),
        ("mainline", needs[1], "main-line valve"),
    ):
        mapped = bool(hw.get(key))
        if needed and not mapped:
            return (
                f"setup says this room has a {label}, but no {label} switch is mapped - not watering "
                f"without it; map the {label} in the Crop Steering setup, or change the room's plumbing"
            )
        if mapped and not needed:
            return (
                f"setup says this room has no {label}, but a {label} switch is mapped ({hw[key]}) - "
                "not watering until they agree; clear it, or change the room's plumbing"
            )
    return None


def _instance_id(path):
    """This install's own id (a uuid4) from `path`, the `instance_id` file beside state.json, made the
    first time. One that is missing, unreadable or not a uuid is replaced; one that cannot be written
    leaves an id for this run only, never a stop."""
    try:
        with open(path, encoding="utf-8") as fh:
            return str(uuid.UUID(fh.read().strip()))
    except (OSError, ValueError):
        pass
    made = str(uuid.uuid4())
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(made + "\n")
        os.replace(path + ".tmp", path)
    except OSError as e:
        log("instance_id could not be written, an id for this run only:", e)
    return made


class Room:
    """One fully-isolated grow room the engine steers. `prefix` is "" for the default
    (un-prefixed) room or "<slug>_" for an additional room, applied to every
    crop_steering_* entity id. Holds the room's config AND its mutable runtime state
    so rooms never clobber each other."""

    def __init__(
        self,
        slug,
        prefix,
        zones,
        hardware,
        enable_flag,
        feed_ec_sensor,
        feed_ph_sensor,
        opt_lon,
        opt_loff,
    ):
        self.slug = slug  # "default" or the room slug
        self.prefix = prefix  # "" or "<slug>_"
        self.zones = zones  # {z: {"vwc": entity, "ec": entity}}
        self.hw = hardware  # {"pump":.., "mainline":.., "valves":{z:..}}
        self.enable_flag = (
            enable_flag  # the per-room KILL SWITCH (must be ON to actuate)
        )
        self.feed_ec_sensor = (feed_ec_sensor or "").strip()
        self.feed_ph_sensor = (feed_ph_sensor or "").strip()
        self.substrate = "generic"  # from the descriptor; see Controller._substrate
        # lights: fall back to these option values until the integration entity is read
        self.opt_lon = opt_lon
        self.opt_loff = opt_loff
        self.lights_on_hour = opt_lon
        self.lights_off_hour = opt_loff
        self._lights_logged = False
        # per-room mutable runtime state
        self.state = {}  # {z: zone_state}
        self.hardware_fault = (
            None  # durable hold; explicit OFF + verified hardware recovery
        )
        # write-ahead record of the shot in flight: what it opened and when (see _execute_shot)
        self.shot_inflight = None
        self._vmax = {}  # z -> (vmax, confidence) advisory, from the zone's saved P1 wet-up series
        self._blind_zones = set()
        self._blind_since = {}  # z -> when its probe was first seen unreadable in this run of it
        self._test_seen = {}  # z -> its Test Shot button's state last seen (the time it was last pressed)
        self._was_lights_on = None
        self._feed_last_good_value = None
        self._feed_last_good_time = None
        self._feed_ph_last_good = None
        self._feed_ph_last_good_time = None
        # when this room was seen switched off (see _room_switched_on); durable, None when not known
        self._off_since = None
        # what the room last reported, repeated while a shot holds the loop (Controller._keep_alive)
        self._beat = None  # (hardware_fault, room_active) of its last heartbeat
        self._beat_at = None  # and when, by time.monotonic()
        self._statuses = {}  # z -> (label, reason) of its zones' last status
        self._safety_shown = {}  # z -> (label, since) of its zones' safety status (the hysteresis)
        self._status_at = {}  # z -> when, by time.monotonic()


def room_gate(room):
    """The kill switch this room stops on: the one entity that must read ON for anything in it to be
    watered (an absent or unreadable one holds). Chosen in two steps and nowhere else: the start-up
    value from Controller._default_enable_flag (a named room its engine switch; the default room the
    app's `enable_flag` option, or its setup's flag where that option is the legacy helper and the
    helper does not exist), then, once a revisioned setup is adopted or resumed, the setup's own flag
    (Controller._apply_setup_descriptors). An update never moves it: the operator does, through the
    option on a room with no revisioned setup, or through a new setup revision on one that has one.
    The heartbeat reports it, so the integration and the dashboard name the same switch."""
    return room.enable_flag


class Controller:
    # Batch-tank dosing (dosing_runner.py, docs/DOSING.md): None until __init__ builds it. A shot starts,
    # and a batch holds a room, under _shot_lock, so a shot is either seen running or never starts.
    dosing = None
    _shot_lock = threading.Lock()

    def __init__(self):
        o = load_options()
        # ---- shared (cross-room) config ----
        # notify_service is OPTIONAL with an empty default: unset = no mobile push (persistent
        # notifications still fire), never a fallback to the developer's phone.
        self.notify_service = (o.get("notify_service") or "").strip()
        self.notify_min = float(o.get("notify_min", 30))
        self.instance_name = o.get("instance_name", "Crop Steering")
        # External operator holds (tank dosing / manual fill / flush). Facility-specific, so
        # they are an OPTION with an empty default — an install without them never holds on
        # them. Configure your own input_boolean/switch ids to enable.
        self.hold_entities = [e for e in (o.get("hold_entities") or []) if e]
        self.feed_grace_min = float(o.get("feed_grace_min", 30))
        self.blind_fallback_min = float(o.get("blind_fallback_min", 90))
        # Optional (CS-311): the power sensor of the sump pump a room's tables drain to, one for every room or
        # `room=sensor` pairs, and how long it may stand still while the room is on. Unset = not watched.
        self.sump_sensors = room_option(o.get("sump_power_sensor"))
        self.sump_silent_h = float(o.get("sump_silent_hours") or SUMP_SILENT_H)
        # Optional: Jev (TypeSafe, via Cloudflare AI) as a guard on auto setpoints. Unset = arithmetic only.
        self._cf = tuple((o.get(k) or "").strip() for k in ("cf_account_id", "cf_api_token", "cf_gateway_id"))
        # The Jev edition: Jev judges the engine's decisions inside a code envelope (docs/JEV.md). None = off.
        try:
            self.jev = jev_bridge.build(o, self._cf, runtime_env.state_path(os.environ), log)
        except Exception as e:  # Jev can never stop the controller starting
            log("jev: off, it could not start:", e)
            self.jev = None
        self.loop_seconds = float(o.get("loop_seconds", 60))
        self.flow_lps = float(
            o.get("flow_lps", 0.02)
        )  # generic last-resort fallback — real flow is computed live per zone
        self.substrate_l = float(
            o.get("substrate_l", 5)
        )  # generic last-resort fallback — real volume read live from the integration
        self._opt_lon = float(o.get("lights_on_hour", SHIPPED_LIGHTS[0]))
        self._opt_loff = float(o.get("lights_off_hour", SHIPPED_LIGHTS[1]))
        # The app always uses /data/state.json (HA-managed, survives Rebuild); a container keeps it in
        # its data volume (F2_DATA_DIR). F2_STATE_PATH lets a test/dev rig redirect the file BEFORE this
        # constructor's own _load_state()/adoption pass reads and writes it.
        self._state_path = runtime_env.state_path(os.environ)
        # Who this controller is, in its heartbeat, so the duplicate-controller guard can tell another one
        # apart (duplicate_hold). Beside state.json, as dosing_state.json is: one data folder, one identity.
        self.instance_id = _instance_id(os.path.join(os.path.dirname(self._state_path) or ".", "instance_id"))
        self._guard = {}  # room slug -> {"answered", "seen", "until"} (_guard_read)
        self._guard_lock = threading.Lock()
        # Dosing runs on its own thread, started by run(). Like Jev, it can never stop the controller
        # starting, and it only ever acts on an explicit request for a room with dosing set up.
        try:
            self.dosing = dosing_runner.DosingRunner(
                self,
                get=lambda entity, **timeout: ha_get(entity, **timeout),
                call=lambda domain, service, **data: ha_call(domain, service, **data),
                publish=lambda entity, state, attributes: ha_set(entity, state, attributes),
                alert=self._dosing_alert,
                history=lambda entity, since: ha_history(entity, since),
                respond=lambda domain, service, data, timeout: ha_service_response(
                    domain, service, data, timeout),
                state_path=os.path.join(os.path.dirname(self._state_path) or ".", "dosing_state.json"),
                log=log,
                actuators=ACTUATORS,
                refused=lambda: _GATE.state == "all",
            )
        except Exception as e:
            log("dosing: off, it could not start:", e)
            self.dosing = None
        self._busy = False
        self._shot_room = None  # the room whose shot is in flight (see _execute_shot / _safe_off)
        _GATE.own = self._switched_on  # what a refused token still closes (_AuthGate)
        self._alerted = {}
        self._alert_codes = {}  # key -> the code last raised under it (see _alert_due)
        self._fused_id_cache = (
            {}
        )  # (prefix,metric,zone) -> resolved fused-sensor entity_id
        self._activity = []
        self._last_notify = None
        self._start = datetime.now()
        self._last_discovery = self._start
        self.rediscover_seconds = float(o.get("rediscover_seconds", 300))
        self._defaulted = (
            {}
        )  # entity_id -> consecutive loops it fell back to an engine default
        self._defaulted_this_loop = set()
        self._n_defaulted = 0

        # ---- the DEFAULT room ----
        # Hardware (pump/mainline/valves) comes from the integration's published
        # engine_config descriptor — the operator maps it once in the Crop Steering UI.
        # `hardware`/`zones` keys in options.json still win when present, but they are NOT
        # in the Supervisor schema (the UI rejects unknown keys) — they exist for the test
        # harness and hand-built dev setups only. There is NO facility-specific fallback:
        # an unmapped room holds SAFE (see _blocked) rather than actuating another
        # install's entities.
        # Sensors are owned by the INTEGRATION: it fuses every probe you map to a zone
        # into sensor.crop_steering_vwc_zone_N / _ec_zone_N; the engine reads those.
        desc = self._default_descriptor()
        self._options = o
        self._default_provisional = False
        zones_opt = o.get("zones")
        if zones_opt:
            zones = {int(k): v for k, v in zones_opt.items()}
        else:
            zone_ids, self._default_provisional = self._default_zone_ids(o, desc)
            zones = self._default_zone_map(zone_ids)
        hw = o.get("hardware")
        if not hw:
            valves = {int(k): v for k, v in (desc.get("valves") or {}).items() if v}
            if valves:
                # A zone needs its valve. Pump and mainline are used when mapped and skipped when
                # not: a tent with one smart plug is a complete room (see _execute_shot).
                hw = with_plumbing({
                    "pump": desc.get("pump") or None,
                    "mainline": desc.get("mainline") or None,
                    "valves": valves,
                }, desc)
            else:
                # unmapped — _blocked() holds every zone and alerts until it's configured
                hw = {"pump": None, "mainline": None, "valves": {}}
        hw["valves"] = {int(k): v for k, v in hw["valves"].items()}
        # Source-water feed gate sensors are OPTIONAL and have NO facility default — an empty
        # (or unset) value disables that half of the source-water gate so the add-on works on
        # any install out of the box. Option wins, else the integration descriptor's value.
        default_room = Room(
            slug="default",
            prefix="",
            zones=zones,
            hardware=hw,
            enable_flag=self._default_enable_flag(o, desc),
            feed_ec_sensor=(
                o.get("feed_ec_sensor") or desc.get("feed_ec_sensor") or ""
            ).strip(),
            feed_ph_sensor=(
                o.get("feed_ph_sensor") or desc.get("feed_ph_sensor") or ""
            ).strip(),
            opt_lon=self._opt_lon,
            opt_loff=self._opt_loff,
        )
        if self._default_provisional and not default_room.zones:
            log(
                "config: Home Assistant is not answering yet, or the Crop Steering integration has "
                "not published a room yet, so there is nothing to drive. If it is not set up, add "
                "it in Home Assistant (Settings > Devices & services > Add "
                "integration > Crop Steering). This controller checks every loop and picks the room "
                "up by itself: no restart needed."
            )
        elif not default_room.hw.get("valves"):
            log(
                "config: default room has NO hardware mapped — holding safe. Map each zone's valve "
                "(and the pump and mainline, if the room has them) in the Crop Steering integration "
                "(or the add-on `hardware` option)."
            )
        self.rooms = [default_room]
        # ---- additional rooms: discovered from the integration's published descriptors ----
        self.rooms.extend(self._discover_rooms())

        for room in self.rooms:
            self._log_feed_config(room)
        if len(self.rooms) > 1:
            log(
                "rooms:",
                ", ".join(
                    f"{r.slug}(prefix='{r.prefix}', {len(r.zones)}z, kill={room_gate(r)})"
                    for r in self.rooms
                ),
            )

        # state for all rooms (nested by slug; old flat single-room files load as 'default')
        self._load_state()
        self._apply_setup_descriptors()  # Gate tombstones/revisions before the very first shot.
        # The guard's first read, before run() starts the dosing thread: a room counts as held until its
        # heartbeat has been read.
        for room in self.rooms:
            self._guard_read(room)
        signal.signal(signal.SIGTERM, self._safe_exit)
        signal.signal(signal.SIGINT, self._safe_exit)

    def _log_feed_config(self, room):
        tag = "" if room.prefix == "" else f"[{room.slug}] "
        if not room.feed_ec_sensor and not room.feed_ph_sensor:
            log(
                f"config: {tag}no feed_ec_sensor/feed_ph_sensor set — source-water pH/EC gate "
                "disabled (dosing/fill holds still apply); set them to enable feed gating"
            )
        elif not room.feed_ec_sensor:
            log(
                f"config: {tag}no feed_ec_sensor set — source-water EC gate disabled (pH gate active)"
            )
        elif not room.feed_ph_sensor:
            log(
                f"config: {tag}no feed_ph_sensor set — source-water pH gate disabled (EC gate active)"
            )
        else:
            log(
                f"config: {tag}feed gate EC={room.feed_ec_sensor} pH={room.feed_ph_sensor}"
            )

    @staticmethod
    def _default_zone_map(zone_ids):
        return {
            z: {
                "vwc": f"sensor.crop_steering_vwc_zone_{z}",
                "ec": f"sensor.crop_steering_ec_zone_{z}",
            }
            for z in zone_ids
        }

    def _default_zone_ids(self, options, descriptor):
        """Which zones the default room has -> (zone ids, provisional).

        `provisional` means the answer is only a stand-in because the integration could not be
        asked yet; the room is then re-resolved every loop until it can (see _rediscover).

        The `num_zones` option (default 3) now counts zones only for a room hand-mapped in the
        `hardware` option. It used to stand in whenever the integration could not be asked, which
        is every first install where the app is started first: a one-zone tent got zones 2 and 3
        that do not exist, each reporting "no hardware mapped", until the new setup happened to be
        adopted. With Home Assistant unreachable at start it invented the same zones for a room
        that might have one. Nothing is invented now: such a room has no zones until Home
        Assistant answers with its own.
        """
        # The descriptor owns the zone list. Sensors can appear one at a time while HA starts,
        # and retired sensors can outlive their zones; neither should redefine a configured room.
        if descriptor:
            ids = descriptor.get("active_zone_ids")
            if isinstance(ids, list) and ids and all(type(z) is int and 1 <= z <= 64 for z in ids):
                return sorted(ids), False
            count = int(descriptor.get("num_zones") or len(descriptor.get("valves") or {}) or 0)
            if count:
                return list(range(1, count + 1)), False
        n = self._detect_zones("", 0)
        if n:
            # Without a descriptor this may still be a partial startup inventory. Keep checking
            # until the room definition arrives, unless the operator supplied the hardware map.
            return list(range(1, n + 1)), not bool(options.get("hardware"))
        if options.get("hardware"):  # hand-mapped in the app options: their zone count stands
            return list(range(1, int(options.get("num_zones", 3)) + 1)), False
        # No hardware map, and either Home Assistant answers with no room in it yet, or it does not
        # answer at all (nothing can be actuated then anyway): no zones, re-resolved every loop.
        return [], True

    def _default_enable_flag(self, options, descriptor):
        legacy = LEGACY_ENABLE_FLAG
        requested = descriptor.get("enable_flag")
        configured = options.get("enable_flag", legacy)
        # Fresh native setups have a real integration switch and no legacy YAML
        # helper. Do not make the old schema default mask that new explicit flag.
        if (
            descriptor.get("setup_revision", 0) > 0
            and requested
            and configured == legacy
            and ha_get(legacy)[0] is None
        ):
            return requested
        return configured or requested or legacy

    def _default_descriptor(self):
        """The DEFAULT room's engine_config descriptor (prefix ""), published by the
        integration from the config-entry hardware map. Returns {} when it isn't present
        yet (HA still booting or the integration not set up) — the room then holds until it
        appears (re-resolved by _rediscover). Explicit add-on options override this."""
        for ent in ha_get_all():
            eid = ent.get("entity_id", "")
            if eid.startswith("sensor.crop_steering_") and eid.endswith(
                "engine_config"
            ):
                a = ent.get("attributes", {}) or {}
                if not a.get("prefix"):
                    return a
        return {}

    def _discover_rooms(self):
        """Find additional rooms from sensor.crop_steering_<prefix>engine_config descriptors
        the integration publishes. The DEFAULT room (prefix "") is skipped — it's built from
        the add-on options + default descriptor above.
        """
        rooms = []
        versions = set()
        for ent in ha_get_all():
            eid = ent.get("entity_id", "")
            if not (
                eid.startswith("sensor.crop_steering_")
                and eid.endswith("engine_config")
            ):
                continue
            a = ent.get("attributes", {}) or {}
            versions.add(a.get("integration_version"))
            if a.get("active", True) is False:
                continue
            prefix = a.get("prefix", "")
            if not prefix:
                continue  # the default room is handled from options, never from the sensor
            try:
                valves = {int(k): v for k, v in (a.get("valves") or {}).items()}
                num = int(a.get("num_zones") or len(valves) or 0)
                zones = {
                    z: {
                        "vwc": f"sensor.crop_steering_{prefix}vwc_zone_{z}",
                        "ec": f"sensor.crop_steering_{prefix}ec_zone_{z}",
                    }
                    for z in a.get("active_zone_ids", range(1, num + 1))
                }
                hw = with_plumbing({
                    "pump": a.get("pump"),
                    "mainline": a.get("mainline"),
                    "valves": valves,
                }, a)
                if not (valves and zones):
                    log(
                        f"room '{a.get('slug')}' engine_config incomplete — skipped (no zone valves or zones)"
                    )
                    continue
                rooms.append(
                    Room(
                        slug=a.get("slug") or prefix.rstrip("_"),
                        prefix=prefix,
                        zones=zones,
                        hardware=hw,
                        enable_flag=a.get("enable_flag")
                        or f"switch.crop_steering_{prefix}engine_enabled",
                        feed_ec_sensor=a.get("feed_ec_sensor", ""),
                        feed_ph_sensor=a.get("feed_ph_sensor", ""),
                        opt_lon=self._opt_lon,
                        opt_loff=self._opt_loff,
                    )
                )
            except Exception as e:
                log("room discovery error for", eid, e)
        for theirs in sorted({str(v) for v in versions if v} - {CONTROLLER_VERSION}):
            fix = (f"set CONTROLLER_VERSION to {theirs}" if _GATE.container
                   else "update the app, or the integration, so both run the same version")
            log(f"version: controller {CONTROLLER_VERSION}, integration {theirs}; {fix}")
        return rooms

    # ---------- entity id helper ----------
    def _cs(self, room, domain, key):
        """A room-namespaced crop_steering entity id, e.g. _cs(room,'sensor','vwc_zone_1')
        -> 'sensor.crop_steering_vwc_zone_1' (default) / 'sensor.crop_steering_veg_vwc_zone_1'.
        """
        return f"{domain}.crop_steering_{room.prefix}{key}"

    # ---------- durable state ----------
    def _fresh_zone(self):
        return {
            "phase": "P2",
            "peak": 0.0,
            "win": [],
            "last_shot": None,
            # True while `last_shot` is only the moment the room was switched on (the timers count
            # from it) and no water has been delivered since: it must never be shown as an irrigation.
            "last_shot_is_anchor": False,
            "shots": 0,
            "daily_vol": 0.0,
            "ec_smooth": None,
            # pore EC from the last reading taken EC_SETTLE_MIN after a shot, and when (see _settled_ec)
            "ec_settled": None,
            "ec_settled_at": None,
            "last_phase_change": datetime.now(),
            "ec_offset": 0.0,
            "last_ec_steer": None,
            "last_daily_reset": None,
            "water_history": None,
            "water_history_legacy_excluded_l": 0.0,
            "learn": auto_setpoints.fresh(),
            "peak_prev": None,  # the follower's highest VWC of the grow-day before, kept at lights-on (_vwc_maxima)
            # the follower's (_follow_fc): this grow-day's highest reading it counts (None: a CS-310 day, not counted)
            # and the points it has moved each setpoint on grow-day `day`
            "fc_follow": {"peak": 0.0, "day": None, "used": {}},
            "p1_reached": False,  # the P1 rule (core.decide): this P1 has read at or over its target
            "p1_peak_before": None,  # ...the zone's peak right before its last P1 shot
            "p1_extra": 0,  # ...and the P1 shots fired since the target was reached
            "capped_in_a_row": 0,  # CS-312: the shots in a row cut to the room's maximum shot length
            "max_run_latch": None,  # ...and, once latched, {"since", "resets"} (_count_capped)
            "p1_settled_before": None,  # ...its settled reading right before its last P1 shot (core.settled_reading)
            "p1_expected_rise": None,  # ...and what that shot should lift it by, from the learned gain
            "vmax_wetup": [],  # this grow-day's P1 wet-up VWC readings, for the Vmax advisory (resets each P0)
            **zone_history.fresh(),
        }

    def _apply_saved_zone(self, fresh, d):
        """Overlay a saved zone dict onto a fresh one — tolerant of missing/unknown keys
        and bad timestamps (the in-place-upgrade contract)."""
        if not isinstance(d, dict):
            return fresh
        s = fresh
        s["learn"] = auto_setpoints.restore(d.get("learn"))
        for k in (
            "phase",
            "peak",
            "shots",
            "daily_vol",
            "ec_smooth",
            "ec_offset",
        ):
            if d.get(k) is not None:
                s[k] = d[k]
        for k in ("last_shot", "last_phase_change", "last_ec_steer", "ec_settled_at"):
            if d.get(k):
                try:
                    s[k] = datetime.fromisoformat(d[k])
                except (ValueError, TypeError):
                    pass
        try:
            settled = float(d.get("ec_settled"))
            if math.isfinite(settled):
                s["ec_settled"] = settled
        except (TypeError, ValueError):
            pass
        if isinstance(d.get("last_shot_is_anchor"), bool):
            s["last_shot_is_anchor"] = d["last_shot_is_anchor"]
        else:
            # Old files do not distinguish an irrigation from a switch-on stamp. Daily counters
            # reset and water history expires (or predates its introduction), so no recorded water
            # cannot prove this was an anchor. Preserve the timestamp the prior version published.
            s["last_shot_is_anchor"] = False
        if d.get("last_daily_reset"):
            try:
                s["last_daily_reset"] = date.fromisoformat(d["last_daily_reset"])
            except (ValueError, TypeError):
                pass
        history = d.get("water_history")
        if isinstance(history, list):
            # Reject malformed/duplicate buckets; old files simply initialize on first use.
            valid = {}
            for item in history:
                try:
                    day = date.fromisoformat(item["grow_day"])
                    litres = float(item["litres"])
                    if not math.isfinite(litres) or litres < 0:
                        continue
                    valid[day] = {"grow_day": day.isoformat(), "litres": litres,
                                  "complete": item.get("complete") is True}
                except (KeyError, TypeError, ValueError):
                    continue
            s["water_history"] = [valid[day] for day in sorted(valid)[-7:]]
        try:
            excluded = float(d.get("water_history_legacy_excluded_l", 0.0))
            if math.isfinite(excluded) and excluded >= 0:
                s["water_history_legacy_excluded_l"] = excluded
        except (TypeError, ValueError):
            pass
        if isinstance(d.get("p1_reached"), bool):  # the P1 rule's state, absent before 3.11.0
            s["p1_reached"] = d["p1_reached"]
        try:
            before = float(d.get("p1_peak_before"))
            if math.isfinite(before) and 0.0 < before <= 100.0:
                s["p1_peak_before"] = before
        except (TypeError, ValueError):
            pass
        if isinstance(d.get("p1_extra"), int) and not isinstance(d.get("p1_extra"), bool) and 0 <= d["p1_extra"] <= 100:
            s["p1_extra"] = d["p1_extra"]
        capped = d.get("capped_in_a_row")  # both absent before the max-run latch: 0 and None
        if type(capped) is int and 0 <= capped <= 10000:
            s["capped_in_a_row"] = capped
        latch = d.get("max_run_latch")
        if isinstance(latch, dict) and type(latch.get("resets")) is int and isinstance(latch.get("since"), str):
            s["max_run_latch"] = {"since": latch["since"], "resets": latch["resets"]}
        for key in ("p1_settled_before", "p1_expected_rise"):  # absent before the settled P1 rise: None
            try:
                value = float(d.get(key))
                if math.isfinite(value) and 0.0 < value <= 100.0:
                    s[key] = value
            except (TypeError, ValueError):
                pass
        try:  # absent before 3.11.0: None, and the grow-day in progress stands in (_vwc_maxima)
            prev = float(d.get("peak_prev"))
            if math.isfinite(prev) and 0.0 < prev <= 100.0:
                s["peak_prev"] = prev
        except (TypeError, ValueError):
            pass
        fc = d.get("fc_follow")
        if isinstance(fc, dict):
            s["fc_follow"] = {"peak": _pct_or_none(fc.get("peak")),
                              "day": fc["day"] if isinstance(fc.get("day"), str) else None,
                              "used": {k: _pct_or_none(v) for k, v in (fc.get("used") or {}).items()
                                       if k in FC_LADDER and _pct_or_none(v) is not None}
                              if isinstance(fc.get("used"), dict) else {}}
        else:  # absent before the bounded follower: the grow-day's own peak stands in until the next lights-on
            s["fc_follow"]["peak"] = _pct_or_none(s.get("peak")) or 0.0
        series = d.get("vmax_wetup")  # absent from 3.11.1 files: an empty series, as at a P0
        if isinstance(series, list):
            s["vmax_wetup"] = [float(v) for v in series
                               if isinstance(v, (int, float)) and not isinstance(v, bool)
                               and math.isfinite(v) and 0.0 <= v <= 100.0][-VMAX_SERIES_MAX:]
        s.update(zone_history.restore(d))
        return s

    def _read_state_file(self):
        """Parse /data/state.json into a per-room dict. Nested by slug
        ({"default": {"1": {...}}, "veg": {...}}); an OLD flat single-room file
        ({"1": {...}}) is mapped to the 'default' room. {} on any read/parse failure."""
        try:
            with open(self._state_path) as fh:
                saved = json.load(fh)
        except (FileNotFoundError, ValueError, OSError):
            return {}
        if not isinstance(saved, dict):
            return {}
        flat = any(str(k).isdigit() for k in saved)
        return {"default": saved} if flat else saved

    def _load_room_state(self, room, per_room=None):
        """Seed one room's zones fresh, then overlay any saved state for its slug."""
        if per_room is None:
            per_room = getattr(self, "_saved_room_blocks", None)
            if per_room is None:
                per_room = self._read_state_file()
        room.state = {z: self._fresh_zone() for z in room.zones}
        room.hardware_fault = None
        room.shot_inflight = None
        room.strategy_required = False
        room._strategy_persisted = True
        room._off_since = None
        block = per_room.get(room.slug)
        if isinstance(block, dict):
            room.strategy_required = bool(block.get("_strategy_required", False))
            try:
                room._off_since = datetime.fromisoformat(block["_room_off_since"])
            except (KeyError, TypeError, ValueError):
                pass
            fault = block.get("_hardware_fault")
            if "_hardware_fault" in block:
                # Old files have no metadata. Malformed new metadata must not clear a hold.
                room.hardware_fault = self._fault_record(
                    fault, self._hardware_entities(room)
                )
            if "_shot_inflight" in block:
                room.shot_inflight = self._inflight_record(block["_shot_inflight"])
                if room.shot_inflight is None:
                    log(f"[{room.slug}] unreadable interrupted-shot record ignored: {block['_shot_inflight']!r}")
            for z in room.zones:
                d = block.get(str(z)) or block.get(z)
                room.state[z] = self._apply_saved_zone(room.state[z], d)
                v, c = detect_vmax(room.state[z]["vmax_wetup"])
                if v is not None:
                    room._vmax[z] = (v, c)

    def _load_state(self):
        """Load /data/state.json into every room (non-ephemeral, survives restart/Rebuild)."""
        per_room = self._read_state_file()
        # HA descriptors may be temporarily missing at startup. Keep their durable
        # state independently of discovery, including faults on shared hardware.
        self._saved_room_blocks = per_room
        for room in self.rooms:
            self._load_room_state(room, per_room)

    def _rediscover(self, now):
        """Periodic re-scan so rooms added in the integration UI (or whose descriptor wasn't
        published yet at add-on startup) join without a restart, and so a default room that
        started unmapped picks up its hardware once HA is up. New rooms join fail-safe OFF
        (their kill switch defaults off); existing rooms and their runtime state are untouched.
        """
        self._last_discovery = now
        # (1) resolve the default room's hardware/zones if it started unmapped (HA was down)
        default = self.rooms[0]
        if default.slug == "default" and getattr(self, "_default_provisional", False):
            desc = self._default_descriptor()
            zone_ids, self._default_provisional = self._default_zone_ids(self._options, desc)
            if set(zone_ids) != set(default.zones):
                was = sorted(default.zones)
                default.zones = self._default_zone_map(zone_ids)
                self._load_room_state(default)
                log(f"config: default room zones resolved: {was or 'none'} -> {sorted(zone_ids) or 'none'}")
            if desc:
                default.enable_flag = self._default_enable_flag(self._options, desc)
                default.feed_ec_sensor = (
                    self._options.get("feed_ec_sensor") or desc.get("feed_ec_sensor") or ""
                ).strip()
                default.feed_ph_sensor = (
                    self._options.get("feed_ph_sensor") or desc.get("feed_ph_sensor") or ""
                ).strip()
        if default.slug == "default" and not default.hw.get("valves"):
            desc = self._default_descriptor()
            valves = {int(k): v for k, v in (desc.get("valves") or {}).items() if v}
            if valves:
                default.hw = with_plumbing({
                    "pump": desc.get("pump") or None,
                    "mainline": desc.get("mainline") or None,
                    "valves": valves,
                }, desc)
                if not default.zones:
                    n = self._detect_zones(
                        "", int(desc.get("num_zones") or len(valves))
                    )
                    default.zones = {
                        z: {
                            "vwc": f"sensor.crop_steering_vwc_zone_{z}",
                            "ec": f"sensor.crop_steering_ec_zone_{z}",
                        }
                        for z in range(1, n + 1)
                    }
                    self._load_room_state(default)
                log(
                    f"config: default room hardware now mapped ({desc.get('pump') or 'valves only'}) — resuming"
                )
        # (2) add any newly-published additional rooms
        known = {r.slug for r in self.rooms}
        for room in self._discover_rooms():
            if room.slug in known:
                continue
            self._load_room_state(room)
            self.rooms.append(room)
            self._log_feed_config(room)
            log(f"room '{room.slug}' discovered live — joined fail-safe OFF")
        self._apply_setup_descriptors()

    @staticmethod
    def _setup_fingerprint(attrs, room):
        """What adopting this descriptor would put in force. Saved with the adopted revision so a
        restarted controller can tell "the setup I already adopted" from "a changed setup that
        happens to carry the same number"."""
        zone_ids = attrs.get(
            "active_zone_ids", list(range(1, int(attrs.get("num_zones", 0)) + 1))
        )
        adopted = {
            "active": attrs.get("active", True),
            "zones": sorted(zone_ids),
            "pump": attrs.get("pump"),
            "mainline": attrs.get("mainline"),
            "valves": {str(k): v for k, v in (attrs.get("valves") or {}).items()},
            "enable_flag": attrs.get("enable_flag") or room.enable_flag,
            "feed_ec_sensor": attrs.get("feed_ec_sensor") or "",
            "feed_ph_sensor": attrs.get("feed_ph_sensor") or "",
        }
        # Only when declared: a room that never declared its plumbing must keep the fingerprint
        # it saved before this field existed, or the update would strand it behind a disarm cycle.
        if attrs.get("plumbing"):
            adopted["plumbing"] = attrs["plumbing"]
        return json.dumps(adopted, sort_keys=True)

    @staticmethod
    def _entry_id(attrs):
        """Which Home Assistant config entry published this descriptor, or None when it does not
        say (every integration before 2.19.3) or says something that is not a plain string."""
        value = (attrs or {}).get("entry_id")
        return value if type(value) is str and value else None

    def _is_another_room(self, room, attrs, saved):
        """True when this descriptor comes from a DIFFERENT room than the one adopted: the
        integration was deleted in Home Assistant and set up again behind the same entity ids.

        A re-created room's setup revision starts again at 1, which is not higher than the one
        held, so it used to be skipped: the controller went on driving the map of a room that no
        longer existed, behind a kill-switch id the new room shares. Adoption is re-opened here
        and nothing more; it still goes through the gate below (kill switch OFF, hardware OFF).

        First sight of an `entry_id` (the integration was updated under a running room, or the
        state file is from before this) is remembered and changes nothing.
        """
        entry_id = self._entry_id(attrs)
        if entry_id is None:
            return False
        known = getattr(room, "_setup_entry_id", None)
        if known is None and isinstance(saved, dict):
            known = saved.get("entry_id") if type(saved.get("entry_id")) is str else None
        if not known:
            room._setup_entry_id = entry_id
            if getattr(room, "_setup_fingerprint_adopted", None):
                self._save_state()  # written down now, not at some later adoption
            return False
        if entry_id == known:
            room._setup_entry_id = known
            return False
        if getattr(room, "setup_revision", 0):
            log(
                f"room '{room.slug}' was deleted in Home Assistant and set up again: its setup is "
                "adopted afresh, once the kill switch and the hardware read OFF"
            )
        room.setup_revision = 0
        room._setup_fingerprint_adopted = None  # the saved block keeps describing the OLD room
        return True

    def _apply_setup_descriptors(self):
        """Adopt explicit versioned setup changes only after both maps are safe OFF.

        Missing legacy revision leaves add-on overrides untouched. Tombstones do
        not delete counters, and missing descriptors never imply room removal.

        A restart forgets nothing: the adopted revision and its fingerprint are saved, and the
        same pair after a restart is RESUMED with the kill switch left as it is (hardware must
        still read OFF). Without this, a host reboot left every zone of a live room blocked behind
        a disarm cycle nobody knew was needed, and two hours of the P1 ramp were lost.
        """
        descriptors = {}
        for entity in ha_get_all():
            eid = entity.get("entity_id", "")
            attrs = entity.get("attributes") or {}
            if (
                eid.startswith("sensor.crop_steering_")
                and eid.endswith("engine_config")
                and "prefix" in attrs
            ):
                descriptors[attrs["prefix"]] = attrs
        for room in self.rooms:
            attrs = descriptors.get(room.prefix)
            if not attrs:
                continue
            room.zone_names = self._zone_names(attrs)  # display only; a rename needs no adoption
            room.room_name = self._room_name(attrs)
            room.substrate = self._substrate(attrs)  # read like the names: needs no adoption
            saved = (getattr(self, "_saved_room_blocks", {}).get(room.slug) or {}).get("_setup")
            another_room = self._is_another_room(room, attrs, saved)
            revision = attrs.get("setup_revision", 0)
            if type(revision) is not int or revision <= getattr(
                room, "setup_revision", 0
            ):
                continue
            room._setup_pending = "Setup changed; disarm current and requested engine flags and verify hardware OFF"
            try:
                fingerprint = self._setup_fingerprint(attrs, room)
                resuming = (
                    getattr(room, "setup_revision", 0) == 0
                    and not another_room  # a different room is gated, however alike it looks
                    and isinstance(saved, dict)
                    and type(saved.get("revision")) is int
                    and saved["revision"] == revision
                    and saved.get("fingerprint") == fingerprint
                )
                active = attrs.get("active", True)
                zone_ids = attrs.get(
                    "active_zone_ids",
                    list(range(1, int(attrs.get("num_zones", 0)) + 1)),
                )
                if (
                    type(active) is not bool
                    or not isinstance(zone_ids, list)
                    or any(type(z) is not int or not 1 <= z <= 64 for z in zone_ids)
                ):
                    raise ValueError("Invalid setup active zone list")
                valves = {int(k): v for k, v in (attrs.get("valves") or {}).items()}
                desired_hw = with_plumbing({
                    "pump": attrs.get("pump"),
                    "mainline": attrs.get("mainline"),
                    "valves": valves,
                }, attrs)
                desired_flag = attrs.get("enable_flag") or room.enable_flag
                hardware = set(self._hardware_entities(room)) | {
                    v
                    for v in [
                        desired_hw["pump"],
                        desired_hw["mainline"],
                        *valves.values(),
                    ]
                    if v
                }
                flags = {room.enable_flag, desired_flag}
                if (
                    room.prefix == ""
                    and room.enable_flag == LEGACY_ENABLE_FLAG
                    and desired_flag == "switch.crop_steering_engine_enabled"
                    and ha_get(room.enable_flag)[0] is None
                ):
                    flags.discard(
                        room.enable_flag
                    )  # absent legacy helper on a fresh setup
                armed = sorted(flag for flag in flags if ha_get(flag)[0] != "off")
                running = sorted(e for e in hardware if hw_get(e)[0] != "off")
                if running or (armed and not resuming):
                    if active:  # an archived room is meant to stay dry: no noise about it
                        self._alert(
                            f"setup_{room.slug}",
                            "CS-201",
                            "setup change waiting, not watering",
                            (f"This room's setup (revision {revision}) is being taken on again after a "
                             "restart" if resuming else
                             f"A changed setup (revision {revision}) was saved")
                            + ", and nothing in this room is watered until the controller takes it "
                            "on. It only does that while these are "
                            f"OFF: {', '.join(running if resuming else armed + running)}. Turn them "
                            "off and wait for this notice to "
                            f"clear (up to {int(getattr(self, 'rediscover_seconds', 300))} seconds)"
                            + (": it then carries on as before." if resuming
                               else ", then turn the engine switch back on."),
                            room=room,
                        )
                    continue
                if active and any(not valves.get(z) for z in zone_ids):
                    raise ValueError("Active setup has a zone without a valve")
                zones = {
                    z: {
                        "vwc": f"sensor.crop_steering_{room.prefix}vwc_zone_{z}",
                        "ec": f"sensor.crop_steering_{room.prefix}ec_zone_{z}",
                    }
                    for z in zone_ids
                }
                for zone in zones:
                    if zone not in room.state:
                        saved = (
                            getattr(self, "_saved_room_blocks", {}).get(room.slug) or {}
                        ).get(str(zone))
                        room.state[zone] = self._apply_saved_zone(
                            self._fresh_zone(), saved
                        )
                room.zones, room.hw, room.enable_flag = zones, desired_hw, desired_flag
                room.feed_ec_sensor = attrs.get("feed_ec_sensor") or ""
                room.feed_ph_sensor = attrs.get("feed_ph_sensor") or ""
                room.setup_active, room.setup_revision = active, revision
                room._setup_fingerprint_adopted = fingerprint
                room._setup_entry_id = self._entry_id(attrs) or getattr(room, "_setup_entry_id", None)
                room._setup_pending = None
                ha_call("persistent_notification", "dismiss", notification_id=f"f2_setup_{room.slug}")
                self._alerted.pop(f"setup_{room.slug}", None)
                self._fused_id_cache = {
                    key: value
                    for key, value in self._fused_id_cache.items()
                    if key[0] != room.prefix
                }
                self._save_state()
                log(
                    f"room '{room.slug}' setup revision {revision} "
                    + ("resumed after restart (unchanged since it was adopted; hardware verified OFF)"
                       if resuming and armed else "adopted with verified OFF hardware")
                )
            except (TypeError, ValueError, KeyError) as error:
                room._setup_pending = f"Invalid setup descriptor: {error}"

    def _serialize_zone(self, s):
        ls, lpc, les, ldr, esa = (
            s.get("last_shot"),
            s.get("last_phase_change"),
            s.get("last_ec_steer"),
            s.get("last_daily_reset"),
            s.get("ec_settled_at"),
        )
        return {
            "phase": s.get("phase"),
            "peak": s.get("peak"),
            "peak_prev": s.get("peak_prev"),
            "fc_follow": s.get("fc_follow"),
            "p1_reached": bool(s.get("p1_reached")),
            "p1_peak_before": s.get("p1_peak_before"),
            "p1_extra": int(s.get("p1_extra") or 0),
            "capped_in_a_row": int(s.get("capped_in_a_row") or 0),
            "max_run_latch": s.get("max_run_latch"),
            "p1_settled_before": s.get("p1_settled_before"),
            "p1_expected_rise": s.get("p1_expected_rise"),
            "shots": s.get("shots"),
            "daily_vol": s.get("daily_vol"),
            "water_history": s.get("water_history"),
            "water_history_legacy_excluded_l": s.get("water_history_legacy_excluded_l", 0.0),
            "learn": s.get("learn"),
            "ec_smooth": s.get("ec_smooth"),
            "ec_settled": s.get("ec_settled"),
            "ec_settled_at": esa.isoformat() if isinstance(esa, datetime) else None,
            "ec_offset": float(s.get("ec_offset") or 0.0),
            "last_shot": ls.isoformat() if isinstance(ls, datetime) else None,
            "last_shot_is_anchor": bool(s.get("last_shot_is_anchor")),
            "last_phase_change": lpc.isoformat() if isinstance(lpc, datetime) else None,
            "last_ec_steer": les.isoformat() if isinstance(les, datetime) else None,
            "last_daily_reset": ldr.isoformat() if isinstance(ldr, date) else None,
            "plateau_hist": s.get("plateau_hist") or [],
            "night_hist": s.get("night_hist") or [],
            "night": s.get("night"),
            "vmax_wetup": list(s.get("vmax_wetup") or []),
        }

    def _save_state(self):
        # Preserve undiscovered rooms and unknown metadata/zones. A descriptor going
        # missing must never delete counters or erase a latched shared-hardware hold.
        out = dict(getattr(self, "_saved_room_blocks", {}))
        for room in self.rooms:
            prior = out.get(room.slug)
            block = dict(prior) if isinstance(prior, dict) else {}
            block.update(
                {str(z): self._serialize_zone(s) for z, s in room.state.items()}
            )
            if getattr(room, "strategy_required", False):
                block["_strategy_required"] = True
            else:
                block.pop("_strategy_required", None)
            if room.hardware_fault:
                block["_hardware_fault"] = room.hardware_fault
            else:
                block.pop("_hardware_fault", None)
            if getattr(room, "shot_inflight", None):
                block["_shot_inflight"] = room.shot_inflight
            else:
                block.pop("_shot_inflight", None)
            if hasattr(room, "_room_active_known"):
                block["_room_active"] = room._room_active_known
            if getattr(room, "_off_since", None):
                block["_room_off_since"] = room._off_since.isoformat()
            else:
                block.pop("_room_off_since", None)
            if getattr(room, "_setup_fingerprint_adopted", None):  # else keep whatever was saved
                block["_setup"] = {
                    "revision": room.setup_revision,
                    "fingerprint": room._setup_fingerprint_adopted,
                }
                if getattr(room, "_setup_entry_id", None):  # which room it was (see _is_another_room)
                    block["_setup"]["entry_id"] = room._setup_entry_id
            out[room.slug] = block
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(out, fh)
            os.replace(tmp, self._state_path)
            self._saved_room_blocks = out
            return True
        except OSError as e:
            log("state save failed", e)
            return False

    # ---------- HA read helpers ----------
    def _num(self, entity, default):
        v, _, _ = ha_get(entity)
        try:
            return (
                float(v)
                if v not in (None, "unknown", "unavailable", "")
                else float(default)
            )
        except Exception:
            return float(default)

    def _zone_num(self, room, zone, suffix, default, optional=False):
        override = parameter_override(
            getattr(room, "strategy_snapshot", None), zone, suffix
        )
        if override is not None:
            return float(override)
        per = f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}"
        v, _, _ = ha_get(per)
        seen = self.__dict__.setdefault("_settings_seen", {})  # entity -> the last value read since start
        if v not in (None, "unknown", "unavailable", ""):
            seen[per] = self._num(per, default)
            return seen[per]
        glob = f"number.crop_steering_{room.prefix}{suffix}"
        gv, _, _ = ha_get(glob)
        if gv not in (None, "unknown", "unavailable", ""):
            seen[glob] = self._num(glob, default)
            return seen[glob]
        # Neither the per-zone NOR the global setpoint entity exists → the engine is silently
        # running its built-in default. On a healthy install the integration creates the global,
        # so this only trips on a real misconfig (renamed/removed entity). Record it so
        # _check_defaulted_setpoints can surface it — EXCEPT engine-only knobs the integration
        # deliberately doesn't create (optional=True): those default by design, never alert.
        if not optional:
            self._defaulted_this_loop.add(glob)
            room.__dict__.setdefault("_settings_missing", set()).add(glob)
            last = seen.get(per, seen.get(glob))
            if last is not None:  # read earlier in this run: a real value, not a guess
                return last
        return None if default is None else float(default)

    def _room_duration_cap(self, room):
        """Read the canonical room cap, or its same-room legacy entity if absent."""
        for suffix in ("max_shot_duration", "maximum_shot_duration"):
            entity = f"number.crop_steering_{room.prefix}{suffix}"
            raw, attributes, updated = ha_get(entity)
            if raw is None and not attributes and updated is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = None
            if value is not None and math.isfinite(value) and value >= 5:
                return value
            self._alert(
                f"duration_config_{room.slug}",
                "CS-203",
                "maximum shot length not valid, not watering",
                "The room's maximum shot length must be a number of at least 5 seconds, and it "
                "isn't, so no shot is started. The value set here is never replaced by a default."
                f"\n\nSetting: {entity}",
                room=room,
            )
            return None
        # Keep the existing installation fallback only when neither room entity exists.
        return 900.0

    def _num_or_none(self, entity):
        """Read a number entity as float, or None if it doesn't exist / isn't a number."""
        v, _, _ = ha_get(entity)
        try:
            return float(v) if v not in (None, "unknown", "unavailable", "") else None
        except Exception:
            return None

    def _detect_zones(self, prefix, fallback):
        """Count zones from the integration's fused VWC sensors. Returns the number of
        consecutive fused VWC sensors that exist under EITHER naming convention —
        sensor.crop_steering_<prefix>vwc_zone_N (current) or the registry-sticky legacy
        sensor.crop_steering_<prefix>zone_N_vwc — or `fallback` if none do (e.g. HA not
        reachable yet at startup)."""
        n = 0
        for z in range(1, 25):
            new, _, _ = ha_get(f"sensor.crop_steering_{prefix}vwc_zone_{z}")
            if new is None:
                old, _, _ = ha_get(f"sensor.crop_steering_{prefix}zone_{z}_vwc")
                if old is None:
                    break
            n += 1
        return n or fallback

    def _fused_id(self, prefix, metric, z, override=None):
        """Resolve a zone's fused sensor entity_id, tolerating BOTH naming conventions.

        The integration's CURRENT object_id is `crop_steering_<prefix>{metric}_zone_N`, but
        HA entity_ids are sticky to the registry from first creation: a box originally set up
        under an older integration that keyed the sensor `zone_N_{metric}` KEEPS that id
        forever, even after the code switched conventions. The engine reads by entity_id, so a
        mismatch makes it blind (the bug that froze every zone in P2). This probes HA for
        whichever id actually exists and caches the hit. If neither is present yet (HA not up
        at startup) it returns the current-convention id WITHOUT caching, so it re-resolves
        once the entity appears. An explicit `override` (a user-mapped id from the `zones`
        option) wins when it exists."""
        key = (prefix, metric, z)
        hit = self._fused_id_cache.get(key)
        if hit:
            return hit
        current = f"sensor.crop_steering_{prefix}{metric}_zone_{z}"
        legacy = f"sensor.crop_steering_{prefix}zone_{z}_{metric}"
        for cand in ([override] if override else []) + [current, legacy]:
            v, _, _ = ha_get(cand)
            if v not in (None, "unknown", "unavailable", ""):
                self._fused_id_cache[key] = cand
                return cand
        return override or current

    def _on(self, entity, default=False):
        v, _, _ = ha_get(entity)
        if v in (None, "unknown", "unavailable", ""):
            return default
        return str(v).lower() in ON_STATES

    def _device(self, entity, quantity, keep_refused=False):
        """One read of a mapped device (a moisture or EC probe, a feed probe, a power plug) through the device-unit
        table (crop_steering_engine.defaults.UNITS) -> (value in the quantity's canonical unit or None, state,
        unit, last_updated, how the unit was taken or None when there is no number, attributes). Every numeric
        device read goes through here or _device_history, so none can skip the table (tests/test_device_units.py).
        The unit of an entity that is unavailable now is the one it last reported this run."""
        v, attrs, lu = ha_get(entity)
        seen = self.__dict__.setdefault("_device_units", {})
        unit = (attrs or {}).get("unit_of_measurement")
        if v in (None, "unknown", "unavailable", ""):
            return None, v, seen.get(entity, unit), lu, None, attrs
        seen[entity] = unit
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None, v, unit, lu, None, attrs
        if not math.isfinite(f):
            return None, v, unit, lu, None, attrs
        value, taken = self._canonical(entity, quantity, f, unit, keep_refused)
        return value, v, unit, lu, taken, attrs

    def _canonical(self, entity, quantity, number, unit, keep_refused=False, keep_unknown=False):
        """`number` from `entity` in its quantity's canonical unit -> (value or None, how the unit was taken). A
        unit that is not simply recognised is said once a run in the log, naming the sensor and the unit.
        `keep_refused`: a refused unit is read as the canonical unit while plausible, as before the table (the
        source-water gate holds on a dead feed probe, so setting one aside would stop a room that waters).
        `keep_unknown`: a unit the table does not know, or none, is read as the canonical unit whatever the
        number, as before the table (the dosing runner: its own checks bound every dose)."""
        value, taken = to_canonical(quantity, number, unit)
        lo, hi = UNITS[quantity]["plausible"]
        if taken == "refused" and keep_refused and lo <= number <= hi:
            value, taken = number, "kept"
        if taken in ("unrecognised", "implausible") and keep_unknown:
            value, taken = number, "as before"
        said = self.__dict__.setdefault("_unit_notices", set())
        if taken != "recognised" and (entity, unit, taken) not in said:
            said.add((entity, unit, taken))
            table = UNITS[quantity]
            log(f"unit: {entity} reports {quantity} in {unit or 'no unit'!r}: " + {
                "refused": f"no exact conversion to {table['canonical']}, so its readings are set aside",
                "kept": f"no exact conversion to {table['canonical']}, but it is read as {table['canonical']} "
                        f"while it stays within {lo:g}-{hi:g}, as it always was, so it keeps feeding its gate",
                "unrecognised": f"not a unit the table knows, so it is read as {table['canonical']} "
                                f"while it stays within {lo:g}-{hi:g}",
                "implausible": f"not a unit the table knows, and {number:g} is outside {lo:g}-{hi:g} "
                               f"{table['canonical']}, so the reading is set aside",
                "as before": f"not a unit the table knows, so it is read as {table['canonical']}, as it always was",
            }[taken])
        return value, taken

    def _device_history(self, entity, quantity, since):
        """Every reading `entity` has had since `since`, through the device-unit table, as [(value, last_changed)],
        or None when there is no evidence: Home Assistant can't say, or a reading had to be set aside for its
        unit. History rows carry no unit (ha_history asks for none), so each is read in the unit the entity
        reports now, or last reported this run while it is unavailable."""
        rows = ha_history(entity, since)
        if rows is None:
            return None
        unit = self._device(entity, quantity)[2]
        out = []
        for state, changed in rows:
            try:
                number = float(state)
            except (TypeError, ValueError):
                continue
            value = self._canonical(entity, quantity, number, unit)[0]
            if value is None:
                return None
            out.append((value, changed))
        return out

    def _read_sensor(self, entity, quantity, max_age_min=20, keep_refused=False):
        """A device's live reading in its quantity's canonical unit, or None: no number, set aside for its unit,
        outside the quantity's sane range, stale, or stamped in the future."""
        lo, hi = UNITS[quantity]["plausible"]
        f, _v, _unit, lu, _taken, _attrs = self._device(entity, quantity, keep_refused)
        if f is None or f < lo or f > hi:
            return None
        try:
            if not lu:
                return None
            ts = datetime.fromisoformat(str(lu).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                return None
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age < -60.0 or age > max_age_min * 60.0:
                return None
        except (ValueError, TypeError, OverflowError):
            return None
        return f

    def _read_feed_ec(self, room):
        if not room.feed_ec_sensor:
            return None
        # A feed probe in ppm or ppt is read as before (keep_refused): never a new dead-feed hold.
        feed = self._read_sensor(room.feed_ec_sensor, "ec", keep_refused=True)
        if feed is not None:
            lo = self._num(f"number.crop_steering_{room.prefix}irrigation_ec_min", 0)
            hi = self._num(f"number.crop_steering_{room.prefix}irrigation_ec_max", 0)
            if (lo <= 0 or feed >= lo) and (hi <= 0 or feed <= hi):
                room._feed_last_good_value, room._feed_last_good_time = (
                    feed,
                    datetime.now(),
                )
        return feed

    def _read_feed_ph(self, room):
        if not room.feed_ph_sensor:
            return None
        ph = self._read_sensor(room.feed_ph_sensor, "ph")
        if ph is not None:
            lo = self._num(f"number.crop_steering_{room.prefix}irrigation_ph_min", 0)
            hi = self._num(f"number.crop_steering_{room.prefix}irrigation_ph_max", 0)
            if (lo <= 0 or ph >= lo) and (hi <= 0 or ph <= hi):
                room._feed_ph_last_good, room._feed_ph_last_good_time = (
                    ph,
                    datetime.now(),
                )
        return ph

    def _veg(self, room, zone):
        v, _, _ = ha_get(f"select.crop_steering_{room.prefix}zone_{zone}_steering_mode")
        if v in (None, "unknown", "unavailable", ""):
            v, _, _ = ha_get(f"select.crop_steering_{room.prefix}growth_stage")
        return str(v or "Generative").lower().startswith("veg")

    def _lights_on(self, room, now):
        h = now.hour + now.minute / 60.0
        on, off = room.lights_on_hour, room.lights_off_hour
        return (on <= h < off) if on <= off else (h >= on or h < off)

    def _hours_to(self, now, target):
        h = now.hour + now.minute / 60.0
        d = target - h
        return d if d >= 0 else d + 24.0

    def _grow_day_start(self, room, now):
        return (
            now.date()
            if (now.hour + now.minute / 60.0) >= room.lights_on_hour
            else (now - timedelta(days=1)).date()
        )

    def _refresh_lights(self, room):
        """Lights are configured once in the integration, per room. Read them live from
        number.crop_steering_<prefix>lights_on_hour / _off_hour each loop, keeping the hours last
        read through a loop that can't read them, and falling back to the add-on option only when
        none have been read since start (an older integration without the entities). Log the
        source once per room, and alert once if the integration value disagrees with the
        (now-legacy) add-on option."""
        lon = self._num_or_none(f"number.crop_steering_{room.prefix}lights_on_hour")
        loff = self._num_or_none(f"number.crop_steering_{room.prefix}lights_off_hour")
        if lon is not None and loff is not None:
            src = "integration"
            room._lights_last_read = (lon, loff)
        elif getattr(room, "_lights_last_read", None):
            # One unreadable loop (Home Assistant restarting, an integration reload, a timed-out
            # read) must not swap in the option: with the integration on 7-20 and the option on
            # 10-22, 08:30 read as lights-off, the zone was forced to P3, and the next loop's
            # lights-on edge restarted its day, daily volume and shot count included.
            (lon, loff), src = room._lights_last_read, "integration (last reading)"
        else:
            lon, loff, src = (
                room.opt_lon,
                room.opt_loff,
                "add-on option (integration entity missing)",
            )
        if not room._lights_logged:
            tag = "" if room.prefix == "" else f"[{room.slug}] "
            log(f"config: {tag}lights {int(lon)}:00-{int(loff)}:00 (source: {src})")
            if (
                src == "integration"
                and room.prefix == ""
                and (lon != room.opt_lon or loff != room.opt_loff)
                and not self._lights_option_was_never_the_source(room)
            ):
                self._alert(
                    "lights_source",
                    "CS-403",
                    "lights hours now come from the integration",
                    f"The engine uses lights on at {int(lon)}:00 and off at {int(loff)}:00 from the "
                    "integration. The controller app's own option still says "
                    f"{int(room.opt_lon)}:00-{int(room.opt_loff)}:00, which is used only when the "
                    "integration's hours can't be read and haven't been since the controller app "
                    "started: set it to the same hours so that can't move lights-on. If the "
                    "integration's hours are wrong, change its Lights on hour and Lights off hour."
                    "\n\nSettings: number.crop_steering_lights_on_hour, number.crop_steering_lights_off_hour",
                    room=room,
                )
            room._lights_logged = True
        room.lights_on_hour, room.lights_off_hour = float(lon), float(loff)

    def _lights_option_was_never_the_source(self, room):
        """A room made by the setup wizard, on an app whose lights option nobody touched.

        The wizard asks for the lights hours and the integration holds the answer; the option is
        still the shipped 10-22, so "the add-on option still says 10:00-22:00" told every new
        install about a setting they never made. A room on the legacy kill-switch helper may rely
        on exactly that shipped value, and an option somebody changed is somebody's intent: both
        still get the alert."""
        if (room.opt_lon, room.opt_loff) != SHIPPED_LIGHTS:
            return False
        flag = str(self._default_descriptor().get("enable_flag") or "")
        return flag.startswith("switch.crop_steering_")

    # ---------- params + snapshot ----------
    def _params(self, room, zone, ec_known=True):
        veg = self._veg(room, zone)
        sfx = "veg" if veg else "gen"
        base = self._zone_num(room, zone, "p2_vwc_threshold", FALLBACK["p2_vwc_threshold"])
        p1t = self._zone_num(room, zone, "p1_target_vwc", FALLBACK["p1_target_vwc"])
        fc = self._zone_num(room, zone, "field_capacity", FALLBACK["field_capacity"])
        efloor = self._zone_num(room, zone, "p3_emergency_vwc_threshold", FALLBACK["p3_emergency_vwc_threshold"])
        # EC-steer offset is shell-owned (decide() no longer nudges). Bake it into the
        # P2 rewater threshold, clamped to the same safe band the engine used: never
        # below the emergency-floor band, never above the ramp ceiling.
        # Keep learned state for recovery, but never apply stale EC steering while blind to EC.
        p2_thr = base + (float(room.state[zone].get("ec_offset", 0.0)) if ec_known else 0.0)
        p2_thr = max(efloor + 3.0, min(min(p1t, fc) - 1.0, p2_thr))
        prof = _profile(room)
        raw = ZoneParams(
            p1_target=p1t,
            p2_threshold=p2_thr,
            p2_shot_size=self._zone_num(room, zone, "p2_shot_size", FALLBACK["p2_shot_size"]),
            p1_initial=self._zone_num(room, zone, "p1_initial_shot_size", FALLBACK["p1_initial_shot_size"]),
            p1_incr=self._zone_num(room, zone, "p1_shot_size_increment", FALLBACK["p1_shot_size_increment"]),
            p1_max_shots=int(self._zone_num(room, zone, "p1_maximum_shots", FALLBACK["p1_maximum_shots"])),
            p1_min_shots=int(self._zone_num(room, zone, "p1_minimum_shots", FALLBACK["p1_minimum_shots"])),
            # new settings: an integration older than them has no such number, and the fallback is the rule as it was
            p1_rise_pts=self._zone_num(room, zone, "p1_rise_pts", FALLBACK["p1_rise_pts"], optional=True),
            p1_max_extra_shots=int(self._zone_num(
                room, zone, "p1_maximum_extra_shots", FALLBACK["p1_maximum_extra_shots"], optional=True)),
            p1_time_between_min=self._zone_num(room, zone, "p1_time_between_shots", FALLBACK["p1_time_between_shots"]),
            dryback_target=self._zone_num(
                room,
                zone,
                f"{'vegetative' if veg else 'generative'}_dryback_target",
                FALLBACK[f"{'vegetative' if veg else 'generative'}_dryback_target"],
            ),
            p0_max_wait_min=self._zone_num(room, zone, "p0_maximum_wait_time", FALLBACK["p0_maximum_wait_time"]),
            # Per zone only. Optional: an integration older than the setting leaves it at 0 (off), so
            # P0 waits for the dryback target as it always has, and nothing alerts.
            p0_additional_dryback=self._zone_num(
                room, zone, "p0_additional_dryback", FALLBACK["p0_additional_dryback"], optional=True
            ),
            ec_target_p0=self._zone_num(room, zone, f"ec_target_{sfx}_p0", FALLBACK[f"ec_target_{sfx}_p0"]),
            ec_target_p1=self._zone_num(room, zone, f"ec_target_{sfx}_p1", FALLBACK[f"ec_target_{sfx}_p1"]),
            ec_target_p2=self._zone_num(room, zone, f"ec_target_{sfx}_p2", FALLBACK[f"ec_target_{sfx}_p2"]),
            p3_emergency_floor=efloor,
            p3_emergency_shot=self._zone_num(room, zone, "p3_emergency_shot_size", FALLBACK["p3_emergency_shot_size"]),
            p2_time_between_min=self._zone_num(
                room, zone, "p2_time_between_shots", FALLBACK["p2_time_between_shots"], optional=True
            ),
            p2_min_interval_min=self._zone_num(
                room, zone, "ec_min_interval", FALLBACK["ec_min_interval"], optional=True
            ),
            p3_time_between_min=self._zone_num(
                room, zone, "p3_time_between_shots", FALLBACK["p3_time_between_shots"], optional=True
            ),
            # Opt-in: an older integration has no such switch, and a missing one is off (P3 as before).
            p3_hold=self._on(
                f"switch.crop_steering_{room.prefix}zone_{zone}_p3_dryback_hold", False
            ),
            # Fallback used ONLY when a zone has no readable max_daily_volume entity — e.g. a zone the
            # engine detected from its VWC sensor but the integration never built a cap entity for
            # (num_zones < detected zones). Must fail LOW: under the 200 L the integration's entity allowed
            # when this was set (its limit now follows the zone's size, ZONE_BOUNDS). Was 300, which let
            # orphaned zones free-run to 300 L/day while wired zones honoured their cap.
            max_daily_volume=self._zone_num(room, zone, "max_daily_volume", FALLBACK["max_daily_volume"]),
            field_capacity=fc,
            max_ec=self._zone_num(room, zone, "maximum_ec", FALLBACK["maximum_ec"]),
            stacking_on=self._on(
                f"switch.crop_steering_{room.prefix}ec_stacking_enabled", False
            ),
            watchdog_hours=self._zone_num(room, zone, "watchdog_hours", FALLBACK["watchdog_hours"]),
            # mL/plant x plants -> zone-L floor (0 if either unset). An integration older than the
            # zone's number has only the old input_number helper (TODO: drop that site-shaped id).
            min_daily_volume=self._zone_num(
                room,
                zone,
                "min_daily_ml_per_plant",
                self._num(f"input_number.crop_steering_{room.prefix}zone_{zone}_min_daily_ml_per_plant", 0.0),
                optional=True,
            )
            * self._zone_num(room, zone, "plant_count", FALLBACK["plant_count"])
            / 1000.0,
            # Anti-drown VWC cap on the floor: field capacity plus a margin, inside the engine's
            # 50-100 band. An engine-only knob (no integration entity) still overrides it.
            drown_ceiling=self._zone_num(
                room, zone, "min_floor_drown_ceiling", max(50.0, min(100.0, fc + MIN_FLOOR_FC_MARGIN)), optional=True
            ),
            ec_settle_min=prof["ec_settle_min"],
            p0_ec_flush_ratio=prof["p0_ec_flush_ratio"],
            p0_ec_flush_shot=prof["p0_ec_flush_shot"],
            ec_adjust_up=prof["ec_adjust_up"],
            ec_adjust_down=prof["ec_adjust_down"],
        )
        p, warns = validate_params(raw)
        for w in warns:
            self._alert(
                f"cfg_{room.slug}_z{zone}_{w.split('=')[0]}",
                "CS-401",
                "setting outside the engine's range",
                "A setting is outside what the engine accepts, so the engine uses the nearest "
                "allowed value instead. The setting itself accepts a wider range than the engine "
                "does. Set it inside the range shown to clear this; where the detail compares two "
                "settings (a minimum above its maximum), change either one. The minimum daily volume "
                f"is worked out from mL per plant and plant count.\n\nDetail: {w}",
                room=room,
                zone=zone,
            )
        return p

    def _watch_probe_methods(self, room):
        """CS-502: a zone set to steer on its Lowest or Highest probe that has too few probes that
        agree, so the integration steers it on their median (calculations.fuse_probes publishes the
        choice as `method`, what it used as `steered_by`). Watering carries on, on the median.
        CS-504: a zone with pore and bulk EC probes steering on bulk (`ec_type`), as no pore probe
        reports. Watering carries on."""
        for zone in room.zones:
            for metric, what in (("vwc", "moisture"), ("ec", "EC")):
                looking = self._fused_id(room.prefix, metric, zone, room.zones[zone].get(metric))
                attrs = self._device(looking, metric)[5] or {}
                if metric == "ec" and attrs.get("ec_type") == "bulk":
                    left_out = ", ".join(sorted((attrs.get("excluded") or {}).keys())) or "none"
                    self._alert(
                        f"ec_type_{room.slug}_z{zone}",
                        "CS-504",
                        "steering on bulk EC: no pore EC probe reporting",
                        "This zone has pore EC and bulk EC probes, which are never combined. No "
                        "pore EC probe is reporting, so the zone's EC comes from its bulk EC "
                        "probes, which read lower than pore EC from the same slab: EC targets, "
                        "stacking and flushes act on that lower number until a pore EC probe "
                        "reports again. Check the pore EC probes listed below."
                        f"\n\nSensor: {looking}\nLeft out: {left_out}",
                        room=room,
                        zone=zone,
                    )
                if attrs:
                    self._watch_primary_probe(room, zone, metric, what, looking, attrs)
                chosen, steered = attrs.get("method"), attrs.get("steered_by")
                if not chosen or not steered or chosen == steered:
                    continue
                left_out = ", ".join(sorted((attrs.get("excluded") or {}).keys())) or "none"
                self._alert(
                    f"probe_method_{room.slug}_z{zone}_{metric}",
                    "CS-502",
                    f"too few {what} probes agree for {chosen}",
                    f"This zone's {what} is set to steer on its {chosen.lower()} probe, which needs "
                    f"three probes that agree. Fewer do, so it steers on their {steered.lower()} "
                    "instead and watering carries on. Check the probes left out of the reading "
                    "(one pulled out of its cube, or in a puddle), or choose Median for the zone."
                    f"\n\nSensor: {looking}\nLeft out: {left_out}",
                    room=room,
                    zone=zone,
                )

    def _watch_primary_probe(self, room, zone, metric, what, looking, attrs):
        """CS-505: the probe the zone's setup names primary (published as `primary`) gives no reading
        or has stopped reporting, so the zone's reading is made from its other probes. Said once
        while it stays offline; the card goes when it reports again. No primary, no alert."""
        key = f"probe_primary_{room.slug}_z{zone}_{metric}"
        primary = attrs.get("primary")
        why = (attrs.get("excluded") or {}).get(primary) if primary else None
        if why not in ("no reading", "not reporting"):
            if key in self._alerted:
                ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}")
                self._alerted.pop(key, None)
                self._alert_codes.pop(key, None)
            return
        if key in self._alerted:
            return
        self._alert(
            key,
            "CS-505",
            f"the primary {what} probe is offline",
            f"The probe chosen as this zone's primary for {what} "
            f"{'gives no reading' if why == 'no reading' else 'has stopped reporting'}. The zone's reading "
            "carries on from its other probes, and watering with it. Check the probe's cable, "
            "power and its device in Home Assistant, or choose another primary under the zone's "
            f"Probes. You are told once; this goes when it reports again.\n\nSensor: {looking}\n"
            f"Primary: {primary}",
            room=room,
            zone=zone,
            quiet=False,
        )

    def _snapshot(self, room, zone, now, lights_on, lights_just_on):
        st = room.state[zone]
        vwc = self._read_sensor(
            self._fused_id(room.prefix, "vwc", zone, room.zones[zone].get("vwc")), "vwc"
        )
        ec = self._read_sensor(
            self._fused_id(room.prefix, "ec", zone, room.zones[zone].get("ec")), "ec"
        )
        if vwc is None:
            return None, self._params(room, zone)
        if vwc > st["peak"]:
            st["peak"] = vwc
        st["win"] = (st["win"] + [(now, vwc)])[-30:]
        rate = 0.0
        if len(st["win"]) >= 3:
            t0, v0 = st["win"][0]
            dt_h = (now - t0).total_seconds() / 3600.0
            if dt_h > 0:
                rate = max(0.0, (v0 - vwc) / dt_h)
        ec_settled = self._settled_ec(st, ec, now, _profile(room)["ec_settle_min"])
        feed_live = self._read_feed_ec(room)
        if feed_live is not None:
            feed_ec = feed_live
        elif feed_grace_ok(
            now.timestamp(),
            (
                room._feed_last_good_time.timestamp()
                if room._feed_last_good_time
                else None
            ),
            self.feed_grace_min,
        ):
            feed_ec = room._feed_last_good_value
        else:
            feed_ec = None
        new_grow_day = self._new_grow_day(room, st, now, lights_on)
        snap = ZoneSnapshot(
            vwc=vwc,
            ec=ec,
            phase=st["phase"],
            peak_vwc=st["peak"],
            dryback_pct=(
                (st["peak"] - vwc) / st["peak"] * 100 if st["peak"] > 0 else 0
            ),
            dryback_rate=rate,
            shot_count=st["shots"],
            phase_minutes=(now - st["last_phase_change"]).total_seconds() / 60.0,
            minutes_since_shot=(
                (now - st["last_shot"]).total_seconds() / 60.0
                if st["last_shot"]
                else 1e9
            ),
            daily_vol=st["daily_vol"],
            ec_smooth=st["ec_smooth"] if ec is not None else None,
            lights_on=lights_on,
            lights_just_on=lights_just_on,
            hours_to_lights_on=self._hours_to(now, room.lights_on_hour),
            hours_to_lights_off=self._hours_to(now, room.lights_off_hour),
            # the min-daily floor's clock: it is paced from lights-on (core.floor_share)
            hours_since_lights_on=(24.0 - self._hours_to(now, room.lights_on_hour)) % 24.0,
            uptime_min=(now - self._start).total_seconds() / 60.0,
            feed_ec=(feed_ec if feed_ec is not None else 3.0),
            new_grow_day=new_grow_day,
            # the P1 rule (core.decide): reached the target, the peak before the last shot, shots since reaching it
            p1_reached=bool(st.get("p1_reached")),
            p1_peak_before_shot=st.get("p1_peak_before"),
            p1_extra_shots=int(st.get("p1_extra") or 0),
            # ...measured on settled readings, against what the learned gain says the shot should have given
            vwc_settled=self._settled_vwc(st),
            p1_settled_before_shot=st.get("p1_settled_before"),
            p1_expected_rise=st.get("p1_expected_rise"),
            ec_settled=ec_settled,
            # a held plan holds the steering; decide() then fires only the rescues (PLAN_HOLD_EXEMPT)
            steering_held=bool(strategy_block(getattr(room, "strategy_snapshot", None), zone)),
        )
        return snap, self._params(room, zone, ec_known=ec is not None)

    @staticmethod
    def _settled_vwc(st):
        """The zone's settled moisture reading (core.settled_reading): the median of its readings over the last
        SETTLED_VWC_MIN minutes, since its last shot. None before the first reading."""
        win = st.get("win") or []
        if not win:
            return None
        start = win[-1][0] - timedelta(minutes=SETTLED_VWC_MIN)
        last = st.get("last_shot")
        return settled_reading([v for t, v in win if t > start and not (isinstance(last, datetime) and t <= last)])

    def _settled_ec(self, st, ec, now, settle_min=EC_SETTLE_MIN):
        """The pore EC the engine's EC rules act on (ZoneSnapshot.ec_settled).

        A reading counts as settled only settle_min (the room's substrate profile; EC_SETTLE_MIN for generic)
        after the last shot ended: before that the probe
        reads the feed front passing it (6-8 mS/cm during the 22 Sep ramp, on zones whose quiet readings
        were ~4.5). Between settled readings the last one stands. None while the probe itself reads
        nothing valid, and before the first settled reading (decide() then uses the raw reading, as it
        always did). Only settled readings feed ec_smooth, and through it the EC offset step."""
        if ec is None:
            return None
        last = st.get("last_shot")
        if last is None or st.get("last_shot_is_anchor") or (now - last).total_seconds() >= settle_min * 60.0:
            previous = st.get("ec_smooth")
            st["ec_smooth"] = (
                ec if previous is None or not math.isfinite(previous)
                else 0.3 * ec + 0.7 * previous
            )
            st["ec_settled"], st["ec_settled_at"] = ec, now
            return ec
        held = st.get("ec_settled")
        return held if isinstance(held, (int, float)) and math.isfinite(held) else None

    def _new_grow_day(self, room, st, now, lights_on):
        """Lights on, and this zone's daily counters have not been reset for the current grow-day. A zone
        with no dated reset at all (fresh state) only counts from P3, as it always has: a missing date
        never restarts a zone that is already running its day."""
        if not lights_on:
            return False
        ldr = st.get("last_daily_reset")
        if ldr is None:
            return st.get("phase") == "P3"
        return ldr < self._grow_day_start(room, now)

    def _starts_day(self, room, st, now, lights_on, lights_just_on):
        """Will this tick move the zone into P0 on the lights-on / new-grow-day rule (as decide() and
        _blind_time_transition do)?"""
        phase = st.get("phase")
        if not lights_on or phase == "P0":
            return False
        new_day = self._new_grow_day(room, st, now, lights_on)
        return (phase == "P3" and (lights_just_on or new_day)) or (phase in ("P1", "P2") and new_day)

    # ---------- auto setpoints (the engine still fires every shot) ----------
    def _auto_tick(self, room, zone, snap, p, lights_on, now):
        """Learn this zone from its own shots every loop. Rewrite its targets only when the room's
        opt-in switch is on, only on its own per-zone numbers, never while a grow plan owns the room,
        and never one that Jev's Setpoints judge owns."""
        st = room.state[zone]
        if not isinstance(st.get("learn"), dict):
            st["learn"] = auto_setpoints.fresh()
        learn = st["learn"]
        st["last_vwc"] = snap.vwc
        # the pore EC the engine's own rules act on (settled when there is one), so the P1 EC gate helper
        # and the judge reason about the same number the engine does
        ec_rules = getattr(snap, "ec_settled", None)
        ec_rules = snap.ec if ec_rules is None else ec_rules
        auto_setpoints.new_day(learn, self._grow_day_start(room, now).isoformat(), snap.vwc)
        auto_setpoints.tick(learn, snap.vwc, st["phase"], now.timestamp(), lights_on,
                            snap.dryback_rate, self._minutes_since_shot(st, now))
        enabled = self._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)
        planned = bool(getattr(room, "strategy_required", False))
        jev_state = room.__dict__.setdefault("_jev_state", {})
        jev = jev_state.get(zone, "ok") if (self._cf[0] and self._cf[1]) else "disabled"
        # Each lever has one writer. With Jev's Setpoints judge running, the P2 shot size and re-water threshold
        # are its own (jev_bridge) and this learner writes the rest, never consulting the old per-hour judge
        # (26 Sep 2026: that judge walked zone 1's shot to 1 %). Writing nothing at all under the judge left
        # nobody on the P1 target: zone 2 sat at 29.5 under a probe reading 44 % and never ramped (4 Oct 2026).
        judged = jev_bridge.judge_levers(self)
        if judged:
            jev = "disabled"
        writes = enabled and not planned
        stall = None
        note = stop = None  # today's plan: what the dryback gets, and when maintenance shots stop for it
        was = learn["outcome"]
        outcome = auto_setpoints.ramp_outcome(learn, st["phase"])
        if outcome != was:
            if outcome == "plateau" and enabled and jev != "disabled":
                verdict = jev_policy.verdicts(jev_policy.call(
                    self._cf[0], self._cf[1],
                    auto_setpoints.evidence(learn, st["phase"], snap.vwc, p.p1_target, ec_rules, p.ec_target_p2,
                                            self._read_feed_ec(room), p.p2_shot_size, st["shots"]),
                    gateway=self._cf[2] or None, timeout=5.0), learner=_profile(room)["learner"])
                jev = jev_state[zone] = "ok" if verdict is not None else "unavailable"
                if verdict and verdict.get("freeze"):  # a guard can only make it MORE careful
                    auto_setpoints.distrust(learn, f"Jev: {verdict['freeze']}")
                    outcome = learn["outcome"]
            log(f"[{room.slug}] Z{zone} P1 ramp outcome: {outcome} (peak {learn['peak']})")
            if outcome == "suspect":
                self._alert(f"auto_{room.slug}_z{zone}", "CS-404", "automatic targets paused",
                            "Automatic adjustment of this zone's targets is paused, because this "
                            f"morning's ramp didn't look right: {auto_setpoints.frozen_reason(learn)}. "
                            "Watering carries on with the current targets, and the next morning's "
                            "ramp is judged again.",
                            room=room, zone=zone)
            self._save_state()
        # In P2 the judge manages the maintenance shot: asked once an hour, it may nudge the P2 shot
        # size (pore EC) and the working peak, one bounded step per lever per grow-day. It cannot fire,
        # size or delay a shot, and a call that fails or takes too long changes nothing.
        stamp = now.strftime("%Y-%m-%dT%H")
        if (writes and jev != "disabled" and lights_on and st["phase"] == "P2"
                and auto_setpoints.jev_due(learn, stamp)):
            verdict = jev_policy.verdicts(jev_policy.call(
                self._cf[0], self._cf[1],
                auto_setpoints.evidence(learn, "P2", snap.vwc, p.p1_target, ec_rules, p.ec_target_p2,
                                        self._read_feed_ec(room), p.p2_shot_size, st["shots"]),
                gateway=self._cf[2] or None, timeout=5.0), learner=_profile(room)["learner"])
            jev = jev_state[zone] = "ok" if verdict is not None else "unavailable"
            asked = auto_setpoints.jev_verdict(learn, stamp, verdict, p.p2_shot_size, now.strftime("%H:%M"),
                                               _profile(room)["learner"])
            for suffix, value in asked.items():
                self._auto_write(room, zone, suffix, p.p2_shot_size, value, learn, now, by="Jev")
            log(f"[{room.slug}] Z{zone} Jev P2: {learn['jev']['last']}")
            self._save_state()
        if writes:
            current = {
                "p1_target_vwc": p.p1_target, "field_capacity": p.field_capacity,
                "p2_vwc_threshold": self._zone_num(room, zone, "p2_vwc_threshold", FALLBACK["p2_vwc_threshold"], optional=True),
                "p3_emergency_vwc_threshold": p.p3_emergency_floor, "p2_shot_size": p.p2_shot_size,
            }
            h = now.hour + now.minute / 60.0
            ctx = dict(
                lights_on_h=room.lights_on_hour, lights_off_h=room.lights_off_hour,
                minutes_since_lights_on=((h - room.lights_on_hour) % 24) * 60.0 if lights_on else None,
                shots_today=st["shots"], dryback_pct=p.dryback_target, p0_wait_min=p.p0_max_wait_min,
                p1_shot_pct=p.p1_initial, p1_gap_min=p.p1_time_between_min,
                start_vwc=learn["ramp_start"] if learn["ramp_start"] is not None else snap.vwc,
                generative=not self._veg(room, zone),
            )
            today = None if "p2_vwc_threshold" in judged else auto_setpoints.day_plan(learn, current, ctx)
            if today:
                note, stop = today[1].note, curve_tracker.clock(today[1].p2_stop_h)
            if self._follow_fc(room, zone, p, now):
                pass  # the setpoints moved with the zone's highest readings; the learner acts on the next pass
            else:
                want = auto_setpoints.wanted(learn, current, snap.vwc, st["phase"], ctx, others=judged)
                for suffix in ("p1_target_vwc", "field_capacity"):  # the zone's highest readings set these
                    want.pop(suffix, None)
                stall = auto_setpoints.stalled(current, want)
                for suffix, value, _why in setpoint_supervisor.writes(current, want):
                    self._auto_write(room, zone, suffix, current[suffix], value, learn, now)
        state, attrs = auto_setpoints.status(learn, enabled, stall, note, stop)
        if enabled and planned:
            state, attrs["frozen_reason"] = "frozen", "an armed grow plan owns this room's targets"
        who = dict.fromkeys(auto_setpoints.MANAGED, "Auto setpoints learner")
        who["p1_target_vwc"] = "the zone's highest reading of the grow-day before"
        who["field_capacity"] = "the zone's highest reading of this grow-day or the one before"
        who.update(dict.fromkeys(judged, "Jev's Setpoints judge, one notch a night"))
        if jev != "disabled":  # the old per-hour judge, which only ever runs without the Setpoints judge
            who.update(dict.fromkeys(auto_setpoints.JEV_MANAGED, "Jev's hourly P2 check"))
        number = f"number.crop_steering_{room.prefix}zone_{zone}_"
        attrs.update(
            jev=jev, jev_last=learn["jev"]["last"], jev_changed_today=learn["jev"]["changed"],
            working_peak_adjust=learn["peak_adj"],
            updated=now.isoformat(), engine=PRODUCT, friendly_name=f"Zone {zone} auto setpoints",
            managed=[number + s for s in who], managed_by={number + s: w for s, w in who.items()},
        )
        ha_set(f"sensor.crop_steering_{room.prefix}zone_{zone}_auto_setpoints", state, attrs)

    def _vwc_maxima(self, st):
        """-> (field capacity, P1 target) from the zone's highest readings, or (None, None) until a lights-on has
        kept a day before.

        `fc_follow["peak"]` is the highest VWC since this grow-day's lights-on that the follower counts (_count_peak);
        `peak_prev` is the grow-day before's, kept at lights-on. Field capacity is the higher of the two; the P1 target
        is the day before's. Until the first lights-on after the update keeps one, nothing is written: the grow-day in
        progress is no stand-in for it (observed on a production room, 6 Oct 2026, updated after lights-on: a zone's
        ramp stopped at its shot limit at 51.4, and field capacity followed it down from 67.5)."""
        prev = st.get("peak_prev")
        if prev is None or prev <= 0.0:
            return None, None
        return max((st.get("fc_follow") or {}).get("peak") or 0.0, prev), prev

    @staticmethod
    def _count_peak(st, snap):
        """The follower counts this reading toward the grow-day's highest. Only trusted readings come here (a blind or
        distrusted probe never does); a zone held as backed up (CS-310) does not count for the rest of its grow-day,
        what it read before the rise was caught included."""
        fc = st["fc_follow"]
        if snap.backed_up:
            fc["peak"] = None
        elif fc["peak"] is not None and snap.vwc > fc["peak"]:
            fc["peak"] = snap.vwc

    @staticmethod
    def _keep_day_peak(st):
        """Lights-on: the grow-day's counted peak becomes the day before's. A day with none (blind all day, or a CS-310
        day) keeps the one before."""
        fc = st["fc_follow"]
        if fc["peak"]:
            st["peak_prev"] = fc["peak"]
        fc["peak"] = 0.0

    def _follow_fc(self, room, zone, p, now):
        """The zone's setpoints follow its own highest readings -> True when anything was written.

        The rule (adopted 6 Oct 2026): the P1 target is the highest reading the zone reached the day before, field
        capacity rises as the probe's readings do, and the P2 dryback and the rescue floor move with field capacity,
        all without the operator having to do it. So:
          - field capacity = the highest reading of this grow-day or the one before (_vwc_maxima);
          - the P1 target = the highest reading of the grow-day before;
          - when field capacity moves by FC_SHIFT_MIN or more, the P2 re-water threshold moves by the same points, so
            the dryback under full keeps its size. Jev's Setpoints judge takes a moved threshold as the new centre of
            its range (jev_bridge).
        Bounded, as following its own readings feeds a drifting probe back into the ladder (a 15-20 point flood jump
        dragged the whole ladder with it): each setpoint moves at most FC_STEP_MAX points a grow-day, counted from
        where it stood, so an operator's edit is moved from, never undone. The readings counted are the trusted
        ones outside a CS-310 day (_count_peak), and a zone without a usable probe is not followed at all. The
        rescue (P3 emergency) floor is the operator's and never moves (DB-04).
        Nothing is written that would leave the ladder inverted (rescue + 3 <= threshold < P1 target <= field
        capacity): then field capacity alone moves if that is valid, else nothing. Within the engine's bounds and each
        number's own min and max, which Home Assistant enforces. The ladder is written from the top when it moves up
        and from the bottom when it moves down, so it holds after every write, and a refused write stops the rest.
        Only under the room's Auto setpoints switch, never while a grow plan owns it."""
        if not self._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False):
            return False
        if getattr(room, "strategy_required", False):
            return False
        st = room.state[zone]
        seen, yday = self._vwc_maxima(st)
        if seen is None:
            return False
        thr = self._zone_num(room, zone, "p2_vwc_threshold", None, optional=True)
        if thr is None:
            return False
        follow = st["fc_follow"]
        day = self._grow_day_start(room, now).isoformat()
        if follow["day"] != day:
            follow.update(day=day, used={})
        used = follow["used"]

        def bounded(suffix, old, value):
            lo, hi = setpoint_supervisor.BOUNDS[suffix]
            attrs = ha_get(f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}")[1] or {}
            try:
                lo = max(lo, float(attrs["min"]))
            except (KeyError, TypeError, ValueError):
                pass
            try:
                hi = min(hi, float(attrs["max"]))
            except (KeyError, TypeError, ValueError):
                pass
            left = max(0.0, FC_STEP_MAX - used.get(suffix, 0.0))  # what is left of this grow-day's step
            return round(max(lo, old - left, min(hi, old + left, value)), 1)

        fc = bounded("field_capacity", p.field_capacity, seen)
        target = bounded("p1_target_vwc", p.p1_target, min(yday, fc))
        delta = round(fc - p.field_capacity, 1)
        new_thr = bounded("p2_vwc_threshold", thr, thr + delta) if abs(delta) >= _profile(room)["fc_shift_min"] else thr
        rescue = p.p3_emergency_floor
        if rescue + 3.0 <= new_thr < target <= fc:
            writes = [("field_capacity", p.field_capacity, fc), ("p1_target_vwc", p.p1_target, target),
                      ("p2_vwc_threshold", thr, new_thr)]
            if delta < 0:
                writes.reverse()
        elif rescue + 3.0 <= thr < p.p1_target <= fc:
            writes = [("field_capacity", p.field_capacity, fc)]
        else:
            return False
        learn = st["learn"] if isinstance(st.get("learn"), dict) else {}
        wrote = False
        for suffix, old, value in writes:
            if abs(value - old) >= 0.05:
                if not self._auto_write(room, zone, suffix, old, value, learn, now, by="auto (highest reading)"):
                    break  # refused: what is still to move waits for the next loop, the ladder holds
                used[suffix] = round(used.get(suffix, 0.0) + abs(value - old), 1)
                wrote = True
        if wrote:
            self._save_state()
        return wrote

    def _auto_write(self, room, zone, suffix, old, value, learn, now, by="auto"):
        """Write one per-zone number -> False when it was not written (no such number, or Home Assistant refused)."""
        entity = f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}"
        if ha_get(entity)[0] in (None, "unknown", "unavailable", ""):
            return False  # no per-zone number on this install: room-level values are the operator's, never ours
        written = room.__dict__.setdefault("_auto_written", {})
        last = written.get((zone, suffix))
        if last and last[0] == value and (now - last[1]).total_seconds() < 300:
            return True  # HA has not reflected the last write yet: do not spam it
        # Home Assistant sees only this app's token: name the writer first, for the room's setpoint
        # change log (the integration's setpoint_log.py). The brain's put-back is the safety writer.
        who = "safety" if by.endswith("(put back)") else "brain" if by.startswith("Jev") else "learner"
        claim = {"entity_id": entity, "value": value, "who": who}
        if who == "brain":
            # An AI change is an overlay that goes back by itself (the integration's overlays.py): at the
            # lights-on that ends the grow-day it is for. A night move (P3) is for the next grow-day.
            local = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
            day = self._grow_day_start(room, local) + timedelta(days=2 if room.state[zone].get("phase") == "P3" else 1)
            on = datetime.combine(day, datetime.min.time()) + timedelta(hours=room.lights_on_hour)
            claim["expires"] = on.astimezone().isoformat(timespec="seconds")
        ha_fire("crop_steering_setpoint_write", claim)
        if not ha_call("number", "set_value", entity_id=entity, value=value):
            return False
        written[(zone, suffix)] = (value, now)
        learn["last_change"] = f"{now.strftime('%H:%M')} {suffix} {old:g} -> {value:g}"
        tag = "" if room.prefix == "" else f"{room.slug} "
        self._activity.insert(0, f"{now.strftime('%H:%M')} {tag}Z{zone} {by} {suffix} {old:g} -> {value:g}"[:120])
        log(f"[{room.slug}] Z{zone} {by} {suffix} {old:g} -> {value:g}")
        return True

    # ---------- room status (On / Off) ----------
    def _room_active(self, room):
        """OFF = nothing growing: no irrigation and no alerts for this room. A switch that has never
        been seen (an integration older than this add-on) means ON, so behaviour never changes
        silently. One that has been seen and cannot be read right now (Home Assistant restarting)
        keeps its last value: an idle room is not woken, reset and re-alerted by every restart."""
        v, _, _ = ha_get(f"switch.crop_steering_{room.prefix}room_active")
        if str(v).lower() in ("on", "off"):
            room._room_active_known = str(v).lower() == "on"
        elif not hasattr(room, "_room_active_known"):
            saved = (getattr(self, "_saved_room_blocks", {}).get(room.slug) or {}).get("_room_active")
            room._room_active_known = True if saved is None else bool(saved)
        return room._room_active_known

    def _room_switched_off(self, room):
        """Stand the room down: its standing alerts are about a room that is now deliberately idle."""
        log(f"[{room.slug}] room switched OFF - irrigation and alerts stand down")
        # A snapshot: the dosing thread may raise an alert meanwhile (dosing_runner.py). A dosing alert
        # is about one event in the batch tank, which a room going idle does not undo: it stays.
        for key in [k for k in list(self._alerted) if not k.startswith("dosing_")
                    and (f"_{room.slug}_" in k or k.endswith(f"_{room.slug}"))]:
            ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}")
            del self._alerted[key]

    # A room switched back on within this many hours of being seen going off carries on where it was.
    ROOM_RESUME_H = 24

    def _room_switched_on(self, room):
        """Switched back on within ROOM_RESUME_H of being seen going off, a room carries on where it
        was: its phases, today's counters and what it has learned. Turning a room off and on to clear a
        fault must not restart its day: on 25 Sep 2026 three zones in P2 went back to a P1 ramp at
        20:53, an hour before lights-off. A room off for longer, or since before the controller last
        started, is a new crop: yesterday's phase, counters and learned ceiling belong to the last one,
        so it starts a fresh run, and its grow-day begins at once when the lights are on, else at
        lights-on. Water history is a record, so it always stays."""
        off_since, room._off_since = getattr(room, "_off_since", None), None
        now = datetime.now()
        if off_since is not None and timedelta(0) <= now - off_since < timedelta(hours=self.ROOM_RESUME_H):
            minutes = (now - off_since).total_seconds() / 60.0
            log(f"[{room.slug}] room switched ON after {minutes:.0f} min off - carrying on where it was")
            self._save_state()
            return
        log(f"[{room.slug}] room switched ON - starting a fresh run")
        for zone in room.zones:
            old = room.state[zone]
            room.state[zone] = {
                **self._fresh_zone(),
                "phase": "P3",
                "last_shot": datetime.now(),  # the blind-probe schedule counts from switch-on, not from "never"
                "last_shot_is_anchor": True,  # ...but it is not an irrigation, and is never shown as one
                "water_history": old.get("water_history"),
                "water_history_legacy_excluded_l": old.get("water_history_legacy_excluded_l", 0.0),
            }
        room._vmax = {}
        self._save_state()

    # A shot holds the loop, which is synchronous, and a batch of them can hold it past every "not
    # reporting" limit: at the 25 Sep 2026 lights-on, three floor shots in a row kept every room
    # quiet for 8.2 minutes while the controller was busy watering. _wait_shot repeats what each
    # room last reported meanwhile.
    KEEP_ALIVE_S = 60
    # ...at most this many repeats in one round of _wait_shot's checks. A 24-zone room has 25
    # reports, each allowed a second to connect and a second to read: a stalled Home Assistant could
    # hold one round for 50 s, the kill switch unread and the valve open.
    KEEP_ALIVE_WRITES = 2

    def _heartbeat(self, room, now, hardware_fault, room_active=True, timeout=None):
        room._beat, room._beat_at = (hardware_fault, room_active), time.monotonic()
        ha_set(
            f"sensor.crop_steering_{room.prefix}ai_heartbeat",
            "healthy",
            {
                "engine": PRODUCT,
                # which controller is actually RUNNING, for the dashboard's sidebar
                "controller_version": CONTROLLER_VERSION,
                "controller_instance": self.instance_id,  # the duplicate-controller guard's (duplicate_hold)
                "controller_runtime": "container" if _GATE.container else "addon",  # for support
                "last_beat": now.isoformat(),
                # the kill switch this room ACTUALLY uses — the integration's health
                # check reads this so a custom enable_flag isn't flagged as "missing"
                "enable_flag": room_gate(room),
                "hardware_fault": hardware_fault,
                "strategy_snapshot_version": 1,
                "setup_lifecycle_version": 1,
                "strategy_required": getattr(room, "strategy_required", False),
                "strategy_error": (getattr(room, "strategy_snapshot", None) or {}).get("error"),
                "setup_revision": getattr(room, "setup_revision", 0),
                "setup_active": getattr(room, "setup_active", True),
                "setup_pending": getattr(room, "_setup_pending", None),
                "room_active": room_active,
                "max_run": self._max_run_report(room),
            },
            **({"timeout": timeout} if timeout else {}),
        )

    def _keep_alive(self, remaining):
        """While a shot holds the loop, repeat each part of a room's last report once it is a minute
        old: its heartbeat with a fresh time, and its zones' status labels as they were. A round
        repeats at most KEEP_ALIVE_WRITES of them, heartbeats first, then the oldest labels, so the
        shot reads its kill switch again within about one of its 2 s rounds however many zones there
        are; the rest follow in the next rounds. The writes are optional, so they are kept short and
        fit in the time the shot has left with a second to spare. requests applies a timeout to the
        connect and to the read separately, so each write gets half its share; as with the shot's
        reads, a slow network can still overshoot."""
        timeout = min(0.5, (remaining - 1) / (2 * self.KEEP_ALIVE_WRITES))
        if timeout < 0.25:
            return
        now = time.monotonic()
        beats = [
            (room._beat_at, room, None)
            for room in self.rooms
            if room._beat is not None and now - room._beat_at >= self.KEEP_ALIVE_S
        ]
        labels = [
            (room._status_at[zone], room, zone)
            for room in self.rooms
            # a zone the room no longer has (its zone count changed in place) is not brought back
            for zone in room.zones
            if zone in room._statuses and now - room._status_at[zone] >= self.KEEP_ALIVE_S
        ]
        due = sorted(beats, key=lambda d: d[0]) + sorted(labels, key=lambda d: d[0])
        for _at, room, zone in due[: self.KEEP_ALIVE_WRITES]:
            if zone is None:
                self._heartbeat(room, datetime.now(), *room._beat, timeout=timeout)
            else:
                self._publish_zone_status(room, zone, *room._statuses[zone], timeout=timeout)

    def _report_before_acting(self, room, decisions, snaps, now):
        """What _keep_alive repeats is a room's last report, and a room has none that holds when
        this process has not reported it yet, or when its last report said "Room off" and it has
        just been switched on. Before this pass's shots, report it afresh: the heartbeat, and the
        label of each zone that is not watered this pass, as the pass will give it. A zone that is
        to be watered gets no label here (whether its shot is blocked is known only as its turn
        comes), so a stale "Room off" is never repeated for it while it waters."""
        room._statuses, room._status_at = {}, {}
        snapshot = getattr(room, "strategy_snapshot", None)
        # A hardware fault holds every zone of the room, wanting water or not: none reads "Optimal".
        held = self._hardware_fault_short(room)
        for zone, (fire, _size, reason) in decisions.items():
            if not fire:
                self._publish_zone_status(
                    room, zone,
                    zone_status_label(room.state[zone]["phase"], False,
                                      held or strategy_block(snapshot, zone),
                                      not held and zone not in snaps, reason),
                    reason,
                )
        self._heartbeat(room, now, self._hardware_fault_block(room))

    @staticmethod
    def _publish_zone_status(room, zone, label, reason, timeout=None):
        """The zone's status label, for the integration's zone_N_status to show. The controller writes
        only this _app entity: zone_N_status belongs to the integration, and two writers made it flip
        between two vocabularies about twice a minute."""
        room._statuses[zone], room._status_at[zone] = (label, reason), time.monotonic()
        ha_set(
            f"sensor.crop_steering_{room.prefix}zone_{zone}_status_app",
            label,
            {"reason": reason, "friendly_name": f"Zone {zone} status (controller)", "engine": PRODUCT},
            **({"timeout": timeout} if timeout else {}),
        )

    @staticmethod
    def _publish_waiting_for(room, zone, snap, p, now):
        """What would move the zone next (crop_steering_engine.waiting_for), for the dashboard's zone
        card and grow-day line. No snapshot (no probe, or the room is off): an empty list, so an old
        one never lingers. A wait's clock time is `at` plus its in_min."""
        conditions = waiting_for(snap, p) if snap is not None else []
        # Kept for the vitals notification's "Next:" lines (_maybe_notify).
        if getattr(room, "_waiting", None) is None:
            room._waiting = {}
        room._waiting[zone] = (conditions, now)
        ha_set(
            f"sensor.crop_steering_{room.prefix}zone_{zone}_waiting_for_app",
            snap.phase if snap is not None else "none",
            {
                "conditions": conditions,
                "at": now.astimezone().isoformat(timespec="seconds"),
                "friendly_name": f"Zone {zone} waiting for (controller)",
                "engine": PRODUCT,
            },
        )

    def _publish_room_off(self, room, now):
        """An OFF room still reports in, so the dashboard shows why it is idle and the integration
        never mistakes a deliberately idle room for a dead engine."""
        px = room.prefix
        try:
            for zone in room.zones:
                self._publish_zone_status(room, zone, "Room off", "Room off (nothing growing)")
                self._publish_waiting_for(room, zone, None, None, now)
                if room.state.get(zone, {}).get("last_shot_is_anchor"):
                    # a room switched on and off again without watering: take back the false
                    # "last irrigation" an earlier controller published for it
                    ha_set(f"sensor.crop_steering_{px}zone_{zone}_last_irrigation_app", "unknown",
                           {"device_class": "timestamp"})
            ha_set(f"sensor.crop_steering_{px}app_status", "room_off",
                   {"engine": PRODUCT, "updated": now.isoformat()})
            ha_set(f"sensor.crop_steering_{px}current_decision", "Room off - nothing growing",
                   {"fired": [], "blocked": []})
            self._heartbeat(room, now, self._hardware_fault_block(room), room_active=False)
        except Exception as e:
            log("publish failed", room.slug, e)

    # ---------- gates ----------
    def _blocked(self, room, zone, reason=None):
        if getattr(room, "_setup_pending", None):
            return room._setup_pending
        if getattr(room, "setup_active", True) is False:
            return "Room archived in integration setup"
        if not self._room_active(room):
            return "Room off (nothing growing)"
        making = self._dosing_hold(room)  # every shot, the rescues a plan hold lets through included
        if making:
            return making
        planned_hold = strategy_block(getattr(room, "strategy_snapshot", None), zone)
        if planned_hold:
            if getattr(reason, "kind", None) not in PLAN_HOLD_EXEMPT:
                return planned_hold
            log(f"[{room.slug}] Z{zone} {planned_hold}: not holding a {reason.kind} shot")
        fault = self._hardware_fault_block(room)
        if fault:
            return fault
        latched = self._max_run_hold(room, zone)
        if latched:
            return latched
        hw = room.hw
        if not hw["valves"].get(zone):
            return (
                "no hardware mapped — set this zone's valve (and the pump and mainline, if the room "
                "has them) in the Crop Steering integration (or the add-on `hardware` option)"
            )
        plumbing = plumbing_hold(hw)
        if plumbing:
            self._alert(
                f"plumbing_{room.slug}",
                "CS-202",
                "plumbing and switches disagree, not watering",
                "The plumbing this room was set up with and the switches mapped to it don't "
                "match, so nothing in this room is watered until they do. The detail below says "
                "what to change, in Rooms & setup."
                f"\n\nDetail: {plumbing}.",
                room=room,
            )
            return plumbing
        undrivable = self._undrivable(room, zone)
        if undrivable:
            names = ", ".join(undrivable)
            self._alert(
                f"actuator_{room.slug}_z{zone}",
                "CS-313",
                "a valve or pump the controller can't switch, not watering",
                "This zone's valve, or the room's pump or main line, is a kind of device the controller "
                "has no way to open and close, so it is never sent a command and the zone is not "
                "watered. Map a switch, an input_boolean or a valve in its place in Rooms & setup."
                f"\n\nCan't be switched: {names}",
                room=room,
                zone=zone,
            )
            return f"{names} can't be switched (a zone valve, main line or pump must be a switch, input_boolean or valve)"
        if not self._on(room_gate(room), False):
            return f"{PRODUCT} disabled (kill switch off)"
        retired = getattr(room, "_retired_off", None)
        if retired:  # switched off in their place this pass; the switch may not read OFF yet
            return f"{' and '.join(retired)} off: engine switch switched off in its place"
        # A zone switch that can't be read holds the zone, as the kill switch does: whether the zone
        # is paused can't be known, and when every one reads unavailable the integration itself is
        # not running (not loaded, disabled, Home Assistant in safe mode), so its overrides can't be
        # read either. A shot already running still ends only on a definite OFF (_wait_shot).
        zone_switch = f"switch.crop_steering_{room.prefix}zone_{zone}_enabled"
        state = ha_get(zone_switch)[0]
        if state in (None, "unknown", "unavailable", ""):
            return f"{zone_switch} unreadable (reads neither on nor off)"
        if str(state).lower() not in ON_STATES:
            return "zone disabled"
        if self._on(
            f"switch.crop_steering_{room.prefix}zone_{zone}_manual_override", False
        ):
            return "manual override"
        # External operator holds (tank dosing / manual fill / flush) are configurable
        # (self.hold_entities, empty by default) — an install without them never holds here.
        # One that can't be read (missing, unknown, unavailable) holds too, as an unreadable zone
        # switch does: whether its tank is being dosed or filled can't be known. A shot already
        # running still ends only on a definite ON (_wait_shot).
        for f in self.hold_entities:
            state = ha_get(f)[0]
            if state in (None, "unknown", "unavailable", ""):
                return f"external hold {f} unreadable (reads neither on nor off)"
            if str(state).lower() in ON_STATES:
                return f"external hold ({f.split('.')[-1]})"
        settings = self._settings_hold(room, zone)
        if settings:
            return settings
        # Source-water EC gate — only when a feed-EC sensor is configured. With no feed sensor
        # the gate is disabled (the dosing/fill holds above still apply) so the add-on is safe
        # out of the box on installs without a reservoir probe.
        if room.feed_ec_sensor:
            feed = self._read_feed_ec(room)
            lo = self._num(f"number.crop_steering_{room.prefix}irrigation_ec_min", 0)
            hi = self._num(f"number.crop_steering_{room.prefix}irrigation_ec_max", 0)
            if lo > 0 or hi > 0:
                if feed is None:
                    if not feed_grace_ok(
                        datetime.now().timestamp(),
                        (
                            room._feed_last_good_time.timestamp()
                            if room._feed_last_good_time
                            else None
                        ),
                        self.feed_grace_min,
                    ):
                        return f"source-water EC dead >{self.feed_grace_min:.0f}min — holding (fail-closed)"
                    # Inside the grace window we skip the EC band check only — fall through
                    # so the pH gate below still runs. Returning None here would report the
                    # zone as unblocked and silently bypass pH entirely.
                elif (lo > 0 and feed < lo) or (hi > 0 and feed > hi):
                    return f"source-water EC {feed:.1f} out of [{lo:g},{hi:g}]"
        # pH half of the source-water gate — bad-pH feed locks out nutrients / burns roots, so
        # gate it too, but only when a feed-pH sensor is configured.
        if room.feed_ph_sensor:
            ph_lo = self._num(f"number.crop_steering_{room.prefix}irrigation_ph_min", 0)
            ph_hi = self._num(f"number.crop_steering_{room.prefix}irrigation_ph_max", 0)
            if ph_lo > 0 or ph_hi > 0:
                ph = self._read_feed_ph(room)
                if ph is None:
                    if not feed_grace_ok(
                        datetime.now().timestamp(),
                        (
                            room._feed_ph_last_good_time.timestamp()
                            if room._feed_ph_last_good_time
                            else None
                        ),
                        self.feed_grace_min,
                    ):
                        return f"source-water pH probe dead >{self.feed_grace_min:.0f}min — holding (fail-closed)"
                elif (ph_lo > 0 and ph < ph_lo) or (ph_hi > 0 and ph > ph_hi):
                    return f"source-water pH {ph:.2f} out of [{ph_lo:g},{ph_hi:g}]"
        # Last, once nothing else holds the zone: a switch that reads neither on nor off (its device
        # offline, Home Assistant still starting) accepts a command without switching and cannot be read
        # back after the shot. On 25 Sep 2026 a shot opened onto an offline pump, could not be confirmed
        # closed, and latched a hold that stopped the room for 7 hours. Nothing is opened until the
        # whole feed path reads again, and nothing latches.
        offline = [e for e in (hw.get("pump"), hw.get("mainline"), hw["valves"].get(zone))
                   if e and str(hw_get(e)[0]).lower() not in ("on", "off")]
        if offline:
            return f"{', '.join(offline)} offline (reads neither on nor off)"
        return None

    # ---------- alerts / notify ----------
    @staticmethod
    def _zone_names(attrs):
        """The names the operator gave the zones ({2: "GT4"}), from the room's descriptor. A zone
        still called "Zone N", or a descriptor without names, has none."""
        names = (attrs or {}).get("zone_names")
        found = {}
        for key, name in (names.items() if isinstance(names, dict) else ()):
            try:
                zone = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(name, str) and name.strip() and name.strip() != f"Zone {zone}":
                found[zone] = name.strip()[:40]
        return found

    @staticmethod
    def _substrate(attrs):
        """What the room grows in, from its descriptor: "generic" when an older integration publishes
        none or the value is one this controller does not know."""
        value = (attrs or {}).get("substrate", "generic")
        return value if value in SUBSTRATES else "generic"

    @staticmethod
    def _room_name(attrs):
        """The name the operator gave the room, from its descriptor. "" when it has none: an older
        integration publishes none, and the wizard's own default is not a name anyone chose."""
        name = (attrs or {}).get("room_name")
        if not isinstance(name, str):
            return ""
        name = name.strip()[:40]
        return "" if name.lower() in ("default", "crop steering", "crop steering system") else name

    def _where(self, room, zone=None):
        """Where a notification is about, the way the operator named it: "Tent · GT4 (Z2)". An
        install with one unnamed room says nothing about the room; the internal "default" is
        never shown unless two rooms would otherwise read the same."""
        name = getattr(room, "room_name", "")
        if not name and len(self.rooms) > 1:
            name = room.slug
        if zone is None:
            return name
        return " · ".join(p for p in (name, self._zone_title(room, zone)) if p)

    @staticmethod
    def _zone_title(room, zone):
        """A zone in a notification: "GT4 (Z2)" when the operator named it, else "Zone 2". The
        number is always there, because the entity ids and the log say zone N."""
        name = getattr(room, "zone_names", {}).get(zone)
        return f"{name} (Z{zone})" if name else f"Zone {zone}"

    def _alert_due(self, key, code=None):
        """Whether `key` may be raised now: out of its 30-minute repeat window, or raised under a
        different code at least 5 minutes ago. One key can carry several codes (a probe going from
        CS-101 to CS-102, a zone from CS-206 to CS-205), and its card must not keep the old
        diagnosis for half an hour; the 5 minutes stop a flapping cause re-raising it every loop."""
        last = self._alerted.get(key)
        if not last:
            return True
        age = (datetime.now() - last).total_seconds()
        if code is not None and self._alert_codes.get(key, code) != code:
            return age >= 300
        return age >= 1800

    def _push_due(self, key, code, now):
        """Whether this raise of `key` also pushes to a phone (see NOT_WATERING_CODES): the first raise of an
        episode always does; its repeats decay by the code's severity. A push only ever goes with a card, so a
        step falls due at the card's next update after it. Call before the raise is recorded in _alerted."""
        pushes = self.__dict__.setdefault("_pushes", {})  # key -> (pushes this episode, the last one's time, code)
        last = self._alerted.get(key)
        count, pushed, was = pushes.get(key, (0, None, None))
        if last is None or was != code or (now - last).total_seconds() > ALERT_EPISODE_GAP_S:
            count, pushed = 0, None  # a new episode
        if pushed is None:
            due = True
        elif code in CRITICAL_CODES or code in NOT_WATERING_CODES:
            due = (now - pushed).total_seconds() >= 1800
        elif code in INFO_CODES:
            due = False
        else:
            step = WARNING_REPUSH_MIN[min(count, len(WARNING_REPUSH_MIN)) - 1]
            due = (now - pushed).total_seconds() >= step * 60
        pushes[key] = (count + 1, now, code) if due else (count, pushed, code)
        return due

    def _carry_retired_switches(self, room):
        """Switch the engine switch off for each RETIRED_SWITCHES entry that reads off, and return
        their names. Only ever OFF: an off one never switches watering back on. A retired switch
        that is on, missing or unreadable changes nothing (the integration will remove them).
        Not while an interrupted shot is unsettled: _reconcile_room_inflight reads an engine switch
        that is off as a person taking over, and would leave what the shot opened running. The
        names still hold the room (_blocked) until the switch goes off after the shot is settled."""
        off = []
        for key, name in RETIRED_SWITCHES:
            entity = f"switch.crop_steering_{room.prefix}{key}"
            state, _, _ = ha_get(entity)
            if str(state).lower() != "off":
                continue
            off.append(name)
            if getattr(room, "shot_inflight", None) or not self._on(room_gate(room), False):
                continue  # a shot still to settle, or watering is off already: nothing is switched
            ha_call(room_gate(room).split(".", 1)[0], "turn_off", entity_id=room_gate(room))
            log(f"[{room.slug}] {name} ({entity}) is off: engine switch {room_gate(room)} switched off")
            self._alert(
                f"retired_switch_{room.slug}_{key}",
                "CS-208",
                f"{name} is off, so watering was switched off",
                f"{name} no longer stops watering by itself: the room's Watering switch does that, "
                f"its engine switch ({room_gate(room)}). Because {name} ({entity}) is off, the "
                "controller switched watering off in its place, and does so again while it stays "
                f"off. Switch {name} back on in Home Assistant, then switch watering on in Crop "
                "Steering → Settings → Watering.",
                room=room,
            )
        return off

    def _alert(self, key, code, title, message, room=None, zone=None, quiet=True):
        """Raise notification `f2_{key}` with its error code (docs/error-codes.json; the dashboard's
        Help & tools lists the same catalog). The key, and so the notification id, never changes
        with the wording: an update replaces an old notification instead of adding a second one.
        True once Home Assistant has it; False while it is inside its quiet period (`quiet`: for a
        condition re-checked every loop) or could not be created."""
        if quiet and not self._alert_due(key, code):
            return False
        now = datetime.now()
        where = self._where(room, zone) if room is not None else ""
        title = f"{where}: {title} ({code})" if where else f"{title[:1].upper()}{title[1:]} ({code})"
        log("ALERT", title, "-", " ".join(message.split()))
        message = (
            f"{message}\n\nCode {code}. What it means and what to do: "
            "Crop Steering → Help & tools → Error codes."
        )
        # The 30-minute quiet period starts only once Home Assistant HAS the notification: an alert
        # raised while it is unreachable (the moment a close fails, typically) is raised again on the
        # next call, not silenced for half an hour. The phone push goes with it, never without it.
        if not ha_call(
            "persistent_notification",
            "create",
            title=title,
            message=message,
            notification_id=f"f2_{key}",
        ):
            return False
        push = self._push_due(key, code, now)
        self._alerted[key] = now
        self._alert_codes[key] = code
        if push:
            self._push(key, code, title, message, room, zone, self._notify_config()[0])
        return True

    def _push(self, key, code, title, message, room, zone, recipients):
        """An alert's phone push (docs/NOTIFICATIONS.md). With phones set up in the integration it goes through
        crop_steering.notify to the ones whose row ticks its kind of alert, and nothing is pushed here. With none,
        or when that call fails, it goes to the notify_service option exactly as it always did: never both, and
        never lost to the router."""
        if recipients:
            try:
                if self._route(key, code, None, room, zone, title, message, code in CRITICAL_CODES):
                    return
            except Exception as e:  # whatever goes wrong, the push goes the old way
                log("notify: crop_steering.notify failed", key, e)
        dom, _, svc = self.notify_service.partition("/")
        if dom and svc:
            ha_call(dom, svc, title=title, message=message)
        else:
            log("notify: the push for", key, "went to no phone: none takes it in Crop Steering, and the "
                "notify_service option is empty")

    def _route(self, key, code, event, room, zone, title, message, urgent=False, timeout=NOTIFY_TIMEOUT_S):
        """Hand one push to crop_steering.notify, asking for its answer -> True when the integration took it: sent
        to the phones that ask for it, or to none because none does. False when it could not be asked, refused it
        (HTTP 4xx or 5xx, no answer in `timeout`), sent it nowhere and said why (nobody set up after all, or every
        phone it tried failed), or when an emergency (`urgent`) reached no phone at all."""
        data = {"key": key, "title": title, "message": message}
        for name, value in (("code", code), ("event", event), ("zone", zone)):
            if value is not None:
                data[name] = value
        if room is not None:
            data["room"] = room.prefix
        if urgent:
            data["urgent"] = True
        status, answer = ha_service_response("crop_steering", "notify", data, timeout)
        if status is None or not 200 <= status < 300:
            log("notify: crop_steering.notify did not take", key, "HTTP", status)
            return False
        sent = answer.get("sent_to") if isinstance(answer, dict) else None
        if isinstance(answer, dict) and answer.get("error") and not sent:
            log("notify: crop_steering.notify sent", key, "to nobody:", answer["error"])
            return False
        if urgent and not sent:  # an emergency must reach a phone: the notify_service option is tried next
            log("notify: emergency", key, "reached no phone through crop_steering.notify")
            return False
        return True

    def _notify_config(self, refresh=False):
        """(recipients, idle_hours) from the integration's sensor.crop_steering_notify_config: read by each loop at
        most once a minute (`refresh`), and otherwise the last reading, so an alert never waits on the read. An
        integration without it (older than notifications) or unable to read its store: (0, 3.0), so every push
        goes to the notify_service option exactly as before and CS-209 counts 3 hours."""
        now = time.monotonic()
        cached = getattr(self, "_notify_cfg", None)
        if cached is not None and (not refresh or 0 <= now - cached[0] < NOTIFY_CONFIG_S):
            return cached[1]
        attrs = ha_get(NOTIFY_CONFIG)[1]
        attrs = attrs if isinstance(attrs, dict) else {}
        try:
            recipients = max(0, int(attrs.get("recipients") or 0))
        except (TypeError, ValueError):
            recipients = 0
        try:
            idle = float(attrs.get("idle_hours"))
        except (TypeError, ValueError):
            idle = IDLE_HOURS
        idle = min(IDLE_HOURS_RANGE[1], max(IDLE_HOURS_RANGE[0], idle)) if math.isfinite(idle) else IDLE_HOURS
        self._notify_cfg = (now, (recipients, idle))
        return recipients, idle

    def _notify_event(self, event, room, zone, *detail):
        """A phase change ("phase": was, to, why) or a setting Jev moved ("jev_setpoint": words, why): not an
        alert, so no card, and pushed only through crop_steering.notify, never to the notify_service option
        (docs/NOTIFICATIONS.md). Queued, and sent once the loop's shots are done (_send_events), so a slow Home
        Assistant never holds one up."""
        self.__dict__.setdefault("_events", []).append((event, room, zone, detail))

    def _send_events(self):
        """The events queued this loop, to the phones that ask for them, when any phone is set up at all: one push
        per room and kind (lights-off moves every zone at once), within EVENTS_BUDGET_S for the lot. One that
        fails, or is left when the time is up, is logged and dropped: an event is never worth a retry, nor a push
        to notify_service."""
        events = self.__dict__.pop("_events", None) or []
        if not events or not self._notify_config()[0]:
            return
        grouped = {}
        for event, room, zone, detail in events:
            grouped.setdefault((event, room.slug), (event, room, []))[2].append((zone, detail))
        deadline = time.monotonic() + EVENTS_BUDGET_S
        for event, room, items in grouped.values():
            left = deadline - time.monotonic()
            if left <= 0:
                log("notify: no time left this loop, not sent:", event, room.slug, len(items))
                continue
            try:
                zone = items[0][0] if len(items) == 1 else None
                title, message = self._event_text(event, room, items)
                key = f"{event}_{room.slug}" + (f"_z{zone}" if zone is not None else "")
                self._route(key, None, event, room, zone, title, message, timeout=min(NOTIFY_TIMEOUT_S, left))
            except Exception as e:
                log("notify: event not sent", event, room.slug, e)

    def _event_text(self, event, room, items):
        """A room's events of one kind this loop as one push -> (title, message): one zone's in its own words, or
        a line for each ("Zone 1: P2 → P3, lights-off -> P3")."""
        moves = []
        for zone, detail in items:
            if event == "phase":
                was, to, why = detail
                moves.append((zone, f"{was} → {to}", why))
            else:
                words, why = detail
                moves.append((zone, f"Jev changed {words}", why))
        if len(moves) == 1:
            zone, head, why = moves[0]
            return f"{self._where(room, zone)}: {head}", why or head
        what = "phase changes" if event == "phase" else "settings Jev changed"
        name = self._where(room)
        title = f"{name}: {what}" if name else what[:1].upper() + what[1:]
        return title, "\n".join(
            f"{self._zone_title(room, zone)}: {head}" + (f", {why}" if why else "") for zone, head, why in moves
        )

    # ---------- CS-310: moisture rising with no water ----------
    def _watch_backup(self, room, zone, snap, now):
        """CS-310 (docs/error-codes.json) -> whether the zone is held as backed up. Its moisture rose by
        BACKUP_RISE_PTS within BACKUP_WINDOW_MIN while its valve, opened by the controller or by hand, stayed shut
        for that time and the BACKUP_GRACE_MIN before it: water coming up from below, a table that isn't draining.
        The readings compared start only BACKUP_GRACE_MIN after the zone's last water and after the controller
        started (a valve opened before a restart is not known). Held until the reading has not risen for
        BACKUP_CLEAR_MIN, then the card goes. A room that drains freely is not watched, and a card it had goes."""
        free = ha_get(f"select.crop_steering_{room.prefix}drainage")[0] == "free_drain"
        valve = room.hw["valves"].get(zone)
        last = room.__dict__.setdefault("_last_water", {})
        if valve and hw_get(valve)[0] == "on":
            last[zone] = now
        shot = room.state[zone].get("last_shot")
        wet = max((t for t in (last.get(zone), shot if isinstance(shot, datetime) else None) if t), default=None)
        start = max(now - timedelta(minutes=BACKUP_WINDOW_MIN), self._start + timedelta(minutes=BACKUP_GRACE_MIN))
        if wet is not None:
            start = max(start, wet + timedelta(minutes=BACKUP_GRACE_MIN))
        track = room.__dict__.setdefault("_vwc_track", {}).setdefault(zone, [])
        track.append((now, snap.vwc))
        track[:] = [(t, v) for t, v in track if t >= start]
        recent = sorted(v for t, v in track if t > now - timedelta(minutes=5))
        low = min((v for _, v in track), default=None)
        rising = (not free and len(track) >= 3 and (now - track[0][0]).total_seconds() >= 20 * 60
                  and recent[len(recent) // 2] - low >= BACKUP_RISE_PTS)
        held = room.__dict__.setdefault("_backed_up", {})
        key = f"backup_{room.slug}_z{zone}"
        if rising:
            held[zone] = now
            since = f"since {wet:%H:%M}" if wet else "since before the controller started"
            self._alert(
                key,
                "CS-310",
                "moisture rising with no water: the table is not draining",
                f"Moisture went from {low:.1f} to {recent[len(recent) // 2]:.1f} % in the last "
                f"{(now - track[0][0]).total_seconds() / 60:.0f} minutes, but this zone has had no water {since}. "
                "Water is coming up from below: the table, its drain or the sump is backed up and the slabs are "
                "sitting in runoff. Check the table, its drains and the sump pump now. The zone's daily minimum is "
                "held until the reading stops rising.",
                room=room,
                zone=zone,
            )
        elif zone in held and (free or now - held[zone] >= timedelta(minutes=BACKUP_CLEAR_MIN)):
            del held[zone]
            ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}")
            self._alerted.pop(key, None)
            self._alert_codes.pop(key, None)
        return zone in held

    def _watch_sump(self, room, now):
        """CS-311 (docs/error-codes.json): the sump pump this room's tables drain to (option sump_power_sensor) has
        drawn no power for sump_silent_h while the room is on: no reading above the room's Sump Pump Run Threshold
        (SUMP_RUN_W when it has none, or it can't be read). Read from Home Assistant's history every SUMP_CHECK_MIN
        (a run lasts about a minute); no evidence either way says nothing. The card goes at its next run."""
        entity = self.sump_sensors.get(room.slug) or self.sump_sensors.get("*")
        checked = getattr(room, "_sump_checked", None)
        if not entity or (checked is not None and now - checked < timedelta(minutes=SUMP_CHECK_MIN)):
            return
        room._sump_checked = now
        rows = self._device_history(
            entity, "power", datetime.now(timezone.utc) - timedelta(hours=self.sump_silent_h))
        if rows is None:
            return
        run_w = self._num(f"number.crop_steering_{room.prefix}sump_power_threshold_w", SUMP_RUN_W)
        ran = any(watts > run_w for watts, _changed in rows)
        key = f"sump_{room.slug}"
        if ran:
            if key in self._alerted:
                ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}")
                self._alerted.pop(key, None)
                self._alert_codes.pop(key, None)
            return
        self._alert(
            key,
            "CS-311",
            "the sump pump has not run",
            f"The sump pump this room drains to has drawn no power for {self.sump_silent_h:g} hours, though it "
            "normally runs every hour or two while the room is watered. Runoff has nowhere to go: the sump fills and "
            "backs up into the tables, and the slabs end up sitting in it (CS-310 follows once a zone's moisture "
            "rises with no water). Check the sump pump now: its power, its float and that it pumps out, or its "
            f"plug if the reading is unavailable.\n\nSensor: {entity}",
            room=room,
        )

    # ---------- CS-209: no watering for a while ----------
    def _watch_idle(self, room, now, lights_on, pub):
        """CS-209 (docs/NOTIFICATIONS.md): the room is on, its lights are on and a zone is in P1 or P2, and no zone
        has had a shot for idle_hours. The clock starts when that holds and again at every shot in the room; the
        card comes at idle_hours and again each idle_hours after while it lasts, and goes at the next shot, or
        once lights-off or P0 and P3 end it. A room that is off never reaches here (_loop_room)."""
        if not (lights_on and any(room.state[z].get("phase") in ("P1", "P2") for z in room.zones)):
            self._idle_reset(room, now)
            return
        began = getattr(room, "_idle_began", None)
        if began is None:
            began = room._idle_began = self._idle_start(room, now)
        shots = [room.state[z].get("last_shot") for z in room.zones if not room.state[z].get("last_shot_is_anchor")]
        start = max([began, *(shot for shot in shots if isinstance(shot, datetime))])
        if start != getattr(room, "_idle_from", None):  # the clock started, or a shot restarted it
            room._idle_from, room._idle_raised = start, 0
            self._idle_dismiss(room)
        hours = self._notify_config()[1]
        idle = (now - start).total_seconds() / 3600.0
        due = int(idle // hours)
        if due > getattr(room, "_idle_raised", 0) and self._alert(
            f"idle_{room.slug}",
            "CS-209",
            "no watering for a while",
            f"Nothing in this room has been watered for {idle:.1f} hours while its lights were on and a zone "
            f"was in P1 or P2. {self._idle_why(room, pub)} This is said again every "
            f"{'hour' if hours == 1 else f'{hours:g} hours'} while it lasts, and clears itself at the next shot.",
            room=room,
            quiet=False,
        ):
            room._idle_raised, room._idle_card = due, True

    def _idle_start(self, room, now):
        """When the room's CS-209 clock began, as far as can be told: after the last loop that saw it not running
        (lights off, no zone in P1 or P2, the room off), after today's lights-on and after the first zone now in P1
        or P2 moved there. After a restart that is what the saved state says, so a restart does not reset it; a
        zone now in P2 ramped in P1 before that, so it is never earlier than the truth."""
        lights_on = datetime.combine(self._grow_day_start(room, now), datetime.min.time())
        moved = [room.state[z].get("last_phase_change") for z in room.zones
                 if room.state[z].get("phase") in ("P1", "P2")]
        moved = [when for when in moved if isinstance(when, datetime)]
        times = [lights_on + timedelta(hours=room.lights_on_hour), getattr(room, "_idle_off", None),
                 min(moved) if moved else None]
        return min(now, max(t for t in times if t is not None))

    def _idle_reset(self, room, now):
        """CS-209's clock is not running: it may start only after now, and its card goes."""
        room._idle_began, room._idle_from, room._idle_off = None, None, now
        self._idle_dismiss(room)

    def _idle_dismiss(self, room):
        """Take CS-209's card down when one may be up: after this controller raised it, and once after a start,
        whatever the last run left."""
        if getattr(room, "_idle_card", None) is False:
            return
        key = f"idle_{room.slug}"
        if ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}"):
            room._idle_card = False
        self._alerted.pop(key, None)
        self._alert_codes.pop(key, None)

    def _idle_why(self, room, pub):
        """Why nothing has been watered, as far as this pass can tell: watering switched off, a hold (_blocked), or
        nothing called for water."""
        if not self._on(room_gate(room), False):
            return f"Watering is switched off in this room: its engine switch ({room_gate(room)}) is off."
        holds = []
        for zone in sorted(room.zones):
            if room.state[zone].get("phase") in ("P1", "P2"):
                hold = (pub.get(zone) or {}).get("block") or self._blocked(room, zone)
                if hold:
                    holds.append(f"{self._zone_title(room, zone)}: {hold}")
        if holds:
            return f"Watering is held. {'; '.join(holds)}."
        return ("Nothing called for water: no zone in P1 or P2 dried to the point where the engine waters it. If "
                "the plants are drinking, check the probes and each zone's re-water point.")

    def _dosing_alert(self, room, code, title, message, event=None, quiet=False):
        """An alert the dosing runner raised (docs/DOSING.md) -> True once Home Assistant has it (the
        runner keeps it until then). Only these codes exist, each written out here so the error-code
        list sees it; `room` is None for a room no longer set up, or for dosing as a whole. Each
        event (a dose, a batch, a restart) has its own notification: a second one within 30 minutes
        is never swallowed by the first. The runner paces an event's repeats itself (and a repeat
        replaces its card), so `_alert`'s quiet period is only for a condition re-checked every loop."""
        key = f"dosing_{getattr(room, 'slug', 'gone')}_{code[3:]}" + (f"_{event}" if event else "")
        if code == "CS-801":
            return self._alert(key, "CS-801", title, message, room=room, quiet=quiet)
        if code == "CS-802":
            return self._alert(key, "CS-802", title, message, room=room, quiet=quiet)
        if code == "CS-803":
            return self._alert(key, "CS-803", title, message, room=room, quiet=quiet)
        if code == "CS-804":
            return self._alert(key, "CS-804", title, message, room=room, quiet=quiet)
        if code == "CS-805":
            return self._alert(key, "CS-805", title, message, room=room, quiet=quiet)
        if code == "CS-806":
            return self._alert(key, "CS-806", title, message, room=room, quiet=quiet)
        if code == "CS-807":
            return self._alert(key, "CS-807", title, message, room=room, quiet=quiet)
        log("dosing alert refused: not in the error-code list", code)
        return True  # never deliverable: not kept

    def _dosing_hold(self, room):
        """Why dosing holds this room's watering ("making a batch", or "dosing hardware still on: ..."
        while something a dose or batch left does not read off), else None."""
        return self.dosing.holds(room) if self.dosing is not None else None

    def _watch_dosing(self):
        """The dosing thread is never gone unnoticed (dosing_runner.health): dead, it is started again,
        its records recovered as after a restart, and CS-806 says so; stalled, CS-806 says that."""
        dosing = self.dosing
        if dosing is None:
            return
        try:
            health = dosing.health()
            if health == "dead":
                log("dosing: the dosing thread has stopped: starting it again")
                dosing.restart()
            elif health == "stalled":
                self._dosing_alert(
                    None, "CS-806", "dosing has stopped answering",
                    "The controller's dosing thread has not gone round for more than 10 minutes, so "
                    "dosing requests are not being taken. Anything it holds stays held. Restart the "
                    "controller app if it does not recover; check the tank if a dose or batch was "
                    "running.", "stalled", quiet=True)  # checked every loop: once per 30 min
        except Exception as e:
            log("dosing: could not check the dosing thread:", e)

    def _shot_running(self, slugs):
        """Whether a shot is in flight in one of these rooms, read under the lock a shot starts under,
        so a batch that has just held them never misses one starting."""
        with self._shot_lock:
            room = getattr(self, "_shot_room", None) if getattr(self, "_busy", False) else None
        return room is not None and room.slug in slugs

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
        elif code == "CS-710":
            self._alert(key, "CS-710", title, message, room=room, zone=zone)
        else:
            log("jev alert refused: not in the error-code list", judge, code)

    @staticmethod
    def _jev_read(entity):
        """One entity's state for Jev's context (the room's flower start date)."""
        return ha_get(entity)[0]

    def _unreadable(self, entity, max_age_min=20):
        """Why `_read_sensor` found no usable moisture reading at `entity`, as (code, sentence).
        The same tests in the same order, on one more read of the entity."""
        lo, hi = UNITS["vwc"]["plausible"]
        value, v, unit, lu, taken, attrs = self._device(entity, "vwc")
        if v is None:
            return "CS-102", "This zone's moisture sensor can't be found in Home Assistant, so the controller has no reading to steer by."
        # The integration's zone reading names the probes it set aside for their unit (unit_set_aside).
        aside = (attrs or {}).get("unit_set_aside")
        if v in ("unknown", "unavailable", "") and isinstance(aside, dict) and aside:
            probes = ", ".join(f"{probe} (in '{unit or 'no unit'}')" for probe, unit in aside.items())
            return "CS-503", (
                f"This zone's moisture probe {probes} reports in a unit the controller can't take as a moisture "
                "percentage, so the probe is set aside and the zone has no reading to steer by."
            )
        if v in ("unknown", "unavailable", ""):
            return "CS-102", f"This zone's moisture sensor reads '{v or 'empty'}', so the controller has no reading to steer by."
        try:
            float(v)
        except (TypeError, ValueError):
            return "CS-102", f"This zone's moisture sensor reads '{v}', which isn't a number, so the controller has no reading to steer by."
        if taken == "refused" or (taken == "implausible" and str(unit or "").strip()):
            return "CS-503", (
                f"This zone's moisture sensor reads {v} in '{unit}', which the controller can't take as a "
                "moisture percentage, so it sets the probe aside."
            )
        if value is None or value < lo or value > hi:
            return "CS-103", f"This zone's moisture sensor reads {v}, which can't be a moisture reading ({lo:g}–{hi:g}%), so the controller ignores it."
        f = value
        try:
            ts = datetime.fromisoformat(str(lu).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
        except (ValueError, TypeError, OverflowError):
            ts = age_min = None
        if age_min is not None and age_min > max_age_min:
            age = f"{age_min:.0f} minutes" if age_min < 120 else f"{age_min / 60:.1f} hours"
            return "CS-101", (
                f"This zone's moisture reading has stayed at {f:g}% for {age}, so the controller "
                "can't tell a working probe from one that has stopped or been pulled out."
            )
        if age_min is not None and age_min < -1.0:  # _read_sensor: age < -60 s
            return "CS-102", (
                f"This zone's moisture reading is stamped {-age_min:.0f} minutes in the future, so "
                "the controller can't trust it: Home Assistant's clock and this app's clock disagree."
            )
        if age_min is None:
            return "CS-102", "This zone's moisture sensor has no valid time for its last reading, so the controller has no reading to steer by."
        return "CS-102", "This zone's moisture sensor had no usable reading a moment ago, so the controller had nothing to steer by."

    def _water_usage(self, room, zone, now):
        """Recorded controller delivery over this grow-day and the previous six.

        Buckets follow room lights-on, independently of phase/reset timing. Old counters
        are never reset here. Import only a dated, current grow-day counter; unknown
        legacy volume stays in daily_vol and is explicitly excluded from this window.
        Missing grow-days remain missing (not invented zeroes). The first observed day
        is partial; subsequent consecutive grow-days have full controller coverage.
        """
        st = room.state[zone]
        today = self._grow_day_start(room, now)
        cutoff = today - timedelta(days=6)
        history = st.get("water_history")
        changed = False
        if history is None:
            legacy = float(st.get("daily_vol") or 0.0)
            legacy = legacy if math.isfinite(legacy) and legacy >= 0 else 0.0
            dated = st.get("last_daily_reset") == today
            history = [{"grow_day": today.isoformat(), "litres": legacy if dated else 0.0,
                        "complete": False}]
            st["water_history_legacy_excluded_l"] = 0.0 if dated else legacy
            changed = True
        history = [item for item in history if cutoff.isoformat() <= item["grow_day"] <= today.isoformat()]
        if history != st.get("water_history"):
            changed = True
        current = next((item for item in history if item["grow_day"] == today.isoformat()), None)
        if current is None:
            consecutive = any(item["grow_day"] == (today - timedelta(days=1)).isoformat()
                              for item in history)
            current = {"grow_day": today.isoformat(), "litres": 0.0, "complete": consecutive}
            history.append(current)
            changed = True
        st["water_history"] = history[-7:]
        if changed:
            self._save_state()
        complete_days = sum(item["complete"] for item in history)
        attrs = {
            "window_start_grow_day": cutoff.isoformat(),
            "window_end_grow_day": today.isoformat(),
            "observed_grow_days": len(history),
            "complete_grow_days": complete_days,
            "history_complete": complete_days == 7,
            "coverage": "complete" if complete_days == 7 else "partial_history",
            "legacy_volume_excluded_l": st.get("water_history_legacy_excluded_l", 0.0),
            "measurement": "estimated controller delivery; current grow-day to date",
        }
        return round(sum(item["litres"] for item in history), 2), attrs

    def _advance_shot_counters(self, room, zone, size_pct, *, delivered_l=None, steering=True):
        """A delivered shot's water, counted. A test shot (steering False) is water like any other, but
        not one of the day's shots: it is not a ramp shot, and nothing learns from it."""
        st = room.state[zone]
        now = datetime.now()
        self._water_usage(room, zone, now)
        if delivered_l is None:
            delivered_l = size_pct / 100.0 * self._substrate_l(room, zone)
        day = self._grow_day_start(room, now).isoformat()
        for item in st["water_history"]:
            if item["grow_day"] == day:
                item["litres"] += delivered_l
                break
        if steering:
            if not isinstance(st.get("learn"), dict):
                st["learn"] = auto_setpoints.fresh()
            auto_setpoints.shot(st["learn"], st.get("phase"), size_pct, st.get("last_vwc"), now.timestamp())
            first = st.get("phase") == "P1" and st["shots"] == 0
            try:  # the day's first shot closes the night: the VWC it started from is what the zone landed on
                record = zone_history.shot(st, vwc_before=st.get("last_vwc"), now=now, day=day, first=first)
                if record is not None:
                    words = zone_history.night_words(record)
                    tag = "" if room.prefix == "" else f"{room.slug} "
                    self._activity.insert(0, f"{now.strftime('%H:%M')} {tag}Z{zone} {words}"[:120])
                    log(f"[{room.slug}] Z{zone} {words}")
            except Exception as e:  # a record is never worth a delivered shot the counters miss
                log("zone history error", room.slug, zone, e)
            if st.get("phase") == "P1":  # the P1 rule (core.decide): did this shot raise the peak?
                st["p1_peak_before"] = st.get("peak")
                st["p1_settled_before"] = self._settled_vwc(st)
                gain = st["learn"].get("gain")
                st["p1_expected_rise"] = round(gain * size_pct, 2) if gain and size_pct > 0 else None
                if st.get("p1_reached"):
                    st["p1_extra"] = int(st.get("p1_extra") or 0) + 1
            st["shots"] += 1
        st["last_shot"] = now
        st["last_shot_is_anchor"] = False  # water was delivered: this one is an irrigation
        st["daily_vol"] += delivered_l
        self._save_state()
        if getattr(self, "jev", None) is not None:
            try:  # the shot, for Jev's Shot and Probe judges to read its answer later
                jev_bridge.shot_counted(room, zone, delivered_l)
            except Exception as e:
                log("jev shot record error", room.slug, zone, e)

    def _record_phase(self, room, zone, st, was, new, now, how):
        """Keep the zone's history on a phase change by anyone (the engine, a Jev judge, the operator's Set Phase):
        P1 handing over to P2 is the day's plateau. A history error never stops the phase change."""
        if new == "P1":  # the P1 rule (core.decide) starts again
            st["p1_reached"], st["p1_peak_before"], st["p1_extra"] = False, None, 0
            st["p1_settled_before"], st["p1_expected_rise"] = None, None
        try:
            entry = zone_history.phase_changed(st, was, new, day=self._grow_day_start(room, now).isoformat(), how=how)
            if entry is not None:
                log(f"[{room.slug}] Z{zone} plateau {entry['value']:.2f} after {entry['shots']} shots: {entry['how']}")
        except Exception as e:
            log("zone history error", room.slug, zone, e)

    # ---------- hardware (sync; this process does one thing) ----------
    @staticmethod
    def _hardware_entities(room):
        return {
            e
            for e in (
                room.hw.get("pump"),
                room.hw.get("mainline"),
                *room.hw.get("valves", {}).values(),
            )
            if e
        }

    @staticmethod
    def _undrivable(room, zone):
        """This zone's valve and the room's main line and pump that have no row in ACTUATORS. Setup refuses
        them; one mapped by hand holds its zone (CS-313) and is never sent a command."""
        hw = room.hw
        return [e for e in (hw.get("pump"), hw.get("mainline"), hw["valves"].get(zone))
                if e and e.split(".", 1)[0] not in ACTUATORS]

    @staticmethod
    def _fault_record(fault, fallback_entities=()):
        entities = fault.get("entities") if isinstance(fault, dict) else None
        # Which switches did not read OFF, and how: a fault saved by an older controller has none.
        switches = fault.get("switches") if isinstance(fault, dict) else None
        return {
            "switches": [
                s
                for s in (switches if isinstance(switches, list) else [])
                if isinstance(s, dict) and isinstance(s.get("problem"), str)
            ],
            "reason": (
                str(fault.get("reason", "unconfirmed hardware close"))
                if isinstance(fault, dict)
                else "unconfirmed hardware close"
            ),
            "entities": (
                entities
                if isinstance(entities, list)
                and entities
                and all(isinstance(e, str) and e for e in entities)
                else sorted(fallback_entities)
            ),
        }

    @staticmethod
    def _fault_words(fault):
        """What a hardware fault was, in words: where, then each switch that did not read OFF and
        how ("zone 1 shot end: Pump (switch.pump) still read ON 16 s after it was switched off")."""
        told = []
        for s in fault.get("switches") or []:
            what = CLOSE_FAILURES.get(s["problem"], f"read \"{s.get('state')}\" instead of OFF")
            entity = s.get("entity_id")
            if not entity:
                told.append(f"a pump or valve {what}")
                continue
            name = s.get("name")
            told.append(f"{name} ({entity}) {what}" if name and name != entity else f"{entity} {what}")
        return f"{fault['reason']}: {'; '.join(told)}" if told else fault["reason"]

    def _hardware_fault_block(self, room):
        entities = self._hardware_entities(room)
        for owner in self.rooms:
            fault = owner.hardware_fault
            if fault and (owner is room or entities.intersection(fault["entities"])):
                if owner is room:
                    return f"hardware fault (CS-301): {self._fault_words(fault)}"
                return (
                    f"hardware fault in {self._where(owner) or owner.slug} (CS-301), which shares "
                    f"this hardware: {self._fault_words(fault)}"
                )
        discovered = {r.slug for r in self.rooms}
        for slug, block in getattr(self, "_saved_room_blocks", {}).items():
            if (
                slug in discovered
                or not isinstance(block, dict)
                or "_hardware_fault" not in block
            ):
                continue
            fault = self._fault_record(block["_hardware_fault"])
            # If orphan metadata is damaged there is no safe hardware mapping to
            # infer: hold until its owner returns and can be verified explicitly.
            if not fault["entities"] or entities.intersection(fault["entities"]):
                return (
                    f"hardware fault in undiscovered room {slug}: {fault['reason']}; "
                    "restore the room descriptor before verified disarm/recovery"
                )
        return None

    def _hardware_fault_short(self, room):
        """A hardware fault holding this room, as each zone's status says it: briefly, with its code
        ("hardware fault (CS-301)"); the room's alert and notification name the switch. None when
        there is none."""
        block = self._hardware_fault_block(room)
        return block.split(":", 1)[0] if block else None

    def _latch_hardware_fault(self, room, reason, switches=None):
        room.hardware_fault = {
            "reason": reason,
            "entities": sorted(self._hardware_entities(room)),
            "switches": list(switches or []),
        }
        saved = self._save_state()
        self._alert_hardware_fault(room, saved)

    def _alert_hardware_fault(self, room, saved=True):
        self._alert(
            f"hardware_fault_{room.slug}",
            "CS-301",
            "CRITICAL hardware fault, watering stopped",
            f"{self._fault_words(room.hardware_fault)}.\n\nA pump or valve did not confirm it had "
            "switched OFF, so watering is stopped on this hardware and in every room that shares "
            f"it. Switch watering off ({room_gate(room)}) in each of those rooms, then check that "
            "switch at the device and in Home Assistant. The hold clears by itself within a minute "
            "once every pump and valve reads OFF; then switch watering back on."
            + (
                ""
                if saved
                else " THE FAULT COULD NOT BE SAVED: do not restart the controller before it is repaired."
            ),
            room=room,
        )

    def _recover_hardware_faults(self):
        for room in self.rooms:
            fault = room.hardware_fault
            if not fault:
                continue
            entities = set(fault["entities"])
            affected = [
                r
                for r in self.rooms
                if r is room or entities.intersection(self._hardware_entities(r))
            ]
            if not all(ha_get(room_gate(r))[0] == "off" for r in affected):
                continue
            for affected_room in affected:
                entities.update(self._hardware_entities(affected_room))
            if not entities or not all(hw_get(e)[0] == "off" for e in entities):
                continue
            room.hardware_fault = None
            # an interrupted shot's record is settled too: every switch it could name reads OFF
            inflight, room.shot_inflight = getattr(room, "shot_inflight", None), None
            if not self._save_state():
                room.hardware_fault = fault  # clearing must also survive a restart
                room.shot_inflight = inflight
                continue
            log(
                f"[{room.slug}] hardware hold (CS-301) cleared: watering is off and every pump and valve "
                "reads OFF; switch watering back on to resume"
            )
            # The next hold is a new fault: announce it, don't take it for this one still quiet.
            self._alerted.pop(f"hardware_fault_{room.slug}", None)
        for room in self.rooms:
            if room.hardware_fault and f"hardware_fault_{room.slug}" not in self._alerted:
                # A hold latched while Home Assistant was unreachable (a failed close, typically) was never
                # announced, and one found at start-up is announced once: say it until HA has it.
                self._alert_hardware_fault(room)

    @staticmethod
    def _inflight_record(saved):
        """A saved write-ahead shot record (see _execute_shot), or None when absent or unusable."""
        if not isinstance(saved, dict):
            return None
        entities = {key: saved.get(key) for key in ("valve", "mainline", "pump")}
        if (
            type(saved.get("zone")) is not int
            or not isinstance(saved.get("started"), str)
            or not any(entities.values())
            or not all(v is None or (isinstance(v, str) and v) for v in entities.values())
        ):
            return None
        return {"zone": saved["zone"], **entities, "started": saved["started"]}

    def _reconcile_inflight(self):
        """Top of every loop, so also at start-up: settle any shot whose close was never confirmed."""
        for room in self.rooms:
            record = getattr(room, "shot_inflight", None)
            if record and not self._busy:
                try:
                    self._reconcile_room_inflight(room, record)
                except Exception as e:  # the recovery path must never stop the loop
                    log("interrupted-shot check failed", room.slug, e)

    def _reconcile_room_inflight(self, room, rec):
        """Close what an interrupted shot opened, and nothing else.

        The record names the valve, main line and pump the shot opened, and when (_execute_shot writes it
        before opening anything). People run this hardware by hand: the tank is circulated for well over
        20 minutes to heat it, and zones are hand-watered with the valves and main line open. So:
          * nothing is touched while the room's kill switch is not ON: the operator has taken over;
          * a switch is closed only if it has been ON since this shot opened it (Home Assistant's
            last_changed inside INFLIGHT_OPEN_WINDOW_S of the record's start, or, when a Home Assistant
            restart or the switch reconnecting has moved last_changed, its recorded history ON since
            then). One a person has switched since, or that was already on, is theirs: it is left
            alone, and so is everything upstream of it (valve -> main line -> pump), and the record is
            closed;
          * the main line and pump are left alone while another valve on the same line is open, and the
            pump while any hold (dosing, fill, flush, circulation) is on;
          * manifold, circulation and tank-fill relays are never touched: the record only names the
            room's mapped valve, main line and pump.
        """
        zone = rec["zone"]
        tag = f"[{room.slug}] Z{zone} interrupted shot (started {rec['started']})"
        order = [e for e in (rec.get("valve"), rec.get("mainline"), rec.get("pump")) if e]
        reads = {e: hw_get(e) for e in order}
        if all(read[0] == "off" for read in reads.values()):
            self._clear_inflight(room, f"{tag}: its valve/main line/pump read OFF - record closed")
            return
        flag = ha_get(room_gate(room))[0]
        if flag is None:
            return  # Home Assistant unreachable: nothing can be read or closed; try again next loop
        if flag != "on":
            if not getattr(room, "_inflight_waiting_logged", False):
                still_on = ", ".join(e for e in order if reads[e][0] != "off")
                log(f"{tag}: kill switch {room_gate(room)} is {flag}, so the operator has it - "
                    f"leaving {still_on} alone")
                room._inflight_waiting_logged = True
            return
        close, left, unsure, why = self._inflight_plan(room, rec, reads)
        if close:
            failures = self._switch_off_failures(close)
            if failures:
                if not room.hardware_fault:
                    self._latch_hardware_fault(room, f"zone {zone} interrupted shot", failures)
                self._alert(
                    f"inflight_{room.slug}",
                    "CS-308",
                    "CRITICAL, an interrupted shot's hardware is still ON",
                    f"A shot that started {rec['started']} never finished cleanly (the controller "
                    "stopped or lost Home Assistant part-way through, or a switch did not confirm OFF "
                    "at the end of it). What it opened was switched off and still does not read OFF, "
                    "so water may still be running. The controller tries again every "
                    f"loop.\n\nStill ON: {', '.join(close)}",
                    room=room,
                    zone=zone,
                )
                return
            log(f"{tag}: switched off {', '.join(close)} (ON since the shot opened them)")
        if unsure:
            self._alert(
                f"inflight_{room.slug}",
                "CS-309",
                "an interrupted shot's hardware may still be ON",
                f"A shot that started {rec['started']} never finished, and what it opened can't be "
                "read (or Home Assistant gives no time for its last change, or no history since the "
                "shot began), so the controller can't tell whether a person has switched it since. It leaves it alone and checks "
                "again every loop. Check it now and switch it off by hand if water is running: once "
                "it can be read, the controller switches off only what it can prove this shot "
                "opened, and leaves anything else on for you to deal with."
                f"\n\nCan't be read: {', '.join(unsure)}",
                room=room,
                zone=zone,
            )
            return
        if left:
            self._clear_inflight(room, f"{tag}: left {', '.join(left)} alone ({why}) - record closed")
            return
        self._clear_inflight(room, f"{tag}: closed and read back OFF - record closed")

    def _inflight_plan(self, room, rec, reads, deadline=None):
        """Which of a recorded shot's switches are provably its own -> (close, left, unsure, why).

        Walks valve -> main line -> pump. A switch is the shot's own while it has been ON since the shot
        opened it (last_changed inside INFLIGHT_OPEN_WINDOW_S of the record's start; when last_changed is
        outside it, the switch's recorded history decides, because a Home Assistant restart or a
        reconnect moves last_changed too). The walk stops at the first switch that is not: one a person
        switched since, or that was on before, is theirs (`left`, with everything upstream of it), and so
        are the main line and pump while another valve on the line is open, and the pump while a hold is
        on. One that cannot be read, has no change time, or has no readable history stops it too
        (`unsure`): whose it is cannot be told. Inside the stop's `deadline` (a _Stop), so does a read
        it needed that was not made in time or not answered (a hold or another valve it could not read
        may be on); each read keeps time for the offs of what it would prove and of what is proven."""
        order = [e for e in (rec.get("valve"), rec.get("mainline"), rec.get("pump")) if e]
        started = _aware(rec.get("started"))
        lo, hi = INFLIGHT_OPEN_WINDOW_S
        close, line_in_use = [], None
        for i, ent in enumerate(order):
            read = reads[ent]
            if read[0] == "off":
                continue
            changed = _aware(getattr(read, "last_changed", None))
            if read[0] != "on" or changed is None or started is None:
                return close, [], order[i:], ""
            part = None if deadline is None else deadline.keeping(len(close) + 1)
            if not lo <= (changed - started).total_seconds() <= hi:
                # A Home Assistant restart or the switch reconnecting also moves last_changed: ask the
                # recorder whether anyone switched it since the shot opened it.
                own = _on_since_shot(_history(ent, started + timedelta(seconds=lo), part), started)
                if own is None:
                    return close, [], order[i:], ""
                if not own:
                    return close, order[i:], [], f"{ent} changed at {changed.isoformat()}, not when the shot opened it"
            if ent != rec.get("valve"):
                if line_in_use is None:
                    line_in_use = self._line_in_use(room, rec, part)
                    if line_in_use is None:
                        return close, [], order[i:], ""
                if line_in_use:
                    return close, order[i:], [], "another valve on this line is open"
            if ent == rec.get("pump"):
                hold = self._hold_on(part)
                if hold is None:
                    return close, [], order[i:], ""
                if hold:
                    return close, order[i:], [], "a hold (dosing / fill / flush / circulation) is on"
            close.append(ent)
        return close, [], [], ""

    def _hold_on(self, deadline=None):
        """A hold (hold_entities) is on. Inside the stop's `deadline` (a _Stop), None when one was not read
        in time or not answered and none read is on: it may be on."""
        if deadline is None:
            return any(self._on(f, False) for f in self.hold_entities)
        unread = False
        for entity in self.hold_entities:
            v = _read(entity, deadline)[0]
            if v is None:
                unread = True
            elif v not in ("unknown", "unavailable", "") and str(v).lower() in ON_STATES:
                return True
        return None if unread else False

    def _switch_off_failures(self, entities):
        """As _switch_off_confirmed, saying which did not read back OFF and how (_close_failures):
        empty when every one did."""
        refused = []
        for index, entity in enumerate(entities):
            if index == 1:
                time.sleep(1)
            if not hw_call(entity, False):
                refused.append(entity)
        if not refused and self._confirm_switches(entities, "off"):
            return []
        return self._close_failures(entities, refused)

    @staticmethod
    def _close_failures(entities, refused=()):
        """Each switch that did not read OFF after a close, and how (CLOSE_FAILURES): Home Assistant
        refused to switch it off, or it reads ON, unavailable, unknown or nothing. When every one
        reads OFF by now, one was late: the read-back gave up first, so the hold stands and says so."""
        failures = []
        for entity in entities:
            state, attributes = hw_get(entity)[:2]
            if entity not in refused and state == "off":
                continue
            problem = (
                "refused"
                if entity in refused
                else state
                if state in ("on", "unavailable", "unknown")
                else "unreadable"
                if state is None
                else "other"
            )
            record = {"entity_id": entity, "problem": problem}
            name = attributes.get("friendly_name") if isinstance(attributes, dict) else None
            if isinstance(name, str) and name.strip():
                record["name"] = name.strip()
            if problem == "other":
                record["state"] = state
            failures.append(record)
        return failures or [{"entity_id": None, "problem": "late"}]

    def _switch_off_confirmed(self, entities, deadline=None):
        """Switch these off, the valve first and then back up the line as after a normal shot, and
        report whether every one reads back OFF (inside the stop's `deadline`, a _Stop, when given)."""
        ok = _switch_off(entities[0], deadline, len(entities) - 1)
        if len(entities) > 1:
            _pause(1, deadline)
        for i, ent in enumerate(entities[1:], 2):
            ok = _switch_off(ent, deadline, len(entities) - i) and ok
        return ok and self._confirm_switches(entities, "off", deadline)

    def _line_in_use(self, room, rec, deadline=None):
        """Another valve fed by this shot's main line or pump is open: someone is watering through it.
        Inside the stop's `deadline` (a _Stop), None when one was not read in time or not answered and
        none read is open: it may be."""
        line = {rec.get("mainline"), rec.get("pump")} - {None}
        unread = False
        for other in self.rooms:
            if other is not room and not line & {other.hw.get("mainline"), other.hw.get("pump")}:
                continue
            for valve in other.hw.get("valves", {}).values():
                if not valve or valve == rec.get("valve"):
                    continue
                v = _read(valve, deadline)[0]
                if v == "on":
                    return True
                unread = unread or (deadline is not None and v is None)
        return None if unread else False

    def _clear_inflight(self, room, message):
        room.shot_inflight = None
        room._inflight_waiting_logged = False
        self._save_state()
        log(message)
        if self._alerted.pop(f"inflight_{room.slug}", None):
            ha_call("persistent_notification", "dismiss", notification_id=f"f2_inflight_{room.slug}")

    def _wait_shot(self, room, zone, duration_s, started=None):
        """Wait to a monotonic deadline, including HA latency and valve-open command time.

        Check kill/override, the holds and the shot's valve between <=2 s sleeps using bounded
        reads. This remains synchronous: other rooms wait and network/device delays can delay
        shutdown. Returns actual seconds elapsed and what ended the shot early, or None:
          ("abort", entity): a definitive kill OFF / room OFF / zone OFF / override ON. The
            operator's own switches are read first in every round, so they win.
          ("refused", None): Home Assistant refused this controller's token (_AuthGate, a container):
            the shot closes as after a kill-switch abort, with nothing sent but its own offs.
          ("external", entity): something else closed the feed path: a hold (hold_entities) reads
            ON (the test _blocked applies before a shot), or the shot's own valve reads OFF. The
            caller closes only what is still this shot's (_close_cut_short).
        An unreadable entity retains the existing in-flight policy: it ends nothing.
        """
        started = time.monotonic() if started is None else started
        deadline = started + duration_s
        step = 2.0
        valve = room.hw.get("valves", {}).get(zone)
        valve_seen_on = False
        while time.monotonic() < deadline:
            for entity, stop_state in (
                (room_gate(room), "off"),
                (f"switch.crop_steering_{room.prefix}room_active", "off"),
                (f"switch.crop_steering_{room.prefix}zone_{zone}_enabled", "off"),
                (
                    f"switch.crop_steering_{room.prefix}zone_{zone}_manual_override",
                    "on",
                ),
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if _GATE.state == "all":
                    return time.monotonic() - started, ("refused", None)
                # Account for network time, and never start an eight-second read when
                # less than that remains. HTTP/socket scheduling can still overshoot;
                # return measured time rather than pretending sleep time was delivery.
                state = ha_get(entity, timeout=min(step, remaining))[0]
                if state == stop_state:
                    return time.monotonic() - started, ("abort", entity)
            for entity in [e for e in (*self.hold_entities, valve) if e]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if _GATE.state == "all":
                    return time.monotonic() - started, ("refused", None)
                state = hw_get(entity, timeout=min(step, remaining))[0]
                if entity != valve:
                    ended = str(state).lower() in ON_STATES
                else:
                    # Right after turn_on Home Assistant can still show the valve's old OFF (a Zigbee
                    # plug reports its new state up to ~1.6 s late): only an OFF after it was seen ON
                    # is somebody closing it.
                    ended = state == "off" and valve_seen_on
                    valve_seen_on = valve_seen_on or state == "on"
                if ended:
                    return time.monotonic() - started, ("external", entity)
            self._keep_alive(deadline - time.monotonic())
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(step, remaining))
        return time.monotonic() - started, None

    def _close_cut_short(self, room, zone, by, elapsed, duration_s, valve_opened):
        """Close a shot that something else cut short (see _wait_shot) -> seconds its valve was open.

        The shot's valve and main line are its own: each is switched off unless it already reads OFF
        (a guard automation closed it first; it is not touched again). So is its pump, but never while
        a hold is ON: dosing, a fill, a flush or circulation owns the pump now, as in _inflight_plan.
        Only what this switches off is read back, so a feed path somebody else closed never latches a
        hardware hold. A switch of the shot's own that will not close still does, and the shot stays
        recorded for the reconciler.

        The seconds come from Home Assistant's last_changed for the valve when it reads OFF and that
        change falls between this shot opening it and the interruption being seen: it closed before
        the controller looked. Otherwise (still open, or no usable change time) they run to when the
        interruption was seen.
        """
        valve, mainline, pump = room.hw["valves"].get(zone), room.hw.get("mainline"), room.hw.get("pump")
        reads = {e: hw_get(e) for e in (valve, mainline, pump) if e}
        close = [e for e in (valve, mainline) if e and reads[e][0] != "off"]
        left = []
        if pump and reads[pump][0] != "off":
            (left if any(self._on(f, False) for f in self.hold_entities) else close).append(pump)
        failures = self._switch_off_failures(close) if close else []
        if failures:
            self._latch_hardware_fault(room, f"zone {zone} shot cut short", failures)
        else:
            room.shot_inflight = None  # as after a normal close: nothing of this shot's is left open
        changed = _aware(getattr(reads[valve], "last_changed", None)) if reads[valve][0] == "off" else None
        closed_after = (changed - valve_opened).total_seconds() if changed else None
        open_s = closed_after if closed_after is not None and 0 <= closed_after <= elapsed else elapsed
        what = (f"its valve {by} was switched OFF by something other than this controller" if by == valve
                else f"the hold {by} turned ON")
        outcome = " ".join(
            ([f"Switched off {', '.join(close)}."] if close else [])
            + ([f"Left {', '.join(left)} on: a hold owns it now."] if left else [])
        ) or "Nothing it had opened was still on."
        log(f"[{room.slug}] Z{zone} shot cut short after {open_s:.1f}/{duration_s:.0f}s: {what}. {outcome}")
        self._alert(
            f"cutshort_{room.slug}_z{zone}",
            "CS-307",
            "shot stopped early, something else closed the feed",
            f"The shot ended after {open_s:.0f} of {duration_s:.0f} seconds because {what}. Only "
            f"those {open_s:.0f} seconds of water are counted. {outcome}",
            room=room,
            zone=zone,
        )
        return open_s

    @staticmethod
    def _confirm_switches(entities, want, deadline=None):
        """True only when every switch reads back `want`.

        Zigbee/MQTT plugs accept a command at once but report the new state later
        (a pump's OFF report: usually under 1 s; 1.6 s on 15 Sep and about 10 s on 28 Sep 2026 on a
        live install). A read-back that gives up too early latches a false hardware hold; one that
        waits too long stalls every room (this loop is synchronous) before a real stuck-open is caught.
        On the way out (SIGTERM) it gives up when the stop's `deadline` (a _Stop) runs out.
        """

        def settled(window, first):
            end = time.monotonic() + window
            if deadline is not None:
                end = min(end, deadline.until)
            _pause(first, deadline)
            while True:
                if deadline is not None and deadline.timeout(8) is None:
                    return False  # no read-back fits in what is left of the stop
                if all(_read(ent, deadline)[0] == want for ent in entities):
                    return True
                if time.monotonic() >= end:
                    return False
                _pause(CONFIRM_POLL_S, deadline)

        # First read at 1 s, exactly as before, so a plug that reports promptly costs nothing extra.
        # A late report is then re-read every 0.5 s up to 6 s. The pump has already been commanded
        # OFF by the time this runs.
        if settled(CONFIRM_TIMEOUT_S, CONFIRM_FIRST_READ_S):
            return True
        if want != "off" or (deadline is not None and deadline.timeout(8) is None):
            return False
        # Whatever still does not read OFF is sent OFF again (a plug may have missed the first) and
        # read back for 10 s more: 16 s in all, still inside the minute's loop for a genuinely
        # stuck-open valve.
        for ent in entities:
            if _read(ent, deadline)[0] != "off":
                _switch_off(ent, deadline)
        return settled(CONFIRM_RETRY_S, CONFIRM_POLL_S)

    def _execute_shot(self, room, zone, duration_s, size_pct, *, flow_lps=None, plan_exempt=False, steering=True):
        if self._hardware_fault_block(room):
            return
        if _GATE.state is not None:
            log(f"[{room.slug}] Z{zone} shot held: Home Assistant refuses this controller's token")
            return
        if getattr(room, "shot_inflight", None):
            log(f"[{room.slug}] Z{zone} shot held: an interrupted shot's hardware is not accounted for yet")
            return
        plumbing = plumbing_hold(room.hw)
        if plumbing:  # never open a valve on a room whose declared pump is not there to run
            log(f"[{room.slug}] Z{zone} shot held: {plumbing}")
            return
        undrivable = self._undrivable(room, zone)
        if undrivable:  # never sent a command (_blocked raises CS-313 for it)
            log(f"[{room.slug}] Z{zone} shot held: {', '.join(undrivable)} can't be switched")
            return
        # A shot a plan hold never stops (PLAN_HOLD_EXEMPT) does not wait on the plan here either.
        strategy_hold = None if plan_exempt else self._strategy_preflight(room, zone, datetime.now())
        if strategy_hold:
            log(f"[{room.slug}] Z{zone} shot held: {strategy_hold}")
            return
        # Freeze hydraulic sizing before opening hardware. Editing plant count,
        # substrate or dripper configuration mid-shot must not rewrite its litres.
        nominal_l = (flow_lps * duration_s if flow_lps is not None
                     else size_pct / 100.0 * self._substrate_l(room, zone))
        with self._shot_lock:  # a batch holds rooms under this lock (see _shot_running)
            making = self._dosing_hold(room)
            if not making:
                self._busy = True
                self._shot_room = room  # the room whose shot is in flight right now (see _safe_off)
        if making:
            log(f"[{room.slug}] Z{zone} shot held: {making}")
            return
        hw = room.hw
        valve = hw["valves"].get(zone)
        pump, mainline = hw.get("pump"), hw.get("mainline")
        # Read before anything opens, so nothing waits on Home Assistant between the steps.
        # An integration older than these settings has neither: the 2 s and 1 s always waited apply.
        prime = lead = 0.0
        if pump:
            prime = _lead_time(
                self._zone_num(room, zone, "pump_prime_time", FALLBACK["pump_prime_time"], optional=True),
                FALLBACK["pump_prime_time"], PUMP_PRIME_MAX_S)
        if mainline:
            lead = _lead_time(
                self._zone_num(room, zone, "main_line_lead_time", FALLBACK["main_line_lead_time"], optional=True),
                FALLBACK["main_line_lead_time"], MAIN_LINE_LEAD_MAX_S)
        # WRITE-AHEAD: what this shot is about to open, and when, saved BEFORE anything opens. If the
        # controller dies, is killed or loses Home Assistant mid-shot, the next loop closes exactly what
        # this shot opened, from this record, and nothing else (see _reconcile_room_inflight).
        room.shot_inflight = {
            "zone": zone, "valve": valve, "mainline": mainline, "pump": pump,
            "started": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()
        shutdown_checked = False
        valve_started = None
        counted = False
        stopping = False
        try:
            # OPEN sequence — FAIL CLOSED: if any service call errors, cut what's on, alert, and DO NOT count the shot
            # (otherwise daily_vol / last_shot lie after an auth/entity/service failure and a zone silently starves).
            # Pump and mainline are optional (a one-switch tent has neither): each is sequenced when
            # mapped and skipped, with its lead time, when not. The valve is always required.
            if pump and not hw_call(pump, True):
                hw_call(pump, False)  # it may be on all the same: off before the alert
                self._alert(
                    f"hw_{room.slug}_z{zone}",
                    "CS-302",
                    "shot cancelled, the pump didn't switch on",
                    "Home Assistant returned an error when the pump was switched on. No water was "
                    f"delivered and the shot was not counted. {_CANCELLED_SHOT_CLEANUP}"
                    f"\n\nPump: {pump}",
                    room=room,
                    zone=zone,
                )
                return
            if pump:
                time.sleep(prime)
            if mainline and not hw_call(mainline, True):
                if pump:
                    hw_call(pump, False)
                self._alert(
                    f"hw_{room.slug}_z{zone}",
                    "CS-303",
                    "shot cancelled, the main-line valve didn't switch on",
                    "Home Assistant returned an error when the main-line valve was switched on. No "
                    f"water was delivered and the shot was not counted. {_CANCELLED_SHOT_CLEANUP}"
                    f"\n\nMain-line valve: {mainline}",
                    room=room,
                    zone=zone,
                )
                return
            if mainline:
                time.sleep(lead)
            valve_started = time.monotonic()
            valve_opened = datetime.now(timezone.utc)  # on Home Assistant's clock too: see _close_cut_short
            if not hw_call(valve, True):
                for upstream in (mainline, pump):
                    if upstream:
                        hw_call(upstream, False)
                self._alert(
                    f"hw_{room.slug}_z{zone}",
                    "CS-304",
                    "shot cancelled, the zone valve didn't switch on",
                    "Home Assistant returned an error when this zone's valve was switched on. No "
                    f"water was delivered and the shot was not counted. {_CANCELLED_SHOT_CLEANUP}"
                    f"\n\nValve: {valve}",
                    room=room,
                    zone=zone,
                )
                return
            elapsed, aborted = self._wait_shot(
                room, zone, duration_s, started=valve_started
            )
            if aborted and aborted[0] == "external":
                # Something else closed the feed path (dosing, a tank fill, a guard automation, a person).
                # Only what is still this shot's is closed, so the error cleanup below, which switches off
                # all three (a pump a hold now owns too), must never run for it: anything left recorded is
                # settled by the reconciler at the next loop.
                shutdown_checked = True
                elapsed = self._close_cut_short(room, zone, aborted[1], elapsed, duration_s, valve_opened)
                # Counted as a kill-switch abort is: the shot counts, with only the water it delivered.
                run = elapsed / duration_s if duration_s > 0 else 1.0
                counted = True
                self._advance_shot_counters(room, zone, size_pct * run, delivered_l=nominal_l * run,
                                            steering=steering)
                return
            # CLOSE sequence. A failed close (e.g. HA went unreachable mid-shot) leaves the valve
            # OPEN and the SOFTWARE CANNOT fix it — only the hardware fail-safe (NC valve /
            # pump-relay-default-off / independent watchdog) can. So check EVERY turn_off + the
            # read-back and ALERT loudly on any non-close (the old code ignored turn_off failures
            # and a dead-HA read-back masked a stuck-open valve as "closed" — silent danger).
            refused = [] if hw_call(valve, False) else [valve]
            # Delivery is estimated, not flow-metered. Include the acknowledgement
            # interval conservatively because the exact physical close time is unknown.
            elapsed = max(elapsed, time.monotonic() - valve_started)
            upstream = [e for e in (mainline, pump) if e]  # closed valve first, then back up the line
            if upstream:
                time.sleep(1)
            for ent in upstream:
                if not hw_call(ent, False):
                    refused.append(ent)
            # Only a definitive OFF is safe, including pump/mainline read-back.
            closed = self._confirm_switches((valve, *upstream), "off")
            if (refused or not closed) and _GATE.state == "all":
                # Refused, not stuck: what is not confirmed stays recorded for the reconciler, which
                # reads it back once Home Assistant accepts this controller again.
                log(f"[{room.slug}] Z{zone} shot closed with Home Assistant refusing: its offs were sent, "
                    "not read back; left recorded")
            elif refused or not closed:
                # Which one, and how, as it is now: before the second try below changes it.
                failures = self._close_failures((valve, *upstream), refused)
                for ent in reversed(upstream):
                    hw_call(ent, False)
                self._latch_hardware_fault(room, f"zone {zone} shot end", failures)
            else:
                room.shot_inflight = None  # closed and read back OFF: this shot left nothing open
            shutdown_checked = True
            # Count the shot — water WAS delivered, so daily_vol/last_shot must reflect it (else the
            # daily cap under-counts and the zone can over-water). A kill-switch/override abort mid-shot
            # only delivered part of the shot, so scale the volume by the fraction actually run.
            delivered_pct = size_pct * (elapsed / duration_s if duration_s > 0 else 1.0)
            counted = True
            self._advance_shot_counters(
                room, zone, delivered_pct,
                delivered_l=nominal_l * (elapsed / duration_s if duration_s > 0 else 1.0),
                steering=steering,
            )
            if aborted and aborted[0] == "refused":
                log(f"[{room.slug}] Z{zone} shot ended after {elapsed:.0f}/{duration_s:.0f}s: Home Assistant "
                    "refused this controller's token")
            elif aborted:
                by = aborted[1]
                why = {
                    room_gate(room): "the engine switch was turned off",
                    f"switch.crop_steering_{room.prefix}room_active": "Room Active was switched off",
                    f"switch.crop_steering_{room.prefix}zone_{zone}_enabled": "this zone was switched off",
                }.get(by, "manual override was turned on")
                self._alert(
                    f"killshot_{room.slug}_z{zone}",
                    "CS-305",
                    "shot stopped early",
                    f"The shot was stopped after {elapsed:.0f} of {duration_s:.0f} seconds, because "
                    f"{why} ({by}). The valve and anything upstream were switched off, and the water "
                    "delivered so far is counted.",
                    room=room,
                    zone=zone,
                )
        except SystemExit:
            # SIGTERM/SIGINT mid-shot (the app stopped or updated): _safe_exit has already closed what this
            # shot has open, by the reconciler's rules, so the cleanup below must not switch the rest off.
            # Count the water this shot delivered before the process goes, or the next start would water
            # the zone as if it had had none.
            stopping = True
            if valve_started is not None and not counted:
                counted = True
                run = (time.monotonic() - valve_started) / duration_s if duration_s > 0 else 1.0
                self._advance_shot_counters(room, zone, size_pct * run, delivered_l=nominal_l * run,
                                            steering=steering)
            raise
        except Exception as e:
            log("shot error", room.slug, zone, e)
        finally:
            try:
                # Early command failures and unexpected exceptions need the SAME hold
                # guarantee as normal shutdown; no path may start the next row blindly.
                if not shutdown_checked and not stopping:
                    closing = [
                        e for e in (valve, hw.get("mainline"), hw.get("pump")) if e
                    ]
                    refused = [
                        ent
                        for ent in closing
                        if not hw_call(ent, False)
                    ]
                    # Read back as patiently as after a normal close: a plug that reports OFF 1.6 s
                    # late is not a stuck pump (the 15 Sep false hold, on this very path).
                    closed = self._confirm_switches(closing, "off")
                    if refused or not closed:
                        self._latch_hardware_fault(
                            room,
                            f"zone {zone} shot error cleanup",
                            self._close_failures(closing, refused),
                        )
                    else:
                        room.shot_inflight = None
                        self._save_state()
            finally:
                self._busy = False
                self._shot_room = None

    def _safe_off(self, deadline=None):
        """Stopping (SIGTERM: the app stopped, updated or restarted): close only what this controller has
        in flight, by the reconciler's rules (_inflight_plan), and nothing else.

        With no shot in flight nothing is switched off: the tank is circulated for well over 20 minutes to
        heat it and zones are hand-watered with the valves and main line open, and stopping the app must
        end neither. The shot running NOW is closed whatever its kill switch reads (it is this process's
        own); an older interrupted shot is left to the operator while its kill switch is not ON, as in the
        loop. Anything that cannot be closed and read back OFF stays recorded for the next start.

        With a `deadline` (the monotonic clock) every room with a shot recorded gets an equal share of the
        time left, the room whose shot is running now first, so a slow room never takes the next one's
        time. What no longer fits is not read or sent, and stays recorded (see _Stop)."""
        shot_room = getattr(self, "_shot_room", None)
        rooms = [room for room in self.rooms if getattr(room, "shot_inflight", None)]
        rooms.sort(key=lambda room: room is not shot_room)
        slowest = [0.0]  # how slow Home Assistant is answering, carried from room to room
        for i, room in enumerate(rooms):
            stop = None
            if deadline is not None:
                now = time.monotonic()
                stop = _Stop(now + max(0.0, deadline - now) / (len(rooms) - i), slowest)
            self._safe_off_room(room, room is shot_room, stop)

    def _safe_off_room(self, room, running, stop):
        rec = room.shot_inflight
        order = [e for e in (rec.get("valve"), rec.get("mainline"), rec.get("pump")) if e]
        # Each read keeps time for its own switch's off and those of the switches read before it.
        reads = {e: _read(e, stop and stop.keeping(i)) for i, e in enumerate(order, 1)}
        if all(read[0] == "off" for read in reads.values()):
            room.shot_inflight = None
            return
        if not running and _read(room_gate(room), stop and stop.keeping(1))[0] != "on":
            return
        close, left, unsure, why = self._inflight_plan(room, rec, reads, stop)
        if running and unsure[:1] == [rec.get("valve")]:
            # The valve of the shot running now is this process's own: when whose it is could not be told
            # (no time left, or no read), it is switched off all the same. What is upstream stays recorded.
            close, unsure = unsure[:1], unsure[1:]
        if close and not self._switch_off_confirmed(close, stop):
            log(f"[{room.slug}] stopping: {', '.join(close)} not confirmed OFF - left recorded for the next start")
            return
        if close:
            log(f"[{room.slug}] stopping: switched off {', '.join(close)} (the shot in flight)")
        if left:
            log(f"[{room.slug}] stopping: left {', '.join(left)} alone ({why})")
        if not unsure:
            room.shot_inflight = None

    def _safe_exit(self, *_):
        budget = runtime_env.stop_budget(os.environ)
        deadline = time.monotonic() + budget
        log(f"SIGTERM — closing what is in flight within {budget:g} s, saving state, exiting")
        try:
            try:
                # Dosing starts nothing from here on. Then the shot in flight: it is water running now.
                # Dosing's way out waits on its thread, so it goes last, in the time the stop keeps for it.
                self._stop_dosing_starts()
                reserve = min(STOP_DOSING_S, budget / 5) if self._dosing_recorded() else 0.0
                self._safe_off(deadline - reserve)
                self._exit_dosing(deadline)
            finally:
                self._save_state()
                self._say_stopped(datetime.now(), deadline)
        finally:
            sys.exit(0)

    def _say_stopped(self, now, deadline):
        """Stopping (an update, a restart or by hand): each room's heartbeat says so, so the dashboard
        shows a stopped controller, and since when, rather than one that stopped reporting. It keeps
        what the integration reads to find the engine switch, and leaves out strategy_snapshot_version,
        so no grow plan is armed on a stopped controller. Last, after the safe-off and the state file,
        and only in what is left of the stop's budget (`deadline`, the monotonic clock): requests
        applies the timeout to the connect and the read separately, so each write gets half its share,
        at most 2 s, and none is sent once that is under 0.25 s."""
        try:
            for i, room in enumerate(self.rooms):
                timeout = min(2.0, (deadline - time.monotonic()) / (2 * (len(self.rooms) - i)))
                if timeout < 0.25:
                    return
                beat = getattr(room, "_beat", None)
                ha_set(
                    f"sensor.crop_steering_{room.prefix}ai_heartbeat",
                    "stopped",
                    {
                        "engine": PRODUCT,
                        "controller_version": CONTROLLER_VERSION,
                        "stopped_at": now.isoformat(),
                        "last_beat": now.isoformat(),
                        "enable_flag": room_gate(room),
                        "hardware_fault": self._hardware_fault_block(room),
                        "setup_revision": getattr(room, "setup_revision", 0),
                        "setup_active": getattr(room, "setup_active", True),
                        "room_active": beat[1] if beat else True,
                    },
                    timeout=timeout,
                )
        except Exception as e:
            log("could not say stopped on the heartbeat:", e)

    def _stop_dosing_starts(self):
        try:
            if self.dosing is not None:
                self.dosing.stop_starting()
        except Exception as e:
            log("dosing: could not be stopped from starting on the way out:", e)

    def _dosing_recorded(self):
        try:
            return self.dosing is not None and self.dosing.recorded()
        except Exception:
            return True  # whether it has anything to switch off can't be told: keep it its time

    def _exit_dosing(self, deadline=None):
        """Stopping: no dosing switch-on starts from here, the dosing thread switches its own job off,
        and what a dose or batch has recorded is switched off again, each off with a short timeout
        (dosing_runner.exit), all before the stop's `deadline` (the monotonic clock) when given. Its
        record stays in dosing_state.json, so the next start reads it back OFF and raises CS-803."""
        try:
            if self.dosing is not None:
                self.dosing.exit(None if deadline is None else max(0.0, deadline - time.monotonic()))
        except Exception as e:
            log("dosing: could not switch off on the way out:", e)

    def _start_dosing(self):
        """Before the first loop: settle what a dose or batch left running before this start
        (docs/DOSING.md, After a restart), then start dosing's own thread, which tries the recovery
        again until Home Assistant takes it. Neither can stop the controller starting."""
        if self.dosing is None:
            return
        try:
            self.dosing.recover()
        except Exception as e:
            log("dosing: start-up recovery failed; the dosing thread tries again:", e)
        try:
            self.dosing.start()
        except Exception as e:
            log("dosing: off, it could not start:", e)

    @staticmethod
    def _step_ec_offset(cur, ec_smooth, ec_target_p2, base):
        if ec_target_p2 <= 0:
            return cur
        if ec_smooth < ec_target_p2 * 0.90:
            target = -1.0
        elif ec_smooth > ec_target_p2 * 1.10:
            target = 1.0
        else:
            target = 0.0
        step = max(-1.0, min(1.0, target - cur))
        return max(-0.20 * base, min(0.20 * base, cur + step))

    def _minutes_since_shot(self, st, now):
        ls = st.get("last_shot")
        return (now - ls).total_seconds() / 60.0 if ls else 1e9

    # ---- shot sizing from LIVE config (not a hardcoded option) — a shot is size% of substrate volume ----
    def _test_shot(self, room, zone, now):
        """A new press of the zone's Test Shot button: this pass's decision for the zone, a TEST_SHOT_S
        shot sized from its flow, or None. It then goes through every gate a shot does but a held plan
        (PLAN_HOLD_EXEMPT). The first state seen is a starting point, not a press: it may be from
        before this controller started."""
        pressed = ha_get(f"button.crop_steering_{room.prefix}zone_{zone}_test_shot")[0]
        if pressed in (None, "", "unavailable") or pressed == room._test_seen.get(zone):
            return None
        first = zone not in room._test_seen
        room._test_seen[zone] = pressed
        if first or pressed == "unknown":
            return None
        at = _aware(pressed)
        if at is None or abs((now.astimezone() - at).total_seconds()) > TEST_REQUEST_S:
            log(f"[{room.slug}] Z{zone} Test Shot pressed at {pressed[:16]} was not acted on: too long ago")
            return None
        flow, substrate = self._zone_flow_lps(room, zone), self._substrate_l(room, zone)
        sized = math.isfinite(flow) and flow > 0 and math.isfinite(substrate) and substrate > 0
        # Unsized, _act_zone says why (CS-204) and runs nothing.
        size = TEST_SHOT_S * flow / substrate * 100.0 if sized else 0.0
        return True, size, Reason(f"TEST shot {TEST_SHOT_S} s (asked for)", "test_shot")

    def _substrate_l(self, room, zone):
        """ZONE-TOTAL substrate (L) = per-plant block x plant_count. The substrate_volume entity is the
        PER-PLANT block size (e.g. 6 L); flow_lps is zone-total (plant_count x drippers x L/hr), so the
        duration + daily-volume math need zone-total substrate or shots come out plant_count-times short
        (the machine-gun: per-plant 6 L / zone flow -> ~36x too short, VWC never rises).
        """
        per_plant = self._zone_num(room, zone, "substrate_volume", self.substrate_l)
        pc = self._zone_num(room, zone, "plant_count", FALLBACK["plant_count"])
        return per_plant * pc if pc > 0 else per_plant

    def _zone_flow_lps(self, room, zone):
        """Real zone delivery rate (L/s) = plants x drippers/plant x dripper L/hr / 3600.
        plant_count CANCELS against the zone-total substrate in the duration math, so default it
        to 1 here — that way the dripper flow rate + drippers/plant ALWAYS drive shot length even
        when plant_count hasn't been set. Only fall back to the option if drippers/flow are unset.
        """
        # Missing legacy sizing can use the option, but explicit invalid sizing
        # must hold rather than silently substituting a different delivery rate.
        for suffix in ("drippers_per_plant", "dripper_flow_rate"):
            for scope in (f"zone_{zone}_", ""):
                value = self._num_or_none(
                    f"number.crop_steering_{room.prefix}{scope}{suffix}"
                )
                if value is not None:
                    if not math.isfinite(value) or value <= 0:
                        return 0.0
                    break
        pc = self._zone_num(room, zone, "plant_count", FALLBACK["plant_count"]) or 1
        dpp = self._zone_num(room, zone, "drippers_per_plant", FALLBACK["drippers_per_plant"])
        fr = self._zone_num(
            room,
            zone,
            "dripper_flow_rate",
            self._num(f"number.crop_steering_{room.prefix}dripper_flow_rate", 0),
        )  # L/hr per dripper; preserve the legacy global fallback.
        if dpp > 0 and fr > 0:
            return pc * dpp * fr / 3600.0
        return self.flow_lps

    def _budget_spent(self, room, zone, p, st):
        """Less of the zone's daily budget is left than the shortest shot (MIN_SHOT_S at its flow)."""
        left = p.max_daily_volume - float(st.get("daily_vol") or 0.0)
        flow = self._zone_flow_lps(room, zone)
        return math.isfinite(flow) and flow > 0 and left < MIN_SHOT_S * flow

    def _act_zone(self, room, zone, p, snap, decision, block, lights_on, now):
        st = room.state[zone]
        fire, size, reason = decision
        if (
            snap is not None
            and fire
            and block
            and lights_on
            and p.watchdog_hours > 0
            and snap.minutes_since_shot > p.watchdog_hours * 60
            and snap.vwc < p.p2_threshold
        ):
            self._alert(
                f"wd_{room.slug}_z{zone}",
                "CS-207",
                "URGENT, drying out and not being watered",
                f"This zone is dry (moisture {snap.vwc:.0f}%, below its {p.p2_threshold:.0f}% trigger) and "
                + (
                    "has never been watered by the controller"
                    if snap.minutes_since_shot > 1e8
                    else f"hasn't been watered for {snap.minutes_since_shot/60.0:.1f} hours"
                )
                + ", but watering is blocked. If you switched it off on purpose, this is a reminder "
                f"that the plants are drying out.\n\nBlocked by: {block}",
                room=room,
                zone=zone,
            )
        if fire and block:
            log(
                f"[{room.slug}] Z{zone} {st['phase']} BLOCKED ({block}): would {reason}"
            )
        elif fire:
            flow = self._zone_flow_lps(room, zone)
            substrate = self._substrate_l(room, zone)
            if not (
                math.isfinite(flow)
                and flow > 0
                and math.isfinite(substrate)
                and substrate > 0
            ):
                self._alert(
                    f"sizing_{room.slug}_z{zone}",
                    "CS-204",
                    "shot size can't be worked out, not watering",
                    "To size a shot the controller needs this zone's pot size (litres per plant), "
                    "plant count, drippers per plant and dripper flow, and one of them is missing, "
                    "zero or unreadable. Set them in Rooms & setup.",
                    room=room,
                    zone=zone,
                )
                return
            test = getattr(reason, "kind", None) == "test_shot"
            raw_dur = float(TEST_SHOT_S) if test else size / 100.0 * substrate / flow
            max_dur = self._room_duration_cap(room)
            if max_dur is None:
                return
            # Hydraulic sizing determines nominal runtime; the room's duration
            # limit bounds every physical shot independently of its requested volume.
            dur = max(MIN_SHOT_S, min(int(max_dur), int(raw_dur)))
            if raw_dur > max_dur:
                self._alert(
                    f"durcap_{room.slug}_z{zone}",
                    "CS-306",
                    "shot shortened to the safety limit",
                    f"The planned shot would run {int(raw_dur)} seconds, longer than the room's "
                    f"{int(max_dur)}-second limit, so it runs for {int(max_dur)} seconds and delivers "
                    "less than planned. Check this zone's pot size and dripper flow; if they are "
                    "right, raise the maximum shot length.",
                    room=room,
                    zone=zone,
                )
            # A shot that is not exempt from the daily budget gets only what is left of it (22 Sep: a
            # 607 s, ~28 L flush fired with ~2 L of an 80 L budget left). Copied / blind-schedule
            # decisions are never exempt either (their Reason, or plain text, is not cap_exempt).
            if p is not None and not getattr(reason, "cap_exempt", False):
                left_l = p.max_daily_volume - float(st.get("daily_vol") or 0.0)
                allowed = int(left_l / flow) if left_l > 0 else 0
                if allowed < MIN_SHOT_S:
                    held = f"BLOCK daily-cap ({max(left_l, 0.0):.2f} L left)"
                    self._alert_daily_cap(room, zone, st, snap is None, held)
                    log(f"[{room.slug}] Z{zone} {st['phase']} hold — {held}: would {reason}")
                    return False, 0.0, held
                if dur > allowed:
                    log(f"[{room.slug}] Z{zone} shot clipped {dur}s -> {allowed}s: {left_l:.2f} L of the daily budget left")
                    size, dur = round(size * allowed / dur, 2), allowed
            log(f"[{room.slug}] Z{zone} {st['phase']} FIRE {size}% ~{dur}s — {reason}")
            # Count configured flow x actual runtime, including caps, truncation,
            # the minimum duration and partial aborts. Preserve this flow snapshot
            # so later sizing edits cannot change an already delivered volume.
            self._execute_shot(room, zone, dur, size, flow_lps=flow,
                               plan_exempt=getattr(reason, "kind", None) in PLAN_HOLD_EXEMPT, steering=not test)
            self._count_capped(room, zone, raw_dur > max_dur)
        else:
            if "BLOCK" in reason and (
                getattr(reason, "kind", None) == "block_daily_cap" or "daily-cap" in reason
            ):
                self._alert_daily_cap(room, zone, st, snap is None, reason)
            elif "BLOCK" in reason:
                self._alert(
                    f"block_{room.slug}_z{zone}",
                    "CS-206",
                    "root-zone EC too high, not watering",
                    "Root-zone EC is above this zone's maximum, and a flush can't bring it down "
                    "right now (the feed is no weaker than the root zone, or the cube is already "
                    "saturated), so the controller holds the zone: no shot runs, the overnight "
                    "emergency shot and the no-water-for-hours safety shot included. The hold lifts "
                    "by itself once a flush could help; if the plants may dry out first, check the "
                    "feed EC and the EC probe now."
                    f"\n\nDetail ({st['phase']}): {reason}",
                    room=room,
                    zone=zone,
                )
            # A gate that is closed is said out loud in every phase: overnight nothing is due, and a
            # room blocked since a restart used to look exactly like a healthy one until lights-on.
            log(f"[{room.slug}] Z{zone} {st['phase']} hold — {reason}"
                + (f" [blocked: {block}]" if block else ""))

    # ---------- CS-312: the max-run latch ----------
    def _max_run_switch(self, room):
        """-> (state, resets) of the room's max-run latch switch: its state as read, None when it can't be
        read (absent, as on an integration from before the latch), and how many times its Repairs card was fixed."""
        state, attributes, _ = ha_get(f"switch.crop_steering_{room.prefix}max_run_latch")
        resets = (attributes or {}).get("resets")
        return state, resets if type(resets) is int else 0

    def _count_capped(self, room, zone, capped):
        """After a shot: count it into the zone's run of shots cut to the room's maximum shot length, and latch
        the zone at MAX_RUN_IN_A_ROW while the room's max-run latch switch reads ON. The integration's CS-312
        card reports the run either way, from the heartbeat (_max_run_report)."""
        st = room.state[zone]
        st["capped_in_a_row"] = int(st.get("capped_in_a_row") or 0) + 1 if capped else 0
        if st["capped_in_a_row"] < MAX_RUN_IN_A_ROW or st.get("max_run_latch"):
            return
        state, resets = self._max_run_switch(room)
        if str(state).lower() not in ON_STATES:
            log(f"[{room.slug}] Z{zone} {st['capped_in_a_row']} shots in a row cut to the longest allowed shot "
                "(CS-312); the max-run latch is off, so it keeps watering")
            return
        st["max_run_latch"] = {"since": datetime.now().isoformat(), "resets": resets}
        self._save_state()
        log(f"[{room.slug}] Z{zone} max-run latch: {st['capped_in_a_row']} shots in a row cut to the longest "
            "allowed shot; no more water until its Repairs card (CS-312) is fixed")

    def _max_run_hold(self, room, zone):
        """The hold of a latched zone, or None. Released once its Repairs card is fixed (the switch's `resets`
        moved) or the switch reads OFF; a switch that can't be read keeps it held."""
        st = room.state.get(zone) or {}
        latch = st.get("max_run_latch")
        if not latch:
            return None
        state, resets = self._max_run_switch(room)
        off = str(state).lower() == "off"
        if off or (state not in (None, "unknown", "unavailable", "") and resets != latch["resets"]):
            st["max_run_latch"], st["capped_in_a_row"] = None, 0
            self._save_state()
            log(f"[{room.slug}] Z{zone} max-run latch released: " + ("switched off" if off else "reset in Repairs"))
            return None
        return (
            f"max-run latch: {MAX_RUN_IN_A_ROW} shots in a row cut to the longest allowed shot; "
            "fix its Repairs card (CS-312) to water again"
        )

    def _max_run_report(self, room):
        """The heartbeat's `max_run`: each zone in a run of MAX_RUN_IN_A_ROW or more cut shots, or latched, with the
        `resets` it was latched at (the integration's card leaves a zone off once the switch has moved past it)."""
        report = {}
        for zone, st in (getattr(room, "state", None) or {}).items():
            latch, capped = st.get("max_run_latch"), int(st.get("capped_in_a_row") or 0)
            if latch:
                report[str(zone)] = {"capped": capped, "latched": True, "resets": latch["resets"]}
            elif capped >= MAX_RUN_IN_A_ROW:
                report[str(zone)] = {"capped": capped, "latched": False}
        return report

    def _alert_daily_cap(self, room, zone, st, blind, detail):
        """CS-205. A zone with a working probe still gets its rescue shots past its daily limit; a zone
        without one gets nothing more, because its copied and timed shots all count against it."""
        self._alert(
            f"block_{room.slug}_z{zone}",
            "CS-205",
            "daily water limit reached",
            (
                "This zone has had its daily water limit. It has no usable moisture reading, so "
                "every shot it gets is copied or timed and none is exempt: it gets no more water "
                "until lights-on starts the next day, the overnight emergency shot included. Check "
                "its probe (this zone's moisture notification says what is wrong)."
                if blind
                else "This zone has had its daily water limit, so routine top-ups and EC-correction "
                "shots stop until lights-on starts the next day. The morning ramp, the "
                "overnight emergency shot, the no-water-for-hours safety shot and high-EC "
                "flushes still run."
            )
            + f"\n\nDetail ({st['phase']}): {detail}",
            room=room,
            zone=zone,
        )

    def _settings_hold(self, room, zone):
        """Why the zone waits for its settings, or None. First, every shot kind: a setting this pass could not
        read, missing for fewer than SETTINGS_WAIT_PASSES passes, is still loading. Then a setting that sizes
        this zone's water (WATER_SIZING) not read once since the controller started holds this zone, its
        rescues included. Any other missing setting runs on its last value read, else its built-in value."""
        seen = self.__dict__.setdefault("_settings_seen", {})
        unread = []
        for suffix in WATER_SIZING:
            if parameter_override(getattr(room, "strategy_snapshot", None), zone, suffix) is not None:
                continue
            self._zone_num(room, zone, suffix, None)  # a read is remembered; a miss is noted for CS-402
            per = f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}"
            glob = f"number.crop_steering_{room.prefix}{suffix}"
            if per not in seen and glob not in seen:
                unread.append(glob)
        waiting = sorted(
            e for e in getattr(room, "_settings_missing", ())
            if self._defaulted.get(e, 0) < SETTINGS_WAIT_PASSES
        )
        if waiting:
            more = f" and {len(waiting) - 2} more" if len(waiting) > 2 else ""
            return f"waiting for its settings to load ({', '.join(waiting[:2])}{more})"
        if unread:
            return (f"not watering: {', '.join(unread)} not read since the controller started, and it sizes "
                    "this zone's water (CS-402)")
        return None

    def _check_defaulted_setpoints(self):
        """Turn the per-loop 'setpoint entity missing' set into a rate-limited alert once an
        entity has been missing for >=3 consecutive loops (ignores one-off read blips). Clears
        automatically when the entity reappears."""
        cur = self._defaulted_this_loop
        for eid in list(self._defaulted):
            if eid not in cur:
                del self._defaulted[eid]
        for eid in cur:
            self._defaulted[eid] = self._defaulted.get(eid, 0) + 1
        persistent = sorted(e for e, n in self._defaulted.items() if n >= 3)
        self._n_defaulted = len(persistent)
        if persistent:
            # Name the ones that size how much water a zone gets, when they are among them.
            key = [what for part, what in (("substrate_volume", "the pot size"),
                                           ("plant_count", "the plant count"),
                                           ("drippers_per_plant", "the drippers per plant"),
                                           ("dripper_flow_rate", "the dripper flow"),
                                           ("max_daily_volume", "the daily water limit"))
                   if any(e.endswith(part) for e in persistent)]
            self._alert(
                "defaulted_setpoints",
                "CS-402",
                "settings missing, running on built-in values",
                "These settings can't be read in Home Assistant, so the engine uses the last value it "
                "read since it started, else its built-in value"
                + (f". {' and '.join(key).capitalize()} size a zone's water: a zone that has not read "
                   "one since the controller started is not watered, its rescues included, until it is back"
                   if key else ". Check those values suit this room")
                + ": reload the integration, and if Repairs lists settings that are not where the "
                "controller looks, follow code CS-605.\n\n"
                + "\n".join(persistent[:20]),
            )

    def loop_once(self, now):
        if self._busy:
            return
        self._notify_config(refresh=True)  # who gets pushes, read here so an alert never waits on it
        self._watch_dosing()
        self._recover_hardware_faults()
        self._reconcile_inflight()
        self._defaulted_this_loop = set()
        if (
            getattr(self, "_default_provisional", False)
            or (now - self._last_discovery).total_seconds() >= self.rediscover_seconds
        ):
            try:
                self._rediscover(now)
            except Exception as e:
                log("rediscover error", e)
        all_pub = {}
        for room in self.rooms:
            self._guard_read(room)  # before this pass writes the room's heartbeat
            self._refresh_lights(room)
            pub = self._loop_room(room, now)
            self._publish_status(room, pub, now)
            all_pub[room.slug] = pub
        self._check_defaulted_setpoints()
        self._maybe_notify(all_pub, now)
        self._send_events()

    # ---------------------------------------------------------------- two controllers on one room
    def _guard_read(self, room):
        """Read the room's heartbeat for the duplicate-controller guard (duplicate_hold). Another
        controller's write is a beat whose controller_instance is not ours, or missing (a controller
        from before the guard), with a last_updated other than the last such one seen. Home Assistant
        stamps last_updated itself, so neither controller's clock or time zone matters; only at the
        first answer is a beat's age judged, by Home Assistant's own clock when it says (its Date), and
        an old one is not counted. No heartbeat at all (404: Home Assistant restarted, as a state set
        over REST is not restored) is nobody's. No answer changes nothing."""
        status, beat = ha_get_status(f"sensor.crop_steering_{room.prefix}ai_heartbeat")
        if status not in (200, 404):
            return
        with self._guard_lock:
            guard = self._guard.setdefault(room.slug, {"answered": False, "seen": None, "until": None})
            first, guard["answered"] = not guard["answered"], True
            _state, attributes, stamp = beat
            if status == 404 or attributes.get("controller_instance") == self.instance_id or stamp == guard["seen"]:
                return
            guard["seen"] = stamp
            when, now = _aware(stamp), beat.served_at or datetime.now(timezone.utc)
            if first and when is not None and (now - when).total_seconds() >= DUPLICATE_HOLD_S:
                return
            guard["until"] = time.monotonic() + DUPLICATE_HOLD_S
        log(f"[{room.slug}] another controller wrote this room's heartbeat "
            f"({attributes.get('controller_instance') or 'no id: a version before the guard'}): holding")

    def duplicate_hold(self, room):
        """Whether the room holds for another controller: from start until its heartbeat has been read,
        and for DUPLICATE_HOLD_S of this process's monotonic clock after the last read that saw another
        controller write it. A lock and a clock read, so the dosing thread asks it too."""
        with self._guard_lock:
            guard = self._guard.get(room.slug)
            return (guard is None or not guard["answered"]
                    or (guard["until"] is not None and time.monotonic() < guard["until"]))

    def _hold_duplicate(self, room, now):
        """A room duplicate_hold holds: nothing in it is switched on and none of its logic runs, so no
        phase, setpoint, EC step or shot, and the dosing thread refuses its dose and batch requests.
        Offs still run. Only its heartbeat is written, which makes the other controller hold too."""
        with self._guard_lock:
            seen = (self._guard.get(room.slug) or {}).get("until") is not None
        if seen:
            self._alert(
                f"duplicate_{room.slug}",
                "CS-609",
                "another controller is writing this room's heartbeat, holding",
                "Another controller is reporting for this room, so this one waters nothing and doses "
                "nothing in it until none has been seen for 3 minutes. Right after an update this is "
                "expected: the version before it reported without an id, and this clears by itself in "
                "about 3 minutes. If it stays, two controllers are running this room (an app and a "
                "container, or two apps): stop and remove the one you no longer use.",
                room=room,
            )
        self._heartbeat(room, now, self._hardware_fault_block(room))

    def _blind_time_transition(self, room, zone, now, lights_on, lights_just_on):
        """Time-only phase forces for a BLIND zone (dead/missing probe), so it can never
        strand overnight while `decide()` is skipped: lights-off -> P3, and P3 -> P0 at the
        new photoperiod (with the daily-counter reset, mirroring the P0 branch in _loop_room),
        also from a P1/P2 left over from a grow-day the controller did not see end (as decide()).
        The VWC-driven transitions (P0->P1->P2, predictive P3) need a probe and stay paused.
        """
        st = room.state[zone]
        gds = self._grow_day_start(room, now)
        new_grow_day = self._new_grow_day(room, st, now, lights_on)
        new_phase = None
        why = None
        if not lights_on and st["phase"] != "P3":
            new_phase, why = "P3", "lights-off (no moisture reading)"
        elif st["phase"] == "P3" and (lights_just_on or new_grow_day):
            new_phase, why = "P0", "lights-on (no moisture reading)"
        elif st["phase"] in ("P1", "P2") and new_grow_day:
            new_phase, why = "P0", "a new grow-day (no moisture reading)"
        if new_phase and new_phase != st["phase"]:
            if new_phase == "P0":
                self._keep_day_peak(st)  # the grow-day ending: tomorrow's P1 target (_vwc_maxima)
                st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, 0.0  # _snapshot takes the peak from the next reading
                st["ec_offset"], st["last_ec_steer"] = 0.0, None
                st["last_daily_reset"] = gds
            was = st["phase"]
            st["phase"] = new_phase
            st["last_phase_change"] = now
            self._save_state()
            self._notify_event("phase", room, zone, was, new_phase, why)

    def _apply_phase_request(self, room, zone, st, now):
        """Move a zone to the phase the operator picked on its Set Phase select, once. The select is
        set back to Keep first; if that write fails the request waits for the next loop, so a phase
        the engine has since moved on from is never applied twice. The move is made as the engine's
        own would be: P1 ramps from its first shot again, and P0 measures its dry-back from the
        moisture now (_snapshot takes the peak from the next reading). Nothing else is reset, today's
        water included, and the engine's rules carry on from the new phase: lights-off still moves
        a zone to P3 and lights-on to P0."""
        entity = f"select.crop_steering_{room.prefix}zone_{zone}_set_phase"
        wanted = ha_get(entity)[0]
        if wanted not in ("P0", "P1", "P2", "P3"):
            return
        if not ha_call("select", "select_option", entity_id=entity, option="Keep"):
            return
        was = st["phase"]
        if wanted == was:
            return
        self._record_phase(room, zone, st, was, wanted, now, "set by hand")
        if wanted == "P0":
            st["peak"] = 0.0
        if wanted == "P1":
            st["shots"] = 0
        st["phase"], st["last_phase_change"] = wanted, now
        tag = "" if room.prefix == "" else f"{room.slug} "
        self._activity.insert(0, f"{now.strftime('%H:%M')} {tag}Z{zone} phase {was} -> {wanted}, set by hand"[:120])
        log(f"[{room.slug}] Z{zone} phase {was} -> {wanted}: set by hand")
        self._save_state()
        self._notify_event("phase", room, zone, was, wanted, "set by hand")

    def _strategy_preflight(self, room, zone, now):
        if getattr(room, "_strategy_batch_invalid", False):
            return "Strategy changed or held; recompute the irrigation batch on the next loop"
        previous = getattr(room, "strategy_snapshot", None) or {}
        before = (
            previous.get("required", False),
            previous.get("managed", set()),
            previous.get("zones", {}),
        )
        self._load_strategy_snapshot(room, now)
        current = room.strategy_snapshot
        hold = strategy_block(current, zone)
        if hold:
            room._strategy_batch_invalid = True
            return hold
        after = (
            current.get("required", False),
            current.get("managed", set()),
            current.get("zones", {}),
        )
        if before != after:
            room._strategy_batch_invalid = True
            return (
                "Strategy changed; recompute the irrigation decision on the next loop"
            )
        return None

    def _load_strategy_snapshot(self, room, now):
        state, attrs, _ = ha_get(self._cs(room, "sensor", "strategy_plan"))
        was_required = getattr(room, "strategy_required", False)
        snapshot = parse_snapshot(
            state, attrs, room.prefix, now.timestamp(), was_required
        )
        if (
            snapshot["required"]
            and not snapshot["error"]
            and snapshot["managed"] != set(room.zones)
        ):
            snapshot["error"] = (
                "Strategy zones do not match room setup; disarm and reconcile the draft"
            )
        changed = was_required != snapshot["required"]
        room.strategy_required = snapshot["required"]
        if changed:
            room._strategy_persisted = False
        if not getattr(room, "_strategy_persisted", True):
            if self._save_state():
                room._strategy_persisted = True
            else:
                # Never permit activation or a return to legacy behaviour without
                # preserving that decision across a controller/container restart.
                room.strategy_required = was_required or snapshot["required"]
                snapshot["required"] = True
                snapshot["error"] = "Strategy state could not be persisted"
        room.strategy_snapshot = snapshot

    def _loop_room(self, room, now):
        """One room's full control pass: snapshot -> decide -> act -> build the publish dict.
        Reads/writes only this room's prefixed entities + its own state."""
        if getattr(room, "setup_active", True) is False:
            self._idle_reset(room, now)
            return {}
        if self.duplicate_hold(room):
            self._hold_duplicate(room, now)
            return {}
        if f"duplicate_{room.slug}" in self._alerted:
            log(f"[{room.slug}] no other controller seen for {DUPLICATE_HOLD_S // 60} min: carrying on")
            ha_call("persistent_notification", "dismiss", notification_id=f"f2_duplicate_{room.slug}")
            del self._alerted[f"duplicate_{room.slug}"]
        room._settings_missing = set()  # what this pass could not read (_zone_num)
        active, was = self._room_active(room), getattr(room, "_was_room_active", None)
        room._was_room_active = active
        if not active:
            if was is True:  # seen going off: how long it stays off decides what switching it on does
                room._off_since = datetime.now()
                self._save_state()
            if was is not False:
                self._room_switched_off(room)
            self._idle_reset(room, now)  # CS-209 runs only while the room is on
            self._publish_room_off(room, now)
            return {}  # no snapshot, no decision, no blind schedule, no alerts, no vitals line
        if was is False:
            self._room_switched_on(room)
        room._retired_off = self._carry_retired_switches(room)
        self._load_strategy_snapshot(room, now)
        # Only a newly computed batch can clear a prior preflight invalidation.
        room._strategy_batch_invalid = False
        lights_on = self._lights_on(room, now)
        was_off = not (
            room._was_lights_on if room._was_lights_on is not None else lights_on
        )
        lights_just_on = lights_on and was_off
        lights_just_off = room._was_lights_on is True and not lights_on
        snaps, decisions, healthy, blind, params = {}, {}, [], [], {}
        for zone in room.zones:
            st = room.state[zone]
            self._apply_phase_request(room, zone, st, now)
            self._water_usage(room, zone, now)
            if self._starts_day(room, st, now, lights_on, lights_just_on):
                # This tick starts the zone's day: yesterday's EC steer must not shape it. The P0 reset
                # below clears it as well, but only after decide() has read the P2 threshold (its P0
                # bypass test) with yesterday's offset baked in.
                st["ec_offset"], st["last_ec_steer"] = 0.0, None
            snap, p = self._snapshot(room, zone, now, lights_on, lights_just_on)
            params[zone] = p
            if lights_just_off or lights_just_on:  # the night's two readings (zone_history), kept across a restart
                try:
                    vwc = snap.vwc if snap is not None else None
                    if lights_just_off:
                        zone_history.lights_off(st, vwc, now, self._grow_day_start(room, now).isoformat())
                    else:
                        zone_history.lights_on(st, vwc, now)
                    self._save_state()
                except Exception as e:  # a record never stops the room being decided and watered
                    log("zone history error", room.slug, zone, e)
            jev_dirs = {}
            distrusted = room.__dict__.setdefault("_jev_distrusted", {})
            distrusted.pop(zone, None)
            if snap is not None and getattr(self, "jev", None) is not None:
                try:  # Jev's judges (docs/JEV.md): whatever goes wrong here, the base engine decides
                    jev_dirs = jev_bridge.tick(self, room, zone, snap, p, now, lights_on)
                    if "distrust" in jev_dirs:
                        distrusted[zone] = jev_dirs["distrust"].why  # the zone takes the dead-probe path
                        snap = None
                    elif "advance" in jev_dirs:
                        snap = jev_bridge.advance(self, room, zone, snap, jev_dirs["advance"], now)
                except Exception as e:
                    log("jev error", room.slug, zone, e)
                    jev_dirs = {}
            if snap is None:
                room._blind_since.setdefault(zone, now)
                blind.append((zone, p))
                continue
            room._blind_since.pop(zone, None)
            snaps[zone] = snap
            if st["phase"] == "P1" and snap.vwc >= min(p.p1_target, p.field_capacity):
                st["p1_reached"] = True  # the P1 rule (core.decide): the target has been read this P1
            try:  # CS-310: never pour the daily minimum, or an EC flush, into a table that isn't draining
                if self._watch_backup(room, zone, snap, now):
                    p = params[zone] = dataclasses.replace(p, min_daily_volume=0.0)
                    snap = snaps[zone] = dataclasses.replace(snap, backed_up=True)
            except Exception as e:
                log("backup watch error", room.slug, zone, e)
            self._count_peak(st, snap)
            if snap.ec is None:
                self._alert(
                    f"ec_unknown_{room.slug}_z{zone}",
                    "CS-104",
                    "root-zone EC not available",
                    "There is no usable root-zone EC reading for this zone: it is missing, "
                    "unavailable, out of range, or hasn't changed for 20 minutes. Watering carries on "
                    "by moisture alone; EC-based shot sizing and EC learning are paused, and salt "
                    "build-up can't be checked or flushed."
                    f"\n\nSensor: {self._fused_id(room.prefix, 'ec', zone, room.zones[zone].get('ec'))}",
                    room=room,
                    zone=zone,
                )
            healthy.append((zone, p.p1_target))
            new_phase, new_thr, fire, size, reason = decide(snap, p)
            if fire and not getattr(reason, "cap_exempt", False) and self._budget_spent(room, zone, p, st):
                # Less of the daily budget is left than the shortest shot: decide again as the engine
                # does with the budget spent (the watchdog rescue, P1 completing at its ceiling) instead
                # of firing a shot _act_zone could only refuse.
                snap = snaps[zone] = dataclasses.replace(snap, daily_vol=max(snap.daily_vol, p.max_daily_volume))
                new_phase, new_thr, fire, size, reason = decide(snap, p)
            shown = snap  # what waiting_for reads: the snapshot, in the phase the zone is now in
            if new_phase != st["phase"]:
                # decide()'s reason leads with why the phase moved ("lights-off -> P3 | ..."): the push says it.
                self._notify_event("phase", room, zone, st["phase"], new_phase, str(reason).split(" | ")[0])
                self._record_phase(room, zone, st, st["phase"], new_phase, now, str(reason).split(" | ")[0])
                if new_phase == "P0":
                    self._keep_day_peak(st)  # the grow-day ending: tomorrow's P1 target (_vwc_maxima)
                    st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, snap.vwc
                    st["ec_offset"], st["last_ec_steer"] = 0.0, None
                    st["last_daily_reset"] = self._grow_day_start(room, now)
                    st["vmax_wetup"] = []  # fresh wet-up curve for today's ramp
                if new_phase == "P1":
                    st["shots"] = 0
                    # entering P1 already at the target: the shot decide() fires on this tick is the extra shot
                    st["p1_reached"] = snap.vwc >= min(p.p1_target, p.field_capacity)
                st["phase"] = new_phase
                st["last_phase_change"] = now
                self._save_state()
                # The snapshot was taken in the old phase: what the new one starts from.
                shown = dataclasses.replace(
                    snap, phase=new_phase, phase_minutes=0.0,
                    **({"peak_vwc": snap.vwc} if new_phase == "P0" else {}),
                    **({"shot_count": 0} if new_phase == "P1" else {}),
                )
            self._publish_waiting_for(room, zone, shown, p, now)
            # The EC steer runs on ec_smooth, which only settled readings feed (see _settled_ec).
            if (snap.ec is not None and snap.ec_smooth is not None and p.stacking_on
                    and st["phase"] == "P2" and p.ec_target_p2 > 0):
                base = self._zone_num(room, zone, "p2_vwc_threshold", FALLBACK["p2_vwc_threshold"])
                les = st.get("last_ec_steer")
                # Jev's Salt judge chooses how: steer (as always), hold the offset, or decay it toward 0.
                ec_mode = getattr(jev_dirs.get("ec_mode"), "value", "steer")
                if ec_mode != "steer" and (les is None or (now - les).total_seconds() >= 1800):
                    if ec_mode == "decay":
                        st["ec_offset"] = round(float(st.get("ec_offset", 0.0)) * 0.5, 2)
                    st["last_ec_steer"] = now
                    self._save_state()
                elif les is None or (now - les).total_seconds() >= 1800:
                    st["ec_offset"] = self._step_ec_offset(
                        float(st.get("ec_offset", 0.0)),
                        snap.ec_smooth,
                        p.ec_target_p2,
                        base,
                    )
                    st["last_ec_steer"] = now
                    self._save_state()
            # Vmax advisory: watch the P1 wet-up for the field-capacity ceiling.
            # Published as a sensor only — it does NOT change any irrigation decision.
            if st["phase"] == "P1":
                st["vmax_wetup"] = ((st.get("vmax_wetup") or []) + [snap.vwc])[-VMAX_SERIES_MAX:]
                v, c = detect_vmax(st["vmax_wetup"])
                if v is not None:
                    room._vmax[zone] = (v, c)
            decisions[zone] = (fire, size, reason)
            try:  # learning and setpoint upkeep must never be able to stop a zone being watered
                self._auto_tick(room, zone, snap, p, lights_on, now)
            except Exception as e:
                log("auto setpoints error", room.slug, zone, e)
        for zone, p in blind:
            st = room.state[zone]
            self._publish_waiting_for(room, zone, None, p, now)  # no probe: nothing to compare
            # A dead probe must NOT freeze the daily cycle: still honour the time-based
            # phase forces (lights-off -> P3, P3 -> P0 at the new photoperiod). Only the
            # VWC-driven transitions are paused while blind.
            self._blind_time_transition(room, zone, now, lights_on, lights_just_on)
            out_min = (now - room._blind_since[zone]).total_seconds() / 60.0
            if out_min < BLIND_GRACE_MIN:
                # 25 Sep 2026: the probes read unknown for a minute, and a timer shot fired at once.
                decisions[zone] = (False, 0.0, Reason(
                    f"probe unreadable {out_min:.0f} min: waiting {BLIND_GRACE_MIN} min before watering "
                    "without it", "blind_wait"))
                continue
            if healthy:
                sib = pick_sibling(p.p1_target, healthy)
                s_fire, s_size, s_reason = decisions[sib]
                rescue = getattr(s_reason, "kind", None) in PLAN_HOLD_EXEMPT
                decisions[zone] = (s_fire, s_size, Reason(f"COPY Z{sib} (VWC probe dead)",
                                                          "blind_copy_rescue" if rescue else "blind_copy"))
                plan = (
                    "Until it reads normally again, this zone gets the same shots as "
                    f"{self._zone_title(room, sib)}, whose probe is working."
                )
            else:
                mss = self._minutes_since_shot(st, now)
                decisions[zone] = (
                    mss >= self.blind_fallback_min,
                    p.p2_shot_size,
                    Reason("FALLBACK schedule (no live probe)", "blind_fallback"),
                )
                plan = (
                    "Until it reads normally again, this zone is watered on a timer while the engine "
                    f"is on: one shot every {int(self.blind_fallback_min)} minutes, within its daily "
                    "water limit. Phase changes that go by moisture wait for the probe."
                )
            # Re-alert each tick — _alert's 30-min debounce throttles it to a repeating
            # reminder so a dead probe can't sit unnoticed (the silent-freeze lesson). Why it
            # is unusable is read every tick, so a changed cause replaces the card's diagnosis.
            looking = self._fused_id(room.prefix, "vwc", zone, room.zones[zone].get("vwc"))
            set_aside = room.__dict__.get("_jev_distrusted", {}).get(zone)
            if set_aside:
                self._alert(
                    f"blind_{room.slug}_z{zone}",
                    "CS-704",
                    "Jev set this zone's probe aside",
                    f"Jev judged, twice in a row and confirmed by the controller's own check, that this "
                    f"zone's moisture probe is not tracking the substrate ({set_aside}). {plan} It counts "
                    "again as soon as Jev judges it tracks. Check the probe's placement and wiring."
                    f"\n\nSensor: {looking}",
                    room=room,
                    zone=zone,
                )
                room._blind_zones.add(zone)
                continue
            code, what = self._unreadable(looking)
            self._alert(
                f"blind_{room.slug}_z{zone}",
                code,
                _PROBE_ALERTS[code][0],
                f"{what} {plan} {_PROBE_ALERTS[code][1]}\n\nSensor: {looking}",
                room=room,
                zone=zone,
            )
            room._blind_zones.add(zone)
        room._blind_zones = {z for z in room._blind_zones if z not in snaps}
        for zone in room.zones:  # a test shot asked for takes the zone's turn this pass
            test = self._test_shot(room, zone, now)
            if test:
                decisions[zone] = test
        if room._beat is None or not room._beat[1]:
            self._report_before_acting(room, decisions, snaps, now)
        pub = {}
        for zone in room.zones:
            if zone not in decisions:
                continue
            fire, size, reason = decisions[zone]
            # A dead probe cannot establish an emergency on THIS row. Copy/fallback
            # shots therefore keep its own budget, even when the sibling is flushing.
            if (
                zone not in snaps
                and fire
                and room.state[zone]["daily_vol"] >= params[zone].max_daily_volume
            ):
                fire, size = False, 0.0
                reason = (
                    f"BLOCK daily-cap {room.state[zone]['daily_vol']:.0f}/"
                    f"{params[zone].max_daily_volume:.0f}L (blind irrigation budget)"
                )
                decisions[zone] = (fire, size, reason)
            # A held plan is shown on every zone it holds: decide() no longer returns the steering shot it
            # would have stopped (ZoneSnapshot.steering_held), so the hold is said here instead.
            block = (self._blocked(room, zone, reason) if fire
                     else strategy_block(getattr(room, "strategy_snapshot", None), zone))
            if fire and not block and getattr(self, "jev", None) is not None and getattr(reason, "kind", None) != "test_shot":
                jev_bridge.shot_started(room, zone, snaps.get(zone), getattr(reason, "kind", None))
            acted = self._act_zone(
                room,
                zone,
                params[zone],
                snaps.get(zone),
                decisions[zone],
                block,
                lights_on,
                now,
            )
            if acted is not None:  # held back at the daily budget after all: publish what happened
                fire, size, reason = decisions[zone] = acted
            snap = snaps.get(zone)
            # Estimated hours to the next P2 top-up: time for VWC to dry from now down to the
            # (EC-adjusted) re-water threshold at the current dryback rate. Only meaningful in P2;
            # 0 = due now, None elsewhere. Drives the dashboard's "next" on the frequency card.
            pz = params[zone]
            next_h = None
            if snap is not None and room.state[zone]["phase"] == "P2":
                if snap.vwc <= pz.p2_threshold:
                    next_h = 0.0
                elif snap.dryback_rate and snap.dryback_rate > 0:
                    next_h = round(
                        min((snap.vwc - pz.p2_threshold) / snap.dryback_rate, 48.0), 2
                    )
            pub[zone] = {
                "phase": room.state[zone]["phase"],
                "vwc": snap.vwc if snap else None,
                "ec": snap.ec if snap else None,
                "ec_settled": snap.ec_settled if snap else None,
                "fire": fire,
                "block": block,
                "reason": reason,
                "blind": snap is None,
                "p": params[zone],
                "vmax": room._vmax.get(zone),
                "next_h": next_h,
            }
        for z, why in cross_zone_outliers(snaps):
            self._alert(
                f"xzone_{room.slug}_{z}",
                "CS-501",
                "much less water than the other zones",
                "This zone has been given far less water today than the room's other zones. "
                "Plants that drink less, a probe sitting in a wetter spot, or a valve or dripper "
                f"problem can all do this. Watering carries on as normal.\n\nDetail: {why}",
                room=room,
                zone=z,
            )
        self._watch_probe_methods(room)
        if getattr(self, "jev", None) is not None:
            try:
                jev_bridge.siblings(self, room, snaps, params, now)
                jev_bridge.publish(self, room, now, ha_set)
            except Exception as e:
                log("jev publish error", room.slug, e)
        try:  # CS-209 only ever tells: it can never stop the room being watered
            self._watch_idle(room, now, lights_on, pub)
        except Exception as e:
            log("idle watch error", room.slug, e)
        try:  # CS-311 only ever tells, too
            self._watch_sump(room, now)
        except Exception as e:
            log("sump watch error", room.slug, e)
        room._was_lights_on = lights_on
        return pub

    def _publish_status(self, room, pub, now):
        if not pub:
            return
        px = room.prefix
        try:
            labels = []
            for zone in sorted(pub):
                d = pub[zone]
                p = d["p"]
                shown, since = room._safety_shown.get(zone, (None, None))
                saf = zone_safety_status(
                    d["vwc"], d["ec"], p.field_capacity, p.max_ec,
                    shown, None if since is None else (now - since).total_seconds() / 60,
                )
                if saf != shown:
                    room._safety_shown[zone] = (saf, now)
                labels.append(saf)
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_phase",
                    d["phase"],
                    {"reason": d["reason"], "engine": PRODUCT},
                )
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_safety_status",
                    saf,
                    {
                        "vwc": d["vwc"],
                        "ec": d["ec"],
                        # the pore EC the EC rules act on: a reading EC_SETTLE_MIN after a shot, held between
                        "ec_settled": d.get("ec_settled"),
                        "ec_valid": d["ec"] is not None,
                        "ec_degraded": d["ec"] is None,
                        "ec_fallback": "base_vwc" if d["ec"] is None else None,
                        "field_capacity": p.field_capacity,
                        "max_ec_limit": p.max_ec,
                    },
                )
                held = self._hardware_fault_short(room)
                tested = d["fire"] and not d["block"] and getattr(d["reason"], "kind", None) == "test_shot"
                self._publish_zone_status(
                    room, zone,
                    zone_status_label(d["phase"], False, held, False, d["reason"]) if held
                    else "Test shot" if tested
                    else zone_status_label(d["phase"], d["fire"], d["block"], d["blind"], d["reason"]),
                    d["reason"],
                )
                # Advisory Vmax (detected P1 wet-up ceiling); operator eyeballs it,
                # nothing auto-tunes from it yet.
                vm = d.get("vmax")
                if vm and vm[0] is not None:
                    ha_set(
                        f"sensor.crop_steering_{px}zone_{zone}_vmax_detected",
                        vm[0],
                        {
                            "confidence": vm[1],
                            "unit_of_measurement": "%",
                            "friendly_name": f"Zone {zone} detected Vmax (advisory)",
                            "engine": PRODUCT,
                        },
                    )
                ls = room.state[zone].get("last_shot")
                if ls is not None:
                    ha_set(
                        f"sensor.crop_steering_{px}zone_{zone}_last_irrigation_app",
                        # Internal times stay local-naive; publish the event's local
                        # UTC offset, including historical daylight-saving changes.
                        # The switch-on stamp is NOT an irrigation: say "unknown", which also
                        # overwrites the false time an earlier controller left in Home Assistant.
                        "unknown" if room.state[zone].get("last_shot_is_anchor")
                        else ls.astimezone().isoformat(),
                        {"device_class": "timestamp"},
                    )
                # Daily volume fed + shot count today — the dashboard's "Volume fed vs cap"
                # + "Irrigation frequency" tiles read these. The data lives in zone state;
                # republish it (resets at the P3->P0 lights-on rollover, like the counters).
                zst = room.state[zone]
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_daily_water_app",
                    round(float(zst.get("daily_vol") or 0.0), 2),
                    {
                        "unit_of_measurement": "L",
                        "device_class": "water",
                        "state_class": "total",
                        "friendly_name": f"Zone {zone} water today",
                        "engine": PRODUCT,
                    },
                )
                weekly, coverage = self._water_usage(room, zone, now)
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_weekly_water_app",
                    weekly,
                    {"unit_of_measurement": "L", "device_class": "water",
                     "state_class": "total", "friendly_name": f"Zone {zone} water over seven grow-days",
                     "engine": PRODUCT, **coverage},
                )
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_irrigation_count_app",
                    int(zst.get("shots") or 0),
                    {
                        "state_class": "total",
                        "friendly_name": f"Zone {zone} shots today",
                        "engine": PRODUCT,
                    },
                )
                # Estimated hours to the next P2 shot (drives the dashboard "next"). Only published
                # when computable (P2 + a real dryback rate); skipped otherwise so the card shows "—".
                nh = d.get("next_h")
                if nh is not None:
                    ha_set(
                        f"sensor.crop_steering_{px}prediction_zone_{zone}_next_irrigation_hours",
                        nh,
                        {
                            "unit_of_measurement": "h",
                            "friendly_name": f"Zone {zone} next irrigation",
                            "engine": PRODUCT,
                        },
                    )
            sys_stat, unsafe, warn, safe = system_safety_status(labels)
            ha_set(
                f"sensor.crop_steering_{px}system_safety_status",
                sys_stat,
                {"unsafe_zones": unsafe, "warning_zones": warn, "safe_zones": safe},
            )
            ha_set(
                f"sensor.crop_steering_{px}app_current_phase",
                ", ".join(f"Z{z}:{pub[z]['phase']}" for z in sorted(pub)),
                {"friendly_name": "Zone Phases"},
            )
            room_held = any(
                d["block"] and "fail-closed" in str(d["block"]) for d in pub.values()
            )
            hardware_fault = self._hardware_fault_block(room)
            ha_set(
                f"sensor.crop_steering_{px}app_status",
                (
                    "error"
                    if room_held or hardware_fault
                    else ("irrigating" if self._busy else "safe_idle")
                ),
                {"engine": PRODUCT, "updated": now.isoformat()},
            )
            self._heartbeat(room, now, hardware_fault)
            fired = [
                f"Z{z} {d['phase']} {d['reason']}"
                for z, d in sorted(pub.items())
                if d["fire"] and not d["block"]
            ]
            held = [
                f"Z{z} {d['phase']} {d['block'] or d['reason']}"
                for z, d in sorted(pub.items())
                if d["block"] or "BLOCK" in d["reason"]
            ]
            ha_set(
                f"sensor.crop_steering_{px}current_decision",
                (
                    fired[0]
                    if fired
                    else (held[0] if held else "Holding — all zones in band")
                )[:255],
                {"fired": fired, "blocked": held},
            )
            tag = "" if px == "" else f"{room.slug} "
            for ln in fired + held:
                self._activity.insert(0, f"{now.strftime('%H:%M')} {tag}{ln}"[:120])
            del self._activity[60:]
            ha_set(
                f"sensor.crop_steering_{px}activity_log",
                (self._activity[0] if self._activity else "idle")[:255],
                {
                    "feed": "\n".join(self._activity[:50]),
                    "event_count": len(self._activity),
                },
            )
        except Exception as e:
            log("publish failed", room.slug, e)

    def _maybe_notify(self, all_pub, now):
        if (
            self._last_notify
            and (now - self._last_notify).total_seconds() < self.notify_min * 60
        ):
            return
        self._last_notify = now
        any_live = False
        blocks = []
        for room in self.rooms:
            pub = all_pub.get(room.slug) or {}
            if not pub:
                continue
            on = self._on(room_gate(room), False)
            any_live = any_live or on
            head = (room.slug if room.prefix else self.instance_name) + (
                " LIVE" if on else " HELD"
            )
            # Only a room with a feed EC probe says anything about feed EC. One that reads nothing
            # usable holds watering (the source-water gate), so it is named, not dropped.
            if room.feed_ec_sensor:
                feed = self._read_feed_ec(room)
                head += f" | feed EC {feed if feed is not None else 'unreadable'}"
            lines = [head]
            # "Include Predictions in Notifications": each zone's next step under its line. On until
            # switched off; an integration without the switch counts as on.
            predictions = self._on(f"switch.crop_steering_{room.prefix}notify_predictions", True)
            waiting = getattr(room, "_waiting", None) or {}
            per_plant = ha_get(f"select.crop_steering_{room.prefix}water_today_view")[0] == PER_PLANT
            for z in sorted(pub):
                d = pub[z]
                st = room.state[z]
                mss = self._minutes_since_shot(st, now)
                ago = "never" if mss > 1e8 else f"{mss/60:.1f}h"
                vwc = f"{d['vwc']:.0f}%" if d["vwc"] is not None else "—"
                ec = f"{d['ec']:.1f}" if d["ec"] is not None else "—"
                fc = f"{st['peak']:.0f}" if st.get("peak") else "—"
                water = f"{st['daily_vol']:.1f}L day"
                if per_plant:  # each plant's share; a zone without a plant count stays in litres
                    plants = self._zone_num(room, z, "plant_count", FALLBACK["plant_count"])
                    if plants >= 1 and float(plants).is_integer():
                        ml = st["daily_vol"] * 1000 / plants
                        water = f"{ml:.0f} mL/plant day" if ml < 1000 else f"{ml / 1000:.1f} L/plant day"
                lines.append(
                    f"  Z{z} {d['phase']}: VWC {vwc} EC {ec} (FC~{fc}) | {water} | last {ago}"
                )
                if predictions and z in waiting:
                    upcoming = next_text(*waiting[z])
                    if upcoming:
                        lines.append(f"  Next: {upcoming}")
            blocks.append("\n".join(lines))
        if not blocks:
            return
        head = now.strftime("%H:%M")
        if self._n_defaulted:
            head += f"  ⚠️ {self._n_defaulted} setpoint(s) missing → engine defaults"
        msg = f"{head}\n" + "\n".join(blocks)
        title = f"{self.instance_name} vitals"
        if not self._route_vitals(title, msg):
            dom, _, svc = self.notify_service.partition("/")
            if dom and svc:
                ha_call(dom, svc, title=title, message=msg)
        ha_call(
            "persistent_notification",
            "create",
            title=title,
            message=msg,
            notification_id="f2_vitals",
        )
        ha_set(
            "sensor.f2_control_vitals",
            now.strftime("%H:%M"),
            {"vitals": msg, "live": any_live, "friendly_name": f"{self.instance_name} vitals"},
        )

    def _route_vitals(self, title, message):
        """The vitals push, to the phones that tick Vitals (docs/NOTIFICATIONS.md) -> True when the integration
        took it. False, so it goes to the notify_service option as it always did, with nobody set up, with an
        integration that has no vitals kind (older than it), or when the call fails."""
        attrs = ha_get(NOTIFY_CONFIG)[1]
        kinds = attrs.get("kinds") if isinstance(attrs, dict) else None
        if not isinstance(kinds, list) or "vitals" not in kinds or not self._notify_config()[0]:
            return False
        try:
            return self._route("vitals", None, "vitals", None, None, title, message)
        except Exception as e:  # whatever goes wrong, the vitals go the old way
            log("notify: vitals not handed to crop_steering.notify", e)
            return False

    def _log_timezone(self):
        """All phase logic runs on container-local `datetime.now()`. If the Supervisor's TZ
        injection or tzdata is missing, the container is UTC and every lights/dryback/daily-reset
        window silently shifts by the site's offset. Log the effective offset at startup and
        alert if it disagrees with Home Assistant's configured zone."""
        now_local = datetime.now().astimezone()
        off = now_local.utcoffset()
        off_h = off.total_seconds() / 3600.0 if off else 0.0
        log(
            f"timezone: container local {now_local:%Y-%m-%d %H:%M} "
            f"(UTC{off_h:+.1f}h) TZ={os.environ.get('TZ', 'unset')}"
        )
        try:
            r = _session().get(f"{BASE}/config", headers=HDR, timeout=8) if _GATE.allows("other") else None
            if r is not None:
                _GATE.saw("other", r.status_code, f"GET {BASE}/config")
            ha_tz = (r.json() or {}).get("time_zone") if r is not None and r.status_code == 200 else None
        except Exception:
            ha_tz = None
        if not ha_tz:
            return
        try:
            from zoneinfo import ZoneInfo

            ha_off = datetime.now(ZoneInfo(ha_tz)).utcoffset().total_seconds() / 3600.0
        except Exception as e:  # tzdata missing, unknown zone, etc.
            log("timezone: could not resolve HA zone", ha_tz, e)
            return
        if abs(ha_off - off_h) > 0.01:
            self._alert(
                "tz_mismatch",
                "CS-405",
                "timezone mismatch, the day may be shifted",
                f"The controller app's clock is on UTC{off_h:+.1f}h, but Home Assistant is set to "
                f"{ha_tz} (UTC{ha_off:+.1f}h). Lights on and off, dryback and the daily reset all go "
                "by the app's clock, so the whole grow-day is shifted by the difference. "
                + (
                    "Set TZ in the controller container's compose file to Home Assistant's time zone, "
                    "or remove it to follow Home Assistant, then restart the container."
                    if _GATE.container
                    else "Update or rebuild the controller app; if it stays, check the time zone under "
                    "Settings → System → General."
                ),
            )
        else:
            log(f"timezone: matches Home Assistant ({ha_tz})")

    def run(self):
        log(
            f"{PRODUCT} {CONTROLLER_VERSION} starting | rooms",
            ", ".join(r.slug for r in self.rooms),
            "| notify",
            self.notify_service or "(none)",
            f"| loop {self.loop_seconds:.0f}s",
        )
        log("token present:", bool(TOKEN), "| base:", BASE)
        self._log_timezone()
        self._start_dosing()
        while True:
            if _GATE.state is not None:
                self._park_refused()
            try:
                self.loop_once(datetime.now())
            except Exception as e:
                log("loop error", e)
            if _GATE.state is None:
                time.sleep(self.loop_seconds)

    # ---------------------------------------------------------------- a refused token (container mode)
    def _switched_on(self):
        """What this process has switched on now, which a refused token still switches off (_AuthGate):
        the shot in flight's valve, main line and pump, and the running dose's or batch's hardware."""
        rec = getattr(self._shot_room, "shot_inflight", None) if self._shot_room is not None else None
        own = [rec.get(k) for k in ("valve", "mainline", "pump")] if rec else []
        if self.dosing is not None:
            own += self.dosing.running_off()
        return [e for e in own if e]

    def _recorded_entity(self):
        """The first switch a shot or a dose has recorded as maybe still on, or None."""
        for room in self.rooms:
            rec = getattr(room, "shot_inflight", None)
            for key in ("valve", "mainline", "pump"):
                if rec and rec.get(key):
                    return rec[key]
        return self.dosing.recorded_entity() if self.dosing is not None else None

    def _park_refused(self):
        """Home Assistant refuses this controller's token (_AuthGate): no more requests, but one question
        while anything is recorded, one read of a recorded switch every 60 s for 10 min and every 15 min
        after, so that if the refusal came from a proxy that recovers, the run carries on and the
        reconciler closes what is left. Returns once Home Assistant accepts again. A token whose user is
        no longer an administrator ("writes") never gets that back by itself: the shot in flight closed
        as usual, so the safe-off of a stop runs (without exiting), and while a shot stays recorded the
        reconciler, which needs no administrator, is run on the same schedule."""
        if _GATE.state == "writes":
            budget = runtime_env.stop_budget(os.environ)
            deadline = time.monotonic() + budget
            self._stop_dosing_starts()
            self._safe_off(deadline - (min(STOP_DOSING_S, budget / 5) if self._dosing_recorded() else 0.0))
            self._exit_dosing(deadline)
            self._save_state()
        since, said = time.monotonic(), False
        while True:
            writes = _GATE.state == "writes"
            entity = (next((r.shot_inflight["valve"] for r in self.rooms if getattr(r, "shot_inflight", None)),
                           None) if writes else self._recorded_entity())
            if entity is None:
                if not said:
                    log("parked: nothing this controller started is recorded, so nothing more is sent to Home "
                        "Assistant until the controller is restarted")
                    said = True
                time.sleep(runtime_env.PROBE_SLOW_S)
                continue
            due = since + runtime_env.next_probe(time.monotonic() - since)
            time.sleep(max(0.0, due - time.monotonic()))
            if writes:
                self._reconcile_inflight()
            else:
                _GATE.probe(entity)
                if _GATE.state is None:
                    return


def close_only_start():
    """For runtime_env.preflight: the token works but its user is not an administrator, and the previous
    run left a shot or a dose recorded. Close what is recorded with this token, by the usual rules (the
    reconciler, dosing's recovery), switch nothing on and write no state to Home Assistant, then return."""
    _GATE.state = "writes"
    controller = Controller()
    controller._reconcile_inflight()
    if controller.dosing is not None:
        controller.dosing.recover()


if __name__ == "__main__":
    runtime_env.preflight(close_only_start, version=CONTROLLER_VERSION)
    Controller().run()
