"""A room that is deleted and set up again starts fresh. It does not inherit the deleted room.

First real install, 2026-09-21. Setup went badly, so the integration was deleted and added
again, which is what anybody does. The wizard was told lights 07:00-20:00; the room came up on
12:00-00:00 and switched OFF. Home Assistant keeps the last state of a REMOVED entity for seven
days, keyed by entity id (`restore_state.STATE_EXPIRATION`), this integration pins its entity ids,
and every number, switch and select restored whatever it found there. So the new room inherited
the old one: its setpoints over the answers just typed into the wizard, its room on/off switch,
and its KILL SWITCH. A room deleted while armed came back armed. (The controller refuses to adopt
a setup while the kill switch reads ON, so nothing was watered, and the operator got "Irrigation
BLOCKED - setup needs re-arming" on a room they had only just created.)

The rule: a restored state that was written before this config entry existed is not this room's.
"""

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)
from conftest import fixture
from test_setup_entry import _install

DOMAIN = "crop_steering"
KILL = "switch.crop_steering_engine_enabled"
ROOM = "switch.crop_steering_room_active"
LIGHTS_ON, LIGHTS_OFF = (
    "number.crop_steering_lights_on_hour",
    "number.crop_steering_lights_off_hour",
)
P1 = "number.crop_steering_p1_target_vwc"
MODE = "select.crop_steering_steering_mode"

# What the DELETED room left behind, as Home Assistant still holds it.
LEFT_BEHIND = {
    KILL: "on",  # it was armed when it was deleted
    ROOM: "off",
    LIGHTS_ON: "12.0",
    LIGHTS_OFF: "0.0",
    P1: "58.0",
    "switch.crop_steering_zone_1_enabled": "off",
}


def _left_behind(hass, written, extra=None):
    mock_restore_cache(
        hass,
        [
            State(entity_id, state, last_changed=written, last_updated=written)
            for entity_id, state in {**LEFT_BEHIND, **(extra or {})}.items()
        ],
    )


def _read(hass, entity_id):
    return hass.states.get(entity_id).state


# ------------------------------------------------------------------ fresh install, second attempt
async def test_a_room_set_up_again_is_born_with_its_kill_switch_off(hass):
    _left_behind(hass, dt_util.utcnow() - timedelta(hours=2))
    await _install(hass)
    assert _read(hass, KILL) == "off"  # was "on": armed by a room that no longer exists


async def test_a_room_set_up_again_takes_the_wizards_answers_not_the_deleted_rooms(
    hass,
):
    _left_behind(hass, dt_util.utcnow() - timedelta(hours=2))
    await _install(hass, {"lights_on_hour": 7, "lights_off_hour": 20})
    assert (float(_read(hass, LIGHTS_ON)), float(_read(hass, LIGHTS_OFF))) == (
        7.0,
        20.0,
    )
    assert float(_read(hass, P1)) == 65.0  # the default, not the old room's 58
    assert (
        _read(hass, ROOM) == "on"
    )  # a room is growing until the operator says otherwise
    assert _read(hass, "switch.crop_steering_zone_1_enabled") == "on"


async def test_a_select_does_not_inherit_the_deleted_rooms_choice_either(hass):
    await _install(hass)
    default = _read(hass, MODE)
    other = next(o for o in hass.states.get(MODE).attributes["options"] if o != default)
    for entry in hass.config_entries.async_entries(DOMAIN):
        assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    _left_behind(hass, dt_util.utcnow() - timedelta(hours=2), {MODE: other})
    await _install(hass)
    assert _read(hass, MODE) == default


async def test_the_real_sequence_delete_and_set_up_again_in_one_home_assistant(hass):
    """No hand-built cache: a real room is armed and tuned, deleted, and set up again. Home
    Assistant's own restore data (what it would write to disk) is what carries over."""
    from homeassistant.helpers.restore_state import async_get as restore_data

    entry = await _install(hass, {"lights_on_hour": 12, "lights_off_hour": 0})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": KILL}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": ROOM}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": P1, "value": 58}, blocking=True
    )
    assert _read(hass, KILL) == "on"

    data = restore_data(hass)
    stored = data.async_get_stored_states()  # what a shutdown would save
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    data.last_states = {
        s.state.entity_id: s for s in stored
    }  # ...and the next start reads
    assert hass.states.get(KILL) is None

    await _install(hass, {"lights_on_hour": 7, "lights_off_hour": 20})
    assert _read(hass, KILL) == "off"
    assert _read(hass, ROOM) == "on"
    assert (float(_read(hass, LIGHTS_ON)), float(_read(hass, LIGHTS_OFF))) == (
        7.0,
        20.0,
    )
    assert float(_read(hass, P1)) == 65.0


# ------------------------------------------------------------------ the same room, restarted
async def _restart(hass, *, created_at, written, states):
    """Home Assistant starting with an EXISTING room: its entry, and the states it saved."""
    seed = fixture("entry_2_18_one_switch_tent.json")
    for entity_id, (state, attributes) in seed["states"].items():
        hass.states.async_set(entity_id, state, attributes)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=seed["entry_id"],
        unique_id=seed["unique_id"],
        title=seed["title"],
        data=seed["data"],
        options=seed["options"],
    )
    if created_at is not None:
        object.__setattr__(entry, "created_at", created_at)
    entry.add_to_hass(hass)
    mock_restore_cache(
        hass,
        [
            State(entity_id, state, last_changed=written, last_updated=written)
            for entity_id, state in states.items()
        ],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


OPERATORS = {KILL: "on", ROOM: "off", LIGHTS_ON: "8.0", LIGHTS_OFF: "20.0", P1: "58.0"}


@pytest.mark.parametrize(
    "created_days_ago, written_hours_ago",
    [
        (400, 1),  # a room from last year, restarted an hour after its last change
        (400, 24 * 6),  # ...or whose values have not been touched for six days
        (1, 2),  # a room made yesterday
    ],
)
async def test_an_existing_room_restores_everything_exactly_as_before(
    hass, created_days_ago, written_hours_ago
):
    """In-place upgrade, and every ordinary restart: the kill switch of a room that is growing
    stays ON, and nothing the operator tuned moves."""
    now = dt_util.utcnow()
    await _restart(
        hass,
        created_at=now - timedelta(days=created_days_ago),
        written=now - timedelta(hours=written_hours_ago),
        states=OPERATORS,
    )
    assert _read(hass, KILL) == "on"
    assert _read(hass, ROOM) == "off"
    assert (float(_read(hass, LIGHTS_ON)), float(_read(hass, LIGHTS_OFF))) == (
        8.0,
        20.0,
    )
    assert float(_read(hass, P1)) == 58.0


async def test_a_room_older_than_home_assistants_own_record_of_when_it_was_made_restores(
    hass,
):
    """Entries created before Home Assistant recorded `created_at` carry the epoch."""
    now = dt_util.utcnow()
    await _restart(
        hass,
        created_at=dt_util.utc_from_timestamp(0),
        written=now - timedelta(hours=1),
        states=OPERATORS,
    )
    assert _read(hass, KILL) == "on" and float(_read(hass, P1)) == 58.0
