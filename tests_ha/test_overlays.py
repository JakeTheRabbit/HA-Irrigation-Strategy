"""AI overlays (custom_components/crop_steering/overlays.py) in a real Home Assistant, on the seeded
3.11.1 install, with the real controller's writes sent to it exactly as the controller sends them,
its event first. A brain move opens an overlay that goes back to the operator's value by itself at
lights-on; Undo puts the operator's value back now and Keep keeps the AI's; any other write ends it.
The numbers 3.11.1's brain wrote before the update load as plain values that never go back."""

from datetime import datetime, time, timedelta

from conftest import fixture
from homeassistant.core import Context
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_upgrade_in_place import JEV_3_11_1, KILL, _jev_3_11_1_app, _upgrade

DOMAIN = "crop_steering"
ROOM = "room:"
SHOT = "number.crop_steering_zone_1_p2_shot_size"
THRESHOLD = "number.crop_steering_zone_1_p2_vwc_threshold"


def _value(hass, entity_id):
    return float(hass.states.get(entity_id).state)


async def _call(hass, service, data, context=None):
    return await hass.services.async_call(
        DOMAIN,
        service,
        {"room_id": ROOM, **data},
        blocking=True,
        return_response=service == "overlay_get",
        context=context,
    )


async def _overlays(hass):
    return (await _call(hass, "overlay_get", {}))["overlays"]


async def _room(hass, controller_for):
    seed = fixture(JEV_3_11_1)
    entry, _seed = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    c._refresh_lights(room)
    fake.events.clear()
    fake.calls.clear()  # what the controller did on starting up
    return entry, c, fake, room


async def _write(hass, c, fake, room, entity_id, value, by="Jev", phase="P3"):
    """One controller write of zone 1's `entity_id`, sent to this Home Assistant as it sends it."""
    room.state[1]["phase"] = phase
    old = _value(hass, entity_id)
    suffix = entity_id.removeprefix("number.crop_steering_zone_1_")
    assert c._auto_write(room, 1, suffix, old, value, {}, datetime.now(), by=by)
    for event, data in fake.events:
        hass.bus.async_fire(event, data)
    await hass.async_block_till_done()
    for domain, service, data in fake.calls:
        await hass.services.async_call(domain, service, data, blocking=True)
    fake.events.clear()
    fake.calls.clear()
    return old


