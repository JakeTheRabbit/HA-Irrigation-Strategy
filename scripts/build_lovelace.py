#!/usr/bin/env python3
"""Generate a native Home Assistant Lovelace dashboard for crop steering.

Zone-count-driven (works for ANY configured zone count, 1-24) and free of facility-
specific entity ids: it covers every ``crop_steering_<prefix>*`` entity the integration
created, plus any extra probe/hardware entities YOU opt in via env. Nothing here assumes
the original developer's hardware names, and the live-computed verdict / exception centre
loops over the zones actually present — not a hardcoded 1-3.

Run:  HA_TOKEN=... python scripts/build_lovelace.py

Optional env:
  HA_BASE                  HA URL (default http://homeassistant.local:8123)
  CROP_STEERING_PREFIX     room prefix for a per-room dashboard, e.g. "veg_"
                           (default "" = the default/un-prefixed room)
  CROP_STEERING_RAW_PROBES JSON {"1": ["sensor.vwc","sensor.ec"], ...} to show the raw
                           fusion inputs per zone (default: none — portable installs
                           read the integration's fused sensors instead)
  CROP_STEERING_RELATED    JSON ["sensor.x", ...] extra related entities to include
"""
import json
import os
import re
import sys
import urllib.request

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")


class Lit(str):
    pass


yaml.add_representer(
    Lit, lambda d, x: d.represent_scalar("tag:yaml.org,2002:str", x, style="|")
)


def pull(base, tok):
    req = urllib.request.Request(
        base + "/api/states", headers={"Authorization": "Bearer " + tok}
    )
    return [e["entity_id"] for e in json.load(urllib.request.urlopen(req, timeout=25))]


def _zone_jinja(zones):
    """Render the detected zone list as a Jinja list literal, e.g. [1,2,3,4]."""
    return "[" + ",".join(str(z) for z in (zones or [1])) + "]"


