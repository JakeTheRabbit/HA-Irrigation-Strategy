#!/usr/bin/env python3
"""Generate a native Home Assistant Lovelace dashboard for crop steering.

Same decision-control design as the standalone HTML (Strategy -> state -> deviation ->
cause -> action -> verify), built from NATIVE cards: markdown+Jinja compute the live
verdict / exception centre / trust strip; gauges carry target-band severity; and grouped
entities cards guarantee EVERY crop_steering entity (+ probes/water/climate/hardware) is
present. Paste the output into HA: Settings -> Dashboards -> + Add -> (3-dot) Edit raw config.

Run:  HA_TOKEN=... python scripts/build_lovelace.py
"""
import json
import os
import re
import sys
import urllib.request

BASE = os.environ.get("HA_BASE", "http://homeassistant.local:8123") + "/api"
TOK = os.environ.get("HA_TOKEN", "")
try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")


class Lit(str):
    pass
yaml.add_representer(Lit, lambda d, x: d.represent_scalar("tag:yaml.org,2002:str", x, style="|"))


def pull():
    req = urllib.request.Request(BASE + "/states", headers={"Authorization": "Bearer " + TOK})
    return json.load(urllib.request.urlopen(req, timeout=25))

ALL = [e["entity_id"] for e in pull()]
CS = sorted(e for e in ALL if "crop_steering" in e)
ZONES = sorted({int(m.group(1)) for e in CS for m in [re.search(r"_zone_(\d+)_", e)] if m})
RAW = {1: ("sensor.f2_row_1_vwc", "sensor.f2_row_1_pwec"), 2: ("sensor.veg_sdi12_vwc_2", "sensor.veg_sdi12_ec_2"), 3: ("sensor.veg_sdi12_vwc", "sensor.veg_sdi12_ec")}
RELATED = [v for z in RAW for v in RAW[z]] + [
    "sensor.aquaponics_kit_f4f618_ph", "sensor.atlas_legacy_1_ec",
    "sensor.veg_scd41_top_temperature_scd41", "sensor.veg_scd41_top_humidity_scd41",
    "sensor.f2_vwc_dryback_rate", "sensor.f2_ec_trend", "sensor.tank_percentage_full",
    "input_boolean.nutrient_dosing_active", "switch.veg_main_pump",
    "switch.espoe_irrigation_relay_2_3", "switch.f2_row1", "switch.f2_row2", "switch.f2_row3"]
RELATED = [e for e in RELATED if e in ALL]
print(f"// {len(CS)} crop_steering + {len(RELATED)} related, zones={ZONES}", file=sys.stderr)

def of(dom, *, zone=None, glob=False):
    out = []
    for e in CS:
        if not e.startswith(dom + ".crop_steering_"):
            continue
        m = re.search(r"_zone_(\d+)_", e)
        if zone is not None:
            if m and int(m.group(1)) == zone: out.append(e)
        elif glob:
            if not m: out.append(e)
        else: out.append(e)
    return sorted(out)

def nice(e, z=None):
    s = e.split("crop_steering_", 1)[1] if "crop_steering_" in e else e.split(".", 1)[1]
    if z is not None: s = s.replace(f"zone_{z}_", "")
    return s.replace("_", " ").title()

def ent_card(title, ids, icon=None):
    c = {"type": "entities", "title": title, "state_color": True,
         "entities": [{"entity": e, "name": nice(e)} for e in ids if e in ALL]}
    if icon: c["icon"] = icon
    return c

