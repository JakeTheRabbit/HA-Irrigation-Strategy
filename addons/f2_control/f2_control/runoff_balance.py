"""The sump as a water balance: a room-wide runoff estimate from the sump pump's power, never a reading of runoff.

Every sump cycle empties one pit volume V, so the time between two runs gives the pit's inflow rate. In a sealed room
three things fill the pit: runoff (arriving in the minutes after shots), condensate from each AC and dehumidifier
(following their run time), and a small baseline (seepage). Per interval between two runs:

    1 pit / hours = sum_k beta_k x (share of the interval unit k ran) + r' x (litres fed per hour, shifted by the drain
                    delay) + c

fitted by non-negative least squares over the last KEEP_DAYS days, every interval counted. r' x V is the runoff
fraction. The drain delay is learned by trying each delay in DELAYS_MIN up to the room's attribution window and
keeping the best fit.

Sealed room (water in = water out): over a grow-day, sump litres = fed litres - the change in substrate water, since
the water the plants transpire ends up as condensate in the same pit. That closure gives V with no bucket test (the
median over complete days), and is a daily self-check against a leak, a missed pump cycle or a stuck float when V is
known otherwise. The split then gives the runoff % and the transpiration (condensate) per day.

Pure: the controller hands in the readings and publishes what comes back. Nothing here waters, holds or moves a
setting. Read-only, room-wide (or per sump, when rooms share one), per grow-day; a per-zone figure would assume every
zone runs off alike, so none is given.
"""
from __future__ import annotations

import bisect
import math

KEEP_DAYS = 14
KEEP_S = KEEP_DAYS * 86400
MAX_GAP_H = 6.0  # an interval longer than this is a missed cycle or a stopped pump, not one pit
MIN_INTERVALS = 24  # intervals before a fit is reported
MIN_CLOSURE_DAYS = 3  # complete grow-days before the closure calibrates the pit volume
CLOSURE_ALERT_PCT = 30.0  # a grow-day whose sump litres miss fed minus the substrate change by more: CS-314
DELAYS_MIN = (0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240)
BLOCK_H = 6  # today's runoff and condensate in blocks of this many hours
MAX_ITEMS = 4000


def fresh():
    return {"runs": [], "shots": [], "on": {}, "cursor": None, "days": [], "day": None}


def _pair(x):
    return (isinstance(x, list) and len(x) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                         and math.isfinite(v) for v in x))


def load(saved):
    """A saved record, anything of the wrong shape dropped (never fails the load); an old file has none."""
    out = fresh()
    if not isinstance(saved, dict):
        return out
    out["runs"] = [list(x) for x in saved.get("runs") or [] if _pair(x)][-MAX_ITEMS:]
    out["shots"] = [list(x) for x in saved.get("shots") or [] if _pair(x)][-MAX_ITEMS:]
    on = saved.get("on")
    if isinstance(on, dict):
        out["on"] = {str(k): [list(x) for x in v if _pair(x)][-MAX_ITEMS:] for k, v in on.items() if isinstance(v, list)}
    cursor = saved.get("cursor")
    out["cursor"] = cursor if isinstance(cursor, (int, float)) and not isinstance(cursor, bool) else None
    out["days"] = [dict(d) for d in saved.get("days") or [] if isinstance(d, dict) and isinstance(d.get("date"), str)
                   ][-KEEP_DAYS:]
    day = saved.get("day")
    if isinstance(day, dict) and isinstance(day.get("date"), str):
        out["day"] = dict(day)
    return out


def has_data(st):
    return bool(st["runs"] or st["shots"] or st["days"] or st["on"])


def prune(st, now_s):
    lo = now_s - KEEP_S
    st["runs"] = [x for x in st["runs"] if x[1] >= lo][-MAX_ITEMS:]
    st["shots"] = [x for x in st["shots"] if x[0] >= lo][-MAX_ITEMS:]
    st["on"] = {k: [x for x in v if x[1] >= lo][-MAX_ITEMS:] for k, v in st["on"].items()}


# ---------------------------------------------------------------- readings in
def spans(rows, on, end_s):
    """[(start, end)] epoch seconds while `on(value)` held, from history rows [(value, changed_epoch)], oldest first.
    The last span still on ends at `end_s`."""
    out, start = [], None
    for value, t in rows:
        if t is None:
            continue
        if on(value):
            if start is None:
                start = t
        elif start is not None:
            out.append([start, t])
            start = None
    if start is not None:
        out.append([start, end_s])
    return out


def merge(old, new):
    """Spans from a new read added to those kept: one whose start is already kept replaces it (it ran on)."""
    kept = {round(s[0]): s for s in old}
    for s in new:
        kept[round(s[0])] = s
    return [kept[k] for k in sorted(kept)]


def add_shot(st, t_s, litres):
    if litres and litres > 0:
        st["shots"] = (st["shots"] + [[float(t_s), float(litres)]])[-MAX_ITEMS:]


# ---------------------------------------------------------------- the fit
def _on_seconds(sp, a, b):
    return sum(max(0.0, min(e, b) - max(s, a)) for s, e in sp)


