"""API v2: an opt-in answer envelope on every crop_steering response service.

A caller that sends `api: 2` and asks for the answer gets
`{api: 2, ok: true, room_id, revision, readback: {status, at}, event_ids, data}`, `data` being the
v1 answer, or `{api: 2, ok: false, error: {code, message, current_revision?}}`. Without `api` the
service answers exactly as before. An error is answered only to a caller that asked for the answer:
any other caller gets the exception v1 raised, so a refused write never looks like it went through.
An exception this module does not know is raised as it is.

`event_ids` are the journal events `journal_api.emit()` recorded while the service ran.

Fields every response service takes besides its own (`COMMON`; documented here and in docs/MCP.md,
not per service in services.yaml): `api` (1 or 2; absent or 1 is v1), `client` (`mcp` or `aigrow`,
for attribution) and `proposal_token` (the reviewed proposal a write carries). A field a service
already declares keeps its own validator.

Error codes, each from a type, never from message text: StaleRevision -> `stale_revision` (with
`current_revision`), admin.Forbidden -> `forbidden`, GuardRefused or an `intent.refused` event ->
`guard_refused`, Unavailable -> `unavailable`, any other ValueError or HomeAssistantError -> `invalid`.
Each is matched on the exception or what it was raised from (`raise ... from`). A service that
answers a refusal instead of raising maps it with its `error_of` hook; the answer stays in `data`.
"""

from __future__ import annotations

import functools

from .journal_api import EMITTED


class StaleRevision(ValueError):
    """A save against a revision that has moved on (`stale_revision`). The message is the one v1
    raised."""

    def __init__(self, message: str, current_revision=None) -> None:
        super().__init__(message)
        self.current_revision = current_revision


class Unavailable(ValueError):
    """A hub or store that cannot be used (`unavailable`): it could not be loaded or is not set up."""


class GuardRefused(ValueError):
    """A guard that refuses the change for now (`guard_refused`), such as a readiness check."""


def __getattr__(name):
    """`API` ({api}) and `COMMON` ({api, client, proposal_token}), the fields every response service
    takes. Built on use, so the stores import StaleRevision from here without voluptuous.
    """
    if name not in ("API", "COMMON"):
        raise AttributeError(name)
    import voluptuous as vol

    api = {vol.Optional("api"): vol.In([1, 2])}
    if name == "API":
        return api
    return {
        **api,
        vol.Optional("client"): vol.In(["mcp", "aigrow"]),
        vol.Optional("proposal_token"): str,
    }


def fields(schema: dict, common: dict | None = None) -> dict:
    """`schema` with COMMON (or `common`) added; a key the service already declares keeps its own
    validator."""
    common = __getattr__("COMMON") if common is None else common
    return {**{k: v for k, v in common.items() if k not in schema}, **schema}


class _Call:
    """The service call without `api`, for the handler."""

    def __init__(self, call, data: dict) -> None:
        self._call = call
        self.data = data

    def __getattr__(self, name):
        return getattr(self._call, name)


def _now() -> str:
    from homeassistant.util import dt as dt_util

    return dt_util.now().isoformat()


def _room(call, result):
    room_id = call.data.get("room_id")
    if room_id is None and isinstance(result, dict):
        room_id = result.get("room_id")
    return room_id if isinstance(room_id, str) else None


def _revision(result):
    return result.get("revision") if isinstance(result, dict) else None


def nested_revision(result):
    """`revision_of` for an answer that carries its stored setup as `config` (dosing, notify)."""
    config = result.get("config") if isinstance(result, dict) else None
    return config.get("revision") if isinstance(config, dict) else None


def _readback(call, result) -> str:
    """The handler's own read-back: `applied` rows (presets) or a `readback` status (supply_save)."""
    if not isinstance(result, dict):
        return "none"
    rows = result.get("applied")
    if isinstance(rows, list) and rows:
        marks = [row.get("readback") for row in rows if isinstance(row, dict)]
        if "refused" in marks:
            return "refused"
        if len(marks) == len(rows) and all(m == "verified" for m in marks):
            return "verified"
        return "none"
    own = result.get("readback")
    if isinstance(own, dict) and own.get("status") == "ok":
        return "verified"
    return "none"


def _chain(error) -> list:
    """`error` and what it was raised from (`raise ... from`), never what it was raised while handling."""
    out = []
    while error is not None and error not in out:
        out.append(error)
        error = error.__cause__
    return out