# ---------- decision markdown (Jinja, computed live in HA) ----------
VERDICT = Lit(r"""{% set h = states('sensor.crop_steering_sensor_health')|float(100) %}
{% set armed = is_state('switch.crop_steering_system_enabled','on') and is_state('switch.crop_steering_auto_irrigation_enabled','on') %}
{% set safe = is_state('sensor.crop_steering_system_safety_status','safe') %}
{% set ecmax = states('number.crop_steering_irrigation_ec_max')|float(3.5) %}
{% set ns = namespace(t1=0,t2=0) %}
{% if not safe %}{% set ns.t1 = ns.t1+1 %}{% endif %}
{% if h < 40 %}{% set ns.t1 = ns.t1+1 %}{% endif %}
{% for z in [1,2,3] %}{% set ec = states('sensor.crop_steering_zone_'~z~'_ec')|float(0) %}
{% set vwc = states('sensor.crop_steering_zone_'~z~'_vwc')|float(0) %}
{% set fl = states('number.crop_steering_zone_'~z~'_p2_vwc_threshold')|float(0) %}
{% if ec > ecmax %}{% set ns.t2 = ns.t2+1 %}{% endif %}
{% if vwc < fl %}{% set ns.t2 = ns.t2+1 %}{% endif %}{% endfor %}
{% if not armed %}{% set ns.t2 = ns.t2+1 %}{% endif %}
{% set v = 'INTERVENE' if (ns.t1>0 or h<40 or not safe) else ('WATCH' if (ns.t2>0 or not armed) else 'SAFE') %}
{% set c = '#f87171' if v=='INTERVENE' else ('#fbbf24' if v=='WATCH' else '#34d399') %}
<h1 style="margin:0;color:{{c}}">{{ v }}</h1>

**{{ states('sensor.crop_steering_app_current_phase') }}** &middot; {{ ns.t1+ns.t2 }} item(s) need attention

<font color="{{ '#34d399' if armed else '#fbbf24' }}">&#9679; ARM {{ 'ARMED' if armed else 'DISARMED' }}</font> &nbsp;
<font color="{{ '#34d399' if safe else '#f87171' }}">&#9679; SAFETY {{ 'OK' if safe else 'FAULT' }}</font> &nbsp;
<font color="{{ '#34d399' if h>=80 else ('#fbbf24' if h>=40 else '#f87171') }}">&#9679; DATA {{ h|round }}%</font>

<font color="#5d6b88">{{ state_attr('sensor.crop_steering_app_status','message') }} &middot; decision: {{ states('sensor.crop_steering_current_decision') }}</font>""")

