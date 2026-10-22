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
import logging
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
import dry_dim
import brain_bridge
import gate_report
import log_words
import phase_options
import plan_adherence
import runoff_balance
import runtime_env
import safety_ops
import sensing
import shot_audit
from brain import client as jev_client
import setpoint_supervisor
import tank_level
import zone_history
import day_summary
from strategy_runtime import merge_bridge, parse_snapshot, parameter_override, strategy_block

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
from crop_steering_engine.core import SETTLED_VWC_MIN, ec_flush_goal, p1_stall, p1_stall_rewater
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
SHOWN_BASE = runtime_env._shown(BASE)  # for the log: no user name or password in it
TOKEN = runtime_env.resolve_token(os.environ)[0]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
_S = requests.Session()


def _session():
    """The controller's requests.Session. Every request is made on the main loop (dosing runs there
    too, in steps), so one is enough; a test stands a fake one in here."""
    return _S


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
        _GATE.saw("read", r.status_code, f"GET {SHOWN_BASE}/states/{entity}")
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
        _GATE.saw("read", r.status_code, f"GET {SHOWN_BASE}/states/{entity}")
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
        _GATE.saw("other", r.status_code, f"GET {SHOWN_BASE}/states")
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
        _GATE.saw("other", r.status_code, f"GET {SHOWN_BASE}/history/period")
        if r.status_code != 200:
            return None
        rows = (r.json() or [[]])[0]
        return [(row.get("state"), row.get("last_changed")) for row in rows] or None
    except Exception:
        return None


def ha_logbook(entity, since, timeout=8):
    """Home Assistant's logbook entries for `entity` from `since` (an aware datetime) to now, oldest
    first, each with who made it (context_user_id, or the automation or script by name). [] when
    Home Assistant can't say."""
    if not _GATE.allows("other"):
        return []
    try:
        r = _session().get(
            f"{BASE}/logbook/{since.isoformat()}",
            headers=HDR,
            params={"entity": entity, "end_time": datetime.now(timezone.utc).isoformat()},
            timeout=timeout,
        )
        _GATE.saw("other", r.status_code, f"GET {SHOWN_BASE}/logbook")
        entries = r.json() if r.status_code == 200 else []
        return entries if isinstance(entries, list) else []
    except Exception:
        return []


def ha_call(domain, service, *, timeout=12, **data):
    kind = "off" if service == "turn_off" else "other"
    if not _GATE.allows(kind, data.get("entity_id")):
        return False
    try:
        r = _session().post(
            f"{BASE}/services/{domain}/{service}", headers=HDR, json=data, timeout=timeout
        )
        _GATE.saw(kind, r.status_code, f"POST {SHOWN_BASE}/services/{domain}/{service}")
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
    _GATE.saw("other", r.status_code, f"POST {SHOWN_BASE}/services/{domain}/{service}")
    if r.status_code >= 300:
        log("call_service FAILED", domain, service, "HTTP", r.status_code)
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body.get("service_response") if isinstance(body, dict) else None


def ha_fire(event, data, timeout=4):
    """Fire a Home Assistant event, best effort -> True when Home Assistant took it."""
    if not _GATE.allows("other"):
        return False
    try:
        r = _session().post(f"{BASE}/events/{event}", headers=HDR, json=data, timeout=timeout)
        _GATE.saw("other", r.status_code, f"POST {SHOWN_BASE}/events/{event}")
        return r.status_code < 300
    except Exception:
        return False


def ha_set(entity, state, attributes=None, timeout=8):
    """Write a state -> Home Assistant's HTTP status, or None when it was not sent or not answered. A write
    sent that failed is counted (the heartbeat's `write_failures`) and logged once an hour per entity."""
    if not _GATE.allows("write"):
        return None
    try:
        r = _session().post(
            f"{BASE}/states/{entity}",
            headers=HDR,
            json={"state": state, "attributes": attributes or {}},
            timeout=timeout,
        )
    except Exception as e:
        _set_failed(entity, e)
        return None
    _GATE.saw("write", r.status_code, f"POST {SHOWN_BASE}/states/{entity}")
    if r.status_code >= 300:
        _set_failed(entity, f"HTTP {r.status_code}")
    return r.status_code


# State writes that failed since the start, and when each entity's last failure was logged (time.monotonic()).
_SET_FAILED = {"count": 0, "logged": {}}
SET_FAILED_LOG_S = 3600.0


def _set_failed(entity, why):
    _SET_FAILED["count"] += 1
    now, last = time.monotonic(), _SET_FAILED["logged"].get(entity)
    if last is None or now - last >= SET_FAILED_LOG_S:
        _SET_FAILED["logged"][entity] = now
        log(f"state write failed: {entity} ({why}); {_SET_FAILED['count']} failed since the controller started")


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
        "moisture reading has not changed",
        "A cube with no plant gives a flat reading, because nothing drinks the water. If the cube "
        "has a plant, make sure that the probe is fully in the cube. A probe out of its cube also "
        "gives a flat reading. The zone goes back to usual shots when the reading changes. This "
        "alert stays until you dismiss it. In an empty room, set Room Active to off to stop these "
        "alerts.",
    ),
    "CS-102": (
        "moisture probe does not report",
        "Make sure that the probe has power and is online. Make sure that the correct moisture "
        "entity is mapped to the zone in Rooms & setup.",
    ),
    "CS-103": (
        "moisture reading out of range",
        "Check the calibration of the probe. Make sure that the entity mapped to this zone gives "
        "the moisture in %.",
    ),
    "CS-503": (
        "moisture probe set aside because of its unit",
        "Map the moisture reading of the probe in % (or m³/m³) to this zone. Alternatively, correct "
        "the unit of the entity in its own integration. The probe counts again when the controller "
        "can use its reading.",
    ),
}

# What follows a shot cancelled because a switch did not switch on (CS-302, CS-303, CS-304): _execute_shot's
# error cleanup switches off everything the shot may have opened and latches a hardware hold unless
# it all reads back OFF, which it can't while Home Assistant is unreachable.
_CANCELLED_SHOT_CLEANUP = (
    "The controller sets the pump, the main-line valve and the zone valve to off, and checks that "
    "they read off. If it cannot confirm this (Home Assistant cannot be reached, or a switch is "
    "offline), it latches a hardware hold (CS-301). Then no shot starts on this hardware until the "
    "hold clears. If the check passes, the controller tries the next shot as usual: after 3 such "
    "shots of a zone in a row, at most once every 30 min (rescue shots too, a Test Shot not)."
)

# Switch read-back after a close: see Controller._confirm_switches.
CONFIRM_FIRST_READ_S, CONFIRM_POLL_S, CONFIRM_TIMEOUT_S = 1.0, 0.5, 6.0
CONFIRM_RETRY_S = 10.0  # a second read-back, after OFF is sent again to what still reads on
# The whole read-back, ON or OFF (CLOSE_FAILURES words it). A pump, main line or zone valve that took its
# turn_on and does not read ON within it never started (CS-302 to CS-304; a zone valve within its shot, when
# shorter). After this many such shots in a row a zone is tried at most once every SWITCH_ON_BACKOFF_MIN,
# until its switches read on again.
SWITCH_ON_S = CONFIRM_TIMEOUT_S + CONFIRM_RETRY_S
SWITCH_ON_BACKOFF_AFTER, SWITCH_ON_BACKOFF_MIN = 3, 30


def _switch_on_retry_at(st):
    """When a zone backed off for switches that did not switch on may be tried again, or None: not backed off."""
    record = st.get("on_failures")
    if not record or record["count"] < SWITCH_ON_BACKOFF_AFTER:
        return None
    return datetime.fromisoformat(record["last"]) + timedelta(minutes=SWITCH_ON_BACKOFF_MIN)

# The safe-off on SIGTERM (Controller._safe_exit) runs inside runtime_env.stop_budget(). Dosing keeps
# STOP_DOSING_S of it (a fifth at most) for its own offs while a dose or batch has anything recorded.
# Each room with a shot recorded gets an equal share of the rest (see _Stop).
STOP_DOSING_S = 5.0


class _ShotStopped(Exception):
    """The operator stopped a shot while it was still opening (Controller._operator_stop's answer, `by`)."""

    def __init__(self, by):
        super().__init__(by)
        self.by = by


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
    "on": f"still read ON {SWITCH_ON_S:g} s after it was switched off",
    "unavailable": "read unavailable: Home Assistant could not reach it",
    "unknown": "read unknown instead of OFF",
    "unreadable": "could not be read from Home Assistant",
    "late": f"reported OFF only after the {SWITCH_ON_S:g} s check",
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


def hold_missing(entity):
    """Why a hold that Home Assistant answers it does not have (404) holds the shots: what to do about it."""
    return (f"Hold entity {entity} does not exist in Home Assistant. Remove it from the app's hold entities, "
            "or create it.")

# The most the room's Pump Prime Time and Main Line Lead Time may make a shot wait, in seconds: the
# top of each setting.
PUMP_PRIME_MAX_S, MAIN_LINE_LEAD_MAX_S = 20.0, 10.0


def _lead_time(value, default, top):
    """A Pump Prime Time or Main Line Lead Time read, as the seconds to wait: from 0 to `top`, and
    `default` for a value that is not a number."""
    return max(0.0, min(top, value)) if math.isfinite(value) else float(default)


# A room's no-touch window, as its Pause AI Changes select names it: how long it runs from the choice
# (None: until the next lights-on). Off, or any other word, is no window.
NO_TOUCH_HOURS = {"1 h": 1.0, "24 h": 24.0, "Until lights-on": None}


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
GROW_DAY_PROBE_S = 600  # how often the probes behind each zone are read for its grow-day summary (day_summary)
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
# The most one loop spends sending its phase changes and the AI assistant's moves: they are only news, and the loop is not.
EVENTS_BUDGET_S = 10.0
# The codes whose severity is critical in docs/error-codes.json (tests/test_error_codes.py keeps the two equal):
# their push is urgent, a high-priority one on a phone whose row asks for that.
CRITICAL_CODES = frozenset({"CS-201", "CS-202", "CS-203", "CS-204", "CS-207", "CS-211", "CS-212", "CS-301",
                            "CS-308", "CS-310", "CS-311", "CS-315", "CS-402", "CS-601", "CS-606", "CS-801",
                            "CS-809", "CS-811", "CS-901", "CS-902"})
# How often a standing alert pushes again, by its severity in docs/error-codes.json (tests/test_error_codes.py
# keeps INFO_CODES equal to the info codes): a critical code, or a warning that means a zone is not being watered,
# every 30 minutes for as long as it lasts; any other warning after 15 minutes, then 1, 2 and 4 hours, then every
# 8 hours; an info code once. Each episode starts the schedule again: an alert cleared (or not raised for
# ALERT_EPISODE_GAP_S) and raised again, or raised under another code. Held in memory only: a restart pushes once.
NOT_WATERING_CODES = frozenset({"CS-206", "CS-208", "CS-209", "CS-210", "CS-316", "CS-602"})
INFO_CODES = frozenset({"CS-205", "CS-305", "CS-403", "CS-501", "CS-702", "CS-705", "CS-711", "CS-712", "CS-906"})
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
# ladder this far a day. The fallback of the room's Max setpoint move per day (_step_limit).
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
# CS-317: the pump (option pump_power_sensor) draws more than the room's Pump Dead-Head Power with every zone
# valve of the room reading off for this long, outside a shot, a hold or a batch. It only tells.
DEADHEAD_S, DEADHEAD_W = 60.0, 20.0
# The room's waste-valve rule (select waste_valve_rule): Off (as before), Check closed, Close for each shot.
WASTE_CHECK, WASTE_CLOSE = "Check closed", "Close for each shot"
# The runoff estimator (runoff_balance.py, select runoff_estimator, off by default): the sump's runs and each mapped AC
# and dehumidifier's run time are read from Home Assistant's history every RUNOFF_CHECK_MIN (RUNOFF_FIRST_H back the
# first time) and the balance refitted every RUNOFF_FIT_MIN. A unit mapped by its power counts as running above the
# room's HVAC run power (HVAC_RUN_W where the integration has no such setting).
RUNOFF_MODES = ("off", "shadow", "shown_alerts", "ai")
RUNOFF_CHECK_MIN, RUNOFF_FIT_MIN, RUNOFF_FIRST_H, HVAC_RUN_W = 10.0, 30.0, 48.0, 50.0
# CS-312: a zone whose last MAX_RUN_IN_A_ROW shots were all cut to the room's maximum shot length (CS-306 each) keeps
# asking for more water than a shot may give, as a probe stuck dry does all day. With the room's max-run latch switch
# ON the zone is latched until its Repairs card is fixed; OFF, or absent (an older integration), it is only reported.
MAX_RUN_IN_A_ROW = 3
# The default room's kill switch on an installation from before the setup wizard: a helper the operator
# made by hand, and this app's shipped `enable_flag` option (config.yaml). A room made by the wizard stops
# on its own engine switch, named by its setup. Named here once; room_gate() is the rule.
LEGACY_ENABLE_FLAG = "input_boolean.f2_control_enabled"


