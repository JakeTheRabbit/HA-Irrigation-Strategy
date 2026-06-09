"""
VRWE Shadow — Virtual Root-Zone Water Estimator, SHADOW / READ-ONLY mode.

A standalone AppDaemon app that runs BESIDE the live crop-steering engine.
It NEVER actuates hardware. It only reads entities and publishes its own
`sensor.vrwe_zone{N}_*` virtual sensors plus a `sensor.vrwe_status` summary,
so you can watch what it *would* conclude before granting it any authority.

Scope (deliberately NOT duplicating the live engine, which already does
delta-VWC collapse / peak-plateau / pore-EC field-capacity detection):
  - Shared-pump RUNOFF ATTRIBUTION with condensate subtraction (M34/M39-lite)
  - CONDENSATE baseline learned from quiet windows (M35 input via AC/dehum)
  - 6-D TRUST vector + sensor-lying cross-checks (M6 phantom-dryback, M15 cohort,
    M30 daily closure, actuation-proof via feed-pump watts)
  - DUL (container-capacity) anchor as an INDEPENDENT cross-check (M33), corroborated
  - Priority STATE MACHINE + a "would-have" recommendation string

Epistemics (per white paper v2): per-zone runoff is INFERRED, not observed. When the
shared pump cannot be attributed to one zone (overlapping shots, or condensate-dominated),
the output is RUNOFF_UNRESOLVABLE. Specific yield S->0 is a CANDIDATE, never proof.
The app shrinks its own confidence under doubt; it can never escalate irrigation —
because it cannot irrigate at all.
"""

import appdaemon.plugins.hass.hassapi as hass
import json
import os
import time

SHADOW_ONLY = True  # HARD INVARIANT: this app issues NO actuation service calls. Read + publish only.


def _f(x, d=None):
    """Safe float; returns d for None/'unknown'/'unavailable'/garbage."""
    try:
        v = float(x)
        if v != v:  # NaN
            return d
        return v
    except (TypeError, ValueError):
        return d


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _ewma(old, new, alpha):
    return new if old is None else (1 - alpha) * old + alpha * new