EXC = Lit(r"""### What needs attention now
{% set ecmax = states('number.crop_steering_irrigation_ec_max')|float(3.5) %}
{% set fc = states('number.crop_steering_field_capacity')|float(60) %}
{% set armed = is_state('switch.crop_steering_system_enabled','on') and is_state('switch.crop_steering_auto_irrigation_enabled','on') %}
{% set ns = namespace(rows=[]) %}
{% if not is_state('sensor.crop_steering_system_safety_status','safe') %}{% set ns.rows = ns.rows + ['&#128308; **Safety fault** &mdash; engine protective state &middot; *inspect guardrails*'] %}{% endif %}
{% if states('sensor.crop_steering_sensor_health')|float(100) < 40 %}{% set ns.rows = ns.rows + ['&#128308; **Sensor health low** &mdash; steering on degraded data &middot; *hand-verify with a meter*'] %}{% endif %}
{% for z in [1,2,3] %}{% set ec = states('sensor.crop_steering_zone_'~z~'_ec')|float(0) %}
{% set vwc = states('sensor.crop_steering_zone_'~z~'_vwc')|float(0) %}
{% set fl = states('number.crop_steering_zone_'~z~'_p2_vwc_threshold')|float(0) %}
{% set ph = states('sensor.crop_steering_zone_'~z~'_phase') %}
{% set pn = '0' if 'P0' in ph else ('1' if 'P1' in ph else ('3' if 'P3' in ph else '2')) %}
{% set tg = states('number.crop_steering_zone_'~z~'_ec_target_veg_p'~pn)|float(3.2) %}
{% if ec > ecmax %}{% set ns.rows = ns.rows + ['&#128992; **Z'~z~' EC '~ec~' &gt; max '~ecmax~'** &mdash; salt stacking &middot; *flush; target '~tg~'*'] %}{% endif %}
{% if vwc < fl and vwc > 0 %}{% set ns.rows = ns.rows + ['&#128992; **Z'~z~' VWC '~vwc~' &lt; floor '~fl~'** &mdash; under-watered &middot; *why no shot?*'] %}{% endif %}
{% if vwc > fc %}{% set ns.rows = ns.rows + ['&#128992; **Z'~z~' VWC '~vwc~' &gt; FC '~fc~'** &mdash; over-saturated'] %}{% endif %}{% endfor %}
{% if not armed %}{% set ns.rows = ns.rows + ['&#128992; **System DISARMED** &mdash; watchdog only &middot; *arm when ready*'] %}{% endif %}
{% set gs = states('select.crop_steering_growth_stage')|lower %}{% set gp = states('input_select.growth_phase') %}{% set np = states('input_select.nutrient_phase') %}
{% if gp not in ['unknown','unavailable'] and not ('veg' in gs and 'veg' in gp|lower and 'veg' in np|lower) %}{% set ns.rows = ns.rows + ['&#128992; **Strategy selectors disagree** &mdash; '~states('select.crop_steering_growth_stage')~' &middot; '~gp~' &middot; '~np~''] %}{% endif %}
{% for z in [1,2,3] %}{% set ec = states('sensor.crop_steering_zone_'~z~'_ec')|float(0) %}
{% set ph = states('sensor.crop_steering_zone_'~z~'_phase') %}{% set pn = '0' if 'P0' in ph else ('1' if 'P1' in ph else ('3' if 'P3' in ph else '2')) %}
{% set tg = states('number.crop_steering_zone_'~z~'_ec_target_veg_p'~pn)|float(3.2) %}
{% if ec > 0 and ec < tg*0.8 and ec <= ecmax %}{% set ns.rows = ns.rows + ['&#128993; **Z'~z~' EC '~ec~' lean** (target '~tg~') &middot; *raise feed / lengthen dryback*'] %}{% endif %}
{% if is_state('switch.crop_steering_zone_'~z~'_manual_override','on') %}{% set ns.rows = ns.rows + ['&#9898; **Z'~z~' manual override ON** &mdash; AI blocked'] %}{% endif %}
{% if is_state('switch.crop_steering_zone_'~z~'_enabled','off') %}{% set ns.rows = ns.rows + ['&#9898; **Z'~z~' disabled** &mdash; no water'] %}{% endif %}{% endfor %}
{% set vw = [states('sensor.crop_steering_zone_1_ec')|float(0),states('sensor.crop_steering_zone_2_ec')|float(0),states('sensor.crop_steering_zone_3_ec')|float(0)] %}
{% if (vw|max - vw|min) > 1.0 %}{% set ns.rows = ns.rows + ['&#128993; **Zone EC spread '~(vw|max - vw|min)|round(1)~'** &mdash; zones disagree &middot; *distrust room-average EC*'] %}{% endif %}
{% if ns.rows|length == 0 %}&#9989; **Nothing needs attention** &mdash; every zone on strategy, within limits.{% else %}{% for r in ns.rows %}{{ r }}
{% endfor %}{% endif %}""")

TRUST = Lit(r"""{% set h = states('sensor.crop_steering_sensor_health')|float(100) %}
{% set fc = states('sensor.crop_steering_sensor_fusion_confidence')|float(1) %}
{% set v = 'UNTRUSTED' if h<40 else ('DEGRADED' if (h<80 or fc<0.6) else 'OK') %}
{% set c = '#f87171' if v=='UNTRUSTED' else ('#fbbf24' if v=='DEGRADED' else '#34d399') %}
**<font color="{{c}}">DATA TRUST: {{ v }}</font>** &middot; sensor health {{ h|round }}% &middot; fusion conf {{ fc|round(2) }} &middot; dryback acc {{ states('sensor.crop_steering_dryback_detection_accuracy')|float(0)|round(2) }} &middot; fused VWC {{ states('sensor.crop_steering_fused_vwc') }} / EC {{ states('sensor.crop_steering_fused_ec') }} &middot; AUTO {{ 'ON' if is_state('switch.crop_steering_auto_irrigation_enabled','on') else 'OFF' }}
{% if v=='UNTRUSTED' %}<font color="#f87171">Bands & gauges may be unreliable &mdash; verify probes before acting.</font>{% endif %}""")

