"""Timed overrides exercise the real switch lifecycle with an in-memory HA clock."""

import asyncio
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import services  # noqa: E402
from custom_components.crop_steering.const import DOMAIN  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402


@pytest.fixture
def rig(monkeypatch):
    class Entity:
        async def async_added_to_hass(self):
            pass

        async def async_will_remove_from_hass(self):
            self.removed_state = self.hass.states.get(self.entity_id)

        def async_write_ha_state(self):
            attrs = dict(getattr(self, "extra_state_attributes", {}) or {})
            self.hass.states.set(
                self.entity_id, "on" if self._attr_is_on else "off", attrs
            )

    class SwitchEntity(Entity):
        pass

    class RestoreEntity(Entity):
        async def async_get_last_state(self):
            return self.restored_state

    def module(name, **attributes):
        value = ModuleType(name)
        value.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, value)

    module(
        "homeassistant.components.switch",
        SwitchEntity=SwitchEntity,
        SwitchEntityDescription=lambda **kw: SimpleNamespace(**kw),
    )
    module("homeassistant.config_entries", ConfigEntry=ha_stubs.FakeEntry)
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module("homeassistant.helpers.entity", DeviceInfo=lambda **kw: kw)
    module("homeassistant.helpers.restore_state", RestoreEntity=RestoreEntity)
    clock = SimpleNamespace(
        now=datetime(2026, 9, 8, 10, tzinfo=timezone.utc), timers=[]
    )

    def schedule(hass, callback, when):
        timer = SimpleNamespace(
            callback=callback, when=when, cancelled=False, fired=False
        )
        clock.timers.append(timer)
        return lambda: setattr(timer, "cancelled", True)

    module("homeassistant.helpers.event", async_track_point_in_utc_time=schedule)
    from homeassistant.util import dt as dt_util

    monkeypatch.setattr(dt_util, "utcnow", lambda: clock.now)
    spec = importlib.util.spec_from_file_location(
        "custom_components.crop_steering._override_switch_under_test",
        Path(__file__).parents[1] / "custom_components/crop_steering/switch.py",
    )
    switch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(switch)
    hass = ha_stubs.FakeHass()

    def make(prefix="", zone=1, restored=None, entity_id=None):
        entry = ha_stubs.FakeEntry(
            data={"room_prefix": prefix, "room_slug": prefix.rstrip("_") or "default"},
            entry_id=prefix or "default",
        )
        hass.config_entries._entries.append(entry)
        entity = switch.CropSteeringSwitch(
            entry,
            SimpleNamespace(key=f"zone_{zone}_manual_override", name="Override"),
        )
        entity.hass = hass
        entity.entity_id = (
            entity_id or f"switch.crop_steering_{prefix}zone_{zone}_manual_override"
        )
        entity.restored_state = restored
        asyncio.run(entity.async_added_to_hass())
        entity.async_write_ha_state()
        return entity

    def request(zone=1, room=None, **kwargs):
        asyncio.run(services.async_setup_services(hass))
        handler = hass.services.registered[(DOMAIN, "set_manual_override")]
        asyncio.run(
            handler(SimpleNamespace(data={"zone": zone, "room": room, **kwargs}))
        )

    def advance(minutes):
        clock.now += timedelta(minutes=minutes)
        for timer in list(clock.timers):
            if not timer.cancelled and not timer.fired and timer.when <= clock.now:
                timer.fired = True
                timer.callback(clock.now)

    return SimpleNamespace(
        hass=hass, make=make, request=request, advance=advance, clock=clock
    )


def test_timed_service_expires_the_actual_loaded_switch(rig):
    entity = rig.make()
    rig.request(timeout_minutes=5)
    assert entity._attr_is_on
    assert (
        entity.extra_state_attributes["manual_override_expires_at"]
        == (rig.clock.now + timedelta(minutes=5)).isoformat()
    )
    rig.advance(4)
    assert entity._attr_is_on
    rig.advance(1)
    assert not entity._attr_is_on
    assert entity.extra_state_attributes["manual_override_expires_at"] is None
    assert rig.hass.services.calls == []  # No pump, valve or engine commands.


def test_default_timeout_and_retrigger_supersede_an_already_queued_callback(rig):
    entity = rig.make()
    rig.request()
    old = rig.clock.timers[-1]
    assert old.when == rig.clock.now + timedelta(minutes=60)
    rig.advance(10)
    rig.request(timeout_minutes=120)
    assert old.cancelled
    old.callback(rig.clock.now + timedelta(hours=1))
    assert entity._attr_is_on
    rig.advance(119)
    assert entity._attr_is_on
    rig.advance(1)
    assert not entity._attr_is_on


@pytest.mark.parametrize("action", ["disable", "direct_off", "direct_on"])
def test_explicit_switch_actions_cancel_existing_deadline(rig, action):
    entity = rig.make()
    rig.request(timeout_minutes=5)
    timer = rig.clock.timers[-1]
    if action == "disable":
        rig.request(enable=False)
    else:
        asyncio.run(
            getattr(
                entity, "async_turn_on" if action == "direct_on" else "async_turn_off"
            )()
        )
    assert timer.cancelled
    assert entity.extra_state_attributes["manual_override_expires_at"] is None
    timer.callback(rig.clock.now + timedelta(minutes=6))
    assert entity._attr_is_on is (action == "direct_on")


