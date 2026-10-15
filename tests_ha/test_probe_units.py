"""Device units, on upgraded rooms in a real Home Assistant with the real controller.

The controller now reads every probe and the sump plug through the one device-unit table. On a room
upgraded from 2.25.1 or 3.11.1 every reading it steers by is exactly what that release read, so no zone
waters differently; and a sump plug that reports kW, which 3.11.1 compared with 20 as if it were watts,
no longer says the sump pump has stopped while it runs.
"""

import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import controller
import pytest
from conftest import fixture, room_of
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_probe_fusion import A, ZONE
from test_probe_fusion import _install as _install_probes
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

SUMP = "sensor.sump_pump_power"


def _read_3_11_1(state, lo, hi, microsiemens):
    """3.11.1's _read_sensor arithmetic, written out (its freshness test aside)."""
    if state is None or state.state in ("unknown", "unavailable", ""):
        return None
    try:
        f = float(state.state)
    except ValueError:
        return None
    unit = str(state.attributes.get("unit_of_measurement") or "").lower().replace(" ", "")
    if microsiemens and unit in ("µs/cm", "μs/cm", "us/cm"):
        f /= 1000.0
    return f if math.isfinite(f) and lo <= f <= hi else None


async def _upgraded(hass, controller_for, name, **options):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    hass.states.async_set(SUMP, "0", {"unit_of_measurement": options.pop("sump_unit", "W")})
    c, fake, _clock = controller_for({**(seed.get("addon_options") or {}), **options})
    return c, fake, c.rooms[0]


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_upgraded_room_reads_every_probe_exactly_as_before(hass, controller_for, name):
    c, _fake, room = await _upgraded(hass, controller_for, name)
    now = datetime.now()
    usable = 0
    for zone in sorted(room.zones):
        expected = {}
        for metric, hi in (("vwc", 100), ("ec", 20)):
            entity = c._fused_id(room.prefix, metric, zone, room.zones[zone].get(metric))
            expected[metric] = _read_3_11_1(hass.states.get(entity), 0, hi, False)
            assert c._read_sensor(entity, metric) == expected[metric], entity
            usable += expected[metric] is not None
        snap, _params = c._snapshot(room, zone, now, True, False)
        if expected["vwc"] is not None:  # what the zone steers by is what 3.11.1 steered by
            assert (snap.vwc, snap.ec) == (expected["vwc"], expected["ec"])
    assert usable >= 4  # two zones, each with a moisture and an EC reading
    assert (room.feed_ec_sensor, room.feed_ph_sensor) == ("sensor.feed_ec", "sensor.feed_ph")
    assert c._read_feed_ec(room) == _read_3_11_1(hass.states.get("sensor.feed_ec"), 0, 20, True) == 2.2
    assert c._read_feed_ph(room) == _read_3_11_1(hass.states.get("sensor.feed_ph"), 0, 14, False) == 5.9


def _sump_cards(fake):
    return [
        d
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create") and d["notification_id"].startswith("f2_sump")
    ]


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
@pytest.mark.parametrize(
    "unit,rows,stopped",
    [
        ("kW", [("0", "a"), ("0.35", "b"), ("0", "c")], False),  # a 350 W run: 3.11.1 said it had stopped
        ("kW", [("0", "a"), ("0.002", "b")], True),  # 2 W is no run
        ("W", [("0", "a"), ("350", "b")], False),
        ("W", [("0", "a"), ("0", "b")], True),  # a plug in watts: the same verdicts as ever
    ],
)
async def test_a_sump_plug_is_compared_in_watts_whatever_it_reports(
    hass, controller_for, monkeypatch, name, unit, rows, stopped
):
    c, fake, room = await _upgraded(hass, controller_for, name, sump_power_sensor=SUMP, sump_unit=unit)
    monkeypatch.setattr(controller, "ha_history", lambda entity, since, timeout=12: rows)
    c._watch_sump(room, datetime.now())
    cards = _sump_cards(fake)
    assert bool(cards) is stopped
    if stopped:
        assert cards[0]["title"].endswith("(CS-311)") and f"Sensor: {SUMP}" in cards[0]["message"]


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
@pytest.mark.parametrize("unit", ["ppm", "ppt"])
@pytest.mark.parametrize("reading", ["1.2", "800"])
async def test_a_feed_probe_in_ppm_or_ppt_feeds_the_gate_exactly_as_before(
    hass, controller_for, name, unit, reading
):
    """A zone EC probe in ppm is set aside and its zone runs without EC. The feed probe is read as before
    instead: the source-water gate holds on a dead feed probe, so setting it aside would stop the room."""
    c, fake, room = await _upgraded(hass, controller_for, name)
    attributes = {"unit_of_measurement": unit}
    fake.set_state(room.feed_ec_sensor, reading, attributes)
    feed = c._read_feed_ec(room)
    assert feed == _read_3_11_1(SimpleNamespace(state=reading, attributes=attributes), 0, 20, True)
    assert (feed is None) is (reading == "800")


async def test_a_zone_whose_only_probe_reports_in_an_unknown_unit_names_it(
    hass, freezer, controller_for, monkeypatch
):
    """Fresh install, both layers: the integration sets the probe aside for its unit, the zone reading says
    which probe and unit, and the controller waters the zone blind and raises CS-503 naming them."""
    await _install_probes(hass, [A])
    hass.states.async_set(A, "1250", {"unit_of_measurement": "mV"})
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()
    state = hass.states.get(ZONE)
    assert state.state == "unknown"
    assert state.attributes["excluded"] == {A: "set aside for its unit"}
    assert state.attributes["unit_set_aside"] == {A: "mV"}

    monkeypatch.setattr(controller, "BLIND_GRACE_MIN", 0)
    c, fake, _clock = controller_for()
    room = room_of(c)
    monkeypatch.setattr(c, "_act_zone", lambda *args: None)
    c._loop_room(room, datetime.now())
    assert 1 in room._blind_zones  # the dead-probe path: watered on the timer or a sibling's shots
    [card] = [
        d
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create")
        and d["notification_id"].startswith("f2_blind_")
    ]
    assert card["title"].endswith("(CS-503)")
    assert f"{A} (in 'mV')" in card["message"] and f"Sensor: {ZONE}" in card["message"]
