"""API v2 (api_v2.py) through a real Home Assistant: every crop_steering service that answers takes `api: 2`
and answers in the envelope, and without it answers exactly as before."""

from homeassistant.core import Context, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
import pytest
import voluptuous as vol
from test_setup_entry import _install

DOMAIN = "crop_steering"
F2 = "room:tent_"


async def _call(hass, user, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


def _keys(schema) -> set:
    inner = getattr(schema, "schema", None)
    return (
        {str(getattr(k, "schema", k)) for k in inner}
        if isinstance(inner, dict)
        else set()
    )


async def test_every_response_service_accepts_api_2(hass, hass_admin_user):
    await _install(hass)
    services = hass.services.async_services()[DOMAIN]
    names = sorted(
        name
        for name in services
        if hass.services.supports_response(DOMAIN, name) is not SupportsResponse.NONE
    )
    assert len(names) > 40
    answered, needs_more = [], []
    for name in names:
        service = services[name]
        # One wrap at registration, for every service that answers.
        assert getattr(service.job.target, "__wrapped__", None) is not None, name
        data = {"api": 2}
        if "room_id" in _keys(service.schema):
            data["room_id"] = F2
        try:
            out = await _call(hass, hass_admin_user, name, **data)
        except vol.Invalid as error:
            # Only the service's own required fields may be missing: never `api` refused.
            errors = getattr(error, "errors", [error])
            assert all(e.path[:1] != ["api"] for e in errors), (name, str(error))
            needs_more.append(name)
            continue
        except HomeAssistantError as error:
            pytest.fail(f"{name} raised with api 2: {error}")
        assert out["api"] == 2, name
        assert isinstance(out["ok"], bool), name
        answered.append(name)
    assert {"setup_read", "supply_get", "dashboard_list", "whats_new_get"} <= set(
        answered
    ), (answered, needs_more)


async def test_setup_read_keeps_api_version_1_and_reports_2_in_the_envelope(
    hass, hass_admin_user
):
    await _install(hass)
    v1 = await _call(hass, hass_admin_user, "setup_read")
    assert v1["api_version"] == 1 and "ok" not in v1
    v2 = await _call(hass, hass_admin_user, "setup_read", api=2)
    assert v2["api"] == 2 and v2["ok"] is True
    assert v2["data"] == v1
    assert v2["data"]["api_version"] == 1


async def test_a_stale_setup_save_is_stale_revision_with_the_current_one(
    hass, hass_admin_user
):
    entry = await _install(hass)
    room = (await _call(hass, hass_admin_user, "setup_read"))["rooms"][0]
    out = await _call(
        hass,
        hass_admin_user,
        "setup_save",
        api=2,
        entry_id=entry.entry_id,
        expected_revision=room["revision"] + 5,
        zones=room["zones"],
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "stale_revision"
    assert out["error"]["current_revision"] == room["revision"]
    # v1 raises, as it always did.
    with pytest.raises(HomeAssistantError, match="Room setup changed"):
        await _call(
            hass,
            hass_admin_user,
            "setup_save",
            entry_id=entry.entry_id,
            expected_revision=room["revision"] + 5,
            zones=room["zones"],
        )


async def test_a_write_answers_its_journal_event_ids(hass, hass_admin_user):
    await _install(hass)
    supply = await _call(hass, hass_admin_user, "supply_get")
    out = await _call(
        hass,
        hass_admin_user,
        "supply_save",
        api=2,
        expected_revision=supply["revision"],
        irrigation_pumps=[],
        zone_meters={F2: {"1": "sensor.not_there"}},
    )
    assert out["ok"] is True, out
    assert out["revision"] == supply["revision"] + 1
    assert out["readback"]["status"] == "verified"
    assert out["event_ids"] and all(len(i) == 26 for i in out["event_ids"])


async def test_a_read_takes_client_and_proposal_token_too(hass, hass_admin_user):
    await _install(hass)
    out = await _call(
        hass,
        hass_admin_user,
        "journal_query",
        api=2,
        room_id=F2,
        since="2026-01-01T00:00:00+00:00",
        client="mcp",
        proposal_token="p-1",
    )
    assert out["ok"] is True and out["room_id"] == F2
    assert "events" in out["data"]


async def test_a_non_admin_write_is_forbidden(hass, hass_read_only_user):
    await _install(hass)
    out = await _call(
        hass,
        hass_read_only_user,
        "supply_save",
        api=2,
        expected_revision=0,
        irrigation_pumps=[],
    )
    assert out["ok"] is False and out["error"]["code"] == "forbidden"
    assert "administrator" in out["error"]["message"]
    with pytest.raises(HomeAssistantError, match="administrator"):
        await _call(
            hass,
            hass_read_only_user,
            "supply_save",
            expected_revision=0,
            irrigation_pumps=[],
        )


async def test_a_stop_all_that_leaves_something_on_is_never_ok(
    hass, hass_admin_user, monkeypatch
):
    from homeassistant.components import persistent_notification
    from test_safety_ops import KILL, WASTE, _pumped_room

    from custom_components.crop_steering import safety_ops

    monkeypatch.setattr(safety_ops, "STOP_READBACK_S", 1.0)
    monkeypatch.setattr(persistent_notification, "async_create", lambda *a, **k: None)
    await _pumped_room(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": KILL}, blocking=True
    )
    hass.states.async_set(WASTE, "on")  # no device behind it: it stays on
    out = await _call(hass, hass_admin_user, "stop_all", api=2, room_id=F2)
    assert out["ok"] is False and out["error"]["code"] == "guard_refused"
    assert WASTE in out["error"]["message"]
    assert WASTE in out["data"]["still_on"]
    # With everything off, the read-back is verified.
    hass.states.async_set(WASTE, "off")
    out = await _call(hass, hass_admin_user, "stop_all", api=2, room_id=F2)
    assert out["ok"] is True, out
    assert out["readback"]["status"] == "verified"
    assert out["data"]["still_on"] == [] and out["data"]["refused"] == []


async def test_every_response_service_has_a_refusal_hook_or_never_answers_one(hass):
    """A service that answers "did not do it" instead of raising must map it (error_of); one that
    never does is named in NEVER_ANSWERS_REFUSAL. A new service is in neither until someone looks.
    """
    from custom_components.crop_steering.api_v2 import NEVER_ANSWERS_REFUSAL

    await _install(hass)
    services = hass.services.async_services()[DOMAIN]
    names = {
        name
        for name in services
        if hass.services.supports_response(DOMAIN, name) is not SupportsResponse.NONE
    }
    hooked = {name for name in names if name in services[name].job.target.error_of}
    assert not hooked & NEVER_ANSWERS_REFUSAL
    assert names - hooked - NEVER_ANSWERS_REFUSAL == set()
    assert NEVER_ANSWERS_REFUSAL <= names  # no stale name
    assert hooked == {
        "alert_rule_test",
        "calibration_capture",
        "copy_config",
        "dosing_request",
        "dosing_save",
        "grow_day_record",
        "history_revert",
        "notify",
        "notify_save",
        "notify_test",
        "preset_apply",
        "pump_calibrate",
        "pump_prime",
        "stock_draw",
        "stop_all",
    }
