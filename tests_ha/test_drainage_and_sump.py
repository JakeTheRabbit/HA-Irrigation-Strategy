"""A room's drainage and its sump pump's run threshold, in a real Home Assistant with the real controller.

CS-310 (moisture rising with no water) watches for a table that is not draining. It now asks the room how it
drains: a free-draining room has nothing that can back up, so it is not watched and its zones keep their
daily minimum and EC flushes. Setup asks on its first page. A room from before reads unknown, which is
watched exactly as before. CS-311 compares the sump plug, in watts whatever it reports, with the room's own
Sump Pump Run Threshold, which starts at the 20 W the controller always used.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import controller
import pytest
from conftest import fixture
from homeassistant import config_entries
from homeassistant.const import ATTR_OPTION
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from test_real_flow import ZONES, _seed
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

DOMAIN = "crop_steering"
DRAINAGE = "select.crop_steering_drainage"
THRESHOLD = "number.crop_steering_sump_power_threshold_w"
# A new room has a slug: the wizard's "Tent" is tent_ (an upgraded room keeps the ids above).
NEW_DRAINAGE = "select.crop_steering_tent_drainage"
NEW_THRESHOLD = "number.crop_steering_tent_sump_power_threshold_w"
SUMP = "sensor.sump_pump_power"
F_38 = "entry_3_8_learned_tent.json"


async def _wizard(hass, first_page):
    """The setup wizard, answering its first page with `first_page`."""
    _seed(hass)
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await flow.async_configure(result["flow_id"], first_page)
    result = await flow.async_configure(result["flow_id"], {"num_zones": 1})
    result = await flow.async_configure(result["flow_id"], dict(ZONES))
    result = await flow.async_configure(result["flow_id"], {"plumbing": "valves_only"})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


async def test_the_first_page_of_setup_asks_how_the_room_drains(hass):
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    asked = {str(marker): marker for marker in result["data_schema"].schema}
    assert asked["drainage"].default() == "unknown"  # a person who is not sure is watched, as tables are
    entry = await _wizard(hass, {"name": "Tent", "drainage": "free_drain"})
    assert entry.data["drainage"] == "free_drain"
    drainage = hass.states.get(NEW_DRAINAGE)
    assert drainage.state == "free_drain"
    assert drainage.attributes["options"] == ["unknown", "flood_table", "free_drain"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": NEW_DRAINAGE, ATTR_OPTION: "flood_table"}, blocking=True
    )
    # The room's answer is its select from then on: a reload (or a restart) restores it, not setup's.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(NEW_DRAINAGE).state == "flood_table"


async def test_a_new_room_left_unsaid_reads_unknown_and_its_threshold_starts_at_20_w(hass):
    await _wizard(hass, {"name": "Tent"})
    assert hass.states.get(NEW_DRAINAGE).state == "unknown"
    threshold = hass.states.get(NEW_THRESHOLD)
    assert float(threshold.state) == 20 and threshold.attributes["unit_of_measurement"] == "W"
    registry = er.async_get(hass)
    assert registry.async_get(NEW_DRAINAGE) is not None and registry.async_get(NEW_THRESHOLD) is not None


async def test_a_room_added_later_is_asked_too(hass):
    await _wizard(hass, {"name": "Tent"})
    hass.states.async_set("switch.veg_valve", "off")
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "room"
    result = await flow.async_configure(result["flow_id"], {"room_name": "Veg", "drainage": "flood_table"})
    result = await flow.async_configure(result["flow_id"], {"num_zones": 1})
    zones = {**ZONES, "zone_1_switch": "switch.veg_valve", "zone_1_vwc": [], "zone_1_ec": []}
    result = await flow.async_configure(result["flow_id"], zones)
    result = await flow.async_configure(result["flow_id"], {"plumbing": "valves_only"})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    assert hass.states.get("select.crop_steering_veg_drainage").state == "flood_table"
    assert hass.states.get(NEW_DRAINAGE).state == "unknown"  # the first room keeps its own


# ------------------------------------------------------------------ upgraded rooms
@pytest.mark.parametrize("name", [F_38, UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_upgraded_room_gets_the_two_settings_and_nothing_else_moves(hass, name):
    seed = fixture(name)
    entry, _seed_ = await _upgrade(hass, name, registry_ids=seed.get("registry"))
    assert "drainage" not in entry.data
    assert hass.states.get(DRAINAGE).state == "unknown"
    assert float(hass.states.get(THRESHOLD).state) == 20
    registry = er.async_get(hass)
    assert [e for e in (seed.get("registry") or {}) if registry.async_get(e) is None] == []
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = str(saved[0] if isinstance(saved, list) else saved)
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            state, tuned = float(state), float(tuned)
        assert state == tuned, entity_id


def _backup_cards(fake):
    return [
        d
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create") and d["notification_id"].startswith("f2_backup_")
    ]


def _rising(c, room, zone):
    """Moisture rising by 4.2 points in an hour with the zone's valve shut -> what the last loop said."""
    now = datetime.now()
    c._start = now - timedelta(hours=3)
    room.state[zone]["last_shot"] = now - timedelta(hours=2)
    held = None
    for minute in range(0, 61, 5):
        held = c._watch_backup(room, zone, SimpleNamespace(vwc=36.6 + 0.07 * minute), now + timedelta(minutes=minute))
    return held