class VRWEShadow(hass.Hass):

    # ---------------------------------------------------------------- lifecycle
    def initialize(self):
        a = self.args
        self.tick_s = int(a.get("tick_seconds", 60))
        self.alpha = float(a.get("ewma_alpha", 0.2))
        self.settle_s = int(a.get("shot_settle_seconds", 150))
        self.on_w = float(a.get("pump_on_watts", 15.0))
        self.rol_min = float(a.get("rol_min_s", 10.0))
        self.rol_max = float(a.get("rol_max_s", 300.0))
        self.quiet_gap_s = float(a.get("quiet_gap_s", 900.0))   # no shot for this long => pump event is condensate
        self.s_knee = float(a.get("s_collapse_ratio", 0.25))    # specific-yield ratio below which = saturation candidate
        self.cold_events = int(a.get("cold_start_events", 5))

        self.zones = a.get("zones", {}) or {}
        self.env = a.get("env", {}) or {}
        self.hvac = a.get("hvac", {}) or {}
        self.feed_pump = a.get("feed_pump_power", "") or ""
        self.runoff_pump = a.get("runoff_pump_power", "") or ""   # <<< placeholder until you give me the watts entity

        self.state_path = a.get(
            "state_file",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "vrwe_state.json"),
        )

        # persistent across restarts
        self.persist = self._load_state()
        self.persist.setdefault("condensate", {"rate_w_avg": None, "cycle_interval_s": None, "samples": 0})
        self.persist.setdefault("zones", {})

        # volatile working state
        self.pump = {"feed": {"on": False, "t_on": None},
                     "runoff": {"on": False, "t_on": None, "last_w": 0.0}}
        self.shot_log = []           # recent finished shots: {zone, t_start, t_end, ml, vwc_before}
        self.active_shot = {}        # zone -> {t_start, vwc_before, feed_seen}
        self.last_runoff_event_t = None
        self.day = {"in_ml": 0.0, "demand_ml": 0.0, "runoff_runtime_s": 0.0, "t0": time.time()}

        for zid, z in self.zones.items():
            self.persist["zones"].setdefault(str(zid), {
                "dul_vwc": None, "dul_ml": None, "events": 0,
                "trust": {"T_abs": 0.5, "T_trend": 0.6, "T_EC": 0.5,
                          "T_DUL": 0.3, "T_runoff": 0.2, "T_ctrl": 0.4},
            })
            if z.get("valve"):
                self.listen_state(self.on_valve, z["valve"], zone=str(zid))

        if self.feed_pump:
            self.listen_state(self.on_pump, self.feed_pump, which="feed")
        if self.runoff_pump:
            self.listen_state(self.on_pump, self.runoff_pump, which="runoff")

        self.run_every(self.tick, "now+15", self.tick_s)
        self.run_daily(self.reset_day, "00:00:01")  # rough grow-day boundary; closure is informational in shadow

        self.log("VRWE SHADOW started (READ-ONLY, no actuation). zones=%s feed_pump=%s runoff_pump=%s"
                 % (list(self.zones.keys()), self.feed_pump or "<unset>", self.runoff_pump or "<UNSET — placeholder>"))
        self.tick({})  # publish an initial snapshot

    def terminate(self):
        self._save_state()

    # ------------------------------------------------------------ valve events
    def on_valve(self, entity, attribute, old, new, **kwargs):
        zid = kwargs.get("zone")
        if new == "on" and old != "on":
            vwc = _f(self.get_state(self.zones[zid]["vwc"]))
            self.active_shot[zid] = {"t_start": time.time(), "vwc_before": vwc, "feed_seen": False}
        elif new != "on" and old == "on" and zid in self.active_shot:
            sh = self.active_shot.pop(zid)
            t_end = time.time()
            dur = max(0.0, t_end - sh["t_start"])
            z = self.zones[zid]
            emitters = _f(z.get("emitters"), 0.0)
            lph = _f(z.get("emitter_lph"), 0.0)
            ml = emitters * lph * (dur / 3600.0) * 1000.0   # commanded estimate (C4)
            shot = {"zone": zid, "t_start": sh["t_start"], "t_end": t_end,
                    "ml": ml, "vwc_before": sh["vwc_before"], "feed_seen": sh["feed_seen"]}
            self.shot_log.append(shot)
            self.shot_log = self.shot_log[-50:]
            self.day["in_ml"] += ml
            # schedule a delayed read of the response (specific yield / actuation proof)
            self.run_in(self.read_shot_result, self.settle_s, zone=zid, shot=shot)

    def read_shot_result(self, **kwargs):
        zid = kwargs["zone"]
        shot = kwargs["shot"]
        z = self.zones[zid]
        zp = self.persist["zones"][str(zid)]
        vwc_after = _f(self.get_state(z["vwc"]))
        vwc_before = shot["vwc_before"]
        notes = []

        # actuation proof (T_ctrl): did the feed pump run, and did VWC move?
        if shot["ml"] > 0:
            moved = (vwc_after is not None and vwc_before is not None and (vwc_after - vwc_before) > 0.2)
            if shot["feed_seen"] and moved:
                zp["trust"]["T_ctrl"] = self._raise(zp["trust"]["T_ctrl"], 0.9)
            elif shot["feed_seen"] and not moved:
                # water pushed but probe didn't rise: bypass/channel/dry-pocket OR sensor under-reading
                zp["trust"]["T_ctrl"] = self._lower(zp["trust"]["T_ctrl"], 0.3)
                notes.append("shot delivered, no VWC rise -> bypass/dry-pocket/under-read")
            elif not shot["feed_seen"]:
                zp["trust"]["T_ctrl"] = self._lower(zp["trust"]["T_ctrl"], 0.25)
                notes.append("valve open but no feed-pump watts -> actuation unproven")

        # specific yield S (candidate only, C7)
        if vwc_after is not None and vwc_before is not None and shot["ml"] > 0:
            sub_ml = _f(z.get("substrate_ml"), 0.0)
            dvwc = (vwc_after - vwc_before) / 100.0          # % -> fraction
            stored_equiv_ml = dvwc * sub_ml
            s_ratio = stored_equiv_ml / shot["ml"] if shot["ml"] > 0 else None
            zp["S_last"] = round(s_ratio, 3) if s_ratio is not None else None
            # DUL candidate: S collapsed AND runoff corroboration within window AND not suspect
            corroborated = self._recent_runoff_for_zone(zid)
            if s_ratio is not None and s_ratio < self.s_knee and corroborated and self._zone_ok(zp):
                cand = vwc_after
                zp["dul_vwc"] = _ewma(zp["dul_vwc"], cand, min(self.alpha, 0.15))  # bounded step
                zp["events"] = zp.get("events", 0) + 1
                zp["trust"]["T_DUL"] = self._raise(zp["trust"]["T_DUL"], 0.85)
                notes.append("DUL candidate %0.1f%% (S=%.2f + runoff corroborated)" % (cand, s_ratio))
            elif s_ratio is not None and s_ratio < self.s_knee and not corroborated:
                notes.append("S collapsed (%.2f) but NO runoff corroboration -> candidate only, ignored" % s_ratio)

        if notes:
            self.log("[zone %s] " % zid + " | ".join(notes))
        self._save_state()

    # ------------------------------------------------------------- pump events
    def on_pump(self, entity, attribute, old, new, **kwargs):
        which = kwargs.get("which")
        w = _f(new, 0.0) or 0.0
        st = self.pump[which]
        rising = (w >= self.on_w) and not st["on"]
        falling = (w < self.on_w) and st["on"]
        if rising:
            st["on"] = True
            st["t_on"] = time.time()
            if which == "feed":
                # mark any active shots as feed-proven
                for zid in self.active_shot:
                    self.active_shot[zid]["feed_seen"] = True
            else:
                self._on_runoff_start(st["t_on"])
        elif falling:
            st["on"] = False
            if which == "runoff" and st["t_on"] is not None:
                runtime = max(0.0, time.time() - st["t_on"])
                self.day["runoff_runtime_s"] += runtime
            st["t_on"] = None

    def _on_runoff_start(self, t):
        """Classify a runoff-pump start: zone runoff vs condensate vs unresolvable."""
        self.last_runoff_event_t = t
        recent = [s for s in self.shot_log if (t - s["t_end"]) >= self.rol_min and (t - s["t_end"]) <= self.rol_max]
        # also catch shots still settling (ended just before window)
        recent += [s for s in self.shot_log if 0 <= (t - s["t_end"]) < self.rol_min]
        zones_in_window = sorted({s["zone"] for s in recent})

        last_shot_age = min([(t - s["t_end"]) for s in self.shot_log], default=1e9)
        if last_shot_age >= self.quiet_gap_s:
            # CONDENSATE: no irrigation for a long time -> this pump event is condensate-only
            self._update_condensate(t)
            self._note_runoff("condensate", None, t)
        elif len(zones_in_window) == 1:
            zid = zones_in_window[0]
            rol = t - max(s["t_end"] for s in recent if s["zone"] == zid)
            zp = self.persist["zones"][str(zid)]
            zp["rol_last_s"] = round(rol, 1)
            zp["trust"]["T_runoff"] = self._raise(zp["trust"]["T_runoff"], 0.8)
            zp["last_runoff_t"] = t
            self._note_runoff("zone%s" % zid, zid, t)
        elif len(zones_in_window) >= 2:
            # overlapping zones on one shared pump -> cannot attribute
            for zid in zones_in_window:
                self.persist["zones"][str(zid)]["trust"]["T_runoff"] = self._lower(
                    self.persist["zones"][str(zid)]["trust"]["T_runoff"], 0.2)
            self._note_runoff("UNRESOLVABLE(zones=%s)" % zones_in_window, None, t)
        else:
            self._note_runoff("UNRESOLVABLE(no-clean-window)", None, t)

    def _update_condensate(self, t):
        c = self.persist["condensate"]
        if c.get("last_t") is not None:
            interval = t - c["last_t"]
            c["cycle_interval_s"] = _ewma(c.get("cycle_interval_s"), interval, 0.2)
        c["last_t"] = t
        c["samples"] = c.get("samples", 0) + 1

    def _recent_runoff_for_zone(self, zid):
        zp = self.persist["zones"][str(zid)]
        lt = zp.get("last_runoff_t")
        return lt is not None and (time.time() - lt) < (self.rol_max + self.settle_s + 60)

    def _note_runoff(self, label, zid, t):
        self.persist.setdefault("runoff_events", [])
        self.persist["runoff_events"].append({"t": round(t, 1), "label": label})
        self.persist["runoff_events"] = self.persist["runoff_events"][-50:]
        self.log("[runoff] %s" % label)

    # ----------------------------------------------------------------- the tick
    def tick(self, kwargs):
        vwcs = {}
        for zid, z in self.zones.items():
            vwcs[zid] = _f(self.get_state(z.get("vwc")))
        median_vwc = self._median([v for v in vwcs.values() if v is not None])

        vpd = _f(self.get_state(self.env.get("vpd")))
        ppfd = _f(self.get_state(self.env.get("ppfd")))
        demand_unit = (vpd or 0.0) * (ppfd or 0.0)  # canopy demand index input (C6); k learned later
        self.day["demand_ml"] += demand_unit * (self.tick_s / 3600.0)  # raw index accrual (unitless until k_demand calibrated)

        for zid, z in self.zones.items():
            zp = self.persist["zones"][str(zid)]
            T = zp["trust"]
            vwc = vwcs[zid]
            ec = _f(self.get_state(z.get("bulk_ec"))) if z.get("bulk_ec") else None
            floor = _f(self.get_state(z.get("emergency_floor")))
            dul = zp.get("dul_vwc")
            notes = []

            # ---- sensor validity / trust ----
            if vwc is None:
                T["T_abs"] = self._lower(T["T_abs"], 0.1)
                T["T_trend"] = self._lower(T["T_trend"], 0.2)
                state = "SENSOR_FAULT"
            else:
                # cohort outlier (M15)
                if median_vwc is not None and abs(vwc - median_vwc) > 15:
                    T["T_abs"] = self._lower(T["T_abs"], 0.35)
                    notes.append("cohort outlier vs median %.0f%%" % median_vwc)
                else:
                    T["T_abs"] = self._raise(T["T_abs"], 0.7)

                # phantom dryback (M6): VWC falling with ~zero canopy demand and no runoff
                prev = zp.get("_prev_vwc")
                if prev is not None and (prev - vwc) > 1.0 and demand_unit < 1.0 and not self._recent_runoff_for_zone(zid):
                    T["T_abs"] = self._lower(T["T_abs"], 0.3)
                    notes.append("phantom dryback: VWC down %.1f w/ ~0 demand & no runoff" % (prev - vwc))
                zp["_prev_vwc"] = vwc

                state = self._state_machine(zid, zp, vwc, dul, floor, T)

            # runoff trust if no runoff-pump entity yet
            if not self.runoff_pump:
                T["T_runoff"] = min(T["T_runoff"], 0.1)

            rec, runoff_status = self._recommend(zid, zp, vwc, dul, floor, T, state)
            self._publish_zone(zid, zp, vwc, ec, dul, floor, state, rec, runoff_status, notes)

        self._publish_status()
        self._save_state()

    # ----------------------------------------------------------- state machine
    def _state_machine(self, zid, zp, vwc, dul, floor, T):
        """Priority sweep: safety > fallback/cold > sensor > steering. Shadow output only."""
        # P0 safety
        if floor is not None and vwc is not None and vwc <= floor:
            return "DRYBACK_FAST"  # at/below emergency floor (the live engine handles rescue; we only flag)
        if zp.get("rol_last_s") is not None and self.day["runoff_runtime_s"] > float(self.args.get("excess_runoff_runtime_s", 600)):
            return "EXCESS_RUNOFF"
        # P1 trust collapse
        if T["T_ctrl"] < 0.3:
            return "FALLBACK_IRRIG"
        if zp.get("events", 0) < self.cold_events and dul is None:
            return "COLD_START"
        # P3 sensor degraded
        if T["T_abs"] < 0.3 and T["T_trend"] >= 0.4:
            return "SENSOR_TREND_ONLY"
        if T["T_abs"] < 0.3:
            return "SENSOR_SUSPECT"
        # runoff / capacity bands
        if self._recent_runoff_for_zone(zid):
            return "LIKELY_RUNOFF"
        if dul is not None and vwc is not None and vwc >= (dul - 3):
            return "APPROACH_DUL"
        return "NORMAL_STEER"

    def _recommend(self, zid, zp, vwc, dul, floor, T, state):
        runoff_status = "UNRESOLVABLE (no runoff-pump entity)" if not self.runoff_pump else (
            "recent runoff attributed" if self._recent_runoff_for_zone(zid) else "no recent runoff")
        if state in ("SENSOR_FAULT", "FALLBACK_IRRIG"):
            return "HOLD — conservative fallback (low confidence)", runoff_status
        if state == "EXCESS_RUNOFF":
            return "HOLD — excess runoff, would cap/stop fill", runoff_status
        if state == "LIKELY_RUNOFF":
            return "STOP fill — runoff onset (would log DUL)", runoff_status
        if state == "APPROACH_DUL":
            return "CAP to safe headroom — near container capacity", runoff_status
        if state in ("SENSOR_SUSPECT", "SENSOR_TREND_ONLY"):
            return "ASK HUMAN — confirm probe/runoff before trusting absolute VWC", runoff_status
        if state == "COLD_START":
            return "OBSERVE ONLY — learning DUL/condensate, no opinion yet", runoff_status
        return "OK to steer within recipe (confidence ok)", runoff_status

    # --------------------------------------------------------------- publishing
    def _publish_zone(self, zid, zp, vwc, ec, dul, floor, state, rec, runoff_status, notes):
        T = zp["trust"]
        headroom = None
        if dul is not None and vwc is not None:
            sub_ml = _f(self.zones[zid].get("substrate_ml"), 0.0)
            headroom = round(max(0.0, (dul - vwc) / 100.0 * sub_ml), 0)  # LOCAL estimate only (C9)
        self.set_state(
            "sensor.vrwe_zone%s_state" % zid,
            state=state,
            attributes={
                "friendly_name": "VRWE Zone %s" % zid,
                "icon": "mdi:water-percent-alert",
                "recommendation": rec,
                "runoff_status": runoff_status,
                "vwc_pct": vwc,
                "bulk_ec": ec,
                "dul_vwc_anchor": None if dul is None else round(dul, 1),
                "dul_events": zp.get("events", 0),
                "S_last_ratio": zp.get("S_last"),
                "rol_last_s": zp.get("rol_last_s"),
                "headroom_ml_local_est": headroom,
                "emergency_floor": floor,
                "trust_abs": round(T["T_abs"], 2),
                "trust_trend": round(T["T_trend"], 2),
                "trust_EC": round(T["T_EC"], 2),
                "trust_DUL": round(T["T_DUL"], 2),
                "trust_runoff": round(T["T_runoff"], 2),
                "trust_ctrl": round(T["T_ctrl"], 2),
                "notes": "; ".join(notes) if notes else "",
                "shadow_only": True,
            },
        )

    def _publish_status(self):
        c = self.persist["condensate"]
        self.set_state(
            "sensor.vrwe_status",
            state="shadow",
            attributes={
                "friendly_name": "VRWE Status (shadow)",
                "icon": "mdi:brain",
                "mode": "READ-ONLY — no actuation",
                "runoff_pump_entity": self.runoff_pump or "UNSET (placeholder)",
                "condensate_samples": c.get("samples", 0),
                "condensate_cycle_interval_s": None if c.get("cycle_interval_s") is None else round(c["cycle_interval_s"], 0),
                "day_irrigation_ml": round(self.day["in_ml"], 0),
                "day_demand_index_ml": round(self.day["demand_ml"], 0),
                "day_runoff_runtime_s": round(self.day["runoff_runtime_s"], 0),
                "recent_runoff_events": self.persist.get("runoff_events", [])[-8:],
                "zones": list(self.zones.keys()),
            },
        )

    # ------------------------------------------------------------------- closure
    def reset_day(self, kwargs):
        resid = self.day["in_ml"] - self.day["demand_ml"]  # runoff/storage not volume-resolved in shadow
        self.log("[closure] day reset. in=%.0f mL demand_idx=%.0f runoff_runtime=%.0fs (residual=%.0f, informational)"
                 % (self.day["in_ml"], self.day["demand_ml"], self.day["runoff_runtime_s"], resid))
        self.day = {"in_ml": 0.0, "demand_ml": 0.0, "runoff_runtime_s": 0.0, "t0": time.time()}

    # ------------------------------------------------------------- trust helpers
    def _raise(self, t, target):
        return _clamp(t + self.alpha * (target - t), 0.0, 1.0)

    def _lower(self, t, target):
        # hard haircut: trust is cheap to lose
        return _clamp(min(t, target) if target < t else t + self.alpha * (target - t), 0.0, 1.0)

    def _zone_ok(self, zp):
        T = zp["trust"]
        return T["T_abs"] >= 0.4 and T["T_ctrl"] >= 0.4

    @staticmethod
    def _median(xs):
        if not xs:
            return None
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0

    # ------------------------------------------------------------- persistence
    def _load_state(self):
        try:
            with open(self.state_path, "r") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        try:
            with open(self.state_path, "w") as fh:
                json.dump(self.persist, fh, indent=2)
        except OSError as e:
            self.log("WARN could not save state: %s" % e, level="WARNING")
