"""Setup response services require authenticated administrator context."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from .test_setup import rig, payload, api


def test_response_services_require_admin_and_return_actual_saved_revision(monkeypatch):
    from . import ha_stubs

    ha_stubs.install()
    core = sys.modules["homeassistant.core"]
    monkeypatch.setattr(
        core,
        "SupportsResponse",
        SimpleNamespace(ONLY="only", OPTIONAL="optional"),
        raising=False,
    )
    monkeypatch.setattr(
        sys.modules["voluptuous"], "ALLOW_EXTRA", object(), raising=False
    )
    hass, _, _ = rig()
    handlers = {}
    hass.services = SimpleNamespace(
        async_register=lambda domain, name, fn, **kwargs: handlers.setdefault(name, fn)
    )
    admin = {"is_admin": False}

    async def user(_id):
        return SimpleNamespace(**admin)

    hass.auth = SimpleNamespace(async_get_user=user)
    asyncio.run(api.async_setup_setup_services(hass))
    asyncio.run(api.async_setup_setup_services(hass))
    assert set(handlers) == {"setup_read", "setup_save", "setup_create", "setup_remove"}
    call = SimpleNamespace(
        context=SimpleNamespace(user_id="person"), return_response=True, data=payload()
    )
    with pytest.raises(Exception, match="administrator"):
        asyncio.run(handlers["setup_save"](call))
    assert not hass.config_entries.updates
    admin["is_admin"] = True
    result = asyncio.run(handlers["setup_save"](call))
    assert result["revision"] == 1 and result["active_zone_ids"] == [2]
    result = asyncio.run(handlers["setup_read"](call))
    assert result["api_version"] == 1 and result["rooms"][0]["revision"] == 1
