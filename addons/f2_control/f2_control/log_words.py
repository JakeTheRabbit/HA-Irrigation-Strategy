"""The controller's log in plain words: why a zone changed phase, what a shot is and why, why a zone
is held, and who changed a setting, the way the dashboard says it. Only the log's wording lives here.
What the engine decides, and the texts decide() publishes to Home Assistant, stay the engine's own
(crop_steering_engine.core): these read those texts and say them for a person, and anything they do
not recognise is logged as it is."""

import re

# Each setting's short name, as the dashboard shows it (frontend/src/lib/setting-words.ts, `short`).
# tests/test_log_words.py reads that file and holds the two together.
SETTING_NAMES = {
    "p0_maximum_wait_time": "Latest first shot",
    "p1_target_vwc": "Peak target",
    "p1_initial_shot_size": "First P1 shot",
    "p1_shot_size_increment": "Each P1 shot adds",
    "p1_time_between_shots": "Time between P1 shots",
    "p1_maximum_shots": "Most P1 shots",
    "p2_vwc_threshold": "Re-water point",
    "p2_shot_size": "Maintenance shot",
    "p3_emergency_vwc_threshold": "Rescue floor",
    "p3_emergency_shot_size": "Rescue shot",
    "field_capacity": "Full saturation",
    "max_daily_volume": "Daily water limit",
    "maximum_ec": "Maximum EC",
    "watchdog_hours": "Watchdog interval",
    "min_floor_drown_ceiling": "Daily minimum stops at",
    "min_daily_ml_per_plant": "Daily minimum",
    "p0_additional_dryback": "Extra dryback",
    "sump_power_threshold_w": "Sump pump runs above",
    "irrigation_ec_min": "Feed EC, lowest",
    "irrigation_ec_max": "Feed EC, highest",
    "irrigation_ph_min": "Feed pH, lowest",
    "irrigation_ph_max": "Feed pH, highest",
    "max_shot_duration": "Longest shot",
    "substrate_volume": "Substrate per plant",
    "plant_count": "Plants",
    "drippers_per_plant": "Drippers per plant",
    "dripper_flow_rate": "Dripper flow",
    "lights_on_hour": "Lights on",
    "lights_off_hour": "Lights off",
}
_EC_TARGETS = {"0": "P0 EC target", "1": "P1 EC target", "2": "P2 EC target"}
_DRYBACK = "P3 dryback target"
_MODES = {"veg": "vegetative", "vegetative": "vegetative", "gen": "generative", "generative": "generative"}


def setting_name(key):
    """A setting's short name from its key, a zone's without its "zone_N_": "p2_vwc_threshold" is
    "Re-water point", "ec_target_veg_p1" "P1 EC target (vegetative)". A key nobody has named
    reads as its own words."""
    ec = re.fullmatch(r"ec_target_(?:(veg|gen)_)?p([012])", key)
    if ec:
        name = _EC_TARGETS[ec.group(2)]
        return f"{name} ({_MODES[ec.group(1)]})" if ec.group(1) else name
    dryback = re.fullmatch(r"(?:(vegetative|generative)_)?dryback_target", key)
    if dryback:
        return f"{_DRYBACK} ({_MODES[dryback.group(1)]})" if dryback.group(1) else _DRYBACK
    key = "max_shot_duration" if key == "maximum_shot_duration" else key
    return SETTING_NAMES.get(key) or key.replace("_", " ").capitalize()


def amount(value, unit=""):
    """A value as the dashboard shows it, to at most two decimals, with its unit: "63.3%", "10",
    "15 min", "2.8 mS/cm"."""
    shown = f"{value:.2f}".rstrip("0").rstrip(".")
    shown = "0" if shown == "-0" else shown
    if not unit:
        return shown
    return f"{shown}%" if unit == "%" else f"{shown} {unit}"


def change(name, unit, old, new, who=None):
    """A setting change in one sentence: "Sam raised Most P1 shots to 10 (was 6)"; with nobody
    known, "Most P1 shots raised to 10 (was 6)"."""
    way = "raised" if new > old else "lowered"
    to, was = amount(new, unit), amount(old, unit)
    return f"{who} {way} {name} to {to} (was {was})" if who else f"{name} {way} to {to} (was {was})"


