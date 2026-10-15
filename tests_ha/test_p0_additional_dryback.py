"""P0 additional dryback, in a real Home Assistant with the real controller.

P0 ends once moisture is this % below the highest reading since lights-on, the small extra dryback
before the first shot. It is a number per zone. A room set up from this release on starts each zone
at 3; a room updated in place starts each zone at 0 (off), so its P0 decides exactly as before, and
the older P0 drop percent it already has keeps its value and stays unread. A controller whose
integration is older than the setting uses 0 without raising the missing-setting alert.
"""

import dataclasses
import re
from datetime import datetime

import pytest
import test_upgrade_in_place
from conftest import fixture, room_of
from crop_steering_engine import decide
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

ROOM = "number.crop_steering_p0_additional_dryback"
OLD = "number.crop_steering_zone_1_p0_dryback_drop_percent"


def _zones(hass, prefix=""):
    """Every zone's P0 additional dryback number, in zone order."""
    zone = re.compile(rf"number\.crop_steering_{prefix}zone_\d+_p0_additional_dryback$")
    return sorted(s.entity_id for s in hass.states.async_all("number") if zone.match(s.entity_id))


def _morning(snap, p):
    """A grow-day's morning from the zone's reading at lights-on: a reading every 10 minutes, the
    slab drying 0.6 points each, until the P0 timeout."""
    top = snap.vwc or p.p2_threshold + 15
    for minutes in range(0, int(p.p0_max_wait_min) + 10, 10):
        vwc = top - 0.06 * minutes
        yield dataclasses.replace(
            snap,
            phase="P0",
            vwc=vwc,
            peak_vwc=top,
            dryback_pct=(top - vwc) / top * 100,
            phase_minutes=minutes,
            lights_on=True,
            lights_just_on=False,
            new_grow_day=False,
        )


def _p0_before(s, p):
    """P0 as it was decided before the setting existed (v3.11.1)."""
    out = s.vwc <= p.p2_threshold or s.dryback_pct >= p.dryback_target
    return "P1" if out or s.phase_minutes >= p.p0_max_wait_min else "P0"


async def test_a_new_room_starts_every_zone_at_three_percent(hass):
    await _install(hass)  # a new room has a slug: the wizard's "Tent" is tent_
    zones = _zones(hass, "tent_")
    assert zones and hass.states.get(ROOM.replace("crop_steering_", "crop_steering_tent_")) is None
    for entity_id in zones:
        state = hass.states.get(entity_id)
        assert float(state.state) == 3
        assert (state.attributes["min"], state.attributes["max"]) == (0, 40)
        assert state.attributes["unit_of_measurement"] == "%"


async def test_a_new_room_waits_for_the_extra_drop_before_the_first_shot(hass, controller_for):
    await _install(hass)
    c, _fake, _clock = controller_for({})
    room = room_of(c)
    c.loop_once(datetime.now())
    snap, p = c._snapshot(room, 1, datetime.now(), True, False)
    assert p.p0_additional_dryback == 3
    top = p.p2_threshold + 10

    def at(drop_pct):
        vwc = top * (1 - drop_pct / 100)
        return dataclasses.replace(
            snap, phase="P0", vwc=vwc, peak_vwc=top, dryback_pct=drop_pct, phase_minutes=1,
            lights_on=True, lights_just_on=False, new_grow_day=False,
        )

    assert decide(at(2.5), p)[0] == "P0"
    moved = decide(at(3.1), p)
    assert moved[0] == "P1" and moved[4].startswith("P0 dryback done")


@pytest.mark.parametrize("name", ["entry_2_17_wizard.json", UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_updated_in_place_starts_at_zero_and_nothing_else_moves(
    hass, monkeypatch, name
):
    seed = fixture(name)
    seed["operator_tuned_numbers"][OLD] = "24.0"  # the older P0 setting, as the operator left it
    monkeypatch.setattr(test_upgrade_in_place, "fixture", lambda _name: seed)
    await _upgrade(hass, name, registry_ids=seed.get("registry"))
    zones = _zones(hass)
    assert len(zones) == seed["data"]["num_zones"] and hass.states.get(ROOM) is None
    assert [float(hass.states.get(e).state) for e in zones] == [0] * len(zones)
    assert hass.states.get(OLD).state == "24.0"
    for entity_id, saved in seed["operator_tuned_numbers"].items():
        tuned = saved[0] if isinstance(saved, list) else saved
        state = hass.states.get(entity_id).state
        if entity_id.startswith("number."):
            assert float(state) == float(tuned), entity_id
        else:
            assert state == tuned, entity_id


async def test_an_updated_room_decides_p0_exactly_as_before(hass, controller_for):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    c.loop_once(datetime.now())
    for zone in sorted(room.state):
        snap, p = c._snapshot(room, zone, datetime.now(), True, False)
        assert p.p0_additional_dryback == 0
        table = list(_morning(snap, p))
        assert [decide(s, p)[0] for s in table] == [_p0_before(s, p) for s in table]


async def test_a_controller_updated_ahead_of_a_3_11_1_integration_keeps_p0_off(
    hass, controller_for
):
    """Only the controller app updated: the room's integration is 3.11.1's, which has no such number."""
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id in _zones(hass):
        hass.states.async_remove(entity_id)
    assert _zones(hass) == []
    c, _fake, _clock = controller_for({})
    room = c.rooms[0]
    for zone in sorted(room.state):
        assert c._params(room, zone).p0_additional_dryback == 0
    c.loop_once(datetime.now())
    assert ROOM not in c._defaulted_this_loop and ROOM not in c._defaulted
