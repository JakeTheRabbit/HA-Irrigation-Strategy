"""Shared AppDaemon hassapi stub for intelligence module tests.

Importing this module installs a fake `appdaemon.plugins.hass.hassapi`
into `sys.modules` so the production modules can `import` it without a
real AppDaemon runtime. Idempotent — safe to import from multiple
test files.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

if "appdaemon.plugins.hass.hassapi" not in sys.modules:
    ad_module = types.ModuleType("appdaemon"); ad_module.__path__ = []
    ad_plugins = types.ModuleType("appdaemon.plugins"); ad_plugins.__path__ = []
    ad_hass = types.ModuleType("appdaemon.plugins.hass"); ad_hass.__path__ = []
    ad_hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")

    class _Hass:
        def __init__(self):
            self.app_dir = "."
            self.args = {}

        def get_state(self, *a, **kw): return None
        def set_state(self, *a, **kw): pass
        def listen_event(self, *a, **kw): pass
        def listen_state(self, *a, **kw): pass
        def run_every(self, *a, **kw): pass
        def run_in(self, *a, **kw): pass
        def run_daily(self, *a, **kw): pass
        def fire_event(self, *a, **kw): pass
        def call_service(self, *a, **kw): pass
        def register_service(self, *a, **kw): pass
        def log(self, *a, **kw): pass

    ad_hassapi.Hass = _Hass
    sys.modules["appdaemon"] = ad_module
    sys.modules["appdaemon.plugins"] = ad_plugins
    sys.modules["appdaemon.plugins.hass"] = ad_hass
    sys.modules["appdaemon.plugins.hass.hassapi"] = ad_hassapi

# Make the appdaemon/apps directory importable.
_ROOT = Path(__file__).resolve().parents[2]
_APPS = str(_ROOT / "appdaemon" / "apps")
if _APPS not in sys.path:
    sys.path.insert(0, _APPS)
