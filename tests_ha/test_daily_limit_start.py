"""What a new zone's daily water limit starts at, in a real Home Assistant.

Every new zone started at 20 L whatever its size. A zone of 40 plants in 10 L pots gives more than
that with its ramp alone, so it reached the limit on its first grow-day and got no maintenance shot
until a person raised it. A zone that setup makes now starts at half of its substrate (plants x
litres for each plant), and at 20 L when that is less, which is what a default zone (4 plants x
10 L) always got.

Only a zone that setup marks as new takes this. A zone made before has no mark: it keeps its
limit, and with no saved value it starts at 20 L as it always did. The size is read from the
room's own numbers once all of them hold their value, the same two numbers as the limit of the
setting, so the start is never above that limit.
"""

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.core import Context, State
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import mock_restore_cache

from conftest import fixture
from custom_components.crop_steering.bounds import (
    daily_volume_bound,
    start_new_daily_limits,
    starting_daily_volume,
)
from custom_components.crop_steering.const import CONF_DAILY_LIMIT_FROM_SIZE
from custom_components.crop_steering.generated.defaults import (
    ENTITY_DEFAULTS,
    ZONE_STARTS,
)
from test_configure import _open, _shown, _suggested
from test_real_flow import ZONES, _seed, _to_zones_step
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
DAILY = "number.crop_steering_tent_zone_1_max_daily_volume"
DAILY_2 = "number.crop_steering_tent_zone_2_max_daily_volume"
POT = "number.crop_steering_tent_substrate_volume"
WIZARD_2_17 = "entry_2_17_wizard.json"
ENV_ERA = "entry_env_era.json"


# ------------------------------------------------------------------ the rule
def test_the_rule():
    assert ZONE_STARTS == {"max_daily_volume": {"substrate_multiple": 0.5, "ceiling": 2000.0}}
    assert starting_daily_volume(4, 10) == 20.0  # the default zone starts where it always did
    assert starting_daily_volume(40, 10) == 200.0
    assert starting_daily_volume(36, 6) == 108.0
    assert starting_daily_volume(7, 3.4) == 20.0  # 11.9 L: never under the entity default
    assert starting_daily_volume(100, 0.65) == 33.0  # 32.5 L: to the nearest litre, a half goes up
    assert starting_daily_volume(27, 5) == 68.0  # 67.5 L
    assert starting_daily_volume(1000, 200) == 2000.0  # never more than the engine accepts
    for unreadable in ((None, 10), (0, 10), ("unknown", 10), (4, float("nan"))):
        assert starting_daily_volume(*unreadable) == ENTITY_DEFAULTS["max_daily_volume"]


def test_the_ceiling_is_the_most_the_engine_accepts():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crop-steering-engine" / "src"))
    from crop_steering_engine.core import _PARAM_BOUNDS

    assert ZONE_STARTS["max_daily_volume"]["ceiling"] == _PARAM_BOUNDS["max_daily_volume"][1]


def test_the_start_is_inside_the_limit_of_the_setting_for_every_zone_size():
    for plants in (1, 2, 4, 7, 36, 40, 250, 1000):
        for litres in (0.1, 0.65, 1, 3.4, 6, 10, 50, 200):
            start = starting_daily_volume(plants, litres)
            assert 20.0 <= start <= daily_volume_bound(plants, litres), (plants, litres)
            assert start == int(start)


def _number(zone, plants, litres, *, marked=True, restored=False, value=20.0):
    written = []
    number = SimpleNamespace(
        hass=object(),
        _zone_num=zone,
        start_from_size=marked,
        was_restored=restored,
        _attr_native_value=value,
        _sizing=lambda z, key: {"plant_count": plants, "substrate_volume": litres}[key],
        async_write_ha_state=lambda: written.append(True),
        written=written,
    )
    return number


