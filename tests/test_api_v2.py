"""The API v2 envelope (api_v2.py) against the stubs: v1 unchanged, the envelope, the error codes and the
journal event ids."""

import asyncio
from types import SimpleNamespace

import pytest

ROOM = "room:f2_"


def _stubs():
    from . import ha_stubs

    ha_stubs.install()
    from custom_components.crop_steering import api_v2

    return ha_stubs, api_v2


def _call(data, *, user_id=None, return_response=True, service="thing"):
    return SimpleNamespace(
        data=data,
        context=SimpleNamespace(user_id=user_id),
        return_response=return_response,
        service=service,
        domain="crop_steering",
    )


def _run(coro):
    return asyncio.run(coro)


def test_without_api_the_answer_is_unchanged():
    _, api_v2 = _stubs()
    answer = {"revision": 3, "rows": [1, 2]}
    seen = []

    async def handler(call):
        seen.append(call)
        return answer

    call = _call({"room_id": ROOM})
    assert _run(api_v2.wrap(handler)(call)) is answer
    assert seen == [call]  # the very call, not a copy
    # api 1 is v1 too; only `api` is taken off what the handler sees.
    assert _run(api_v2.wrap(handler)(_call({"room_id": ROOM, "api": 1}))) is answer
    assert seen[-1].data == {"room_id": ROOM}


def test_api_2_wraps_the_answer():
    _, api_v2 = _stubs()

    async def handler(call):
        assert "api" not in call.data and call.service == "thing"
        return {"revision": 7, "applied": [{"readback": "verified"}]}

    out = _run(api_v2.wrap(handler)(_call({"room_id": ROOM, "api": 2})))
    assert out["api"] == 2 and out["ok"] is True
    assert out["room_id"] == ROOM and out["revision"] == 7
    assert out["readback"]["status"] == "verified"
    assert out["readback"]["at"] == "2026-01-01T12:00:00+00:00"
    assert out["event_ids"] == []
    assert out["data"] == {"revision": 7, "applied": [{"readback": "verified"}]}


@pytest.mark.parametrize(
    "result,status",
    [
        ({"applied": [{"readback": "verified"}, {"readback": "verified"}]}, "verified"),
        ({"applied": [{"readback": "verified"}, {"readback": "refused"}]}, "refused"),
        ({"applied": []}, "none"),
        ({"readback": {"status": "ok"}}, "verified"),
        ({"readback": {"status": "mismatch"}}, "none"),
        ({"revision": 1}, "none"),
    ],
)
def test_readback_comes_only_from_the_handlers_own_read_back(result, status):
    _, api_v2 = _stubs()

    async def handler(call):
        return result

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["readback"]["status"] == status


def test_stale_revision_maps_to_its_code_and_current_revision():
    _, api_v2 = _stubs()
    from homeassistant.exceptions import HomeAssistantError

    message = "Harvests changed elsewhere. Reload before saving."

    async def handler(call):
        try:
            raise api_v2.StaleRevision(message, 4)
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error

    wrapped = api_v2.wrap(handler)
    out = _run(wrapped(_call({"room_id": ROOM, "api": 2})))
    assert out == {
        "api": 2,
        "ok": False,
        "error": {"code": "stale_revision", "message": message, "current_revision": 4},
        "event_ids": [],
    }
    # v1, and a v2 caller that does not read the answer, get the exception as before.
    for call in (_call({}), _call({"api": 2}, return_response=False)):
        with pytest.raises(HomeAssistantError, match="changed elsewhere"):
            _run(wrapped(call))


def test_a_refusal_answered_rather_than_raised_comes_from_the_service_s_own_hook():
    _, api_v2 = _stubs()
    answer = {"config": {"revision": 9}, "error": "revision"}

    async def handler(call):
        return answer

    def error_of(call, result):
        if result["error"] == "revision":
            return api_v2.failure("stale_revision", "changed", 9)
        return None

    out = _run(api_v2.wrap(handler, error_of={"thing": error_of})(_call({"api": 2})))
    assert out == {
        "api": 2,
        "ok": False,
        "error": {
            "code": "stale_revision",
            "message": "changed",
            "current_revision": 9,
        },
        "event_ids": [],  # nothing was journaled before it refused
        "data": answer,
    }
    # No hook, no sniffing: the same answer from another service is ok, its revision as given.
    plain = _run(
        api_v2.wrap(handler, revision_of=api_v2.nested_revision)(_call({"api": 2}))
    )
    assert plain["ok"] is True and plain["revision"] == 9
    assert _run(api_v2.wrap(handler, error_of={"thing": error_of})(_call({}))) is answer


