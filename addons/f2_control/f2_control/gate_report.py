"""Every pre-shot gate of one zone, each with pass or hold: the "Before the next shot" list on the dashboard's zone
page. Read only.

Controller._blocked is the safety interlock and stays the only thing that holds a shot: it stops at the first gate
that holds and raises the alerts some gates carry (CS-202, CS-313, CS-901, CS-902). This list is a second,
side-effect-free reading of the same gates in the same order, so a zone's card can say what passes as well as what
holds. It raises nothing, writes nothing and releases nothing (a max-run latch is released by _blocked alone). The
tank gates read the level the controller last read rather than reading the sensor again.

tests: addons/f2_control/tests/test_gate_report.py holds the first "hold" here equal to _blocked()'s answer over a
table of cases, so the two cannot drift apart.
"""
from __future__ import annotations

import sys
from datetime import datetime


def _gate(key, label, held=None, detail=""):
    return {"key": key, "label": label, "state": "hold" if held else "pass", "detail": held or detail}


def report(c, room, zone, reason=None):
    """[{key, label, state: pass|hold, detail}] in _blocked's order. `reason` is the zone's decision this pass (a
    held plan lets its rescues through, as in _blocked)."""
    m = sys.modules[type(c).__module__]  # the controller module: its reads and its constants
    out = []
    add = out.append

    add(_gate("setup", "Room setup adopted", getattr(room, "_setup_pending", None)))
    add(_gate("archived", "Room not archived",
              "Room archived in integration setup" if getattr(room, "setup_active", True) is False else None))
    add(_gate("room_on", "Room on", None if c._room_active(room) else "Room off (nothing growing)"))
    add(_gate("dosing", "No dosing hold", c._dosing_hold(room)))
    planned = m.strategy_block(getattr(room, "strategy_snapshot", None), zone)
    exempt = planned and getattr(reason, "kind", None) in m.PLAN_HOLD_EXEMPT
    add(_gate("plan", "Grow plan not holding", None if exempt else planned,
              f"{planned}: not holding a {getattr(reason, 'kind', '')} shot" if exempt else ""))
    add(_gate("hardware_fault", "No hardware fault", c._hardware_fault_block(room)))
    latch = (room.state.get(zone) or {}).get("max_run_latch")
    latched = None
    if latch:
        state, resets = c._max_run_switch(room)
        released = str(state).lower() == "off" or (
            state not in (None, "unknown", "unavailable", "") and resets != latch["resets"])
        if not released:
            latched = (f"max-run latch: {m.MAX_RUN_IN_A_ROW} shots in a row cut to the longest allowed shot; "
                       "fix its Repairs card (CS-312) to water again")
    add(_gate("max_run", "Max-run latch clear", latched))
    hw = room.hw
    add(_gate("valve_mapped", "Zone valve mapped", None if hw["valves"].get(zone) else (
        "no hardware mapped — set this zone's valve (and the pump and mainline, if the room "
        "has them) in the Crop Steering integration (or the add-on `hardware` option)")))
    if not hw["valves"].get(zone):
        return out  # nothing further can be read without a valve
    add(_gate("plumbing", "Plumbing matches the switches", m.plumbing_hold(hw)))
    undrivable = c._undrivable(room, zone)
    add(_gate("switchable", "Valve, pump and main line can be switched", (
        f"{', '.join(undrivable)} can't be switched (a zone valve, main line or pump must be a switch, "
        "input_boolean or valve)") if undrivable else None))
    add(_gate("kill_switch", "Kill switch on",
              None if c._on(m.room_gate(room), False) else f"{m.PRODUCT} disabled (kill switch off)"))
    retired = getattr(room, "_retired_off", None)
    add(_gate("retired", "No retired switch off",
              f"{' and '.join(retired)} off: engine switch switched off in its place" if retired else None))
    zone_switch = f"switch.crop_steering_{room.prefix}zone_{zone}_enabled"
    state = m.ha_get(zone_switch)[0]
    if state in (None, "unknown", "unavailable", ""):
        held = f"{zone_switch} unreadable (reads neither on nor off)"
    else:
        held = None if str(state).lower() in m.ON_STATES else "zone disabled"
    add(_gate("zone_on", "Zone switch on", held))
    add(_gate("manual_override", "No manual override",
              "manual override" if c._on(f"switch.crop_steering_{room.prefix}zone_{zone}_manual_override", False)
              else None))
    held = None
    for f in c.hold_entities:
        state = m.ha_get(f)[0]
        if state is None and m.ha_get_status(f)[0] == 404:
            held = m.hold_missing(f)
        elif state in (None, "unknown", "unavailable", ""):
            held = f"external hold {f} unreadable (reads neither on nor off)"
        elif str(state).lower() in m.ON_STATES:
            held = f"external hold ({f.split('.')[-1]})"
        if held:
            break
    add(_gate("external_holds", "No external hold", held,
              "" if c.hold_entities else "none configured"))
    add(_gate("settings", "Settings loaded", c._settings_hold(room, zone)))
    add(_gate("tank", "Tank above its minimum", _tank(room), "" if room.tank else "no tank level mapped"))
    add(_gate("feed_ec", "Source-water EC", _feed_ec(c, room, m), "" if room.feed_ec_sensor else "no feed EC probe"))
    add(_gate("feed_ph", "Source-water pH", _feed_ph(c, room, m), "" if room.feed_ph_sensor else "no feed pH probe"))
    offline = [e for e in (hw.get("pump"), hw.get("mainline"), hw["valves"].get(zone))
               if e and str(m.hw_get(e)[0]).lower() not in ("on", "off")]
    add(_gate("online", "Feed path online",
              f"{', '.join(offline)} offline (reads neither on nor off)" if offline else None))
    return out


