"""API v2: an opt-in answer envelope on every crop_steering response service.

A caller that sends `api: 2` and asks for the answer gets
`{api: 2, ok: true, room_id, revision, readback: {status, at}, event_ids, data}`, `data` being the
v1 answer, or `{api: 2, ok: false, error: {code, message, current_revision?}}`. Without `api` the
service answers exactly as before. An error is answered only to a caller that asked for the answer:
any other caller gets the exception v1 raised, so a refused write never looks like it went through.
An exception this module does not know is raised as it is.

`event_ids` are the journal events `journal_api.emit()` recorded while the service ran.
"""

from __future__ import annotations

import functools

from .journal_api import EMITTED

FORBIDDEN = (
    "requires an authenticated Home Assistant administrator",
    "requires a signed-in Home Assistant user",
)
UNAVAILABLE = ("unavailable", "could not be loaded")


class StaleRevision(ValueError):
    """A save against a revision that has moved on. The message is the one v1 raised."""

    def __init__(self, message: str, current_revision=None) -> None:
        super().__init__(message)
        self.current_revision = current_revision


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
    out = []
    while error is not None and error not in out:
        out.append(error)
        error = error.__cause__ or error.__context__
    return out


def _failure(error, events) -> dict | None:
    """The v2 error for `error`, or None for an exception this module does not know. A refusal the
    service raised on purpose (ValueError, HomeAssistantError) that is nothing more specific is
    `invalid`; anything else (a bug) is raised as it is."""
    from homeassistant.exceptions import HomeAssistantError

    if not isinstance(error, (ValueError, HomeAssistantError)):
        return None
    chain = _chain(error)
    message = str(error)
    stale = next((e for e in chain if isinstance(e, StaleRevision)), None)
    if stale is not None:
        out = {"code": "stale_revision", "message": message}
        if stale.current_revision is not None:
            out["current_revision"] = stale.current_revision
        return out
    if any(text in message for text in FORBIDDEN):
        return {"code": "forbidden", "message": message}
    if any(kind == "intent.refused" for _, kind in events):
        return {"code": "guard_refused", "message": message}
    if any(text in message.lower() for text in UNAVAILABLE):
        return {"code": "unavailable", "message": message}
    return {"code": "invalid", "message": message}


def wrap(handler, *, room_of=_room, revision_of=_revision, readback_of=_readback):
    """The service handler, answering in the v2 envelope when the call says `api: 2`."""

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
            failure = _failure(error, events)
            if failure is None:
                raise
            return {"api": 2, "ok": False, "error": failure}
        finally:
            EMITTED.reset(token)
        if isinstance(result, dict) and result.get("error") == "revision":
            # dosing_save and notify_save answer a stale save instead of raising.
            failure = {
                "code": "stale_revision",
                "message": "Changed elsewhere. Reload before saving.",
            }
            current = (result.get("config") or {}).get("revision")
            if current is not None:
                failure["current_revision"] = current
            return {"api": 2, "ok": False, "error": failure}
        return {
            "api": 2,
            "ok": True,
            "room_id": room_of(call, result),
            "revision": revision_of(result),
            "readback": {"status": readback_of(call, result), "at": _now()},
            "event_ids": [event_id for event_id, _ in events],
            "data": result,
        }

    return wrapped
