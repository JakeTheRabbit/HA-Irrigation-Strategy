"""Each zone's grow-day summary: one record per zone and grow-day, built at lights-on (the P3 -> P0 reset) for the day
that just ended, and sent to the integration's grow-day store (crop_steering.grow_day_record) so grows stay comparable
after Home Assistant's recorder has purged the readings. Read-only: nothing here changes watering.

Only while the room's Record grow days switch is on. Pure: it reads and writes the zone's state dict and nothing else.

- day_acc: the grow-day being measured now: readings (moisture, pore EC, feed EC and pH), shots by kind and litres,
  alert codes, and each probe behind the zone (sampled every few minutes).
- day_out: the summaries built and not yet taken by Home Assistant, newest KEEP kept, so an integration updated
  later, or a Home Assistant that was down, still receives them.

A state file from before this module has neither key and loads with them empty. Stored values keep full precision.
"""
from __future__ import annotations

import math
from datetime import date, datetime

KEEP = 14
MAX_PROBES = 16
MAX_ALERTS = 20
SCHEMA = 1

# decide()'s Reason.kind (and the controller's own kinds) -> what the summary counts the shot as.
SHOT_KINDS = {
    "p1_ramp": "ramp",
    "p1_extra": "extra",
    "p2_topup": "topup",
    "min_daily": "topup",
    "p2_dilute": "dilute",
    "p2_rescue": "dilute",
    "flush_high_ec": "dilute",
    "p0_ec_flush": "dilute",
    "p3_emergency": "rescue",
    "watchdog": "rescue",
    "blind_fallback": "rescue",
    "blind_copy_rescue": "rescue",
    "p3_hold": "p3",
    "test_shot": "test",
}
KINDS = ("ramp", "extra", "topup", "dilute", "rescue", "p3", "test", "other")


def fresh():
    return {"day_acc": None, "day_out": []}


def _number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _stat():
    return {"n": 0, "sum": 0.0, "min": None, "max": None}


def _add(stat, v):
    v = _number(v)
    if v is None:
        return
    stat["n"] += 1
    stat["sum"] += v
    stat["min"] = v if stat["min"] is None else min(stat["min"], v)
    stat["max"] = v if stat["max"] is None else max(stat["max"], v)


def _stat_ok(s):
    return (isinstance(s, dict) and isinstance(s.get("n"), int) and not isinstance(s.get("n"), bool) and s["n"] >= 0
            and _number(s.get("sum")) is not None
            and all(s.get(k) is None or _number(s.get(k)) is not None for k in ("min", "max")))


def _out(stat, digits=3):
    if not stat["n"]:
        return None
    return {"min": round(stat["min"], digits), "max": round(stat["max"], digits),
            "mean": round(stat["sum"] / stat["n"], digits)}


def _acc(day, now):
    return {"day": day, "since": now.isoformat(timespec="seconds"), "samples": 0, "vwc": _stat(), "ec": _stat(),
            "feed_ec": _stat(), "feed_ph": _stat(), "shots": {}, "litres": {}, "alerts": [], "probes": {}}


def _day(st, day, now):
    """The accumulator of grow-day `day`, started when absent, or None: the one of the grow-day before is still open
    (its lights-on reset comes later in this pass, and closes it). One older than that was never closed (the room was
    off across a lights-on): it is dropped, and this grow-day starts."""
    acc = st.get("day_acc")
    if isinstance(acc, dict) and acc.get("day") != day:
        try:
            stale = (date.fromisoformat(day) - date.fromisoformat(acc["day"])).days != 1
        except (TypeError, ValueError):
            stale = True
        if not stale:
            return None
        acc = None
    if not isinstance(acc, dict):
        acc = st["day_acc"] = _acc(day, now)
    return acc


def observe(st, *, day, now, vwc, ec, feed_ec=None, feed_ph=None, stalled=False):
    """One control pass's readings of the zone; `stalled`: its ramp stalled this grow-day (core.p1_stall)."""
    acc = _day(st, day, now)
    if acc is None:
        return
    acc["samples"] += 1
    if stalled:
        acc["p1_stall"] = True
    _add(acc["vwc"], vwc)
    _add(acc["ec"], ec)
    _add(acc["feed_ec"], feed_ec)
    _add(acc["feed_ph"], feed_ph)


def shot(st, *, day, now, kind, litres):
    """A delivered shot, by the rule that fired it."""
    acc = _day(st, day, now)
    if acc is None:
        return
    k = SHOT_KINDS.get(kind, "other")
    acc["shots"][k] = int(acc["shots"].get(k) or 0) + 1
    acc["litres"][k] = float(acc["litres"].get(k) or 0.0) + (_number(litres) or 0.0)


def alert(st, code):
    """An alert raised for the zone: its code, once a day."""
    acc = st.get("day_acc")
    if isinstance(acc, dict) and isinstance(code, str) and code not in acc["alerts"] and len(acc["alerts"]) < MAX_ALERTS:
        acc["alerts"].append(code[:16])