def test_only_a_marked_limit_that_did_not_restore_its_value_takes_the_start():
    new = _number(1, 40, 10)
    restored = _number(2, 40, 10, restored=True, value=75.0)
    old = _number(3, 40, 10, marked=False)
    room_number = SimpleNamespace(_zone_num=None, _attr_native_value=5.0)  # any other number
    disabled = _number(4, 40, 10)
    disabled.hass = None  # a person disabled it: Home Assistant does not have it
    start_new_daily_limits([new, restored, old, room_number, disabled])
    assert (disabled._attr_native_value, disabled.written) == (20.0, [])
    assert (new._attr_native_value, new.written) == (200.0, [True])
    assert (restored._attr_native_value, restored.written) == (75.0, [])
    assert (old._attr_native_value, old.written) == (20.0, [])
    assert room_number._attr_native_value == 5.0


# ------------------------------------------------------------------ a new room
async def _wizard(hass, plants, litres):
    _seed(hass)
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**ZONES, "zone_1_plant_count": plants}
    )
    assert result["step_id"] == "hardware", result.get("errors")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"plumbing": "valves_only", "substrate_volume": litres}
    )
    assert result["type"].value == "create_entry", result
    await hass.async_block_till_done()
    return result["result"]


def _value(hass, entity_id=DAILY):
    return float(hass.states.get(entity_id).state)


def _max(hass, entity_id=DAILY):
    return hass.states.get(entity_id).attributes["max"]


def _cards(hass):
    return [
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith("outside_zone_bounds")
    ]


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )


async def _service(hass, user, name, data=None):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data or {},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def test_a_default_zone_from_the_wizard_starts_at_20_litres_as_before(hass):
    entry = await _install(hass)  # 4 plants, 10 L for each plant
    assert _value(hass) == 20.0
    zone = entry.data["zones"]["1"]
    assert zone[CONF_DAILY_LIMIT_FROM_SIZE] is True and "max_daily_volume" not in zone


async def test_a_large_zone_from_the_wizard_starts_at_half_of_its_substrate(hass):
    await _wizard(hass, plants=40, litres=10)
    assert _value(hass) == 200.0  # was 20
    assert _max(hass) == 1600.0  # and inside the setting's limit
    assert _cards(hass) == []


async def test_a_small_zone_from_the_wizard_starts_at_20_litres(hass):
    await _wizard(hass, plants=6, litres=4)  # half of 24 L is 12 L
    assert _value(hass) == 20.0


async def test_a_room_made_on_the_dashboard_starts_each_zone_at_its_size(hass, hass_admin_user):
    await _install(hass)  # the dashboard needs one room to be there
    for valve in ("switch.bench_a", "switch.bench_b"):
        hass.states.async_set(valve, "off")
    zone = {"active": True, "vwc_sensors": [], "ec_sensors": []}
    await _service(
        hass,
        hass_admin_user,
        "setup_create",
        {
            "room_name": "Second Room",
            "active": True,
            "plumbing": "valves_only",
            "hardware": {},
            "zones": [
                {**zone, "id": 1, "valve": "switch.bench_a", "plant_count": 40, "substrate_volume": 10.0},
                {**zone, "id": 2, "valve": "switch.bench_b", "plant_count": 4},
            ],
        },
    )
    await hass.async_block_till_done()
    assert _value(hass, "number.crop_steering_second_room_zone_1_max_daily_volume") == 200.0
    assert _value(hass, "number.crop_steering_second_room_zone_2_max_daily_volume") == 20.0
    assert _cards(hass) == []


# ------------------------------------------------------------------ given once
async def test_the_start_is_given_once_and_a_reload_keeps_what_the_grower_set(hass):
    entry = await _wizard(hass, plants=40, litres=10)
    await _set(hass, DAILY, 75)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _value(hass) == 75.0
    # More plants later do not move the limit: it is the grower's setting now.
    await _set(hass, "number.crop_steering_tent_zone_1_plant_count", 80)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _value(hass) == 75.0


