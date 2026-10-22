"""The site store and its supply section (G1): pump capacity, exclusive groups, flow meters.

Pure arithmetic from generated/guards.py through site_store.capacity_check, and SiteStore driven
over an in-memory store: a missing store reads as no supply, saves are checked against a revision
and against what the pump can carry, a preview writes nothing, and a save publishes
sensor.crop_steering_supply_config and journals config.changed.
"""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import site_api, site_store  # noqa: E402

PUMP = "switch.pump"
ROOM = "room:f2_"


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.saves = value, 0

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value, self.saves = copy.deepcopy(value), self.saves + 1


class States:
    def __init__(self):
        self.items = {}

    def async_set(self, entity_id, state, attributes=None):
        self.items[entity_id] = SimpleNamespace(
            state=state, attributes=attributes or {}
        )

    def async_remove(self, entity_id):
        self.items.pop(entity_id, None)

    def get(self, entity_id):
        return self.items.get(entity_id)


def rig(zones=None, value=None, pump=PUMP, monkeypatch=None):
    hass = SimpleNamespace(states=States())
    backing = MemoryStore(value)
    site = site_api.SiteStore(hass, backing)
    asyncio.run(site.async_init())
    demand = {z: lph for z, lph in (zones or {}).items()}
    site.rooms = lambda: [{"room_id": ROOM, "pump": pump, "zones": demand}]
    return hass, site, backing


def pump(flow=1200, concurrent=1, **more):
    return {
        "entity_id": PUMP,
        "max_flow_lph": flow,
        "max_concurrent_zones": concurrent,
        **more,
    }


def save(site, **data):
    data.setdefault("expected_revision", site.document["revision"])
    data.setdefault("irrigation_pumps", [pump()])
    return asyncio.run(site.save(data))


SIX_AT_240 = {z: 240.0 for z in range(1, 7)}


def test_missing_store_reads_as_no_supply():
    hass, site, backing = rig(SIX_AT_240)
    read = site.response()
    assert read["revision"] == 0
    assert read["irrigation_pumps"] == []
    assert read["zone_groups"] == {} and read["zone_meters"] == {}
    check = read["capacity_check"]
    assert check["ok"] is True
    assert (check["worst_case_lph"], check["max_flow_lph"], check["pairs"]) == (
        0.0,
        None,
        [],
    )
    site.publish()
    assert (
        hass.states.get(site_api.SENSOR) is None
    )  # no descriptor: the controller runs as before
    assert backing.saves == 0


def test_save_refuses_a_stale_revision():
    _, site, backing = rig(SIX_AT_240)
    save(site)
    with pytest.raises(ValueError, match="changed elsewhere"):
        save(site, expected_revision=0)
    assert backing.saves == 1


def test_save_refuses_concurrency_the_pump_cannot_feed():
    _, site, backing = rig(SIX_AT_240)
    with pytest.raises(ValueError) as refused:
        save(site, irrigation_pumps=[pump(1200, 6)])
    message = str(refused.value)
    assert message.startswith("pump_over_capacity:")
    assert message.endswith("Set Zones at once to 5 or less.")
    assert backing.saves == 0 and site.document["revision"] == 0
    assert save(site, irrigation_pumps=[pump(1200, 5)])["revision"] == 1


def test_one_zone_at_a_time_is_never_refused():
    """A zone bigger than its pump still waters (CS-214 warns); the save only reports it."""
    _, site, _ = rig({1: 2000.0})
    saved = save(site, irrigation_pumps=[pump(1200, 1)])
    assert saved["capacity_check"]["ok"] is False


def test_groups_lower_the_worst_case():
    _, site, _ = rig(SIX_AT_240)
    plain = site.check({**site_store.empty(), "irrigation_pumps": [pump(1200, 6)]})
    assert plain["worst_case_lph"] == 1440.0 and plain["ok"] is False
    # Zones 1-3 on one line and 4-6 on another: at most one from each group runs.
    groups = {ROOM: {"1": "a", "2": "a", "3": "a", "4": "b", "5": "b", "6": "b"}}
    saved = save(site, irrigation_pumps=[pump(1200, 6)], zone_groups=groups)
    check = saved["capacity_check"]
    assert check["worst_case_lph"] == 480.0 and check["ok"] is True
    assert saved["zone_groups"] == groups


def test_preview_writes_nothing():
    hass, site, backing = rig(SIX_AT_240)
    preview = save(site, preview=True, irrigation_pumps=[pump(1200, 2)])
    assert set(preview) == {"diff", "capacity_check"}
    assert preview["diff"] and preview["capacity_check"]["ok"] is True
    assert backing.saves == 0 and site.document["revision"] == 0
    assert hass.states.get(site_api.SENSOR) is None
    with pytest.raises(ValueError, match="pump_over_capacity"):
        save(site, preview=True, irrigation_pumps=[pump(1200, 6)])


