"""The room's heartbeat between two controllers, in a REAL Home Assistant over its real REST API.

The duplicate-controller guard (CS-609) leans on three things a fake cannot prove: Home Assistant moves a
state's `last_updated` on every beat, answers 404 for a state it does not have, and does not restore a
state set over REST after a restart. Here the controller's heartbeat writes and the guard's reads go to Home
Assistant's real `POST`/`GET /api/states` with an administrator's token; the room's other entities are the
controller_for mirror (conftest). Only the HTTP listener's start is stood in for (conftest.real_api), and
the panel's static files, which need that listener.

H4: the first start after an in-place update from 2.25.1 or 3.11.1 reads that version's fresh beat (no id)
and holds, then carries on by itself. H5: no heartbeat (a restarted Home Assistant) never holds. H6: the
integration accepts the new beat.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import controller
import pytest
import requests
from conftest import switch_calls
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.restore_state import async_get as restore_state
from test_real_flow import VALVE
from test_setup_entry import _install

from custom_components.crop_steering import health, setup_api
from custom_components.crop_steering.const import DOMAIN

BEAT = "sensor.crop_steering_ai_heartbeat"
KILL = "switch.crop_steering_engine_enabled"
ARMED = (KILL, "switch.crop_steering_system_enabled", "switch.crop_steering_auto_irrigation_enabled",
         "switch.crop_steering_zone_1_enabled")
REAL = {name: getattr(controller, name) for name in ("ha_get_status", "ha_set")}
# The heartbeat each version wrote (its controller.py _heartbeat), last_beat a naive local time.
OLD_BEATS = {
    "2.25.1": {"engine": "f2-control", "controller_version": "2.25.1", "enable_flag": KILL,
               "hardware_fault": None},
    "3.11.1": {"engine": "f2-control", "controller_version": "3.11.1", "enable_flag": KILL,
               "hardware_fault": None, "strategy_snapshot_version": 1, "setup_lifecycle_version": 1,
               "strategy_required": False, "strategy_error": None, "setup_revision": 1,
               "setup_active": True, "setup_pending": None, "room_active": True},
}


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    """Home Assistant's real `http` and `api` (conftest.real_api); the frontend is marked loaded."""
    hass.config.components.add("frontend")
    yield


@pytest.fixture
async def api(hass, real_api, hass_access_token, monkeypatch):
    """The installed room, with the controller's heartbeat going over the real REST API."""
    monkeypatch.setattr(hass.http, "async_register_static_paths", AsyncMock(), raising=False)
    await _install(hass)
    monkeypatch.setattr(controller, "BASE", real_api)
    monkeypatch.setattr(controller, "HDR", {"Authorization": f"Bearer {hass_access_token}",
                                            "Content-Type": "application/json"})
    return real_api, {"Authorization": f"Bearer {hass_access_token}"}


def wire(c, fake, monkeypatch):
    """The heartbeat's reads and writes go to the real Home Assistant; everything else stays on the fake."""
    monkeypatch.setattr(controller, "ha_get_status", REAL["ha_get_status"])

    def ha_set(entity, state, attributes=None, timeout=8):
        if entity == BEAT:
            return REAL["ha_set"](entity, state, attributes, timeout=timeout)
        return fake.ha_set(entity, state, attributes, timeout)

    monkeypatch.setattr(controller, "ha_set", ha_set)


def due(c, fake):
    """Zone 1 armed, dry and in P2 for four hours: its shot is due on the next pass that runs it."""
    for switch in ARMED:
        fake.set_state(switch, "on")
    fake.set_state(VALVE, "off")
    fake.set_state("sensor.crop_steering_vwc_zone_1", "30", {"unit_of_measurement": "%"})
    fake.set_state("sensor.crop_steering_ec_zone_1", "3.1", {"unit_of_measurement": "mS/cm"})
    now = datetime.now()
    fake.set_state("number.crop_steering_lights_on_hour", str((now.hour - 1) % 24))
    fake.set_state("number.crop_steering_lights_off_hour", str((now.hour + 3) % 24))
    room = c.rooms[0]
    room.state[1].update(phase="P2", last_shot=now - timedelta(hours=4), last_phase_change=now - timedelta(hours=5))
    room._was_lights_on = True
    return room


def read(base, auth):
    answer = requests.get(f"{base}/states/{BEAT}", headers=auth, timeout=5)
    return answer.status_code, (answer.json() if answer.status_code == 200 else None)


