"""Is the room running the grow plan its grower chose? (docs/GROW_PLANS.md, "How the controller checks the plan
is running")

PURE: no Home Assistant, no brain, no clock of its own. Each pass the controller builds a View from what it reads
anyway (the plan sensor, each zone's phase, the lights) and from the plan itself (crop_steering.strategy_get and
strategy_preview, fetched only when the plan changes, after lights-on and every few hours), and `detect()` compares
what code expected since lights-on with what happened. A drift is reported, never corrected here: a plan is armed,
edited or disarmed only by a person, and a number changed by hand while it runs is advised about, never written.

Every drift's words are code's. The brain (jev/plan_task.py) may pick which of a drift's suggestions is shown, and
only under the Claude Haiku brain; with no brain the first one stands.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

SETTLE_MIN = 10.0  # minutes after lights-on, lights-off or a start before anything is judged
STALE_H = 6.0  # a plan fetched longer ago than this is not judged on
LOG_MAX = 12  # observed phase changes kept per zone, this grow-day only
NEUTRAL = (40.0, 60.0)  # % generative: a plan bias in here agrees with either steering select
TRIPWIRES = ("missed_day_start", "missed_lights_off", "p0_overrun")

LABELS = {
    "dryback_target": "the dryback target", "p1_target_vwc": "the P1 target", "p2_vwc_threshold":
    "the re-water threshold", "p2_shot_size": "the maintenance shot size", "p1_initial_shot_size":
    "the first ramp shot", "p3_emergency_vwc_threshold": "the rescue floor", "p3_emergency_shot_size":
    "the rescue shot size", "ec_target_p0": "the P0 EC target", "ec_target_p1": "the P1 EC target",
    "ec_target_p2": "the P2 EC target", "p1_shot_size_increment": "the ramp's shot increment",
    "p1_maximum_shots": "the ramp's maximum shots", "p1_time_between_shots": "the time between ramp shots",
    "p0_maximum_wait_time": "the P0 maximum wait", "max_daily_volume": "the daily water limit",
    "field_capacity": "field capacity", "maximum_ec": "the maximum EC", "watchdog_hours": "the watchdog",
}
UNITS = {"dryback_target": " % of the peak", "p2_shot_size": " %", "p1_initial_shot_size": " %",
         "p3_emergency_shot_size": " %", "p1_shot_size_increment": " %", "p1_target_vwc": " %",
         "p2_vwc_threshold": " %", "p3_emergency_vwc_threshold": " %", "field_capacity": " %",
         "max_daily_volume": " L", "p1_time_between_shots": " min", "p0_maximum_wait_time": " min",
         "watchdog_hours": " h"}

TITLES = {
    "transition_missed": "today's plan day is not in force",
    "armed_not_started": "the armed plan has not started",
    "saved_not_armed": "a saved grow plan is not armed",
    "plan_ending": "the grow plan ends soon",
    "shadowed_edit": "a change to a setting the plan controls has no effect",
    "disarm_return": "the room goes back to its own settings at lights-on",
    "steering_disagrees": "the steering select disagrees with the plan",
    "day_boundary": "the controller's day may not match the plan's",
    "lights_entity": "the room's light disagrees with its lights hours",
    "missed_day_start": "a zone did not start its day at lights-on",
    "missed_lights_off": "a zone did not stop for the night at lights-off",
    "p0_overrun": "a zone stayed in its morning dryback past its maximum wait",
    "p1_long": "a zone has been ramping a long time",
}
# The `cause` answers each drift the brain is asked about accepts, and which of its suggestions each one shows (the
# first suggestion is the one shown with no firm answer). A drift class not here is never asked about.
PICK = {
    "transition_missed": {"reading_holds_plan": 0, "plan_out_of_date": 1, "no_effect_today": 2},
    "armed_not_started": {"reading_holds_plan": 0, "plan_out_of_date": 1, "no_effect_today": 2},
    "saved_not_armed": {"plan_out_of_date": 0, "deliberate_change": 1, "no_effect_today": 1},
    "shadowed_edit": {"deliberate_change": 0, "plan_out_of_date": 1, "no_effect_today": 2},
    "steering_disagrees": {"settings_disagree": 0, "deliberate_change": 1, "no_effect_today": 0},
    "p1_long": {"reading_holds_plan": 0, "no_effect_today": 0},
}


def fresh():
    return {"v": 1, "draft_seen": None, "baseline": None, "alerted": {}, "phase_log": {}, "bridge": None,
            "bridge_day": None, "cooldown_until": None, "bridge_outcome": None}


def load(raw):
    """The room's saved `_adherence`, field by field: anything missing or of the wrong type starts fresh."""
    out = fresh()
    if not isinstance(raw, dict):
        return out
    for key in ("draft_seen", "baseline", "bridge"):
        if isinstance(raw.get(key), dict):
            out[key] = dict(raw[key])
    if isinstance(raw.get("alerted"), dict):
        out["alerted"] = {k: v for k, v in raw["alerted"].items() if isinstance(k, str) and isinstance(v, str)}
    if isinstance(raw.get("phase_log"), dict):
        out["phase_log"] = {str(z): [e for e in v if isinstance(e, dict)][-LOG_MAX:]
                            for z, v in raw["phase_log"].items() if isinstance(v, list)}
    if isinstance(out["bridge"], dict) and not isinstance(out["bridge"].get("zones"), dict):
        out["bridge"] = None
    for key in ("bridge_day", "cooldown_until", "bridge_outcome"):
        if isinstance(raw.get(key), str):
            out[key] = raw[key]
    if isinstance(out["baseline"], dict) and not isinstance(out["baseline"].get("values"), dict):
        out["baseline"] = None
    for key in raw:  # a field a later release added is kept, not dropped
        if key not in out:
            out[key] = raw[key]
    return out