async def test_a_room_set_up_again_under_the_same_name_does_not_take_the_deleted_rooms_limit(hass):
    """Home Assistant keeps the last state of a removed entity for seven days. The deleted room's
    75 L is not this room's: the new zone starts at its own size."""
    before = dt_util.utcnow() - timedelta(hours=2)
    mock_restore_cache(hass, [State(DAILY, "75.0", last_changed=before, last_updated=before)])
    await _wizard(hass, plants=40, litres=10)
    assert _value(hass) == 200.0


# ------------------------------------------------------------------ a room from before
async def test_an_old_room_keeps_20_litres_on_each_zone_with_or_without_a_saved_state(hass):
    """The 2.17 wizard room: 36 plants x 6 L on each zone, and 20 L written in its entry. The new
    rule would give 108 L."""
    seed = fixture(WIZARD_2_17)
    assert seed["data"]["zones"]["1"]["max_daily_volume"] == 20.0
    await _upgrade(hass, WIZARD_2_17)  # no saved state for the two limits
    assert _value(hass, "number.crop_steering_zone_1_max_daily_volume") == 20.0
    assert _value(hass, "number.crop_steering_zone_2_max_daily_volume") == 20.0


async def test_an_old_room_keeps_the_limit_its_grower_set(hass):
    await _upgrade(
        hass,
        WIZARD_2_17,
        restored={"number.crop_steering_zone_1_max_daily_volume": "64.0"},
    )
    assert _value(hass, "number.crop_steering_zone_1_max_daily_volume") == 64.0
    assert _value(hass, "number.crop_steering_zone_2_max_daily_volume") == 20.0


async def test_an_old_room_with_no_limit_in_its_entry_and_no_saved_state_still_starts_at_20(hass):
    """The .env-era room: its zone holds no limit and no mark. With no saved value its limit
    starts at 20 L, as it did before, whatever the zone's size (4 plants x 8 L here; a zone of
    40 plants would also get 20)."""
    seed = fixture(ENV_ERA)
    zone = seed["data"]["zones"]["1"]
    assert "max_daily_volume" not in zone and CONF_DAILY_LIMIT_FROM_SIZE not in zone
    await _upgrade(
        hass, ENV_ERA, restored={"number.crop_steering_zone_1_plant_count": "40"}
    )
    assert _value(hass, "number.crop_steering_zone_1_plant_count") == 40.0
    assert _value(hass, "number.crop_steering_zone_1_max_daily_volume") == 20.0


async def test_an_old_room_with_no_limit_in_its_entry_keeps_its_saved_limit(hass):
    await _upgrade(
        hass, ENV_ERA, restored={"number.crop_steering_zone_1_max_daily_volume": "64.0"}
    )
    assert _value(hass, "number.crop_steering_zone_1_max_daily_volume") == 64.0


# ------------------------------------------------------------------ a zone added to a room
async def _add_zone_in_configure(hass, entry, plants):
    hass.states.async_set("switch.valve_2", "off")
    hass.states.async_set("sensor.vwc_2", "40", {"unit_of_measurement": "%"})
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"num_zones": 2})
    assert flow["step_id"] == "edit_zones_map"
    answers = {
        **_shown(flow),
        **_suggested(flow),
        "zone_2_switch": "switch.valve_2",
        "zone_2_vwc": ["sensor.vwc_2"],
        "zone_2_plant_count": plants,
    }
    done = await hass.config_entries.options.async_configure(flow["flow_id"], answers)
    assert done["type"].value == "create_entry", done.get("errors")
    await hass.async_block_till_done()


async def test_a_zone_added_in_configure_starts_at_its_size_and_the_first_zone_keeps_its_limit(
    hass,
):
    entry = await _wizard(hass, plants=40, litres=10)
    await _set(hass, DAILY, 120)
    await _add_zone_in_configure(hass, entry, plants=30)
    assert _value(hass) == 120.0  # the first zone: the grower's value, not moved
    assert _value(hass, DAILY_2) == 150.0  # 30 plants x 10 L, the room's litres for each plant
    assert _cards(hass) == []


