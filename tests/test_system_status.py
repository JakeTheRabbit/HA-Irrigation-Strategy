"""System status (system_status.py): each room's mapped entities online or silent, the controller's heartbeat
per room, and the site's health. Driven against a hand-made hass (states, entries, data)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import system_status  # noqa: E402
from custom_components.crop_steering.system_status import (  # noqa: E402
    Ring,
    Tracker,
    card_version,
    median_interval,
    status,
    uptime_pct,
)

DOMAIN = "crop_steering"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def _state(entity_id, value="on", age_s=30, attrs=None, reported_s=None):
    at = NOW - timedelta(seconds=age_s)
    reported = NOW - timedelta(seconds=reported_s) if reported_s is not None else at
    return SimpleNamespace(
        entity_id=entity_id,
        state=value,
        attributes=attrs or {},
        last_updated=at,
        last_changed=at,
        last_reported=reported,
    )


def _room(prefix, zones=3, hardware=None):
    return {
        "room_prefix": prefix,
        "num_zones": zones,
        "hardware": (
            hardware
            if hardware is not None
            else {
                "pump_switch": f"switch.{prefix}pump",
                "main_line_switch": f"switch.{prefix}main",
                "feed_ec_sensor": f"sensor.{prefix}feed_ec",
                "feed_ph_sensor": f"sensor.{prefix}feed_ph",
            }
        ),
        "zones": {
            str(z): {
                "name": f"Zone {z}",
                "zone_switch": f"switch.{prefix}valve_{z}",
                "vwc_sensors": [f"sensor.{prefix}vwc_{z}"],
            }
            for z in range(1, zones + 1)
        },
    }


def _hass(rooms: dict, states=()):
    """rooms: {entry_id: config}. Every mapped entity is online unless `states` says otherwise."""
    entries = [
        SimpleNamespace(
            entry_id=eid, data={"room_prefix": cfg["room_prefix"]}, options={}
        )
        for eid, cfg in rooms.items()
    ]
    table = {}
    for cfg in rooms.values():
        hw = cfg["hardware"]
        for key in ("pump_switch", "main_line_switch"):
            if hw.get(key):
                table[hw[key]] = _state(hw[key], "off")
        for key in ("feed_ec_sensor", "feed_ph_sensor"):
            if hw.get(key):
                table[hw[key]] = _state(hw[key], "5.8")
        for zone in cfg["zones"].values():
            table[zone["zone_switch"]] = _state(zone["zone_switch"], "off")
            for probe in zone["vwc_sensors"]:
                table[probe] = _state(probe, "41")
    for state in states:
        table[state.entity_id] = state
    hass = SimpleNamespace(
        states=SimpleNamespace(get=table.get),
        data={DOMAIN: {eid: cfg for eid, cfg in rooms.items()}},
        config_entries=SimpleNamespace(async_entries=lambda domain: entries),
        config=SimpleNamespace(components=set()),
    )
    return hass


def _beat(prefix, age_s, **attrs):
    return _state(f"sensor.crop_steering_{prefix}ai_heartbeat", "ok", age_s, attrs)


def test_one_silent_probe_drops_pct_online():
    hass = _hass({"e1": _room("f2_")}, [_state("sensor.f2_vwc_2", "unavailable")])
    out = status(hass, NOW)
    (room,) = out["rooms"]
    assert room["room_id"] == "room:f2_"
    assert len(room["entities"]) == 10
    assert room["pct_online"] == 90.0
    bad = [e for e in room["entities"] if not e["ok"]]
    assert [e["entity_id"] for e in bad] == ["sensor.f2_vwc_2"]


def test_stale_heartbeat_is_stale_controller():
    hass = _hass(
        {"e1": _room("f2_")}, [_beat("f2_", 11 * 60, controller_version="1.4.0")]
    )
    out = status(hass, NOW)
    assert out["controller"] == "stale"
    assert out["rooms"][0]["heartbeat"]["controller"] == "stale"
    assert out["rooms"][0]["heartbeat"]["age_s"] == 660.0
    assert out["addon_version"] == "1.4.0"

    fresh = _hass(
        {"e1": _room("f2_")}, [_beat("f2_", 9 * 60, controller_version="1.4.0")]
    )
    assert status(fresh, NOW)["controller"] == "running"
    assert status(_hass({"e1": _room("f2_")}), NOW)["controller"] == "absent"


def test_entities_are_grouped_by_kind_with_names():
    named = _state("sensor.f2_vwc_1", "41", attrs={"friendly_name": "Zone 1 front"})
    hass = _hass({"e1": _room("f2_", zones=2)}, [named])
    room = status(hass, NOW)["rooms"][0]
    assert [g["kind"] for g in room["groups"]] == [
        "probe_vwc",
        "valve",
        "pump",
        "main_line",
        "feed_probe",
    ]
    vwc = room["groups"][0]["entities"]
    assert [(e["entity_id"], e["name"], e["zone"]) for e in vwc] == [
        ("sensor.f2_vwc_1", "Zone 1 front", 1),
        ("sensor.f2_vwc_2", "sensor.f2_vwc_2", 2),
    ]
    pump = room["groups"][2]["entities"][0]
    assert pump["zone"] is None and pump["kind"] == "pump"
    assert pump["last_change"] == (NOW - timedelta(seconds=30)).isoformat()
    assert pump["uptime_7d_pct"] is None  # nothing read from the recorder yet


def test_uptime_7d_from_a_state_history():
    start = NOW - timedelta(days=7)
    down = start + timedelta(days=2)
    history = [
        SimpleNamespace(state="41", last_changed=start),
        SimpleNamespace(state="unavailable", last_changed=down),
        SimpleNamespace(state="42", last_changed=down + timedelta(hours=12)),
    ]
    assert uptime_pct(history, start, NOW) == pytest.approx(92.85714285714286)
    assert uptime_pct([], start, NOW) is None  # nothing recorded: not known


def test_a_fresh_install_reads_its_real_uptime():
    """The share is of the time since the first recorded state, not of 7 days."""
    start = NOW - timedelta(days=7)
    first = NOW - timedelta(hours=2)
    history = [
        SimpleNamespace(state="41", last_changed=first),
        SimpleNamespace(
            state="unavailable", last_changed=first + timedelta(minutes=90)
        ),
    ]
    assert uptime_pct(history, start, NOW) == pytest.approx(75.0)


def _joined(hass, **entries):
    tracker = Tracker(hass)
    tracker.entries = entries or {
        "e1": "room:f2_"
    }  # joined (no listener in a hand-made hass)
    hass.data[DOMAIN][system_status.TRACKER] = tracker
    return tracker


def _ok(hass, entity_id):
    room = status(hass, NOW)["rooms"][0]
    return {e["entity_id"]: e["ok"] for e in room["entities"]}[entity_id]


def test_a_probe_reporting_every_5_min_is_not_silent():
    reports = [NOW - timedelta(minutes=5 * i) for i in range(12, 0, -1)]
    assert median_interval(reports) == 300.0
    probe = _state("sensor.f2_vwc_1", "41", age_s=3600, reported_s=880)
    hass = _hass({"e1": _room("f2_", zones=1)}, [probe])
    tracker = _joined(hass)
    # No interval known yet: the 900 s fallback.
    assert _ok(hass, "sensor.f2_vwc_1") is True
    # Its own reports, kept in memory (the last 12): every 5 min, so silent after 3 x 5 min.
    for at in [NOW - timedelta(minutes=5 * i) for i in range(20, 2, -1)]:
        tracker.report("sensor.f2_vwc_1", at)
    assert len(tracker.reports["sensor.f2_vwc_1"]) == 12
    assert tracker.median("sensor.f2_vwc_1") == 300.0
    assert _ok(hass, "sensor.f2_vwc_1") is True
    hass.states.get("sensor.f2_vwc_1").last_reported = NOW - timedelta(seconds=901)
    assert _ok(hass, "sensor.f2_vwc_1") is False
    # Fast reports never go below the 180 s floor.
    for i in range(12):
        tracker.report("sensor.f2_vwc_1", NOW + timedelta(seconds=10 * i))
    hass.states.get("sensor.f2_vwc_1").last_reported = NOW - timedelta(seconds=170)
    assert _ok(hass, "sensor.f2_vwc_1") is True
    # An actuator is ok while available, however long ago it last changed.
    valve = _state("switch.f2_valve_1", "off", age_s=86400)
    hass = _hass({"e1": _room("f2_", zones=1)}, [valve])
    assert _ok(hass, "switch.f2_valve_1") is True


def test_tank_probes_go_silent_but_the_low_float_and_flow_meters_do_not():
    hardware = {
        "tank_ec_sensor": "sensor.tank_ec",
        "tank_ph_sensor": "sensor.tank_ph",
        "tank_temperature_sensor": "sensor.tank_temp",
        "tank_distance_sensor": "sensor.tank_distance",
        "tank_low_float": "binary_sensor.tank_low",
    }
    old = 1000  # over the 900 s fallback
    states = [_state(e, "1", age_s=old, reported_s=old) for e in hardware.values()]
    states.append(_state("sensor.z1_flow", "0", age_s=old, reported_s=old))
    hass = _hass({"e1": _room("f2_", zones=1, hardware=hardware)}, states)
    hass.data[DOMAIN]["_site"] = SimpleNamespace(
        document={"zone_meters": {"room:f2_": {"1": "sensor.z1_flow"}}}
    )
    room = status(hass, NOW)["rooms"][0]
    ok = {e["entity_id"]: e["ok"] for e in room["entities"]}
    assert [k for k, v in ok.items() if not v] == [
        "sensor.tank_distance",
        "sensor.tank_temp",
        "sensor.tank_ec",
        "sensor.tank_ph",
    ]
    assert ok["binary_sensor.tank_low"] is True and ok["sensor.z1_flow"] is True


def test_uptime_reads_are_shared_and_the_cache_forgets_unmapped_entities(monkeypatch):
    import sys
    import types

    calls = []

    async def run(job):
        await asyncio.sleep(0)
        return job()

    def changes(hass, start, end, entity_id, **_):
        calls.append(entity_id)
        return {entity_id: [SimpleNamespace(state="1", last_changed=start)]}

    recorder = types.ModuleType("homeassistant.components.recorder")
    recorder.get_instance = lambda hass: SimpleNamespace(async_add_executor_job=run)
    recorder.history = SimpleNamespace(state_changes_during_period=changes)
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(sys.modules, "homeassistant.components.recorder", recorder)

    hass = _hass({"e1": _room("f2_", zones=1, hardware={})})
    hass.config.components.add("recorder")
    tracker = _joined(hass)
    tracker.uptime["sensor.no_longer_mapped"] = (NOW, 50.0)

    async def both():
        await asyncio.gather(tracker.refresh_uptime(NOW), tracker.refresh_uptime(NOW))

    asyncio.run(both())
    assert sorted(calls) == [
        "sensor.f2_vwc_1",
        "switch.f2_valve_1",
    ]  # one 7-day read each
    assert set(tracker.uptime) == {"sensor.f2_vwc_1", "switch.f2_valve_1"}
    assert tracker.uptime["sensor.f2_vwc_1"] == (NOW, 100.0)


def test_a_heartbeat_gap_is_a_missed_beat():
    ring = Ring()
    t0 = NOW - timedelta(minutes=10)
    ring.add(t0)
    ring.add(t0 + timedelta(seconds=60), readback_ms=42)
    ring.add(t0 + timedelta(seconds=300))
    beats = ring.rows()
    assert [b["missed"] for b in beats] == [False, False, True, False]
    assert beats[1]["readback_ms"] == 42 and beats[0]["readback_ms"] is None
    assert beats[2]["at"] == (t0 + timedelta(seconds=120)).isoformat()
    assert beats[2]["gap_s"] == 240.0  # the gap the missed beat stands for
    for i in range(200):
        ring.add(t0 + timedelta(seconds=360 + 60 * i))
    assert len(ring.rows()) == 120


def test_each_room_carries_its_own_heartbeat():
    hass = _hass(
        {"e1": _room("f2_", zones=1), "e2": _room("veg_", zones=1)},
        [_beat("f2_", 30), _beat("veg_", 20 * 60)],
    )
    tracker = Tracker(hass)
    tracker.entries = {"e1": "room:f2_", "e2": "room:veg_"}
    hass.data[DOMAIN][system_status.TRACKER] = tracker
    tracker.ring("room:f2_").add(NOW - timedelta(seconds=30))
    out = status(hass, NOW)
    f2, veg = out["rooms"]
    assert (f2["room_id"], veg["room_id"]) == ("room:f2_", "room:veg_")
    assert f2["controller"] == f2["heartbeat"]["controller"] == "running"
    assert veg["controller"] == veg["heartbeat"]["controller"] == "stale"
    assert len(f2["heartbeat"]["beats"]) == 1 and veg["heartbeat"]["beats"] == []
    assert f2["heartbeat"]["interval_s"] == 60
    assert out["controller"] == "running"  # the best of the rooms


def test_no_brain_no_lovelace_resource_gives_none_not_an_error():
    hass = _hass({"e1": _room("f2_", zones=1)})
    out = status(hass, NOW)
    assert out["ai"] is None and out["card_version"] is None
    assert asyncio.run(card_version(hass)) is None
    hass.data["lovelace"] = {"resources": None}
    assert asyncio.run(card_version(hass)) is None

    # With them: the AI budget, and the card's ?v= from either shape of hass.data["lovelace"].
    class Resources:
        async def async_get_info(self):
            return {}

        def async_items(self):
            return [
                {"url": "/local/other.js?v=1"},
                {"url": "/crop_steering/crop-steering-card.js?v=3171"},
            ]

    hass.data["lovelace"] = SimpleNamespace(resources=Resources())
    assert asyncio.run(card_version(hass)) == "3171"
    jev = _state(
        "sensor.crop_steering_f2_jev",
        "on",
        attrs={"calls_today": 30, "daily_budget": 120},
    )
    hass = _hass({"e1": _room("f2_", zones=1)}, [jev])
    assert status(hass, NOW)["ai"] == {
        "calls_today": 30,
        "daily_budget": 120,
        "pct_used": 25.0,
        "model": None,
    }
