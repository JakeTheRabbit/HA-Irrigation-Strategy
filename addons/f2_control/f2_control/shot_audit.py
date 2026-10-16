"""Did each shot reach the zone? A code-only check of every shot, whether or not the AI assistant is on.

It reuses the AI assistant's own pure helpers (brain.context: response, expected_rise, landed_share), which read
nothing but the readings and shots kept here, so the table and the AI shot judge measure a shot the same way. The
audit keeps its own short in-memory history per zone (a restart empties it; the table fills again with the next
shots). Nothing here waters, holds or moves a setting: the controller publishes the table and, only when the room's
Shot check select says table_and_alert and the AI assistant is off, raises CS-701 after two shots in a row with no
sign of water.

Verdicts: landed (the spike reached LANDED_SHARE of the rise the litres should give), small (some rise, less than
that), flat_ec_moved (moisture flat but pore EC moved: the water passed the probe, the slab may be full),
no_sign (neither), settling (younger than SETTLE_MIN), unknown (no reading to judge it by).
"""
from __future__ import annotations

from datetime import datetime

from brain.context import LANDED_SHARE, Shot, ZoneHistory, expected_rise, landed_share, response

MODES = ("off", "table", "table_and_alert")
SHOWN = 8  # shots in the table
RISE_PTS = 0.1  # a spike under this many points is no rise
EC_MOVE = 0.1  # pore EC moved this many mS/cm: the water passed the probe
NEAR_FC_PTS = 1.0  # a shot started this close to field capacity is not counted toward the alert (the slab is full)
# Shots the alert never counts: a flush and the P3 shots are expected to show little rise, a test shot is 10 s.
NOT_COUNTED = frozenset({"flush_high_ec", "p0_ec_flush", "p1_flush", "p2_dilute", "p3_emergency", "p3_hold",
                         "test_shot"})
IN_A_ROW = 2


def _store(room):
    return room.__dict__.setdefault("_shot_audit", {})


def _zone(room, zone):
    return _store(room).setdefault(zone, {"hist": ZoneHistory(hours=8), "start": None, "alerted": None})


def reading(room, zone, now, vwc, ec):
    _zone(room, zone)["hist"].add_reading(now, vwc, ec)


def started(room, zone, snap, kind):
    _zone(room, zone)["start"] = (datetime.now(), kind, None if snap is None else snap.vwc,
                                  None if snap is None else snap.ec)


def counted(room, zone, litres):
    z = _store(room).get(zone)
    if z is None or z["start"] is None:
        return
    start, z["start"] = z["start"], None
    t0, kind, pre_v, pre_e = start
    z["hist"].add_shot(Shot(t0, (datetime.now() - t0).total_seconds(), float(litres or 0.0), str(kind or "shot"),
                            pre_v, pre_e))


def verdict(r, substrate_l):
    if not r.settled:
        return "settling"
    share = landed_share(r, substrate_l)
    if share is not None and share >= LANDED_SHARE:
        return "landed"
    if share is None and r.peak_rise is not None and r.peak_rise >= LANDED_SHARE:
        return "landed"  # substrate unknown: a clear rise is a landing
    if r.peak_rise is not None and r.peak_rise >= RISE_PTS:
        return "small"
    if r.ec_move is not None and abs(r.ec_move) >= EC_MOVE:
        return "flat_ec_moved"
    if r.peak_rise is None and r.retained is None:
        return "unknown"
    return "no_sign"


def ai_labels(jev, room_slug, zone):
    """The AI shot judge's answers for this zone, [(shot start, label)], or [] when the AI assistant is off."""
    for judge in getattr(jev, "judges", None) or []:
        if getattr(judge, "name", None) == "shot":
            z = getattr(judge, "_zones", {}).get((room_slug, zone))
            return list(getattr(z, "labels", None) or [])
    return []


def _ai_for(start, labels):
    best = None
    for t, label in labels:
        gap = abs((t - start).total_seconds())
        if gap <= 120 and (best is None or gap < best[0]):
            best = (gap, label)
    return best and best[1]


def table(room, zone, now, substrate_l, field_capacity, ai=()):
    """The zone's last SHOWN shots, newest first, each with its numbers (units in the keys), the code verdict and,
    with the AI assistant on, its shot judge's answer for the same shot (`ai`: ai_labels())."""
    z = _store(room).get(zone)
    if z is None:
        return []
    out = []
    for s in list(z["hist"].shots)[-SHOWN:][::-1]:
        r = response(z["hist"], s, now)
        out.append({
            "start": s.start.astimezone().isoformat(timespec="seconds"),
            "kind": s.kind,
            "litres": s.litres,
            "seconds": s.seconds,
            "pre_vwc_pct": s.pre_vwc,
            "expected_rise_pts": expected_rise(s, substrate_l),
            "peak_rise_pts": r.peak_rise,
            "retained_rise_pts": r.retained,
            "ec_move_mscm": r.ec_move,
            "landed_share": landed_share(r, substrate_l),
            "verdict": verdict(r, substrate_l),
            "ai_verdict": _ai_for(s.start, ai),
            "counted": counts(s, field_capacity),
        })
    return out


def counts(shot, field_capacity):
    """Whether a shot may count toward the no-sign alert."""
    if shot.kind in NOT_COUNTED:
        return False
    return not (shot.pre_vwc is not None and field_capacity and shot.pre_vwc >= field_capacity - NEAR_FC_PTS)


def no_sign_in_a_row(room, zone, rows):
    """True once, when the newest IN_A_ROW counted, settled shots all showed no sign of water and the newest of
    them has not been alerted on yet. Shots that do not count are skipped, not a break in the row."""
    z = _store(room).get(zone)
    judged = [r for r in rows if r["counted"] and r["verdict"] not in ("settling", "unknown")][:IN_A_ROW]
    if z is None or len(judged) < IN_A_ROW or any(r["verdict"] != "no_sign" for r in judged):
        return False
    if z["alerted"] == judged[0]["start"]:
        return False
    z["alerted"] = judged[0]["start"]
    return True