def dump(adh, today):
    """What `_save_state` writes, or None when there is nothing worth keeping. Alerts older than two days go."""
    keep = (today - timedelta(days=2)).isoformat()
    adh["alerted"] = {k: v for k, v in adh.get("alerted", {}).items() if v >= keep}
    return None if adh == fresh() else adh


@dataclass
class View:
    """One pass of the room, as code sees it. Times are local and naive, like the controller's."""

    now: datetime
    expected_day: date  # the date whose lights-on began this photoperiod (controller._grow_day_start)
    uptime_min: float
    lights_on: bool
    on_hour: float
    off_hour: float
    lights_source: str = "integration"
    status: str = "none"  # the plan sensor's state: none, draft, armed, active, disarming, error
    attrs: dict = field(default_factory=dict)  # its attributes
    plan: dict | None = None  # strategy_get's answer, or None when it could not be had
    plan_age_h: float | None = None
    preview: dict = field(default_factory=dict)  # {"today"|"yesterday": {zone: preview row}}
    natives: dict | None = None  # {entity id: value} of the numbers the plan controls
    steering: dict = field(default_factory=dict)  # {zone: "vegetative"|"generative"}
    zones: dict = field(default_factory=dict)  # {zone: phase state, params and whether it is blind}
    titles: dict = field(default_factory=dict)  # {zone: its name}
    light_state: str | None = None  # the mapped light entity: "on", "off" or None
    light_since: datetime | None = None  # since when it has disagreed with the hours
    lights_bad_since: datetime | None = None  # since when the hours have not come from the integration
    slug: str = "default"

    @property
    def lights_on_at(self):
        """This photoperiod's lights-on, or None when the hours are the same (no lights-on edge)."""
        if self.on_hour == self.off_hour:
            return None
        return datetime.combine(self.expected_day, time()) + timedelta(hours=self.on_hour)

    @property
    def lights_off_at(self):
        on = self.lights_on_at
        return None if on is None else on + timedelta(hours=(self.off_hour - self.on_hour) % 24)

    def in_force(self):
        """{zone: the plan sensor's row} for the rows it publishes."""
        rows = self.attrs.get("zones") if isinstance(self.attrs.get("zones"), list) else []
        return {r["zone_id"]: r for r in rows if isinstance(r, dict) and type(r.get("zone_id")) is int}

    def in_force_day(self, zone=None):
        """The date whose targets are in force (a zone's own, when it is held on an earlier day)."""
        row = self.in_force().get(zone) if zone is not None else None
        day = (row or {}).get("applied_day") or self.attrs.get("grow_day")
        try:
            return date.fromisoformat(day)
        except (TypeError, ValueError):
            return None

    def fresh_plan(self):
        return self.plan is not None and self.plan_age_h is not None and self.plan_age_h <= STALE_H


