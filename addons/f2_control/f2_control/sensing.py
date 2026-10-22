"""Read-only numbers the controller already has, worked into what a grower reads: the live dryback of each zone, and
each zone's measured answer to VPD. Pure: nothing here reads Home Assistant or drives hardware; the controller hands
in what it read and publishes what comes back. Nothing here feeds decide() or the auto setpoints.

- dryback(): the zone's drop from its peak, in the same relative % decide() uses ((peak - VWC) / peak x 100), with
  the drop in VWC points beside it, for the zone_N_dryback_app sensor.
- The water-and-VPD record (water_vpd, day_hist): per grow-day, the litres the zone was given, the median dryback
  rate in quiet lights-on windows, and the mean lights-on VPD. fit() relates the rate to VPD over the last KEEP days.
  A state file from before this module has neither key and loads with them empty (restore()).
"""
from __future__ import annotations

import math
import statistics

KEEP = 14  # grow-days of water-and-VPD records kept per zone
QUIET_MIN = 30.0  # minutes after a shot before a dryback rate is clean (drainage has finished), as auto_setpoints
SAMPLE_EVERY_MIN = 10.0  # one quiet-rate sample per this many minutes
MAX_SAMPLES = 200
MIN_DAYS = 7  # grow-days with a rate and a VPD before the slope is reported
MIN_SPREAD_KPA = 0.2  # ...and how far apart their VPDs must be
SETTLE_MIN = 20.0  # a zone losing water this long after its last shot is drying back, not draining


