"""history_revert of saved store sections (journal_api.py) through a real Home Assistant: each kind is
saved again from its old copy and read back from the store (verified), a save that did not take is
refused, never claimed done; the room setup goes back whole or not at all, and only past its safety
checks; a feed probe calibration is put back to the one before it."""

from copy import deepcopy

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_calibration_wizard import CORRECTED, PH, TEMP, _calibrate
from test_presets import ROOM, SINCE, _three_zones
from test_setup_entry import _install

from custom_components.crop_steering.generated.ids import new_id

DOMAIN = "crop_steering"
TENT = "room:tent_"
ENGINE = "switch.crop_steering_tent_engine_enabled"
UNSAVED = ("revision", "safety", "commissioning")


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


async def _latest(hass, user, room_id, section):
    """The newest change of `section` in the room, once the journal has it."""
    await hass.data[DOMAIN]["_journal"]._ready.wait()
    await hass.async_block_till_done()
    changes = (await _call(hass, user, "history_changes", room_id=room_id, since=SINCE))[
        "changes"
    ]
    return next(c for c in changes if c["section"] == section)


async def _revert(hass, user, change):
    return await _call(hass, user, "history_revert", api=2, event_id=change["id"])


def _refused(out):
    assert out["ok"] is False and out["error"]["code"] == "guard_refused", out
    assert out["data"]["readback"] == "refused"


# ------------------------------------------------------------------ timers
PROGRAM = {
    "name": "Mothers AM",
    "type": "recycle",
    "zones": [3],
    "duration_s": 120,
    "interval_min": 30,
    "window": {"kind": "custom", "from": "08:00", "to": "12:00"},
}


async def _timer_deleted(hass, user):
    saved = await _call(
        hass, user, "timer_program_set", room_id=ROOM, expected_revision=0, program=PROGRAM
    )
    await _call(
        hass,
        user,
        "timer_program_delete",
        room_id=ROOM,
        expected_revision=1,
        id=saved["program"]["id"],
    )
    return saved["program"], await _latest(hass, user, ROOM, "programs")


async def test_a_deleted_timer_comes_back_under_a_new_id_and_reads_back(
    hass, hass_admin_user
):
    await _three_zones(hass)
    program, deleted = await _timer_deleted(hass, hass_admin_user)
    out = await _revert(hass, hass_admin_user, deleted)
    assert out["ok"] is True and out["readback"]["status"] == "verified", out
    (timer,) = (await _call(hass, hass_admin_user, "timer_program_list", room_id=ROOM))[
        "programs"
    ]
    assert (timer["name"], timer["duration_s"]) == ("Mothers AM", 120)
    assert timer["id"] != program["id"]
    assert out["data"]["renewed"] == [
        {"name": "Mothers AM", "old_id": program["id"], "id": timer["id"]}
    ]