@dataclass
class Drift:
    cls: str
    zone: int | None
    sev: int
    line: str  # the panel's line
    facts: str  # what the brain is shown under plan_drift
    suggestions: tuple = ()
    alert: bool = True  # raises CS-713
    key: str = ""  # one CS-713 card per key: per photoperiod, or once when `once`
    once: bool = False
    since: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ask(self):
        return self.cls in PICK

    @property
    def title(self):
        return TITLES[self.cls]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _fmt(key, v):
    unit = UNITS.get(key, "")
    return f"{v:g}{unit}" if isinstance(v, (int, float)) else str(v)


def changes(before, after):
    """[(key, from, to)] for the keys whose value differs, in a stable order."""
    out = []
    for key in sorted(set(before or {}) | set(after or {})):
        a, b = _num((before or {}).get(key)), _num((after or {}).get(key))
        if a is None and b is None:
            continue
        if a is None or b is None or abs(a - b) > 1e-6:
            out.append((key, a, b))
    return out


def change_words(diff, limit=4):
    parts = [f"{LABELS.get(k, k.replace('_', ' '))} from {_fmt(k, a)} to {_fmt(k, b)}" for k, a, b in diff[:limit]]
    more = len(diff) - limit
    return ", ".join(parts) + (f" and {more} more" if more > 0 else "")


def _zone(view, z):
    return view.titles.get(z) or f"zone {z}"


def _profile_name(view, pid):
    for p in (view.plan or {}).get("plan", {}).get("profiles", []) if view.plan else []:
        if p.get("id") == pid:
            return p.get("name") or pid
    return pid


def _assignment(view, z):
    for a in ((view.plan or {}).get("plan") or {}).get("zones", []):
        if a.get("zone_id") == z:
            return a
    return None


def zone_plan(view, z):
    """{day, week, of_days, profile, bias, status, next_change} for a zone, from the plan in force."""
    row = view.in_force().get(z) or {}
    day = row.get("day")
    out = {"zone": z, "day": day, "week": math.ceil(day / 7) if isinstance(day, int) and day > 0 else None,
           "of_days": None, "profile": _profile_name(view, row.get("profile_id")) if row.get("profile_id") else None,
           "steering_pct": row.get("bias"), "status": row.get("status"), "next_change": None}
    a = _assignment(view, z)
    if a and isinstance(day, int):
        schedule = a.get("schedule") or []
        out["of_days"] = max((s.get("end_day", 0) for s in schedule), default=None)
        now = next((s for s in schedule if s.get("start_day", 0) <= day <= s.get("end_day", 0)), None)
        for s in sorted(schedule, key=lambda s: s.get("start_day", 0)):
            if s.get("start_day", 0) > day and now is not None and (
                    s.get("profile_id"), s.get("bias")) != (now.get("profile_id"), now.get("bias")):
                out["next_change"] = {"day": s["start_day"], "in_days": s["start_day"] - day,
                                      "profile": _profile_name(view, s.get("profile_id"))}
                break
    return out


def _seed(plan):
    """The plan every room starts with (strategy._seed_plan): never one a grower saved."""
    profiles = (plan or {}).get("profiles") or []
    return bool(profiles) and all(str(p.get("id", "")).startswith("zone-") and str(p.get("id", "")).endswith(
        "-current") and p.get("vegetative") == p.get("generative") for p in profiles)