def test_forbidden_maps_from_the_admin_check():
    ha_stubs, api_v2 = _stubs()
    from custom_components.crop_steering.admin import async_require_admin

    hass = ha_stubs.FakeHass()

    async def get_user(user_id):
        return SimpleNamespace(id=user_id, is_admin=False)

    hass.auth = SimpleNamespace(async_get_user=get_user)

    async def handler(call):
        await async_require_admin(hass, call, "crop_steering.thing")
        return {}

    out = _run(api_v2.wrap(handler)(_call({"api": 2}, user_id="staff")))
    assert out["ok"] is False
    assert out["error"]["code"] == "forbidden"
    assert "administrator" in out["error"]["message"]


@pytest.mark.parametrize(
    "error,code",
    [
        (ValueError("pump_over_capacity: switch.pump cannot feed 3 zones"), "invalid"),
        (ValueError("Give at least one target"), "invalid"),
        (ValueError("The stored dashboards could not be loaded; ..."), "invalid"),
        ("Unavailable", "unavailable"),
        ("GuardRefused", "guard_refused"),
    ],
)
def test_value_errors_map_to_their_codes(error, code):
    _, api_v2 = _stubs()

    if isinstance(error, str):  # a type of api_v2: same message, the code from the type
        error = getattr(api_v2, error)("Zone 1 VWC is unavailable or stale")

    async def handler(call):
        raise error

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["error"] == {"code": code, "message": str(error)}


def test_the_journal_being_unavailable_is_unavailable():
    _, api_v2 = _stubs()
    from homeassistant.exceptions import HomeAssistantError

    message = "The event journal is unavailable"

    async def handler(call):
        raise HomeAssistantError(message) from api_v2.Unavailable(message)

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["error"] == {"code": "unavailable", "message": message}

    async def only_says_so(call):
        raise HomeAssistantError(message)

    # The code comes from the type, never from the words.
    out = _run(api_v2.wrap(only_says_so)(_call({"api": 2})))
    assert out["error"]["code"] == "invalid"


def test_only_what_an_error_was_raised_from_counts():
    _, api_v2 = _stubs()
    from homeassistant.exceptions import HomeAssistantError

    async def handler(call):
        try:
            raise api_v2.StaleRevision("changed elsewhere", 3)
        except ValueError:
            raise HomeAssistantError("Something else went wrong")

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["error"] == {"code": "invalid", "message": "Something else went wrong"}


def test_forbidden_comes_from_the_type_not_the_words():
    _, api_v2 = _stubs()
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.crop_steering.admin import Forbidden, forbidden

    refusal = forbidden("x requires an authenticated Home Assistant administrator")
    assert isinstance(refusal, HomeAssistantError) and isinstance(refusal, Forbidden)
    assert str(refusal) == "x requires an authenticated Home Assistant administrator"

    async def handler(call):
        raise HomeAssistantError(
            "x requires an authenticated Home Assistant administrator"
        )

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["error"]["code"] == "invalid"


def test_a_guard_refusal_is_guard_refused():
    _, api_v2 = _stubs()
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.crop_steering.journal_api import EMITTED

    async def handler(call):
        EMITTED.get().append(("01J0000000000000000000000A", "intent.refused"))
        raise HomeAssistantError("Refused: the zone is in its no-touch window")

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["error"]["code"] == "guard_refused"


def test_an_unknown_exception_still_raises():
    _, api_v2 = _stubs()

    async def handler(call):
        raise KeyError("bug")

    with pytest.raises(KeyError):
        _run(api_v2.wrap(handler)(_call({"api": 2})))

    async def while_refusing(call):
        try:
            raise ValueError("Give at least one target")
        except ValueError:
            raise KeyError("bug")

    with pytest.raises(KeyError):
        _run(api_v2.wrap(while_refusing)(_call({"api": 2})))


