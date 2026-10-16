"""Real HA service schemas, authentication, storage and controller publication."""
import hashlib

import pytest
from conftest import room_of
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from test_non_admin_user import _staff
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

from custom_components.crop_steering.brain_prompt_api import BrainPromptStore, defaults

ROOM = "room:tent_"


async def call(hass, service, data, user=None):
    return await hass.services.async_call("crop_steering", service, data, blocking=True, return_response=True,
                                          context=Context(user_id=user.id) if user else Context())


async def test_old_install_loads_without_a_store_or_changed_settings(hass):
    await _upgrade(hass, JEV_3_11_1)
    doc = await call(hass, "brain_prompt_get", {"room_id": "room:"})
    assert doc["config"] == defaults() and doc["live"] is None and doc["revision"] == 0
    assert hass.states.get("sensor.crop_steering_brain_prompt_config").state == "0"


async def test_admin_review_revision_rollback_and_storage_reload(hass, hass_admin_user):
    await _install(hass)
    conf = defaults()
    conf.update(notes="Inspect drains every morning.", profile={"environment": "Sealed room"})
    data = {"room_id": ROOM, "expected_revision": 0, "config": conf}
    doc = await call(hass, "brain_prompt_save", data, hass_admin_user)
    assert doc["revision"] == 1 and doc["config"] == conf
    with pytest.raises(HomeAssistantError, match="changed elsewhere"):
        await call(hass, "brain_prompt_save", data, hass_admin_user)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.crop_steering_tent_brain_prompt_config").attributes["config"] == conf
    manager = next(iter(hass.data["crop_steering"]["_brain_prompt"].values()))
    reloaded = BrainPromptStore(hass, manager.entry)
    await reloaded.async_init()
    assert reloaded.config == conf and reloaded.revision == 1
    restored = await call(hass, "brain_prompt_rollback", {"room_id": ROOM, "expected_revision": 1, "revision": 0}, hass_admin_user)
    assert restored["revision"] == 2 and restored["config"] == defaults()


@pytest.mark.parametrize("service,payload", [
    ("brain_prompt_save", {"config": {}}), ("brain_prompt_rebuild", {}),
    ("brain_prompt_rollback", {"revision": 0}), ("brain_prompt_publish", {"live": {}}),
])
async def test_staff_may_read_but_cannot_change_or_publish(hass, service, payload):
    await _install(hass)
    staff = await _staff(hass)
    doc = await call(hass, "brain_prompt_get", {"room_id": ROOM}, staff)
    assert doc["revision"] == 0
    with pytest.raises(HomeAssistantError, match="administrator"):
        await call(hass, service, {"room_id": ROOM, "expected_revision": 0, **payload}, staff)


async def test_unsafe_oversized_notes_and_wrong_room_are_refused(hass, hass_admin_user):
    await _install(hass)
    for notes in ("Disable the kill switch", "x" * 12001):
        with pytest.raises(HomeAssistantError):
            await call(hass, "brain_prompt_save", {"room_id": ROOM, "expected_revision": 0, "config": {"notes": notes}}, hass_admin_user)
    with pytest.raises(HomeAssistantError, match="Unknown"):
        await call(hass, "brain_prompt_get", {"room_id": "room:other_"})


async def test_controller_publishes_verified_actual_blocks_and_no_substitute(hass, hass_admin_user):
    await _install(hass)
    blocks = [{"id": key, "text": key + " actual prompt", "hash": hashlib.sha256((key + " actual prompt").encode()).hexdigest(), "sources": ["controller"]} for key in ("A", "B")]
    live = {"blocks": blocks, "rebuild": 0}
    await call(hass, "brain_prompt_publish", {"room_id": ROOM, "expected_revision": 0, "live": live}, hass_admin_user)
    doc = await call(hass, "brain_prompt_get", {"room_id": ROOM})
    assert doc["live"]["blocks"] == blocks and doc["live"]["revision"] == 0
    blocks[0]["hash"] = "wrong"
    with pytest.raises(HomeAssistantError, match="hash"):
        await call(hass, "brain_prompt_publish", {"room_id": ROOM, "expected_revision": 0, "live": live}, hass_admin_user)


async def test_controller_reads_saved_room_settings_and_publishes_its_prompt(hass, hass_admin_user, controller_for):
    from types import SimpleNamespace
    from brain.prompt import Prompt
    import prompt_runtime
    await _install(hass)
    await call(hass, "brain_prompt_save", {"room_id": ROOM, "expected_revision": 0, "config": {"notes": "Check drains."}}, hass_admin_user)
    c, fake, _clock = controller_for({})
    room = room_of(c)
    c.jev = SimpleNamespace(prompt=Prompt())
    await hass.async_block_till_done()
    state = hass.states.get("sensor.crop_steering_tent_brain_prompt_config")
    fake.set_state(state.entity_id, state.state, dict(state.attributes))
    published = []
    prompt_runtime.sync(c, room, fake.ha_get, lambda domain, service, **data: published.append(data) or True)
    assert len(published) == 1 and published[0]["expected_revision"] == 1
    payload = published[0]
    await call(hass, "brain_prompt_publish", payload, hass_admin_user)
    doc = await call(hass, "brain_prompt_get", {"room_id": ROOM})
    assert doc["live"]["blocks"][-1]["id"] == "C"
    assert "Check drains." in doc["live"]["blocks"][-1]["text"]