def _key(view, cls, zone=None, *extra):
    return "_".join(["plan", cls, view.slug] + ([f"z{zone}"] if zone is not None else []) + [str(e) for e in extra])


def _after(view, when, minutes):
    return when is not None and view.now >= when + timedelta(minutes=minutes)


# ---------------------------------------------------------------- the detectors
def _day(view, adh):
    """D1/D2/D3: today's plan day applied, or not."""
    out = []
    on = view.lights_on_at
    if view.status == "active" and _after(view, on, SETTLE_MIN):
        today = view.preview.get("today") if view.fresh_plan() else None
        behind = []
        for z, row in sorted(view.in_force().items()):
            day = view.in_force_day(z)
            if day is not None and day < view.expected_day:
                behind.append((z, row))
        missed = []
        for z, row in behind:
            want = (today or {}).get(z)
            if want is None:
                continue
            diff = changes(row.get("parameters"), want.get("parameters"))
            if diff or want.get("status") != row.get("status"):
                missed.append((z, row, want, diff))
        why = view.attrs.get("degraded_reason") or "the plan has not said why"
        if missed:
            z0, _row, want0, diff0 = missed[0]
            what = (change_words(diff0) if diff0 else f"its status from {_row.get('status')} to {want0.get('status')}")
            names = ", ".join(_zone(view, z) for z, *_ in missed)
            out.append(Drift(
                "transition_missed", None, 1,
                f"today's targets not applied for {names}: {why}. Day {want0.get('day')} changes {what}.",
                f"{names} {'has' if len(missed) == 1 else 'have'} not had today's plan day applied, because {why}. "
                f"For {_zone(view, z0)}, day {want0.get('day')} changes {what}.",
                ("Fix or unmap the probe the plan waits for; until then that zone stays on the earlier day's "
                 "targets.",
                 "Check the plan's dates for this room.",
                 "Nothing changes today: the plan moves on as soon as the reading is back."),
                key=_key(view, "transition_missed", None, view.expected_day.isoformat()),
                extra={"zones": {z: want.get("parameters") for z, _r, want, _d in missed},
                       "days": {z: want.get("day") for z, _r, want, _d in missed}}))
        elif behind:
            out.append(Drift("day_behind", None, 6, "today's plan day not applied yet; it changes no target today.",
                             "", alert=False, key=_key(view, "day_behind")))
    if view.status == "armed" and _after(view, on, 30) and view.fresh_plan():
        due = view.plan.get("armed_after")
        try:
            due_at = datetime.fromisoformat(due).astimezone().replace(tzinfo=None) if due else None
        except (TypeError, ValueError):
            due_at = None
        if due_at is not None and due_at <= on:
            why = view.attrs.get("degraded_reason") or "the plan has not said why"
            out.append(Drift(
                "armed_not_started", None, 1, f"armed but not started at this lights-on: {why}.",
                f"The plan was armed to start at this lights-on and has not, because {why}.",
                ("Fix or unmap the probe the plan waits for; until then the room stays on its own settings.",
                 "Check the plan's start dates for this room.",
                 "Nothing changes today: the plan starts as soon as the reading is back."),
                key=_key(view, "armed_not_started", None, view.expected_day.isoformat())))
    return out


def _saved(view, adh):
    """D4: a plan saved and never armed, a whole photoperiod on."""
    rev = view.attrs.get("revision")
    if view.status != "draft" or view.attrs.get("release_legacy") is True or type(rev) is not int or rev < 1:
        adh["draft_seen"] = None
        return []
    seen = adh.get("draft_seen") or {}
    if seen.get("revision") != rev:
        adh["draft_seen"] = seen = {"revision": rev, "first_day": view.expected_day.isoformat()}
    if seen.get("first_day", "") >= view.expected_day.isoformat() or not view.fresh_plan():
        return []
    plan = view.plan.get("plan") or {}
    if _seed(plan):
        return []
    starts = [a.get("start_date") for a in plan.get("zones", []) if isinstance(a.get("start_date"), str)]
    if not any(s <= view.expected_day.isoformat() for s in starts):
        return []
    return [Drift("saved_not_armed", None, 4, "a saved plan has not been armed, so the room runs on its own settings.",
                  f"A grow plan (revision {rev}) was saved and has not been armed for a whole day; its start dates "
                  "have passed, so nothing in the room is running from it.",
                  ("Your saved plan has not been armed, so the room is on its own settings. Arm it, or change its "
                   "start dates.", "If you meant to keep editing, nothing is running from it yet."),
                  key=_key(view, "saved_not_armed", None, f"r{rev}"), once=True)]