async def test_a_timer_put_back_that_did_not_save_is_refused(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import timers_api

    await _three_zones(hass)
    _program, deleted = await _timer_deleted(hass, hass_admin_user)

    async def nothing(self, expected_revision, programs, who=None):
        return {"programs": [], "revision": expected_revision}

    monkeypatch.setattr(timers_api.TimerPrograms, "set_programs", nothing)
    _refused(await _revert(hass, hass_admin_user, deleted))


# ------------------------------------------------------------------ presets
async def _preset_saved(hass, user):
    await _call(
        hass,
        user,
        "preset_save",
        name="Week 3",
        scope="targets",
        expected_revision=0,
        **{"from": {"room_id": ROOM, "zone": 3}},
    )
    return await _latest(hass, user, ROOM, "presets")


async def test_a_preset_save_is_put_back(hass, hass_admin_user):
    await _three_zones(hass)
    saved = await _preset_saved(hass, hass_admin_user)
    out = await _revert(hass, hass_admin_user, saved)
    assert out["ok"] is True and out["readback"]["status"] == "verified", out
    assert (await _call(hass, hass_admin_user, "preset_list"))["presets"] == []


async def test_a_preset_put_back_that_did_not_save_is_refused(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import site_api

    await _three_zones(hass)
    saved = await _preset_saved(hass, hass_admin_user)

    async def nothing(self, expected_revision, change, who, room_id):
        return None, expected_revision

    monkeypatch.setattr(site_api.SiteStore, "_save_presets", nothing)
    _refused(await _revert(hass, hass_admin_user, saved))


# ------------------------------------------------------------------ supply
async def _supply_saved(hass, user):
    await _call(
        hass,
        user,
        "supply_save",
        expected_revision=0,
        irrigation_pumps=[],
        zone_meters={ROOM: {"1": "sensor.meter_1"}},
    )
    return await _latest(hass, user, ROOM, "supply")


async def test_a_supply_save_is_put_back(hass, hass_admin_user):
    await _three_zones(hass)
    saved = await _supply_saved(hass, hass_admin_user)
    out = await _revert(hass, hass_admin_user, saved)
    assert out["ok"] is True and out["readback"]["status"] == "verified", out
    assert (await _call(hass, hass_admin_user, "supply_get"))["zone_meters"] == {}


async def test_a_supply_put_back_that_did_not_save_is_refused(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import site_api

    await _three_zones(hass)
    saved = await _supply_saved(hass, hass_admin_user)

    async def nothing(self, data, who=None):
        return {"readback": {"status": "ok"}}

    monkeypatch.setattr(site_api.SiteStore, "save", nothing)
    _refused(await _revert(hass, hass_admin_user, saved))


# ------------------------------------------------------------------ probe offsets
async def _offset_set(hass, user):
    revision = (await _call(hass, user, "calibration_get", room_id=ROOM))["revision"]
    await _call(
        hass,
        user,
        "probe_offset_set",
        room_id=ROOM,
        entity_id="sensor.vwc",
        offset=1.5,
        expected_revision=revision,
    )
    return await _latest(hass, user, ROOM, "probe_user_offsets")


async def test_a_probe_offset_is_put_back_per_probe(hass, hass_admin_user):
    await _three_zones(hass)
    changed = await _offset_set(hass, hass_admin_user)
    out = await _revert(hass, hass_admin_user, changed)
    assert out["ok"] is True and out["readback"]["status"] == "verified", out
    assert out["data"]["entities"] == [
        {"entity_id": "sensor.vwc", "readback": "verified"}
    ]
    calibration = await _call(hass, hass_admin_user, "calibration_get", room_id=ROOM)
    assert calibration["probe_user_offsets"] == {}


async def test_a_probe_offset_put_back_that_did_not_save_is_refused(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import calibration

    await _three_zones(hass)
    changed = await _offset_set(hass, hass_admin_user)

    async def nothing(self, data, who=None):
        return {}

    monkeypatch.setattr(calibration.CalibrationStore, "probe_offset_set", nothing)
    out = await _revert(hass, hass_admin_user, changed)
    _refused(out)
    assert out["data"]["entities"] == [{"entity_id": "sensor.vwc", "readback": "refused"}]


# ------------------------------------------------------------------ feed probe calibration
async def _calibrated(hass, user):
    hass.states.async_set(TEMP, "21.3", {"unit_of_measurement": "°C"})
    hass.states.async_set(PH, "6.1", {"unit_of_measurement": "pH"})
    entry = await _install(hass, {"feed_ph_sensor": PH, "tank_temperature_sensor": TEMP})
    await _calibrate(hass, user, entry)
    return await _latest(hass, user, TENT, "calibration")


async def test_a_feed_probe_calibration_is_put_back(hass, hass_admin_user):
    committed = await _calibrated(hass, hass_admin_user)
    assert committed["revertible"] is True
    out = await _revert(hass, hass_admin_user, committed)
    assert out["ok"] is True and out["readback"]["status"] == "verified", out
    await hass.async_block_till_done()
    assert hass.states.get(CORRECTED).state == "unknown"


async def test_a_calibration_put_back_that_did_not_take_is_refused(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import calibration

    committed = await _calibrated(hass, hass_admin_user)

    async def nothing(self, probe, who=None):
        return {}

    monkeypatch.setattr(calibration.CalibrationStore, "revert", nothing)
    _refused(await _revert(hass, hass_admin_user, committed))


# ------------------------------------------------------------------ room setup
def _saved(room):
    return {k: v for k, v in room.items() if k not in UNSAVED}


async def _renamed(hass, user):
    before = (await _call(hass, user, "setup_read"))["rooms"][0]
    sent = deepcopy(before)  # the save takes what it is sent apart
    await _call(
        hass,
        user,
        "setup_save",
        entry_id=sent["entry_id"],
        expected_revision=sent["revision"],
        room_name="Back room",
        active=sent["active"],
        zones=sent["zones"],
        hardware=sent["hardware"],
    )
    return before, await _latest(hass, user, TENT, "room")


async def test_a_setup_put_back_restores_the_setup_as_it_was(hass, hass_admin_user):
    await _install(hass)
    before, renamed = await _renamed(hass, hass_admin_user)
    out = await _revert(hass, hass_admin_user, renamed)
    assert out["ok"] is True and out["readback"]["status"] == "verified", out
    after = (await _call(hass, hass_admin_user, "setup_read"))["rooms"][0]
    assert _saved(after) == _saved(before)


async def test_a_setup_put_back_is_held_by_the_safety_checks(hass, hass_admin_user):
    await _install(hass)
    _before, renamed = await _renamed(hass, hass_admin_user)
    await hass.services.async_call("switch", "turn_on", {"entity_id": ENGINE}, blocking=True)
    out = await _revert(hass, hass_admin_user, renamed)
    assert out["ok"] is False and "must read OFF" in out["error"]["message"], out
    with pytest.raises(HomeAssistantError, match="must read OFF"):
        await _call(hass, hass_admin_user, "history_revert", event_id=renamed["id"])
    room = (await _call(hass, hass_admin_user, "setup_read"))["rooms"][0]
    assert room["room_name"] == "Back room"


async def test_a_setup_put_back_is_whole_or_not_at_all(hass, hass_admin_user):
    await _install(hass)
    _before, renamed = await _renamed(hass, hass_admin_user)
    # A change whose old copy lacks a part of the setup the room has now (hardware).
    partial = {
        "v": 1,
        "id": new_id(),
        "ts": renamed["ts"],
        "kind": "config.changed",
        "zone": None,
        "outcome": "ok",
        "source": {"actor": "manual"},
        "correlation": {},
        "data": {
            "store": "setup",
            "section": "room",
            "old": {k: v for k, v in renamed["old"].items() if k != "hardware"},
            "new": renamed["new"],
            "diff": [],
        },
    }
    await _call(hass, hass_admin_user, "journal_append", room_id=TENT, events=[partial])
    with pytest.raises(HomeAssistantError, match="This change can't be put back"):
        await _call(hass, hass_admin_user, "history_revert", event_id=partial["id"])
    room = (await _call(hass, hass_admin_user, "setup_read"))["rooms"][0]
    assert room["room_name"] == "Back room"


async def test_a_setup_put_back_that_did_not_save_is_refused(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import setup_api

    await _install(hass)
    _before, renamed = await _renamed(hass, hass_admin_user)

    async def nothing(hass, payload):
        return setup_api.setup_room(hass, setup_api._entry(hass, payload["entry_id"]))

    monkeypatch.setattr(setup_api, "save_setup", nothing)
    _refused(await _revert(hass, hass_admin_user, renamed))