async def test_a_zone_added_later_reads_the_pot_size_the_room_holds_now(hass):
    """The grower changed the room's pot size on the dashboard after setup. Setup still holds the
    10 L it was told; the room's number holds 20 L, and that is what the controller uses."""
    entry = await _wizard(hass, plants=40, litres=10)
    await _set(hass, POT, 20)
    await _add_zone_in_configure(hass, entry, plants=30)
    assert _value(hass, POT) == 20.0
    assert _value(hass, DAILY_2) == 300.0  # 30 x 20 x 0.5; from setup's 10 L it was 150


async def test_a_zone_added_later_never_starts_above_the_limit_of_its_setting(hass):
    """Pots much smaller than setup was told. From setup's 10 L the start was 150 L, above the
    120 L the setting allows (30 x 1 x 4), and the new zone got a Repairs card."""
    entry = await _wizard(hass, plants=40, litres=10)
    await _set(hass, POT, 1)
    await _add_zone_in_configure(hass, entry, plants=30)
    assert _max(hass, DAILY_2) == 120.0
    assert _value(hass, DAILY_2) == 20.0  # half of 30 L is 15 L
    # The first zone's 200 L is now above its own limit (40 x 1 x 4 = 160 L), and the card says so,
    # as before. It does not name the new zone.
    (card,) = _cards(hass)
    named = ir.async_get(hass).async_get_issue(DOMAIN, card).translation_placeholders["settings"]
    assert f"`{DAILY}`: 200 (limit 160)" in named and DAILY_2 not in named


async def test_a_zone_added_on_the_dashboard_setup_page_starts_at_its_own_size(
    hass, hass_admin_user
):
    hass.states.async_set("switch.valve_2", "off")
    hass.states.async_set("sensor.vwc_2", "40", {"unit_of_measurement": "%"})
    entry = await _wizard(hass, plants=40, litres=10)
    (room,) = (await _service(hass, hass_admin_user, "setup_read"))["rooms"]
    zones = [{"id": z["id"], "active": z["active"]} for z in room["zones"]]
    zones.append(
        {
            "id": 2,
            "active": True,
            "valve": "switch.valve_2",
            "vwc_sensors": ["sensor.vwc_2"],
            "plant_count": 24,
            "substrate_volume": 4.0,  # this zone's own pots
        }
    )
    await _service(
        hass,
        hass_admin_user,
        "setup_save",
        {"entry_id": room["entry_id"], "expected_revision": room["revision"], "zones": zones},
    )
    await hass.async_block_till_done()
    assert _value(hass) == 200.0
    assert _value(hass, DAILY_2) == 48.0  # 24 plants x 4 L = 96 L of substrate
    assert _cards(hass) == []
    marks = {z: cfg.get(CONF_DAILY_LIMIT_FROM_SIZE) for z, cfg in entry.data["zones"].items()}
    assert marks == {"1": True, "2": True}


async def test_saving_an_old_room_again_does_not_mark_its_zones_as_new(hass, hass_admin_user):
    """Configure and the dashboard's setup page write every zone again on a save. A zone that was
    there before the save gets no mark, so an old room stays an old room."""
    await _upgrade(hass, WIZARD_2_17)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    flow = await _open(hass, entry, "edit_zones")
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"num_zones": 2})
    done = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**_shown(flow), **_suggested(flow)}
    )
    assert done["type"].value == "create_entry", done.get("errors")
    await hass.async_block_till_done()
    (room,) = (await _service(hass, hass_admin_user, "setup_read"))["rooms"]
    await _service(
        hass,
        hass_admin_user,
        "setup_save",
        {
            "entry_id": room["entry_id"],
            "expected_revision": room["revision"],
            "zones": [{"id": z["id"], "active": z["active"], "name": "Row"} for z in room["zones"]],
        },
    )
    await hass.async_block_till_done()
    zones = {**entry.data, **entry.options}["zones"]
    assert [zones[z]["name"] for z in ("1", "2")] == ["Row", "Row"]  # both saves went through
    assert all(CONF_DAILY_LIMIT_FROM_SIZE not in zones[z] for z in ("1", "2"))
    assert _value(hass, "number.crop_steering_zone_1_max_daily_volume") == 20.0


