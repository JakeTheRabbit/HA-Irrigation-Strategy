"""Each zone's own record of its plateaus and its nights, for the dryback planner
(docs/superpowers/specs/2026-10-02-dryback-planner-jev-steering-design.md). Pure: it reads and writes the zone's
state dict and nothing else.

- plateau_hist: one entry per grow day whose P1 handed over to P2: the VWC it reached, how P1 ended, and after how
  many shots. A second hand-over on the same grow day replaces the first.
- night_hist: one entry per morning: the night from lights-off to the day's first shot, where Athena measures the
  landing (p.39), with the night's drying rate and the P0 drop.
- night: the night being measured now, from the lights-off reading until the next grow day's first shot closes it.
  A night still open when a later morning's first shot comes (a missed lights-on or lights-off: the room was off,
  or the app restarted across it) is dropped: no record beats a record of two nights.

Both lists keep the newest KEEP entries. A state file from before this module has none of the three keys and loads
with them empty. Stored values keep full precision; only night_words() rounds, for people to read.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

KEEP = 14


def fresh():
    return {"plateau_hist": [], "night_hist": [], "night": None}


def _night(off_at, off_vwc, plateau, day):
    return {"off_at": off_at, "off_vwc": off_vwc, "plateau": plateau, "day": day, "on_at": None, "on_vwc": None,
            "on_shots": 0, "shots": 0, "end_at": None, "end_vwc": None}


def _number(v):
    """`v` when it is a finite number (a bool is not one), else None."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _parses(v, parse):
    try:
        parse(v)
        return True
    except (TypeError, ValueError):
        return False


def _plateau_ok(e):
    return (isinstance(e, dict) and _parses(e.get("date"), date.fromisoformat)
            and (_number(e.get("value")) or 0) > 0 and _count(e.get("shots")))


def _night_ok(n):
    """The open night with every key in place, or None when anything in it has the wrong type."""
    if not isinstance(n, dict) or not _parses(n.get("off_at"), datetime.fromisoformat):
        return None
    n = {**_night(n["off_at"], None, None, None), **n}
    ok = (all(_count(n[k]) for k in ("shots", "on_shots"))
          and all(n[k] is None or _parses(n[k], datetime.fromisoformat) for k in ("on_at", "end_at"))
          and all(n[k] is None or _number(n[k]) is not None for k in ("off_vwc", "on_vwc", "end_vwc", "plateau"))
          and (n["day"] is None or _parses(n["day"], date.fromisoformat)))
    return n if ok else None


def restore(saved):
    """The three keys from a saved zone dict. Anything of the wrong shape or type is dropped instead of failing the
    load, or failing later inside the control loop: a damaged file, or one a newer version wrote (whose extra keys
    are kept)."""
    out = fresh()
    items = saved.get("plateau_hist")
    if isinstance(items, list):
        out["plateau_hist"] = [dict(e) for e in items if _plateau_ok(e)][-KEEP:]
    items = saved.get("night_hist")
    if isinstance(items, list):
        out["night_hist"] = [dict(e) for e in items
                             if isinstance(e, dict) and _parses(e.get("date"), date.fromisoformat)][-KEEP:]
    out["night"] = _night_ok(saved.get("night"))
    return out


def _iso(t):
    return t.isoformat(timespec="seconds")


def _hours(start, end):
    """Real hours between two ISO times, with or without a UTC offset: a clock change in between counts right."""
    return (datetime.fromisoformat(end).timestamp() - datetime.fromisoformat(start).timestamp()) / 3600.0


def plateau(st, *, day, value, how, shots):
    """Record the grow day's plateau. Nothing is recorded (None) without a usable value."""
    if (_number(value) or 0) <= 0:
        return None
    entry = {"date": day, "value": float(value), "how": str(how)[:80], "shots": int(shots or 0)}
    kept = [e for e in st.get("plateau_hist") or [] if e.get("date") != day]
    st["plateau_hist"] = (kept + [entry])[-KEEP:]
    return entry


def phase_changed(st, was, new, *, day, how):
    """A phase change by anyone (the engine, a Jev judge, the operator). P1 handing over to P2 is the day's plateau:
    the highest VWC since lights-on, which the controller keeps in `peak`."""
    if was == "P1" and new == "P2":
        return plateau(st, day=day, value=st.get("peak"), how=how, shots=st.get("shots"))
    return None


def lights_off(st, vwc, now, day):
    """The lights went off: tonight is measured from this reading. A night still open (no first shot came) is
    dropped. `day` is the grow day that is ending: its plateau, when P1 found one, is what the landing is measured
    from, never an older day's."""
    last = (st.get("plateau_hist") or [None])[-1]
    st["night"] = _night(_iso(now), vwc, last["value"] if last and last.get("date") == day else None, day)


def lights_on(st, vwc, now):
    """The lights came on: the night's last reading, and the shots so far, so a shot in P0 can be told apart."""
    n = st.get("night")
    if n is not None and n["on_at"] is None:
        n["on_at"], n["on_vwc"], n["on_shots"] = _iso(now), vwc, n["shots"]


def shot(st, *, vwc_before, now, day, first):
    """A shot was delivered. The day's first shot (`first`) closes the night it follows, the one whose lights-off
    ended the grow day before `day`: the VWC just before the shot is the landing, and the record goes into night_hist. Any other shot while a night is open is counted; the night's rate is
    measured up to the first one that came before lights-on. Returns the closed record, or None."""
    n = st.get("night")
    if n is None:
        return None
    if not first:
        if n["on_at"] is None and n["end_at"] is None:
            n["end_at"], n["end_vwc"] = _iso(now), vwc_before
        n["shots"] += 1
        return None
    st["night"] = None
    if n["day"] is None or date.fromisoformat(n["day"]) != date.fromisoformat(day) - timedelta(days=1):
        return None  # not last night: a morning was missed in between
    record = _close(n, vwc_before, now, day)
    kept = [e for e in st.get("night_hist") or [] if e.get("date") != day]
    st["night_hist"] = (kept + [record])[-KEEP:]
    return record


def _close(n, landing, now, day):
    end_at, end_vwc = (n["end_at"], n["end_vwc"]) if n["end_at"] else (n["on_at"], n["on_vwc"])
    rate = None
    if n["off_vwc"] is not None and end_vwc is not None and end_at is not None:
        hours = _hours(n["off_at"], end_at)
        if hours > 0:
            rate = (n["off_vwc"] - end_vwc) / hours
    drop = None
    if n["on_vwc"] is not None and landing is not None and n["shots"] == n["on_shots"]:
        drop = n["on_vwc"] - landing
    top = n["plateau"]
    dryback = (top - landing) / top * 100.0 if top and landing is not None else None
    return {"date": day, "plateau": top, "off_at": n["off_at"], "off_vwc": n["off_vwc"], "on_at": n["on_at"],
            "on_vwc": n["on_vwc"], "first_at": _iso(now), "landing": landing, "night_rate": rate,
            "p0_drop": drop, "dryback_pct": dryback, "night_shots": n["shots"]}


def night_words(r):
    """The morning record in one line, for the activity feed and the log."""
    def num(v):
        return "unknown" if v is None else f"{v:.2f}"

    words = f"night: landed {num(r['landing'])}"
    if r["dryback_pct"] is not None:
        words += f" ({r['dryback_pct']:.1f} % under {r['plateau']:.2f})"
    words += f", {num(r['night_rate'])} pts/h, P0 drop {num(r['p0_drop'])}"
    if r["night_shots"]:
        words += f", {r['night_shots']} night shot(s)"
    return words
