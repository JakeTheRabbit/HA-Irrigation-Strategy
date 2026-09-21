"""What the MCP tools send is what the REAL `crop_steering.setup_save` accepts.

mcp-server/ has its own tests, against a mock of these services. A mock can only ever agree with
whoever wrote it: since 2.19.0 the real service refuses an active room whose mapped switches
contradict its DECLARED plumbing, the MCP payload had no `plumbing` in it at all, and both suites
were green. (Review finding on JakeTheRabbit/HA-Irrigation-Strategy#47: a declared room could
never gain or lose its pump through the MCP tools.)

These tests build the payload the way mcp-server/src/workspace.ts does: read the room with
`setup_read`, change fields, and send back `room_name`, `active`, `hardware`, `zones`, plus
`plumbing` ONLY when the room has declared one.
"""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_declared_plumbing import PUMP
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
DESCRIPTOR = "sensor.crop_steering_engine_config"


async def _service(hass, admin, name, data=None):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data or {},
        blocking=True,
        return_response=True,
        context=Context(user_id=admin.id),
    )


async def _room(hass, admin):
    (room,) = (await _service(hass, admin, "setup_read"))["rooms"]
    return room


def _payload(room, **changes):
    """mcp-server/src/workspace.ts `config(room)`, then the reviewed changes on top."""
    payload = {
        "room_name": room["room_name"],
        "active": room["active"],
        **({"plumbing": room["plumbing"]} if room.get("plumbing") else {}),
        "hardware": dict(room["hardware"]),
        "zones": room["zones"],
    }
    payload["hardware"].update(changes.pop("hardware", {}))
    return {
        "entry_id": room["entry_id"],
        "expected_revision": room["revision"],
        **payload,
        **changes,
    }


async def test_a_declared_room_loses_and_regains_its_pump_through_the_mcp_payload(
    hass, hass_admin_user
):
    hass.states.async_set(PUMP, "off")
    await _install(hass, {"plumbing": "pump_valves", "pump_switch": PUMP})
    room = await _room(hass, hass_admin_user)
    assert (room["plumbing"], room["plumbing_inferred"]) == ("pump_valves", "pump_valves")

    # The mapping alone, which is all the tools could send before: refused, and nothing saved.
    with pytest.raises(HomeAssistantError, match="pump"):
        await _service(
            hass, hass_admin_user, "setup_save", _payload(room, hardware={"pump_switch": ""})
        )
    assert (await _room(hass, hass_admin_user))["revision"] == room["revision"]

    # Layout and mapping together, in one save.
    await _service(
        hass,
        hass_admin_user,
        "setup_save",
        _payload(room, plumbing="valves_only", hardware={"pump_switch": ""}),
    )
    await hass.async_block_till_done()
    after = await _room(hass, hass_admin_user)
    assert after["revision"] == room["revision"] + 1
    assert (after["plumbing"], after["hardware"].get("pump_switch") or "") == ("valves_only", "")
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert descriptor["plumbing"] == "valves_only" and not descriptor["pump"]

    # And back again. An unchanged declared layout travels with every save, as the tools send it.
    await _service(
        hass,
        hass_admin_user,
        "setup_save",
        _payload(after, plumbing="pump_valves", hardware={"pump_switch": PUMP}),
    )
    await hass.async_block_till_done()
    again = await _room(hass, hass_admin_user)
    assert (again["plumbing"], again["hardware"]["pump_switch"]) == ("pump_valves", PUMP)
    await _service(hass, hass_admin_user, "setup_save", _payload(again, room_name="Tent A"))
    await hass.async_block_till_done()
    assert (await _room(hass, hass_admin_user))["plumbing"] == "pump_valves"


async def test_an_upgraded_room_that_never_declared_is_not_declared_by_an_mcp_save(
    hass, hass_admin_user
):
    """In-place upgrade. The payload carries no `plumbing` for a room that has none, so an
    unrelated save leaves the room undeclared and its descriptor byte-for-byte what it was (the
    controller's saved setup fingerprint depends on that)."""
    _entry, seed = await _upgrade(hass, "entry_2_18_one_switch_tent.json")
    assert "plumbing" not in seed["data"]
    room = await _room(hass, hass_admin_user)
    assert (room["plumbing"], room["plumbing_inferred"]) == ("", "valves_only")
    payload = _payload(room, room_name="GT1")
    assert "plumbing" not in payload

    await _service(hass, hass_admin_user, "setup_save", payload)
    await hass.async_block_till_done()
    after = await _room(hass, hass_admin_user)
    assert (after["room_name"], after["plumbing"]) == ("GT1", "")
    assert "plumbing" not in hass.states.get(DESCRIPTOR).attributes

    # Declaring it is an explicit change, and from then on it is enforced.
    await _service(hass, hass_admin_user, "setup_save", _payload(after, plumbing="valves_only"))
    await hass.async_block_till_done()
    declared = await _room(hass, hass_admin_user)
    assert declared["plumbing"] == "valves_only"
    assert hass.states.get(DESCRIPTOR).attributes["plumbing"] == "valves_only"