def test_a_refusal_raised_as_home_assistant_error_is_invalid():
    _, api_v2 = _stubs()
    from homeassistant.exceptions import HomeAssistantError

    async def handler(call):
        raise HomeAssistantError("crop_steering.notify_test needs either service")

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["error"]["code"] == "invalid"


def test_event_ids_are_the_events_emitted_during_the_call(tmp_path, monkeypatch):
    from .test_journal_api import _rig

    hass, journal_api = _rig(monkeypatch, tmp_path)
    from custom_components.crop_steering import api_v2

    async def go():
        hub = journal_api.JournalHub(hass, str(tmp_path / "journal.db"))
        # Still opening: the id is known at emit time, the event goes in once it opens.
        hass.data.setdefault("crop_steering", {})["_journal"] = hub
        outside = journal_api.emit(hass, ROOM, "shot.completed", zone=3)
        ids = []

        async def handler(call):
            ids.append(journal_api.note(hass, ROOM, "shot.completed", zone=1))
            ids.append(journal_api.emit(hass, ROOM, "shot.completed", zone=2))
            return {}

        out = await api_v2.wrap(handler)(_call({"api": 2}))
        await hub.async_init()
        assert out["event_ids"] == ids and None not in ids and outside not in ids
        assert journal_api.emit(hass, ROOM, "shot.completed", zone=4)  # no call open

    asyncio.run(go())


def test_common_keeps_a_field_the_service_already_declares():
    _, api_v2 = _stubs()
    import voluptuous as vol

    own = vol.Optional("proposal_token")
    merged = api_v2.fields({vol.Required("room_id"): str, own: dict})
    assert merged[own] is dict
    assert {getattr(k, "key", getattr(k, "schema", k)) for k in merged} == {
        "room_id",
        "proposal_token",
        "api",
        "client",
    }


@pytest.mark.parametrize(
    "module,hook,service,data,answer,code",
    [
        (
            "grow_day_store",
            "_rows_refused",
            "grow_day_record",
            {},
            {"taken": 1, "refused": ["date must be YYYY-MM-DD"]},
            "invalid",
        ),
        (
            "stock_api",
            "_unknown_tanks",
            "stock_draw",
            {},
            {"counted": True, "duplicate": False, "skipped": ["no_such_tank"]},
            "invalid",
        ),
        (
            "site_api",
            "_rows_refused",
            "preset_apply",
            {},
            {
                "diff": [],
                "missing": [],
                "applied": [
                    {"key": "p1", "readback": "verified", "error": None},
                    {"key": "p2", "readback": "refused", "error": "out of range"},
                ],
            },
            "guard_refused",
        ),
        (
            "calibration",
            "_not_captured",
            "calibration_capture",
            {},
            {"reading": 7.1, "raw": 7.1, "stable": False, "drift": 0.2, "stable_s": 3},
            "guard_refused",
        ),
    ],
)
def test_each_answered_refusal_hook(module, hook, service, data, answer, code):
    import importlib

    _, api_v2 = _stubs()
    hook = getattr(
        importlib.import_module(f"custom_components.crop_steering.{module}"), hook
    )

    async def handler(call):
        return answer

    wrapped = api_v2.wrap(handler, error_of={service: hook})
    out = _run(wrapped(_call({"api": 2, **data}, service=service)))
    assert out["ok"] is False and out["error"]["code"] == code
    assert out["data"] is answer
    assert _run(wrapped(_call(data, service=service))) is answer  # v1 unchanged
    # The same service with nothing refused is ok.
    fine = {
        "grow_day_record": {"taken": 1, "refused": []},
        "stock_draw": {"counted": True, "duplicate": True, "skipped": []},
        "preset_apply": {"diff": [], "missing": [], "applied": []},
        "calibration_capture": {"stable": True},
    }[service]

    async def done(call):
        return fine

    ok = _run(
        api_v2.wrap(done, error_of={service: hook})(_call({"api": 2}, service=service))
    )
    assert ok["ok"] is True