def who(entries, value, people):
    """Who changed a setting to `value`, from its logbook entries (Home Assistant's, oldest first): an
    automation or a script by its name, a user by their person's name. None when that is not known,
    as for a user who is nobody's person."""
    for entry in reversed(entries or []):
        try:
            if float(entry.get("state")) != float(value):
                continue
        except (TypeError, ValueError):
            continue
        kind, name = entry.get("context_event_type"), entry.get("context_name")
        if kind == "automation_triggered":
            return f'Automation "{name}"' if name else "An automation"
        if kind == "script_started":
            return f'Script "{name}"' if name else "A script"
        return people.get(entry.get("context_user_id"))
    return None


# Why a zone changed phase: decide()'s transition texts, said for a person.
_TRANSITIONS = [
    (r"lights-off -> P3", lambda m: "lights off"),
    (r"lights-on -> P0", lambda m: "lights on"),
    (r"new grow-day -> P0 \(missed light edge\)", lambda m: "a new grow-day, its lights-on missed"),
    (
        r"new grow-day -> P0 \(reset\)",
        lambda m: "a new grow-day began before this zone finished the last one",
    ),
    (
        r"P0 bypass VWC (\S+)<=rewater (\S+)",
        lambda m: f"VWC {m[1]}% is at or under the maintenance trigger ({m[2]}%), "
        "no morning dryback needed",
    ),
    (r"P0 dryback done (\S+)%", lambda m: f"the morning dryback reached {m[1]}%"),
    (r"P0 timeout (\S+)min", lambda m: f"the latest first shot came, {m[1]} min into P0"),
    (
        r"P0 stalled: dryback (\S+) pts/h too slow to finish",
        lambda m: f"the morning dryback ({m[1]} points an hour) is too slow to finish before the latest first shot",
    ),
    (
        r"timed P2 end (\S+)h<=(\S+)h to lights-off",
        lambda m: f"P2 ends {m[2]} h before lights-off, as set",
    ),
    (r"P1 max shots (\S+)/(\S+)", lambda m: f"all {m[2]} ramp shots are in"),
    (
        r"P1 full: the last shot raised the peak (\S+) \(< (\S+)\)",
        lambda m: f"the last shot raised the peak only {m[1]} points (under {m[2]}), so the slab is full",
    ),
    (
        r"predictive P3 \(need (\S+)h, (\S+)h to on\)",
        lambda m: f"the overnight dryback needs {m[1]} h and lights-on is {m[2]} h away, "
        "so it starts now",
    ),
]


def transition(text):
    """Why a zone changed phase, from decide()'s reason (its transition comes first)."""
    first = str(text or "").split(" | ")[0]
    for pattern, words in _TRANSITIONS:
        found = re.fullmatch(pattern, first)
        if found:
            return words(found)
    return first