def build_dashboard(all_ids, prefix="", raw=None, related=None):
    """Pure: build the dashboard dict from the entity-id list. `prefix` selects a room
    ("" = default). No network, no globals — unit-testable with any entity set."""
    raw = {int(k): v for k, v in (raw or {}).items()}
    P = prefix
    csp = f"crop_steering_{P}"
    cs = sorted(e for e in all_ids if f".{csp}" in e)
    zones = sorted(
        {
            int(m.group(1))
            for e in cs
            for m in [re.search(r"_zone_(\d+)(?:_|$)", e)]
            if m
        }
    )
    related = [e for e in (related or []) if e in all_ids]
    ZL = _zone_jinja(zones)

    def sc(dom, suffix):
        return f"{dom}.{csp}{suffix}"

    def of(dom, *, zone=None, glob=False):
        out = []
        for e in cs:
            if not e.startswith(f"{dom}.{csp}"):
                continue
            m = re.search(r"_zone_(\d+)(?:_|$)", e)
            if zone is not None:
                if m and int(m.group(1)) == zone:
                    out.append(e)
            elif glob:
                if not m:
                    out.append(e)
            else:
                out.append(e)
        return sorted(out)

    def nice(e, z=None):
        s = e.split(csp, 1)[1] if csp in e else e.split(".", 1)[1]
        if z is not None:
            s = s.replace(f"zone_{z}_", "")
        return s.replace("_", " ").title() or e

    def ent_card(title, ids, icon=None):
        c = {
            "type": "entities",
            "title": title,
            "state_color": True,
            "entities": [{"entity": e, "name": nice(e)} for e in ids if e in all_ids],
        }
        if icon:
            c["icon"] = icon
        return c

    # ---------- decision markdown (Jinja, computed live in HA) ----------
    VERDICT = Lit(
        r"""{% set h = states('"""
        + sc("sensor", "sensor_health")
        + r"""')|float(100) %}
{% set armed = is_state('"""
        + sc("switch", "system_enabled")
        + r"""','on') and is_state('"""
        + sc("switch", "auto_irrigation_enabled")
        + r"""','on') %}
{% set safe = is_state('"""
        + sc("sensor", "system_safety_status")
        + r"""','safe') %}
{% set ecmax = states('"""
        + sc("number", "irrigation_ec_max")
        + r"""')|float(3.5) %}
{% set ns = namespace(t1=0,t2=0) %}
{% if not safe %}{% set ns.t1 = ns.t1+1 %}{% endif %}
{% if h < 40 %}{% set ns.t1 = ns.t1+1 %}{% endif %}
{% for z in """
        + ZL
        + r""" %}{% set ec = states('sensor."""
        + csp
        + r"""zone_'~z~'_ec')|float(0) %}
{% set vwc = states('sensor."""
        + csp
        + r"""zone_'~z~'_vwc')|float(0) %}
{% set fl = states('number."""
        + csp
        + r"""zone_'~z~'_p2_vwc_threshold')|float(0) %}
{% if ec > ecmax %}{% set ns.t2 = ns.t2+1 %}{% endif %}
{% if vwc < fl %}{% set ns.t2 = ns.t2+1 %}{% endif %}{% endfor %}
{% if not armed %}{% set ns.t2 = ns.t2+1 %}{% endif %}
{% set v = 'INTERVENE' if (ns.t1>0 or h<40 or not safe) else ('WATCH' if (ns.t2>0 or not armed) else 'SAFE') %}
{% set c = '#f87171' if v=='INTERVENE' else ('#fbbf24' if v=='WATCH' else '#34d399') %}
<h1 style="margin:0;color:{{c}}">{{ v }}</h1>

**{{ states('"""
        + sc("sensor", "app_current_phase")
        + r"""') }}** &middot; {{ ns.t1+ns.t2 }} item(s) need attention

<font color="{{ '#34d399' if armed else '#fbbf24' }}">&#9679; ARM {{ 'ARMED' if armed else 'DISARMED' }}</font> &nbsp;
<font color="{{ '#34d399' if safe else '#f87171' }}">&#9679; SAFETY {{ 'OK' if safe else 'FAULT' }}</font> &nbsp;
<font color="{{ '#34d399' if h>=80 else ('#fbbf24' if h>=40 else '#f87171') }}">&#9679; DATA {{ h|round }}%</font>

<font color="#5d6b88">decision: {{ states('"""
        + sc("sensor", "current_decision")
        + r"""') }}</font>"""
    )

    EXC = Lit(
        r"""### What needs attention now
{% set ecmax = states('"""
        + sc("number", "irrigation_ec_max")
        + r"""')|float(3.5) %}
{% set fc = states('"""
        + sc("number", "field_capacity")
        + r"""')|float(60) %}
{% set armed = is_state('"""
        + sc("switch", "system_enabled")
        + r"""','on') and is_state('"""
        + sc("switch", "auto_irrigation_enabled")
        + r"""','on') %}
{% set ns = namespace(rows=[], ecs=[]) %}
{% if not is_state('"""
        + sc("sensor", "system_safety_status")
        + r"""','safe') %}{% set ns.rows = ns.rows + ['&#128308; **Safety fault** &mdash; engine protective state &middot; *inspect guardrails*'] %}{% endif %}
{% if states('"""
        + sc("sensor", "sensor_health")
        + r"""')|float(100) < 40 %}{% set ns.rows = ns.rows + ['&#128308; **Sensor health low** &mdash; steering on degraded data &middot; *hand-verify with a meter*'] %}{% endif %}
{% for z in """
        + ZL
        + r""" %}{% set ec = states('sensor."""
        + csp
        + r"""zone_'~z~'_ec')|float(0) %}
{% set vwc = states('sensor."""
        + csp
        + r"""zone_'~z~'_vwc')|float(0) %}
{% set fl = states('number."""
        + csp
        + r"""zone_'~z~'_p2_vwc_threshold')|float(0) %}
{% set ns.ecs = ns.ecs + [ec] %}
{% if ec > ecmax %}{% set ns.rows = ns.rows + ['&#128992; **Z'~z~' EC '~ec~' &gt; max '~ecmax~'** &mdash; salt stacking &middot; *flush*'] %}{% endif %}
{% if vwc < fl and vwc > 0 %}{% set ns.rows = ns.rows + ['&#128992; **Z'~z~' VWC '~vwc~' &lt; floor '~fl~'** &mdash; under-watered &middot; *why no shot?*'] %}{% endif %}
{% if vwc > fc %}{% set ns.rows = ns.rows + ['&#128992; **Z'~z~' VWC '~vwc~' &gt; FC '~fc~'** &mdash; over-saturated'] %}{% endif %}
{% if is_state('switch."""
        + csp
        + r"""zone_'~z~'_manual_override','on') %}{% set ns.rows = ns.rows + ['&#9898; **Z'~z~' manual override ON** &mdash; AI blocked'] %}{% endif %}
{% if is_state('switch."""
        + csp
        + r"""zone_'~z~'_enabled','off') %}{% set ns.rows = ns.rows + ['&#9898; **Z'~z~' disabled** &mdash; no water'] %}{% endif %}{% endfor %}
{% if not armed %}{% set ns.rows = ns.rows + ['&#128992; **System DISARMED** &mdash; watchdog only &middot; *arm when ready*'] %}{% endif %}
{% if ns.ecs|length > 1 and (ns.ecs|max - ns.ecs|min) > 1.0 %}{% set ns.rows = ns.rows + ['&#128993; **Zone EC spread '~(ns.ecs|max - ns.ecs|min)|round(1)~'** &mdash; zones disagree &middot; *distrust room-average EC*'] %}{% endif %}
{% if ns.rows|length == 0 %}&#9989; **Nothing needs attention** &mdash; every zone on strategy, within limits.{% else %}{% for r in ns.rows %}{{ r }}
{% endfor %}{% endif %}"""
    )

    TRUST = Lit(
        r"""{% set h = states('"""
        + sc("sensor", "sensor_health")
        + r"""')|float(100) %}
{% set fc = states('"""
        + sc("sensor", "sensor_fusion_confidence")
        + r"""')|float(1) %}
{% set v = 'UNTRUSTED' if h<40 else ('DEGRADED' if (h<80 or fc<0.6) else 'OK') %}
{% set c = '#f87171' if v=='UNTRUSTED' else ('#fbbf24' if v=='DEGRADED' else '#34d399') %}
**<font color="{{c}}">DATA TRUST: {{ v }}</font>** &middot; sensor health {{ h|round }}% &middot; fusion conf {{ fc|round(2) }} &middot; AUTO {{ 'ON' if is_state('"""
        + sc("switch", "auto_irrigation_enabled")
        + r"""','on') else 'OFF' }}
{% if v=='UNTRUSTED' %}<font color="#f87171">Bands & gauges may be unreliable &mdash; verify probes before acting.</font>{% endif %}"""
    )

    def zone_dev(z):
        probe = ""
        if z in raw and len(raw[z]) == 2:
            probe = (
                r" &middot; probe {{ states('"
                + raw[z][0]
                + r"') }} / {{ states('"
                + raw[z][1]
                + r"') }}"
            )
        t = (
            r"""{% set vwc = states('sensor."""
            + csp
            + r"""zone_ZZ_vwc')|float(0) %}
{% set ec = states('sensor."""
            + csp
            + r"""zone_ZZ_ec')|float(0) %}
{% set fl = states('number."""
            + csp
            + r"""zone_ZZ_p2_vwc_threshold')|float(0) %}
{% set fc = states('number."""
            + csp
            + r"""field_capacity')|float(60) %}
{% set tgt = states('number."""
            + csp
            + r"""zone_ZZ_p1_target_vwc')|float(0) %}
{% set ecmax = states('number."""
            + csp
            + r"""irrigation_ec_max')|float(3.5) %}
{% set vc = '#fbbf24' if vwc<fl else ('#60a5fa' if vwc>fc else '#34d399') %}
{% set ecc = '#f87171' if ec>ecmax else '#34d399' %}
#### Zone ZZ &middot; <font color="#5d6b88">{{ states('sensor."""
            + csp
            + r"""zone_ZZ_status') }}</font>
<font color="{{vc}}">**VWC {{ vwc }}%**</font> {% if vwc<fl %}({{ (fl-vwc)|round(1) }} below floor {{fl}}){% elif vwc>fc %}({{ (vwc-fc)|round(1) }} above FC){% else %}(in band, floor {{fl}}-FC {{fc}}, target {{tgt}}){% endif %} &nbsp; <font color="{{ecc}}">**EC {{ ec }}**</font> {% if ec>ecmax %}**OVER MAX**{% endif %}"""
            + probe
        )
        return Lit(t.replace("ZZ", str(z)))

    GA = {"green": 40, "yellow": 62, "red": 72}
    EA = {"green": 0, "yellow": 6, "red": 8}
    views = []

    # ---- View 1: Triage ----
    v1 = {
        "title": "Triage",
        "path": "triage",
        "icon": "mdi:alert-decagram",
        "cards": [],
    }
    v1["cards"].append({"type": "markdown", "content": VERDICT})
    v1["cards"].append({"type": "markdown", "content": TRUST})
    v1["cards"].append({"type": "markdown", "content": EXC})
    v1["cards"].append(
        {
            "type": "conditional",
            "conditions": [
                {
                    "entity": sc("switch", f"zone_{(zones or [1])[0]}_manual_override"),
                    "state": "on",
                }
            ],
            "card": {
                "type": "markdown",
                "content": "## &#9888; Manual override active — AI irrigation blocked on one or more zones (see Control).",
            },
        }
    )
    v1["cards"].append(
        ent_card(
            "Arm / Modes",
            [
                sc("switch", "system_enabled"),
                sc("switch", "auto_irrigation_enabled"),
                sc("select", "steering_mode"),
                sc("select", "growth_stage"),
                sc("select", "irrigation_phase"),
            ],
            icon="mdi:cog",
        )
    )
    views.append(v1)

    # ---- View 2: Steering Trace ----
    v2 = {
        "title": "Steering Trace",
        "path": "trace",
        "icon": "mdi:chart-line",
        "cards": [],
    }
    v2["cards"].append(
        {
            "type": "history-graph",
            "title": "VWC — all zones (24h)",
            "hours_to_show": 24,
            "entities": [sc("sensor", f"zone_{z}_vwc") for z in zones],
        }
    )
    v2["cards"].append(
        {
            "type": "history-graph",
            "title": "Pore EC — all zones (24h)",
            "hours_to_show": 24,
            "entities": [sc("sensor", f"zone_{z}_ec") for z in zones],
        }
    )
    v2["cards"].append(
        {
            "type": "history-graph",
            "title": "Phase timeline (24h)",
            "hours_to_show": 24,
            "entities": [sc("sensor", f"zone_{z}_phase") for z in zones],
        }
    )
    views.append(v2)

    # ---- View 3: Zones (deviation + gauges) ----
    v3 = {"title": "Zones", "path": "zones", "icon": "mdi:sprout", "cards": []}
    for z in zones:
        v3["cards"].append({"type": "markdown", "content": zone_dev(z)})
        v3["cards"].append(
            {
                "type": "horizontal-stack",
                "cards": [
                    {
                        "type": "gauge",
                        "entity": sc("sensor", f"zone_{z}_vwc"),
                        "name": f"Z{z} VWC",
                        "min": 0,
                        "max": 100,
                        "needle": True,
                        "severity": GA,
                    },
                    {
                        "type": "gauge",
                        "entity": sc("sensor", f"zone_{z}_ec"),
                        "name": f"Z{z} EC",
                        "min": 0,
                        "max": 12,
                        "needle": True,
                        "severity": EA,
                    },
                ],
            }
        )
    if raw:
        v3["cards"].append(
            ent_card(
                "Raw probes (fusion inputs)",
                [v for z in zones if z in raw for v in raw[z]],
                icon="mdi:radar",
            )
        )
    views.append(v3)

    # ---- View 4: Control (numbers / switches / selects) ----
    v4 = {
        "title": "Control",
        "path": "control",
        "icon": "mdi:tune-variant",
        "cards": [],
    }
    buckets = [
        ("P0", lambda s: s.startswith("p0_")),
        ("P1", lambda s: s.startswith("p1_")),
        ("P2", lambda s: s.startswith("p2_")),
        ("P3", lambda s: s.startswith("p3_")),
        ("EC Targets", lambda s: s.startswith("ec_target")),
        (
            "Substrate & Schedule",
            lambda s: any(
                k in s
                for k in (
                    "substrate",
                    "dripper",
                    "field_capacity",
                    "lights_",
                    "dryback_target",
                )
            ),
        ),
        (
            "Safety Limits",
            lambda s: any(
                k in s
                for k in (
                    "irrigation_ec",
                    "irrigation_ph",
                    "maximum_ec",
                    "blocked_dripper",
                )
            ),
        ),
    ]
    gnums = of("number", glob=True)
    used = set()
    for title, pred in buckets:
        grp = [e for e in gnums if pred(e.split(csp, 1)[1]) and e not in used]
        if grp:
            v4["cards"].append(ent_card("Global · " + title, grp))
            used.update(grp)
    leftover = [e for e in gnums if e not in used]
    if leftover:
        v4["cards"].append(ent_card("Global · Other", leftover))
    v4["cards"].append(
        ent_card("System switches", of("switch", glob=True), icon="mdi:toggle-switch")
    )
    v4["cards"].append(
        ent_card(
            "System modes", of("select", glob=True), icon="mdi:format-list-bulleted"
        )
    )
    for z in zones:
        zn = of("number", zone=z) + of("switch", zone=z) + of("select", zone=z)
        if zn:
            v4["cards"].append(
                ent_card(
                    f"Zone {z} · per-zone overrides & controls",
                    zn,
                    icon="mdi:sprout-outline",
                )
            )
    views.append(v4)

    # ---- View 5: Sensors & Trust ----
    v5 = {
        "title": "Sensors & Trust",
        "path": "sensors",
        "icon": "mdi:stethoscope",
        "cards": [],
    }
    v5["cards"].append({"type": "markdown", "content": TRUST})
    sys_sens = of("sensor", glob=True)
    hb = [
        e
        for e in sys_sens
        if any(
            k in e
            for k in (
                "health",
                "safety",
                "heartbeat",
                "uptime",
                "fusion",
                "accuracy",
                "confidence",
            )
        )
    ]
    rest = [e for e in sys_sens if e not in hb]
    v5["cards"].append(ent_card("Health & trust", hb, icon="mdi:heart-pulse"))
    v5["cards"].append(ent_card("System sensors", rest, icon="mdi:gauge"))
    for z in zones:
        v5["cards"].append(
            ent_card(f"Zone {z} sensors", of("sensor", zone=z), icon="mdi:sprout")
        )
    if related:
        v5["cards"].append(
            ent_card(
                "Related — your probes / water / climate / hardware",
                related,
                icon="mdi:hydraulic-oil-level",
            )
        )
    views.append(v5)

    # ---- View 6: Reference — every crop_steering entity (coverage guarantee) ----
    v6 = {
        "title": "All Entities",
        "path": "all",
        "icon": "mdi:format-list-checkbox",
        "cards": [
            {
                "type": "markdown",
                "content": "## Complete entity reference\nEvery crop_steering entity for this room, guaranteed present.",
            }
        ],
    }
    for dom in ("number", "switch", "select", "sensor"):
        ids = of(dom)
        if ids:
            v6["cards"].append(ent_card(f"All {dom} ({len(ids)})", ids))
    placed = set(
        re.findall(
            r"(?:number|switch|select|sensor|binary_sensor)\.[a-z0-9_]+",
            json.dumps(views + [v6]),
        )
    )
    strag = [e for e in cs if e not in placed]
    if strag:
        v6["cards"].append(ent_card(f"Uncategorised ({len(strag)})", strag))
    views.append(v6)

    room = P.rstrip("_") or "default"
    return (
        {"title": f"Crop Steering ({room})" if P else "Crop Steering", "views": views},
        cs,
        zones,
    )


