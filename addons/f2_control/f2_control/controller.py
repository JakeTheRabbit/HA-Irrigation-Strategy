# -*- coding: utf-8 -*-
"""F2 Control — standalone crop-steering controller (Home Assistant add-on).

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
auto-injected SUPERVISOR_TOKEN. Safe-offs the hardware on exit.
"""
import json
import math
import os
import re
import signal
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
import auto_setpoints
import jev_policy
import setpoint_supervisor
from strategy_runtime import parse_snapshot, parameter_override, strategy_block

from crop_steering_engine import (
    decide,
    ZoneParams,
    ZoneSnapshot,
    validate_params,
    pick_sibling,
    feed_grace_ok,
    ec_pid,
    cross_zone_outliers,
    detect_vmax,
    zone_safety_status,
    system_safety_status,
    zone_status_label,
)

# ---------------------------------------------------------------- HA REST (Supervisor proxy)
BASE = os.environ.get("HA_URL", "http://supervisor/core/api")
TOKEN = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN", "")
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
_S = requests.Session()


def log(*a):
    print("[f2-control]", *a, flush=True)


def ha_get(entity, timeout=8):
    """Return (state_str, attributes, last_updated_iso) or (None, {}, None)."""
    try:
        r = _S.get(f"{BASE}/states/{entity}", headers=HDR, timeout=timeout)
        if r.status_code != 200:
            return None, {}, None
        d = r.json()
        return d.get("state"), d.get("attributes", {}), d.get("last_updated")
    except Exception:
        return None, {}, None


def ha_get_all():
    """Return the full /api/states list (or [] on failure). Used once at startup for
    multi-room discovery — find every sensor.crop_steering_*engine_config descriptor."""
    try:
        r = _S.get(f"{BASE}/states", headers=HDR, timeout=12)
        if r.status_code != 200:
            return []
        return r.json() or []
    except Exception:
        return []


def ha_call(domain, service, **data):
    try:
        r = _S.post(
            f"{BASE}/services/{domain}/{service}", headers=HDR, json=data, timeout=12
        )
        if r.status_code >= 300:
            log("call_service FAILED", domain, service, "HTTP", r.status_code)
            return False
        return True
    except Exception as e:
        log("call_service failed", domain, service, e)
        return False


def ha_set(entity, state, attributes=None):
    try:
        _S.post(
            f"{BASE}/states/{entity}",
            headers=HDR,
            json={"state": state, "attributes": attributes or {}},
            timeout=8,
        )
    except Exception:
        pass


# ---------------------------------------------------------------- config (F2 defaults; override via /data/options.json)
def load_options():
    opts = {}
    for p in ("/data/options.json",):
        try:
            with open(p) as fh:
                opts = json.load(fh)
        except Exception:
            pass
    return opts


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

# Switch read-back after a close: see Controller._confirm_switches.
CONFIRM_FIRST_READ_S, CONFIRM_POLL_S, CONFIRM_TIMEOUT_S = 1.0, 0.5, 6.0

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
        self._vmax_wetup = {}  # z -> P1 wet-up VWC series (resets each P0)
        self._vmax = {}  # z -> (vmax, confidence) advisory
        self._blind_zones = set()
        self._was_lights_on = None
        self._feed_last_good_value = None
        self._feed_last_good_time = None
        self._feed_ph_last_good = None
        self._feed_ph_last_good_time = None