@pytest.mark.parametrize("name", [F_38, JEV_3_11_1])
async def test_an_upgraded_room_is_watched_for_a_table_backing_up_as_before(hass, controller_for, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    c, fake, _clock = controller_for(seed.get("addon_options") or {})
    room = c.rooms[0]
    zone = sorted(room.zones)[0]
    assert _rising(c, room, zone) is True
    assert _backup_cards(fake)[0]["title"].endswith("(CS-310)")


@pytest.mark.parametrize("name", [F_38, JEV_3_11_1])
async def test_a_free_draining_room_is_never_held_and_gets_its_ec_flush(hass, controller_for, monkeypatch, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    await hass.services.async_call(
        "select", "select_option", {"entity_id": DRAINAGE, ATTR_OPTION: "free_drain"}, blocking=True
    )
    c, fake, _clock = controller_for(seed.get("addon_options") or {})
    room = c.rooms[0]
    zone = sorted(room.zones)[0]
    assert _rising(c, room, zone) is False
    assert _backup_cards(fake) == []
    # In the loop: a zone held before the room said it drains freely is let go, and decide() is not told
    # the table is backed up, which is what blocks an EC correction.
    room._backed_up = {zone: datetime.now()}
    seen = []
    original = controller.decide

    def decide(snap, params):
        seen.append(snap.backed_up)
        return original(snap, params)

    monkeypatch.setattr(controller, "decide", decide)
    monkeypatch.setattr(c, "_act_zone", lambda *args: None)
    c._loop_room(room, datetime.now())
    assert zone not in room._backed_up and seen and not any(seen)


# ------------------------------------------------------------------ the sump pump's run threshold
@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
@pytest.mark.parametrize(
    "threshold,unit,reading,stopped",
    [
        (None, "W", "15", True),  # the default 20 W: 15 W is no run, as it never was
        (None, "W", "25", False),
        (10, "kW", "0.015", False),  # 15 W, above a 10 W threshold
        (50, "W", "30", True),
    ],
)
async def test_the_sump_pump_runs_above_the_rooms_threshold(
    hass, controller_for, monkeypatch, name, threshold, unit, reading, stopped
):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    if threshold is not None:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": THRESHOLD, "value": threshold}, blocking=True
        )
    hass.states.async_set(SUMP, "0", {"unit_of_measurement": unit})
    c, fake, _clock = controller_for({**(seed.get("addon_options") or {}), "sump_power_sensor": SUMP})
    rows = [("0", "a"), (reading, "b"), ("0", "c")]
    monkeypatch.setattr(controller, "ha_history", lambda entity, since, timeout=12: rows)
    c._watch_sump(c.rooms[0], datetime.now())
    cards = [
        d
        for dom, svc, d in fake.calls
        if (dom, svc) == ("persistent_notification", "create") and d["notification_id"].startswith("f2_sump")
    ]
    assert bool(cards) is stopped