def zone_dev(z):
    t = (r"""{% set vwc = states('sensor.crop_steering_zone_ZZ_vwc')|float(0) %}
{% set ec = states('sensor.crop_steering_zone_ZZ_ec')|float(0) %}
{% set fl = states('number.crop_steering_zone_ZZ_p2_vwc_threshold')|float(0) %}
{% set fc = states('number.crop_steering_field_capacity')|float(60) %}
{% set tgt = states('number.crop_steering_zone_ZZ_p1_target_vwc')|float(0) %}
{% set ecmax = states('number.crop_steering_irrigation_ec_max')|float(3.5) %}
{% set vc = '#fbbf24' if vwc<fl else ('#60a5fa' if vwc>fc else '#34d399') %}
{% set ecc = '#f87171' if ec>ecmax else '#34d399' %}
#### Zone ZZ &middot; <font color="#5d6b88">{{ states('sensor.crop_steering_zone_ZZ_status') }}</font>
<font color="{{vc}}">**VWC {{ vwc }}%**</font> {% if vwc<fl %}({{ (fl-vwc)|round(1) }} below floor {{fl}}){% elif vwc>fc %}({{ (vwc-fc)|round(1) }} above FC){% else %}(in band, floor {{fl}}-FC {{fc}}, target {{tgt}}){% endif %} &nbsp; <font color="{{ecc}}">**EC {{ ec }}**</font> {% if ec>ecmax %}**OVER MAX**{% endif %} &middot; probe {{ states('RVWC') }} / {{ states('REC') }}""")
    return Lit(t.replace("ZZ", str(z)).replace("RVWC", RAW[z][0]).replace("REC", RAW[z][1]))

GA = {"green": 40, "yellow": 62, "red": 72}
EA = {"green": 0, "yellow": 6, "red": 8}

views = []

# ---- View 1: Triage ----
v1 = {"title": "Triage", "path": "triage", "icon": "mdi:alert-decagram", "cards": []}
v1["cards"].append({"type": "markdown", "content": VERDICT})
v1["cards"].append({"type": "markdown", "content": TRUST})
v1["cards"].append({"type": "markdown", "content": EXC})
# override banner — conditional
v1["cards"].append({"type": "conditional",
    "conditions": [{"entity": f"switch.crop_steering_zone_{z}_manual_override", "state": "on"} for z in ZONES][:1] or [{"entity": "switch.crop_steering_zone_1_manual_override", "state": "on"}],
    "card": {"type": "markdown", "content": "## &#9888; Manual override active — AI irrigation blocked on one or more zones (see Control)."}})
v1["cards"].append(ent_card("Arm / Modes", [
    "switch.crop_steering_system_enabled", "switch.crop_steering_auto_irrigation_enabled",
    "select.crop_steering_steering_mode", "select.crop_steering_growth_stage",
    "select.crop_steering_irrigation_phase"], icon="mdi:cog"))
views.append(v1)

# ---- View 2: Steering Trace ----
v2 = {"title": "Steering Trace", "path": "trace", "icon": "mdi:chart-line", "cards": []}
vwc_ids = [f"sensor.crop_steering_zone_{z}_vwc" for z in ZONES]
ec_ids = [f"sensor.crop_steering_zone_{z}_ec" for z in ZONES]
v2["cards"].append({"type": "history-graph", "title": "VWC — all zones (24h)", "hours_to_show": 24, "entities": vwc_ids})
v2["cards"].append({"type": "history-graph", "title": "Pore EC — all zones (24h)", "hours_to_show": 24, "entities": ec_ids})
v2["cards"].append({"type": "markdown", "content": Lit(
    "### Dryback\n"
    "Target **{{ states('sensor.crop_steering_dryback_target') }}%** drop-from-peak &middot; "
    "rate {{ states('sensor.f2_vwc_dryback_rate') }} %/h &middot; "
    "detector acc {{ states('sensor.crop_steering_dryback_detection_accuracy')|float(0)|round(2) }}\n\n"
    "<font color=\"#5d6b88\">Engine `dryback_percentage` is offline; the standalone HTML dashboard computes "
    "dryback from history. Per-zone phases:</font> {{ states('sensor.crop_steering_app_current_phase') }}")})
