"""Tests that run inside a REAL Home Assistant (pytest-homeassistant-custom-component).

Everything under tests/ drives the integration against hand-written stubs. That is fast, and it is
also how 2.17.0 shipped two switches whose entity ids Home Assistant generated from their labels:
the stub tests asserted an attribute the real entity platform ignores. These tests load the real
config flow and the real entity registry, so they fail when Home Assistant would.

Run: `python -m pytest tests_ha -q` on Python 3.13 with requirements-test-ha.txt installed. They are
kept out of tests/ because that suite replaces the `homeassistant` package with stubs.
"""

import pytest


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/crop_steering from this repository."""
    yield