async def test_a_limit_written_in_the_setup_wins_over_the_mark(hass, monkeypatch):
    """A room made by this version and then saved by an older one has both: the mark, and the 20 L
    the older version wrote for each zone. What is written is what the zone gets."""
    import test_upgrade_in_place

    seed = fixture(WIZARD_2_17)
    for zone in seed["data"]["zones"].values():
        zone[CONF_DAILY_LIMIT_FROM_SIZE] = True
    monkeypatch.setattr(test_upgrade_in_place, "fixture", lambda name: seed)
    await _upgrade(hass, WIZARD_2_17)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.data["zones"]["1"][CONF_DAILY_LIMIT_FROM_SIZE] is True  # the seed was used
    assert _value(hass, "number.crop_steering_zone_1_max_daily_volume") == 20.0  # not 108


async def test_a_zone_the_old_room_counted_with_nothing_stored_for_it_is_not_a_new_zone(
    hass, hass_admin_user, monkeypatch
):
    """An old room that counts two zones and holds a config for one only. A save writes a config
    for the second zone too. That zone is not new: no mark, and 20 L with no saved value."""
    import test_upgrade_in_place

    seed = fixture(WIZARD_2_17)
    assert seed["data"]["num_zones"] == 2
    del seed["data"]["zones"]["2"]
    monkeypatch.setattr(test_upgrade_in_place, "fixture", lambda name: seed)
    await _upgrade(hass, WIZARD_2_17)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert set(entry.data["zones"]) == {"1"}  # the seed was used
    (room,) = (await _service(hass, hass_admin_user, "setup_read"))["rooms"]
    await _service(
        hass,
        hass_admin_user,
        "setup_save",
        {
            "entry_id": room["entry_id"],
            "expected_revision": room["revision"],
            "zones": [
                {"id": 1, "active": True},
                {"id": 2, "active": True, "valve": "switch.row_2_valve", "plant_count": 30},
            ],
        },
    )
    await hass.async_block_till_done()
    zones = {**entry.data, **entry.options}["zones"]
    assert zones["2"]["plant_count"] == 30  # the save went through
    assert CONF_DAILY_LIMIT_FROM_SIZE not in zones["1"] and CONF_DAILY_LIMIT_FROM_SIZE not in zones["2"]
    assert _value(hass, "number.crop_steering_zone_2_max_daily_volume") == 20.0


def test_configure_marks_only_a_zone_above_the_rooms_old_count():
    from custom_components.crop_steering.config_flow import _build_zones

    data = {f"zone_{z}_switch": f"switch.v{z}" for z in (1, 2, 3)}
    old = {"1": {"zone_switch": "switch.v1", "max_daily_volume": 20.0}}
    marks = lambda zones: {z: cfg.get(CONF_DAILY_LIMIT_FROM_SIZE) for z, cfg in zones.items()}  # noqa: E731
    assert marks(_build_zones(3, data)) == {"1": True, "2": True, "3": True}  # the wizard: all new
    assert marks(_build_zones(3, data, old, had=2)) == {"1": None, "2": None, "3": True}
    assert marks(_build_zones(3, data, {1: old["1"]}, had=2)) == {"1": None, "2": None, "3": True}  # int keys
    assert marks(_build_zones(2, data, old, had=1)) == {"1": None, "2": True}
