"""Lightweight Home Assistant stubs for dependency-free unit tests.

The integration modules import `voluptuous`, `homeassistant.*` and friends that are
not installed in the lean CI image (the project is intentionally dependency-free and
only pulls full HA for hassfest). These stubs let us import and *drive* real handler
code — service handlers, prefix resolution, event payloads — without a live HA or the
heavy pytest-homeassistant-custom-component stack.

They are deliberately minimal: just enough surface for the code under test. Call
`install()` once at import time (idempotent) before importing the integration module.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone


def _mod(name: str) -> types.ModuleType:
    m = sys.modules.get(name)
    if m is None:
        m = types.ModuleType(name)
        sys.modules[name] = m
    return m


def install() -> None:
    """Register minimal stubs for the HA + voluptuous surface the integration imports."""
    # --- voluptuous: schema builders as lenient no-ops (we test handlers, not validation) ---
    if "voluptuous" not in sys.modules:
        vol = _mod("voluptuous")

        class _Marker:
            def __init__(self, key, *a, **k):
                self.key = key

            def __hash__(self):
                return hash(self.key)

            def __eq__(self, other):
                return self.key == getattr(other, "key", other)

        def _passthrough(*a, **k):
            return a[0] if a else None

        vol.Schema = lambda x=None, *a, **k: x
        vol.Required = _Marker
        vol.Optional = _Marker
        vol.In = _passthrough
        vol.All = _passthrough
        vol.Coerce = _passthrough
        vol.Range = _passthrough

    # --- homeassistant core / exceptions / helpers / util ---
    ha = _mod("homeassistant")
    if not hasattr(ha, "__path__"):
        ha.__path__ = []  # mark as package so submodules import

    core = _mod("homeassistant.core")
    if not hasattr(core, "HomeAssistant"):

        class HomeAssistant:  # pragma: no cover - type placeholder
            ...

        core.HomeAssistant = HomeAssistant
    if not hasattr(core, "ServiceCall"):

        class ServiceCall:  # pragma: no cover - type placeholder
            ...

        core.ServiceCall = ServiceCall
    if not hasattr(core, "callback"):
        core.callback = lambda f: f

    exc = _mod("homeassistant.exceptions")
    if not hasattr(exc, "HomeAssistantError"):

        class HomeAssistantError(Exception): ...

        exc.HomeAssistantError = HomeAssistantError
    if not hasattr(exc, "ConfigEntryNotReady"):

        class ConfigEntryNotReady(Exception): ...

        exc.ConfigEntryNotReady = ConfigEntryNotReady

    helpers = _mod("homeassistant.helpers")
    if not hasattr(helpers, "__path__"):
        helpers.__path__ = []
    cv = _mod("homeassistant.helpers.config_validation")
    cv.string = str
    cv.boolean = bool
    helpers.config_validation = cv

    ir = _mod("homeassistant.helpers.issue_registry")
    if not hasattr(ir, "async_create_issue"):

        class IssueSeverity:
            ERROR = "error"
            WARNING = "warning"

        def _create(hass, domain, issue_id, **kw):
            store = getattr(hass, "_issues", None)
            if store is None:
                store = {}
                hass._issues = store
            store[issue_id] = kw

        def _delete(hass, domain, issue_id):
            store = getattr(hass, "_issues", None)
            if store is not None:
                store.pop(issue_id, None)

        ir.IssueSeverity = IssueSeverity
        ir.async_create_issue = _create
        ir.async_delete_issue = _delete
    helpers.issue_registry = ir

    util = _mod("homeassistant.util")
    if not hasattr(util, "__path__"):
        util.__path__ = []
    dt = _mod("homeassistant.util.dt")
    if not hasattr(dt, "now"):
        # Fixed, tz-aware instant — deterministic and, crucially, NOT via the removed
        # hass.helpers.template.now() (the bug under test).
        dt.now = lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        dt.utcnow = lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    util.dt = dt


# ------------------------------- fakes for driving handlers -------------------------------
class FakeState:
    def __init__(self, state, attributes=None, last_updated=None):
        self.state = state
        self.attributes = attributes or {}
        self.last_updated = last_updated


class FakeStates:
    def __init__(self, mapping=None):
        self._m = dict(mapping or {})

    def get(self, entity_id):
        v = self._m.get(entity_id)
        if v is None:
            return None
        return v if isinstance(v, FakeState) else FakeState(v)

    def set(self, entity_id, state, attributes=None, last_updated=None):
        self._m[entity_id] = FakeState(state, attributes, last_updated)


class FakeServices:
    def __init__(self):
        self.registered = {}  # (domain, name) -> handler
        self.calls = []  # (domain, service, data)

    def async_register(self, domain, name, handler, schema=None):
        self.registered[(domain, name)] = handler

    def async_remove(self, domain, name):
        self.registered.pop((domain, name), None)

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))


class FakeBus:
    def __init__(self):
        self.events = []  # (event_type, data)

    def async_fire(self, event_type, data):
        self.events.append((event_type, data))


class FakeEntry:
    def __init__(self, data=None, options=None, entry_id="entry"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id


class FakeConfigEntries:
    def __init__(self, entries=None):
        self._entries = list(entries or [])

    def async_entries(self, domain):
        return list(self._entries)


class FakeHass:
    def __init__(self, states=None, data=None, entries=None):
        self.states = FakeStates(states)
        self.services = FakeServices()
        self.bus = FakeBus()
        self.data = data or {}
        self.config_entries = FakeConfigEntries(entries)
        self._issues = {}  # issue_id -> kwargs (populated by the issue_registry stub)