def _failure(error, events) -> dict | None:
    """The v2 error for `error`, or None for an exception this module does not know. A refusal the
    service raised on purpose (ValueError, HomeAssistantError) that is nothing more specific is
    `invalid`; anything else (a bug) is raised as it is."""
    from homeassistant.exceptions import HomeAssistantError

    from .admin import Forbidden

    if not isinstance(error, (ValueError, HomeAssistantError)):
        return None
    chain = _chain(error)
    message = str(error)

    def raised(kind):
        return next((e for e in chain if isinstance(e, kind)), None)

    stale = raised(StaleRevision)
    if stale is not None:
        return failure("stale_revision", message, stale.current_revision)
    if raised(Forbidden):
        return failure("forbidden", message)
    if raised(GuardRefused) or any(kind == "intent.refused" for _, kind in events):
        return failure("guard_refused", message)
    if raised(Unavailable):
        return failure("unavailable", message)
    return failure("invalid", message)


def failure(code: str, message: str, current_revision=None) -> dict:
    """An `error` of the envelope; for a service's `error_of` hook too."""
    out = {"code": code, "message": message}
    if current_revision is not None:
        out["current_revision"] = current_revision
    return out


# The response services that never answer a refusal: each says "did not do it" by raising. Every
# other response service has an `error_of` hook for its own refusal answers. tests_ha/test_api_v2.py
# holds every registered service to one or the other, so a new service cannot slip through.
NEVER_ANSWERS_REFUSAL = frozenset(
    {
        "brain_ask",
        "brain_prompt_get",
        "brain_prompt_publish",
        "brain_prompt_rebuild",
        "brain_prompt_rollback",
        "brain_prompt_save",
        "calibration_abandon",
        "calibration_commit",
        "calibration_get",
        "calibration_record",
        "calibration_revert",
        "calibration_start",
        "calibration_status",
        "dashboard_create",
        "dashboard_list",
        "display_get",
        "display_save",
        "dosing_get",
        "grow_days_backfill",
        "grow_days_get",
        "harvests_get",
        "history_connection_get",
        "history_connection_save",
        "history_long",
        "journal_append",
        "journal_query",
        "notify_get",
        "overlay_get",
        "preset_delete",
        "preset_list",
        "preset_save",
        "probe_offset_set",
        "pump_calibration_commit",
        "pump_precheck",
        "pump_stop",
        "runs_archive",
        "runs_get",
        "runs_import",
        "runs_save",
        "runs_set_harvest",
        "setpoint_log_get",
        "setup_commission",
        "setup_create",
        "setup_read",
        "setup_remove",
        "setup_save",
        "stock_get",
        "stock_record_batch",
        "stock_refill",
        "stock_save",
        "strategy_activate",
        "strategy_disarm",
        "strategy_get",
        "strategy_preview",
        "strategy_save",
        "supply_get",
        "supply_save",
        "test_shot",
        "timer_program_delete",
        "timer_program_list",
        "timer_program_preview",
        "timer_program_set",
        "timer_skip",
        "whats_new_get",
        "whats_new_seen",
    }
)


def wrap(
    handler,
    *,
    room_of=_room,
    revision_of=_revision,
    readback_of=_readback,
    error_of=None,
):
    """The service handler, answering in the v2 envelope when the call says `api: 2`.

    `error_of`: {service: hook(call, result)} for each service of the handler that answers a refusal
    instead of raising. A hook returns a failure() for an answer that means "did not do it", else
    None; the answer then stays in `data`. Kept on the wrapper as `.error_of`.
    """
    refusals = dict(error_of or {})

    @functools.wraps(handler)
    async def wrapped(call):
        if "api" not in call.data:
            return await handler(call)
        api = call.data["api"]
        call = _Call(call, {k: v for k, v in call.data.items() if k != "api"})
        if api != 2 or not call.return_response:
            return await handler(call)
        events: list = []
        token = EMITTED.set(events)
        try:
            result = await handler(call)
        except Exception as error:
            failed = _failure(error, events)
            if failed is None:
                raise
            return {"api": 2, "ok": False, "error": failed}
        finally:
            EMITTED.reset(token)
        hook = refusals.get(call.service)
        refused = hook(call, result) if hook is not None else None
        if refused is not None:
            return {"api": 2, "ok": False, "error": refused, "data": result}
        return {
            "api": 2,
            "ok": True,
            "room_id": room_of(call, result),
            "revision": revision_of(result),
            "readback": {"status": readback_of(call, result), "at": _now()},
            "event_ids": [event_id for event_id, _ in events],
            "data": result,
        }

    wrapped.error_of = refusals
    return wrapped