def _ending(view):
    """D5: a managed zone's plan ends within three days."""
    if view.status != "active" or not view.fresh_plan():
        return []
    out = []
    for z in sorted(view.in_force()):
        zp = zone_plan(view, z)
        if not isinstance(zp["day"], int) or not zp["of_days"]:
            continue
        left = zp["of_days"] - zp["day"]
        if 0 <= left <= 3:
            stage = 3 if left >= 2 else 1
            out.append(Drift(
                "plan_ending", z, 2, f"{_zone(view, z)}'s plan ends after day {zp['of_days']} (in {left} days).",
                "", (f"{_zone(view, z).capitalize()}'s plan ends after day {zp['of_days']} (in {left} days). After that "
                     "the plan holds its steering (rescue water only) until you extend or disarm it.",),
                key=_key(view, "plan_ending", z, view.attrs.get("revision"), stage), once=True))
    return out


def _catalog_rows(view):
    """[(zone, key, [entity ids])] for every number the plan controls."""
    rows = []
    for zone, keys in ((view.plan or {}).get("catalog") or {}).items():
        try:
            z = int(zone)
        except (TypeError, ValueError):
            continue
        for key, entry in (keys or {}).items():
            ids = [e for e in (entry or {}).get("entity_ids") or [] if isinstance(e, str)]
            if ids:
                rows.append((z, key, ids, entry))
    return rows


def _edits(view, adh):
    """D7: a number the plan controls changed while it runs: no effect, and nothing said so."""
    rev = view.attrs.get("revision")
    if view.status != "active" or view.natives is None or not view.fresh_plan():
        if view.status not in ("active", "disarming"):
            adh["baseline"] = None
        return []
    base = adh.get("baseline") or {}
    if (base.get("revision"), base.get("status")) != (rev, view.status):
        adh["baseline"] = base = {"revision": rev, "status": view.status, "values": {}}
    values = base["values"]
    out, managed = [], set(view.in_force())
    for z, key, ids, _entry in _catalog_rows(view):
        if z not in managed:
            continue
        for eid in ids:
            v = _num(view.natives.get(eid))
            if v is None:
                continue
            if eid not in values:
                values[eid] = v
                continue
            if abs(values[eid] - v) <= 1e-6:
                continue
            plan = _num(((view.in_force().get(z) or {}).get("parameters") or {}).get(key))
            what = LABELS.get(key, key.replace("_", " "))
            moves = zone_plan(view, z).get("next_change")
            out.append(Drift(
                "shadowed_edit", z, 3,
                f"{what} on {_zone(view, z)} was changed to {_fmt(key, v)}; the plan keeps it at "
                f"{_fmt(key, plan)} today, so the change has no effect.",
                f"{what.capitalize()} on {_zone(view, z)} was changed from {_fmt(key, values[eid])} to {_fmt(key, v)}, "
                f"not by the plan. The plan keeps it at {_fmt(key, plan)} today, so the change has no effect while "
                "the plan runs.",
                (f"Your change to {what} on {_zone(view, z)} has no effect while the plan runs. To keep it, change "
                 "the plan's days from today; to drop it, set it back.",
                 f"The plan moves this setting on day {moves['day']}; edit the plan if that is too late."
                 if moves else "The plan keeps this setting as it is; edit the plan to move it.",
                 "No effect today: it comes back into force when the plan is disarmed."),
                key=_key(view, "shadowed_edit", z, eid.split(".")[-1], view.expected_day.isoformat()),
                extra={"entity_id": eid}))
    return out