def intervals(st, units, delay_s):
    """One row per interval between two consecutive pump runs (start to start), no longer than MAX_GAP_H."""
    rows = []
    starts = [r[0] for r in st["runs"]]
    shots = sorted(st["shots"])
    times = [t + delay_s for t, _litres in shots]
    cum = [0.0]
    for _t, litres in shots:
        cum.append(cum[-1] + litres)
    for a, b in zip(starts, starts[1:]):
        dt = b - a
        if dt <= 0 or dt > MAX_GAP_H * 3600:
            continue
        fed = cum[bisect.bisect_right(times, b)] - cum[bisect.bisect_right(times, a)]
        rows.append({"a": a, "b": b, "h": dt / 3600.0,
                     "on": [_on_seconds(st["on"].get(u, []), a, b) / dt for u in units], "fed_l": fed})
    return rows


def _solve(m, v):
    """Gaussian elimination with partial pivoting; None when singular."""
    n = len(v)
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            return None
        a[c], a[p] = a[p], a[c]
        for r in range(n):
            if r != c:
                f = a[r][c] / a[c][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [a[i][n] / a[i][i] for i in range(n)]


def _inverse_diag(m, k):
    """Element (k, k) of the inverse of m, or None."""
    e = [1.0 if i == k else 0.0 for i in range(len(m))]
    col = _solve(m, e)
    return None if col is None else col[k]


def gram(x, y, w):
    """X'WX, X'Wy and y'Wy of a weighted least-squares problem."""
    n = len(x[0])
    xx = [[sum(wi * xi[a] * xi[b] for xi, wi in zip(x, w)) for b in range(n)] for a in range(n)]
    xy = [sum(wi * xi[a] * yi for xi, yi, wi in zip(x, y, w)) for a in range(n)]
    return xx, xy, sum(wi * yi * yi for yi, wi in zip(y, w))


def nnls(xx, xy, yy):
    """Non-negative least squares from the normal equations, for a few columns: every subset of free columns is
    solved and the best feasible one kept (exact for small problems). -> (coefficients, residual sum, free columns)
    or None."""
    n = len(xy)
    best = None
    for mask in range(1, 1 << n):
        cols = [j for j in range(n) if mask >> j & 1]
        sol = _solve([[xx[a][b] for b in cols] for a in cols], [xy[a] for a in cols])
        if sol is None or any(v < 0 for v in sol):
            continue
        coef = [0.0] * n
        for j, v in zip(cols, sol):
            coef[j] = v
        res = yy - 2 * sum(c * v for c, v in zip(coef, xy)) + sum(
            coef[a] * coef[b] * xx[a][b] for a in range(n) for b in range(n))
        if best is None or res < best[1]:
            best = (coef, max(res, 0.0), cols)
    return best


def fit(st, units, max_delay_min):
    """The pit's inflow split over the units, the feed and a baseline, at the drain delay that fits best.
    -> dict, or None with fewer than MIN_INTERVALS intervals."""
    best = None
    for d in [d for d in DELAYS_MIN if d <= max_delay_min] or [0]:
        rows = intervals(st, units, d * 60)
        if len(rows) < MIN_INTERVALS:
            return None
        x = [r["on"] + [r["fed_l"] / r["h"], 1.0] for r in rows]
        y = [1.0 / r["h"] for r in rows]
        w = [r["h"] for r in rows]  # each interval weighs as long as it lasted
        xx, xy, yy = gram(x, y, w)
        got = nnls(xx, xy, yy)
        if got is None:
            continue
        mean = sum(yi * wi for yi, wi in zip(y, w)) / sum(w)
        total = sum(wi * (yi - mean) ** 2 for yi, wi in zip(y, w))
        r2 = 1.0 - got[1] / total if total > 0 else None
        if best is None or got[1] < best["res"]:
            best = {"coef": got[0], "res": got[1], "free": got[2], "r2": r2, "delay_min": d, "rows": rows, "xx": xx}
    if best is None:
        return None
    k = len(units)  # the feed's column
    se = None
    if k in best["free"] and len(best["rows"]) > len(best["free"]):
        cols = best["free"]
        m = [[best["xx"][a][b] for b in cols] for a in cols]
        diag = _inverse_diag(m, cols.index(k))
        sigma2 = best["res"] / (len(best["rows"]) - len(cols))
        se = math.sqrt(diag * sigma2) if diag is not None and diag > 0 else None
    return {"beta": best["coef"][:k], "r_pit_per_l": best["coef"][k], "base_pit_per_h": best["coef"][k + 1],
            "r_se": se, "r2": best["r2"], "delay_min": best["delay_min"], "n": len(best["rows"])}


# ---------------------------------------------------------------- the grow-day closure
def runs_between(st, a, b):
    return sum(1 for s, _e in st["runs"] if a <= s < b)


def fed_between(st, a, b):
    return sum(litres for t, litres in st["shots"] if a <= t < b)


def day_tick(st, day, start_s, substrate_l):
    """At each pass: the open grow-day, and the one before closed when `day` is new. -> the closed day or None."""
    cur = st["day"]
    closed = None
    if cur is not None and cur["date"] != day:
        end = start_s
        closed = {"date": cur["date"], "start": cur["start"], "end": end,
                  "runs": runs_between(st, cur["start"], end), "fed_l": fed_between(st, cur["start"], end),
                  "substrate_start_l": cur.get("substrate_l"), "substrate_end_l": substrate_l}
        s0 = closed["substrate_start_l"]
        closed["delta_substrate_l"] = (substrate_l - s0) if s0 is not None and substrate_l is not None else None
        st["days"] = ([d for d in st["days"] if d["date"] != closed["date"]] + [closed])[-KEEP_DAYS:]
        cur = None
    if cur is None:
        st["day"] = {"date": day, "start": start_s, "substrate_l": substrate_l}
    return closed


def balance_litres(d):
    """What the sump should have taken that grow-day in a sealed room: fed - the substrate's change, or None."""
    return None if d.get("delta_substrate_l") is None else d["fed_l"] - d["delta_substrate_l"]


def closure_volume(st):
    """The pit volume the sealed-room closure gives: the median of (fed - substrate change) / runs over complete
    days, or None with fewer than MIN_CLOSURE_DAYS."""
    vals = sorted(balance_litres(d) / d["runs"] for d in st["days"]
                  if d.get("runs") and balance_litres(d) is not None and balance_litres(d) > 0)
    if len(vals) < MIN_CLOSURE_DAYS:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def closure_error_pct(d, volume):
    want = balance_litres(d)
    if not volume or want is None or want <= 0:
        return None
    return (d["runs"] * volume - want) / want * 100.0


# ---------------------------------------------------------------- what is published
def estimate(st, units, *, volume, volume_source, f, now_s, today_start_s, unresolvable=None):
    """(state, attributes) for the room's runoff sensor. State: the runoff % of the water fed, room-wide, or
    'unresolvable' / 'learning' with the reason in `why`."""
    attrs = {"scope": "room-wide estimate, per grow-day (one sump serves the room)", "unit_of_measurement": "%",
             "litres_per_run": volume, "litres_per_run_source": volume_source,
             "runs_today": runs_between(st, today_start_s, now_s), "fed_today_l": fed_between(st, today_start_s, now_s),
             "days": st["days"][-7:]}
    if volume:
        for d in attrs["days"]:
            d["closure_error_pct"] = closure_error_pct(d, volume)
    if unresolvable:
        return "unresolvable", {**attrs, "why": unresolvable}
    if f is None:
        return "learning", {**attrs, "why": f"fewer than {MIN_INTERVALS} pump cycles recorded yet"}
    attrs.update(r2=f["r2"], drain_delay_min=f["delay_min"], intervals=f["n"])
    if not volume:
        share = None
        fed = sum(x["fed_l"] for x in intervals(st, units, f["delay_min"] * 60))
        runs = f["n"]
        if runs:
            share = f["r_pit_per_l"] * fed / runs * 100.0
        return "learning", {**attrs, "runoff_share_of_pit_pct": share,
                            "why": "the litres per sump run are unknown: set them (bucket test or pump flow), or wait "
                                   f"for {MIN_CLOSURE_DAYS} complete grow-days of the sealed-room closure"}
    runoff = f["r_pit_per_l"] * volume
    band = 2.0 * f["r_se"] * volume * 100.0 if f["r_se"] is not None else None
    per_unit = {u: b * volume for u, b in zip(units, f["beta"])}  # litres an hour while the unit runs
    sump_today = attrs["runs_today"] * volume
    runoff_today = runoff * attrs["fed_today_l"]
    blocks = []
    t = today_start_s
    while t < now_s:
        e = min(t + BLOCK_H * 3600, now_s)
        fed = fed_between(st, t, e)
        blocks.append({"from": t, "to": e, "runs": runs_between(st, t, e), "fed_l": fed, "runoff_l": runoff * fed,
                       "condensate_l": max(0.0, runs_between(st, t, e) * volume - runoff * fed)})
        t = e
    attrs.update(runoff_pct=runoff * 100.0, band_pct=band, litres_per_hour=per_unit,
                 baseline_l_per_h=f["base_pit_per_h"] * volume, sump_today_l=sump_today, runoff_today_l=runoff_today,
                 transpiration_today_l=max(0.0, sump_today - runoff_today), blocks=blocks)
    return runoff * 100.0, attrs


def words(state, attrs):
    """One sentence for the AI assistant's evidence and the why answers."""
    if not isinstance(state, float):
        return f"room-wide runoff estimate: {state} ({attrs.get('why', '')})"
    band = attrs.get("band_pct")
    return (f"room-wide runoff estimate from the sump water balance: {state:.0f}%"
            + (f" (+/- {band:.0f})" if band is not None else "") + " of the water fed, fit R2 "
            + ("unknown" if attrs.get("r2") is None else f"{attrs['r2']:.2f}")
            + "; a hint with an error band, not a measured catch")