v2["cards"].append({"type": "history-graph", "title": "Phase timeline (24h)", "hours_to_show": 24,
                    "entities": [f"sensor.crop_steering_zone_{z}_phase" for z in ZONES]})
v2["cards"].append({"type": "history-graph", "title": "Daily water (48h)", "hours_to_show": 48,
                    "entities": [f"sensor.crop_steering_zone_{z}_daily_water_usage" for z in ZONES if f"sensor.crop_steering_zone_{z}_daily_water_usage" in CS]})
views.append(v2)

# ---- View 3: Zones (gauges + deviation + raw) ----
v3 = {"title": "Zones", "path": "zones", "icon": "mdi:sprout", "cards": []}
for z in ZONES:
    v3["cards"].append({"type": "markdown", "content": zone_dev(z)})
    v3["cards"].append({"type": "horizontal-stack", "cards": [
        {"type": "gauge", "entity": f"sensor.crop_steering_zone_{z}_vwc", "name": f"Z{z} VWC", "min": 0, "max": 100, "needle": True, "severity": GA},
        {"type": "gauge", "entity": f"sensor.crop_steering_zone_{z}_ec", "name": f"Z{z} EC", "min": 0, "max": 12, "needle": True, "severity": EA}]})
v3["cards"].append({"type": "markdown", "content": Lit(
    "### Sensors & Environment\n"
    "Source pH **{{ states('sensor.aquaponics_kit_f4f618_ph')|float(0)|round(1) }}** &middot; "
    "Source EC **{{ states('sensor.atlas_legacy_1_ec')|float(0)|round(1) }}** &middot; "
    "Room **{{ states('sensor.veg_scd41_top_temperature_scd41')|float(0)|round(1) }}&deg;C** / "
    "**{{ states('sensor.veg_scd41_top_humidity_scd41')|float(0)|round(0) }}%** &middot; "
    "Tank {{ states('sensor.tank_percentage_full') }}%")})
v3["cards"].append(ent_card("Raw probes (fusion inputs)", [RAW[z][i] for z in ZONES for i in (0, 1)], icon="mdi:radar"))
views.append(v3)

# ---- View 4: Control (ALL numbers / switches / selects / input_selects) ----
v4 = {"title": "Control", "path": "control", "icon": "mdi:tune-variant", "cards": []}
buckets = [("P0", lambda s: s.startswith("p0_")), ("P1", lambda s: s.startswith("p1_")),
           ("P2", lambda s: s.startswith("p2_")), ("P3", lambda s: s.startswith("p3_")),
           ("EC Targets", lambda s: s.startswith("ec_target")),
           ("Substrate & Schedule", lambda s: any(k in s for k in ("substrate", "dripper", "field_capacity", "lights_", "dryback_target"))),
           ("Safety Limits", lambda s: any(k in s for k in ("irrigation_ec", "irrigation_ph", "maximum_ec", "blocked_dripper")))]
gnums = of("number", glob=True)
used = set()
for title, pred in buckets:
    grp = [e for e in gnums if pred(e.split("crop_steering_", 1)[1]) and e not in used]
    if grp:
        v4["cards"].append(ent_card("Global · " + title, grp)); used.update(grp)
leftover = [e for e in gnums if e not in used]
if leftover: v4["cards"].append(ent_card("Global · Other", leftover))
v4["cards"].append(ent_card("System switches", of("switch", glob=True), icon="mdi:toggle-switch"))
v4["cards"].append(ent_card("System modes", of("select", glob=True) + of("input_select", glob=True), icon="mdi:format-list-bulleted"))
for z in ZONES:
    zn = of("number", zone=z) + of("switch", zone=z) + of("select", zone=z) + of("input_select", zone=z)
    if zn: v4["cards"].append(ent_card(f"Zone {z} · per-zone overrides & controls", zn, icon="mdi:sprout-outline"))