def _disarm(view):
    """D8: what comes back at the next lights-on, when it differs from today's plan by more than a step."""
    if view.status != "disarming" or not view.fresh_plan():
        return []
    rows, back = view.in_force(), []
    for z, key, _ids, entry in _catalog_rows(view):
        plan = _num(((rows.get(z) or {}).get("parameters") or {}).get(key))
        own = _num((entry or {}).get("value"))
        step = _num((entry or {}).get("step")) or 0.0
        if plan is not None and own is not None and abs(plan - own) > step + 1e-9:
            back.append(f"{LABELS.get(key, key)} on {_zone(view, z)} {_fmt(key, plan)} -> {_fmt(key, own)}")
    if not back:
        return []
    listed = "; ".join(back[:6]) + (f" and {len(back) - 6} more" if len(back) > 6 else "")
    return [Drift("disarm_return", None, 3, f"at lights-on the room goes back to its own settings: {listed}.", "",
                  (f"At lights-on the room goes back to its own settings. These differ from today's plan: {listed}.",),
                  key=_key(view, "disarm_return", None, view.attrs.get("revision")), once=True)]


def _steering(view):
    """D9: the plan steers a zone one way while its steering select says the other."""
    if view.status != "active":
        return []
    out = []
    for z, row in sorted(view.in_force().items()):
        bias, mode = _num(row.get("bias")), view.steering.get(z)
        if bias is None or mode is None or row.get("status") != "active":
            continue
        if (bias < NEUTRAL[0] and mode == "generative") or (bias > NEUTRAL[1] and mode == "vegetative"):
            out.append(Drift(
                "steering_disagrees", z, 5,
                f"{_zone(view, z)}'s steering select says {mode}; the plan steers it {bias:g} % generative.",
                f"{_zone(view, z).capitalize()}'s steering select says {mode}; the plan steers it {bias:g} % generative "
                "today.",
                (f"{_zone(view, z).capitalize()}'s steering select says {mode} but the plan steers it {bias:g} % "
                 "generative. The plan sets the targets; the select still decides when the evening dryback may start "
                 "early. Set the select to match.",
                 "If you changed the select on purpose, change the plan's bias to match."),
                key=_key(view, "steering_disagrees", z, view.expected_day.isoformat())))
    return out


def _boundary(view):
    """D10: the controller's day may start at another hour than the plan's."""
    if view.status not in ("armed", "active") or view.lights_bad_since is None:
        return []
    if view.now - view.lights_bad_since < timedelta(minutes=30):
        return []
    return [Drift("day_boundary", None, 5,
                  f"the controller is not reading the lights hours from the integration ({view.lights_source}).", "",
                  ("The controller is not reading the room's lights hours from the integration "
                   f"({view.lights_source}), so its day may start at a different time from the plan's. Check the "
                   "lights hours.",),
                  key=_key(view, "day_boundary", None, view.expected_day.isoformat()))]


def _light(view):
    """D11: the room's mapped light reads on while the hours say off, or the reverse, for 15 minutes."""
    if view.light_state not in ("on", "off") or view.light_since is None or view.lights_on_at is None:
        return []
    if view.now - view.light_since < timedelta(minutes=15):
        return []
    for edge in (view.lights_on_at, view.lights_off_at, view.lights_on_at + timedelta(days=1)):
        if abs((view.now - edge).total_seconds()) < 600:
            return []
    other = "on" if view.lights_on else "off"
    return [Drift("lights_entity", None, 5, f"the room's light reads {view.light_state} but the hours say {other}.",
                  "", (f"The room's light reads {view.light_state} but the lights hours say {other}. The engine "
                       "follows the hours.",),
                  key=_key(view, "lights_entity", None, view.expected_day.isoformat()))]


