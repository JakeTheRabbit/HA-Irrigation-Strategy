"""The raw numbers, zone settings and stage the Claude brain reads beside a judge's sentences (haiku-brain-design
section 7). Code still does the arithmetic: these are the values of one moment, each key carrying its unit
(`_pct` moisture as the probe reads it, `_pct_rel` a share of the zone's own peak, `_pts` points, `_ms_cm`, `_l`,
`_min`, `_h`). Built from the context code made for the zone, never an entity id; a value code does not have is
left out, not guessed."""
from __future__ import annotations


def _r(x, nd=2):
    try:
        return None if x is None else round(float(x), nd)
    except (TypeError, ValueError):
        return None


def _drop_none(d):
    return {k: v for k, v in d.items() if v is not None}


def zone_numbers(ctx):
    s, p = ctx.snap, ctx.params
    out = {"phase": ctx.phase, "hours_to_lights_off_h": _r(ctx.hours_to_off, 1),
           "hours_to_lights_on_h": _r(ctx.hours_to_on, 1)}
    if s is not None:
        out.update(moisture_pct=_r(s.vwc), peak_pct=_r(s.peak_vwc), dryback_now_pct_rel=_r(s.dryback_pct),
                   drying_rate_pts_per_h=_r(s.dryback_rate), pore_ec_ms_cm=_r(s.ec), ec_settled_ms_cm=_r(s.ec_settled),
                   shots_today=s.shot_count, phase_minutes_min=_r(s.phase_minutes, 0),
                   minutes_since_shot_min=_r(s.minutes_since_shot, 0), daily_l=_r(s.daily_vol))
        if ctx.plants:
            out["litres_per_plant_l"] = _r(s.daily_vol / ctx.plants)
    if p is not None:
        out.update(field_capacity_pct=_r(p.field_capacity), p1_target_pct=_r(p.p1_target),
                   p2_threshold_pct=_r(p.p2_threshold), p3_floor_pct=_r(p.p3_emergency_floor),
                   daily_limit_l=_r(p.max_daily_volume), ec_target_p2_ms_cm=_r(p.ec_target_p2),
                   max_ec_ms_cm=_r(p.max_ec), dryback_target_pct_rel=_r(p.dryback_target))
    out["feed_ec_ms_cm"] = _r(ctx.feed_ec)
    room = [v.get("litres_per_plant") for v in (ctx.siblings or {}).values() if v.get("litres_per_plant") is not None]
    if out.get("litres_per_plant_l") is not None:
        room.append(out["litres_per_plant_l"])
    if len(room) >= 2:
        room.sort()
        mid = len(room) // 2
        out["room_median_litres_per_plant_l"] = _r(room[mid] if len(room) % 2 else (room[mid - 1] + room[mid]) / 2)
    return _drop_none(out)


def zone_config(ctx):
    """The grower's settings for the zone: what the controller put in ctx.brain, plus the engine's targets today."""
    out = dict((getattr(ctx, "brain", None) or {}).get("zone_config") or {})
    p = ctx.params
    if ctx.plants:
        out.setdefault("plants", ctx.plants)
    if p is not None:
        out.update(p2_shot_size_pct_of_substrate=_r(p.p2_shot_size), p1_first_shot_pct_of_substrate=_r(p.p1_initial),
                   p1_max_shots=p.p1_max_shots, p1_min_shots=p.p1_min_shots, p2_ec_target_ms_cm=_r(p.ec_target_p2))
    return _drop_none(out)


def stage_block(ctx):
    """Today's place on the install's stage arc in one paragraph: the stage judge's `stage_today` and more, with the
    dryback band converted to this zone's own peak. Unknown when there is no flower start or no arc in force."""
    brain = getattr(ctx, "brain", None) or {}
    arc = brain.get("arc") or "the install's"
    mode = f" The grower's steering mode for this zone: {ctx.steering}." if ctx.steering else ""
    if getattr(ctx, "cultivar", None):
        mode += f" The cultivar in this zone, as the grower labels it: {ctx.cultivar}."
    if brain.get("arc_note"):
        return f"unknown: {brain['arc_note']}{mode}"
    if ctx.flower_day is None:
        return f"unknown: no flower start is set for this room.{mode}"
    st = ctx.stage
    if not st:
        return f"flower day {ctx.flower_day} of about {ctx.flower_days}: outside the {arc} arc's days.{mode}"
    lo, hi = st["days"]
    dlo, dhi = st["dryback_points"]
    peak = getattr(ctx.snap, "peak_vwc", None)
    rel = (f", which is about {dlo / peak * 100:.0f}-{dhi / peak * 100:.0f} % of this zone's peak"
           if peak and peak > 0 else "")
    dryback = f"{dlo:g}-{dhi:g} points{rel}"
    if (brain.get("zone_config") or {}).get("substrate", "generic") == "generic":
        vendor = st.get("dryback_relative_vendor")
        dryback = (f"{vendor[0]:g}-{vendor[1]:g}% of peak (vendor starting band)" if vendor else
                   "unknown for an uncalibrated generic substrate; compare the zone's repeated observations")
    elo, ehi = st["pore_ec_range"]
    rlo, rhi = st["runoff_pct"]
    return (f"flower day {ctx.flower_day} of about {ctx.flower_days}: {st['stage']} (days {lo}-{hi}) on the {arc} "
            f"arc; the arc steers {st['steering']} here, with an overnight dryback of {dryback}; "
            f"pore EC {elo:g}-{ehi:g}; runoff {rlo:g}-{rhi:g} %; the stage moves on when {st['move_on_when']}.{mode}")