def test_unload_keeps_deadline_for_restore_but_invalidates_old_callback(rig):
    entity = rig.make()
    rig.request(timeout_minutes=30)
    timer = rig.clock.timers[-1]
    saved = rig.hass.states.get(entity.entity_id)
    asyncio.run(entity.async_will_remove_from_hass())
    assert timer.cancelled
    assert entity.extra_state_attributes == saved.attributes
    with pytest.raises(HomeAssistantError, match="not loaded"):
        rig.request(timeout_minutes=5)
    restored = rig.make(restored=saved)
    timer.callback(rig.clock.now + timedelta(minutes=30))
    assert restored._attr_is_on
    rig.advance(30)
    assert not restored._attr_is_on


@pytest.mark.parametrize(
    "minutes,state,expected,timers",
    [(20, "on", True, 1), (-1, "on", False, 0), (20, "off", False, 0)],
)
def test_restart_respects_restored_deadline_and_switch_state(
    rig, minutes, state, expected, timers
):
    deadline = rig.clock.now + timedelta(minutes=minutes)
    restored = ha_stubs.FakeState(
        state, {"manual_override_expires_at": deadline.isoformat()}
    )
    entity = rig.make(restored=restored)
    assert entity._attr_is_on is expected
    assert len(rig.clock.timers) == timers


@pytest.mark.parametrize(
    "metadata",
    [None, "nonsense", "2026-09-08T09:00:00", 0, {}, "99999-01-01T00:00:00+00:00"],
)
def test_legacy_or_invalid_deadline_never_releases_an_indefinite_hold(rig, metadata):
    entity = rig.make(
        restored=ha_stubs.FakeState("on", {"manual_override_expires_at": metadata})
    )
    rig.advance(1441)
    assert entity._attr_is_on
    assert not rig.clock.timers


def test_default_named_room_and_zone_timers_are_isolated(rig):
    default = rig.make()
    f1 = rig.make("f1_")
    f1z2 = rig.make("f1_", 2)
    rig.request(timeout_minutes=5)
    rig.request(room="f1", timeout_minutes=10)
    rig.request(room="f1", zone=2, timeout_minutes=15)
    rig.advance(5)
    assert not default._attr_is_on and f1._attr_is_on and f1z2._attr_is_on
    rig.advance(5)
    assert not f1._attr_is_on and f1z2._attr_is_on
    rig.advance(5)
    assert not f1z2._attr_is_on


def test_service_rejects_unloaded_zone_without_a_success_event(rig):
    with pytest.raises(HomeAssistantError, match="not loaded"):
        rig.request()
    assert not rig.hass.bus.events and not rig.hass.services.calls


@pytest.mark.parametrize("timeout", [0, 1441, float("nan"), float("inf"), True, "5"])
def test_invalid_timeout_does_not_replace_an_existing_hold(rig, timeout):
    entity = rig.make()
    rig.request(timeout_minutes=5)
    before = dict(entity.extra_state_attributes)
    timer = rig.clock.timers[-1]
    with pytest.raises(HomeAssistantError, match="1–1440"):
        rig.request(timeout_minutes=timeout)
    assert entity._attr_is_on and entity.extra_state_attributes == before
    assert not timer.cancelled


def test_scheduler_failure_preserves_previous_deadline(rig, monkeypatch):
    entity = rig.make()
    rig.request(timeout_minutes=5)
    before = dict(entity.extra_state_attributes)
    timer = rig.clock.timers[-1]

    def unavailable(*args):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(
        sys.modules["homeassistant.helpers.event"],
        "async_track_point_in_utc_time",
        unavailable,
    )
    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        rig.request(timeout_minutes=10)
    assert not timer.cancelled
    assert entity.extra_state_attributes == before and entity._attr_is_on
    rig.advance(5)
    assert not entity._attr_is_on


def test_restart_normalizes_an_aware_offset_to_utc(rig):
    deadline = (rig.clock.now + timedelta(minutes=20)).astimezone(
        timezone(timedelta(hours=12))
    )
    entity = rig.make(
        restored=ha_stubs.FakeState(
            "on", {"manual_override_expires_at": deadline.isoformat()}
        )
    )
    assert rig.clock.timers[-1].when == rig.clock.now + timedelta(minutes=20)
    assert entity.extra_state_attributes["manual_override_expires_at"].endswith(
        "+00:00"
    )
    rig.advance(20)
    assert not entity._attr_is_on


def test_renamed_override_is_rejected_without_replacing_existing_timer(rig):
    entity = rig.make()
    rig.request(timeout_minutes=5)
    before = dict(entity.extra_state_attributes)
    timer = rig.clock.timers[-1]
    event_count = len(rig.hass.bus.events)
    entity.entity_id = "switch.renamed_override"
    with pytest.raises(
        HomeAssistantError, match="Restore.*switch.crop_steering_zone_1_manual_override"
    ):
        rig.request(timeout_minutes=10)
    assert entity._attr_is_on and entity.extra_state_attributes == before
    assert not timer.cancelled and len(rig.clock.timers) == 1
    assert len(rig.hass.bus.events) == event_count