def probes(st, *, day, now, readings):
    """The probes behind the zone, read now: [(kind "vwc"|"ec", entity_id, name, unit, value or None, used)]."""
    acc = _day(st, day, now)
    if acc is None:
        return
    for kind, pid, name, unit, value, used in readings:
        key = f"{kind}|{pid}"
        p = acc["probes"].get(key)
        if p is None:
            if len(acc["probes"]) >= MAX_PROBES:
                continue
            p = acc["probes"][key] = {"kind": kind, "entity_id": pid, "name": None, "unit": None,
                                      "stat": _stat(), "seen": 0, "used": 0}
        p["name"] = str(name)[:80] if name else p["name"]
        p["unit"] = str(unit)[:16] if unit else p["unit"]
        p["seen"] += 1
        p["used"] += 1 if used else 0
        _add(p["stat"], value)


def close(st, *, day, now, info):
    """The grow-day `day` ended (lights-on): its summary, queued in day_out, and a fresh accumulator. `info` is what
    the controller knows of the zone now: zone, lights, plant_count, mode, targets, litres (the day's counted water),
    plan_day, day_start (when the grow-day began). Returns the summary, or None without any reading."""
    acc = st.get("day_acc")
    st["day_acc"] = None
    if not isinstance(acc, dict) or not acc.get("samples"):
        return None
    began = acc.get("day")
    since = acc.get("since")
    partial = began != day  # it began on another grow-day than the one that ended
    try:
        start = info.get("day_start")
        if start and (datetime.fromisoformat(since) - start).total_seconds() > 3600:
            partial = True  # recording began, or the controller came back, well after lights-on
    except (TypeError, ValueError):
        partial = True
    plateau = next((e for e in reversed(st.get("plateau_hist") or []) if e.get("date") == day), None)
    night = next((e for e in reversed(st.get("night_hist") or []) if e.get("date") == day), None)
    litres = _number(info.get("litres"))
    if litres is None:
        litres = sum(acc["litres"].values())
    plants = info.get("plant_count")
    plants = int(plants) if _number(plants) and plants >= 1 else None
    probe_rows = []
    for p in acc["probes"].values():
        values = _out(p["stat"])
        probe_rows.append({
            "kind": p["kind"], "entity_id": p["entity_id"], "name": p["name"], "unit": p["unit"],
            "peak": values and values["max"], "trough": values and values["min"], "mean": values and values["mean"],
            "used_share": round(p["used"] / p["seen"], 3) if p["seen"] else None,
        })
    vwc = _out(acc["vwc"])
    top = night and _number(night.get("plateau"))
    landing = night and _number(night.get("landing"))
    summary = {
        "schema": SCHEMA,
        "date": day,
        "zone": info.get("zone"),
        "partial": partial,
        "began": began,
        "since": since,
        "samples": acc["samples"],
        "plan_day": info.get("plan_day"),
        "lights": info.get("lights"),
        "mode": info.get("mode"),
        "vwc": vwc and {"peak": vwc["max"], "trough": vwc["min"], "mean": vwc["mean"]},
        "ec": _out(acc["ec"]),
        "feed_ec": _out(acc["feed_ec"]),
        "feed_ph": _out(acc["feed_ph"]),
        "plateau": plateau and {"value": plateau.get("value"), "how": plateau.get("how"), "shots": plateau.get("shots")},
        # the night before this grow-day and the morning dryback it ended in (zone_history: dated by its morning)
        "p0": night and {"dryback_pct": _number(night.get("dryback_pct")),
                         "drop_pts": round(top - landing, 3) if top and landing is not None else None,
                         "landing": landing},
        "night": night and {"rate": _number(night.get("night_rate")), "shots": night.get("night_shots")},
        "p1_stall": acc.get("p1_stall") is True,
        "shots": {k: int(v) for k, v in acc["shots"].items()},
        "shot_litres": {k: round(v, 3) for k, v in acc["litres"].items()},
        "rescues": int(acc["shots"].get("rescue") or 0),
        "litres": round(litres, 3),
        "plant_count": plants,
        "litres_per_plant": round(litres / plants, 4) if plants else None,
        "alerts": list(acc["alerts"]),
        "targets": info.get("targets"),
        "probes": probe_rows,
    }
    out = [s for s in st.get("day_out") or [] if s.get("date") != day]
    st["day_out"] = (out + [summary])[-KEEP:]
    return summary


def taken(st, dates):
    """Home Assistant has the summaries of these grow-days."""
    st["day_out"] = [s for s in st.get("day_out") or [] if s.get("date") not in set(dates)]


def stop(st):
    """Recording is off: today's measurement is dropped (what is queued is still sent)."""
    st["day_acc"] = None


def _date_ok(v):
    try:
        date.fromisoformat(v)
        return True
    except (TypeError, ValueError):
        return False


def restore(saved):
    """The two keys from a saved zone dict; anything of the wrong shape is dropped instead of failing the load."""
    out = fresh()
    acc = saved.get("day_acc")
    if (isinstance(acc, dict) and _date_ok(acc.get("day")) and isinstance(acc.get("since"), str)
            and isinstance(acc.get("samples"), int) and all(_stat_ok(acc.get(k)) for k in ("vwc", "ec", "feed_ec", "feed_ph"))
            and isinstance(acc.get("shots"), dict) and isinstance(acc.get("litres"), dict)
            and isinstance(acc.get("alerts"), list) and isinstance(acc.get("probes"), dict)
            and all(isinstance(p, dict) and _stat_ok(p.get("stat")) for p in acc["probes"].values())):
        out["day_acc"] = acc
    items = saved.get("day_out")
    if isinstance(items, list):
        out["day_out"] = [dict(s) for s in items if isinstance(s, dict) and _date_ok(s.get("date"))][-KEEP:]
    return out