@pytest.mark.parametrize("version", sorted(OLD_BEATS))
async def test_h4_the_first_start_after_an_update_holds_3_minutes_then_waters(
    hass, api, controller_for, monkeypatch, version
):
    base, auth = api
    off_by = timedelta(hours=13)  # only last_updated can make it fresh
    old = {**OLD_BEATS[version], "last_beat": (datetime.now() + off_by).isoformat()}
    posted = await hass.async_add_executor_job(
        lambda: requests.post(f"{base}/states/{BEAT}", headers=auth, json={"state": "healthy", "attributes": old},
                              timeout=5))
    assert posted.status_code in (200, 201)
    c, fake, clock = controller_for({"enable_flag": KILL})
    wire(c, fake, monkeypatch)
    room = due(c, fake)
    # (a) its own id, made beside state.json: the data folder had none.
    beside = Path(os.environ["F2_STATE_PATH"]).parent / "instance_id"
    assert beside.read_text(encoding="utf-8").strip() == c.instance_id
    # (b) the guard's first read, as at start, is the real GET: the old version's beat holds the room.
    c._guard.clear()
    await hass.async_add_executor_job(c._guard_read, room)
    assert c.duplicate_hold(room)
    # (c), (d), (f): each pass holds and switches nothing on; its own beat is a real POST whose
    # last_updated Home Assistant moves on every beat.
    stamps = []
    for _minute in range(3):
        await hass.async_add_executor_job(c.loop_once, datetime.now())
        status, beat = await hass.async_add_executor_job(read, base, auth)
        assert status == 200 and beat["attributes"]["controller_instance"] == c.instance_id
        stamps.append(beat["last_updated"])
        clock.sleep(59)
    assert len(set(stamps)) == 3
    assert ("turn_on", VALVE) not in switch_calls(fake)
    assert [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
            and d["notification_id"] == "f2_duplicate_default"]
    # (g) 3 min of the clock past the pass that saw the old beat: it carries on, with no operator action.
    clock.sleep(181 - 3 * 59)
    assert not c.duplicate_hold(room)
    await hass.async_add_executor_job(c.loop_once, datetime.now())
    assert ("turn_on", VALVE) in switch_calls(fake)


async def test_h5_a_restarted_home_assistant_has_no_heartbeat_and_never_holds(
    hass, api, controller_for, monkeypatch
):
    base, auth = api
    assert (await hass.async_add_executor_job(read, base, auth))[0] == 404  # before any controller runs
    c, fake, _clock = controller_for({"enable_flag": KILL})
    wire(c, fake, monkeypatch)
    room = due(c, fake)
    await hass.async_add_executor_job(c.loop_once, datetime.now())
    assert (await hass.async_add_executor_job(read, base, auth))[0] == 200  # its beat, a real POST
    # A state set over REST is no entity's: Home Assistant's restore-state dump never holds it, so after a
    # restart there is no heartbeat until a controller writes one.
    assert BEAT not in {stored.state.entity_id for stored in restore_state(hass).async_get_stored_states()}
    hass.states.async_remove(BEAT)  # what the restart leaves
    assert (await hass.async_add_executor_job(read, base, auth))[0] == 404
    again, fake, _clock = controller_for({"enable_flag": KILL})  # the same data folder: the same id
    wire(again, fake, monkeypatch)
    room = due(again, fake)
    again._guard.clear()
    await hass.async_add_executor_job(again._guard_read, room)
    assert not again.duplicate_hold(room)
    await hass.async_add_executor_job(again.loop_once, datetime.now())
    assert ("turn_on", VALVE) in switch_calls(fake)
    assert not [d for dom, svc, d in fake.calls if d.get("notification_id") == "f2_duplicate_default"]


@pytest.mark.parametrize("version", [None, *sorted(OLD_BEATS)])
async def test_h6_the_integration_accepts_the_new_beat_and_the_old_ones(
    hass, api, controller_for, monkeypatch, version
):
    base, auth = api
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    if version is None:
        c, fake, _clock = controller_for({"enable_flag": KILL})
        wire(c, fake, monkeypatch)
        await hass.async_add_executor_job(c._heartbeat, c.rooms[0], datetime.now(), None)
        assert hass.states.get(BEAT).attributes["controller_instance"] == c.instance_id
        assert hass.states.get(BEAT).attributes["controller_runtime"] == "addon"
    else:
        old = {**OLD_BEATS[version], "last_beat": datetime.now().isoformat()}
        await hass.async_add_executor_job(
            lambda: requests.post(f"{base}/states/{BEAT}", headers=auth,
                                  json={"state": "healthy", "attributes": old}, timeout=5))
    health.run_health_check(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "engine_offline") is None
    assert setup_api.engine_flag(hass, dict(entry.data)) == KILL