def _phases(view):
    """P1-P3 (tripwires: decide() and the blind path make them impossible) and P5 (a long ramp, advisory)."""
    out = []
    on, off = view.lights_on_at, view.lights_off_at
    for z, zs in sorted(view.zones.items()):
        name = _zone(view, z)
        last = zs.get("last_daily_reset")
        if isinstance(last, str):
            try:
                last = date.fromisoformat(last[:10])
            except ValueError:
                last = None
        if (on is not None and view.lights_on and _after(view, on, SETTLE_MIN) and isinstance(last, date)
                and last < view.expected_day):
            out.append(_trip(view, "missed_day_start", z, f"{name} did not start its day at lights-on "
                             f"({on:%H:%M}): it is still in {zs.get('phase')}."))
        if off is not None and not view.lights_on and _after(view, off, SETTLE_MIN) and zs.get("phase") != "P3":
            out.append(_trip(view, "missed_lights_off", z, f"{name} did not stop for the night at lights-off "
                             f"({off:%H:%M}): it is in {zs.get('phase')}."))
        changed, wait = zs.get("last_phase_change"), _num(zs.get("p0_wait"))
        if (view.lights_on and zs.get("phase") == "P0" and isinstance(changed, datetime) and wait is not None
                and view.now - changed > timedelta(minutes=wait + 15)):
            out.append(_trip(view, "p0_overrun", z, f"{name} has been in its morning dryback since "
                             f"{changed:%H:%M}, past its maximum wait of {wait:g} min."))
        shots, gap = _num(zs.get("p1_shots")), _num(zs.get("p1_gap"))
        if (view.lights_on and zs.get("phase") == "P1" and isinstance(changed, datetime) and shots and gap
                and view.now - changed > timedelta(minutes=shots * gap + 60)):
            window = shots * gap + 60
            hours = (view.now - changed).total_seconds() / 3600
            out.append(Drift(
                "p1_long", z, 4, f"{name} has been ramping for {hours:.1f} h.",
                f"{name.capitalize()} has been in its ramp (P1) for {hours:.1f} h; the ramp's maximum shots at its "
                f"time between shots take about {window / 60:.1f} h. {zs.get('waiting') or ''}".strip(),
                (f"{name.capitalize()} has been ramping for {hours:.1f} h: "
                 f"{zs.get('waiting') or 'the ramp waits for its shots or a gate'}.",),
                alert=view.now - changed > timedelta(minutes=2 * window),
                key=_key(view, "p1_long", z, view.expected_day.isoformat())))
    return out


def _trip(view, cls, z, words):
    return Drift(cls, z, 1 if cls != "p0_overrun" else 2, words, words,
                 (f"This should not happen: {words} The controller keeps running; please report it with the "
                  "controller log.",),
                 key=_key(view, cls, z, view.expected_day.isoformat()))


def detect(view, adh):
    """Every drift this pass, highest severity first. Nothing in the first SETTLE_MIN minutes after a start."""
    if view.uptime_min < SETTLE_MIN:
        return []
    found = (_day(view, adh) + _saved(view, adh) + _ending(view) + _edits(view, adh) + _disarm(view)
             + _steering(view) + _boundary(view) + _light(view) + _phases(view))
    return sorted(found, key=lambda d: (d.sev, d.zone or 0))


def due(adh, drift, day):
    """Whether `drift` raises its CS-713 card now: once per episode (per photoperiod, or once when it is `once`)."""
    if not drift.alert:
        return False
    seen = adh.get("alerted", {}).get(drift.key)
    return seen is None if drift.once else seen != day.isoformat()


def raised(adh, drift, day):
    adh.setdefault("alerted", {})[drift.key] = day.isoformat()


def observe(adh, zone, phase, now, how, day_start):
    """A zone's phase, as the end of a pass found it: a change since the last one seen is logged with why (`how`),
    whatever made it. Entries from before this grow-day's start (`day_start`) are dropped. -> True when it logged."""
    log = adh.setdefault("phase_log", {}).setdefault(str(zone), [])
    log[:] = [e for e in log if str(e.get("at", "")) >= day_start.isoformat(timespec="minutes")]
    last = log[-1]["to"] if log else None
    if log and last == phase:
        return False
    log.append({"at": now.isoformat(timespec="minutes"), "from": last, "to": phase,
                "how": how or ("observed" if log else "first seen")})
    del log[:-LOG_MAX]
    return True