def _number(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def number(state):
    """A Home Assistant state as a finite float, or None."""
    try:
        return _number(float(state))
    except (TypeError, ValueError):
        return None


def dryback(peak, vwc, rate, minutes_since_shot):
    """(state, attributes) for the zone's dryback sensor. The state is the RELATIVE drop from the peak in %; the
    attributes carry the drop in VWC points as well, so the two are never mistaken for each other."""
    peak, vwc = _number(peak), _number(vwc)
    if not peak or peak <= 0 or vwc is None:
        return "unknown", {"unit_of_measurement": "%", "peak_vwc": None, "dryback_points": None,
                           "rate_points_per_h": None, "drying_back": False}
    rate = _number(rate)  # None = the controller has no rate: published as null, never as a 0.0 that reads "steady"
    return (peak - vwc) / peak * 100.0, {
        "unit_of_measurement": "%",
        "peak_vwc": peak,
        "dryback_points": peak - vwc,
        "rate_points_per_h": rate,
        "drying_back": rate is not None and rate > 0 and (_number(minutes_since_shot) or 0.0) >= SETTLE_MIN,
    }


def post_shot_rate(window, last_shot):
    """The zone's dryback rate in VWC points an hour from its readings taken after its last shot, or None until
    there are three (the window is not cleared on a shot, and a window holding the shot's rise measures the shot,
    not the drying). Never negative, as the snapshot's rate."""
    pts = [(t, v) for t, v in window if last_shot is None or t > last_shot]
    if len(pts) < 3:
        return None
    dt_h = (pts[-1][0] - pts[0][0]).total_seconds() / 3600.0
    return max(0.0, (pts[0][1] - pts[-1][1]) / dt_h) if dt_h > 0 else None


def next_irrigation(phase, vwc, threshold, rate, after_shot):
    """(hours, reason) to the zone's next P2 top-up: hours is None, with the reason, whenever the controller has no
    current estimate. 0.0 = due now."""
    if vwc is None:
        return None, "the controller has no VWC reading for this zone"
    if phase != "P2":
        return None, "the controller estimates the next shot only in P2"
    if vwc <= threshold:
        return 0.0, None
    if rate is None:
        return None, ("no dryback rate yet since the last shot" if after_shot
                      else "no dryback rate yet")
    if rate <= 0:
        return None, "VWC is not falling, so there is no time to the next shot"
    return round(min((vwc - threshold) / rate, 48.0), 2), None


DRYBACK_NOTE = ("Relative dryback: (peak - VWC) / peak x 100, the % the controller steers on. The peak is the "
                "highest VWC since the last lights-on, so it reads near 0 just after lights-on, and overnight it is "
                "the drop from the day's peak. dryback_points is the same drop in VWC points.")


# ---------------------------------------------------------------- water and VPD
def fresh():
    return {"water_vpd": None, "day_hist": []}


def _day_ok(e):
    return isinstance(e, dict) and isinstance(e.get("date"), str) and all(
        e.get(k) is None or _number(e.get(k)) is not None for k in ("litres", "per_plant", "rate", "vpd"))


def restore(saved):
    """The two keys from a saved zone dict; anything of the wrong shape is dropped, never fails the load."""
    out = fresh()
    hist = saved.get("day_hist")
    if isinstance(hist, list):
        out["day_hist"] = [dict(e) for e in hist if _day_ok(e)][-KEEP:]
    w = saved.get("water_vpd")
    if (isinstance(w, dict) and isinstance(w.get("day"), str) and isinstance(w.get("rates"), list)
            and isinstance(w.get("vpd"), list) and len(w["vpd"]) == 2):
        rates = [r for r in w["rates"] if _number(r) is not None][-MAX_SAMPLES:]
        total, n = w["vpd"]
        if _number(total) is not None and isinstance(n, int) and n >= 0:
            out["water_vpd"] = {"day": w["day"], "rates": rates, "vpd": [float(total), n],
                                "last": _number(w.get("last"))}
    return out


def vpd_from(temperature_c, humidity_pct):
    """Air VPD in kPa from temperature (deg C) and relative humidity (%), Tetens; None without both."""
    t, rh = _number(temperature_c), _number(humidity_pct)
    if t is None or rh is None or not 0 <= rh <= 100 or not -10 <= t <= 60:
        return None
    return 0.6108 * math.exp(17.27 * t / (t + 237.3)) * (1.0 - rh / 100.0)


def sample(st, *, day, ts, lights_on, rate, minutes_since_shot, vpd):
    """This pass, for the record of grow-day `day`: a quiet lights-on dryback rate now and then, and the VPD.
    -> the previous grow-day's closed record when `day` is a new one (the caller adds its litres), else None."""
    w = st.get("water_vpd")
    closed = None
    if w is not None and w["day"] != day:
        closed = close(w)
        w = None
    if w is None:
        w = st["water_vpd"] = {"day": day, "rates": [], "vpd": [0.0, 0], "last": None}
    if not lights_on:
        return closed
    vpd = _number(vpd)
    if vpd is not None and 0 <= vpd <= 6:
        w["vpd"] = [w["vpd"][0] + vpd, w["vpd"][1] + 1]
    rate = _number(rate)
    if (rate is not None and 0.02 <= rate <= 5.0 and (_number(minutes_since_shot) or 0.0) >= QUIET_MIN
            and (w["last"] is None or ts - w["last"] >= SAMPLE_EVERY_MIN * 60.0)):
        w["rates"] = (w["rates"] + [rate])[-MAX_SAMPLES:]
        w["last"] = ts
    return closed


def close(w):
    """A grow-day's record from its samples: the median quiet rate (points/h) and mean lights-on VPD (kPa)."""
    total, n = w["vpd"]
    return {"date": w["day"], "rate": statistics.median(w["rates"]) if w["rates"] else None,
            "vpd": total / n if n else None, "samples": len(w["rates"]), "litres": None, "per_plant": None}


def keep(st, record, litres, plants):
    """Add a closed grow-day's record with its litres (and per plant, when the plant count is known)."""
    litres = _number(litres)
    record = {**record, "litres": litres,
              "per_plant": litres / plants if litres is not None and plants and plants >= 1 else None}
    kept = [e for e in st.get("day_hist") or [] if e.get("date") != record["date"]]
    st["day_hist"] = (kept + [record])[-KEEP:]
    return record


def fit(days):
    """The zone's dryback rate against VPD over its recorded grow-days: {"slope", "r", "n", "spread", "words"}.
    The slope (points/h per kPa) is None until MIN_DAYS days with a spread of at least MIN_SPREAD_KPA."""
    pts = [(e["vpd"], e["rate"]) for e in days if _number(e.get("vpd")) is not None and _number(e.get("rate"))]
    n = len(pts)
    spread = max(v for v, _ in pts) - min(v for v, _ in pts) if pts else 0.0
    out = {"slope": None, "r": None, "n": n, "spread": spread}
    if n < MIN_DAYS or spread < MIN_SPREAD_KPA:
        out["words"] = (f"Not enough data yet: {n} of {MIN_DAYS} grow-days with a quiet dryback rate and a VPD, "
                        f"VPD spread {spread:.2f} of {MIN_SPREAD_KPA:g} kPa.")
        return out
    mx, my = sum(v for v, _ in pts) / n, sum(r for _, r in pts) / n
    sxx = sum((v - mx) ** 2 for v, _ in pts)
    syy = sum((r - my) ** 2 for _, r in pts)
    sxy = sum((v - mx) * (r - my) for v, r in pts)
    slope = sxy / sxx
    out.update(slope=slope, r=sxy / math.sqrt(sxx * syy) if syy > 0 else None)
    r_words = "unknown" if out["r"] is None else f"{out['r']:.2f}"
    out["words"] = (f"Over the last {n} grow-days, at 0.2 kPa more VPD this zone dried about {abs(slope) * 0.2:.2f} "
                    f"points an hour {'faster' if slope >= 0 else 'slower'} in quiet lights-on windows (r "
                    f"{r_words}). An observation, not a cause: plant "
                    "size and light change over the same days.")
    return out