views.append(v4)

# ---- View 5: Sensors & Trust (ALL sensors) ----
v5 = {"title": "Sensors & Trust", "path": "sensors", "icon": "mdi:stethoscope", "cards": []}
v5["cards"].append({"type": "markdown", "content": TRUST})
sys_sens = of("sensor", glob=True)
hb = [e for e in sys_sens if any(k in e for k in ("health", "safety", "heartbeat", "uptime", "fusion", "accuracy", "confidence"))]
rest = [e for e in sys_sens if e not in hb]
v5["cards"].append(ent_card("Health & trust", hb, icon="mdi:heart-pulse"))
v5["cards"].append(ent_card("System sensors", rest, icon="mdi:gauge"))
for z in ZONES:
    v5["cards"].append(ent_card(f"Zone {z} sensors", of("sensor", zone=z), icon="mdi:sprout"))
v5["cards"].append(ent_card("Related — probes / water / climate / hardware", RELATED, icon="mdi:hydraulic-oil-level"))
views.append(v5)

# ---- View 6: Reference — EVERY entity (coverage guarantee) ----
placed = set(re.findall(r"(?:number|switch|select|sensor|input_select|input_boolean|automation|binary_sensor)\.[a-z0-9_]+", json.dumps(views)))
missing = [e for e in CS if e not in placed]
v6 = {"title": "All Entities", "path": "all", "icon": "mdi:format-list-checkbox", "cards": [
    {"type": "markdown", "content": "## Complete entity reference\nEvery crop_steering entity, guaranteed present. Legacy blueprint automations are listed but **superseded** by the f2-control add-on engine."}]}
for dom in ("number", "switch", "select", "input_select", "sensor"):
    ids = of(dom)
    if ids: v6["cards"].append(ent_card(f"All {dom} ({len(ids)})", ids))
autos = [e for e in CS if e.startswith("automation.")]
if autos: v6["cards"].append(ent_card(f"Legacy automations — superseded ({len(autos)})", autos, icon="mdi:robot-off"))
# any straggler not yet referenced
placed2 = set(re.findall(r"(?:number|switch|select|sensor|input_select|input_boolean|automation|binary_sensor)\.[a-z0-9_]+", json.dumps(views + [v6])))
strag = [e for e in CS if e not in placed2]
if strag: v6["cards"].append(ent_card(f"Uncategorised ({len(strag)})", strag))
views.append(v6)

# coverage report
final = set(re.findall(r"(?:number|switch|select|sensor|input_select|input_boolean|automation|binary_sensor)\.[a-z0-9_]+", json.dumps(views)))
cov = [e for e in CS if e in final]
print(f"// coverage: {len(cov)}/{len(CS)} crop_steering entities; missing {len(CS)-len(cov)}", file=sys.stderr)
if len(cov) != len(CS):
    print("// MISSING:", [e for e in CS if e not in final][:20], file=sys.stderr)

dash = {"title": "F2 Crop Steering", "views": views}
out = ("# F2 Crop Steering — native Home Assistant dashboard (auto-generated)\n"
       "# Import: Settings -> Dashboards -> + Add Dashboard -> open it -> 3-dot menu -> Edit dashboard\n"
       "#   -> 3-dot menu -> Raw configuration editor -> paste this whole file.\n"
       "# Decision-control design (markdown+Jinja compute the live verdict/exceptions/trust).\n"
       "# Covers EVERY crop_steering entity. Regenerate: scripts/build_lovelace.py\n")
out += yaml.dump(dash, sort_keys=False, default_flow_style=False, allow_unicode=True, width=1000)
dest = os.path.join(os.path.dirname(__file__), "..", "crop_steering_lovelace.yaml")
open(os.path.abspath(dest), "w", encoding="utf-8", newline="\n").write(out)
print(f"// wrote {os.path.abspath(dest)} ({len(out)} bytes, {len(views)} views)", file=sys.stderr)
