"""Plant twin wrapped around the REAL engine decide(). Pure, no I/O.

The engine fires every shot by its own rules, exactly as on the box. The twin supplies the plant
(water + salt balance) and the controller's bookkeeping, and lets a supervisor rewrite the zone's
SETPOINTS while the day runs. That is the whole experiment: do better setpoints make the engine's
own shots follow the reference curve?

Water is tracked in VWC points. Salt is EC x water, so transpiration concentrates it, feed dilutes
it towards the feed EC, and runoff above the knee carries salt away.
"""
import math
import random

from crop_steering_engine import ZoneParams, ZoneSnapshot, decide

LITRES_PER_PCT = 6.75 * 42 / 100.0  # one 1% shot across the zone (42 plants x 6.75 L)
SHOT_MIN_PER_PCT = 1.0  # a 1% shot holds the valve open about a minute (0.0467 L/s); the controller is busy meanwhile
UPTAKE_EC = 1.0  # mS/cm equivalent the plant removes with the water it drinks


def params_from(sp):
    """Engine setpoint suffixes -> ZoneParams, the same mapping controller._params() performs."""
    return ZoneParams(
        p1_target=sp["p1_target_vwc"], p2_threshold=sp["p2_vwc_threshold"], p2_shot_size=sp["p2_shot_size"],
        p1_initial=sp["p1_initial_shot_size"], p1_incr=sp["p1_shot_size_increment"],
        p1_max_shots=int(sp["p1_maximum_shots"]), p1_time_between_min=sp["p1_time_between_shots"],
        dryback_target=sp["dryback_target"], p0_max_wait_min=sp["p0_maximum_wait_time"],
        ec_target_p0=sp["ec_target_p0"], ec_target_p1=sp["ec_target_p1"], ec_target_p2=sp["ec_target_p2"],
        p3_emergency_floor=sp["p3_emergency_vwc_threshold"], p3_emergency_shot=sp["p3_emergency_shot_size"],
        max_daily_volume=sp["max_daily_volume"], field_capacity=sp["field_capacity"], max_ec=sp["maximum_ec"],
        stacking_on=False, watchdog_hours=sp.get("watchdog_hours", 3.0),
        p1_min_shots=int(sp.get("p1_minimum_shots", 0)),
    )


def run(model, setpoints, start_vwc, start_ec, feed_ec, days=1, lights_on_h=10, lights_off_h=22,
        supervisor=None, every_min=15, demand=None, noise=0.0, seed=7, latency_min=2, drain_tau_min=15.0):
    """-> (trace, changes). trace rows are dicts; changes = [(clock_h, suffix, old, new, why)].

    supervisor(ctx) -> [(suffix, new_value, why)], called every `every_min` minutes with the live context.
    """
    rnd = random.Random(seed)
    sp = dict(setpoints)
    day_min = int(((lights_off_h - lights_on_h) % 24) * 60)
    water, salt = start_vwc, start_vwc * start_ec
    phase, peak, shots, since, phase_min, daily_l = "P3", start_vwc, 0, 999.0, 0.0, 0.0
    pending, recent, responses, watch, runoff_today, busy_until = {}, [], [], None, 0.0, -1
    trace, changes = [], []
    for m in range(days * 24 * 60):
        dm = m % 1440
        h = lights_on_h + m / 60.0
        lights = dm < day_min
        rate = model.day_rate * (demand(dm, day_min) if demand else 1.0) if lights else model.night_rate
        drink = min(rate / 60.0, max(0.0, water - 5.0))
        water, salt = water - drink, max(0.0, salt - UPTAKE_EC * drink)
        if m in pending:
            lift = pending.pop(m)
            water, salt = water + lift, salt + feed_ec * lift
        if water > model.knee:
            out = (water - model.knee) * (1.0 - math.exp(-1.0 / drain_tau_min))
            salt -= salt / water * out
            water -= out
            runoff_today += out
        ec = salt / water
        seen = water + (rnd.gauss(0, noise) if noise else 0.0)
        recent = (recent + [seen])[-60:]
        if watch and m == watch[0]:
            responses, watch = (responses + [round(seen - watch[1], 2)])[-4:], None
        peak = max(peak, seen)
        snap = ZoneSnapshot(
            vwc=seen, ec=ec, phase=phase, peak_vwc=peak,
            dryback_pct=max(0.0, (peak - seen) / peak * 100.0) if peak > 0 else 0.0,
            dryback_rate=max(0.0, recent[0] - recent[-1]) * 60.0 / max(1, len(recent) - 1),
            shot_count=shots, phase_minutes=phase_min, minutes_since_shot=since, daily_vol=daily_l,
            ec_smooth=ec, lights_on=lights, lights_just_on=dm == 0,
            hours_to_lights_on=(1440 - dm) / 60.0 if lights else (1440 - dm) / 60.0,
            hours_to_lights_off=max(0.0, (day_min - dm) / 60.0), uptime_min=m + 60.0, feed_ec=feed_ec,
        )
        new_phase, _thr, fire, size, reason = decide(snap, params_from(sp))
        if m < busy_until:  # the real controller runs a shot synchronously: no second decision until it ends
            fire = False
        if new_phase != phase:  # the controller's bookkeeping on a phase change
            if new_phase == "P0":
                daily_l, shots, peak, runoff_today = 0.0, 0, seen, 0.0
            if new_phase == "P1":
                shots = 0
            phase, phase_min = new_phase, 0.0
        if fire and size > 0:
            pending[m + latency_min] = pending.get(m + latency_min, 0.0) + model.gain * size
            watch, since, shots, daily_l = (m + 8, seen), 0.0, shots + 1, daily_l + size * LITRES_PER_PCT
            busy_until = m + max(latency_min, int(round(size * SHOT_MIN_PER_PCT))) + 1
        else:
            since += 1.0
        phase_min += 1.0
        if supervisor and m % every_min == 0:
            ctx = dict(minute=m, shot=round(size, 2) if fire and size > 0 else 0.0, dryback_rate=snap.dryback_rate,
                       minutes_since_shot=since,
                       clock_h=h % 24, minutes_since_lights_on=dm if lights else None, lights_on=lights, phase=phase,
                       vwc=seen, ec=ec, feed_ec=feed_ec, peak_today=peak, shots_today=shots, responses=list(responses),
                       runoff_today=runoff_today, setpoints=dict(sp), reason=reason)
            for suffix, value, why in supervisor(ctx) or []:
                if sp.get(suffix) != value:
                    changes.append((round(h, 2), suffix, sp.get(suffix), value, why))
                    sp[suffix] = value
        trace.append(dict(h=round(h, 3), vwc=round(water, 3), ec=round(ec, 3), shot=round(size, 2) if fire else 0.0,
                          phase=phase, p1_target=sp["p1_target_vwc"], p2_threshold=sp["p2_vwc_threshold"]))
    return trace, changes