class Controller:
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
        # Optional: Jev (TypeSafe, via Cloudflare AI) as a guard on auto setpoints. Unset = arithmetic only.
        self._cf = tuple((o.get(k) or "").strip() for k in ("cf_account_id", "cf_api_token", "cf_gateway_id"))
        self.loop_seconds = float(o.get("loop_seconds", 60))
        self.flow_lps = float(
            o.get("flow_lps", 0.02)
        )  # generic last-resort fallback — real flow is computed live per zone
        self.substrate_l = float(
            o.get("substrate_l", 5)
        )  # generic last-resort fallback — real volume read live from the integration
        self._opt_lon = float(o.get("lights_on_hour", 10))
        self._opt_loff = float(o.get("lights_off_hour", 22))
        # Live installs always use /data/state.json (HA-managed, survives Rebuild). The env
        # override exists so a test/dev rig can redirect the file BEFORE this constructor's
        # own _load_state()/adoption pass reads and writes it.
        self._state_path = os.environ.get("F2_STATE_PATH") or "/data/state.json"
        self._busy = False
        self._alerted = {}
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
        zones_opt = o.get("zones")
        if zones_opt:
            zones = {int(k): v for k, v in zones_opt.items()}
        else:
            # auto-detect zone count from the integration's fused sensors (configure once);
            # fall back to the descriptor/option if HA isn't reachable yet at startup.
            n = self._detect_zones(
                "", int(o.get("num_zones", desc.get("num_zones") or 3))
            )
            zones = {
                z: {
                    "vwc": f"sensor.crop_steering_vwc_zone_{z}",
                    "ec": f"sensor.crop_steering_ec_zone_{z}",
                }
                for z in range(1, n + 1)
            }
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
        if not default_room.hw.get("valves"):
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
                    f"{r.slug}(prefix='{r.prefix}', {len(r.zones)}z, kill={r.enable_flag})"
                    for r in self.rooms
                ),
            )

        # state for all rooms (nested by slug; old flat single-room files load as 'default')
        self._load_state()
        self._apply_setup_descriptors()  # Gate tombstones/revisions before the very first shot.
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

    def _default_enable_flag(self, options, descriptor):
        legacy = "input_boolean.f2_control_enabled"
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
        for ent in ha_get_all():
            eid = ent.get("entity_id", "")
            if not (
                eid.startswith("sensor.crop_steering_")
                and eid.endswith("engine_config")
            ):
                continue
            a = ent.get("attributes", {}) or {}
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
            "shots": 0,
            "daily_vol": 0.0,
            "ec_smooth": None,
            "last_phase_change": datetime.now(),
            "ec_offset": 0.0,
            "ec_integral": 0.0,
            "ec_prev_err": 0.0,
            "last_ec_steer": None,
            "last_daily_reset": None,
            "water_history": None,
            "water_history_legacy_excluded_l": 0.0,
            "learn": auto_setpoints.fresh(),
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
            "ec_integral",
            "ec_prev_err",
        ):
            if d.get(k) is not None:
                s[k] = d[k]
        for k in ("last_shot", "last_phase_change", "last_ec_steer"):
            if d.get(k):
                try:
                    s[k] = datetime.fromisoformat(d[k])
                except (ValueError, TypeError):
                    pass
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
        room.strategy_required = False
        room._strategy_persisted = True
        block = per_room.get(room.slug)
        if isinstance(block, dict):
            room.strategy_required = bool(block.get("_strategy_required", False))
            fault = block.get("_hardware_fault")
            if "_hardware_fault" in block:
                # Old files have no metadata. Malformed new metadata must not clear a hold.
                room.hardware_fault = self._fault_record(
                    fault, self._hardware_entities(room)
                )
            for z in room.zones:
                d = block.get(str(z)) or block.get(z)
                room.state[z] = self._apply_saved_zone(room.state[z], d)

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

    def _apply_setup_descriptors(self):
        """Adopt explicit versioned setup changes only after both maps are safe OFF.

        Missing legacy revision leaves add-on overrides untouched. Tombstones do
        not delete counters, and missing descriptors never imply room removal.

        A restart forgets nothing: the adopted revision and its fingerprint are saved, and the
        same pair after a restart is RESUMED with the kill switch left as it is (hardware must
        still read OFF). On 2026-09-20 a host reboot otherwise left every F2 zone blocked behind
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
            revision = attrs.get("setup_revision", 0)
            if type(revision) is not int or revision <= getattr(
                room, "setup_revision", 0
            ):
                continue
            room._setup_pending = "Setup changed; disarm current and requested engine flags and verify hardware OFF"
            try:
                fingerprint = self._setup_fingerprint(attrs, room)
                saved = (getattr(self, "_saved_room_blocks", {}).get(room.slug) or {}).get("_setup")
                resuming = (
                    getattr(room, "setup_revision", 0) == 0
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
                    and room.enable_flag == "input_boolean.f2_control_enabled"
                    and desired_flag == "switch.crop_steering_engine_enabled"
                    and ha_get(room.enable_flag)[0] is None
                ):
                    flags.discard(
                        room.enable_flag
                    )  # absent legacy helper on a fresh setup
                armed = sorted(flag for flag in flags if ha_get(flag)[0] != "off")
                running = sorted(e for e in hardware if ha_get(e)[0] != "off")
                if running or (armed and not resuming):
                    if active:  # an archived room is meant to stay dry: no noise about it
                        self._alert(
                            f"setup_{room.slug}",
                            "Irrigation BLOCKED - setup needs re-arming",
                            f"{room.slug}: setup revision {revision} is waiting to be adopted, and nothing "
                            "in this room will be watered until it is. It is adopted only while these read "
                            f"OFF: {', '.join(armed + running)}. Turn them OFF, wait for this notice to "
                            f"clear (up to {int(getattr(self, 'rediscover_seconds', 300))} s), then turn "
                            "the kill switch back ON.",
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
        ls, lpc, les, ldr = (
            s.get("last_shot"),
            s.get("last_phase_change"),
            s.get("last_ec_steer"),
            s.get("last_daily_reset"),
        )
        return {
            "phase": s.get("phase"),
            "peak": s.get("peak"),
            "shots": s.get("shots"),
            "daily_vol": s.get("daily_vol"),
            "water_history": s.get("water_history"),
            "water_history_legacy_excluded_l": s.get("water_history_legacy_excluded_l", 0.0),
            "learn": s.get("learn"),
            "ec_smooth": s.get("ec_smooth"),
            "ec_offset": float(s.get("ec_offset") or 0.0),
            "ec_integral": float(s.get("ec_integral") or 0.0),
            "ec_prev_err": float(s.get("ec_prev_err") or 0.0),
            "last_shot": ls.isoformat() if isinstance(ls, datetime) else None,
            "last_phase_change": lpc.isoformat() if isinstance(lpc, datetime) else None,
            "last_ec_steer": les.isoformat() if isinstance(les, datetime) else None,
            "last_daily_reset": ldr.isoformat() if isinstance(ldr, date) else None,
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
            if hasattr(room, "_room_active_known"):
                block["_room_active"] = room._room_active_known
            if getattr(room, "_setup_fingerprint_adopted", None):  # else keep whatever was saved
                block["_setup"] = {
                    "revision": room.setup_revision,
                    "fingerprint": room._setup_fingerprint_adopted,
                }
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
        if v not in (None, "unknown", "unavailable", ""):
            return self._num(per, default)
        glob = f"number.crop_steering_{room.prefix}{suffix}"
        gv, _, _ = ha_get(glob)
        if gv not in (None, "unknown", "unavailable", ""):
            return self._num(glob, default)
        # Neither the per-zone NOR the global setpoint entity exists → the engine is silently
        # running its built-in default. On a healthy install the integration creates the global,
        # so this only trips on a real misconfig (renamed/removed entity). Record it so
        # _check_defaulted_setpoints can surface it — EXCEPT engine-only knobs the integration
        # deliberately doesn't create (optional=True): those default by design, never alert.
        if not optional:
            self._defaulted_this_loop.add(glob)
        return float(default)

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
                "Irrigation held — invalid maximum shot duration",
                f"{entity} must report a finite duration of at least 5 seconds. "
                "The selected cap is not replaced by a legacy value or default.",
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
        return str(v).lower() in ("on", "true", "open", "1", "home")

    def _read_sensor(self, entity, lo=0.0, hi=200.0, max_age_min=20, to_ms_cm=False):
        v, attrs, lu = ha_get(entity)
        if v in (None, "unknown", "unavailable", ""):
            return None
        try:
            f = float(v)
        except Exception:
            return None
        if to_ms_cm:  # an EC probe in uS/cm (micro sign, Greek mu or plain "u") is a thousandth of that in mS/cm
            unit = str((attrs or {}).get("unit_of_measurement") or "").lower().replace(" ", "")
            if unit in ("µs/cm", "μs/cm", "us/cm"):
                f /= 1000.0
        if not math.isfinite(f) or f < lo or f > hi:
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
        feed = self._read_sensor(room.feed_ec_sensor, lo=0, hi=20, to_ms_cm=True)
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
        ph = self._read_sensor(room.feed_ph_sensor, lo=0, hi=14)
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
        number.crop_steering_<prefix>lights_on_hour / _off_hour each loop, falling back to the
        add-on option if the entities are missing. Log the source once per room, and alert once
        if the integration value disagrees with the (now-legacy) add-on option."""
        lon = self._num_or_none(f"number.crop_steering_{room.prefix}lights_on_hour")
        loff = self._num_or_none(f"number.crop_steering_{room.prefix}lights_off_hour")
        if lon is not None and loff is not None:
            src = "integration"
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
            ):
                self._alert(
                    "lights_source",
                    "Lights now read from the integration",
                    f"Engine uses {int(lon)}:00-{int(loff)}:00 from the integration. The add-on "
                    f"option still says {int(room.opt_lon)}:00-{int(room.opt_loff)}:00 — if the "
                    "integration value is wrong, set number.crop_steering_lights_on_hour / _off_hour.",
                )
            room._lights_logged = True
        room.lights_on_hour, room.lights_off_hour = float(lon), float(loff)

    # ---------- params + snapshot ----------
    def _params(self, room, zone, ec_known=True):
        veg = self._veg(room, zone)
        sfx = "veg" if veg else "gen"
        base = self._zone_num(room, zone, "p2_vwc_threshold", 45)
        p1t = self._zone_num(room, zone, "p1_target_vwc", 60)
        fc = self._zone_num(room, zone, "field_capacity", 70)
        efloor = self._zone_num(room, zone, "p3_emergency_vwc_threshold", 40)
        # EC-steer offset is shell-owned (decide() no longer nudges). Bake it into the
        # P2 rewater threshold, clamped to the same safe band the engine used: never
        # below the emergency-floor band, never above the ramp ceiling.
        # Keep learned state for recovery, but never apply stale EC steering while blind to EC.
        p2_thr = base + (float(room.state[zone].get("ec_offset", 0.0)) if ec_known else 0.0)
        p2_thr = max(efloor + 3.0, min(min(p1t, fc) - 1.0, p2_thr))
        raw = ZoneParams(
            p1_target=p1t,
            p2_threshold=p2_thr,
            p2_shot_size=self._zone_num(room, zone, "p2_shot_size", 5),
            p1_initial=self._zone_num(room, zone, "p1_initial_shot_size", 2),
            p1_incr=self._zone_num(room, zone, "p1_shot_size_increment", 0.5),
            p1_max_shots=int(self._zone_num(room, zone, "p1_maximum_shots", 12)),
            p1_min_shots=int(self._zone_num(room, zone, "p1_minimum_shots", 0)),
            p1_time_between_min=self._zone_num(room, zone, "p1_time_between_shots", 15),
            dryback_target=self._zone_num(
                room,
                zone,
                f"{'vegetative' if veg else 'generative'}_dryback_target",
                20,
            ),
            p0_max_wait_min=self._zone_num(room, zone, "p0_maximum_wait_time", 45),
            ec_target_p0=self._zone_num(room, zone, f"ec_target_{sfx}_p0", 4),
            ec_target_p1=self._zone_num(room, zone, f"ec_target_{sfx}_p1", 5),
            ec_target_p2=self._zone_num(room, zone, f"ec_target_{sfx}_p2", 6),
            p3_emergency_floor=efloor,
            p3_emergency_shot=self._zone_num(room, zone, "p3_emergency_shot_size", 2),
            # Fallback used ONLY when a zone has no readable max_daily_volume entity — e.g. a zone the
            # engine detected from its VWC sensor but the integration never built a cap entity for
            # (num_zones < detected zones). Must fail LOW: the integration's own entity maxes at 200 L,
            # so the engine can never grant more daily water than the UI can express. Was 300 (above the
            # UI max) which let orphaned zones free-run to 300 L/day while wired zones honoured their cap.
            max_daily_volume=self._zone_num(room, zone, "max_daily_volume", 150),
            field_capacity=fc,
            max_ec=self._zone_num(room, zone, "maximum_ec", 9),
            stacking_on=self._on(
                f"switch.crop_steering_{room.prefix}ec_stacking_enabled", False
            ),
            watchdog_hours=self._zone_num(room, zone, "watchdog_hours", 3),
            min_daily_volume=self._num(
                f"input_number.crop_steering_{room.prefix}zone_{zone}_min_daily_ml_per_plant",
                0.0,
            )
            * self._zone_num(room, zone, "plant_count", 0)
            / 1000.0,  # mL/plant x plants -> zone-L floor (0 if either unset)
            drown_ceiling=self._zone_num(
                room, zone, "min_floor_drown_ceiling", 90, optional=True
            ),  # hard anti-drown VWC cap on the floor (engine-only knob — no integration entity)
        )
        p, warns = validate_params(raw)
        for w in warns:
            self._alert(
                f"cfg_{room.slug}_z{zone}_{w.split('=')[0]}",
                "F2 config clamp",
                f"{room.slug} zone {zone}: {w}",
            )
        return p

    def _snapshot(self, room, zone, now, lights_on, lights_just_on):
        st = room.state[zone]
        vwc = self._read_sensor(
            self._fused_id(room.prefix, "vwc", zone, room.zones[zone].get("vwc")),
            lo=0,
            hi=100,
        )
        ec = self._read_sensor(
            self._fused_id(room.prefix, "ec", zone, room.zones[zone].get("ec")),
            lo=0,
            hi=20,
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
        if ec is not None:
            previous = st["ec_smooth"]
            st["ec_smooth"] = (
                ec if previous is None or not math.isfinite(previous)
                else 0.3 * ec + 0.7 * previous
            )
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
        gds = self._grow_day_start(room, now)
        ldr = st.get("last_daily_reset")
        new_grow_day = lights_on and (ldr is None or ldr < gds)
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
            uptime_min=(now - self._start).total_seconds() / 60.0,
            feed_ec=(feed_ec if feed_ec is not None else 3.0),
            new_grow_day=new_grow_day,
        )
        return snap, self._params(room, zone, ec_known=ec is not None)

    # ---------- auto setpoints (the engine still fires every shot) ----------
    def _auto_tick(self, room, zone, snap, p, lights_on, now):
        """Learn this zone from its own shots every loop. Rewrite its targets only when the room's
        opt-in switch is on, only on its own per-zone numbers, and never while a grow plan owns the room."""
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
        jev_state = room.__dict__.setdefault("_jev_state", {})
        jev = jev_state.get(zone, "ok") if (self._cf[0] and self._cf[1]) else "disabled"
        was = learn["outcome"]
        outcome = auto_setpoints.ramp_outcome(learn, st["phase"])
        if outcome != was:
            if outcome == "plateau" and enabled and jev != "disabled":
                verdict = jev_policy.verdicts(jev_policy.call(
                    self._cf[0], self._cf[1],
                    auto_setpoints.evidence(learn, st["phase"], snap.vwc, p.p1_target, snap.ec, p.ec_target_p2,
                                            self._read_feed_ec(room), p.p2_shot_size, st["shots"]),
                    gateway=self._cf[2] or None, timeout=5.0))
                jev = jev_state[zone] = "ok" if verdict is not None else "unavailable"
                if verdict and verdict.get("freeze"):  # a guard can only make it MORE careful
                    auto_setpoints.distrust(learn, f"Jev: {verdict['freeze']}")
                    outcome = learn["outcome"]
            log(f"[{room.slug}] Z{zone} P1 ramp outcome: {outcome} (peak {learn['peak']})")
            if outcome == "suspect":
                self._alert(f"auto_{room.slug}_z{zone}", f"{room.slug} Z{zone} auto setpoints frozen",
                            auto_setpoints.frozen_reason(learn))
            self._save_state()
        # In P2 the judge manages the maintenance shot: asked once an hour, it may nudge the P2 shot
        # size (pore EC) and the working peak, one bounded step per lever per grow-day. It cannot fire,
        # size or delay a shot, and a call that fails or takes too long changes nothing.
        stamp = now.strftime("%Y-%m-%dT%H")
        if (enabled and not planned and jev != "disabled" and lights_on and st["phase"] == "P2"
                and auto_setpoints.jev_due(learn, stamp)):
            verdict = jev_policy.verdicts(jev_policy.call(
                self._cf[0], self._cf[1],
                auto_setpoints.evidence(learn, "P2", snap.vwc, p.p1_target, snap.ec, p.ec_target_p2,
                                        self._read_feed_ec(room), p.p2_shot_size, st["shots"]),
                gateway=self._cf[2] or None, timeout=5.0))
            jev = jev_state[zone] = "ok" if verdict is not None else "unavailable"
            asked = auto_setpoints.jev_verdict(learn, stamp, verdict, p.p2_shot_size, now.strftime("%H:%M"))
            for suffix, value in asked.items():
                self._auto_write(room, zone, suffix, p.p2_shot_size, value, learn, now, by="Jev")
            log(f"[{room.slug}] Z{zone} Jev P2: {learn['jev']['last']}")
            self._save_state()
        if enabled and not planned:
            current = {
                "p1_target_vwc": p.p1_target, "field_capacity": p.field_capacity,
                "p2_vwc_threshold": self._zone_num(room, zone, "p2_vwc_threshold", 45, optional=True),
                "p3_emergency_vwc_threshold": p.p3_emergency_floor, "p2_shot_size": p.p2_shot_size,
            }
            h = now.hour + now.minute / 60.0
            ctx = dict(
                lights_on_h=room.lights_on_hour, lights_off_h=room.lights_off_hour,
                minutes_since_lights_on=((h - room.lights_on_hour) % 24) * 60.0 if lights_on else None,
                shots_today=st["shots"], dryback_pct=p.dryback_target, p0_wait_min=p.p0_max_wait_min,
                p1_shot_pct=p.p1_initial, p1_gap_min=p.p1_time_between_min,
                start_vwc=learn["ramp_start"] if learn["ramp_start"] is not None else snap.vwc,
            )
            want = auto_setpoints.wanted(learn, current, snap.vwc, st["phase"], ctx)
            for suffix, value, _why in setpoint_supervisor.writes(current, want):
                self._auto_write(room, zone, suffix, current[suffix], value, learn, now)
            if st["phase"] == "P1" and learn["outcome"] == "plateau":
                gate = auto_setpoints.p1_ec_gate(snap.ec, p.ec_target_p1, p.ec_target_p2)
                if gate is not None:  # let the hand-over through; see p1_ec_gate
                    mode = "veg" if self._veg(room, zone) else "gen"
                    self._auto_write(room, zone, f"ec_target_{mode}_p1", p.ec_target_p1, gate, learn, now)
        state, attrs = auto_setpoints.status(learn, enabled)
        if enabled and planned:
            state, attrs["frozen_reason"] = "frozen", "an armed grow plan owns this room's targets"
        suffixes = auto_setpoints.MANAGED + (auto_setpoints.JEV_MANAGED if jev != "disabled" else ())
        attrs.update(
            jev=jev, jev_last=learn["jev"]["last"], jev_changed_today=learn["jev"]["changed"],
            working_peak_adjust=learn["peak_adj"],
            updated=now.isoformat(), engine="f2-control", friendly_name=f"Zone {zone} auto setpoints",
            managed=[f"number.crop_steering_{room.prefix}zone_{zone}_{s}" for s in suffixes],
        )
        ha_set(f"sensor.crop_steering_{room.prefix}zone_{zone}_auto_setpoints", state, attrs)

    def _auto_write(self, room, zone, suffix, old, value, learn, now, by="auto"):
        entity = f"number.crop_steering_{room.prefix}zone_{zone}_{suffix}"
        if ha_get(entity)[0] in (None, "unknown", "unavailable", ""):
            return  # no per-zone number on this install: room-level values are the operator's, never ours
        written = room.__dict__.setdefault("_auto_written", {})
        last = written.get((zone, suffix))
        if last and last[0] == value and (now - last[1]).total_seconds() < 300:
            return  # HA has not reflected the last write yet: do not spam it
        written[(zone, suffix)] = (value, now)
        ha_call("number", "set_value", entity_id=entity, value=value)
        learn["last_change"] = f"{now.strftime('%H:%M')} {suffix} {old:g} -> {value:g}"
        tag = "" if room.prefix == "" else f"{room.slug} "
        self._activity.insert(0, f"{now.strftime('%H:%M')} {tag}Z{zone} {by} {suffix} {old:g} -> {value:g}"[:120])
        log(f"[{room.slug}] Z{zone} {by} {suffix} {old:g} -> {value:g}")

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
        for key in [k for k in self._alerted if f"_{room.slug}_" in k or k.endswith(f"_{room.slug}")]:
            ha_call("persistent_notification", "dismiss", notification_id=f"f2_{key}")
            del self._alerted[key]

    def _room_switched_on(self, room):
        """A fresh run: yesterday's phase, counters and learned ceiling belong to the last crop.
        Water history is a record, so it stays. Zones wait in P3 for the next lights-on boundary."""
        log(f"[{room.slug}] room switched ON - starting a fresh run")
        for zone in room.zones:
            old = room.state[zone]
            room.state[zone] = {
                **self._fresh_zone(),
                "phase": "P3",
                "last_shot": datetime.now(),  # the blind-probe schedule counts from switch-on, not from "never"
                "water_history": old.get("water_history"),
                "water_history_legacy_excluded_l": old.get("water_history_legacy_excluded_l", 0.0),
            }
        room._vmax, room._vmax_wetup = {}, {}
        self._save_state()

    def _heartbeat(self, room, now, hardware_fault, room_active=True):
        ha_set(
            f"sensor.crop_steering_{room.prefix}ai_heartbeat",
            "healthy",
            {
                "engine": "f2-control",
                # which controller is actually RUNNING, for the dashboard's sidebar
                "controller_version": CONTROLLER_VERSION,
                "last_beat": now.isoformat(),
                # the kill switch this room ACTUALLY uses — the integration's health
                # check reads this so a custom enable_flag isn't flagged as "missing"
                "enable_flag": room.enable_flag,
                "hardware_fault": hardware_fault,
                "strategy_snapshot_version": 1,
                "setup_lifecycle_version": 1,
                "strategy_required": getattr(room, "strategy_required", False),
                "strategy_error": (getattr(room, "strategy_snapshot", None) or {}).get("error"),
                "setup_revision": getattr(room, "setup_revision", 0),
                "setup_active": getattr(room, "setup_active", True),
                "setup_pending": getattr(room, "_setup_pending", None),
                "room_active": room_active,
            },
        )

    def _publish_room_off(self, room, now):
        """An OFF room still reports in, so the dashboard shows why it is idle and the integration
        never mistakes a deliberately idle room for a dead engine."""
        px = room.prefix
        try:
            for zone in room.zones:
                ha_set(f"sensor.crop_steering_{px}zone_{zone}_status", "Room off",
                       {"reason": "Room off (nothing growing)"})
            ha_set(f"sensor.crop_steering_{px}app_status", "room_off",
                   {"engine": "f2-control", "updated": now.isoformat()})
            ha_set(f"sensor.crop_steering_{px}current_decision", "Room off - nothing growing",
                   {"fired": [], "blocked": []})
            self._heartbeat(room, now, self._hardware_fault_block(room), room_active=False)
        except Exception as e:
            log("publish failed", room.slug, e)

    # ---------- gates ----------
    def _blocked(self, room, zone):
        if getattr(room, "_setup_pending", None):
            return room._setup_pending
        if getattr(room, "setup_active", True) is False:
            return "Room archived in integration setup"
        if not self._room_active(room):
            return "Room off (nothing growing)"
        planned_hold = strategy_block(getattr(room, "strategy_snapshot", None), zone)
        if planned_hold:
            return planned_hold
        fault = self._hardware_fault_block(room)
        if fault:
            return fault
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
                "Irrigation BLOCKED - plumbing and switches disagree",
                f"{room.slug}: {plumbing}.",
            )
            return plumbing
        if not self._on(room.enable_flag, False):
            return "f2-control disabled (kill switch off)"
        if not self._on(f"switch.crop_steering_{room.prefix}system_enabled", False):
            return "system disabled"
        if not self._on(
            f"switch.crop_steering_{room.prefix}auto_irrigation_enabled", False
        ):
            return "auto-irrigation disabled"
        if not self._on(f"switch.crop_steering_{room.prefix}zone_{zone}_enabled", True):
            return "zone disabled"
        if self._on(
            f"switch.crop_steering_{room.prefix}zone_{zone}_manual_override", False
        ):
            return "manual override"
        # External operator holds (tank dosing / manual fill / flush) are configurable
        # (self.hold_entities, empty by default) — an install without them never holds here.
        for f in self.hold_entities:
            if self._on(f, False):
                return f"external hold ({f.split('.')[-1]})"
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
                    if feed_grace_ok(
                        datetime.now().timestamp(),
                        (
                            room._feed_ph_last_good_time.timestamp()
                            if room._feed_ph_last_good_time
                            else None
                        ),
                        self.feed_grace_min,
                    ):
                        return None
                    return f"source-water pH probe dead >{self.feed_grace_min:.0f}min — holding (fail-closed)"
                if (ph_lo > 0 and ph < ph_lo) or (ph_hi > 0 and ph > ph_hi):
                    return f"source-water pH {ph:.2f} out of [{ph_lo:g},{ph_hi:g}]"
        return None

    # ---------- alerts / notify ----------
    def _alert(self, key, title, message):
        now = datetime.now()
        last = self._alerted.get(key)
        if last and (now - last).total_seconds() < 1800:
            return
        self._alerted[key] = now
        log("ALERT", title, "-", message)
        ha_call(
            "persistent_notification",
            "create",
            title=title,
            message=message,
            notification_id=f"f2_{key}",
        )
        dom, _, svc = self.notify_service.partition("/")
        if dom and svc:
            ha_call(dom, svc, title=title, message=message)

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

    def _advance_shot_counters(self, room, zone, size_pct, *, delivered_l=None):
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
        if not isinstance(st.get("learn"), dict):
            st["learn"] = auto_setpoints.fresh()
        auto_setpoints.shot(st["learn"], st.get("phase"), size_pct, st.get("last_vwc"), now.timestamp())
        st["shots"] += 1
        st["last_shot"] = now
        st["daily_vol"] += delivered_l
        self._save_state()

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
    def _fault_record(fault, fallback_entities=()):
        entities = fault.get("entities") if isinstance(fault, dict) else None
        return {
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

    def _hardware_fault_block(self, room):
        entities = self._hardware_entities(room)
        for owner in self.rooms:
            fault = owner.hardware_fault
            if fault and (owner is room or entities.intersection(fault["entities"])):
                return (
                    f"hardware fault in {owner.slug}: {fault['reason']}; turn OFF "
                    f"{owner.enable_flag} and engines sharing this hardware, "
                    "verify all hardware OFF, then re-arm"
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

    def _latch_hardware_fault(self, room, reason):
        room.hardware_fault = {
            "reason": reason,
            "entities": sorted(self._hardware_entities(room)),
        }
        saved = self._save_state()
        self._alert(
            f"hardware_fault_{room.slug}",
            "CRITICAL — hardware hold latched",
            f"{room.slug}: {reason}. Further pumping on shared hardware is blocked. "
            f"Turn OFF {room.enable_flag} and every engine sharing this hardware. "
            "Repair/check every pump and valve; the hold clears only when all affected "
            "engines and hardware read OFF. "
            "Then explicitly re-arm. "
            + (
                ""
                if saved
                else "FAULT STATE COULD NOT BE SAVED — do not restart before repair."
            ),
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
            if not all(ha_get(r.enable_flag)[0] == "off" for r in affected):
                continue
            for affected_room in affected:
                entities.update(self._hardware_entities(affected_room))
            if not entities or not all(ha_get(e)[0] == "off" for e in entities):
                continue
            room.hardware_fault = None
            if not self._save_state():
                room.hardware_fault = fault  # clearing must also survive a restart
                continue
            log(
                f"[{room.slug}] hardware hold cleared: engine OFF and hardware verified OFF; re-arm required"
            )

    def _wait_shot(self, room, zone, duration_s, started=None):
        """Wait to a monotonic deadline, including HA latency and valve-open command time.

        Check kill/override between <=2 s sleeps using bounded reads. This remains
        synchronous: other rooms wait and network/device delays can delay shutdown.
        Returns actual seconds elapsed and whether a definitive kill OFF / override ON
        interrupted it. An unreadable flag retains the existing in-flight policy.
        """
        started = time.monotonic() if started is None else started
        deadline = started + duration_s
        step = 2.0
        while time.monotonic() < deadline:
            for entity, stop_state in (
                (room.enable_flag, "off"),
                (f"switch.crop_steering_{room.prefix}room_active", "off"),
                (
                    f"switch.crop_steering_{room.prefix}zone_{zone}_manual_override",
                    "on",
                ),
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                # Account for network time, and never start an eight-second read when
                # less than that remains. HTTP/socket scheduling can still overshoot;
                # return measured time rather than pretending sleep time was delivery.
                state = ha_get(entity, timeout=min(step, remaining))[0]
                if state == stop_state:
                    return time.monotonic() - started, True
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(step, remaining))
        return time.monotonic() - started, False

    @staticmethod
    def _confirm_switches(entities, want):
        """True only when every switch reads back `want`.

        Zigbee/MQTT plugs accept a command at once but report the new state later
        (veg_main_pump OFF report: usually <1 s, 1.6 s on 2026-09-14 18:52). A read-back
        that gives up too early latches a false hardware hold; one that waits too long
        stalls every room (this loop is synchronous) before a real stuck-open is caught.
        """
        # First read at 1 s, exactly as before, so a plug that reports promptly costs nothing extra.
        # A late report is then re-read every 0.5 s up to 6 s in all: nearly four times the worst lag
        # seen, and still short enough that a genuinely stuck-open valve latches the hold within the
        # same minute's loop. The pump has already been commanded OFF by the time this runs.
        deadline = time.monotonic() + CONFIRM_TIMEOUT_S
        time.sleep(CONFIRM_FIRST_READ_S)
        while True:
            if all(ha_get(ent)[0] == want for ent in entities):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(CONFIRM_POLL_S)

    def _execute_shot(self, room, zone, duration_s, size_pct, *, flow_lps=None):
        if self._hardware_fault_block(room):
            return
        plumbing = plumbing_hold(room.hw)
        if plumbing:  # never open a valve on a room whose declared pump is not there to run
            log(f"[{room.slug}] Z{zone} shot held: {plumbing}")
            return
        strategy_hold = self._strategy_preflight(room, zone, datetime.now())
        if strategy_hold:
            log(f"[{room.slug}] Z{zone} shot held: {strategy_hold}")
            return
        # Freeze hydraulic sizing before opening hardware. Editing plant count,
        # substrate or dripper configuration mid-shot must not rewrite its litres.
        nominal_l = (flow_lps * duration_s if flow_lps is not None
                     else size_pct / 100.0 * self._substrate_l(room, zone))
        self._busy = True
        hw = room.hw
        valve = hw["valves"].get(zone)
        shutdown_checked = False
        try:
            # OPEN sequence — FAIL CLOSED: if any service call errors, cut what's on, alert, and DO NOT count the shot
            # (otherwise daily_vol / last_shot lie after an auth/entity/service failure and a zone silently starves).
            # Pump and mainline are optional (a one-switch tent has neither): each is sequenced when
            # mapped and skipped, with its lead time, when not. The valve is always required.
            pump, mainline = hw.get("pump"), hw.get("mainline")
            if pump and not ha_call("switch", "turn_on", entity_id=pump):
                self._alert(
                    f"hw_{room.slug}_z{zone}",
                    "Shot aborted — pump command failed",
                    f"{room.slug} zone {zone}: pump turn_on returned an error. No water delivered, shot NOT counted.",
                )
                return
            if pump:
                time.sleep(2)
            if mainline and not ha_call("switch", "turn_on", entity_id=mainline):
                if pump:
                    ha_call("switch", "turn_off", entity_id=pump)
                self._alert(
                    f"hw_{room.slug}_z{zone}",
                    "Shot aborted — mainline command failed",
                    f"{room.slug} zone {zone}: mainline turn_on failed. Pump cut. No water, shot NOT counted.",
                )
                return
            if mainline:
                time.sleep(1)
            valve_started = time.monotonic()
            if not ha_call("switch", "turn_on", entity_id=valve):
                for upstream in (mainline, pump):
                    if upstream:
                        ha_call("switch", "turn_off", entity_id=upstream)
                self._alert(
                    f"hw_{room.slug}_z{zone}",
                    "Shot aborted — valve command failed",
                    f"{room.slug} zone {zone}: valve {valve} turn_on failed. Anything upstream was cut. No water, shot NOT counted.",
                )
                return
            elapsed, aborted = self._wait_shot(
                room, zone, duration_s, started=valve_started
            )
            # CLOSE sequence. A failed close (e.g. HA went unreachable mid-shot) leaves the valve
            # OPEN and the SOFTWARE CANNOT fix it — only the hardware fail-safe (NC valve /
            # pump-relay-default-off / independent watchdog) can. So check EVERY turn_off + the
            # read-back and ALERT loudly on any non-close (the old code ignored turn_off failures
            # and a dead-HA read-back masked a stuck-open valve as "closed" — silent danger).
            close_ok = ha_call("switch", "turn_off", entity_id=valve)
            # Delivery is estimated, not flow-metered. Include the acknowledgement
            # interval conservatively because the exact physical close time is unknown.
            elapsed = max(elapsed, time.monotonic() - valve_started)
            upstream = [e for e in (mainline, pump) if e]  # closed valve first, then back up the line
            if upstream:
                time.sleep(1)
            for ent in upstream:
                close_ok = ha_call("switch", "turn_off", entity_id=ent) and close_ok
            # Only a definitive OFF is safe, including pump/mainline read-back.
            closed = self._confirm_switches((valve, *upstream), "off")
            if not close_ok or not closed:
                for ent in reversed(upstream):
                    ha_call("switch", "turn_off", entity_id=ent)
                self._latch_hardware_fault(
                    room, f"zone {zone} valve/pump/mainline close not confirmed"
                )
            shutdown_checked = True
            # Count the shot — water WAS delivered, so daily_vol/last_shot must reflect it (else the
            # daily cap under-counts and the zone can over-water). A kill-switch/override abort mid-shot
            # only delivered part of the shot, so scale the volume by the fraction actually run.
            delivered_pct = size_pct * (elapsed / duration_s if duration_s > 0 else 1.0)
            self._advance_shot_counters(
                room, zone, delivered_pct,
                delivered_l=nominal_l * (elapsed / duration_s if duration_s > 0 else 1.0),
            )
            if aborted:
                self._alert(
                    f"killshot_{room.slug}_z{zone}",
                    "Shot cut short — kill switch / override",
                    f"{room.slug} zone {zone}: shot aborted after {elapsed:.0f}/{duration_s:.0f}s "
                    "by the kill switch or manual override. Valve closed; partial volume counted.",
                )
        except Exception as e:
            log("shot error", room.slug, zone, e)
        finally:
            try:
                # Early command failures and unexpected exceptions need the SAME hold
                # guarantee as normal shutdown; no path may start the next row blindly.
                if not shutdown_checked:
                    closing = [
                        e for e in (valve, hw.get("mainline"), hw.get("pump")) if e
                    ]
                    close_ok = True
                    for ent in closing:
                        close_ok = (
                            ha_call("switch", "turn_off", entity_id=ent) and close_ok
                        )
                    closed = all(ha_get(ent)[0] == "off" for ent in closing)
                    if not close_ok or not closed:
                        self._latch_hardware_fault(
                            room, f"zone {zone} error cleanup close not confirmed"
                        )
            finally:
                self._busy = False

    def _safe_off(self):
        for room in self.rooms:
            if room.hw.get("pump"):
                ha_call("switch", "turn_off", entity_id=room.hw["pump"])
            if room.hw.get("mainline"):
                ha_call("switch", "turn_off", entity_id=room.hw["mainline"])
            for v in room.hw["valves"].values():
                if v:
                    ha_call("switch", "turn_off", entity_id=v)

    def _safe_exit(self, *_):
        log("SIGTERM — safing hardware + exiting")
        try:
            self._safe_off()
            self._save_state()
        finally:
            sys.exit(0)

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
    def _substrate_l(self, room, zone):
        """ZONE-TOTAL substrate (L) = per-plant block x plant_count. The substrate_volume entity is the
        PER-PLANT block size (e.g. 6 L); flow_lps is zone-total (plant_count x drippers x L/hr), so the
        duration + daily-volume math need zone-total substrate or shots come out plant_count-times short
        (the machine-gun: per-plant 6 L / zone flow -> ~36x too short, VWC never rises).
        """
        per_plant = self._zone_num(room, zone, "substrate_volume", self.substrate_l)
        pc = self._zone_num(room, zone, "plant_count", 0)
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
        pc = self._zone_num(room, zone, "plant_count", 0) or 1
        dpp = self._zone_num(room, zone, "drippers_per_plant", 1)
        fr = self._zone_num(
            room,
            zone,
            "dripper_flow_rate",
            self._num(f"number.crop_steering_{room.prefix}dripper_flow_rate", 0),
        )  # L/hr per dripper; preserve the legacy global fallback.
        if dpp > 0 and fr > 0:
            return pc * dpp * fr / 3600.0
        return self.flow_lps

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
                "URGENT — zone starving",
                f"{room.slug} zone {zone}: no water {snap.minutes_since_shot/60.0:.1f}h, "
                f"VWC {snap.vwc:.0f}<{p.p2_threshold:.0f}, blocked by '{block}'.",
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
                    "Invalid hydraulic sizing",
                    "Positive readable substrate and zone flow are required",
                )
                return
            raw_dur = size / 100.0 * substrate / flow
            max_dur = self._room_duration_cap(room)
            if max_dur is None:
                return
            # Hydraulic sizing determines nominal runtime; the room's duration
            # limit bounds every physical shot independently of its requested volume.
            dur = max(5, min(int(max_dur), int(raw_dur)))
            if raw_dur > max_dur:
                self._alert(
                    f"durcap_{room.slug}_z{zone}",
                    "Shot duration capped (flood guard)",
                    f"{room.slug} zone {zone}: computed {int(raw_dur)}s > {int(max_dur)}s cap — clamped. Check substrate volume / flow config.",
                )
            log(f"[{room.slug}] Z{zone} {st['phase']} FIRE {size}% ~{dur}s — {reason}")
            # Count configured flow x actual runtime, including caps, truncation,
            # the minimum duration and partial aborts. Preserve this flow snapshot
            # so later sizing edits cannot change an already delivered volume.
            self._execute_shot(room, zone, dur, size, flow_lps=flow)
        else:
            if "BLOCK" in reason:
                self._alert(
                    f"block_{room.slug}_z{zone}",
                    "Zone blocked — needs attention",
                    f"{room.slug} zone {zone} ({st['phase']}): {reason}",
                )
            # A gate that is closed is said out loud in every phase: overnight nothing is due, and a
            # room blocked since a restart used to look exactly like a healthy one until lights-on.
            log(f"[{room.slug}] Z{zone} {st['phase']} hold — {reason}"
                + (f" [blocked: {block}]" if block else ""))

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
            self._alert(
                "defaulted_setpoints",
                "Setpoint entities missing — using engine defaults",
                "These setpoint entities don't exist in HA, so the engine is running its "
                "built-in defaults (reload the integration / check for renamed entities):\n"
                + "\n".join(persistent[:20]),
            )

    def loop_once(self, now):
        if self._busy:
            return
        self._recover_hardware_faults()
        self._defaulted_this_loop = set()
        if (now - self._last_discovery).total_seconds() >= self.rediscover_seconds:
            try:
                self._rediscover(now)
            except Exception as e:
                log("rediscover error", e)
        all_pub = {}
        for room in self.rooms:
            self._refresh_lights(room)
            pub = self._loop_room(room, now)
            self._publish_status(room, pub, now)
            all_pub[room.slug] = pub
        self._check_defaulted_setpoints()
        self._maybe_notify(all_pub, now)

    def _blind_time_transition(self, room, zone, now, lights_on, lights_just_on):
        """Time-only phase forces for a BLIND zone (dead/missing probe), so it can never
        strand overnight while `decide()` is skipped: lights-off -> P3, and P3 -> P0 at the
        new photoperiod (with the daily-counter reset, mirroring the P0 branch in _loop_room).
        The VWC-driven transitions (P0->P1->P2, predictive P3) need a probe and stay paused.
        """
        st = room.state[zone]
        gds = self._grow_day_start(room, now)
        new_grow_day = lights_on and (
            st.get("last_daily_reset") is None or st["last_daily_reset"] < gds
        )
        new_phase = None
        if not lights_on and st["phase"] != "P3":
            new_phase = "P3"
        elif st["phase"] == "P3" and (lights_just_on or new_grow_day):
            new_phase = "P0"
        if new_phase and new_phase != st["phase"]:
            if new_phase == "P0":
                st["daily_vol"], st["shots"] = 0.0, 0
                st["ec_offset"], st["last_ec_steer"] = 0.0, None
                st["ec_integral"], st["ec_prev_err"] = 0.0, 0.0
                st["last_daily_reset"] = gds
            st["phase"] = new_phase
            st["last_phase_change"] = now
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
            return {}
        active, was = self._room_active(room), getattr(room, "_was_room_active", None)
        room._was_room_active = active
        if not active:
            if was is not False:
                self._room_switched_off(room)
            self._publish_room_off(room, now)
            return {}  # no snapshot, no decision, no blind schedule, no alerts, no vitals line
        if was is False:
            self._room_switched_on(room)
        self._load_strategy_snapshot(room, now)
        # Only a newly computed batch can clear a prior preflight invalidation.
        room._strategy_batch_invalid = False
        lights_on = self._lights_on(room, now)
        was_off = not (
            room._was_lights_on if room._was_lights_on is not None else lights_on
        )
        lights_just_on = lights_on and was_off
        snaps, decisions, healthy, blind, params = {}, {}, [], [], {}
        for zone in room.zones:
            st = room.state[zone]
            self._water_usage(room, zone, now)
            snap, p = self._snapshot(room, zone, now, lights_on, lights_just_on)
            params[zone] = p
            if snap is None:
                blind.append((zone, p))
                continue
            snaps[zone] = snap
            if snap.ec is None:
                self._alert(
                    f"ec_unknown_{room.slug}_z{zone}",
                    f"{room.slug} Z{zone} EC unavailable — base VWC watering",
                    "No valid, fresh pore EC. EC shot scaling and PID/step learning are paused; "
                    "salt protection and flushing cannot be verified. Base VWC watering and "
                    "dry rescue remain active, subject to source-water and volume gates.",
                )
            healthy.append((zone, p.p1_target))
            new_phase, new_thr, fire, size, reason = decide(snap, p)
            if new_phase != st["phase"]:
                if new_phase == "P0":
                    st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, snap.vwc
                    st["ec_offset"], st["last_ec_steer"] = 0.0, None
                    st["ec_integral"], st["ec_prev_err"] = (
                        0.0,
                        0.0,
                    )  # no cross-photoperiod PID windup
                    st["last_daily_reset"] = self._grow_day_start(room, now)
                    room._vmax_wetup[zone] = []  # fresh wet-up curve for today's ramp
                if new_phase == "P1":
                    st["shots"] = 0
                st["phase"] = new_phase
                st["last_phase_change"] = now
                self._save_state()
            if snap.ec is not None and p.stacking_on and st["phase"] == "P2" and p.ec_target_p2 > 0:
                base = self._zone_num(room, zone, "p2_vwc_threshold", 45)
                les = st.get("last_ec_steer")
                if les is None or (now - les).total_seconds() >= 1800:
                    if self._on("input_boolean.crop_steering_ec_pid_enabled", False):
                        gains = (
                            self._num("input_number.crop_steering_ec_pid_kp", 0.4),
                            self._num("input_number.crop_steering_ec_pid_ki", 0.15),
                            self._num("input_number.crop_steering_ec_pid_kd", 0.0),
                        )
                        off, integ, perr = ec_pid(
                            snap.ec_smooth,
                            p.ec_target_p2,
                            base,
                            float(st.get("ec_integral", 0.0)),
                            float(st.get("ec_prev_err", 0.0)),
                            gains,
                        )
                        st["ec_offset"], st["ec_integral"], st["ec_prev_err"] = (
                            off,
                            integ,
                            perr,
                        )
                    else:
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
                series = room._vmax_wetup.setdefault(zone, [])
                series.append(snap.vwc)
                room._vmax_wetup[zone] = series[-40:]
                v, c = detect_vmax(room._vmax_wetup[zone])
                if v is not None:
                    room._vmax[zone] = (v, c)
            decisions[zone] = (fire, size, reason)
            try:  # learning and setpoint upkeep must never be able to stop a zone being watered
                self._auto_tick(room, zone, snap, p, lights_on, now)
            except Exception as e:
                log("auto setpoints error", room.slug, zone, e)
        for zone, p in blind:
            st = room.state[zone]
            # A dead probe must NOT freeze the daily cycle: still honour the time-based
            # phase forces (lights-off -> P3, P3 -> P0 at the new photoperiod). Only the
            # VWC-driven transitions are paused while blind.
            self._blind_time_transition(room, zone, now, lights_on, lights_just_on)
            looking = f"sensor.crop_steering_{room.prefix}vwc_zone_{zone}"
            if healthy:
                sib = pick_sibling(p.p1_target, healthy)
                s_fire, s_size, _ = decisions[sib]
                decisions[zone] = (s_fire, s_size, f"COPY Z{sib} (VWC probe dead)")
                # Re-alert each tick — _alert's 30-min debounce throttles it to a repeating
                # reminder so a dead probe can't sit unnoticed (the silent-freeze lesson).
                self._alert(
                    f"blind_{room.slug}_z{zone}",
                    f"⚠️ {room.slug} Z{zone} moisture probe dead — copying Z{sib}",
                    f"No live VWC at {looking}. Mirroring Zone {sib} until it returns.",
                )
            else:
                mss = self._minutes_since_shot(st, now)
                decisions[zone] = (
                    mss >= self.blind_fallback_min,
                    p.p2_shot_size,
                    "FALLBACK schedule (no live probe)",
                )
                self._alert(
                    f"blind_{room.slug}_z{zone}",
                    f"⚠️ {room.slug} Z{zone} probe dead — blind schedule",
                    f"No live VWC at {looking} and no healthy sibling. On a "
                    f"{int(self.blind_fallback_min)}-min blind safety schedule; VWC-driven "
                    "phase steering is paused until a probe returns.",
                )
            room._blind_zones.add(zone)
        room._blind_zones = {z for z in room._blind_zones if z not in snaps}
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
            block = self._blocked(room, zone) if fire else None
            self._act_zone(
                room,
                zone,
                params[zone],
                snaps.get(zone),
                decisions[zone],
                block,
                lights_on,
                now,
            )
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
                f"xzone_{room.slug}_{z}", "Zone under-drinking vs siblings", why
            )
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
                saf = zone_safety_status(d["vwc"], d["ec"], p.field_capacity, p.max_ec)
                labels.append(saf)
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_phase",
                    d["phase"],
                    {"reason": d["reason"], "engine": "f2-control"},
                )
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_safety_status",
                    saf,
                    {
                        "vwc": d["vwc"],
                        "ec": d["ec"],
                        "ec_valid": d["ec"] is not None,
                        "ec_degraded": d["ec"] is None,
                        "ec_fallback": "base_vwc" if d["ec"] is None else None,
                        "field_capacity": p.field_capacity,
                        "max_ec_limit": p.max_ec,
                    },
                )
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_status",
                    zone_status_label(
                        d["phase"], d["fire"], d["block"], d["blind"], d["reason"]
                    ),
                    {"reason": d["reason"]},
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
                            "engine": "f2-control",
                        },
                    )
                ls = room.state[zone].get("last_shot")
                if ls is not None:
                    ha_set(
                        f"sensor.crop_steering_{px}zone_{zone}_last_irrigation_app",
                        # Internal times stay local-naive; publish the event's local
                        # UTC offset, including historical daylight-saving changes.
                        ls.astimezone().isoformat(),
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
                        "engine": "f2-control",
                    },
                )
                weekly, coverage = self._water_usage(room, zone, now)
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_weekly_water_app",
                    weekly,
                    {"unit_of_measurement": "L", "device_class": "water",
                     "state_class": "total", "friendly_name": f"Zone {zone} water over seven grow-days",
                     "engine": "f2-control", **coverage},
                )
                ha_set(
                    f"sensor.crop_steering_{px}zone_{zone}_irrigation_count_app",
                    int(zst.get("shots") or 0),
                    {
                        "state_class": "total",
                        "friendly_name": f"Zone {zone} shots today",
                        "engine": "f2-control",
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
                            "engine": "f2-control",
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
                {"engine": "f2-control", "updated": now.isoformat()},
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
            on = self._on(room.enable_flag, False)
            any_live = any_live or on
            feed = self._read_feed_ec(room)
            head = (room.slug if room.prefix else self.instance_name) + (
                " LIVE" if on else " HELD"
            )
            head += f" | feed EC {feed if feed is not None else '—'}"
            lines = [head]
            for z in sorted(pub):
                d = pub[z]
                st = room.state[z]
                mss = self._minutes_since_shot(st, now)
                ago = "never" if mss > 1e8 else f"{mss/60:.1f}h"
                vwc = f"{d['vwc']:.0f}%" if d["vwc"] is not None else "—"
                ec = f"{d['ec']:.1f}" if d["ec"] is not None else "—"
                fc = f"{st['peak']:.0f}" if st.get("peak") else "—"
                lines.append(
                    f"  Z{z} {d['phase']}: VWC {vwc} EC {ec} (FC~{fc}) | {st['daily_vol']:.1f}L day | last {ago}"
                )
            blocks.append("\n".join(lines))
        if not blocks:
            return
        head = now.strftime("%H:%M")
        if self._n_defaulted:
            head += f"  ⚠️ {self._n_defaulted} setpoint(s) missing → engine defaults"
        msg = f"{head}\n" + "\n".join(blocks)
        dom, _, svc = self.notify_service.partition("/")
        if dom and svc:
            ha_call(dom, svc, title=f"{self.instance_name} vitals", message=msg)
        ha_call(
            "persistent_notification",
            "create",
            title=f"{self.instance_name} vitals",
            message=msg,
            notification_id="f2_vitals",
        )
        ha_set(
            "sensor.f2_control_vitals",
            now.strftime("%H:%M"),
            {"vitals": msg, "live": any_live},
        )

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
            r = _S.get(f"{BASE}/config", headers=HDR, timeout=8)
            ha_tz = (r.json() or {}).get("time_zone") if r.status_code == 200 else None
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
                "Timezone mismatch — irrigation day may be shifted",
                f"Add-on container is UTC{off_h:+.1f}h but Home Assistant is {ha_tz} "
                f"(UTC{ha_off:+.1f}h). Lights / dryback / daily-reset all use container-local "
                "time, so this shifts the whole photoperiod. Ensure the add-on image has tzdata "
                "and the Supervisor is injecting TZ.",
            )
        else:
            log(f"timezone: matches Home Assistant ({ha_tz})")

    def run(self):
        log(
            f"f2-control {CONTROLLER_VERSION} starting | rooms",
            ", ".join(r.slug for r in self.rooms),
            "| notify",
            self.notify_service or "(none)",
            f"| loop {self.loop_seconds:.0f}s",
        )
        log("token present:", bool(TOKEN), "| base:", BASE)
        self._log_timezone()
        while True:
            try:
                self.loop_once(datetime.now())
            except Exception as e:
                log("loop error", e)
            time.sleep(self.loop_seconds)


if __name__ == "__main__":
    Controller().run()