def _epoch(stamp):
    """An ISO time (with or without a UTC offset; naive is local) as epoch seconds, or None."""
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


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
    topup, off, timed = find("p2_topup"), find("lights_off"), find("p2_timed")
    if topup or off or timed:
        # A held plan leaves the routine shots out: then only lights-off is left.
        dilute = find("p2_dilute")
        parts = [
            f"timed shot {'at ' + when(timed) if when(timed) else 'due'}" if timed else None,
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
        self._beat = None  # (hardware_fault, room_active, loop_error) of its last heartbeat
        self._beat_at = None  # and when, by time.monotonic()
        self._statuses = {}  # z -> (label, reason) of its zones' last status
        self._safety_shown = {}  # z -> (label, since) of its zones' safety status (the hysteresis)
        self._status_at = {}  # z -> when, by time.monotonic()
        # the tank level the descriptor maps (tank_level.mapping), and its drawdown check (durable)
        self.tank = {}
        self.tank_drawdown = tank_level.fresh()
        self.tank_round = {}  # z -> litres of its last shot asked for, for the plan-ahead refill (_tank_plan)
        self.waste = ""  # the room's waste valve (descriptor `waste`), only when mapped: never opened
        self.tank_estimate = safety_ops.tank_fresh()  # the estimated level, with no level sensor (durable)
        self._deadhead_since = None  # when the pump was first seen drawing power with every valve shut


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
        self._holds_card = None  # CS-210's card (_check_holds): True up, False down, None maybe (a previous run's)
        self.feed_grace_min = float(o.get("feed_grace_min", 30))
        self.blind_fallback_min = float(o.get("blind_fallback_min", 90))
        # Optional (CS-311): the power sensor of the sump pump a room's tables drain to, one for every room or
        # `room=sensor` pairs, and how long it may stand still while the room is on. Unset = not watched.
        self.sump_sensors = room_option(o.get("sump_power_sensor"))
        self.sump_silent_h = float(o.get("sump_silent_hours") or SUMP_SILENT_H)
        # Optional (CS-317): the power sensor of a room's feed pump, like the sump's. Unset = not watched.
        self.pump_power = room_option(o.get("pump_power_sensor"))
        # The AI assistant: a brain judges the engine's decisions inside a code envelope (docs/AI_ASSISTANT.md). None = rules;
        # brain_status says which brain runs and why, whether or not one is built (the brain panel shows it).
        logging.getLogger("anthropic").setLevel(logging.WARNING)  # no request or header ever reaches the log
        logging.getLogger("httpx").setLevel(logging.WARNING)
        log("brain SDK: " + (f"anthropic {getattr(jev_client.anthropic, '__version__', '')}".strip()
                             if jev_client.anthropic is not None else "not installed (rules only on this device)"))
        data_dir = os.path.dirname(runtime_env.state_path(os.environ)) or "."
        try:
            self.brain_status = brain_bridge.resolve_provider(o, data_dir)
            self.jev = brain_bridge.build(o, runtime_env.state_path(os.environ), log, self.brain_status)
            if self.jev is None:
                log(f"brain: rules ({self.brain_status.state}). {self.brain_status.words}")
        except Exception as e:  # the brain can never stop the controller starting
            log("brain: off, it could not start:", jev_client.redact(str(e)))
            self.jev, self.brain_status = None, brain_bridge.start_failed()
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
        # Dosing runs in steps on the main loop, which wakes whenever one is due (run, _sleep_for). Like
        # The AI assistant, it can never stop the controller starting, and it only ever acts on an explicit request
        # for a room with dosing set up.
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
            "p1_flat": 0,  # ...the ramp shots in a row under the target that did not give the rise P1 needs
            # this grow-day's stalled ramp (core.p1_stall): {"day", "at", "rewater"}, re-watering under what it reached
            "p1_stall": None,
            # an EC flush fired and the zone has not reached its EC flush target yet (core: ZoneSnapshot.ec_flushing)
            "ec_flushing": False,
            "vmax_wetup": [],  # this grow-day's P1 wet-up VWC readings, for the Vmax advisory (resets each P0)
            "rescue_misses": 0,  # CS-315: rescue shots in a row that did not raise the moisture (safety_ops)
            "rescue_check": None,  # ...and the last rescue waiting to be judged: {"before", "at"}
            # CS-302 to CS-304: shots in a row whose switches did not switch on, {"count", "last"} (_switch_on_retry_at)
            "on_failures": None,
            **zone_history.fresh(),
            **sensing.fresh(),  # the water-and-VPD record (sensing.py), kept only while its switch is on
            **day_summary.fresh(),  # the grow-day summary being measured, and those not yet sent (day_summary)
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
        if isinstance(d.get("ec_flushing"), bool):  # absent before the EC flush target: False
            s["ec_flushing"] = d["ec_flushing"]
        flat = d.get("p1_flat")  # absent before the P1 stall exit: 0, and None
        if type(flat) is int and 0 <= flat <= 100:
            s["p1_flat"] = flat
        stall = d.get("p1_stall")
        try:
            if isinstance(stall, dict) and isinstance(stall.get("day"), str):
                at, rewater = float(stall["at"]), float(stall["rewater"])
                if all(math.isfinite(v) and 0.0 < v <= 100.0 for v in (at, rewater)):
                    s["p1_stall"] = {"day": stall["day"], "at": at, "rewater": rewater}
        except (KeyError, TypeError, ValueError):
            pass
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
        failures = d.get("on_failures")  # absent before the switch-on backoff: None
        try:
            if isinstance(failures, dict) and type(failures.get("count")) is int and failures["count"] > 0:
                if datetime.fromisoformat(failures["last"]).tzinfo is not None:
                    raise ValueError("an aware time: _switch_on_retry_at compares with a naive now")
                s["on_failures"] = {"count": failures["count"], "last": failures["last"]}
        except (KeyError, TypeError, ValueError):
            pass
        s.update(zone_history.restore(d))
        s.update(safety_ops.restore_zone(d))
        s.update(sensing.restore(d))
        s.update(day_summary.restore(d))
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
        # Plan adherence's own record (plan_adherence.load): absent on an older file, field by field otherwise.
        room._adherence = plan_adherence.load(block.get("_adherence") if isinstance(block, dict) else None)
        room.tank_drawdown = tank_level.load(block.get("_tank") if isinstance(block, dict) else None)
        room.tank_estimate = safety_ops.tank_load(block.get("_tank_estimate") if isinstance(block, dict) else None)
        remembered = block.get("_waste_rule") if isinstance(block, dict) else None
        room._waste_rule_known = remembered if remembered in ("Off", WASTE_CHECK, WASTE_CLOSE) else None
        room._runoff = runoff_balance.load(block.get("_runoff") if isinstance(block, dict) else None)
        # A dim the controller did not finish (dry_dim.py): absent on an older file. Restored on the first pass.
        room._dim = dry_dim.load(block.get("_dim") if isinstance(block, dict) else None)
        room._dimmer = dry_dim.Dimmer(restarted=room._dim is not None)
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
            room.zone_cultivars = self._zone_cultivars(attrs)  # a label, read like the names: never decides anything
            room.room_name = self._room_name(attrs)
            room.substrate = self._substrate(attrs)  # read like the names: needs no adoption
            room.light_entity = str(attrs.get("light_entity") or "").strip()  # checked, never actuated
            room.tank = tank_level.mapping(attrs)  # read only, never actuated: needs no adoption
            # Only ever switched OFF, and only under the room's waste-valve rule; setup changes need it off.
            room.waste = str(attrs.get("waste") or "").strip()
            # each AC and dehumidifier the room maps, read only for the runoff estimator (runoff_balance.py)
            room.hvac_units = [str(e) for key in ("ac_entities", "dehumidifier_entities")
                               for e in (attrs.get(key) or []) if isinstance(e, str) and e]
            # the room's climate sensors, read only for the water-and-VPD record (sensing.py)
            room.climate = {k: str(attrs.get(k) or "").strip() for k in ("vpd_sensor", "temperature_sensor",
                                                                         "humidity_sensor")}
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
                            "setup change on hold, no shots",
                            (f"The controller loads the setup of this room (revision {revision}) again "
                             "after a restart" if resuming else
                             f"The room has a changed setup (revision {revision})")
                            + ". The room gets no shots until the controller applies the setup. "
                            "The controller applies it only while these are "
                            f"OFF: {', '.join(running if resuming else armed + running)}. Set them "
                            "to off. Then wait for this alert to "
                            f"clear (up to {int(getattr(self, 'rediscover_seconds', 300))} s)"
                            + (". Then the room continues as before." if resuming
                               else ". Then set the kill switch to on again."),
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
            "p1_flat": int(s.get("p1_flat") or 0),
            "p1_stall": s.get("p1_stall"),
            "ec_flushing": bool(s.get("ec_flushing")),
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
            "rescue_misses": int(s.get("rescue_misses") or 0),
            "rescue_check": s.get("rescue_check"),
            "on_failures": s.get("on_failures"),
            "water_vpd": s.get("water_vpd"),
            "day_hist": s.get("day_hist") or [],
            "day_acc": s.get("day_acc"),
            "day_out": s.get("day_out") or [],
        }

    def _save_state(self):
        # Preserve undiscovered rooms and unknown metadata/zones. A descriptor going
        # missing must never delete counters or erase a latched shared-hardware hold.
        out = dict(getattr(self, "_saved_room_blocks", {}))
        self._unsaved_rooms = {}  # slug -> the error: what this save could not write (see _loop_room)
        for room in self.rooms:
            try:  # one room's state that cannot be saved must not stop every room's save
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
                waste_rule = getattr(room, "_waste_rule_known", None)
                if waste_rule in ("Off", WASTE_CHECK, WASTE_CLOSE):
                    block["_waste_rule"] = waste_rule
                if room.tank_drawdown["base_pct"] is not None:  # only once a level has been read
                    block["_tank"] = room.tank_drawdown
                estimate = getattr(room, "tank_estimate", None) or {}
                if estimate.get("filled_at"):  # only once the tank has been marked filled
                    block["_tank_estimate"] = estimate
                runoff = getattr(room, "_runoff", None)
                if runoff and runoff_balance.has_data(runoff):  # only once the estimator has recorded something
                    block["_runoff"] = runoff
                else:
                    block.pop("_runoff", None)
                if getattr(room, "_dim", None):
                    block["_dim"] = room._dim
                else:
                    block.pop("_dim", None)
                if getattr(room, "_off_since", None):
                    block["_room_off_since"] = room._off_since.isoformat()
                else:
                    block.pop("_room_off_since", None)
                adherence = plan_adherence.dump(getattr(room, "_adherence", None) or plan_adherence.fresh(), datetime.now().date())
                if adherence:
                    block["_adherence"] = adherence
                else:
                    block.pop("_adherence", None)
                if getattr(room, "_setup_fingerprint_adopted", None):  # else keep whatever was saved
                    block["_setup"] = {
                        "revision": room.setup_revision,
                        "fingerprint": room._setup_fingerprint_adopted,
                    }
                    if getattr(room, "_setup_entry_id", None):  # which room it was (see _is_another_room)
                        block["_setup"]["entry_id"] = room._setup_entry_id
                json.dumps(block)  # what json.dump below would refuse, refused here, for this room only
            except Exception as e:
                log("state save failed", room.slug, e, "- its last saved state is kept")
                self._unsaved_rooms[room.slug] = f"{type(e).__name__}: {e}"
                continue
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
        v, attributes, _ = ha_get(entity)
        try:
            value = float(v) if v not in (None, "unknown", "unavailable", "") else None
        except Exception:
            value = None
        if value is None:
            return float(default)
        self._note_setting(entity, value, attributes)
        return value

    def _zone_num(self, room, zone, suffix, default, optional=False):
        override = parameter_override(
            getattr(room, "strategy_snapshot", None), zone, suffix
        )
        if override is not None:
            return float(override)
        seen = self.__dict__.setdefault("_settings_seen", {})  # entity -> the last value read since start
        per = f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}"
        glob = f"number.crop_steering_{room.prefix}{suffix}"

        def number(state):
            try:
                return float(state)
            except (TypeError, ValueError):
                return None  # missing, unknown, unavailable or not a number: not read

        # One read each, its own state parsed: a second read that failed gave the built-in value as read.
        sizing = suffix in WATER_SIZING
        if sizing:  # whether Home Assistant has the zone's number at all: only a 404 means it has none
            status, (v, attributes, _) = ha_get_status(per)
        else:
            v, attributes, _ = ha_get(per)
        value = number(v)
        if value is not None:
            self._note_setting(per, value, attributes)
            seen[per] = value
            return value
        # The zone has its own number and it reads no number: not the room's value unseen. A setting that sizes
        # the zone's water is unread unless Home Assistant answers it has no such number (the settings wait, then
        # CS-402); any other, answering unavailable or unknown or read earlier in this run, takes the room's
        # value, and CS-402 names the zone's number.
        unread = status != 404 if sizing else v is not None or per in seen
        if unread:
            self._defaulted_this_loop.add(per)
        if not (unread and sizing):
            v, attributes, _ = ha_get(glob)
            value = number(v)
            if value is not None:
                self._note_setting(glob, value, attributes)
                seen[glob] = value
                return value
        # Neither the per-zone NOR the global setpoint entity exists → the engine is silently
        # running its built-in default. On a healthy install the integration creates the global,
        # so this only trips on a real misconfig (renamed/removed entity). Record it so
        # _check_defaulted_setpoints can surface it — EXCEPT engine-only knobs the integration
        # deliberately doesn't create (optional=True): those default by design, never alert.
        if unread and sizing:
            room.__dict__.setdefault("_settings_missing", set()).add(per)
            last = seen.get(per)
            if last is not None:  # the zone's own value, read earlier in this run
                return last
        elif not optional:
            self._defaulted_this_loop.add(glob)
            room.__dict__.setdefault("_settings_missing", set()).add(glob)
            last = seen.get(per, seen.get(glob))
            if last is not None:  # read earlier in this run: a real value, not a guess
                return last
        return None if default is None else float(default)

    def _room_duration_cap(self, room):
        """Read the canonical room cap, or its same-room legacy entity if absent. A read that fails
        (no answer, an HA error) is not "absent": it keeps the cap read earlier this run, or holds.
        `room._cap_seen` is only ever the value the last answered read gave (None after an invalid
        value or a missing entity). Accepted by design: a cap lowered since that read loses to the
        old value if the very next read fails; the read after it applies the new one."""
        for suffix in ("max_shot_duration", "maximum_shot_duration"):
            entity = f"number.crop_steering_{room.prefix}{suffix}"
            status, (raw, _attributes, _updated) = ha_get_status(entity)
            if status == 404:
                room._cap_seen = None
                continue
            if status != 200:
                last = room.__dict__.get("_cap_seen")
                if last is not None:
                    return last
                self._alert(
                    f"duration_config_{room.slug}",
                    "CS-203",
                    "maximum shot length not valid, no shots",
                    "The controller could not read the maximum shot length of the room from Home Assistant, "
                    "and it has read no value since it started, so it starts no shot. The controller does "
                    f"not replace the value with a default.\n\nSetting: {entity}",
                    room=room,
                )
                return None
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = None
            if value is not None and math.isfinite(value) and value >= 5:
                room._cap_seen = value
                self._dismiss(f"duration_config_{room.slug}")
                return value
            room._cap_seen = None
            self._alert(
                f"duration_config_{room.slug}",
                "CS-203",
                "maximum shot length not valid, no shots",
                "The maximum shot length of the room must be a number of 5 s or more. It is not, "
                "so the controller starts no shot. The controller does not replace the value with a default."
                f"\n\nSetting: {entity}",
                room=room,
            )
            return None
        # Keep the existing installation fallback only when neither room entity exists.
        return 900.0

    def _num_or_none(self, entity):
        """Read a number entity as float, or None if it doesn't exist / isn't a number."""
        v, attributes, _ = ha_get(entity)
        try:
            value = float(v) if v not in (None, "unknown", "unavailable", "") else None
        except Exception:
            return None
        if value is not None:
            self._note_setting(entity, value, attributes)
        return value

    def _note_setting(self, entity, value, attributes):
        """A setting read with another value than at its last read: the log says who changed it and
        how. The first read after a start only notes it; the controller's own writes are said where
        they are made (_auto_write)."""
        if not entity.startswith("number.crop_steering_") or not math.isfinite(value):
            return
        now = datetime.now()
        settings = self.__dict__.setdefault("_settings_noted", {})  # entity -> (value, when) last read
        seen = settings.get(entity)
        settings[entity] = (value, now)
        if seen is None or seen[0] == value:
            return
        room, zone, key = self._setting_place(entity)
        unit = str((attributes or {}).get("unit_of_measurement") or "")
        entries = ha_logbook(entity, (seen[1] - timedelta(minutes=1)).astimezone())
        who = log_words.who(entries, value, self._people())
        self._say(room, zone, log_words.change(log_words.setting_name(key), unit, seen[0], value, who))

    def _setting_place(self, entity):
        """The room, zone (None for a room-wide one) and key of a setting's number entity."""
        rest = entity[len("number.crop_steering_"):]
        for room in sorted(getattr(self, "rooms", []), key=lambda r: len(r.prefix), reverse=True):
            if rest.startswith(room.prefix):
                key = rest[len(room.prefix):]
                zoned = re.fullmatch(r"zone_(\d+)_(.+)", key)
                return (room, int(zoned[1]), zoned[2]) if zoned else (room, None, key)
        return None, None, rest

    def _people(self):
        """Each Home Assistant user's person name ({user id: "Sam"}), read again at most every ten
        minutes: only a setting change asks."""
        read, people = getattr(self, "_people_cache", (0.0, {}))
        if not read or time.monotonic() - read > 600:
            people = {
                s["attributes"]["user_id"]: s["attributes"].get("friendly_name") or s["entity_id"][7:]
                for s in ha_get_all()
                if str(s.get("entity_id", "")).startswith("person.")
                and (s.get("attributes") or {}).get("user_id")
            }
            self._people_cache = (time.monotonic(), people)
        return people

    @staticmethod
    def _say(room, zone, text):
        """One line of the log about a room, or one of its zones, tagged as the log tags them."""
        tag = "" if room is None else f"[{room.slug}] " + ("" if zone is None else f"Z{zone} ")
        log(f"{tag}{text}")

    def _detect_zones(self, prefix, fallback):
        """Count zones from the integration's fused VWC sensors. Returns the number of
        consecutive fused VWC sensors that exist under EITHER naming convention —
        sensor.crop_steering_<prefix>vwc_zone_N (current) or the registry-sticky legacy
        sensor.crop_steering_<prefix>zone_N_vwc — or `fallback` if none do (e.g. HA not
        reachable yet at startup). One read of every state: a read that failed part-way counted too few."""
        have = {s.get("entity_id") for s in ha_get_all() if isinstance(s, dict)}
        n = 0
        while n < 24 and {f"sensor.crop_steering_{prefix}vwc_zone_{n + 1}",
                          f"sensor.crop_steering_{prefix}zone_{n + 1}_vwc"} & have:
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

    def _recipe_feed_ec(self, room):
        """The feed EC (mS/cm) the feed recipe in use today declares, as the integration publishes it on
        sensor.crop_steering_<prefix>dosing_config (`feed.ec`), or None: no dosing setup, no feed recipe
        in use, none declared, or not a number in 0.1-10. Declared, never measured: it stands in only
        where no feed EC probe reads, and the source-water gate never runs on it."""
        feed = ha_get(f"sensor.crop_steering_{room.prefix}dosing_config")[1].get("feed")
        try:
            ec = float(feed.get("ec"))
        except (AttributeError, TypeError, ValueError):
            return None
        return ec if 0.1 <= ec <= 10 else None

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
                    "lights hours come from the integration",
                    f"The controller uses lights-on at {int(lon)}:00 and lights-off at {int(loff)}:00 from "
                    "the integration. The option of the controller still says "
                    f"{int(room.opt_lon)}:00-{int(room.opt_loff)}:00. The controller uses the option only "
                    "when it cannot read the hours of the integration and has not read them since it "
                    "started. Set the option to the same hours, so that it cannot move lights-on. If the "
                    "hours of the integration are wrong, change its Lights on hour and Lights off hour."
                    "\n\nSettings: number.crop_steering_lights_on_hour, number.crop_steering_lights_off_hour",
                    room=room,
                )
            room._lights_logged = True
        room.lights_on_hour, room.lights_off_hour = float(lon), float(loff)
        room._lights_source = src

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
        learn = room.state[zone].get("learn")
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
            # after a stalled ramp the day re-waters the zone's usual P2 drop under what it reached
            p1_stall_band=auto_setpoints.p2_band(learn if isinstance(learn, dict) else {},
                                                 self._zone_num(room, zone, "p2_shot_size", FALLBACK["p2_shot_size"])),
            dryback_target=self._zone_num(
                room,
                zone,
                f"{'vegetative' if veg else 'generative'}_dryback_target",
                FALLBACK[f"{'vegetative' if veg else 'generative'}_dryback_target"],
            ),
            p0_max_wait_min=self._zone_num(room, zone, "p0_maximum_wait_time", FALLBACK["p0_maximum_wait_time"]),
            # Opt-in phase settings (phase_options). Optional: an integration older than them has none, and each
            # fallback is the rule as it was.
            p0_min_wait_min=self._zone_num(
                room, zone, "p0_minimum_wait", FALLBACK["p0_minimum_wait"], optional=True
            ),
            p0_stall_exit=self._on(f"switch.crop_steering_{room.prefix}p0_stall_exit", False),
            ec_flush_target=self._zone_num(room, zone, "ec_flush_target", FALLBACK["ec_flush_target"], optional=True),
            # The zone's own P2 dilute ratio only behind the room's switch (never the room's p2_ec_high_threshold,
            # editable and unread for months: reading it unasked would change watering on update).
            p2_dilute_ratio=(
                self._zone_num(room, zone, "p2_dilute_ratio", FALLBACK["p2_dilute_ratio"], optional=True)
                if self._on(f"switch.crop_steering_{room.prefix}use_p2_ec_thresholds", False)
                else FALLBACK["p2_dilute_ratio"]
            ),
            p2_mode=phase_options.p2_mode(ha_get(f"select.crop_steering_{room.prefix}zone_{zone}_p2_mode")[0]),
            p2_timed_interval_min=self._zone_num(
                room, zone, "p2_timed_interval_min", FALLBACK["p2_timed_interval_min"], optional=True
            ),
            p2_timed_shot_size=self._zone_num(
                room, zone, "p2_timed_shot_size", FALLBACK["p2_timed_shot_size"], optional=True
            ),
            p2_timed_first_h=self._zone_num(
                room, zone, "p2_timed_first_hours", FALLBACK["p2_timed_first_hours"], optional=True
            ),
            p2_end_h_before_off=self._zone_num(
                room, zone, "p2_end_hours_before_off", FALLBACK["p2_end_hours_before_off"], optional=True
            ),
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
                "setting outside the controller range",
                "A setting is outside the range of the controller, so the controller uses the nearest "
                "permitted value. The entity accepts a wider range than the controller. Set the value "
                "inside the range that the detail shows. If the detail compares two settings (a minimum "
                "above its maximum), change one of them. The controller calculates the minimum daily "
                f"volume from the mL for each plant and the plant count.\n\nDetail: {w}",
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
                        "zone EC from bulk EC: no pore EC probe reports",
                        "This zone has pore EC probes and bulk EC probes. The integration never mixes "
                        "the two. No pore EC probe reports, so the zone EC comes from its bulk EC "
                        "probes. Bulk EC reads lower than pore EC in the same slab. The EC targets, "
                        "EC stacking and flushes use this lower value until a pore EC probe "
                        "reports again. Check the pore EC probes in the list below."
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
                    f"The {what} of this zone steers on its {chosen.lower()} probe. This method needs "
                    f"3 probes that agree. Fewer probes agree, so the zone steers on their {steered.lower()}, "
                    "and the shots continue. Check the probes that the reading does not use, for example "
                    "a probe out of its cube or in a puddle. Alternatively, set the zone to Median."
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
            f"The primary {what} probe of this zone "
            f"{'gives no reading' if why == 'no reading' else 'stopped its reports'}. The zone reading "
            "comes from its other probes, and the shots continue. Check the cable, the power and the "
            "Home Assistant device of the probe. Alternatively, choose a different primary probe under "
            f"Probes for the zone. This alert comes once. It clears when the probe reports again.\n\nSensor: {looking}\n"
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
        if feed_ec is None:  # measured first, then the feed recipe's declared EC, then 3.0
            feed_ec = self._recipe_feed_ec(room)
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
            # ...and the ramp shots before the last one that did not rise, unless the probe is in doubt (core.p1_stall)
            p1_flat_shots=int(st.get("p1_flat") or 0),
            p1_probe_suspect=self._p1_probe_suspect(room, zone, st, now) is not None,
            ec_flushing=bool(st.get("ec_flushing")),
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

    def _p1_probe_suspect(self, room, zone, st, now):
        """Why this zone's probe is in doubt for the P1 stall exit (core.p1_stall), or None: water bypassing it
        (CS-710 raised for the zone in the last 6 h), or a reading that has not moved at all since the last shot.
        A table not draining (CS-310) the engine sees itself (ZoneSnapshot.backed_up)."""
        raised = getattr(self, "_alerted", {}).get(f"jev_channel_{room.slug}_z{zone}")
        if isinstance(raised, datetime) and (now - raised).total_seconds() < 6 * 3600:
            return "water may bypass the substrate or the probe (CS-710)"
        last = st.get("last_shot")
        since = [v for t, v in st.get("win") or [] if isinstance(last, datetime) and t > last]
        if len(since) >= 5 and max(since) == min(since):
            return f"the reading has not moved since the last shot ({since[0]:g})"
        return None

    def _p1_stall_today(self, room, st, now):
        """This grow-day's stalled ramp ({"day", "at", "rewater"}), or None: one from another grow-day is over."""
        stall = st.get("p1_stall")
        if isinstance(stall, dict) and stall.get("day") == self._grow_day_start(room, now).isoformat():
            return stall
        return None

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
        and never one that the AI assistant's Setpoints judge owns."""
        st = room.state[zone]
        if not isinstance(st.get("learn"), dict):
            st["learn"] = auto_setpoints.fresh()
        learn = st["learn"]
        st["last_vwc"] = snap.vwc
        auto_setpoints.new_day(learn, self._grow_day_start(room, now).isoformat(), snap.vwc)
        auto_setpoints.tick(learn, snap.vwc, st["phase"], now.timestamp(), lights_on,
                            snap.dryback_rate, self._minutes_since_shot(st, now))
        enabled = self._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)
        planned = bool(getattr(room, "strategy_required", False))
        # Each lever has one writer. With the AI assistant's Setpoints judge running, the P2 shot size and re-water threshold
        # are its own (brain_bridge) and this learner writes the rest. Writing nothing at all under the judge left
        # nobody on the P1 target: zone 2 sat at 29.5 under a probe reading 44 % and never ramped (4 Oct 2026).
        judged = brain_bridge.judge_levers(self, room)
        # With the room's set_targets_from_achievable power on and the brain able to act, the AI assistant sets the
        # peak target, field capacity, re-water threshold and rescue floor itself: the learner's ladder (and the
        # follower of the highest readings) steps aside for them, and comes back when the power is off.
        owned = brain_bridge.targets_owned(self, room)
        if owned != room.__dict__.setdefault("_targets_owned", {}).get(zone, False):
            room._targets_owned[zone] = owned
            log(f"[{room.slug}] Z{zone} " + ("the AI assistant sets the peak target, field capacity and re-water "
                                            "threshold itself (the owner's power): the learner's ladder steps aside"
                                            if owned else "the learner's ladder is back on the peak target, field "
                                            "capacity and re-water threshold"))
        writes = enabled and not planned
        stall = None
        note = stop = None  # today's plan: what the dryback gets, and when maintenance shots stop for it
        was = learn["outcome"]
        outcome = auto_setpoints.ramp_outcome(learn, st["phase"])
        if outcome != was:
            log(f"[{room.slug}] Z{zone} P1 ramp outcome: {outcome} (peak {learn['peak']})")
            if outcome == "suspect":
                self._alert(f"auto_{room.slug}_z{zone}", "CS-404", "automatic targets paused",
                            "The controller paused the automatic changes to the targets of this zone, "
                            f"because the ramp of this morning was not correct: {auto_setpoints.frozen_reason(learn)}. "
                            "The shots continue with the current targets. The controller examines the "
                            "ramp again the next morning.",
                            room=room, zone=zone)
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
            if owned:
                pass  # the AI assistant owns the ladder (brain_bridge.targets_owned): the learner writes none of it
            elif self._follow_fc(room, zone, p, now):
                pass  # the setpoints moved with the zone's highest readings; the learner acts on the next pass
            else:
                want = auto_setpoints.wanted(learn, current, snap.vwc, st["phase"], ctx, others=judged)
                for suffix in ("p1_target_vwc", "field_capacity"):  # the zone's highest readings set these
                    want.pop(suffix, None)
                stall = auto_setpoints.stalled(current, want)
                for suffix, value, _why in setpoint_supervisor.writes(current, want):
                    value = self._step_bounded(room, zone, suffix, current[suffix], value, now)
                    if value is None:
                        continue
                    wrote = self._auto_write(room, zone, suffix, current[suffix], value, learn, now)
                    if wrote:
                        self._step_count(room, zone, suffix, current[suffix], value, now)
                    if (wrote
                            and suffix in ("p2_shot_size", "p2_vwc_threshold") and brain_bridge.owns_setpoints(self)):
                        # the learner holds the judge's lever while the brain cannot act: not an edit by hand
                        brain_bridge.learner_wrote(self, room, zone, suffix, current[suffix], value, now)
        state, attrs = auto_setpoints.status(learn, enabled, stall, note, stop)
        if enabled and planned:
            state, attrs["frozen_reason"] = "frozen", "an armed grow plan owns this room's targets"
        who = dict.fromkeys(auto_setpoints.MANAGED, "Auto setpoints learner")
        who["p1_target_vwc"] = "the zone's highest reading of the grow-day before"
        who["field_capacity"] = "the zone's highest reading of this grow-day or the one before"
        who.update(dict.fromkeys(judged, "the AI assistant's Setpoints judge, one notch a night"))
        if owned:  # the owner's power: the AI assistant sets the ladder and the rescue floor itself
            who.update(dict.fromkeys(("p1_target_vwc", "field_capacity", "p2_vwc_threshold",
                                      "p3_emergency_vwc_threshold"), "the AI assistant, with the owner's power"))
        number = f"number.crop_steering_{room.prefix}zone_{zone}_"
        attrs.update(
            # the hourly P2 check is retired: its keys stay for one release, for dashboards that read them; its saved
            # last answer and change are not shown, as nothing clears them at lights-on any more
            jev="disabled", jev_last=None, jev_changed_today=None,
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

    # ---------- grow-day summaries (day_summary): read-only, never a reason to water or not ----------
    def _recording_days(self, room, now):
        """The room's Record grow days switch, read once a pass (off when it cannot be read)."""
        seen = room.__dict__.get("_record_days")
        if seen is None or seen[0] != now:
            seen = room._record_days = (now, self._on(f"switch.crop_steering_{room.prefix}record_grow_days", False))
        return seen[1]

    def _observe_grow_day(self, room, zone, st, snap, now):
        try:
            if not self._recording_days(room, now):
                day_summary.stop(st)
                return
            if snap is None:
                return
            day = self._grow_day_start(room, now).isoformat()
            stall = st.get("p1_stall")

            def recent(at):
                return isinstance(at, datetime) and (now - at).total_seconds() < 600

            day_summary.observe(
                st, day=day, now=now, vwc=snap.vwc, ec=snap.ec,
                feed_ec=getattr(room, "_feed_last_good_value", None)
                if recent(getattr(room, "_feed_last_good_time", None)) else None,
                feed_ph=getattr(room, "_feed_ph_last_good", None)
                if recent(getattr(room, "_feed_ph_last_good_time", None)) else None,
                stalled=isinstance(stall, dict) and stall.get("day") == day)
        except Exception as e:  # a record never stops the room being decided and watered
            log("grow-day summary error", room.slug, zone, e)

    def _grow_day_shot(self, room, zone, kind, litres, now):
        try:
            if litres > 0 and self._recording_days(room, now):
                day_summary.shot(room.state[zone], day=self._grow_day_start(room, now).isoformat(), now=now,
                                 kind=kind, litres=litres)
        except Exception as e:
            log("grow-day summary error", room.slug, zone, e)

    def _close_grow_day(self, room, zone, st, now, p=None):
        """Lights-on: the grow-day that ended, summarised and queued for Home Assistant (_send_grow_days)."""
        try:
            if not st.get("day_acc"):
                return
            if not self._recording_days(room, now):
                day_summary.stop(st)
                return
            ended = st.get("last_daily_reset")
            day = ended.isoformat() if isinstance(ended, date) else st["day_acc"]["day"]
            targets = {k: getattr(p, k, None) for k in ("p1_target", "field_capacity", "p2_threshold", "dryback_target",
                                                        "p3_emergency_floor", "max_daily_volume", "ec_target_p2")}
            info = {
                "zone": zone,
                "lights": {"on": room.lights_on_hour, "off": room.lights_off_hour},
                "plant_count": self._zone_num(room, zone, "plant_count", FALLBACK["plant_count"]),
                "mode": "Vegetative" if self._veg(room, zone) else "Generative",
                "targets": {k: v for k, v in targets.items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)},
                "litres": st.get("daily_vol"),
                "plan_day": (getattr(room, "strategy_snapshot", None) or {}).get("grow_day"),
                "day_start": datetime.combine(date.fromisoformat(day), datetime.min.time())
                + timedelta(hours=room.lights_on_hour),
            }
            summary = day_summary.close(st, day=day, now=now, info=info)
            if summary is not None:
                room._grow_days_due = True
                log(f"[{room.slug}] Z{zone} grow-day {day} summarised: {summary['litres']:g} L, "
                    f"{sum(summary['shots'].values())} shot(s)" + (" (partial)" if summary["partial"] else ""))
        except Exception as e:
            log("grow-day summary error", room.slug, zone, e)

    def _sample_probes(self, room, now):
        """Every probe behind each zone, read in one request every GROW_DAY_PROBE_S, for the summaries."""
        last = room.__dict__.get("_probes_sampled")
        if last is not None and (now - last).total_seconds() < GROW_DAY_PROBE_S:
            return
        room._probes_sampled = now
        states = {s.get("entity_id"): s for s in ha_get_all() if isinstance(s, dict)}
        day = self._grow_day_start(room, now).isoformat()
        for zone in room.zones if states else ():
            rows = []
            for kind in ("vwc", "ec"):
                fused = states.get(self._fused_id(room.prefix, kind, zone, room.zones[zone].get(kind))) or {}
                attrs = fused.get("attributes") or {}
                used = [x for x in attrs.get("used") or [] if isinstance(x, str)]
                aside = attrs.get("excluded") if isinstance(attrs.get("excluded"), dict) else {}
                for pid in used + [x for x in aside if isinstance(x, str) and x not in used]:
                    probe = states.get(pid) or {}
                    pa = probe.get("attributes") or {}
                    try:
                        value = float(probe.get("state"))
                    except (TypeError, ValueError):
                        value = None
                    rows.append((kind, pid, pa.get("row_label") or pa.get("friendly_name"), pa.get("unit_of_measurement"), value, pid in used))
            if rows:
                day_summary.probes(room.state[zone], day=day, now=now, readings=rows)

    def _send_grow_days(self, room, now):
        """The summaries not yet taken, sent in one call (crop_steering.grow_day_record): at lights-on, else
        every GROW_DAY_PROBE_S while any wait. An integration without the service keeps them waiting, the
        newest day_summary.KEEP grow-days, and the log says so once."""
        try:
            if self._recording_days(room, now):
                self._sample_probes(room, now)
            pending = {z: list(room.state[z].get("day_out") or []) for z in room.zones}
            days = [s for rows in pending.values() for s in rows]
            if not days:
                return
            last = room.__dict__.get("_grow_days_tried")
            due = room.__dict__.pop("_grow_days_due", False)
            if not due and last is not None and (now - last).total_seconds() < GROW_DAY_PROBE_S:
                return
            room._grow_days_tried = now
            status, _answer = ha_service_response(
                "crop_steering", "grow_day_record", {"room_id": f"room:{room.prefix}", "days": days})
            if status is not None and 200 <= status < 300:
                for z, rows in pending.items():
                    day_summary.taken(room.state[z], [s.get("date") for s in rows])
                self._save_state()
                room._grow_days_refused = False
                log(f"[{room.slug}] {len(days)} grow-day summary(ies) recorded in Home Assistant")
            elif not room.__dict__.get("_grow_days_refused"):
                room._grow_days_refused = True
                log(f"[{room.slug}] Home Assistant did not take the grow-day summaries (HTTP {status}): kept, the "
                    f"newest {day_summary.KEEP} grow-days, and sent again later. An integration older than this "
                    "controller has no grow-day store: update it.")
        except Exception as e:
            log("grow-day summary error", room.slug, e)

    def _follow_fc(self, room, zone, p, now):
        """The zone's setpoints follow its own highest readings -> True when anything was written.

        The rule (adopted 6 Oct 2026): the P1 target is the highest reading the zone reached the day before, field
        capacity rises as the probe's readings do, and the P2 dryback and the rescue floor move with field capacity,
        all without the operator having to do it. So:
          - field capacity = the highest reading of this grow-day or the one before (_vwc_maxima);
          - the P1 target = the highest reading of the grow-day before;
          - when field capacity moves by FC_SHIFT_MIN or more, the P2 re-water threshold moves by the same points, so
            the dryback under full keeps its size. The AI assistant's Setpoints judge takes a moved threshold as the new centre of
            its range (brain_bridge).
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
        limit = self._step_limit(room)
        phase_options.step_left(follow, day, "field_capacity", limit)  # a new grow-day starts the ledger afresh
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
            left = max(0.0, limit - used.get(suffix, 0.0))  # what is left of this grow-day's step
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
                if suffix == "p2_vwc_threshold" and brain_bridge.owns_setpoints(self):
                    try:  # the judge's range follows field capacity while the learner holds its levers
                        brain_bridge.fc_moved(self, room, zone, old, value, now)
                    except Exception as e:
                        log("brain fc error", room.slug, zone, e)
        if wrote:
            self._save_state()
        return wrote

    def _step_limit(self, room):
        """The room's Max setpoint move per day, in VWC points (inf: no limit); FC_STEP_MAX when it cannot be read
        (an integration older than the setting)."""
        value = self._num_or_none(f"number.crop_steering_{room.prefix}setpoint_max_step_per_day")
        return phase_options.step_limit(value, FC_STEP_MAX)

    def _step_limit_all(self, room):
        """True when the room's daily limit also holds the AI assistant's targets power and the learner (the select's
        second option). A missing select, as on an older integration, is the follower only, as before."""
        state = ha_get(f"select.crop_steering_{room.prefix}setpoint_step_limit_applies_to")[0]
        return state == phase_options.STEP_SCOPE_ALL

    def _step_allowance(self, room, zone, suffix, now):
        """What is left of today's allowance for a ladder setpoint when the room's limit holds the learner and the AI
        assistant too (the follower's ledger, shared), or None when it does not apply to `suffix` or to them."""
        if suffix not in FC_LADDER or not self._step_limit_all(room):
            return None
        return phase_options.step_left(room.state[zone]["fc_follow"], self._grow_day_start(room, now).isoformat(),
                                       suffix, self._step_limit(room))

    def _step_bounded(self, room, zone, suffix, old, value, now):
        """A learner write of a ladder setpoint inside what is left of today's allowance (_step_allowance); None when
        nothing is left. Any other setpoint, or the limit holding the follower only, is returned as it came."""
        left = None if old is None else self._step_allowance(room, zone, suffix, now)
        if left is None:
            return value
        bounded = phase_options.clamp_step(float(old), float(value), left)
        return None if abs(bounded - float(old)) < 0.05 else bounded

    def _step_count(self, room, zone, suffix, old, value, now):
        """A written ladder move, counted on today's ledger when the room's limit holds the learner and the AI too."""
        if self._step_allowance(room, zone, suffix, now) is not None:
            phase_options.step_used(room.state[zone]["fc_follow"], suffix, float(value) - float(old))

    def _flush_episode(self, room, zone, st, snap, p, fire, reason):
        """Latch or clear the zone's EC flush episode (core: ZoneSnapshot.ec_flushing) after this pass's decision."""
        was = bool(st.get("ec_flushing"))
        now_on = phase_options.flushing(was, p.ec_flush_target, getattr(reason, "kind", None) if fire else None,
                                        snap.ec_settled, ec_flush_goal(snap, p))
        if now_on != was:
            st["ec_flushing"] = now_on
            log(f"[{room.slug}] Z{zone} EC flush " + (f"to {ec_flush_goal(snap, p):.1f} started" if now_on
                                                       else "episode ended"))
            self._save_state()

    def _zone_bounded(self, room, zone, suffix, value):
        """`value` inside the engine's bounds for `suffix` and the zone number's own min and max (which Home
        Assistant enforces), rounded to 0.1."""
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
        return round(max(lo, min(hi, value)), 1)

    def _number_range(self, room, zone, suffix):
        """(lowest, highest) a zone's own number takes: the engine's bounds for it, inside the entity's own min and
        max (Home Assistant refuses a write outside them). The only limit on an AI assistant power's values."""
        lo, hi = setpoint_supervisor.BOUNDS.get(suffix, (float("-inf"), float("inf")))
        attrs = ha_get(f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}")[1] or {}
        try:
            lo = max(lo, float(attrs["min"]))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            hi = min(hi, float(attrs["max"]))
        except (KeyError, TypeError, ValueError):
            pass
        return float(lo), float(hi)

    def _auto_write(self, room, zone, suffix, old, value, learn, now, by="auto", reason=None, expected=None):
        """Write one per-zone number -> False when it was not written (no such number, or Home Assistant refused).
        `reason` and `expected`: why, and the result expected, for the room's setpoint change log (an AI assistant
        power's write names both)."""
        entity = f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}"
        if ha_get(entity)[0] in (None, "unknown", "unavailable", ""):
            return False  # no per-zone number on this install: room-level values are the operator's, never ours
        written = room.__dict__.setdefault("_auto_written", {})
        last = written.get((zone, suffix))
        if last and last[0] == value and (now - last[1]).total_seconds() < 300:
            return True  # HA has not reflected the last write yet: do not spam it
        # Home Assistant sees only this app's token: name the writer first, for the room's setpoint
        # change log (the integration's setpoint_log.py). The brain's put-back is the safety writer.
        who = ("safety" if by.endswith("(put back)") else "brain" if by.startswith(("Jev", "AI "))
               else "learner")
        claim = {"entity_id": entity, "value": value, "who": who, "claim_id": uuid.uuid4().hex}
        if reason:
            claim["reason"] = str(reason)[:200]
        if expected:
            claim["expected"] = str(expected)[:200]
        if by.startswith(("Jev", "AI setpoints judge")) and who == "brain":
            # An AI change is an overlay that goes back by itself (the integration's overlays.py): at the
            # lights-on that ends the grow-day it is for. A night move (P3) is for the next grow-day.
            local = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
            day = self._grow_day_start(room, local) + timedelta(days=2 if room.state[zone].get("phase") == "P3" else 1)
            on = datetime.combine(day, datetime.min.time()) + timedelta(hours=room.lights_on_hour)
            claim["expires"] = on.astimezone().isoformat(timespec="seconds")
        ha_fire("crop_steering_setpoint_write", claim)
        if not ha_call("number", "set_value", entity_id=entity, value=value):
            # Not written: take the claim back, or the operator writing this value next is taken for us.
            ha_fire("crop_steering_setpoint_claim_cancel", {k: claim[k] for k in ("entity_id", "value", "who", "claim_id")})
            return False
        written[(zone, suffix)] = (value, now)
        self.__dict__.setdefault("_settings_noted", {})[entity] = (value, now)  # said here, not again
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
        # A snapshot: dismissing changes the dict (dosing_runner.py raises into it too). A dosing alert
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

    def _heartbeat(self, room, now, hardware_fault, room_active=True, loop_error=None, timeout=None):
        room._beat, room._beat_at = (hardware_fault, room_active, loop_error), time.monotonic()
        ha_set(
            f"sensor.crop_steering_{room.prefix}ai_heartbeat",
            "error" if loop_error else "healthy",
            {
                **({"loop_error": loop_error} if loop_error else {}),  # the room's pass raised (_room_error)
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
                # the plan day whose targets are in force, a plan-day catch-up's included (plan_task)
                "plan_day_in_force": ((getattr(room, "strategy_snapshot", None) or {}).get("bridged")
                                      or (getattr(room, "strategy_snapshot", None) or {}).get("grow_day")),
                "plan_bridged": bool((getattr(room, "strategy_snapshot", None) or {}).get("bridged")),
                "setup_revision": getattr(room, "setup_revision", 0),
                "setup_active": getattr(room, "setup_active", True),
                "setup_pending": getattr(room, "_setup_pending", None),
                "room_active": room_active,
                "max_run": self._max_run_report(room),
                "write_failures": _SET_FAILED["count"],  # state writes that failed since the start (ha_set)
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
    def _publish_waiting_for(room, zone, snap, p, now, gates=None):
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
                # every pre-shot gate with pass or hold (gate_report.py), for the zone page's list
                **({"gates": gates} if gates is not None else {}),
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
                "plumbing and switches do not agree, no shots",
                "The plumbing of the room setup and the switches mapped to it do not agree. "
                "The room gets no shots until they agree. The detail below tells what to change "
                "in Rooms & setup."
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
                "a valve or pump the controller cannot switch, no shots",
                "The zone valve, the pump or the main-line valve has a device type that the controller "
                "cannot open or close. The controller sends it no command, and the zone gets no shots. "
                "In Rooms & setup, map a switch, an input_boolean or a valve in its place."
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
        # running still ends only on a definite ON (_wait_shot). One Home Assistant answers it does
        # not have (404, a typo or a deleted helper) says so: no wait makes that one readable.
        for f in self.hold_entities:
            state = ha_get(f)[0]
            if state is None and ha_get_status(f)[0] == 404:
                return hold_missing(f)
            if state in (None, "unknown", "unavailable", ""):
                return f"external hold {f} unreadable (reads neither on nor off)"
            if str(state).lower() in ON_STATES:
                return f"external hold ({f.split('.')[-1]})"
        waste = self._waste_hold(room)
        if waste:
            return waste
        settings = self._settings_hold(room, zone)
        if settings:
            return settings
        tank = self._tank_hold(room)  # only with a tank level mapped: never on an upgraded room until then
        if tank:
            return tank
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
                    ) and not self._rescue_past_dead_probe(room, zone, reason, "EC"):
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
                    ) and not self._rescue_past_dead_probe(room, zone, reason, "pH"):
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

    def _rescue_past_dead_probe(self, room, zone, reason, half):
        """True when a rescue may pass the source-water gate although its feed probe is dead: only while the room's
        switch rescue_past_dead_feed_probe reads ON, and only for a P3 emergency or a watchdog shot. Off (or
        unreadable), and for every other shot, the dead probe holds as it always did. An out-of-band reading is
        never passed, and nothing before the gate (kill switch, holds, dosing, tank minimum, faults) is skipped."""
        if getattr(reason, "kind", None) not in safety_ops.RESCUE_KINDS:
            return False
        if not self._on(f"switch.crop_steering_{room.prefix}rescue_past_dead_feed_probe", False):
            return False
        log(f"[{room.slug}] Z{zone} source-water {half} probe dead: a {reason.kind} rescue passes the gate "
            "(Rescues past a dead feed probe is on)")
        return True

    def _waste_rule(self, room):
        """The room's waste-valve rule: Off (the controller never reads it, as before), WASTE_CHECK or WASTE_CLOSE.
        No mapped waste valve or a confirmed absent legacy select keeps the old Off behavior. A transient
        unreadable/invalid policy is a hold, never permission to ignore an enabled interlock."""
        if not getattr(room, "waste", ""):
            return "Off"
        entity = f"select.crop_steering_{room.prefix}waste_valve_rule"
        state = ha_get(entity)[0]
        if state in ("Off", WASTE_CHECK, WASTE_CLOSE):
            room._waste_rule_known = state
            return state
        if state is None and ha_get_status(entity)[0] == 404 and not getattr(room, "_waste_rule_known", None):
            return "Off"
        return "Unreadable"

    def _waste_hold(self, room):
        """Why the waste valve holds the room's shots, else None (CS-316). Check closed: it must read OFF. Close for
        each shot: it must be a switch the controller can close and read (it is closed at the shot's start)."""
        rule = self._waste_rule(room)
        if rule == "Off":
            return None
        waste = room.waste
        state = str(hw_get(waste)[0]).lower()
        if rule == WASTE_CLOSE and waste.split(".", 1)[0] in ACTUATORS and state in ("on", "off"):
            self._dismiss(f"waste_{room.slug}")
            return None
        if rule == WASTE_CHECK and state == "off":
            self._dismiss(f"waste_{room.slug}")
            return None
        why = (f"waste valve {waste} reads {state}" if state in ("on", "off")
               else f"waste valve {waste} offline (reads neither on nor off)")
        if rule == "Unreadable":
            why = "waste valve rule unreadable (no shot until its policy can be confirmed)"
        if rule == WASTE_CLOSE and waste.split(".", 1)[0] not in ACTUATORS:
            why = f"waste valve {waste} can't be switched by the controller"
        self._alert(
            f"waste_{room.slug}",
            "CS-316",
            "the waste valve is not closed, no shots",
            "The waste valve rule of this room says that the waste valve must be closed for a shot. "
            + ("It does not read off, so the feed would go to waste while the controller counts it as given. "
               if rule == WASTE_CHECK else
               "The controller closes it before each shot, but it cannot switch it or read it now. ")
            + "No shot starts until it reads off. Check the waste valve and its switch, or change the waste "
            f"valve rule in the room settings.\n\nDetail: {why}.",
            room=room,
        )
        return why

    def _close_waste(self, room, zone):
        """Close for each shot: switch the waste valve OFF before anything opens, read back. False (and CS-316) when
        it will not read OFF: the shot does not start. Never opened again by the controller."""
        rule = self._waste_rule(room)
        if rule == "Off":
            return True
        if rule != WASTE_CLOSE:
            return self._waste_hold(room) is None if rule == WASTE_CHECK else False
        waste = room.waste
        if hw_get(waste)[0] == "off":
            return True
        hw_call(waste, False)
        if self._confirm_switches((waste,), "off"):
            log(f"[{room.slug}] Z{zone} waste valve {waste} closed for the shot")
            return True
        self._alert(
            f"waste_{room.slug}",
            "CS-316",
            "the waste valve is not closed, no shots",
            "The controller set the waste valve to off before a shot, but it did not read off. The shot did not "
            "start, so no feed went to waste. Check the waste valve and its switch."
            f"\n\nDetail: waste valve {waste} still reads {hw_get(waste)[0]}.",
            room=room,
            zone=zone,
        )
        return False

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
    def _zone_cultivars(attrs):
        """The cultivar label of each zone that has one ({2: "Gelato"}), from the room's descriptor. An older
        integration publishes none."""
        labels = (attrs or {}).get("zone_cultivars")
        found = {}
        for key, label in (labels.items() if isinstance(labels, dict) else ()):
            try:
                zone = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(label, str) and label.strip():
                found[zone] = label.strip()[:40]
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
                f"{name} is off, so the kill switch is off",
                f"{name} is retired. The kill switch of the room ({room_gate(room)}) now stops the "
                f"water. {name} ({entity}) is off, so the controller set the kill switch to off. The "
                f"controller does this again while {name} stays off. Set {name} to on in Home Assistant. "
                "Then set Watering to on in Crop Steering → Settings → Watering.",
                room=room,
            )
        return off

    def _alert(self, key, code, title, message, room=None, zone=None, quiet=True):
        """Raise notification `f2_{key}` with its error code (docs/error-codes.json; the dashboard's
        Help & tools lists the same catalog). The key, and so the notification id, never changes
        with the wording: an update replaces an old notification instead of adding a second one.
        True once Home Assistant has it; False while it is inside its quiet period (`quiet`: for a
        condition re-checked every loop) or could not be created."""
        if room is not None and zone is not None and zone in getattr(room, "state", {}):
            day_summary.alert(room.state[zone], code)  # the code, for the zone's grow-day summary
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
        if push and self._muted(room, code):
            log("ALERT push held:", key, "its room is muted in Crop Steering")
            push = False
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

    def _route(self, key, code, event, room, zone, title, message, urgent=False, timeout=NOTIFY_TIMEOUT_S,
               overlays=None):
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
        if overlays:  # the AI's settings this push is about: Keep and Undo on the phone (the integration's overlays.py)
            data["overlays"] = overlays
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
        """(recipients, idle_hours) from the integration's sensor.crop_steering_notify_config, and the rooms muted
        in it into _notify_mutes (_muted): read by each loop at
        most once a minute (`refresh`), and otherwise the last reading, so an alert never waits on the read. An
        integration without it (older than notifications) or unable to read its store: (0, 3.0), so every push
        goes to the notify_service option exactly as before and CS-209 counts 3 hours."""
        now = time.monotonic()
        cached = getattr(self, "_notify_cfg", None)
        if cached is not None and (not refresh or 0 <= now - cached[0] < NOTIFY_CONFIG_S):
            return cached[1]
        attrs = ha_get(NOTIFY_CONFIG)[1]
        attrs = attrs if isinstance(attrs, dict) else {}
        # An integration that puts Keep and Undo on a push about the AI's settings says so; an older one would
        # refuse the push that names them.
        self._notify_overlays = attrs.get("overlay_actions") is True
        try:
            recipients = max(0, int(attrs.get("recipients") or 0))
        except (TypeError, ValueError):
            recipients = 0
        try:
            idle = float(attrs.get("idle_hours"))
        except (TypeError, ValueError):
            idle = IDLE_HOURS
        idle = min(IDLE_HOURS_RANGE[1], max(IDLE_HOURS_RANGE[0], idle)) if math.isfinite(idle) else IDLE_HOURS
        mutes = {}  # room prefix -> until; an integration from before mutes has none
        for prefix, until in (attrs.get("muted") if isinstance(attrs.get("muted"), dict) else {}).items():
            try:
                until = datetime.fromisoformat(until)
            except (TypeError, ValueError):
                continue
            if until.tzinfo is not None:
                mutes[prefix] = until
        self._notify_mutes = mutes
        self._notify_cfg = (now, (recipients, idle))
        return recipients, idle

    def _muted(self, room, code):
        """Whether an alert's push stays with nobody because its room is muted until a later time (the
        integration's sensor.crop_steering_notify_config `muted`, as last read): never a critical code, nor an
        alert about no room in particular. Covers the notify_service fallback too."""
        if room is None or code in CRITICAL_CODES:
            return False
        self._notify_config()  # the last reading, or the first
        until = self._notify_mutes.get(room.prefix)
        return until is not None and until > datetime.now(timezone.utc)

    def _notify_event(self, event, room, zone, *detail):
        """A phase change ("phase": was, to, why) or a setting the AI assistant moved ("jev_setpoint": words, why[, the number's
        entity id when it was written, for Keep and Undo on the phone]): not an
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
                overlays = [d[2] for _z, d in items if event == "jev_setpoint" and len(d) > 2]
                self._route(key, None, event, room, zone, title, message, timeout=min(NOTIFY_TIMEOUT_S, left),
                            overlays=overlays if getattr(self, "_notify_overlays", False) else None)
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
                words, why = detail[:2]
                moves.append((zone, f"the AI assistant changed {words}", why))
        if len(moves) == 1:
            zone, head, why = moves[0]
            return f"{self._where(room, zone)}: {head}", why or head
        what = "phase changes" if event == "phase" else "settings the AI assistant changed"

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
                "VWC increases with no water: the table does not drain",
                f"The VWC went from {low:.1f}% to {recent[len(recent) // 2]:.1f}% in the last "
                f"{(now - track[0][0]).total_seconds() / 60:.0f} min, but this zone got no water {since}. "
                "Water comes up from below. The table, its drain or the sump is blocked, and the slabs stand "
                "in runoff. Check the table, its drains and the sump pump now. The controller holds the daily "
                "minimum of the zone until the reading stops its increase.",
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
            f"The sump pump of this room used no power for {self.sump_silent_h:g} h. Usually it runs each hour "
            "or two while the room gets water. The runoff cannot go out. The sump fills, the water goes back into "
            "the tables, and the slabs stand in it. CS-310 follows when the VWC of a zone increases with no water. "
            "Check the sump pump now: its power, its float switch and that it pumps the water out. If the reading "
            f"is unavailable, check its power plug.\n\nSensor: {entity}",
            room=room,
        )

    def _watch_runoff(self, room, now):
        """The room's runoff estimate from its sump's water balance (runoff_balance.py), with the select
        runoff_estimator not off and a sump power sensor mapped. Records the sump runs and each mapped AC and
        dehumidifier's run time from history, closes each grow-day's sealed-room balance, refits, and publishes
        sensor.crop_steering_<prefix>runoff_estimate_app. In shown_alerts and ai, a grow-day whose balance does not
        close raises CS-314. Never waters, holds or moves a setting."""
        mode = ha_get(f"select.crop_steering_{room.prefix}runoff_estimator")[0]
        room._runoff_mode = mode if mode in RUNOFF_MODES else "off"
        if room._runoff_mode == "off":
            room._runoff_words = None
            return
        entity = self.sump_sensors.get(room.slug) or self.sump_sensors.get("*")
        sensor = f"sensor.crop_steering_{room.prefix}runoff_estimate_app"
        if not entity:
            room._runoff_words = None
            ha_set(sensor, "no_sump", {"why": "no sump power sensor mapped for this room (option sump_power_sensor)",
                                       "friendly_name": "Runoff estimate (room-wide)", "engine": PRODUCT})
            return
        st, now_s = room._runoff, now.timestamp()
        units = list(getattr(room, "hvac_units", None) or [])
        if st["cursor"] is None or now_s - st["cursor"] >= RUNOFF_CHECK_MIN * 60:
            since_s = (st["cursor"] - 600) if st["cursor"] else now_s - RUNOFF_FIRST_H * 3600
            since = datetime.fromtimestamp(since_s, timezone.utc)
            run_w = self._num(f"number.crop_steering_{room.prefix}sump_power_threshold_w", SUMP_RUN_W)
            hvac_w = self._num(f"number.crop_steering_{room.prefix}hvac_run_power_w", HVAC_RUN_W)
            rows = self._device_history(entity, "power", since)
            if rows is not None:
                st["runs"] = runoff_balance.merge(st["runs"], runoff_balance.spans(
                    [(w, _epoch(t)) for w, t in rows], lambda w: w > run_w, now_s))
            for unit in units:
                st["on"][unit] = runoff_balance.merge(st["on"].get(unit, []),
                                                      self._unit_spans(unit, since, hvac_w, now_s))
            st["cursor"] = now_s
            runoff_balance.prune(st, now_s)
            day_start = self._grow_day_start(room, now)
            closed = runoff_balance.day_tick(st, day_start.isoformat(), self._lights_on_s(room, day_start),
                                             self._substrate_water(room))
            self._save_state()
            if closed is not None and room._runoff_mode in ("shown_alerts", "ai"):
                self._runoff_closure_alert(room, closed)
        fitted = getattr(room, "_runoff_fit", None)
        if fitted is None or now_s - fitted[0] >= RUNOFF_FIT_MIN * 60:
            fit = runoff_balance.fit(st, units, self._num(
                f"number.crop_steering_{room.prefix}runoff_attribution_min", 90))
            room._runoff_fit = fitted = (now_s, fit)
        volume, source = self._sump_volume(room, st)
        held = ["the sump pump has not run (CS-311)"] if f"sump_{room.slug}" in self._alerted else []
        if getattr(room, "_backed_up", None):
            held.append("a table is backing up (CS-310)")
        state, attrs = runoff_balance.estimate(
            st, units, volume=volume, volume_source=source, f=fitted[1], now_s=now_s,
            today_start_s=self._lights_on_s(room, self._grow_day_start(room, now)), unresolvable="; ".join(held) or None)
        shared = sorted(r.slug for r in self.rooms if r is not room and
                        (self.sump_sensors.get(r.slug) or self.sump_sensors.get("*")) == entity)
        if shared:
            attrs["scope"] = f"per sump, shared with {', '.join(shared)}: not split by room"
        room._runoff_words = runoff_balance.words(state, attrs) if room._runoff_mode == "ai" else None
        ha_set(sensor, state, {**attrs, "mode": room._runoff_mode, "units": units, "sump_sensor": entity,
                               "friendly_name": "Runoff estimate (room-wide)", "engine": PRODUCT})

    @staticmethod
    def _lights_on_s(room, day):
        """The epoch seconds of grow-day `day`'s lights-on, on this machine's clock."""
        return (datetime.combine(day, datetime.min.time()) + timedelta(hours=float(room.lights_on_hour))).timestamp()

    def _unit_spans(self, unit, since, hvac_w, now_s):
        """When an AC or dehumidifier ran since `since`: by its power above hvac_w for a sensor, else its state."""
        domain = unit.split(".", 1)[0]
        if domain == "sensor":
            rows = self._device_history(unit, "power", since) or []
            return runoff_balance.spans([(w, _epoch(t)) for w, t in rows], lambda w: w > hvac_w, now_s)
        running = ("cool", "dry", "heat_cool", "auto") if domain == "climate" else ("on", "true", "open", "1")
        rows = ha_history(unit, since) or []
        return runoff_balance.spans([(str(v).lower(), _epoch(t)) for v, t in rows], lambda v: v in running, now_s)

    def _substrate_water(self, room):
        """Litres of water in the room's substrate now: each zone's last VWC x its substrate litres; None when a
        zone has no reading."""
        total = 0.0
        for zone in room.zones:
            vwc = room.state[zone].get("last_vwc")
            if vwc is None:
                return None
            total += float(vwc) / 100.0 * self._substrate_l(room, zone)
        return total

    def _sump_volume(self, room, st):
        """(litres per sump run, where from): the room's own number (a bucket test), else pump flow x the median
        run time, else the sealed-room closure; (None, "unknown") without any."""
        litres = self._num(f"number.crop_steering_{room.prefix}sump_litres_per_run", 0)
        if litres and litres > 0:
            return litres, "sump_litres_per_run"
        flow = self._num(f"number.crop_steering_{room.prefix}sump_pump_flow_lpm", 0)
        runs = sorted(e - s for s, e in st["runs"] if e > s)
        if flow and flow > 0 and runs:
            return flow * runs[len(runs) // 2] / 60.0, "pump flow x run time"
        closure = runoff_balance.closure_volume(st)
        return (closure, "sealed-room closure") if closure else (None, "unknown")

    def _runoff_closure_alert(self, room, day):
        """CS-314: a grow-day whose sump litres miss what a sealed room must give (fed - the substrate's change).
        With the litres per run taken from the closure itself, only a day far from the median says anything."""
        volume, source = self._sump_volume(room, room._runoff)
        error = runoff_balance.closure_error_pct(day, volume)
        if error is None or abs(error) <= runoff_balance.CLOSURE_ALERT_PCT:
            return
        want = runoff_balance.balance_litres(day)
        self._alert(
            f"runoff_closure_{room.slug}",
            "CS-314",
            "the sump water balance does not close",
            f"On the grow-day {day['date'][:10]} the sump took about {day['runs'] * volume:.0f} L ({day['runs']} runs "
            f"of {volume:.1f} L, {source}). A sealed room should have sent it {want:.0f} L: {day['fed_l']:.0f} L fed "
            f"minus the change of water in the substrate. That is {error:+.0f}%. Possible causes are a leak, a sump "
            "run the power plug did not report, a stuck float, or a wrong litres per run. Watering is not changed.",
            room=room,
        )

    def _tank_level(self, room):
        """The room's tank level (tank_level.py) -> (percent or None, low or None). The percent is None when no
        distance sensor is mapped, it has no reading, or the drawdown check says it is stuck. `low` is the
        float's answer, None when no float is mapped or it is unavailable. Read once a loop (_watch_tank)."""
        tank, pct, low = room.tank, None, None
        if tank.get("distance"):
            mm = self._device(tank["distance"], "distance")[0]
            if mm is not None:
                level = tank_level.percent(mm, tank["full_mm"], tank["empty_mm"])
                drawdown = room.tank_drawdown
                was = drawdown["stuck"]
                if tank_level.observe(drawdown, level):
                    pct = level
                if drawdown["stuck"] != was:
                    log(f"[{room.slug}] tank level: " + (
                        f"{tank['distance']} still reads {level:.1f} % although the shots have drawn "
                        f"{drawdown['litres']:.1f} L since it read {drawdown['base_pct']:.1f} %, about "
                        f"{drawdown['litres'] / drawdown['litres_per_pct']:.1f} % at the "
                        f"{drawdown['litres_per_pct']:.2f} L per 1 % it has shown: it looks stuck, so its level "
                        "is not trusted until it moves" if drawdown["stuck"] else
                        f"{tank['distance']} moves again ({level:.1f} %), so its level is trusted again"
                    ))
                    self._save_state()
        if tank.get("float"):
            on = self._on(tank["float"], None)
            low = None if on is None else on == (tank["float_low_state"] == "on")
        return pct, low

    def _watch_tank(self, room):
        """Read the room's tank level and publish it as sensor.crop_steering_<prefix>tank_level, with the minimum
        and overfill latches, and ask for a refill ahead of the minimum (_tank_plan). A room with no tank level
        mapped reads and publishes nothing."""
        if not room.tank:
            self._watch_tank_estimate(room)  # a tank size given instead: estimated, never holding
            return
        pct, low = room.tank_reading = self._tank_level(room)
        drawdown = room.tank_drawdown
        ha_set(
            f"sensor.crop_steering_{room.prefix}tank_level",
            pct if pct is not None else "unknown",
            {
                "unit_of_measurement": "%",
                "friendly_name": "Tank level",
                "stuck": drawdown["stuck"],
                "litres_per_pct": drawdown["litres_per_pct"],
                "low": low,
                "below_minimum": drawdown["low"],
                "over_full": drawdown["over"],
                "minimum_pct": tank_level.LOW_HOLD_PCT,
                "engine": PRODUCT,
            },
        )
        self._tank_marks(room, pct)
        self._tank_plan(room, pct)

    # ---------- SF-08: the reservoir minimum, the plan-ahead refill and the overfill guard ----------
    def _dismiss(self, key):
        """Take card f2_{key} down, when this controller raised it."""
        if key in self._alerted:
            ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}")
            self._alerted.pop(key, None)
            self._alert_codes.pop(key, None)

    def _tank_marks(self, room, pct):
        """Move the minimum and overfill latches (tank_level.below_minimum, over_full) by a level read now; saved
        when either moves. CS-904 goes up and comes down with the overfill latch."""
        drawdown = room.tank_drawdown
        if pct is None:
            return
        low = tank_level.below_minimum(drawdown["low"], pct)
        over = tank_level.over_full(drawdown["over"], pct)
        if over != drawdown["over"]:
            key = f"tank_over_{room.slug}"
            if over:
                self._alert(
                    key,
                    "CS-904",
                    "the tank is above its full mark, the fill stopped",
                    f"The tank reads {pct:.1f}%, at or above {tank_level.OVER_HOLD_PCT:g}% of its mapped full "
                    "distance. The controller sets the fill valve of a batch to off, and opens no fill valve, until "
                    f"the tank reads {tank_level.OVER_RELEASE_PCT:g}% or less. The shots continue. Check that the fill "
                    "valve closes. Check the full and empty distances of the tank in Rooms & setup."
                    f"\n\nSensor: {room.tank['distance']}",
                    room=room,
                    quiet=False,
                )
            else:
                self._dismiss(key)
        if (low, over) != (drawdown["low"], drawdown["over"]):
            drawdown.update(low=low, over=over)
            self._save_state()

    def _tank_hold(self, room):
        """Why the reservoir minimum holds the room's shots (docs/USER_GUIDE.md, "Reservoir minimum"), else None.
        Armed only by a tank level mapped in Rooms & setup (tank_level.mapping): a batch tank's full float is not a
        level, so a room without one, as every room is until its operator maps one, is never held here. A level
        that reads nothing, or that the drawdown check says is stuck, holds (CS-902): a pump run dry is what the
        minimum is there for. At or below 8 % holds until 12 % (CS-901), and so does a low float."""
        tank = room.tank
        if not tank:
            return None
        pct, low = room.tank_reading = self._tank_level(room)
        unread = [e for e, value in ((tank.get("distance"), pct), (tank.get("float"), low)) if e and value is None]
        if unread:
            names = ", ".join(unread)
            self._alert(
                f"tank_unknown_{room.slug}",
                "CS-902",
                "the tank level is not readable, no shots",
                "The tank level of this room gives no usable reading, or its distance sensor seems stuck (the "
                "level did not decrease while the shots took water from the tank). The controller cannot know how "
                "much water remains, so no shot starts, because a pump that takes in air runs dry. The shots start "
                f"again when the level reads again. Check the sensor, its power and its position.\n\nSensor: {names}",
                room=room,
            )
            return f"tank level unknown ({names})"
        self._dismiss(f"tank_unknown_{room.slug}")
        self._tank_marks(room, pct)
        if (pct is not None and room.tank_drawdown["low"]) or low:
            level = f"reads {pct:.1f} %" if pct is not None and room.tank_drawdown["low"] else "float reads low"
            self._alert(
                f"tank_low_{room.slug}",
                "CS-901",
                "the tank is at its minimum, no shots",
                f"The tank of this room {level}: at or below its {tank_level.LOW_HOLD_PCT:g}% minimum, or its low "
                "float switch reads low. No shot starts, because a pump that takes in air runs dry and can lose its "
                f"prime. The shots start again when the tank reads {tank_level.LOW_RELEASE_PCT:g}% or more and its "
                "float switch, if it has one, does not read low. Refill the tank.",
                room=room,
            )
            return f"tank at its minimum ({level})"
        self._dismiss(f"tank_low_{room.slug}")
        return None

    def _tank_short(self, room, zone, litres):
        """A shot of `litres` waits when it would take the tank to its minimum: the level now, less what the litres
        take off it at the litres per 1 % the tank has shown (the drawdown check). Nothing waits before those are
        learned, or with no distance sensor mapped. The litres are kept for the plan-ahead refill (_tank_plan)."""
        if not room.tank.get("distance"):
            return None
        room.tank_round[zone] = litres
        pct = (getattr(room, "tank_reading", None) or (None, None))[0]
        drop = tank_level.drop(room.tank_drawdown, litres)
        if pct is None or drop is None or pct - drop > tank_level.LOW_HOLD_PCT:
            return None
        return (f"this {litres:.1f} L shot would take the tank from {pct:.1f} % to {pct - drop:.1f} %, "
                f"at or below its {tank_level.LOW_HOLD_PCT:g} % minimum")

    def _tank_plan(self, room, pct):
        """CS-903, the plan-ahead refill: one more round of shots, each zone's last, would take the tank to its
        minimum. It only tells; a shot that would cross the minimum waits (_tank_short). Its card comes down once
        a round leaves the tank at 12 % or more, after a refill."""
        need = sum(room.tank_round.values())
        drop = tank_level.drop(room.tank_drawdown, need) if need else None
        if pct is None or drop is None:
            return
        key = f"tank_refill_{room.slug}"
        if pct - drop <= tank_level.LOW_HOLD_PCT:
            self._alert(
                key,
                "CS-903",
                "refill the tank before the next set of shots",
                f"The tank reads {pct:.1f}%. One more set of shots ({need:.1f} L, the last shot of each zone) takes "
                f"it to about {pct - drop:.1f}%, at or below its {tank_level.LOW_HOLD_PCT:g}% minimum. The controller "
                f"calculates this from the {room.tank_drawdown['litres_per_pct']:.2f} L for each 1% that the tank "
                "showed. A shot that crosses the minimum waits until the tank is full again. Refill the tank now.",
                room=room,
            )
        elif pct - drop >= tank_level.LOW_RELEASE_PCT:
            self._dismiss(key)

    def _tank_over(self, room):
        """The overfill guard a batch's fill reads (dosing_runner._fill): True while the tank reads at or over
        102 %, until it reads 98 % or less. False with no distance sensor mapped, so a fill stops on its full
        float as it always did; a level that reads nothing keeps the last answer."""
        if not getattr(room, "tank", {}).get("distance"):
            return False
        self._tank_marks(room, self._tank_level(room)[0])
        return room.tank_drawdown["over"]

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
            "no shots for some hours",
            f"No zone in this room got a shot for {idle:.1f} h while its lights were on and a zone "
            f"was in P1 or P2. {self._idle_why(room, pub)} This alert comes again each "
            f"{'hour' if hours == 1 else f'{hours:g} h'} while the condition stays. It clears at the next shot.",
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

    def _why_gates(self, room, pub):
        """What stops this room being watered, for the AI assistant's why answers (brain_bridge.why_state): its kill
        switch, each external hold (hold_entities) that reads on or cannot be read, and each zone's hold and decision
        from this pass (pub: _blocked, as the shots saw it). Read only when a question is asked; bounded in size."""
        def read(entity):
            v, attrs, _ = ha_get(entity)
            state = ("unreadable" if v in (None, "unknown", "unavailable", "")
                     else "on" if str(v).lower() in ON_STATES else "off")
            name = (attrs or {}).get("friendly_name") or entity.split(".")[-1].replace("_", " ")
            return {"name": str(name)[:60], "state": state}
        holds = [h for h in map(read, self.hold_entities[:10]) if h["state"] != "off"]
        zones = {z: {"block": str(d["block"])[:160] if d.get("block") else None,
                     "decision": str(d.get("reason") or "")[:120]}
                 for z, d in sorted((pub or {}).items())}
        out = {"kill_switch": read(room_gate(room)), "holds_on": holds, "zones": zones}
        if getattr(room, "_runoff_words", None):  # the runoff estimator set to ai: a room-wide hint, never a catch
            out["runoff_estimate"] = room._runoff_words
        return out

    def _idle_why(self, room, pub):
        """Why nothing has been watered, as far as this pass can tell: watering switched off, a hold (_blocked), or
        nothing called for water."""
        if not self._on(room_gate(room), False):
            return f"The kill switch of this room ({room_gate(room)}) is off."
        holds = []
        for zone in sorted(room.zones):
            if room.state[zone].get("phase") in ("P1", "P2"):
                hold = (pub.get(zone) or {}).get("block") or self._blocked(room, zone)
                if hold:
                    holds.append(f"{self._zone_title(room, zone)}: {hold}")
        if holds:
            return f"A hold stops the shots. {'; '.join(holds)}."
        return ("No zone asked for water: no zone in P1 or P2 became dry enough to reach its re-water point. If "
                "the plants drink, check the probes and the re-water point of each zone.")

    def _dosing_alert(self, room, code, title, message, event=None):
        """An alert the dosing runner raised (docs/DOSING.md) -> True once Home Assistant has it (the
        runner keeps it until then). Only these codes exist, each written out here so the error-code
        list sees it; `room` is None for a room no longer set up, or for dosing as a whole. Each
        event (a dose, a batch, a restart) has its own notification: a second one within 30 minutes
        is never swallowed by the first. The runner paces an event's repeats itself (and a repeat
        replaces its card)."""
        key = self._dosing_key(room, code, event)
        if code == "CS-801":
            return self._alert(key, "CS-801", title, message, room=room, quiet=False)
        if code == "CS-802":
            return self._alert(key, "CS-802", title, message, room=room, quiet=False)
        if code == "CS-803":
            return self._alert(key, "CS-803", title, message, room=room, quiet=False)
        if code == "CS-804":
            return self._alert(key, "CS-804", title, message, room=room, quiet=False)
        if code == "CS-805":
            return self._alert(key, "CS-805", title, message, room=room, quiet=False)
        if code == "CS-806":
            return self._alert(key, "CS-806", title, message, room=room, quiet=False)
        if code == "CS-807":
            return self._alert(key, "CS-807", title, message, room=room, quiet=False)
        if code == "CS-808":
            return self._alert(key, "CS-808", title, message, room=room, quiet=False)
        if code == "CS-809":
            return self._alert(key, "CS-809", title, message, room=room, quiet=False)
        if code == "CS-906":
            return self._alert(key, "CS-906", title, message, room=room, quiet=False)
        log("dosing alert refused: not in the error-code list", code)
        return True  # never deliverable: not kept

    @staticmethod
    def _dosing_key(room, code, event=None):
        return f"dosing_{getattr(room, 'slug', 'gone')}_{code[3:]}" + (f"_{event}" if event else "")

    def _dosing_dismiss(self, room, code, event=None):
        """Take down an alert the dosing runner raised (the refill reminder, once the tank is refilled)
        -> True once Home Assistant has dismissed it."""
        key = self._dosing_key(room, code, event)
        self._alerted.pop(key, None)
        self._alert_codes.pop(key, None)
        return ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}")

    def _dosing_may_act(self, room):
        """Whether dosing may act on its own in this room (pH auto-correct): the room is on and its kill
        switch reads on. A request a person makes is not asked this."""
        return self._room_active(room) and self._on(room_gate(room), False)

    # ---------- CS-211: shots held for too long ----------
    @staticmethod
    def _held_by_a_person(block):
        """A hold a person set on purpose: the kill switch, a zone switched off, a manual override."""
        text = str(block)
        return ("kill switch off" in text or "engine switch switched off" in text
                or text in ("zone disabled", "manual override"))

    def _watch_held(self, room, now, pub):
        """CS-211 (opt-in: the room's held_alert_hours, 0 = off): a zone that has asked for water and been held
        by the same kind of block, never a person's (_held_by_a_person), with no shot since, for that many hours.
        The clock starts at the first held shot and stops at the next shot the zone gets; a pass where the zone
        asks for nothing leaves it running. Held in memory: a restart starts it again. It only ever tells."""
        hours = self._num_or_none(f"number.crop_steering_{room.prefix}held_alert_hours")
        since = room.__dict__.setdefault("_held_since", {})
        raised = room.__dict__.setdefault("_held_raised", set())
        for zone in sorted(pub):
            d = pub[zone]
            block = d.get("block")
            if not d.get("fire"):
                continue
            if block and not self._held_by_a_person(block) and hours and hours > 0:
                since.setdefault(zone, (now, block))
            else:
                since.pop(zone, None)
        for zone in list(since):
            if not hours or hours <= 0 or zone not in room.zones:
                since.pop(zone, None)
        for zone in sorted(raised - set(since)):
            key = f"held_{room.slug}_z{zone}"
            if ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}"):
                raised.discard(zone)
            self._alerted.pop(key, None)
            self._alert_codes.pop(key, None)
        for zone, (started, first) in sorted(since.items()):
            held_h = (now - started).total_seconds() / 3600.0
            if held_h < hours:
                continue
            now_block = (pub.get(zone) or {}).get("block") or first
            if self._alert(
                f"held_{room.slug}_z{zone}",
                "CS-211",
                "shots held for too long",
                f"This zone asked for water and got no shot for {held_h:.1f} h: a hold stops its shots. The hold "
                f"now: {now_block}. Your limit for this alert is {hours:g} h (Shots held alert). Remove the hold, "
                "or water the zone by hand. This alert comes again every 30 minutes while the hold lasts. It clears "
                "at the next shot of the zone.",
                room=room,
                zone=zone,
            ):
                raised.add(zone)

    # ---------- light dimming on dry substrate (dry_dim.py) ----------
    def _dim_settings(self, room):
        return {key: dry_dim.setting(self._num_or_none(f"number.crop_steering_{room.prefix}dry_dim_{key}"), key)
                for key in dry_dim.SETTINGS}

    def _dim_alert(self, room, code, title, message, quiet=False):
        """An alert about the room's dimmed light: CS-810 for each dim, restore and hand-over, CS-811 (critical)
        for a room dimmed past its longest time or a light that does not come back."""
        key = f"dim_{room.slug}"
        if code == "CS-810":
            return self._alert(key, "CS-810", title, message, room=room, quiet=quiet)
        if code == "CS-811":
            return self._alert(key, "CS-811", title, message, room=room, quiet=quiet)
        return False

    def _light_reads(self, light, want, tries=5):
        """Read a light back until its brightness is within dry_dim.TOLERANCE of `want` -> True when it is."""
        for attempt in range(tries):
            state, attributes, _ = ha_get(light)
            got = dry_dim.brightness(attributes)
            if str(state).lower() == "on" and got is not None and abs(got - want) <= dry_dim.TOLERANCE:
                return True
            if attempt < tries - 1:
                time.sleep(1.0)
        return False

    def _watch_dim(self, room, now, lights_on, snaps, off_why=None):
        """Light dimming on dry substrate (dry_dim.py), once a pass. `off_why`: the room is off this pass,
        so a dim it holds is restored for that reason and nothing new is dimmed."""
        record = getattr(room, "_dim", None)
        dimmer = room.__dict__.get("_dimmer") or room.__dict__.setdefault("_dimmer", dry_dim.Dimmer())
        enabled = self._on(f"switch.crop_steering_{room.prefix}dry_dim", False)
        if record is None and (not enabled or off_why):
            dimmer.dry_since = dimmer.ok_since = None
            return
        light = (record or {}).get("light") or getattr(room, "light_entity", "")
        state, attributes, _ = ha_get(light) if light else (None, {}, None)
        s = self._dim_settings(room)
        if off_why:
            action, why = "restore", off_why
        else:
            px = room.prefix
            readings = {z: snap.vwc for z, snap in (snaps or {}).items()
                        if self._on(f"switch.crop_steering_{px}zone_{z}_enabled", False)}
            action, why = dimmer.step(
                record, now=now, enabled=enabled, allowed=self._on(room_gate(room), False), lights_on=lights_on,
                to_off_min=self._hours_to(now, room.lights_off_hour) * 60.0,
                light=getattr(room, "light_entity", ""), state=None if state is None else str(state).lower(),
                attributes=attributes, readings=readings, s=s)
            if action == "dim":
                dry = ", ".join(f"{self._zone_title(room, z)} {v:g}%" for z, v in sorted(readings.items())
                                if dry_dim.DEAD_VWC <= v < s["floor_vwc"])
                return self._dim(room, now, light, attributes, why, dry, s)
        if action == "restore":
            return self._undim(room, record, why, s)
        if action == "drop":
            room._dim = None
            self._save_state()
            log(f"[{room.slug}] dimming: {why}; the light is left as it is")
            self._dim_alert(room, "CS-810", "dimming handed back",
                            f"The controller had dimmed {record['light']} because the substrate was dry. Then {why}. "
                            "The controller does not fight another controller: it no longer dims or restores this "
                            f"light. It was at {round(record['was'] / 2.55)}% before the dim. Check its brightness.")

    def _dim(self, room, now, light, attributes, target, dry, s):
        was = dry_dim.brightness(attributes)
        room._dim = {"light": light, "was": was, "set": target, "since": now.isoformat()}
        self._save_state()  # before the light moves, so a restart restores it
        ha_call("light", "turn_on", entity_id=light, brightness=target)
        if not self._light_reads(light, target):
            ha_call("light", "turn_on", entity_id=light, brightness=was)
            back = self._light_reads(light, was)
            if back:
                room._dim = None
                self._save_state()
            log(f"[{room.slug}] dimming: {light} did not read {target}; set back to {was}: {back}")
            self._dim_alert(room, "CS-810", "the light did not dim",
                            f"The substrate is dry ({dry}, under {s['floor_vwc']:g}%) and the controller asked "
                            f"{light} to dim to {s['level_pct']:g}%, but it did not read that brightness. The "
                            "controller set it back to its brightness before"
                            + ("." if back else ", but it does not read that either. Check the light now."))
            return
        log(f"[{room.slug}] dimming: dry substrate ({dry}): {light} {was} -> {target}")
        self._dim_alert(room, "CS-810", "lights dimmed: the substrate is dry",
                        f"The substrate is dry: {dry}, under the floor of {s['floor_vwc']:g}% for "
                        f"{s['after_min']:g} min with the lights on. The controller dimmed {light} from "
                        f"{round(was / 2.55)}% to {s['level_pct']:g}% to slow the drying. It restores the light when "
                        f"every zone reads {s['floor_vwc'] + dry_dim.RECOVER_PTS:g}% for "
                        f"{dry_dim.RECOVER_MIN:g} min, before lights-off, when you switch dimming or the kill switch "
                        f"off, and after {s['max_h']:g} h at most. Find out why the zone is dry: a hold on its shots, "
                        "an empty tank or a blocked dripper.")

    def _undim(self, room, record, why, s):
        light, was = record["light"], record["was"]
        state = str(ha_get(light)[0]).lower()
        if state != "on":  # a restore never switches a light on: an off light is left to its own controller
            if state in ("none", "unknown", "unavailable", ""):
                room._dimmer.restarted = True  # can't be read now: tried again next pass
                return
            room._dim = None
            self._save_state()
            log(f"[{room.slug}] dimming: {light} reads {state}, so it was not set back to {was} ({why})")
            self._dim_alert(room, "CS-810", "a dimmed light was not set back",
                            f"The controller had dimmed {light} because the substrate was dry, and wanted to set it "
                            f"back to {round(was / 2.55)}% ({why}), but the light is off. The controller never switches "
                            "a light on, so it left it. When it comes on again it may still be dimmed: check its "
                            "brightness.")
            return
        ha_call("light", "turn_on", entity_id=light, brightness=was)
        if not self._light_reads(light, was):
            room._dimmer.restarted = True  # tried again every pass
            log(f"[{room.slug}] dimming: {light} did not come back to {was} ({why})")
            self._dim_alert(room, "CS-811", "the light did not come back from a dim",
                            f"The controller dimmed {light} because the substrate was dry, and now asks it back to "
                            f"{round(was / 2.55)}% ({why}), but it does not read that brightness. The controller "
                            "asks again each pass. Check the light now, and set its brightness by hand.", quiet=True)
            return
        room._dim = None
        self._save_state()
        log(f"[{room.slug}] dimming: {light} back to {was} ({why})")
        if why == "max":
            self._dim_alert(room, "CS-811", "lights were dimmed for too long",
                            f"The controller dimmed {light} because the substrate was dry, and it stayed dry for "
                            f"{s['max_h']:g} h, the longest the room may stay dimmed. The controller set the light "
                            f"back to {round(was / 2.55)}%. The zone is still dry: find out why now (a hold on its "
                            "shots, an empty tank, a blocked dripper) and water it by hand if needed.")
        else:
            self._dim_alert(room, "CS-810", "lights back to full",
                            f"The controller set {light} back to {round(was / 2.55)}% after a dim on dry substrate: "
                            f"{why}.")

    def _dosing_hold(self, room):
        """Why dosing holds this room's watering ("making a batch", or "dosing hardware still on: ..."
        while something a dose or batch left does not read off), else None."""
        return self.dosing.holds(room) if self.dosing is not None else None

    def _shot_running(self, slugs):
        """Whether a shot is in flight in one of these rooms, read under the lock a shot starts under,
        so a batch that has just held them never misses one starting."""
        with self._shot_lock:
            room = getattr(self, "_shot_room", None) if getattr(self, "_busy", False) else None
        return room is not None and room.slug in slugs

    def _jev_alert(self, room, zone, judge, alert):
        """An alert one of the AI assistant's judges, or the AI assistant's runtime, raised (docs/AI_ASSISTANT.md). Only these codes exist: a judge can
        never raise anything the error-code list does not explain. `zone` None is a room-wide alert."""
        key = f"jev_{judge}_{room.slug}" + ("" if zone is None else f"_z{zone}")
        code, title, message = alert.get("code"), alert.get("title", ""), alert.get("message", "")
        if code == "CS-701":
            return self._alert(key, "CS-701", title, message, room=room, zone=zone)
        elif code == "CS-702":
            return self._alert(key, "CS-702", title, message, room=room, zone=zone)
        elif code == "CS-703":
            return self._alert(key, "CS-703", title, message, room=room, zone=zone)
        elif code == "CS-705":
            return self._alert(key, "CS-705", title, message, room=room, zone=zone)
        elif code == "CS-706":
            return self._alert(key, "CS-706", title, message, room=room, zone=zone)
        elif code == "CS-707":
            return self._alert(key, "CS-707", title, message, room=room, zone=zone)
        elif code == "CS-708":
            return self._alert(key, "CS-708", title, message, room=room, zone=zone)
        elif code == "CS-709":
            return self._alert(key, "CS-709", title, message, room=room, zone=zone)
        elif code == "CS-710":
            return self._alert(key, "CS-710", title, message, room=room, zone=zone)
        elif code == "CS-711":
            return self._alert(key, "CS-711", title, message, room=room, zone=zone)
        elif code == "CS-712":
            return self._alert(key, "CS-712", title, message, room=room, zone=zone)
        elif code == "CS-713":
            return self._alert(key, "CS-713", title, message, room=room, zone=zone)
        log("brain alert refused: not in the error-code list", judge, code)
        return False

    @staticmethod
    def _jev_read(entity):
        """One entity's state for the AI assistant's context (the room's flower start date)."""
        return ha_get(entity)[0]

    def _unreadable(self, entity, max_age_min=20):
        """Why `_read_sensor` found no usable moisture reading at `entity`, as (code, sentence).
        The same tests in the same order, on one more read of the entity."""
        lo, hi = UNITS["vwc"]["plausible"]
        value, v, unit, lu, taken, attrs = self._device(entity, "vwc")
        if v is None:
            return "CS-102", "The moisture entity of this zone is not in Home Assistant, so the controller has no reading to steer by."
        # The integration's zone reading names the probes it set aside for their unit (unit_set_aside).
        aside = (attrs or {}).get("unit_set_aside")
        if v in ("unknown", "unavailable", "") and isinstance(aside, dict) and aside:
            probes = ", ".join(f"{probe} (in '{unit or 'no unit'}')" for probe, unit in aside.items())
            return "CS-503", (
                f"The moisture probe {probes} of this zone reports in a unit that the controller cannot use as a "
                "moisture percentage. The controller sets the probe aside, and the zone has no reading to steer by."
            )
        if v in ("unknown", "unavailable", ""):
            return "CS-102", f"The moisture entity of this zone reads '{v or 'empty'}', so the controller has no reading to steer by."
        try:
            float(v)
        except (TypeError, ValueError):
            return "CS-102", f"The moisture entity of this zone reads '{v}'. This is not a number, so the controller has no reading to steer by."
        if taken == "refused" or (taken == "implausible" and str(unit or "").strip()):
            return "CS-503", (
                f"The moisture entity of this zone reads {v} in '{unit}'. The controller cannot use this as a "
                "moisture percentage, so it sets the probe aside."
            )
        if value is None or value < lo or value > hi:
            return "CS-103", f"The moisture entity of this zone reads {v}. A moisture reading must be {lo:g}–{hi:g}%, so the controller ignores it."
        f = value
        try:
            ts = datetime.fromisoformat(str(lu).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
        except (ValueError, TypeError, OverflowError):
            ts = age_min = None
        if age_min is not None and age_min > max_age_min:
            age = f"{age_min:.0f} min" if age_min < 120 else f"{age_min / 60:.1f} h"
            return "CS-101", (
                f"The moisture reading of this zone stayed at {f:g}% for {age}. The controller cannot "
                "tell a good probe from a probe that stopped or came out of the cube."
            )
        if age_min is not None and age_min < -1.0:  # _read_sensor: age < -60 s
            return "CS-102", (
                f"The time of the moisture reading of this zone is {-age_min:.0f} min in the future, so "
                "the controller cannot trust it. The clocks of Home Assistant and the controller do not agree."
            )
        if age_min is None:
            return "CS-102", "The moisture entity of this zone has no valid time for its last reading, so the controller has no reading to steer by."
        return "CS-102", "The moisture entity of this zone had no usable reading a moment ago, so the controller had no reading to steer by."

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
                # the ramp shots in a row before this one that did not rise, as this pass's decision counted them
                flat = room.__dict__.get("_p1_stall_now", {}).get(zone, 0)
                st["p1_flat"] = 0 if st.get("p1_reached") else int(flat)
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
        if room.tank.get("distance"):  # what the tank gave, for the level's drawdown check
            tank_level.drawn(room.tank_drawdown, delivered_l)
        elif not room.tank:  # no level mapped: the estimate counts it (only once a fill has been seen)
            safety_ops.tank_used(room.tank_estimate, delivered_l)
        self._save_state()
        if room.__dict__.get("_runoff_mode", "off") != "off":
            runoff_balance.add_shot(room._runoff, now.timestamp(), delivered_l)  # the sump balance's feed
        if room.__dict__.get("_shot_check", "off") != "off":
            shot_audit.counted(room, zone, delivered_l)  # the shot table's record (shot_audit.py)
        if getattr(self, "jev", None) is not None:
            try:  # the shot, for the AI assistant's Shot and Probe judges to read its answer later
                brain_bridge.shot_counted(room, zone, delivered_l)
            except Exception as e:
                log("brain shot record error", room.slug, zone, e)

    def _record_phase(self, room, zone, st, was, new, now, how, snap=None, p=None):
        """Keep the zone's history on a phase change by anyone (the engine, a AI assistant judge, the operator's Set Phase):
        P1 handing over to P2 is the day's plateau. A history error never stops the phase change.
        With the pass's snapshot and params, a ramp handed over while it stalls under its target (core.p1_stall)
        re-waters under what it reached for the rest of the grow-day."""
        if new == "P1":  # the P1 rule (core.decide) starts again
            st["p1_reached"], st["p1_peak_before"], st["p1_extra"] = False, None, 0
            st["p1_settled_before"], st["p1_expected_rise"], st["p1_flat"] = None, None, 0
        if new == "P0":
            st["p1_stall"] = None
        if new in ("P0", "P3"):
            st["ec_flushing"] = False  # an EC flush episode ends at lights-off and never carries into a new day
        if (was == "P1" and new == "P2" and snap is not None and p is not None and not snap.backed_up
                and not snap.p1_probe_suspect and snap.vwc < min(p.p1_target, p.field_capacity)
                and p1_stall(snap, p) >= 1):
            at = max(snap.vwc_settled, snap.p1_settled_before_shot)
            rewater = p1_stall_rewater(at, p.p2_threshold, p.p1_stall_band)
            st["p1_stall"] = {"day": self._grow_day_start(room, now).isoformat(), "at": round(at, 2),
                              "rewater": rewater}
            words = (f"P1 stalled at {at:.1f}% ({p1_stall(snap, p)} shots did not raise moisture): re-water "
                     f"{rewater:g}% for the rest of the grow-day, not {p.p2_threshold:g}%")
            log(f"[{room.slug}] Z{zone} {words}")
            tag = "" if room.prefix == "" else f"{room.slug} "
            self._activity.insert(0, f"{now.strftime('%H:%M')} {tag}Z{zone} {words}"[:120])
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
            "CRITICAL hardware fault, no shots",
            f"{self._fault_words(room.hardware_fault)}.\n\nA pump or a valve did not read back off after "
            "the controller closed it. The controller stops the shots on this hardware and in each room "
            f"that shares it. CAUTION: Set the kill switch ({room_gate(room)}) of each of these rooms to "
            "off. A pump or a valve that stays on can flood the room. Check the switch at the device and "
            "in Home Assistant. The hold clears within a minute when all the pumps and valves read OFF. "
            "Then set the kill switch to on again."
            + (
                ""
                if saved
                else " THE FAULT COULD NOT BE SAVED. CAUTION: Do not restart the controller before the "
                "repair. A restart can lose the hold."
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
                    "CRITICAL, the hardware of an interrupted shot is still ON",
                    f"A shot that started {rec['started']} did not end correctly. The controller "
                    "stopped or lost Home Assistant during the shot, or a switch did not read back off "
                    "at the end. The controller set what the shot opened to off, but it still does not "
                    "read OFF. Water can still flow. CAUTION: Go to the room now, and stop the device by "
                    "hand if water flows. Water that flows can flood the room. The controller tries again "
                    f"each loop.\n\nStill ON: {', '.join(close)}",
                    room=room,
                    zone=zone,
                )
                return
            log(f"{tag}: switched off {', '.join(close)} (ON since the shot opened them)")
        if unsure:
            self._alert(
                f"inflight_{room.slug}",
                "CS-309",
                "the hardware of an interrupted shot can still be ON",
                f"A shot that started {rec['started']} did not end. The controller cannot read what "
                "the shot opened, or Home Assistant has no time for its last change or no history since "
                "the shot started. So the controller cannot tell if a person changed it. The controller "
                "does not touch it, and checks again each loop. Check it now. If water flows, set it to "
                "off by hand. When the controller can read it, it sets to off only what it can prove "
                "that this shot opened. It leaves all other devices on for you."

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

    def _operator_stop(self, room, zone, step, until=None, holds=False):
        """The operator's own switches for a shot, read in turn, each read bounded by `step` and by what
        is left to the monotonic `until` (none starts once it has passed): ("refused", None) when Home
        Assistant refuses this controller's token, ("abort", entity) for a definitive kill OFF / room
        OFF / zone OFF / override ON, else None. With `holds` (a shot still opening; _wait_shot reads
        them itself, with the valve) also ("external", entity) for a hold, or under a waste-valve rule
        the waste valve, that reads ON, as in _wait_shot."""
        for entity, stop_state in (
            (room_gate(room), "off"),
            (f"switch.crop_steering_{room.prefix}room_active", "off"),
            (f"switch.crop_steering_{room.prefix}zone_{zone}_enabled", "off"),
            (
                f"switch.crop_steering_{room.prefix}zone_{zone}_manual_override",
                "on",
            ),
        ):
            remaining = step if until is None else until - time.monotonic()
            if remaining <= 0:
                return None
            if _GATE.state == "all":
                return ("refused", None)
            # Account for network time, and never start a read longer than what remains.
            # HTTP/socket scheduling can still overshoot; the caller measures time rather
            # than pretending sleep time was delivery.
            state = ha_get(entity, timeout=min(step, remaining))[0]
            if state == stop_state:
                return ("abort", entity)
        waste = (room.waste,) if holds and self._waste_rule(room) != "Off" else ()
        for entity in [e for e in (*(self.hold_entities if holds else ()), *waste) if e]:
            remaining = step if until is None else until - time.monotonic()
            if remaining <= 0:
                return None
            if _GATE.state == "all":
                return ("refused", None)
            if str(hw_get(entity, timeout=min(step, remaining))[0]).lower() in ON_STATES:
                return ("external", entity)
        return None

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
        # The waste valve, under a waste-valve rule: opened during the shot, it ends it (CS-307).
        waste = (room.waste,) if self._waste_rule(room) != "Off" else ()
        while time.monotonic() < deadline:
            stop = self._operator_stop(room, zone, step, deadline)
            if stop:
                return time.monotonic() - started, stop
            for entity in [e for e in (*self.hold_entities, *waste, valve) if e]:
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
                # A dose or batch running goes on through the wait: a batch's open fill valve is still
                # watched for its full sensor (dosing_runner._fill). With none running, a plain sleep.
                if self.dosing is not None and self.dosing.running():
                    self._sleep_for(min(step, remaining))
                else:
                    time.sleep(min(step, remaining))
        return time.monotonic() - started, None

    def _close_cut_short(self, room, zone, by, elapsed, duration_s, valve_opened, unconfirmed=None):
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

        `unconfirmed` (a shot cut short while it opened): the switch it had sent ON and not yet read back
        ON. Its OFF may only be its old state, the ON still to land, so it is switched off whatever it reads.
        """
        valve, mainline, pump = room.hw["valves"].get(zone), room.hw.get("mainline"), room.hw.get("pump")
        reads = {e: hw_get(e) for e in (valve, mainline, pump) if e}
        close = [e for e in (valve, mainline) if e and (e == unconfirmed or reads[e][0] != "off")]
        left = []
        if pump and (pump == unconfirmed or reads[pump][0] != "off"):
            (left if any(self._on(f, False) for f in self.hold_entities) else close).append(pump)
        failures = self._switch_off_failures(close) if close else []
        if failures:
            self._latch_hardware_fault(room, f"zone {zone} shot cut short", failures)
        else:
            room.shot_inflight = None  # as after a normal close: nothing of this shot's is left open
        changed = _aware(getattr(reads[valve], "last_changed", None)) if reads[valve][0] == "off" else None
        closed_after = (changed - valve_opened).total_seconds() if changed else None
        open_s = closed_after if closed_after is not None and 0 <= closed_after <= elapsed else elapsed
        what = (f"a device other than this controller set its valve {by} to OFF" if by == valve
                else f"the waste valve {by} opened" if by == getattr(room, "waste", None)
                else f"the hold {by} started")
        outcome = " ".join(
            ([f"The controller set {', '.join(close)} to off."] if close else [])
            + ([f"The controller left {', '.join(left)} on, because a hold uses it now."] if left else [])
        ) or "Nothing that the shot opened was still on."
        log(f"[{room.slug}] Z{zone} shot cut short after {open_s:.1f}/{duration_s:.0f}s: {what}. {outcome}")
        self._alert(
            f"cutshort_{room.slug}_z{zone}",
            "CS-307",
            "shot stopped early by an external change",
            f"The shot stopped after {open_s:.0f} s of {duration_s:.0f} s, because {what}. The controller "
            f"counts only the water of those {open_s:.0f} s. {outcome}",
            room=room,
            zone=zone,
        )
        return open_s

    @staticmethod
    def _confirm_switches(entities, want, deadline=None, reads=None, stop=None, until=None,
                          first=CONFIRM_FIRST_READ_S):
        """True only when every switch reads back `want`. Each state read is added to `reads` when given.

        With `stop` (a shot opening: _operator_stop for it), `stop(end of this stage)` is asked at most every
        2 s before a pause, and an answer raises _ShotStopped; each read is then also bounded by what is left of the
        read-back, so a hanging Home Assistant cannot stretch it while the shot's switches are on. With
        `until` (the monotonic clock) the read-back gives up then, whatever is left of its 16 s.

        Zigbee/MQTT plugs accept a command at once but report the new state later
        (a pump's OFF report: usually under 1 s; 1.6 s on 15 Sep and about 10 s on 28 Sep 2026 on a
        live install). A read-back that gives up too early latches a false hardware hold; one that
        waits too long stalls every room (this loop is synchronous) before a real stuck-open is caught.
        On the way out (SIGTERM) it gives up when the stop's `deadline` (a _Stop) runs out.
        """

        asked = [None]  # when stop() was last asked

        def check(end):
            if stop is not None and (asked[0] is None or time.monotonic() - asked[0] >= 2.0):
                asked[0] = time.monotonic()
                by = stop(end)
                if by:
                    raise _ShotStopped(by)

        def read(ent, end):
            if stop is not None:
                state = hw_get(ent, timeout=min(8.0, max(CONFIRM_POLL_S, end - time.monotonic())))[0]
            else:
                state = _read(ent, deadline)[0]
            if reads is not None:
                reads.append(state)
            return state

        def settled(window, first):
            end = time.monotonic() + window
            if deadline is not None:
                end = min(end, deadline.until)
            if until is not None:
                end = min(end, until)
            check(end)
            _pause(first, deadline)
            while True:
                if deadline is not None and deadline.timeout(8) is None:
                    return False  # no read-back fits in what is left of the stop
                if all(read(ent, end) == want for ent in entities):
                    return True
                if time.monotonic() >= end:
                    return False
                check(end)
                _pause(CONFIRM_POLL_S, deadline)

        # First read at 1 s (`first`: sooner inside a shorter prime or lead), exactly as before, so a plug
        # that reports promptly costs nothing extra. A late report is then re-read every 0.5 s up to 6 s.
        # The pump has already been commanded OFF by the time this runs.
        if settled(CONFIRM_TIMEOUT_S, first):
            return True
        if deadline is not None and deadline.timeout(8) is None:
            return False
        if until is not None and time.monotonic() >= until:
            return False
        # Then 10 s more: 16 s in all (a report about 10 s late was seen on a live install), still inside
        # the minute's loop for a genuinely stuck switch. Whatever still does not read OFF is first sent
        # OFF again (a plug may have missed the first); an ON is not sent again.
        if want == "off":
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
        # A zone whose pump, main line or valve has not switched on for several shots in a row is tried at
        # most once every SWITCH_ON_BACKOFF_MIN, rescue shots too: a dead valve delivers no rescue water,
        # and retrying it each pass would short-cycle the pump. An operator's Test Shot (the only shot with
        # steering off) is not held: it is how a repair is checked.
        retry_at = _switch_on_retry_at(room.state[zone]) if steering else None
        if retry_at is not None and datetime.now() < retry_at:
            log(f"[{room.slug}] Z{zone} shot held: its pump, main line or valve did not switch on "
                f"{room.state[zone]['on_failures']['count']} shots in a row; next try at {retry_at:%H:%M}")
            return
        # Freeze hydraulic sizing before opening hardware. Editing plant count,
        # substrate or dripper configuration mid-shot must not rewrite its litres.
        nominal_l = (flow_lps * duration_s if flow_lps is not None
                     else size_pct / 100.0 * self._substrate_l(room, zone))
        short = self._tank_short(room, zone, nominal_l)
        if short:  # the plan-ahead half of the reservoir minimum: _tank_plan asks for the refill
            log(f"[{room.slug}] Z{zone} shot held: {short}")
            return
        if not self._close_waste(room, zone):  # Close for each shot: a waste valve still open, nothing opens
            log(f"[{room.slug}] Z{zone} shot held: the waste valve did not close")
            return
        with self._shot_lock:  # a batch holds rooms under this lock (see _shot_running)
            making = self._dosing_hold(room)
            if not making:
                self._busy = True
                self._shot_room = room  # the room whose shot is in flight right now (see _safe_off)
        if making:
            log(f"[{room.slug}] Z{zone} shot held: {making}")
            return
        shutdown_checked = False
        valve_started = valve_opened = None
        counted = False
        stopping = False
        commanded = False  # a switch has been sent ON: from here an error must close what may be open
        errored = False

        def count_water_so_far():
            # The shot ended without its close counting it (stopped or errored): count the water given
            # since the valve opened, or the next pass waters the zone as if it had had none.
            nonlocal counted
            if valve_started is not None and not counted:
                counted = True
                run = (time.monotonic() - valve_started) / duration_s if duration_s > 0 else 1.0
                self._advance_shot_counters(room, zone, size_pct * run, delivered_l=nominal_l * run,
                                            steering=steering)

        pending = [None]  # the switch sent ON and not yet read back ON

        def switch_on(ent, what, lead_s=0.0, until=None):
            """Switch `ent` on and read it back ON, then let what is left of `lead_s` from its ack run out
            -> (None, _, _) or (why not in the words of its alert, whether it may have been on all the same,
            what it does to the zone's run of failed shots: "count", "reset" (it read ON just too late) or
            "keep" (the shot's own time cut the read-back short: not a definite failure)). A relay that takes the command and stays off must not be counted as a shot. The read-back runs
            inside the lead time, so a switch that reports promptly costs a normal shot nothing; one that
            reports late stretches the pump's prime or the main line's lead by the difference. A read-back
            cut short by `until` (the monotonic clock) may have been on: nothing proved it off in time."""
            pending[0] = ent  # sent ON, not yet read back ON (_close_cut_short)
            if not hw_call(ent, True):
                if _GATE.state == "all":  # the token refused: not a switch that failed (no CS-302 to CS-304)
                    raise _ShotStopped(("refused", None))
                return f"Home Assistant returned an error when the controller tried to {what}.", False, "count"
            acked, reads = time.monotonic(), []
            # The operator's switches are read through the read-back and the lead time too (_ShotStopped),
            # each check bounded by the end of its stage.
            def stop(end):
                return self._operator_stop(room, zone, 2.0, end, holds=True)

            # inside a prime or lead under 1 s, the first read comes at its end: a prompt report costs nothing
            first = min(lead_s, CONFIRM_FIRST_READ_S) if lead_s > 0 else CONFIRM_FIRST_READ_S
            if not self._confirm_switches((ent,), "on", reads=reads, stop=stop, until=until, first=first):
                # once more as it is switched off: an ON just after the window
                reads.append(hw_get(ent, timeout=2.0)[0])
                if _GATE.state == "all":  # refused late in the read-back: not a switch that failed either
                    raise _ShotStopped(("refused", None))
                cut = until is not None and time.monotonic() >= until
                waited = min(SWITCH_ON_S, until - acked) if until is not None else SWITCH_ON_S
                # "opening" (a valve. entity on its way) or anything but a definite OFF may be open
                tally = "reset" if reads[-1] == "on" else "keep" if cut else "count"
                return (f"Home Assistant took the command to {what}, but it did not read on within "
                        f"{waited:.0f} s."), cut or any(state != "off" for state in reads), tally
            pending[0] = None
            while (left := lead_s - (time.monotonic() - acked)) > 0:
                by = stop(acked + lead_s)
                if by:
                    raise _ShotStopped(by)
                time.sleep(min(2.0, left))
            return None, False, None

        def cancelled(why, named, delivered_s=None, tally="count"):
            """The shot cancelled because a switch did not read on (`delivered_s`: the valve may have been
            open that long, and is counted). A definite failure (`tally` "count") is one more such shot in a
            row for this zone (_switch_on_retry_at); a switch that read ON just too late ("reset") ends the
            run; one whose read-back the shot's own time cut short ("keep") leaves it as it is
            -> its alert's message and quiet."""
            st = room.state[zone]
            failures = (st.get("on_failures") or {}).get("count", 0)
            if tally == "count":
                failures += 1
                st["on_failures"] = {"count": failures, "last": datetime.now().isoformat()}
            elif tally == "reset":
                st["on_failures"], failures = None, 0
            water = (
                "No water went to the zone, and the controller did not count the shot."
                if delivered_s is None
                else "The controller cannot tell whether water went to the zone, so it counts the "
                f"{delivered_s:.0f} s from opening the valve to closing it as delivered."
            )
            backoff = (
                f" The last {failures} shots of this zone in a row could not start, so the controller "
                f"now tries this zone at most once every {SWITCH_ON_BACKOFF_MIN} min, rescue shots too, until "
                "its switches read on again."
                if tally == "count" and failures >= SWITCH_ON_BACKOFF_AFTER
                else ""
            )
            # the zone backing off is news: never held back
            quiet = not (tally == "count" and failures == SWITCH_ON_BACKOFF_AFTER)
            return f"{why} {water} {_CANCELLED_SHOT_CLEANUP}{backoff}\n\n{named}", quiet

        def stopped_early(aborted, elapsed):
            """A shot the operator's switches (or a refused token) ended early: CS-305, or a log line.
            `elapsed` None: it stopped before its valve was sent ON."""
            when = (f"after {elapsed:.0f} s of {duration_s:.0f} s" if elapsed is not None
                    else f"before its valve opened (a {duration_s:.0f} s shot)")
            if aborted[0] == "refused":
                log(f"[{room.slug}] Z{zone} shot ended {when}: Home Assistant refused this controller's token")
                return
            by = aborted[1]
            why = {
                room_gate(room): "the kill switch was set to off",
                f"switch.crop_steering_{room.prefix}room_active": "Room Active was set to off",
                f"switch.crop_steering_{room.prefix}zone_{zone}_enabled": "this zone was set to off",
            }.get(by, "manual override was set to on")
            self._alert(
                f"killshot_{room.slug}_z{zone}",
                "CS-305",
                "shot stopped early",
                f"The shot stopped {when}, because "
                f"{why} ({by}). The controller set the valve and the hardware upstream of it to off. "
                "It counts the water of the shot up to the stop.",

                room=room,
                zone=zone,
            )

        try:  # from the moment _busy is set: an error before any valve opens must not leave it set
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
            saved = self._save_state()
            unsaved = getattr(self, "_unsaved_rooms", {}).get(room.slug)
            if not saved or unsaved:  # no record on disk, nothing opens (raised below: CS-212)
                raise RuntimeError(f"Z{zone} shot refused, its in-flight record was not saved: "
                                   f"{unsaved or 'the state file could not be written'}")
            commanded = True
            # OPEN sequence — FAIL CLOSED: if any service call errors, cut what's on, alert, and DO NOT count the shot
            # (otherwise daily_vol / last_shot lie after an auth/entity/service failure and a zone silently starves).
            # Pump and mainline are optional (a one-switch tent has neither): each is sequenced when
            # mapped and skipped, with its lead time, when not. The valve is always required.
            why, _maybe, tally = switch_on(pump, "start the pump", prime) if pump else (None, False, None)
            if why:
                hw_call(pump, False)  # it may be on all the same: off before the alert
                message, quiet = cancelled(why, f"Pump: {pump}", tally=tally)
                self._alert(f"hw_{room.slug}_z{zone}", "CS-302", "shot cancelled, the pump did not start",
                            message, room=room, zone=zone, quiet=quiet)
                return
            why, _maybe, tally = (switch_on(mainline, "open the main-line valve", lead) if mainline
                                  else (None, False, None))
            if why:
                hw_call(mainline, False)  # it may open all the same
                if pump:
                    hw_call(pump, False)
                message, quiet = cancelled(why, f"Main-line valve: {mainline}", tally=tally)
                self._alert(f"hw_{room.slug}_z{zone}", "CS-303", "shot cancelled, the main-line valve did not open",
                            message, room=room, zone=zone, quiet=quiet)
                return
            # The valve's read-back runs inside the shot's own time, counted from its turn_on. A valve that
            # reports late enough can hold a very short shot open past its nominal length: that time is
            # counted too, so such a shot is over-counted, never under-counted (the safe direction).
            # And it ends with the shot: a valve not read ON once the shot's time (or, for a shot shorter
            # than it, the first read-back stage) is up may be open, and is closed and counted, so a late
            # report cannot run a short shot to several times its length.
            valve_started = time.monotonic()
            valve_opened = datetime.now(timezone.utc)  # on Home Assistant's clock too: see _close_cut_short
            why, maybe_open, tally = switch_on(valve, "open the valve of this zone",
                                        until=valve_started + max(duration_s, CONFIRM_TIMEOUT_S))
            if why:
                hw_call(valve, False)  # it may open all the same
                for upstream in (mainline, pump):
                    if upstream:
                        hw_call(upstream, False)
                delivered_s = None
                if maybe_open:
                    # Unreadable, or ON too late: water may have flowed. Count it to the off, as a stop does.
                    delivered_s = time.monotonic() - valve_started
                    count_water_so_far()
                message, quiet = cancelled(why, f"Valve: {valve}", delivered_s, tally)
                self._alert(f"hw_{room.slug}_z{zone}", "CS-304", "shot cancelled, the zone valve did not open",
                            message, room=room, zone=zone, quiet=quiet)
                return
            room.state[zone]["on_failures"] = None  # pump, main line and valve all read on
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
            if aborted:
                stopped_early(aborted, elapsed)
        except _ShotStopped as stopped:
            # The operator (or a refused token, or a hold) stopped the shot while it was opening. Not a switch
            # that failed to switch on, so no backoff. Water counts only from the valve's turn_on, to the stop.
            # A failure in here is logged, and the cleanup below runs as after any shot error.
            try:
                elapsed = None if valve_started is None else time.monotonic() - valve_started
                if stopped.by[0] == "external":
                    # As _wait_shot's: only what is still this shot's is closed, never a pump a hold now owns.
                    elapsed = self._close_cut_short(room, zone, stopped.by[1], elapsed or 0.0, duration_s,
                                                    valve_opened or datetime.now(timezone.utc), pending[0])
                    shutdown_checked = True
                if valve_started is not None and not counted:
                    counted = True
                    run = elapsed / duration_s if duration_s > 0 else 1.0
                    self._advance_shot_counters(room, zone, size_pct * run, delivered_l=nominal_l * run,
                                                steering=steering)
                if stopped.by[0] != "external":  # _close_cut_short raised its CS-307
                    stopped_early(stopped.by, elapsed)
            except Exception as e:
                log("shot error", room.slug, zone, e)
                errored = True  # its water is still counted, after the cleanup below (count_water_so_far)
        except SystemExit:
            # SIGTERM/SIGINT mid-shot (the app stopped or updated): _safe_exit has already closed what this
            # shot has open, by the reconciler's rules, so the cleanup below must not switch the rest off.
            # Count the water this shot delivered before the process goes, or the next start would water
            # the zone as if it had had none.
            stopping = True
            count_water_so_far()
            raise
        except Exception as e:
            log("shot error", room.slug, zone, e)
            errored = True
            if not commanded:  # nothing opened: the room's pass stops here and says so (CS-212)
                raise
        finally:
            try:
                # Early command failures and unexpected exceptions need the SAME hold
                # guarantee as normal shutdown; no path may start the next row blindly.
                if not commanded and not stopping:
                    # Nothing was sent ON, so nothing is switched off (a person may be running the pump),
                    # and the record of this shot (it held every shot of the room until reconciled) goes.
                    if getattr(room, "shot_inflight", None):
                        room.shot_inflight = None
                        try:
                            self._save_state()
                        except Exception as e:
                            log("state save failed", e)
                elif not shutdown_checked and not stopping:
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
                    if (refused or not closed) and _GATE.state == "all":
                        # Refused, not stuck (as after a normal close): left recorded for the reconciler.
                        log(f"[{room.slug}] Z{zone} shot cleanup with Home Assistant refusing: its offs were "
                            "sent, not read back; left recorded")
                    elif refused or not closed:
                        self._latch_hardware_fault(
                            room,
                            f"zone {zone} shot error cleanup",
                            self._close_failures(closing, refused),
                        )
                    else:
                        room.shot_inflight = None
                        self._save_state()
                if errored:  # after the close, as a normal shot is: its time counts too
                    count_water_so_far()
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
        # The signal lands on the main loop: in the middle of a dosing switch-on, the way out waits for
        # that call to land (dosing_runner.defer_exit), so dosing's offs come after it.
        try:
            if self.dosing is not None and self.dosing.defer_exit(lambda: self._exit_within(budget, deadline)):
                return
        except Exception as e:
            log("dosing: could not be asked to hold the way out:", e)
        self._exit_within(budget, deadline)

    def _exit_within(self, budget, deadline):
        try:
            try:
                # Dosing starts nothing from here on. Then the shot in flight: it is water running now.
                # Dosing's own offs go last, in the time the stop keeps for them.
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
                        "controller_instance": self.instance_id,  # ours: not another controller's write
                        "controller_runtime": "container" if _GATE.container else "addon",
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
        """Stopping: no dosing switch-on starts from here, and what a dose or batch has recorded is
        switched off again, each off with a short timeout
        (dosing_runner.exit), all before the stop's `deadline` (the monotonic clock) when given. Its
        record stays in dosing_state.json, so the next start reads it back OFF and raises CS-803."""
        try:
            if self.dosing is not None:
                self.dosing.exit(None if deadline is None else max(0.0, deadline - time.monotonic()))
        except Exception as e:
            log("dosing: could not switch off on the way out:", e)

    def _start_dosing(self):
        """Before the first loop: settle what a dose or batch left running before this start
        (docs/DOSING.md, After a restart). It cannot stop the controller starting: a failure is tried
        again by every dosing step (dosing_runner.step)."""
        if self.dosing is None:
            return
        try:
            self.dosing.recover()
        except Exception as e:
            log("dosing: start-up recovery failed; dosing tries again:", e)

    def _sleep_for(self, seconds):
        """Wait `seconds` for the next pass, waking whenever dosing is due to run its next step
        (dosing_runner.step). A shot's wait does the same while a dose or batch runs (_wait_shot)."""
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            due = self.dosing.step() if self.dosing is not None else left
            time.sleep(max(0.0, min(left, due)))

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
        # The zone's Manual shot length, when its number can be read (an integration before it has none):
        # TEST_SHOT_S otherwise. _act_zone still cuts it to the room's longest shot and the day's budget left.
        asked = self._num_or_none(f"number.crop_steering_{room.prefix}zone_{zone}_manual_shot_seconds")
        seconds = int(asked) if asked is not None and math.isfinite(asked) and asked >= MIN_SHOT_S else TEST_SHOT_S
        # Unsized, _act_zone says why (CS-204) and runs nothing.
        size = seconds * flow / substrate * 100.0 if sized else 0.0
        reason = Reason(f"TEST shot {seconds} s (asked for)", "test_shot")
        reason.seconds = seconds
        if seconds != TEST_SHOT_S:
            log(f"[{room.slug}] Z{zone} MANUAL shot {seconds} s (asked for)")
        return True, size, reason

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
                "URGENT, the zone is dry and gets no shots",
                f"This zone is dry (VWC {snap.vwc:.0f}%, below its re-water point of {p.p2_threshold:.0f}%) and "
                + (
                    "the controller has not watered it"
                    if snap.minutes_since_shot > 1e8
                    else f"has had no shot for {snap.minutes_since_shot/60.0:.1f} h"
                )
                + ". Something blocks each shot. If you set it to off on purpose, this alert tells you "
                f"that the plants become dry.\n\nBlocked by: {block}",
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
                    "shot size cannot be calculated, no shots",
                    "To calculate a shot, the controller needs the substrate volume (litres for each plant), "
                    "the plant count, the drippers for each plant and the dripper flow of this zone. One of "
                    "these is missing, zero or not readable. Set them in Rooms & setup.",
                    room=room,
                    zone=zone,
                )
                return
            test = getattr(reason, "kind", None) == "test_shot"
            raw_dur = float(getattr(reason, "seconds", TEST_SHOT_S)) if test else size / 100.0 * substrate / flow
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
                    "shot cut to the safety limit",
                    f"The planned shot was {int(raw_dur)} s, more than the {int(max_dur)} s limit of the "
                    f"room. The shot runs for {int(max_dur)} s and gives less water than planned. Check the "
                    "substrate volume and the dripper flow of this zone. If they are correct, increase the "
                    "maximum shot length.",
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
            what, why = log_words.shot(reason)
            log(f"[{room.slug}] Z{zone} {st['phase']} FIRE {size}% ~{dur}s — {what}: {why}")
            # Count configured flow x actual runtime, including caps, truncation,
            # the minimum duration and partial aborts. Preserve this flow snapshot
            # so later sizing edits cannot change an already delivered volume.
            rescue = getattr(reason, "kind", None) in safety_ops.RESCUE_KINDS and self._rescue_watch_on(room)
            if rescue and snap is not None:  # the last rescue, judged before this one changes the moisture
                self._rescue_judged(room, zone, safety_ops.rescue_judge(st, snap.vwc, now, early=True))
            was = st.get("last_shot")
            self._execute_shot(room, zone, dur, size, flow_lps=flow,
                               plan_exempt=getattr(reason, "kind", None) in PLAN_HOLD_EXEMPT, steering=not test)
            if rescue and snap is not None and st.get("last_shot") is not was:
                safety_ops.rescue_fired(st, snap.vwc, now)
                self._save_state()
            # A test or manual shot cut to the longest shot is not one of CS-312's run (it resets it, as before).
            self._count_capped(room, zone, raw_dur > max_dur and not test)
        else:
            if "BLOCK" in reason and (
                getattr(reason, "kind", None) == "block_daily_cap" or "daily-cap" in reason
            ):
                self._alert_daily_cap(room, zone, st, snap is None, reason)
            elif "BLOCK" in reason:
                self._alert(
                    f"block_{room.slug}_z{zone}",
                    "CS-206",
                    "zone EC too high, no shots",
                    "The EC of this zone is above its maximum EC. A flush cannot decrease it now, because "
                    "the feed EC is not lower than the EC of the zone, or the cube is at field capacity. "
                    "So the controller holds the zone. No shot runs, including the rescue shot and the "
                    "watchdog shot. The hold stops when a flush can help. CAUTION: Check the feed EC and "
                    "the EC probe now. The plants can become too dry before the hold stops."
                    f"\n\nDetail ({st['phase']}): {reason}",
                    room=room,
                    zone=zone,
                )
            # A gate that is closed is said out loud in every phase: overnight nothing is due, and a
            # room blocked since a restart used to look exactly like a healthy one until lights-on.
            log(f"[{room.slug}] Z{zone} {st['phase']} hold — {log_words.hold(reason) or 'nothing due'}"
                + (f" [blocked: {block}]" if block else ""))

    # ---------- CS-315: rescue shots that do not raise the moisture (alert only) ----------
    def _rescue_watch_on(self, room):
        """The room's select rescue_miss_action reads Alert. Off (or unreadable): nothing is counted, as before."""
        return ha_get(f"select.crop_steering_{room.prefix}rescue_miss_action")[0] == "Alert"

    def _watch_rescues(self, room, zone, snap, now):
        """Judge the zone's last rescue once it has settled (safety_ops.rescue_judge). Never holds water."""
        st = room.state[zone]
        if not self._rescue_watch_on(room):
            st["rescue_check"] = None
            return
        if st.get("rescue_check"):
            self._rescue_judged(room, zone, safety_ops.rescue_judge(st, snap.vwc, now))

    def _rescue_judged(self, room, zone, missed):
        """After a rescue was judged: CS-315 at the room's Rescue misses before alert in a row, down at the next rise."""
        if missed is None:
            return
        self._save_state()
        st, key = room.state[zone], f"rescue_miss_{room.slug}_z{zone}"
        if not missed:
            self._dismiss(key)
            return
        limit = self._num(f"number.crop_steering_{room.prefix}rescue_miss_count", safety_ops.RESCUE_MISS_DEFAULT)
        misses = int(st.get("rescue_misses") or 0)
        log(f"[{room.slug}] Z{zone} rescue shot not absorbed: moisture rose less than "
            f"{safety_ops.RESCUE_MIN_RISE:g} points ({misses} in a row)")
        if misses >= max(1, int(limit)):
            self._alert(
                key,
                "CS-315",
                "rescue shots do not raise the moisture",
                f"The last {misses} rescue shots of this zone did not raise its moisture. Possible causes are a "
                "blocked dripper or line, a valve that does not open, or a probe that is out of the substrate. The "
                "controller continues the rescue shots; this alert does not stop any water. CAUTION: Go to the zone "
                "now. Check the drippers, the valve and the probe. A blocked line keeps the plants dry, and a line "
                "that leaks puts the water on the floor.",
                room=room,
                zone=zone,
            )

    # ---------- CS-317: the feed pump runs with every valve shut (dead-head, alert only) ----------
    def _watch_deadhead(self, room, now):
        """The room's pump (option pump_power_sensor) draws more than its Pump Dead-Head Power while every zone valve
        of the room reads off, for DEADHEAD_S, with no shot in flight, no hold on and no batch running. Only tells."""
        entity = self.pump_power.get(room.slug) or self.pump_power.get("*")
        if not entity or not room.hw.get("pump"):
            return
        key = f"deadhead_{room.slug}"
        busy = (getattr(room, "shot_inflight", None) or self._dosing_hold(room)
                or (self.dosing is not None and self.dosing.running())
                or any(self._on(f, False) for f in self.hold_entities))
        watts = self._device(entity, "power")[0]
        limit = self._num(f"number.crop_steering_{room.prefix}pump_deadhead_watts", DEADHEAD_W)
        shut = all(hw_get(v)[0] == "off" for v in room.hw.get("valves", {}).values())
        if busy or watts is None or watts <= limit or not shut:
            room._deadhead_since = None
            if not busy and watts is not None:
                self._dismiss(key)
            return
        since = room._deadhead_since = room._deadhead_since or now
        if (now - since).total_seconds() < DEADHEAD_S:
            return
        self._alert(
            key,
            "CS-317",
            "the pump runs with every valve shut",
            f"The pump of this room uses {watts:.0f} W, more than its {limit:g} W dead-head power, and every zone valve "
            "reads off. No shot, hold or batch uses the pump now. A pump that runs against shut valves heats up and "
            "can be damaged. The controller does not switch it off. CAUTION: Check the pump now. Stop it, or open "
            f"the valve that it should feed.\n\nSensor: {entity}",
            room=room,
        )

    # ---------- CS-905: the tank level estimated from the water the shots used (alert only) ----------
    def _tank_estimate_filled(self, room, at=None):
        """The tank was filled (a batch that read full, or the room's Tank filled button): the count starts again."""
        at = at or datetime.now(timezone.utc).isoformat()
        if safety_ops.tank_filled(room.tank_estimate, at):
            log(f"[{room.slug}] estimated tank level: filled at {at[:16]}, the count starts again")
            self._save_state()

    def _watch_tank_estimate(self, room):
        """With no tank level mapped and a Tank size above 0: publish the level estimated from the litres the shots
        used since the tank was last filled, on the room's tank_level sensor (source estimate). Never holds a shot."""
        size = self._num(f"number.crop_steering_{room.prefix}tank_size_l", 0)
        if not size or size <= 0:
            return
        pressed = ha_get(f"button.crop_steering_{room.prefix}tank_filled")[0]
        if pressed not in (None, "", "unknown", "unavailable"):
            self._tank_estimate_filled(room, pressed)
        estimate = room.tank_estimate
        pct, left = safety_ops.tank_percent(estimate, size)
        low = self._num(f"number.crop_steering_{room.prefix}tank_estimate_low_pct", safety_ops.TANK_LOW_DEFAULT)
        ha_set(
            f"sensor.crop_steering_{room.prefix}tank_level",
            pct if pct is not None else "unknown",
            {
                "unit_of_measurement": "%",
                "friendly_name": "Tank level",
                "source": "estimate",
                "litres_left": left,
                "size_l": size,
                "used_l": round(float(estimate.get("used_l") or 0.0), 1),
                "filled_at": estimate.get("filled_at"),
                "low_alert_pct": low,
                "holds_shots": False,
                "engine": PRODUCT,
            },
        )
        key = f"tank_estimate_{room.slug}"
        if pct is not None and pct <= low:
            self._alert(
                key,
                "CS-905",
                "the estimated tank level is low",
                f"From the water that the shots used since the tank was filled, the tank of this room has about "
                f"{left:.0f} L left ({pct:.0f}% of {size:g} L). This is an estimate from the dripper flow settings, "
                "not a measurement, so the shots continue. Refill the tank, then press Tank filled.",
                room=room,
            )
        else:
            self._dismiss(key)

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
                "This zone got its daily water limit. It has no usable moisture reading, so each of "
                "its shots is a copied or a timed shot, and no shot is exempt. The zone gets no more "
                "water until the next lights-on, including the rescue shot. Check its probe. The "
                "moisture alert of this zone tells what is wrong."
                if blind
                else "This zone got its daily water limit. The maintenance shots and the EC shots "
                "stop until the next lights-on. The ramp, the rescue shot, the watchdog shot and "
                "the high-EC flushes continue."
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
            if per in getattr(room, "_settings_missing", ()) and per not in seen:
                unread.append(per)  # the zone's own number reads no number: never the room's value instead
            elif per not in seen and glob not in seen:
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
            key = [what for part, what in (("substrate_volume", "the substrate volume"),
                                           ("plant_count", "the plant count"),
                                           ("drippers_per_plant", "the drippers per plant"),
                                           ("dripper_flow_rate", "the dripper flow"),
                                           ("max_daily_volume", "the daily water limit"))
                   if any(e.endswith(part) for e in persistent)]
            self._alert(
                "defaulted_setpoints",
                "CS-402",
                "settings missing, the controller uses built-in values",
                "The controller cannot read these settings in Home Assistant. It uses the last value that "
                "it read since it started, else, for a zone's own setting, the room's value, else its built-in value"
                + (f". {' and '.join(key).capitalize()} set the water of a zone. A zone that has not read "
                   "one of them since the controller started gets no shots, including rescue shots, until "
                   "the setting is back"
                   if key else ". Make sure that these values are correct for this room")
                + ". Reload the integration. If Repairs lists settings at unexpected entity IDs, do the "
                "steps of CS-605.\n\n"
                + "\n".join(persistent[:20]),
            )

    def loop_once(self, now):
        if self._busy:
            return
        self._notify_config(refresh=True)  # who gets pushes, read here so an alert never waits on it
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
            try:  # one room's error never stops the rooms after it, nor the steps after the rooms
                self._guard_read(room)  # before this pass writes the room's heartbeat
                self._refresh_lights(room)
                pub = self._loop_room(room, now)
                self._publish_status(room, pub, now)
                all_pub[room.slug] = pub
                if f"room_error_{room.slug}" in self._alerted:  # its pass ran again: CS-212 is over
                    ha_call("persistent_notification", "dismiss", notification_id=f"f2_room_error_{room.slug}")
                    del self._alerted[f"room_error_{room.slug}"]
            except Exception as e:  # only Exception: a stop (SystemExit, KeyboardInterrupt) still stops
                self._room_error(room, now, e)
        self._check_defaulted_setpoints()
        self._maybe_notify(all_pub, now)
        self._send_events()

    def _room_error(self, room, now, err):
        """A room's pass raised (loop_once). The room says so: its heartbeat and its status read error,
        its decision fires nothing (an earlier pass's shot must not look live), and CS-212 names it, at
        most each 30 min while the fault stays (_alert); loop_once dismisses it after the room's next
        pass. The report and the alert are tried apart, so one that fails as well never stops the
        other, nor the next room."""
        error = f"{type(err).__name__}: {err}"
        log(f"[{room.slug}] room error", error)
        try:
            ha_set(f"sensor.crop_steering_{room.prefix}app_status", "error",
                   {"engine": PRODUCT, "updated": now.isoformat()})
            ha_set(f"sensor.crop_steering_{room.prefix}current_decision", f"Controller error: {error}"[:255],
                   {"fired": [], "blocked": [f"Controller error: {error}"]})
            active = room._beat[1] if room._beat else True  # as its last beat said: an off room stays off
            self._heartbeat(room, now, self._hardware_fault_block(room), active, loop_error=error)
        except Exception as e:
            log(f"[{room.slug}] room error report error", e)
        try:
            self._alert(
                f"room_error_{room.slug}",
                "CS-212",
                "controller error, this room is skipped",
                "An error stopped the controller in this room. The room gets no shots until the error "
                "stops. The controller tries the room again each minute, and the other rooms continue. "
                f"Read the controller log, and report the error.\n\n{error}",
                room=room,
            )
        except Exception as e:
            log(f"[{room.slug}] room error alert error", e)

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
                "a second controller writes the heartbeat of this room, hold",
                "A different controller reports for this room. This controller does not water or dose in "
                "this room until it sees no other report for 3 min. After an update, this is usual: the "
                "old version reported with no ID, and this alert clears in about 3 min. If the alert "
                "stays, two controllers run this room (an app and a container, or two apps). Stop and "
                "remove the controller that you do not use.",

                room=room,
            )
        self._heartbeat(room, now, self._hardware_fault_block(room))

    def _blind_time_transition(self, room, zone, now, lights_on, lights_just_on, p=None):
        """Time-only phase forces for a BLIND zone (dead/missing probe), so it can never
        strand overnight while `decide()` is skipped: lights-off -> P3, and P3 -> P0 at the
        new photoperiod (with the daily-counter reset, mirroring the P0 branch in _loop_room),
        also from a P1/P2 left over from a grow-day the controller did not see end (as decide()).
        With the zone's params `p`, decide()'s two exits that need no probe as well: P0 -> P1
        once p0_max_wait_min has passed, and P1 -> P2 at p1_max_shots. The VWC-driven
        transitions (dryback, the P1 rise rule, predictive P3) need a probe and stay paused.
        """
        st = room.state[zone]
        gds = self._grow_day_start(room, now)
        new_grow_day = self._new_grow_day(room, st, now, lights_on)
        waited = (now - st["last_phase_change"]).total_seconds() / 60.0
        new_phase = None
        why = None
        if not lights_on and st["phase"] != "P3":
            new_phase, why = "P3", "lights-off (no moisture reading)"
        elif st["phase"] == "P3" and (lights_just_on or new_grow_day):
            new_phase, why = "P0", "lights-on (no moisture reading)"
        elif st["phase"] in ("P1", "P2") and new_grow_day:
            new_phase, why = "P0", "a new grow-day (no moisture reading)"
        elif p is not None and st["phase"] == "P0" and waited >= p.p0_max_wait_min:
            new_phase, why = "P1", f"P0 timeout {waited:.0f}min (no moisture reading)"
        elif p is not None and st["phase"] == "P1" and st["shots"] >= p.p1_max_shots:
            new_phase, why = "P2", f"P1 max shots {st['shots']}/{p.p1_max_shots} (no moisture reading)"
        if new_phase and new_phase != st["phase"]:
            if new_phase == "P0":
                self._close_grow_day(room, zone, st, now, p)
                self._keep_day_peak(st)  # the grow-day ending: tomorrow's P1 target (_vwc_maxima)
                st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, 0.0  # _snapshot takes the peak from the next reading
                st["ec_offset"], st["last_ec_steer"] = 0.0, None
                st["last_daily_reset"] = gds
            if new_phase == "P1":  # the ramp counts its shots from one again, as the engine's own P1 does
                self._record_phase(room, zone, st, st["phase"], "P1", now, why)
                st["shots"] = 0
            was = st["phase"]
            st["phase"] = new_phase
            st["last_phase_change"] = now
            log(f"[{room.slug}] Z{zone} {was} -> {new_phase}: {why}")
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

    def _no_touch_until(self, room, now):
        """When the room's no-touch window ends, or None when none runs. The operator chose it on the room's
        Pause AI Changes select; it runs from that choice (the select's `since`, else when its value changed)
        for an hour, a day or until the next lights-on. Once it is over the select is set back to Off."""
        entity = f"select.crop_steering_{room.prefix}ai_no_touch"
        read = ha_get(entity)
        if read[0] not in NO_TOUCH_HOURS:
            return None  # Off, or a Home Assistant without the select
        since = _aware(read[1].get("since") or read.last_changed)
        if since is None:
            return None
        since = since.astimezone().replace(tzinfo=None)
        hours = NO_TOUCH_HOURS[read[0]] or self._hours_to(since, room.lights_on_hour) or 24.0
        until = since + timedelta(hours=hours)
        if now < until:
            return until
        ha_call("select", "select_option", entity_id=entity, option="Off")
        return None

    # ---------- plan adherence (plan_adherence.py): is the room running its grow plan? ----------
    PLAN_FETCH_H = 6.0  # the plan itself is fetched again at least this often while it exists
    PLAN_NATIVES_MIN = 15.0  # the numbers a running plan controls are read this often (an edit by hand)

    def _plan_fetch(self, room, now, state, attrs, expected_day, lights_on_at):
        """The plan (strategy_get) and today's and yesterday's previews (strategy_preview), kept on the room and
        fetched again only when the plan sensor's revision, status or day changes, once 10 min after lights-on and
        every PLAN_FETCH_H hours: the integration's own code says what the plan wants, never this controller's.
        A call that fails keeps what was had; its age says how old it is. -> the runtime record."""
        rt = room.__dict__.setdefault("_plan_rt", {"key": None, "at": None, "plan": None, "preview": {},
                                                   "natives_at": None, "natives": None})
        rev = attrs.get("revision")
        if state not in ("draft", "armed", "active", "disarming", "error") or (
                state == "draft" and not (type(rev) is int and rev >= 1)):
            rt.update(key=None, at=None, plan=None, preview={}, natives_at=None, natives=None)
            return rt
        key = (rev, state, attrs.get("grow_day"))
        settled = lights_on_at + timedelta(minutes=10) if lights_on_at is not None else None
        due = (rt["key"] != key or rt["at"] is None or now - rt["at"] >= timedelta(hours=self.PLAN_FETCH_H)
               or (settled is not None and rt["at"] < settled <= now))
        room_id = {"room_id": f"room:{room.prefix}"}
        if due:
            status, body = ha_service_response("crop_steering", "strategy_get", room_id)
            if status == 200 and isinstance(body, dict) and isinstance(body.get("plan"), dict):
                previews = {}
                if state in ("armed", "active", "disarming"):
                    for name, day in (("today", expected_day), ("yesterday", expected_day - timedelta(days=1))):
                        got = ha_service_response("crop_steering", "strategy_preview",
                                                  {**room_id, "date": day.isoformat()})[1]
                        rows = ((got or {}).get("preview") or {}).get("zones") if isinstance(got, dict) else None
                        if isinstance(rows, list):
                            previews[name] = {r["zone_id"]: r for r in rows
                                              if isinstance(r, dict) and type(r.get("zone_id")) is int}
                rt.update(key=key, at=now, plan=body, preview=previews)
        if state in ("active", "disarming") and rt["plan"] is not None and (
                rt["natives_at"] is None or now - rt["natives_at"] >= timedelta(minutes=self.PLAN_NATIVES_MIN)):
            wanted = {e for z in (rt["plan"].get("catalog") or {}).values() for v in (z or {}).values()
                      for e in (v or {}).get("entity_ids") or ()}
            found = {}
            for st in ha_get_all():
                if st.get("entity_id") in wanted:
                    try:
                        found[st["entity_id"]] = float(st.get("state"))
                    except (TypeError, ValueError):
                        pass
            rt.update(natives=found, natives_at=now)
        return rt

    def _plan_view(self, room, now, lights_on, params):
        """This pass of the room as plan adherence reads it (plan_adherence.View)."""
        state, attrs = getattr(room, "_strategy_raw", None) or (None, {})
        expected = self._grow_day_start(room, now)
        lights_on_at = (None if room.lights_on_hour == room.lights_off_hour
                        else datetime.combine(expected, datetime.min.time()) + timedelta(hours=room.lights_on_hour))
        rt = self._plan_fetch(room, now, state, attrs, expected, lights_on_at)
        source = getattr(room, "_lights_source", "integration")
        rt["lights_bad_since"] = None if source == "integration" else (rt.get("lights_bad_since") or now)
        if attrs.get("degraded_kind") != rt.get("degraded_kind"):  # since when, as this controller first saw it
            rt["degraded_kind"], rt["degraded_since"] = attrs.get("degraded_kind"), now
        light = getattr(room, "light_entity", "")  # the room's grow light, when setup maps one
        light_state = ha_get(light)[0] if light else None
        light_state = light_state if light_state in ("on", "off") else None
        disagrees = light_state is not None and (light_state == "on") != lights_on
        rt["light_since"] = (rt.get("light_since") or now) if disagrees else None
        zones = {}
        for z in room.zones:
            st, p = room.state[z], params.get(z)
            zones[z] = {"phase": st.get("phase"), "last_phase_change": st.get("last_phase_change"),
                        "last_daily_reset": st.get("last_daily_reset"), "shots": st.get("shots"),
                        "blind": z in getattr(room, "_blind_zones", set()),
                        "p0_wait": getattr(p, "p0_max_wait_min", None), "p1_shots": getattr(p, "p1_max_shots", None),
                        "p1_gap": getattr(p, "p1_time_between_min", None)}
        active = state == "active"
        return plan_adherence.View(
            now=now, expected_day=expected, uptime_min=(now - self._start).total_seconds() / 60.0,
            lights_on=lights_on, on_hour=room.lights_on_hour, off_hour=room.lights_off_hour, lights_source=source,
            status=state if state in ("draft", "armed", "active", "disarming", "error") else "none", attrs=attrs,
            plan=rt["plan"], plan_age_h=None if rt["at"] is None else (now - rt["at"]).total_seconds() / 3600.0,
            preview=rt["preview"], natives=rt["natives"],
            steering={z: "vegetative" if self._veg(room, z) else "generative" for z in room.zones} if active else {},
            zones=zones, titles={z: self._zone_title(room, z) for z in room.zones},
            lights_bad_since=rt["lights_bad_since"], light_state=light_state, light_since=rt["light_since"],
            slug=room.slug)

    def _watch_plan(self, room, now, lights_on, params):
        """Plan adherence, every pass under every brain: the drifts code finds (plan_adherence.detect), one CS-713
        card per episode, the plan line for the brain panel and, under the Claude brain, its plan task. It never
        writes a number, and never arms, edits or disarms a plan."""
        adh = room.__dict__.setdefault("_adherence", plan_adherence.fresh())
        before = json.dumps(adh, sort_keys=True, default=str)
        view = self._plan_view(room, now, lights_on, params)
        on = view.lights_on_at
        day_start = now if on is None else (on if now >= on else on - timedelta(days=1))
        hows = {z: str(d[2]) for event, r, z, d in self.__dict__.get("_events", [])
                if event == "phase" and r is room and len(d) > 2}
        for z in room.zones if plan_adherence.has_plan(view) else ():  # a room with no plan keeps no record
            plan_adherence.observe(adh, z, room.state[z].get("phase"), now, hows.get(z), day_start)
        drifts = plan_adherence.detect(view, adh)
        for d in drifts:
            if not plan_adherence.due(adh, d, view.expected_day):
                continue
            if d.cls in plan_adherence.TRIPWIRES:
                log(f"[{room.slug}] PLAN TRIPWIRE {d.cls} Z{d.zone}: {d.line} state={room.state.get(d.zone)}")
            words = d.line[:1].upper() + d.line[1:]
            if self._alert(d.key, "CS-713", d.title, f"{words}\n\n{d.suggestions[0]}" if d.suggestions else words,
                           room=room, zone=d.zone):
                plan_adherence.raised(adh, d, view.expected_day)
        notes = None
        if getattr(self, "jev", None) is not None:
            try:  # the brain's plan task (brain_bridge.plan_task): what a drift means, never a write
                notes = brain_bridge.plan_task(self, room, now, view, drifts)
            except Exception as e:
                log("plan task error", room.slug, e)
        room._plan_panel = plan_adherence.panel(view, drifts, notes, adh.get("bridge"))
        if json.dumps(adh, sort_keys=True, default=str) != before:
            self._save_state()

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
        room._strategy_raw = (state, attrs if isinstance(attrs, dict) else {})  # what plan adherence reads
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
        if (getattr(room, "_adherence", None) or {}).get("bridge"):
            room.strategy_snapshot = self._bridged(room, snapshot, state, room._strategy_raw[1], now)

    def _bridged(self, room, snapshot, state, attrs, now):
        """The snapshot with a plan-day catch-up merged in (strategy_runtime.merge_bridge), or without it once it is
        over: the plan applied the day itself (its values should be the same: CS-713 if not), the plan, its zones or
        its revision changed, its day is no longer held by a stale probe, or the next lights-on came. The first pass
        that merges it reads every value back through the read path the engine uses; a mismatch drops it."""
        adh = room._adherence
        bridge = adh["bridge"]
        day = self._grow_day_start(room, now).isoformat()
        zones = {int(z): v for z, v in (bridge.get("zones") or {}).items()}
        rows = snapshot.get("zones") or {}
        why, caught = None, False
        if bridge.get("day") != day:
            why = "the next lights-on came"
        elif (state != "active" or not snapshot.get("required") or snapshot.get("error")
              or bridge.get("revision") != snapshot.get("revision")):
            why = "the plan changed or is held"
        elif not set(zones) <= set(snapshot.get("managed") or ()):
            why = "the plan's zones changed"
        elif all(str((rows.get(z) or {}).get("applied_day") or "") >= day for z in zones):
            why, caught = "the plan applied the day itself", True
            differ = [z for z in zones if (rows.get(z) or {}).get("parameters") != zones[z]]
            if differ:
                self._alert(f"plan_bridge_differs_{room.slug}", "CS-713",
                            "the values of the plan differ from the values that the controller applied",
                            f"The plan applied day {day} itself. Its values for zone(s) "
                            f"{', '.join(map(str, differ))} differ from the values that the controller applied while "
                            "the plan waited. This is not usual. The controller continues with the values of the "
                            "plan. Report this with the controller log.", room=room)
        elif attrs.get("degraded_kind") != "probe_stale":
            why = "the plan's day is no longer held by a stale probe"
        if why is None:
            merged = merge_bridge(snapshot, bridge, day)
            if not bridge.get("checked"):
                room.strategy_snapshot = merged
                read = {(z, k): self._zone_num(room, z, k, None) for z, values in zones.items() for k in values}
                wrong = [(z, k) for (z, k), got in read.items()
                         if got is None or abs(got - float(zones[z][k])) > 1e-6]
                if wrong:
                    why = f"read back {wrong[0][1]} on zone {wrong[0][0]} wrong"
                    adh["cooldown_until"] = (now + timedelta(days=7)).isoformat(timespec="minutes")
                    self._alert(f"plan_bridge_{room.slug}", "CS-713", "today's plan targets could not be applied",
                                "The controller applied the plan targets of today while the plan waited. It could "
                                f"not read them back ({why}). It went back to the targets of the plan, and does not "
                                "try again for 7 days. Report this with the controller log.", room=room)
                else:
                    bridge["checked"] = True
                    self._save_state()
                    return merged
            else:
                return merged
        log(f"[plan] {room.slug} catch-up of day {bridge.get('day')} ended: {why}")
        adh["bridge"] = None
        if caught:
            adh["bridge_outcome"] = bridge.get("day")
        room.strategy_snapshot = snapshot
        room._strategy_batch_invalid = True
        self._save_state()
        return snapshot

    def _restore_unsaved_room(self, room):
        """The room's state could not be saved (_save_state): this pass stops with an error (CS-212).

        Its last saved block is loaded back, as at start-up, so the next pass runs. What only memory holds
        and must not be lost stays: a hardware hold, an in-flight record, and, zone by zone, the newer of
        the shot and water counters (_keep_newer_shots: never less water or an older last shot, so neither
        the daily cap nor the shot interval is lifted). With no saved block to go back to, or when what
        memory must keep is itself what cannot be saved, nothing is pretended: the room stays stopped until
        its state saves or the controller restarts."""
        self._save_state()  # it may save now
        error = self._unsaved_rooms.get(room.slug)
        if not error:
            return
        stopped = "the room stays stopped until it saves or the controller restarts"
        if not isinstance(getattr(self, "_saved_room_blocks", {}).get(room.slug), dict):
            raise RuntimeError(f"the state of this room cannot be saved ({error}), and there is no saved state "
                               f"to go back to: {stopped}")
        fault, inflight = room.hardware_fault, getattr(room, "shot_inflight", None)
        memory = {z: s for z, s in room.state.items() if isinstance(s, dict)}
        self._load_room_state(room)
        room.hardware_fault = room.hardware_fault or fault
        room.shot_inflight = room.shot_inflight or inflight
        for z, mem in memory.items():
            if z in room.state:
                self._keep_newer_shots(mem, room.state[z])
        self._save_state()
        if self._unsaved_rooms.get(room.slug):
            raise RuntimeError(f"the state of this room cannot be saved ({self._unsaved_rooms[room.slug]}), "
                               f"even on its last saved state: {stopped}")
        raise RuntimeError(f"the state of this room could not be saved ({error}); its last saved state "
                           "was loaded back, and the room runs again next pass")

    @staticmethod
    def _keep_newer_shots(mem, s):
        """Into the zone `s` loaded back from the saved block, what memory `mem` has that is newer: the later
        last shot, and the day's counters (memory's whole, when its day is newer; the larger, on the same
        day), and each grow-day's larger water. A value of the wrong type in memory is not kept."""
        def number(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0

        shot = mem.get("last_shot")
        if isinstance(shot, datetime) and (not isinstance(s.get("last_shot"), datetime) or shot > s["last_shot"]):
            s["last_shot"] = shot
            s["last_shot_is_anchor"] = bool(mem.get("last_shot_is_anchor"))
        reset, saved_reset = mem.get("last_daily_reset"), s.get("last_daily_reset")
        if type(reset) is date and (type(saved_reset) is not date or reset > saved_reset):
            s["last_daily_reset"] = reset  # a new day in memory: its counters, not the saved day's
            s["daily_vol"] = mem.get("daily_vol") if number(mem.get("daily_vol")) else s["daily_vol"]
            s["shots"] = mem.get("shots") if number(mem.get("shots")) else s["shots"]
        elif reset == saved_reset:
            for key in ("daily_vol", "shots"):
                if number(mem.get(key)) and mem[key] > (s.get(key) or 0):
                    s[key] = mem[key]
        days = {item["grow_day"]: item for item in s.get("water_history") or []}
        for item in mem.get("water_history") or []:
            if (isinstance(item, dict) and isinstance(item.get("grow_day"), str) and number(item.get("litres"))
                    and item["litres"] > days.get(item["grow_day"], {}).get("litres", -1)):
                days[item["grow_day"]] = {"grow_day": item["grow_day"], "litres": float(item["litres"]),
                                          "complete": item.get("complete") is True}
        if days:
            s["water_history"] = [days[d] for d in sorted(days)[-7:]]

    def _loop_room(self, room, now):
        """One room's full control pass: snapshot -> decide -> act -> build the publish dict.
        Reads/writes only this room's prefixed entities + its own state."""
        if getattr(self, "_unsaved_rooms", {}).get(room.slug):
            self._restore_unsaved_room(room)
        try:
            import prompt_runtime
            prompt_runtime.sync(self, room, ha_get, ha_call)
        except Exception as err:
            log("AI instructions synchronization unavailable", room.slug, type(err).__name__)
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
            try:  # a light dimmed on dry substrate is restored when the room goes off
                self._watch_dim(room, now, False, {}, off_why="the room was switched off")
            except Exception as e:
                log("dimming error", room.slug, e)
            self._publish_room_off(room, now)
            return {}  # no snapshot, no decision, no blind schedule, no alerts, no vitals line
        if was is False:
            self._room_switched_on(room)
        room._retired_off = self._carry_retired_switches(room)
        self._sensing_options(room)
        self._load_strategy_snapshot(room, now)
        # Only a newly computed batch can clear a prior preflight invalidation.
        room._strategy_batch_invalid = False
        lights_on = self._lights_on(room, now)
        was_off = not (
            room._was_lights_on if room._was_lights_on is not None else lights_on
        )
        lights_just_on = lights_on and was_off
        lights_just_off = room._was_lights_on is True and not lights_on
        if lights_just_on and getattr(self, "jev", None) is not None:
            try:  # the brain's budget window and the Setpoints judge's levers, before any zone is judged
                brain_bridge.lights_on(self, room, now)
            except Exception as e:
                log("brain lights-on error", room.slug, e)
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
            self._observe_grow_day(room, zone, st, snap, now)
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
                try:  # the AI assistant's judges (docs/AI_ASSISTANT.md): whatever goes wrong here, the base engine decides
                    jev_dirs = brain_bridge.tick(self, room, zone, snap, p, now, lights_on)
                    if "distrust" in jev_dirs:
                        distrusted[zone] = jev_dirs["distrust"].why  # the zone takes the dead-probe path
                        snap = None
                    elif "advance" in jev_dirs:
                        snap = brain_bridge.advance(self, room, zone, snap, jev_dirs["advance"], now, p)
                except Exception as e:
                    log("brain error", room.slug, zone, e)
                    jev_dirs = {}
            if snap is None:
                room._blind_since.setdefault(zone, now)
                blind.append((zone, p))
                continue
            room._blind_since.pop(zone, None)
            snaps[zone] = snap
            self._sensing_tick(room, zone, snap, lights_on, now)
            if st["phase"] == "P1" and snap.vwc >= min(p.p1_target, p.field_capacity):
                st["p1_reached"] = True  # the P1 rule (core.decide): the target has been read this P1
            try:  # CS-310: never pour the daily minimum, or an EC flush, into a table that isn't draining
                if self._watch_backup(room, zone, snap, now):
                    p = params[zone] = dataclasses.replace(p, min_daily_volume=0.0)
                    snap = snaps[zone] = dataclasses.replace(snap, backed_up=True)
            except Exception as e:
                log("backup watch error", room.slug, zone, e)
            # the P1 stall exit (core.p1_stall): this pass's count, for the shot it may fire, and the day's re-water
            room.__dict__.setdefault("_p1_stall_now", {})[zone] = p1_stall(snap, p) if st["phase"] == "P1" else 0
            stall = self._p1_stall_today(room, st, now)
            if stall is not None and st["phase"] in ("P2", "P3") and stall["rewater"] < p.p2_threshold:
                p = params[zone] = dataclasses.replace(p, p2_threshold=stall["rewater"])
            self._count_peak(st, snap)
            try:  # CS-315 only ever tells
                self._watch_rescues(room, zone, snap, now)
            except Exception as e:
                log("rescue watch error", room.slug, zone, e)
            if snap.ec is None:
                self._alert(
                    f"ec_unknown_{room.slug}_z{zone}",
                    "CS-104",
                    "zone EC not available",
                    "This zone has no usable EC reading. The EC entity is missing, unavailable or out of "
                    "range, or it has not changed for 20 min. The shots continue on the moisture reading "
                    "only. The controller cannot check or flush salt that builds up."

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
            self._flush_episode(room, zone, st, snap, p, fire, reason)
            shown = snap  # what waiting_for reads: the snapshot, in the phase the zone is now in
            if new_phase != st["phase"]:
                log(f"[{room.slug}] Z{zone} {st['phase']} -> {new_phase}: {log_words.transition(reason)}")
                # decide()'s reason leads with why the phase moved ("lights-off -> P3 | ..."): the push says it.
                self._notify_event("phase", room, zone, st["phase"], new_phase, str(reason).split(" | ")[0])
                self._record_phase(room, zone, st, st["phase"], new_phase, now, str(reason).split(" | ")[0], snap, p)
                if new_phase == "P0":
                    self._close_grow_day(room, zone, st, now, p)
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
            self._publish_waiting_for(room, zone, shown, p, now, gates=self._gates(room, zone, reason))
            # The EC steer runs on ec_smooth, which only settled readings feed (see _settled_ec).
            if (snap.ec is not None and snap.ec_smooth is not None and p.stacking_on
                    and st["phase"] == "P2" and p.ec_target_p2 > 0):
                base = self._zone_num(room, zone, "p2_vwc_threshold", FALLBACK["p2_vwc_threshold"])
                les = st.get("last_ec_steer")
                # The AI assistant's Salt judge chooses how: steer (as always), hold the offset, or decay it toward 0.
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
            self._publish_waiting_for(room, zone, None, p, now, gates=self._gates(room, zone))  # no probe: nothing to compare
            # A dead probe must NOT freeze the daily cycle: still honour the time-based
            # phase forces (lights-off -> P3, P3 -> P0 at the new photoperiod). Only the
            # VWC-driven transitions are paused while blind.
            self._blind_time_transition(room, zone, now, lights_on, lights_just_on, p)
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
                    "Until the reading is normal again, this zone gets the same shots as "
                    f"{self._zone_title(room, sib)}, which has a good probe."
                )
            else:
                mss = self._minutes_since_shot(st, now)
                decisions[zone] = (
                    mss >= self.blind_fallback_min,
                    p.p2_shot_size,
                    Reason("FALLBACK schedule (no live probe)", "blind_fallback"),
                )
                plan = (
                    "Until the reading is normal again, the zone gets a shot every "
                    f"{int(self.blind_fallback_min)} min while the kill switch is on, inside its daily "
                    "water limit. Phase changes that use the moisture reading wait for the probe."
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
                    "the AI assistant set aside the probe of this zone",
                    "The AI assistant judged twice in sequence that the moisture probe of this zone does not "
                    f"follow the substrate ({set_aside}). The check of the controller agreed. {plan} The probe "
                    "counts again when the AI assistant judges that it follows the substrate. Check the "
                    "position and the wiring of the probe."
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
                brain_bridge.shot_started(room, zone, snaps.get(zone), getattr(reason, "kind", None))
            if fire and not block and room.__dict__.get("_shot_check", "off") != "off":
                shot_audit.started(room, zone, snaps.get(zone), getattr(reason, "kind", None))
            fed_before = room.state[zone]["daily_vol"]
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
            self._grow_day_shot(room, zone, getattr(reason, "kind", None), room.state[zone]["daily_vol"] - fed_before, now)
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
                # the zone's live dryback (sensing.dryback): the numbers decide() used this pass
                "dryback": (snap.peak_vwc, snap.vwc, snap.dryback_rate, snap.minutes_since_shot) if snap else None,
            }
        for z, why in cross_zone_outliers(snaps):
            self._alert(
                f"xzone_{room.slug}_{z}",
                "CS-501",
                "much less water than the other zones",
                "Today this zone got much less water than the other zones of the room. Possible causes "
                "are plants that drink less, a probe in a wetter spot, or a problem with a valve or a "
                f"dripper. The shots continue as usual.\n\nDetail: {why}",
                room=room,
                zone=z,
            )
        self._watch_probe_methods(room)
        try:  # CS-713 only ever tells: the plan's targets in force are the integration's, never this check's
            self._watch_plan(room, now, lights_on, params)
        except Exception as e:
            log("plan watch error", room.slug, e)
        if getattr(self, "jev", None) is not None:
            try:
                brain_bridge.siblings(self, room, snaps, params, now)
                brain_bridge.publish(self, room, now, ha_set)
            except Exception as e:
                log("brain publish error", room.slug, e)
        else:
            try:  # with no brain built, the brain panel still says why rules run
                brain_bridge.publish_rules(self, room, now, ha_set)
            except Exception as e:
                log("brain panel error", room.slug, e)
        try:  # Ask why: the grower's questions, answered on the room's brain_answers sensor
            brain_bridge.why_task(self, room, now, ha_get, ha_set, gates=lambda: self._why_gates(room, pub))
        except Exception as e:
            log("ask why error", room.slug, e)
        try:  # CS-209 only ever tells: it can never stop the room being watered
            self._watch_idle(room, now, lights_on, pub)
        except Exception as e:
            log("idle watch error", room.slug, e)
        try:  # CS-311 only ever tells, too
            self._watch_sump(room, now)
        except Exception as e:
            log("sump watch error", room.slug, e)
        try:  # CS-317 only ever tells, too
            self._watch_deadhead(room, now)
        except Exception as e:
            log("dead-head watch error", room.slug, e)
        try:  # the runoff estimator only ever tells (CS-314): no water is given or held from it
            self._watch_runoff(room, now)
        except Exception as e:
            log("runoff estimator error", room.slug, e)
        try:  # CS-211 only ever tells, too
            self._watch_held(room, now, pub)
        except Exception as e:
            log("held watch error", room.slug, e)
        try:  # opt-in: dims the room's light on dry substrate, and restores it (dry_dim.py)
            self._watch_dim(room, now, lights_on, snaps)
        except Exception as e:
            log("dimming error", room.slug, e)
        try:  # the tank level is read and published, and the plan-ahead refill asked for (CS-903)
            self._watch_tank(room)
        except Exception as e:
            log("tank level error", room.slug, e)
        self._send_grow_days(room, now)
        room._was_lights_on = lights_on
        return pub

    # ---------- read-only sensing: dryback, water and VPD, the shot table, the gate list ----------
    def _sensing_options(self, room):
        """This pass's choices for the read-only sensing (each off on a room that never chose): the Shot check
        select and the Water vs VPD switch, and with the switch on, the room's VPD now."""
        mode = ha_get(f"select.crop_steering_{room.prefix}shot_check")[0]
        room._shot_check = mode if mode in shot_audit.MODES else "off"
        room._water_vpd_on = self._on(f"switch.crop_steering_{room.prefix}water_vpd_insight", False)
        room._vpd_now = self._room_vpd(room) if room._water_vpd_on else None

    def _room_vpd(self, room):
        """The room's air VPD in kPa: its mapped VPD sensor, else worked out from its temperature and humidity
        sensors; None without them."""
        climate = getattr(room, "climate", None) or {}
        if climate.get("vpd_sensor"):
            v = sensing.number(ha_get(climate["vpd_sensor"])[0])
            return v if v is not None and 0 <= v <= 6 else None
        if climate.get("temperature_sensor") and climate.get("humidity_sensor"):
            t = self._read_sensor(climate["temperature_sensor"], "temperature", max_age_min=60)
            return sensing.vpd_from(t, sensing.number(ha_get(climate["humidity_sensor"])[0]))
        return None

    def _sensing_tick(self, room, zone, snap, lights_on, now):
        """A reading for the shot table, and the water-and-VPD record's sample. Never stops a zone being watered."""
        try:
            if room.__dict__.get("_shot_check", "off") != "off":
                shot_audit.reading(room, zone, now, snap.vwc, snap.ec)
            if room.__dict__.get("_water_vpd_on"):
                st = room.state[zone]
                closed = sensing.sample(st, day=self._grow_day_start(room, now).isoformat(), ts=now.timestamp(),
                                        lights_on=lights_on, rate=snap.dryback_rate,
                                        minutes_since_shot=snap.minutes_since_shot, vpd=room._vpd_now)
                if closed is not None:
                    litres = next((i["litres"] for i in st.get("water_history") or []
                                   if i.get("grow_day") == closed["date"]), None)
                    sensing.keep(st, closed, litres, self._zone_num(room, zone, "plant_count", FALLBACK["plant_count"]))
                    self._save_state()
        except Exception as e:
            log("sensing error", room.slug, zone, e)

    def _gates(self, room, zone, reason=None):
        """Every pre-shot gate of the zone with pass or hold (gate_report.py), or None when it cannot be read."""
        try:
            return gate_report.report(self, room, zone, reason)
        except Exception as e:
            log("gate report error", room.slug, zone, e)
            return None

    def _publish_sensing(self, room, zone, d, now):
        """The zone's dryback sensor, and with their toggles on, its water-vs-VPD answer and its shot table."""
        px = room.prefix
        try:
            state, attrs = sensing.dryback(*(d.get("dryback") or (None, None, None, None)))
            ha_set(f"sensor.crop_steering_{px}zone_{zone}_dryback_app", state,
                   {**attrs, "note": sensing.DRYBACK_NOTE, "friendly_name": f"Zone {zone} dryback",
                    "engine": PRODUCT})
            if room.__dict__.get("_water_vpd_on"):
                st = room.state[zone]
                fit = sensing.fit(st.get("day_hist") or [])
                ha_set(f"sensor.crop_steering_{px}zone_{zone}_water_response_app",
                       "unknown" if fit["slope"] is None else fit["slope"],
                       {"unit_of_measurement": "points/h per kPa", "n_days": fit["n"], "r": fit["r"],
                        "vpd_spread_kpa": fit["spread"], "days": st.get("day_hist") or [], "words": fit["words"],
                        "vpd_now_kpa": room._vpd_now, "friendly_name": f"Zone {zone} dryback vs VPD",
                        "engine": PRODUCT})
            mode = room.__dict__.get("_shot_check", "off")
            if mode != "off":
                jev = getattr(self, "jev", None)
                rows = shot_audit.table(room, zone, now, self._substrate_l(room, zone), d["p"].field_capacity,
                                        ai=shot_audit.ai_labels(jev, room.slug, zone) if jev is not None else ())
                ha_set(f"sensor.crop_steering_{px}zone_{zone}_shot_log_app", rows[0]["verdict"] if rows else "none",
                       {"shots": rows, "mode": mode, "ai_on": jev is not None,
                        "note": "Kept in memory: after a restart the table fills again with the next shots.",
                        "friendly_name": f"Zone {zone} last shots", "engine": PRODUCT})
                # Rules-mode CS-701: only with the AI assistant off, under the AI judge's own alert key, so one
                # fault never gives two notices.
                if mode == "table_and_alert" and jev is None and shot_audit.no_sign_in_a_row(room, zone, rows):
                    a, b = [r for r in rows if r["counted"] and r["verdict"] == "no_sign"][:2][::-1]
                    self._alert(
                        f"jev_shot_{room.slug}_z{zone}", "CS-701", "water does not reach this zone",
                        f"The last two shots on {self._zone_title(room, zone)} at {a['start'][11:16]} and "
                        f"{b['start'][11:16]} gave {a['litres']:.1f} L and {b['litres']:.1f} L, and neither the "
                        "VWC nor the pore EC moved (the controller's shot check). Check the valve, the drippers and "
                        "the line of the zone. The shots continue as usual.",
                        room=room, zone=zone)
        except Exception as e:
            log("sensing publish error", room.slug, zone, e)

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
                self._publish_sensing(room, zone, d, now)
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
            head += f"  ⚠️ {self._n_defaulted} setting(s) missing → built-in values"
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
        alert if it disagrees with Home Assistant's configured zone. -> False while Home Assistant has not
        answered with its zone, or a mismatch's card is not up: run() asks again each loop until then."""
        now_local = datetime.now().astimezone()
        off = now_local.utcoffset()
        off_h = off.total_seconds() / 3600.0 if off else 0.0
        if not getattr(self, "_tz_logged", False):
            self._tz_logged = True
            log(
                f"timezone: container local {now_local:%Y-%m-%d %H:%M} "
                f"(UTC{off_h:+.1f}h) TZ={os.environ.get('TZ', 'unset')}"
            )
        try:
            r = _session().get(f"{BASE}/config", headers=HDR, timeout=8) if _GATE.allows("other") else None
            if r is not None:
                _GATE.saw("other", r.status_code, f"GET {SHOWN_BASE}/config")
            ha_tz = (r.json() or {}).get("time_zone") if r is not None and r.status_code == 200 else None
        except Exception:
            ha_tz = None
        if not ha_tz:
            return False
        try:
            from zoneinfo import ZoneInfo

            ha_off = datetime.now(ZoneInfo(ha_tz)).utcoffset().total_seconds() / 3600.0
        except Exception as e:  # tzdata missing, unknown zone, etc.
            log("timezone: could not resolve HA zone", ha_tz, e)
            return True
        if abs(ha_off - off_h) > 0.01:
            return self._alert(  # a card not created is tried again
                "tz_mismatch",
                "CS-405",
                "time zone mismatch, the grow-day can move",
                f"The clock of the controller uses UTC{off_h:+.1f}h, but Home Assistant uses "
                f"{ha_tz} (UTC{ha_off:+.1f}h). The controller uses its own clock for lights-on, lights-off, "
                "dryback and the daily reset. So the full grow-day moves by the difference. "
                + (
                    "Set TZ in the compose file of the controller container to the time zone of Home "
                    "Assistant. Alternatively, remove TZ to use the time zone of Home Assistant. Then "
                    "restart the container."
                    if _GATE.container
                    else "Upgrade or rebuild the controller. If the alert stays, check the time zone in "
                    "Settings → System → General."
                ),
            )
        else:
            log(f"timezone: matches Home Assistant ({ha_tz})")
        return True

    def _check_holds(self):
        """Name every hold (hold_entities) that Home Assistant answers it does not have (404), from the start,
        before anything is watered and whatever the kill switches say: each one holds every shot of every room
        (_blocked). One CS-210 card names them all. run() calls this at start and then each loop until every
        hold answered and exists, and the card is down (one a previous run left goes too); never with no hold
        set up."""
        answers = {entity: ha_get_status(entity)[0] for entity in self.hold_entities}
        missing = [entity for entity, status in answers.items() if status == 404]
        if missing:
            one = len(missing) == 1
            if self._alert(
                "holds_missing",
                "CS-210",
                f"{'hold entity' if one else f'{len(missing)} hold entities'} not in Home Assistant, no shots",
                f"The app's hold entities option names {'an entity' if one else 'entities'} that Home Assistant "
                f"does not have. A hold that does not exist stops every shot in every room, as a hold that is on "
                f"does. For {'it' if one else 'each one'}: remove it from the app's hold entities, or create it "
                "in Home Assistant. This card goes once each one exists. If you remove them from the option "
                "instead, dismiss this card."
                f"\n\nNot in Home Assistant: {', '.join(missing)}",
            ):
                self._holds_card = True
        elif None not in answers.values():  # every hold answered, and each one exists
            if ha_call("persistent_notification", "dismiss", notification_id="f2_holds_missing"):
                self._holds_card = False
            self._alerted.pop("holds_missing", None)
            self._alert_codes.pop("holds_missing", None)

    def run(self):
        log(
            f"{PRODUCT} {CONTROLLER_VERSION} starting | rooms",
            ", ".join(r.slug for r in self.rooms),
            "| notify",
            self.notify_service or "(none)",
            f"| loop {self.loop_seconds:.0f}s",
        )
        log("token present:", bool(TOKEN), "| base:", SHOWN_BASE)
        tz_checked = self._log_timezone()
        if self.hold_entities:
            self._check_holds()
        self._start_dosing()
        while True:
            if _GATE.state is not None:
                self._park_refused()
            if not tz_checked:  # Home Assistant did not answer at start: CS-405 is checked once it does
                try:  # on its own: a raise here never skips the pass
                    tz_checked = self._log_timezone()
                except Exception as e:
                    log("timezone check error", e)
            try:
                if self.hold_entities and self._holds_card is not False:
                    self._check_holds()
                self.loop_once(datetime.now())
            except Exception as e:
                log("loop error", e)
            if _GATE.state is None:
                self._sleep_for(self.loop_seconds)

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