def test_capacity_pairs_say_together_or_one_after_another():
    pumps = [pump(1200, 2)]

    def pairs(zones, groups=None):
        rooms = [{"room_id": ROOM, "pump": PUMP, "zones": zones}]
        return site_store.capacity_check(pumps, rooms, groups or {})["pairs"]

    assert pairs({1: 480.0, 2: 480.0}) == [
        {"zones": [1, 2], "lph": 960.0, "pct_of_pump": 80.0, "verdict": "together"}
    ]
    [over] = pairs({1: 720.0, 2: 720.0})
    assert over["verdict"] == "one_after_another" and over["pct_of_pump"] == 120.0
    [same] = pairs({1: 100.0, 2: 100.0}, {ROOM: {"1": "a", "2": "a"}})
    assert same["verdict"] == "one_after_another"
    [serial] = site_store.capacity_check(
        [pump(1200, 1)],
        [{"room_id": ROOM, "pump": PUMP, "zones": {1: 1.0, 2: 1.0}}],
        {},
    )["pairs"]
    assert serial["verdict"] == "one_after_another"
    [unlimited] = site_store.capacity_check(
        [pump(None, 2)],
        [{"room_id": ROOM, "pump": PUMP, "zones": {1: 1.0, 2: 1.0}}],
        {},
    )["pairs"]
    assert unlimited["pct_of_pump"] is None and unlimited["verdict"] == "together"


def test_a_pair_across_rooms_names_the_room():
    rooms = [
        {"room_id": "room:a_", "pump": PUMP, "zones": {1: 100.0}},
        {"room_id": "room:b_", "pump": PUMP, "zones": {1: 100.0}},
        {"room_id": "room:c_", "pump": "switch.other", "zones": {1: 100.0}},
    ]
    check = site_store.capacity_check([pump(1200, 2)], rooms, {})
    [pair] = check["pairs"]
    assert pair["zones"] == [
        {"room_id": "room:a_", "zone": 1},
        {"room_id": "room:b_", "zone": 1},
    ]


def test_save_publishes_the_descriptor_and_journals_the_old_copy(monkeypatch):
    hass, site, _ = rig({1: 240.0, 2: 360.0})
    journal = []
    monkeypatch.setattr(
        site_api,
        "note",
        lambda hass_, room_id, kind, **kw: journal.append((room_id, kind, kw)),
    )
    meters = {ROOM: {"1": "sensor.f2_meter_1"}}
    saved = save(
        site,
        irrigation_pumps=[pump(1200, 2, flow_meter="sensor.line")],
        zone_meters=meters,
    )
    state = hass.states.get(site_api.SENSOR)
    assert state.state == "1" and saved["readback"]["status"] == "ok"
    assert state.attributes["irrigation_pumps"][0]["flow_meter"] == "sensor.line"
    assert state.attributes["zone_meters"] == meters
    assert state.attributes["zone_demand_lph"] == {ROOM: {"1": 240.0, "2": 360.0}}
    [(room_id, kind, kw)] = journal
    assert (room_id, kind) == (ROOM, "config.changed")
    data = kw["data"]
    assert (data["store"], data["section"]) == ("site", "supply")
    assert (
        data["old"]["irrigation_pumps"] == [] and data["new"]["zone_meters"] == meters
    )
    assert data["diff"]
    # A save that changes nothing journals nothing.
    save(
        site,
        irrigation_pumps=[pump(1200, 2, flow_meter="sensor.line")],
        zone_meters=meters,
    )
    assert len(journal) == 1


def test_a_journal_that_fails_never_fails_the_save(monkeypatch):
    _, site, _ = rig(SIX_AT_240)

    def boom(*a, **k):
        raise RuntimeError("journal down")

    monkeypatch.setattr(site_api, "note", boom)
    assert save(site)["revision"] == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"irrigation_pumps": [{"entity_id": "pump"}]},
        {"irrigation_pumps": [pump(-5)]},
        {"irrigation_pumps": [pump(1200, 0)]},
        {"irrigation_pumps": [pump(), pump()]},
        {"zone_groups": {"f2_": {"1": "a"}}},
        {"zone_groups": {ROOM: {"zero": "a"}}},
        {"zone_groups": {ROOM: {"1": "no spaces"}}},
        {"zone_meters": {ROOM: {"1": "not an entity"}}},
    ],
)
def test_a_bad_save_is_refused(bad):
    _, site, backing = rig(SIX_AT_240)
    with pytest.raises(ValueError):
        save(site, **bad)
    assert backing.saves == 0


def test_a_stored_section_this_version_cannot_read_is_dropped_not_the_store():
    stored = {
        "revision": 3,
        "irrigation_pumps": [pump(1200, 2)],
        "zone_groups": "garbage",
        "presets": [{"id": "p"}],
    }
    document = site_store.from_store(stored)
    assert document["revision"] == 3 and document["zone_groups"] == {}
    assert document["irrigation_pumps"][0]["max_concurrent_zones"] == 2
    assert document["presets"] == [{"id": "p"}]


def test_an_unreadable_store_is_never_overwritten():
    _, site, backing = rig(SIX_AT_240, value={"revision": "x"})
    assert site.error
    with pytest.raises(ValueError):
        save(site)
    assert backing.saves == 0
