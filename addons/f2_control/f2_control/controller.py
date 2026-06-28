# -*- coding: utf-8 -*-
"""F2 Control — standalone crop-steering controller (Home Assistant add-on).

The synchronous I/O shell: ONE sync process, plain REST polling of HA, no asyncio, no
coroutine trap. Imports the pure crop-steering-engine for decisions; this file is
the thin IO shell (read sensors -> decide -> drive valves with readback) plus
durable state, status republish, a 30-min vitals notification, and a hard kill-switch.

Talks to HA through the Supervisor proxy (http://supervisor/core/api) with the
auto-injected SUPERVISOR_TOKEN. Safe-offs the hardware on exit.
"""
import json
import os
import signal
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

from crop_steering_engine import (
    decide, ZoneParams, ZoneSnapshot, validate_params, pick_sibling, feed_grace_ok, ec_pid,
    cross_zone_outliers, zone_safety_status, system_safety_status, zone_status_label,
)

# ---------------------------------------------------------------- HA REST (Supervisor proxy)
BASE = os.environ.get("HA_URL", "http://supervisor/core/api")
TOKEN = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN", "")
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
_S = requests.Session()


def log(*a):
    print("[f2-control]", *a, flush=True)


def ha_get(entity):
    """Return (state_str, attributes, last_updated_iso) or (None, {}, None)."""
    try:
        r = _S.get(f"{BASE}/states/{entity}", headers=HDR, timeout=8)
        if r.status_code != 200:
            return None, {}, None
        d = r.json()
        return d.get("state"), d.get("attributes", {}), d.get("last_updated")
    except Exception:
        return None, {}, None


def ha_call(domain, service, **data):
    try:
        r = _S.post(f"{BASE}/services/{domain}/{service}", headers=HDR, json=data, timeout=12)
        if r.status_code >= 300:
            log("call_service FAILED", domain, service, "HTTP", r.status_code)
            return False
        return True
    except Exception as e:
        log("call_service failed", domain, service, e)
        return False


def ha_set(entity, state, attributes=None):
    try:
        _S.post(f"{BASE}/states/{entity}", headers=HDR,
                json={"state": state, "attributes": attributes or {}}, timeout=8)
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


