"""The one administrator check behind every crop_steering service that changes something."""

from __future__ import annotations


class Forbidden(Exception):
    """A caller refused for who they are (API v2 `forbidden`). What is raised is a
    HomeAssistantError that is also a Forbidden: forbidden() makes it."""


_FORBIDDEN: dict = {}


def forbidden(message: str):
    """A HomeAssistantError, as these refusals always were, that is also a Forbidden."""
    from homeassistant.exceptions import HomeAssistantError

    kind = _FORBIDDEN.get(HomeAssistantError)
    if kind is None:
        kind = _FORBIDDEN[HomeAssistantError] = type(
            "Forbidden", (HomeAssistantError, Forbidden), {}
        )
    return kind(message)


async def async_require_admin(hass, call, action, *, allow_no_user=True):
    """Refuse a service call made by a signed-in Home Assistant user who is not an administrator.

    The sidebar console is open to every login, because looking is legitimate, and it calls these
    services with that login. A call with no user id (an automation, or a script an automation
    started) has no login to check and runs exactly as before, unless `allow_no_user` is false:
    setup has always needed a signed-in administrator. A user id Home Assistant does not know is
    refused. Same semantics as Home Assistant's own admin services.

    HomeAssistantError, the type setup always raised, and not Home Assistant's `Unauthorized`: the
    console calls these services over the REST API, where `Unauthorized` becomes a bare 401 without
    this message, and the http ban middleware records every 401 as a failed login ("Login attempt
    failed", then an IP ban once `login_attempts_threshold` is reached). Pressing Arm on a staff
    phone must not get that phone banned.
    """
    user_id = call.context.user_id
    if not user_id and allow_no_user:
        return
    user = await hass.auth.async_get_user(user_id) if user_id else None
    if user is None or not user.is_admin:
        raise forbidden(
            f"{action} requires an authenticated Home Assistant administrator"
        )