async def _run_until(hass, expires, seconds=1):
    async_fire_time_changed(hass, dt_util.parse_datetime(expires) + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def _log(hass):
    answer = await hass.services.async_call(
        DOMAIN, "setpoint_log_get", {"room_id": ROOM}, blocking=True, return_response=True
    )
    return [(r["who"], r["old"], r["new"]) for r in answer["changes"]]


async def test_a_brain_move_is_an_overlay_that_goes_back_at_lights_on(
    hass, hass_storage, controller_for
):
    entry, c, fake, room = await _room(hass, controller_for)
    old = await _write(hass, c, fake, room, SHOT, _value(hass, SHOT) + 1)
    [row] = await _overlays(hass)
    assert (row["entity_id"], row["zone"], row["field"], row["by"]) == (SHOT, 1, "p2_shot_size", "brain")
    assert (row["old"], row["new"]) == (old, old + 1) and _value(hass, SHOT) == old + 1
    # A night move is for the next grow-day: it runs out at the lights-on that ends that day.
    day = c._grow_day_start(room, datetime.now()) + timedelta(days=2)
    expires = dt_util.parse_datetime(row["expires"]).astimezone().replace(tzinfo=None)
    assert expires == datetime.combine(day, time(6))

    # A second notch moves the overlay; underneath it the value is still the operator's.
    await _write(hass, c, fake, room, SHOT, old + 2)
    [row] = await _overlays(hass)
    assert (row["old"], row["new"]) == (old, old + 2)

    # Kept through a reload, read back from the store.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await _overlays(hass) == [row]

    await _run_until(hass, row["expires"], seconds=-60)  # not before
    assert _value(hass, SHOT) == old + 2 and await _overlays(hass) == [row]
    await _run_until(hass, row["expires"])
    assert _value(hass, SHOT) == old and await _overlays(hass) == []
    assert (await _log(hass))[-1] == ("brain", old + 2, old)
    assert hass_storage[f"{DOMAIN}.overlays.{entry.entry_id}"]["data"]["overlays"] == []


async def test_undo_puts_the_operators_value_back_now_and_keep_keeps_the_ai_value(
    hass, controller_for, hass_admin_user
):
    _entry, c, fake, room = await _room(hass, controller_for)
    admin = Context(user_id=hass_admin_user.id)
    old = await _write(hass, c, fake, room, SHOT, _value(hass, SHOT) + 1)
    await _call(hass, "overlay_undo", {"entity_id": SHOT}, admin)
    assert _value(hass, SHOT) == old and await _overlays(hass) == []
    assert (await _log(hass))[-1] == ("operator", old + 1, old)

    # A daytime move (the hourly check) is for this grow-day: it runs out at the next lights-on.
    threshold = _value(hass, THRESHOLD) + 1
    await _write(hass, c, fake, room, THRESHOLD, threshold, phase="P2")
    [row] = await _overlays(hass)
    day = c._grow_day_start(room, datetime.now()) + timedelta(days=1)
    expires = dt_util.parse_datetime(row["expires"]).astimezone().replace(tzinfo=None)
    assert expires == datetime.combine(day, time(6))
    await _call(hass, "overlay_keep", {"entity_id": THRESHOLD}, admin)
    assert await _overlays(hass) == []
    await _run_until(hass, row["expires"])
    assert _value(hass, THRESHOLD) == threshold


async def test_any_other_write_ends_the_overlay_and_its_value_stands(
    hass, controller_for, hass_admin_user
):
    _entry, c, fake, room = await _room(hass, controller_for)
    old = await _write(hass, c, fake, room, SHOT, _value(hass, SHOT) + 1)
    [row] = await _overlays(hass)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": SHOT, "value": old + 3}, blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    assert await _overlays(hass) == []
    await _run_until(hass, row["expires"])
    assert _value(hass, SHOT) == old + 3

    # The safety put-back after a rescue shot ends it too.
    threshold = await _write(hass, c, fake, room, THRESHOLD, _value(hass, THRESHOLD) + 1)
    await _write(hass, c, fake, room, THRESHOLD, threshold, by="the AI assistant (put back)")
    assert await _overlays(hass) == []
    assert (await _log(hass))[-1] == ("safety", threshold + 1, threshold)


async def test_the_numbers_3_11_1s_brain_wrote_load_as_plain_values(
    hass, hass_storage, controller_for, monkeypatch
):
    """3.11.1's brain had been moving this room (its state says so). After the update every number it
    left is the operator's value like any other: no overlay, nothing stored, and nothing goes back."""
    seed = fixture(JEV_3_11_1)
    entry, _seed = await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    c, fake, _built, _usage, state = _jev_3_11_1_app(
        controller_for, monkeypatch, "options_3_11_1_jev_cf.json"
    )
    assert state["default"]["1"]["learn"]["jev"]["changed"]  # 3.11.1's brain had acted here
    numbers = {s.entity_id: s.state for s in hass.states.async_all("number")}
    answer = await _call(hass, "overlay_get", {})
    assert (answer["room_id"], answer["overlays"], answer["error"]) == (ROOM, [], None)
    assert not [data for _event, data in fake.events if "expires" in data]
    assert f"{DOMAIN}.overlays.{entry.entry_id}" not in hass_storage

    later = (dt_util.utcnow() + timedelta(days=3)).isoformat()
    await _run_until(hass, later)
    assert {s.entity_id: s.state for s in hass.states.async_all("number")} == numbers


async def test_keep_and_undo_tapped_on_a_phone_reach_the_overlay(
    hass, controller_for, hass_admin_user, monkeypatch
):
    """The push about the AI's move carries Keep and Undo to a phone with the Home Assistant app, and a
    tap comes back as that app's mobile_app_notification_action event, as the phone's user: Keep keeps
    the AI's value, Undo puts the operator's back, and a phone whose user is no administrator changes
    nothing, as on the page."""
    import controller
    from test_notify import _call as _notify_call
    from test_notify import _phones, _staff

    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    staff = await _staff(hass)
    received = _phones(hass, [("Grower phone", hass_admin_user), ("Staff phone", staff)])
    doc = await _notify_call(hass, hass_admin_user, "notify_get")
    await _notify_call(
        hass,
        hass_admin_user,
        "notify_save",
        expected_revision=doc["config"]["revision"],
        recipients=[
            {"service": "notify.mobile_app_grower_phone", "kinds": ["jev"]},
            {"service": "notify.mobile_app_staff_phone", "kinds": ["jev"]},
        ],
    )
    await hass.async_block_till_done()
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    c._refresh_lights(room)
    fake.events.clear()
    fake.calls.clear()
    asked = []
    monkeypatch.setattr(
        controller,
        "ha_service_response",
        lambda domain, service, data, timeout=12: asked.append(dict(data))
        or (200, {"sent_to": ["notify.mobile_app_grower_phone"], "error": None}),
    )

    async def move(value):
        old = await _write(hass, c, fake, room, SHOT, value)
        c._notify_event("jev_setpoint", room, 1, f"P2 shot {old:g} -> {value:g}", "Smaller shots.", SHOT)
        c._send_events()
        await hass.services.async_call(DOMAIN, "notify", asked.pop(), blocking=True)
        actions = received["notify.mobile_app_grower_phone"][-1]["data"]["actions"]
        return old, {a["title"]: a["action"] for a in actions}

    async def tap(action, user):
        hass.bus.async_fire(
            "mobile_app_notification_action", {"action": action}, context=Context(user_id=user.id)
        )
        await hass.async_block_till_done()

    old, actions = await move(_value(hass, SHOT) + 1)
    assert actions == {"Keep": f"CROP_STEERING_KEEP:{SHOT}", "Undo": f"CROP_STEERING_UNDO:{SHOT}"}
    await tap(actions["Undo"], staff)  # not an administrator: nothing changes
    assert _value(hass, SHOT) == old + 1 and len(await _overlays(hass)) == 1
    await tap(actions["Undo"], hass_admin_user)
    assert _value(hass, SHOT) == old and await _overlays(hass) == []
    assert (await _log(hass))[-1] == ("operator", old + 1, old)

    old, actions = await move(old + 2)  # not old + 1: the controller would not write that again so soon
    [row] = await _overlays(hass)
    await tap(actions["Keep"], hass_admin_user)
    assert await _overlays(hass) == []
    await _run_until(hass, row["expires"])
    assert _value(hass, SHOT) == old + 2
    await tap(actions["Undo"], hass_admin_user)  # nothing left to undo: nothing changes
    assert _value(hass, SHOT) == old + 2


async def test_a_claim_names_one_write_and_only_its_own_cancel_takes_it_back(
    hass, controller_for, hass_admin_user
):
    """A claim is used once: the write it named consumes it, and the same value written again later is
    the operator's."""
    _entry, c, fake, room = await _room(hass, controller_for)
    admin = Context(user_id=hass_admin_user.id)
    old = await _write(hass, c, fake, room, SHOT, _value(hass, SHOT) + 1)
    for value in (old, old + 1):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": SHOT, "value": value}, blocking=True, context=admin
        )
    assert (await _log(hass))[-3:] == [("brain", old, old + 1), ("operator", old + 1, old), ("operator", old, old + 1)]
    assert await _overlays(hass) == []

    # A cancel naming another claim leaves this one alone; a claim with no id (a controller from before
    # claims carried one) is never cancelled, and names its write as it always did.
    for claim_id in ("mine", None):
        threshold = _value(hass, THRESHOLD)
        claim = {"entity_id": THRESHOLD, "value": threshold + 1, "who": "learner"}
        hass.bus.async_fire("crop_steering_setpoint_write", {**claim, "claim_id": claim_id} if claim_id else claim)
        hass.bus.async_fire("crop_steering_setpoint_claim_cancel", {**claim, "claim_id": "another"})
        await hass.async_block_till_done()
        await hass.services.async_call(
            "number", "set_value", {"entity_id": THRESHOLD, "value": threshold + 1}, blocking=True
        )
        assert (await _log(hass))[-1] == ("learner", threshold, threshold + 1)