class Controller:
    def __init__(self):
        o = load_options()
        # Sensors are owned by the INTEGRATION: it fuses every probe you map to a zone
        # (any number — median/average) into sensor.crop_steering_vwc_zone_N and
        # sensor.crop_steering_ec_zone_N. The engine just reads those fused sensors, so
        # "add as many probes per zone as you want" is done in the integration UI, not here.
        # `zones` stays as an explicit override (rarely needed); otherwise we build the
        # fused-sensor map for `num_zones` zones.
        zones_opt = o.get("zones")
        if zones_opt:
            self.zones = {int(k): v for k, v in zones_opt.items()}
        else:
            # auto-detect zone count from the integration's fused sensors (configure once);
            # fall back to the option if HA isn't reachable yet at startup.
            n = self._detect_zones(int(o.get("num_zones", 3)))
            self.zones = {
                z: {
                    "vwc": f"sensor.crop_steering_vwc_zone_{z}",
                    "ec": f"sensor.crop_steering_ec_zone_{z}",
                }
                for z in range(1, n + 1)
            }
        self.hw = o.get("hardware") or {
            "pump": "switch.veg_main_pump",
            "mainline": "switch.espoe_irrigation_relay_2_3",
            "valves": {1: "switch.f2_row1", 2: "switch.f2_row2", 3: "switch.f2_row3"},
        }
        self.hw["valves"] = {int(k): v for k, v in self.hw["valves"].items()}
        # Lights come from the integration (number.crop_steering_lights_on_hour / _off_hour)
        # so they're configured once in the UI; the add-on options are only a fallback.
        self._opt_lon = float(o.get("lights_on_hour", 10))
        self._opt_loff = float(o.get("lights_off_hour", 22))
        self.lights_on_hour = self._opt_lon
        self.lights_off_hour = self._opt_loff
        self._lights_logged = False
        self.flow_lps = float(o.get("flow_lps", 0.02))     # generic last-resort fallback — real flow is computed live per zone
        self.substrate_l = float(o.get("substrate_l", 5))  # generic last-resort fallback — real volume read live from the integration
        self.enable_flag = o.get("enable_flag", "input_boolean.f2_control_enabled")  # the KILL SWITCH (must be ON)
        self.notify_service = o.get("notify_service", "notify/mobile_app_s23ultra")
        self.notify_min = float(o.get("notify_min", 30))
        self.feed_grace_min = float(o.get("feed_grace_min", 30))
        self.blind_fallback_min = float(o.get("blind_fallback_min", 90))
        self.loop_seconds = float(o.get("loop_seconds", 60))

        self._state_path = "/data/state.json"
        self.state = self._load_state()
        self._busy = False
        self._alerted = {}
        self._activity = []
        self._blind_zones = set()
        # Source-water feed gate sensors are OPTIONAL and have NO default entity — an empty
        # (or unset) value disables that half of the source-water gate so the add-on works on
        # any install out of the box. Configure your own probe entity ids to enable gating.
        self.feed_ec_sensor = (o.get("feed_ec_sensor") or "").strip()
        self.feed_ph_sensor = (o.get("feed_ph_sensor") or "").strip()
        if not self.feed_ec_sensor and not self.feed_ph_sensor:
            log("config: no feed_ec_sensor/feed_ph_sensor set — source-water pH/EC gate "
                "disabled (dosing/fill holds still apply); set them to enable feed gating")
        elif not self.feed_ec_sensor:
            log("config: no feed_ec_sensor set — source-water EC gate disabled (pH gate active)")
        elif not self.feed_ph_sensor:
            log("config: no feed_ph_sensor set — source-water pH gate disabled (EC gate active)")
        else:
            log(f"config: feed gate EC={self.feed_ec_sensor} pH={self.feed_ph_sensor}")
        self._feed_last_good_value = None
        self._feed_last_good_time = None
        self._feed_ph_last_good = None
        self._feed_ph_last_good_time = None
        self._was_lights_on = None
        self._last_notify = None
        self._start = datetime.now()
        signal.signal(signal.SIGTERM, self._safe_exit)
        signal.signal(signal.SIGINT, self._safe_exit)

    # ---------- durable state ----------
    def _fresh_zone(self):
        return {"phase": "P2", "peak": 0.0, "win": [], "last_shot": None, "shots": 0,
                "daily_vol": 0.0, "ec_smooth": None, "last_phase_change": datetime.now(),
                "ec_offset": 0.0, "ec_integral": 0.0, "ec_prev_err": 0.0,
                "last_ec_steer": None, "last_daily_reset": None}

    def _load_state(self):
        st = {z: self._fresh_zone() for z in self.zones}
        try:
            with open(self._state_path) as fh:
                saved = json.load(fh)
        except (FileNotFoundError, ValueError, OSError):
            return st
        for z in self.zones:
            d = saved.get(str(z)) or saved.get(z)
            if not isinstance(d, dict):
                continue
            s = st[z]
            for k in ("phase", "peak", "shots", "daily_vol", "ec_smooth", "ec_offset", "ec_integral", "ec_prev_err"):
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
        return st

    def _save_state(self):
        out = {}
        for z, s in self.state.items():
            ls, lpc, les, ldr = s.get("last_shot"), s.get("last_phase_change"), s.get("last_ec_steer"), s.get("last_daily_reset")
            out[str(z)] = {"phase": s.get("phase"), "peak": s.get("peak"), "shots": s.get("shots"),
                           "daily_vol": s.get("daily_vol"), "ec_smooth": s.get("ec_smooth"),
                           "ec_offset": float(s.get("ec_offset") or 0.0),
                           "ec_integral": float(s.get("ec_integral") or 0.0), "ec_prev_err": float(s.get("ec_prev_err") or 0.0),
                           "last_shot": ls.isoformat() if isinstance(ls, datetime) else None,
                           "last_phase_change": lpc.isoformat() if isinstance(lpc, datetime) else None,
                           "last_ec_steer": les.isoformat() if isinstance(les, datetime) else None,
                           "last_daily_reset": ldr.isoformat() if isinstance(ldr, date) else None}
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(out, fh)
            os.replace(tmp, self._state_path)
        except OSError as e:
            log("state save failed", e)

    # ---------- HA read helpers ----------
    def _num(self, entity, default):
        v, _, _ = ha_get(entity)
        try:
            return float(v) if v not in (None, "unknown", "unavailable", "") else float(default)
        except Exception:
            return float(default)

    def _zone_num(self, zone, suffix, default):
        per = f"number.crop_steering_zone_{zone}_{suffix}"
        v, _, _ = ha_get(per)
        if v not in (None, "unknown", "unavailable", ""):
            return self._num(per, default)
        return self._num(f"number.crop_steering_{suffix}", default)

    def _num_or_none(self, entity):
        """Read a number entity as float, or None if it doesn't exist / isn't a number."""
        v, _, _ = ha_get(entity)
        try:
            return float(v) if v not in (None, "unknown", "unavailable", "") else None
        except Exception:
            return None

    def _detect_zones(self, fallback):
        """Count zones from the integration's fused VWC sensors. Returns the number of
        consecutive sensor.crop_steering_vwc_zone_N that exist, or `fallback` if none do
        (e.g. HA not reachable yet at startup)."""
        n = 0
        for z in range(1, 25):
            state, _, _ = ha_get(f"sensor.crop_steering_vwc_zone_{z}")
            if state is None:
                break
            n += 1
        return n or fallback

    def _on(self, entity, default=False):
        v, _, _ = ha_get(entity)
        if v in (None, "unknown", "unavailable", ""):
            return default
        return str(v).lower() in ("on", "true", "open", "1", "home")

    def _read_sensor(self, entity, lo=0.0, hi=200.0, max_age_min=20):
        v, _, lu = ha_get(entity)
        if v in (None, "unknown", "unavailable", ""):
            return None
        try:
            f = float(v)
        except Exception:
            return None
        if f < lo or f > hi:
            return None
        try:
            if lu:
                ts = datetime.fromisoformat(str(lu).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - ts).total_seconds() > max_age_min * 60.0:
                    return None
        except Exception:
            pass
        return f

    def _read_feed_ec(self):
        if not self.feed_ec_sensor:
            return None
        feed = self._read_sensor(self.feed_ec_sensor, lo=0, hi=20)
        if feed is not None:
            lo = self._num("number.crop_steering_irrigation_ec_min", 0)
            hi = self._num("number.crop_steering_irrigation_ec_max", 0)
            if (lo <= 0 or feed >= lo) and (hi <= 0 or feed <= hi):
                self._feed_last_good_value, self._feed_last_good_time = feed, datetime.now()
        return feed

    def _read_feed_ph(self):
        if not self.feed_ph_sensor:
            return None
        ph = self._read_sensor(self.feed_ph_sensor, lo=0, hi=14)
        if ph is not None:
            lo = self._num("number.crop_steering_irrigation_ph_min", 0)
            hi = self._num("number.crop_steering_irrigation_ph_max", 0)
            if (lo <= 0 or ph >= lo) and (hi <= 0 or ph <= hi):
                self._feed_ph_last_good, self._feed_ph_last_good_time = ph, datetime.now()
        return ph

    def _veg(self, zone):
        v, _, _ = ha_get(f"select.crop_steering_zone_{zone}_steering_mode")
        if v in (None, "unknown", "unavailable", ""):
            v, _, _ = ha_get("select.crop_steering_growth_stage")
        return str(v or "Generative").lower().startswith("veg")

    def _lights_on(self, now):
        h = now.hour + now.minute / 60.0
        on, off = self.lights_on_hour, self.lights_off_hour
        return (on <= h < off) if on <= off else (h >= on or h < off)

    def _hours_to(self, now, target):
        h = now.hour + now.minute / 60.0
        d = target - h
        return d if d >= 0 else d + 24.0

    def _grow_day_start(self, now):
        return now.date() if (now.hour + now.minute / 60.0) >= self.lights_on_hour else (now - timedelta(days=1)).date()

    def _refresh_lights(self):
        """Lights are configured once in the integration. Read them live from
        number.crop_steering_lights_on_hour / _off_hour each loop, falling back to the
        add-on option if the entities are missing. Log the source once, and alert once if
        the integration value disagrees with the (now-legacy) add-on option."""
        lon = self._num_or_none("number.crop_steering_lights_on_hour")
        loff = self._num_or_none("number.crop_steering_lights_off_hour")
        if lon is not None and loff is not None:
            src = "integration"
        else:
            lon, loff, src = self._opt_lon, self._opt_loff, "add-on option (integration entity missing)"
        if not self._lights_logged:
            log(f"config: lights {int(lon)}:00-{int(loff)}:00 (source: {src})")
            if src == "integration" and (lon != self._opt_lon or loff != self._opt_loff):
                self._alert(
                    "lights_source",
                    "Lights now read from the integration",
                    f"Engine uses {int(lon)}:00-{int(loff)}:00 from the integration. The add-on "
                    f"option still says {int(self._opt_lon)}:00-{int(self._opt_loff)}:00 — if the "
                    "integration value is wrong, set number.crop_steering_lights_on_hour / _off_hour.",
                )
            self._lights_logged = True
        self.lights_on_hour, self.lights_off_hour = float(lon), float(loff)

    # ---------- params + snapshot ----------
    def _params(self, zone):
        veg = self._veg(zone)
        sfx = "veg" if veg else "gen"
        base = self._zone_num(zone, "p2_vwc_threshold", 45)
        p1t = self._zone_num(zone, "p1_target_vwc", 60)
        fc = self._zone_num(zone, "field_capacity", 70)
        efloor = self._zone_num(zone, "p3_emergency_vwc_threshold", 40)
        # EC-steer offset is shell-owned (decide() no longer nudges). Bake it into the
        # P2 rewater threshold, clamped to the same safe band the engine used: never
        # below the emergency-floor band, never above the ramp ceiling.
        p2_thr = base + float(self.state[zone].get("ec_offset", 0.0))
        p2_thr = max(efloor + 3.0, min(min(p1t, fc) - 1.0, p2_thr))
        raw = ZoneParams(
            p1_target=p1t,
            p2_threshold=p2_thr,
            p2_shot_size=self._zone_num(zone, "p2_shot_size", 5),
            p1_initial=self._zone_num(zone, "p1_initial_shot_size", 2),
            p1_incr=self._zone_num(zone, "p1_shot_size_increment", 0.5),
            p1_max_shots=int(self._zone_num(zone, "p1_maximum_shots", 12)),
            p1_time_between_min=self._zone_num(zone, "p1_time_between_shots", 15),
            dryback_target=self._zone_num(zone, f"{'vegetative' if veg else 'generative'}_dryback_target", 20),
            p0_max_wait_min=self._zone_num(zone, "p0_maximum_wait_time", 45),
            ec_target_p0=self._zone_num(zone, f"ec_target_{sfx}_p0", 4),
            ec_target_p1=self._zone_num(zone, f"ec_target_{sfx}_p1", 5),
            ec_target_p2=self._zone_num(zone, f"ec_target_{sfx}_p2", 6),
            p3_emergency_floor=efloor,
            p3_emergency_shot=self._zone_num(zone, "p3_emergency_shot_size", 2),
            max_daily_volume=self._zone_num(zone, "max_daily_volume", 300),
            field_capacity=fc,
            max_ec=self._zone_num(zone, "maximum_ec", 9),
            stacking_on=self._on("switch.crop_steering_ec_stacking_enabled", False),
            watchdog_hours=self._zone_num(zone, "watchdog_hours", 3),
            min_daily_volume=self._num(f"input_number.crop_steering_zone_{zone}_min_daily_ml_per_plant", 0.0)
            * self._zone_num(zone, "plant_count", 0) / 1000.0,   # mL/plant x plants -> zone-L floor (0 if either unset)
            drown_ceiling=self._zone_num(zone, "min_floor_drown_ceiling", 90),   # hard anti-drown VWC cap on the floor
        )
        p, warns = validate_params(raw)
        for w in warns:
            self._alert(f"cfg_z{zone}_{w.split('=')[0]}", "F2 config clamp", f"Zone {zone}: {w}")
        return p

    def _snapshot(self, zone, now, lights_on, lights_just_on):
        st = self.state[zone]
        vwc = self._read_sensor(self.zones[zone]["vwc"], lo=0, hi=100)
        ec = self._read_sensor(self.zones[zone]["ec"], lo=0, hi=20)
        if vwc is None:
            return None, self._params(zone)
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
            st["ec_smooth"] = ec if st["ec_smooth"] is None else 0.3 * ec + 0.7 * st["ec_smooth"]
        feed_live = self._read_feed_ec()
        if feed_live is not None:
            feed_ec = feed_live
        elif feed_grace_ok(now.timestamp(),
                           self._feed_last_good_time.timestamp() if self._feed_last_good_time else None,
                           self.feed_grace_min):
            feed_ec = self._feed_last_good_value
        else:
            feed_ec = None
        gds = self._grow_day_start(now)
        ldr = st.get("last_daily_reset")
        new_grow_day = lights_on and (ldr is None or ldr < gds)
        snap = ZoneSnapshot(
            vwc=vwc, ec=(ec if ec is not None else 0.0), phase=st["phase"], peak_vwc=st["peak"],
            dryback_pct=((st["peak"] - vwc) / st["peak"] * 100 if st["peak"] > 0 else 0),
            dryback_rate=rate, shot_count=st["shots"],
            phase_minutes=(now - st["last_phase_change"]).total_seconds() / 60.0,
            minutes_since_shot=((now - st["last_shot"]).total_seconds() / 60.0 if st["last_shot"] else 1e9),
            daily_vol=st["daily_vol"], ec_smooth=(st["ec_smooth"] if st["ec_smooth"] is not None else 0.0),
            lights_on=lights_on, lights_just_on=lights_just_on,
            hours_to_lights_on=self._hours_to(now, self.lights_on_hour),
            hours_to_lights_off=self._hours_to(now, self.lights_off_hour),
            uptime_min=(now - self._start).total_seconds() / 60.0,
            feed_ec=(feed_ec if feed_ec is not None else 3.0), new_grow_day=new_grow_day)
        return snap, self._params(zone)

    # ---------- gates ----------
    def _blocked(self, zone):
        if not self._on(self.enable_flag, False):
            return "f2-control disabled (kill switch off)"
        if not self._on("switch.crop_steering_system_enabled", False):
            return "system disabled"
        if not self._on("switch.crop_steering_auto_irrigation_enabled", False):
            return "auto-irrigation disabled"
        if not self._on(f"switch.crop_steering_zone_{zone}_enabled", True):
            return "zone disabled"
        if self._on(f"switch.crop_steering_zone_{zone}_manual_override", False):
            return "manual override"
        for f in ("input_boolean.nutrient_dosing_active", "input_boolean.f2_fill_mode",
                  "input_boolean.f2_flush_mode", "switch.tank_filling"):
            if self._on(f, False):
                return f"dosing/fill ({f.split('.')[-1]})"
        # Source-water EC gate — only when a feed-EC sensor is configured. With no feed sensor
        # the gate is disabled (the dosing/fill holds above still apply) so the add-on is safe
        # out of the box on installs without a reservoir probe.
        if self.feed_ec_sensor:
            feed = self._read_feed_ec()
            lo = self._num("number.crop_steering_irrigation_ec_min", 0)
            hi = self._num("number.crop_steering_irrigation_ec_max", 0)
            if lo > 0 or hi > 0:
                if feed is None:
                    if feed_grace_ok(datetime.now().timestamp(),
                                     self._feed_last_good_time.timestamp() if self._feed_last_good_time else None,
                                     self.feed_grace_min):
                        return None
                    return f"source-water EC dead >{self.feed_grace_min:.0f}min — holding (fail-closed)"
                if (lo > 0 and feed < lo) or (hi > 0 and feed > hi):
                    return f"source-water EC {feed:.1f} out of [{lo:g},{hi:g}]"
        # pH half of the source-water gate — bad-pH feed locks out nutrients / burns roots, so
        # gate it too, but only when a feed-pH sensor is configured.
        if self.feed_ph_sensor:
            ph_lo = self._num("number.crop_steering_irrigation_ph_min", 0)
            ph_hi = self._num("number.crop_steering_irrigation_ph_max", 0)
            if ph_lo > 0 or ph_hi > 0:
                ph = self._read_feed_ph()
                if ph is None:
                    if feed_grace_ok(datetime.now().timestamp(),
                                     self._feed_ph_last_good_time.timestamp() if self._feed_ph_last_good_time else None,
                                     self.feed_grace_min):
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
        ha_call("persistent_notification", "create", title=title, message=message, notification_id=f"f2_{key}")
        dom, _, svc = self.notify_service.partition("/")
        if dom and svc:
            ha_call(dom, svc, title=title, message=message)

    def _advance_shot_counters(self, zone, size_pct):
        st = self.state[zone]
        st["shots"] += 1
        st["last_shot"] = datetime.now()
        st["daily_vol"] += size_pct / 100.0 * self._substrate_l(zone)
        self._save_state()

    # ---------- hardware (sync; this process does one thing) ----------
    def _execute_shot(self, zone, duration_s, size_pct):
        self._busy = True
        valve = self.hw["valves"].get(zone)
        try:
            # OPEN sequence — FAIL CLOSED: if any service call errors, cut what's on, alert, and DO NOT count the shot
            # (otherwise daily_vol / last_shot lie after an auth/entity/service failure and a zone silently starves).
            if not ha_call("switch", "turn_on", entity_id=self.hw["pump"]):
                self._alert(f"hw_z{zone}", "Shot aborted — pump command failed",
                            f"Zone {zone}: pump turn_on returned an error. No water delivered, shot NOT counted.")
                return
            time.sleep(2)
            if not ha_call("switch", "turn_on", entity_id=self.hw["mainline"]):
                ha_call("switch", "turn_off", entity_id=self.hw["pump"])
                self._alert(f"hw_z{zone}", "Shot aborted — mainline command failed",
                            f"Zone {zone}: mainline turn_on failed. Pump cut. No water, shot NOT counted.")
                return
            time.sleep(1)
            if not ha_call("switch", "turn_on", entity_id=valve):
                ha_call("switch", "turn_off", entity_id=self.hw["mainline"])
                ha_call("switch", "turn_off", entity_id=self.hw["pump"])
                self._alert(f"hw_z{zone}", "Shot aborted — valve command failed",
                            f"Zone {zone}: valve {valve} turn_on failed. Pump + mainline cut. No water, shot NOT counted.")
                return
            time.sleep(duration_s)
            ha_call("switch", "turn_off", entity_id=valve); time.sleep(1)
            ha_call("switch", "turn_off", entity_id=self.hw["mainline"])
            ha_call("switch", "turn_off", entity_id=self.hw["pump"]); time.sleep(1)
            if self._on(valve, False):
                ha_call("switch", "turn_off", entity_id=self.hw["pump"])
                ha_call("switch", "turn_off", entity_id=self.hw["mainline"])
                self._alert(f"valve_z{zone}", "URGENT — valve stuck open",
                            f"Zone {zone} valve {valve} did not close after shot. Pump + mainline cut.")
            # only counts a shot that actually opened the full pump->mainline->valve path
            self._advance_shot_counters(zone, size_pct)
        except Exception as e:
            log("shot error", zone, e)
            for ent in (valve, self.hw["mainline"], self.hw["pump"]):
                ha_call("switch", "turn_off", entity_id=ent)
        finally:
            self._busy = False

    def _safe_off(self):
        ha_call("switch", "turn_off", entity_id=self.hw["pump"])
        ha_call("switch", "turn_off", entity_id=self.hw["mainline"])
        for v in self.hw["valves"].values():
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
    def _substrate_l(self, zone):
        """ZONE-TOTAL substrate (L) = per-plant block x plant_count. The substrate_volume entity is the
        PER-PLANT block size (e.g. 6 L); flow_lps is zone-total (plant_count x drippers x L/hr), so the
        duration + daily-volume math need zone-total substrate or shots come out plant_count-times short
        (the machine-gun: per-plant 6 L / zone flow -> ~36x too short, VWC never rises)."""
        per_plant = self._zone_num(zone, "substrate_volume", self.substrate_l)
        pc = self._zone_num(zone, "plant_count", 0)
        return per_plant * pc if pc > 0 else per_plant

    def _zone_flow_lps(self, zone):
        """Real zone delivery rate (L/s) = plants x drippers/plant x dripper L/hr / 3600.
        plant_count CANCELS against the zone-total substrate in the duration math, so default it
        to 1 here — that way the dripper flow rate + drippers/plant ALWAYS drive shot length even
        when plant_count hasn't been set. Only fall back to the option if drippers/flow are unset."""
        pc = self._zone_num(zone, "plant_count", 0) or 1
        dpp = self._zone_num(zone, "drippers_per_plant", 1)
        fr = self._num("number.crop_steering_dripper_flow_rate", 0)   # L/hr per dripper
        if dpp > 0 and fr > 0:
            return pc * dpp * fr / 3600.0
        return self.flow_lps

    def _act_zone(self, zone, p, snap, decision, block, lights_on, now):
        st = self.state[zone]
        fire, size, reason = decision
        if (snap is not None and fire and block and lights_on and p.watchdog_hours > 0
                and snap.minutes_since_shot > p.watchdog_hours * 60 and snap.vwc < p.p2_threshold):
            self._alert(f"wd_z{zone}", "URGENT — zone starving",
                        f"Zone {zone}: no water {snap.minutes_since_shot/60.0:.1f}h, "
                        f"VWC {snap.vwc:.0f}<{p.p2_threshold:.0f}, blocked by '{block}'.")
        if fire and block:
            log(f"Z{zone} {st['phase']} BLOCKED ({block}): would {reason}")
        elif fire:
            raw_dur = size / 100.0 * self._substrate_l(zone) / max(self._zone_flow_lps(zone), 0.001)
            max_dur = self._num("number.crop_steering_max_shot_duration", 900)   # hard flood cap (s); default 900
            #   a correct 6 % shot of a 6 L block at 4 L/hr is ~324 s; big P1/flush shots reach ~860 s, so the
            #   cap sits at 900 s — above any legit shot, but catches a gross substrate/flow misconfig
            dur = max(5, min(int(max_dur), int(raw_dur)))
            if raw_dur > max_dur:   # a legit F2 shot is <60s — hitting the cap means a substrate/flow misconfig
                self._alert(f"durcap_z{zone}", "Shot duration capped (flood guard)",
                            f"Zone {zone}: computed {int(raw_dur)}s > {int(max_dur)}s cap — clamped. Check substrate volume / flow config.")
            log(f"Z{zone} {st['phase']} FIRE {size}% ~{dur}s — {reason}")
            self._execute_shot(zone, dur, size)
        else:
            if "BLOCK" in reason:
                self._alert(f"block_z{zone}", "Zone blocked — needs attention", f"Zone {zone} ({st['phase']}): {reason}")
            log(f"Z{zone} {st['phase']} hold — {reason}")

    def loop_once(self, now):
        if self._busy:
            return
        self._refresh_lights()
        lights_on = self._lights_on(now)
        was_off = not (self._was_lights_on if self._was_lights_on is not None else lights_on)
        lights_just_on = lights_on and was_off
        snaps, decisions, healthy, blind, params = {}, {}, [], [], {}
        for zone in self.zones:
            st = self.state[zone]
            snap, p = self._snapshot(zone, now, lights_on, lights_just_on)
            params[zone] = p
            if snap is None:
                blind.append((zone, p)); continue
            snaps[zone] = snap
            healthy.append((zone, p.p1_target))
            new_phase, new_thr, fire, size, reason = decide(snap, p)
            if new_phase != st["phase"]:
                if new_phase == "P0":
                    st["daily_vol"], st["shots"], st["peak"] = 0.0, 0, snap.vwc
                    st["ec_offset"], st["last_ec_steer"] = 0.0, None
                    st["ec_integral"], st["ec_prev_err"] = 0.0, 0.0  # no cross-photoperiod PID windup
                    st["last_daily_reset"] = self._grow_day_start(now)
                if new_phase == "P1":
                    st["shots"] = 0
                st["phase"] = new_phase
                st["last_phase_change"] = now
                self._save_state()
            if p.stacking_on and st["phase"] == "P2" and p.ec_target_p2 > 0:
                base = self._zone_num(zone, "p2_vwc_threshold", 45)
                les = st.get("last_ec_steer")
                if les is None or (now - les).total_seconds() >= 1800:
                    if self._on("input_boolean.crop_steering_ec_pid_enabled", False):
                        gains = (self._num("input_number.crop_steering_ec_pid_kp", 0.4),
                                 self._num("input_number.crop_steering_ec_pid_ki", 0.15),
                                 self._num("input_number.crop_steering_ec_pid_kd", 0.0))
                        off, integ, perr = ec_pid(snap.ec_smooth, p.ec_target_p2, base,
                                                  float(st.get("ec_integral", 0.0)), float(st.get("ec_prev_err", 0.0)), gains)
                        st["ec_offset"], st["ec_integral"], st["ec_prev_err"] = off, integ, perr
                    else:
                        st["ec_offset"] = self._step_ec_offset(float(st.get("ec_offset", 0.0)), snap.ec_smooth, p.ec_target_p2, base)
                    st["last_ec_steer"] = now
                    self._save_state()
            decisions[zone] = (fire, size, reason)
        for zone, p in blind:
            st = self.state[zone]
            if healthy:
                sib = pick_sibling(p.p1_target, healthy)
                s_fire, s_size, _ = decisions[sib]
                decisions[zone] = (s_fire, s_size, f"COPY Z{sib} (VWC probe dead)")
                if zone not in self._blind_zones:
                    self._alert(f"blind_z{zone}", "Zone moisture probe dead — copying sibling", f"Zone {zone} copying Zone {sib}.")
            else:
                mss = self._minutes_since_shot(st, now)
                decisions[zone] = (mss >= self.blind_fallback_min, p.p2_shot_size, "FALLBACK schedule (no live probe)")
                if zone not in self._blind_zones:
                    self._alert(f"blind_z{zone}", "Zone probe dead — no live sibling", f"Zone {zone} safe fallback schedule.")
            self._blind_zones.add(zone)
        self._blind_zones = {z for z in self._blind_zones if z not in snaps}
        pub = {}
        for zone in self.zones:
            if zone not in decisions:
                continue
            fire, size, reason = decisions[zone]
            block = self._blocked(zone) if fire else None
            self._act_zone(zone, params[zone], snaps.get(zone), decisions[zone], block, lights_on, now)
            snap = snaps.get(zone)
            pub[zone] = {"phase": self.state[zone]["phase"], "vwc": snap.vwc if snap else None,
                         "ec": snap.ec if snap else None, "fire": fire, "block": block,
                         "reason": reason, "blind": snap is None, "p": params[zone]}
        for z, why in cross_zone_outliers(snaps):
            self._alert(f"xzone_{z}", "Zone under-drinking vs siblings", why)
        self._publish_status(pub, now)
        self._maybe_notify(pub, now)
        self._was_lights_on = lights_on

    def _publish_status(self, pub, now):
        if not pub:
            return
        try:
            labels = []
            for zone in sorted(pub):
                d = pub[zone]; p = d["p"]
                saf = zone_safety_status(d["vwc"], d["ec"], p.field_capacity, p.max_ec)
                labels.append(saf)
                ha_set(f"sensor.crop_steering_zone_{zone}_phase", d["phase"], {"reason": d["reason"], "engine": "f2-control"})
                ha_set(f"sensor.crop_steering_zone_{zone}_safety_status", saf,
                       {"vwc": d["vwc"], "ec": d["ec"], "field_capacity": p.field_capacity, "max_ec_limit": p.max_ec})
                ha_set(f"sensor.crop_steering_zone_{zone}_status",
                       zone_status_label(d["phase"], d["fire"], d["block"], d["blind"], d["reason"]), {"reason": d["reason"]})
                ls = self.state[zone].get("last_shot")
                if ls is not None:
                    ha_set(f"sensor.crop_steering_zone_{zone}_last_irrigation_app", ls.isoformat(), {"device_class": "timestamp"})
            sys_stat, unsafe, warn, safe = system_safety_status(labels)
            ha_set("sensor.crop_steering_system_safety_status", sys_stat,
                   {"unsafe_zones": unsafe, "warning_zones": warn, "safe_zones": safe})
            ha_set("sensor.crop_steering_app_current_phase", ", ".join(f"Z{z}:{pub[z]['phase']}" for z in sorted(pub)),
                   {"friendly_name": "Zone Phases"})
            room_held = any(d["block"] and "fail-closed" in str(d["block"]) for d in pub.values())
            ha_set("sensor.crop_steering_app_status", "error" if room_held else ("irrigating" if self._busy else "safe_idle"),
                   {"engine": "f2-control", "updated": now.isoformat()})
            ha_set("sensor.crop_steering_ai_heartbeat", "healthy", {"engine": "f2-control", "last_beat": now.isoformat()})
            fired = [f"Z{z} {d['phase']} {d['reason']}" for z, d in sorted(pub.items()) if d["fire"] and not d["block"]]
            held = [f"Z{z} {d['phase']} {d['block'] or d['reason']}" for z, d in sorted(pub.items()) if d["block"] or "BLOCK" in d["reason"]]
            ha_set("sensor.crop_steering_current_decision",
                   (fired[0] if fired else (held[0] if held else "Holding — all zones in band"))[:255],
                   {"fired": fired, "blocked": held})
            for ln in fired + held:
                self._activity.insert(0, f"{now.strftime('%H:%M')} {ln}"[:120])
            del self._activity[60:]
            ha_set("sensor.crop_steering_activity_log", (self._activity[0] if self._activity else "idle")[:255],
                   {"feed": "\n".join(self._activity[:50]), "event_count": len(self._activity)})
        except Exception as e:
            log("publish failed", e)

    def _maybe_notify(self, pub, now):
        if self._last_notify and (now - self._last_notify).total_seconds() < self.notify_min * 60:
            return
        self._last_notify = now
        lines = []
        for z in sorted(pub):
            d = pub[z]; st = self.state[z]
            mss = self._minutes_since_shot(st, now)
            ago = "never" if mss > 1e8 else f"{mss/60:.1f}h"
            vwc = f"{d['vwc']:.0f}%" if d["vwc"] is not None else "—"
            ec = f"{d['ec']:.1f}" if d["ec"] is not None else "—"
            fc = f"{st['peak']:.0f}" if st.get("peak") else "—"
            lines.append(f"Z{z} {d['phase']}: VWC {vwc} EC {ec} (FC~{fc}) | {st['daily_vol']:.1f}L day | last {ago}")
        feed = self._read_feed_ec()
        on = self._on(self.enable_flag, False)
        msg = (f"{now.strftime('%H:%M')} | {'LIVE' if on else 'HELD (kill-switch off)'} | feed EC {feed if feed is not None else '—'}\n"
               + "\n".join(lines))
        dom, _, svc = self.notify_service.partition("/")
        if dom and svc:
            ha_call(dom, svc, title="F2 vitals", message=msg)
        ha_call("persistent_notification", "create", title="F2 control vitals", message=msg, notification_id="f2_vitals")
        ha_set("sensor.f2_control_vitals", now.strftime("%H:%M"), {"vitals": msg, "live": on})

    def run(self):
        log("starting | kill-switch", self.enable_flag, "| notify", self.notify_service, f"| loop {self.loop_seconds:.0f}s")
        log("token present:", bool(TOKEN), "| base:", BASE)
        while True:
            try:
                self.loop_once(datetime.now())
            except Exception as e:
                log("loop error", e)
            time.sleep(self.loop_seconds)


if __name__ == "__main__":
    Controller().run()