# A shot by the rule that fired it (Reason.kind): what it is, and why, from its text.
_COPY = (r"COPY Z(\d+) \(VWC probe dead\)", lambda m: f"its probe is out, so it follows zone {m[1]}")
_SHOTS = {
    "p1_ramp": (
        "ramp shot",
        r"P1 ramp VWC (\S+)<(\S+)",
        lambda m: f"VWC {m[1]}% under the {m[2]}% peak target",
    ),
    "p1_extra": (
        "extra ramp shot",
        r"P1 extra shot(?: at the target (\S+)|: the last one raised the peak (\S+))",
        lambda m: f"VWC reached the {m[1]}% peak target; one more shot shows whether the slab is full"
        if m[1]
        else f"the last shot still raised the peak {m[2]} points",
    ),
    "p2_topup": (
        "maintenance shot",
        r"P2 top-up VWC (\S+)<(\S+)",
        lambda m: f"VWC {m[1]}% under the {m[2]}% maintenance trigger",
    ),
    "p2_dilute": (
        "dilution shot",
        r"P2 (?:dilute EC (\S+)|flush to EC target (\S+)>(\S+))",
        lambda m: f"EC {m[1]} more than the dilute ratio times the P2 EC target"
        if m[1]
        else f"EC {m[2]} still over the {m[3]} flush target",
    ),
    "p2_timed": (
        "timed shot",
        r"P2 timed shot every (\S+)min \((\S+)min since the last\)",
        lambda m: f"timed P2: one shot every {m[1]} min, {m[2]} min since the last",
    ),
    "p2_rescue": (
        "rescue flush",
        r"P2 rescue flush EC (\S+)",
        lambda m: f"EC {m[1]} within 1 of the maximum",
    ),
    "flush_high_ec": (
        "high-EC flush",
        r"FLUSH high EC (\S+)>=(\S+)",
        lambda m: f"EC {m[1]} at or over the {m[2]} maximum",
    ),
    "p0_ec_flush": (
        "EC flush",
        r"P0 EC flush (\S+)",
        lambda m: f"EC {m[1]} more than 2.5 times the P0 EC target",
    ),
    "p3_emergency": (
        "rescue shot",
        r"P3 emergency VWC (\S+)<(\S+)",
        lambda m: f"VWC {m[1]}% under the {m[2]}% rescue level",
    ),
    "watchdog": (
        "watchdog shot",
        r"WATCHDOG (\S+)h no water \(VWC (\S+)<(\S+)\)( — over the daily budget)?",
        lambda m: f"no water for {m[1]} h and VWC {m[2]}% under the {m[3]}% maintenance trigger"
        + (", past the daily water limit" if m[4] else ""),
    ),
    "min_daily": (
        "daily minimum shot",
        r"MIN-DAILY floor (\S+)<(\S+) of (\S+)L \(guaranteed\)",
        lambda m: f"{m[1]} L in today, under the {m[2]} L due by now of the {m[3]} L daily minimum",
    ),
    "blind_copy": ("copied shot", *_COPY),
    "blind_copy_rescue": ("copied rescue shot", *_COPY),
    "blind_fallback": (
        "timed shot",
        r"FALLBACK schedule \(no live probe\)",
        lambda m: "no probe reads, so it is watered on a timer",
    ),
}
_EC_UNKNOWN = "EC unknown: base VWC watering; salt protection unverified"


def shot(reason):
    """A shot in words: (what it is, why), as "ramp shot", "VWC 61% under the 88% peak target"."""
    text = str(reason or "")
    what, pattern, why = _SHOTS.get(getattr(reason, "kind", None), ("shot", None, None))
    found = re.search(pattern, text) if pattern else None
    said = why(found) if found else "; ".join(_rule(part) for part in _segments(text)) or text
    if _EC_UNKNOWN in text:
        said += "; EC unknown, watering by moisture alone"
    return what, said


# Why the engine holds a zone it would otherwise water.
_HOLDS = [
    (
        r"BLOCK high EC (\S+) — (.+) \(self-clears\)",
        lambda m: f"EC {m[1]} over the maximum and a flush can't bring it down now ({m[2]}), "
        "so nothing runs until one can",
    ),
    (
        r"HOLD high EC (\S+) — flush draining \((\S+)/(\S+)min\)",
        lambda m: f"EC {m[1]} over the maximum; the last flush is draining ({m[2]} of {m[3]} min)",
    ),
    (
        r"BLOCK daily-cap (\S+)/(\S+)L \(budget; emergencies exempt\)",
        lambda m: f"the daily water limit is spent ({m[1]} of {m[2]} L); rescue shots still run",
    ),
    (
        r"SKIP timed P2 shot: VWC (\S+)>=(\S+) \(ceiling\)",
        lambda m: f"timed P2 shot skipped: VWC {m[1]}% at or over its {m[2]}% ceiling",
    ),
    (
        r"probe unreadable (\S+) min: waiting (\S+) min before watering without it",
        lambda m: f"the probe has been unreadable {m[1]} min; watering without it after {m[2]}",
    ),
]


def hold(reason):
    """Why a zone the engine would water is held, or "" when nothing is due: it is simply holding."""
    text = str(reason or "")
    parts = [_rule(part) for part in _segments(text)]
    if _EC_UNKNOWN in text:
        parts.append("EC unknown, watering by moisture alone")
    return "; ".join(parts)


def _segments(text):
    """decide()'s reason in its parts, without the transition (said on its own line) and the EC
    note (said once)."""
    return [
        part
        for part in str(text or "").split(" | ")
        if part and part != _EC_UNKNOWN and not _is_transition(part)
    ]


def _rule(text):
    for pattern, words in _HOLDS:
        found = re.fullmatch(pattern, text)
        if found:
            return words(found)
    return text


def _is_transition(text):
    return any(re.fullmatch(pattern, text) for pattern, _ in _TRANSITIONS)