def _tank(room):
    """The tank gates, on the level the controller last read (no new read, no alert)."""
    tank = room.tank
    if not tank:
        return None
    pct, low = getattr(room, "tank_reading", (None, None))
    unread = [e for e, value in ((tank.get("distance"), pct), (tank.get("float"), low)) if e and value is None]
    if unread:
        return f"tank level unknown ({', '.join(unread)})"
    if (pct is not None and room.tank_drawdown["low"]) or low:
        level = f"reads {pct:.1f} %" if pct is not None and room.tank_drawdown["low"] else "float reads low"
        return f"tank at its minimum ({level})"
    return None


def _feed_ec(c, room, m):
    if not room.feed_ec_sensor:
        return None
    lo = c._num(f"number.crop_steering_{room.prefix}irrigation_ec_min", 0)
    hi = c._num(f"number.crop_steering_{room.prefix}irrigation_ec_max", 0)
    if not (lo > 0 or hi > 0):
        return None
    feed = c._read_feed_ec(room)
    if feed is None:
        last = room._feed_last_good_time.timestamp() if room._feed_last_good_time else None
        if not m.feed_grace_ok(datetime.now().timestamp(), last, c.feed_grace_min):
            return f"source-water EC dead >{c.feed_grace_min:.0f}min — holding (fail-closed)"
        return None
    if (lo > 0 and feed < lo) or (hi > 0 and feed > hi):
        return f"source-water EC {feed:.1f} out of [{lo:g},{hi:g}]"
    return None


def _feed_ph(c, room, m):
    if not room.feed_ph_sensor:
        return None
    lo = c._num(f"number.crop_steering_{room.prefix}irrigation_ph_min", 0)
    hi = c._num(f"number.crop_steering_{room.prefix}irrigation_ph_max", 0)
    if not (lo > 0 or hi > 0):
        return None
    ph = c._read_feed_ph(room)
    if ph is None:
        last = room._feed_ph_last_good_time.timestamp() if room._feed_ph_last_good_time else None
        if not m.feed_grace_ok(datetime.now().timestamp(), last, c.feed_grace_min):
            return f"source-water pH probe dead >{c.feed_grace_min:.0f}min — holding (fail-closed)"
        return None
    if (lo > 0 and ph < lo) or (hi > 0 and ph > hi):
        return f"source-water pH {ph:.2f} out of [{lo:g},{hi:g}]"
    return None


def first_hold(gates):
    """The detail of the first gate that holds, or None: what _blocked() answers."""
    return next((g["detail"] for g in gates if g["state"] == "hold"), None)