def has_plan(view):
    """A plan a grower saved: not the plan every room starts with, never saved."""
    rev = view.attrs.get("revision")
    return view.status not in ("none", None) and not (view.status == "draft" and not (type(rev) is int and rev >= 1))


def headline(view, drifts):
    """The panel's one line, or None with no plan."""
    status = view.status
    if not has_plan(view):
        return None
    name = ((view.plan or {}).get("plan") or {}).get("name") if view.plan else None
    top = next((d for d in drifts if d.cls not in ("day_behind",)), None)
    if status == "draft":
        return "Plan saved, not armed" + (f": {top.line}" if top and top.cls == "saved_not_armed" else ".")
    if status == "armed":
        if top is not None:
            return f"Plan armed · {top.line}"
        try:
            at = datetime.fromisoformat((view.plan or {}).get("armed_after")).astimezone().replace(tzinfo=None)
        except (TypeError, ValueError):
            return "Plan armed: it starts at the next lights-on."
        return f"Plan armed: it starts at lights-on {at:%H:%M} on {at:%d %B}."
    if status == "disarming":
        return "Plan disarming: the room goes back to its own settings at the next lights-on."
    if status == "error":
        return f"Plan held: {view.attrs.get('error') or 'see the plan'}."
    zones = [zone_plan(view, z) for z in sorted(view.in_force())]
    days = sorted({z["day"] for z in zones if isinstance(z["day"], int)})
    profiles = {z["profile"] for z in zones if z["profile"]}
    label = name or (profiles.pop() if len(profiles) == 1 else None)
    if days:
        weeks = sorted({math.ceil(d / 7) for d in days if d > 0})
        span = f"day {days[0]}" if len(days) == 1 else f"days {days[0]}-{days[-1]}"
        of = {z["of_days"] for z in zones if z["of_days"]}
        if len(days) == 1 and len(of) == 1:
            span += f" of {of.pop()}"
        if weeks:
            span += f" (week {weeks[0]})" if len(weeks) == 1 else f" (weeks {weeks[0]}-{weeks[-1]})"
    else:
        span = "no day in force"
    head = " · ".join(x for x in ("Plan" + (f": {label}" if label else ""), span) if x)
    return f"{head} · {top.line if top else 'on track'}"


def panel(view, drifts, notes=None, bridged=None):
    """The `plan` attribute on the brain panel sensor. `notes` {class: (suggestion, why, action)} is the brain's pick
    for a drift it was asked about."""
    notes = notes or {}
    shown = []
    for d in drifts:
        pick, why, action = notes.get(d.cls, (None, "", None))
        shown.append({"class": d.cls, "zone": d.zone, "severity": d.sev, "line": d.line,
                      "suggestion": pick or (d.suggestions[0] if d.suggestions else ""), "why": why or "",
                      "since": d.since, "action": action or "advise"})
    line = headline(view, drifts)
    if bridged and view.status == "active":
        line = (f"Plan: day {bridged.get('day')}'s targets applied by the controller at "
                f"{str(bridged.get('since', ''))[11:16]} while the plan waits for: "
                f"{view.attrs.get('degraded_reason') or 'a stale probe'}.")
    return {
        "status": view.status, "headline": line,
        "zones": [zone_plan(view, z) for z in sorted(view.in_force())] if view.status in ("active", "disarming")
        else [],
        "expected_day": view.expected_day.isoformat(),
        "in_force_day": view.attrs.get("grow_day"), "bridged": bridged is not None,
        "drifts": shown[:8], "checked_at": view.now.isoformat(timespec="seconds"),
        "data_age_min": None if view.plan_age_h is None else round(view.plan_age_h * 60.0),
    }