def main():
    base = os.environ.get("HA_BASE", "http://homeassistant.local:8123")
    tok = os.environ.get("HA_TOKEN", "")
    if not tok:
        sys.exit("set HA_TOKEN=<long-lived token>")
    prefix = os.environ.get("CROP_STEERING_PREFIX", "")
    raw = json.loads(os.environ.get("CROP_STEERING_RAW_PROBES", "{}"))
    related = json.loads(os.environ.get("CROP_STEERING_RELATED", "[]"))
    all_ids = pull(base, tok)
    dash, cs, zones = build_dashboard(all_ids, prefix=prefix, raw=raw, related=related)
    print(f"// {len(cs)} crop_steering entities, zones={zones}", file=sys.stderr)
    out = (
        "# Crop Steering — native Home Assistant dashboard (auto-generated)\n"
        "# Import: Settings -> Dashboards -> + Add Dashboard -> open it -> 3-dot menu\n"
        "#   -> Edit dashboard -> 3-dot menu -> Raw configuration editor -> paste this file.\n"
        "# Zone-count-driven; covers every crop_steering entity. Regenerate: scripts/build_lovelace.py\n"
    )
    out += yaml.dump(
        dash, sort_keys=False, default_flow_style=False, allow_unicode=True, width=1000
    )
    suffix = f"_{prefix.rstrip('_')}" if prefix else ""
    dest = os.path.join(
        os.path.dirname(__file__), "..", f"crop_steering_lovelace{suffix}.yaml"
    )
    open(os.path.abspath(dest), "w", encoding="utf-8", newline="\n").write(out)
    print(
        f"// wrote {os.path.abspath(dest)} ({len(out)} bytes, {len(dash['views'])} views)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