def test_a_forced_capture_of_an_unsteady_reading_is_ok():
    _, api_v2 = _stubs()
    from custom_components.crop_steering.calibration import _not_captured

    async def handler(call):
        return {"stable": False}

    wrapped = api_v2.wrap(handler, error_of={"calibration_capture": _not_captured})
    out = _run(wrapped(_call({"api": 2, "force": True}, service="calibration_capture")))
    assert out["ok"] is True


def test_a_hook_covers_only_the_service_it_names():
    _, api_v2 = _stubs()

    async def handler(call):
        return {"error": "busy"}

    wrapped = api_v2.wrap(
        handler, error_of={"thing": lambda call, result: api_v2.failure("invalid", "x")}
    )
    assert wrapped.error_of.keys() == {"thing"}
    assert _run(wrapped(_call({"api": 2}, service="other")))["ok"] is True
    assert _run(wrapped(_call({"api": 2}, service="thing")))["ok"] is False


def test_a_partly_applied_refusal_answers_the_ids_of_the_events_it_wrote(
    tmp_path, monkeypatch
):
    from .test_journal_api import _rig

    hass, journal_api = _rig(monkeypatch, tmp_path)
    from custom_components.crop_steering import api_v2
    from custom_components.crop_steering.site_api import _rows_refused

    async def go():
        hub = journal_api.JournalHub(hass, str(tmp_path / "journal.db"))
        hass.data.setdefault("crop_steering", {})["_journal"] = hub
        ids = []

        async def handler(call):
            # One value written (and journaled), one refused: the UI can Undo the one written.
            ids.append(journal_api.emit(hass, ROOM, "target.changed", zone=1))
            return {
                "diff": [],
                "missing": [],
                "applied": [
                    {"key": "p1", "readback": "verified", "error": None},
                    {"key": "p2", "readback": "refused", "error": "out of range"},
                ],
            }

        wrapped = api_v2.wrap(handler, error_of={"preset_apply": _rows_refused})
        out = await wrapped(_call({"api": 2}, service="preset_apply"))
        await hub.async_init()
        assert out["ok"] is False and out["error"]["code"] == "guard_refused"
        assert out["event_ids"] == ids and None not in ids

    asyncio.run(go())


def test_a_source_with_no_timer_program_is_missing_not_a_refused_write():
    _, api_v2 = _stubs()
    from custom_components.crop_steering.site_api import _rows_refused

    answer = {
        "diff": [],
        "missing": [{"key": "timer", "reason": "source zone has no timer program"}],
        "applied": [
            {"key": "p1", "readback": "verified", "error": None},
            {
                "key": "timer",
                "readback": "refused",
                "error": "source zone has no timer program",
                "missing": True,
            },
        ],
    }

    async def handler(call):
        return answer

    wrapped = api_v2.wrap(handler, error_of={"copy_config": _rows_refused})
    out = _run(wrapped(_call({"api": 2}, service="copy_config")))
    assert out["ok"] is True and out["data"]["missing"] == answer["missing"]
    assert out["readback"]["status"] == "verified"  # every write it made read back
    # A real write refusal beside it still refuses the whole answer.
    answer["applied"][0].update(readback="refused", error="out of range")
    out = _run(wrapped(_call({"api": 2}, service="copy_config")))
    assert out["ok"] is False and out["error"]["code"] == "guard_refused"
    assert out["error"]["message"] == "Not applied: p1: out of range"


def test_a_raised_refusal_answers_the_ids_of_the_events_written_before_it():
    _, api_v2 = _stubs()
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.crop_steering.journal_api import EMITTED

    async def handler(call):
        # One value written (and journaled) before the service raised: the UI can Undo it.
        EMITTED.get().append(("01J0000000000000000000000B", "target.changed"))
        raise HomeAssistantError("The second value could not be written")

    out = _run(api_v2.wrap(handler)(_call({"api": 2})))
    assert out["ok"] is False and out["error"]["code"] == "invalid"
    assert out["event_ids"] == ["01J0000000000000000000000B"]
