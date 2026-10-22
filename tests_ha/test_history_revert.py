"""history_revert (journal_api.py) through a real Home Assistant: an operator's setting change is put
back to its old value, read back, and journaled as a manual "put back" caused by the change; a
value that moved since, a non-admin and a refused read-back are never claimed done; a timer
program change is saved again from its old copy."""

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_presets import ROOM, SINCE, _three_zones, number

DOMAIN = "crop_steering"
SHOT = number(1, "p2_shot_size")


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


async def _call(hass, user, service, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def _settled(hass):
    await hass.data[DOMAIN]["_journal"]._ready.wait()
    await hass.async_block_till_done()


async def _operator_sets(hass, user, value):
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": SHOT, "value": value},
        blocking=True,
        context=Context(user_id=user.id),
    )
    await _settled(hass)
    changes = (await _call(hass, user, "history_changes", room_id=ROOM, since=SINCE))[
        "changes"
    ]
    return next(c for c in changes if c["key"] == "p2_shot_size" and c["new"] == value)


async def test_revert_writes_the_old_value_back_and_journals_manual_with_causation(
    hass, hass_admin_user
):
    await _three_zones(hass)
    old = float(hass.states.get(SHOT).state)
    change = await _operator_sets(hass, hass_admin_user, old + 1.5)
    assert (change["actor"], change["user_id"], change["kind"]) == (
        "manual",
        hass_admin_user.id,
        "setpoint",
    )
    assert change["user_name"] == hass_admin_user.name and change["revertible"] is True

    out = await _call(hass, hass_admin_user, "history_revert", api=2, event_id=change["id"])
    assert out["ok"] is True, out
    assert out["readback"]["status"] == "verified"
    assert out["data"]["reverted_event_id"] == change["id"]
    assert float(hass.states.get(SHOT).state) == old
    await _settled(hass)
    events = (
        await _call(
            hass,
            hass_admin_user,
            "journal_query",
            room_id=ROOM,
            since=SINCE,
            kinds=["target.changed"],
        )
    )["events"]
    (put_back,) = [e for e in events if e["correlation"]["causation_id"] == change["id"]]
    assert put_back["id"] == out["data"]["new_event_id"] and put_back["id"] in out["event_ids"]
    assert put_back["source"]["actor"] == "manual"
    assert put_back["source"]["detail"] == "put back"
    assert (put_back["data"]["old"], put_back["data"]["new"]) == (old + 1.5, old)
    assert put_back["readback"] == "verified"
    # Once: the setting no longer holds the change's value, so a second put back is stale.
    again = await _call(hass, hass_admin_user, "history_revert", api=2, event_id=change["id"])
    assert again["ok"] is False and again["error"]["code"] == "stale_revision"
    with pytest.raises(HomeAssistantError, match="has changed since"):
        await _call(hass, hass_admin_user, "history_revert", event_id=change["id"])
    assert float(hass.states.get(SHOT).state) == old


async def test_only_an_admin_may_put_a_change_back(hass, hass_admin_user, hass_read_only_user):
    await _three_zones(hass)
    old = float(hass.states.get(SHOT).state)
    change = await _operator_sets(hass, hass_admin_user, old + 1)
    out = await _call(
        hass, hass_read_only_user, "history_revert", api=2, event_id=change["id"]
    )
    assert out["ok"] is False and out["error"]["code"] == "forbidden"
    # Reading is open to every signed-in user.
    read = await _call(hass, hass_read_only_user, "history_changes", since=SINCE)
    assert change["id"] in {c["id"] for c in read["changes"]}
    assert float(hass.states.get(SHOT).state) == old + 1


async def test_a_put_back_that_does_not_read_back_is_refused_not_done(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import presets

    await _three_zones(hass)
    old = float(hass.states.get(SHOT).state)
    change = await _operator_sets(hass, hass_admin_user, old + 1)

    async def ignored(hass, writes, pending, errors, context):  # the entity takes nothing
        pending.clear()

    monkeypatch.setattr(presets, "_write_all", ignored)
    out = await _call(hass, hass_admin_user, "history_revert", api=2, event_id=change["id"])
    assert out["ok"] is False and out["error"]["code"] == "guard_refused"
    assert out["data"]["readback"] == "refused"
    assert float(hass.states.get(SHOT).state) == old + 1


async def test_a_timer_program_change_is_saved_again_from_its_old_copy(
    hass, hass_admin_user
):
    await _three_zones(hass)
    program = {
        "name": "Mothers AM",
        "type": "recycle",
        "zones": [3],
        "duration_s": 120,
        "interval_min": 30,
        "window": {"kind": "custom", "from": "08:00", "to": "12:00"},
    }
    saved = await _call(
        hass,
        hass_admin_user,
        "timer_program_set",
        room_id=ROOM,
        expected_revision=0,
        program=program,
    )
    await _call(
        hass,
        hass_admin_user,
        "timer_program_set",
        room_id=ROOM,
        expected_revision=1,
        program={**saved["program"], "duration_s": 90},
    )
    await _settled(hass)
    changes = (
        await _call(
            hass, hass_admin_user, "history_changes", room_id=ROOM, since=SINCE, kinds=["setup"]
        )
    )["changes"]
    edit = changes[0]  # newest first: the 120 s -> 90 s edit
    assert (edit["section"], edit["revertible"]) == ("programs", True)
    out = await _call(hass, hass_admin_user, "history_revert", api=2, event_id=edit["id"])
    assert out["ok"] is True, out
    (timer,) = (await _call(hass, hass_admin_user, "timer_program_list", room_id=ROOM))[
        "programs"
    ]
    assert (timer["id"], timer["duration_s"]) == (saved["program"]["id"], 120)
    await _settled(hass)
    events = (
        await _call(
            hass,
            hass_admin_user,
            "journal_query",
            room_id=ROOM,
            since=SINCE,
            kinds=["config.changed"],
        )
    )["events"]
    assert events[-1]["correlation"]["causation_id"] == edit["id"]
    assert events[-1]["source"]["detail"] == "put back"
    # The revision moved: a caller holding the old one is told so.
    stale = await _call(
        hass,
        hass_admin_user,
        "history_revert",
        api=2,
        event_id=changes[1]["id"],
        expected_revision=2,
    )
    assert stale["ok"] is False and stale["error"]["code"] == "stale_revision"
    assert stale["error"]["current_revision"] == 3
