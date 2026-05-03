"""Unit tests for the cultivator-intent resolver in adaptive_irrigation.py.

These tests exercise the pure interpolation + derived-mode bucketing
without an AppDaemon runtime. The AppDaemon hooks are stubbed by
sharing the same test scaffolding as test_dryback_tracker.py.
"""
from __future__ import annotations

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.adaptive_irrigation import (  # noqa: E402
    AdaptiveIrrigation,
    ENTITY_VEG_DRYBACK_DROP,
    ENTITY_GEN_DRYBACK_DROP,
    GENERATIVE_PROFILE,
    INTENT_ENTITY,
    PARAM_TO_ENTITY,
    VEGETATIVE_PROFILE,
    lerp,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_lerp_endpoints_and_midpoint():
    assert lerp(10.0, 20.0, 0.0) == pytest.approx(10.0)
    assert lerp(10.0, 20.0, 1.0) == pytest.approx(20.0)
    assert lerp(10.0, 20.0, 0.5) == pytest.approx(15.0)


def test_intent_endpoints_match_profile_dicts():
    """Sanity check: the endpoint dicts should disagree on every parameter
    we actually interpolate, otherwise the slider does nothing."""
    overlap = {k for k in GENERATIVE_PROFILE if k in VEGETATIVE_PROFILE
               and GENERATIVE_PROFILE[k] == VEGETATIVE_PROFILE[k]}
    assert overlap == set(), f"identical endpoints for: {overlap}"


def test_param_to_entity_covers_every_profile_key():
    missing = set(GENERATIVE_PROFILE) - set(PARAM_TO_ENTITY)
    assert missing == set(), f"profile keys with no entity mapping: {missing}"


# ---------------------------------------------------------------------------
# Resolver behaviour
# ---------------------------------------------------------------------------

@pytest.fixture
def resolver(tmp_path):
    """Build an AdaptiveIrrigation with all I/O captured."""
    a = AdaptiveIrrigation.__new__(AdaptiveIrrigation)
    a.app_dir = str(tmp_path)
    a.args = {}

    # Capture every service / state write.
    a._writes = []
    a._service_calls = []
    a._state_writes = []

    def fake_call_service(name, **kw):
        a._service_calls.append((name, kw))

    def fake_set_state(entity_id, **kw):
        a._state_writes.append((entity_id, kw))

    a.call_service = fake_call_service
    a.set_state = fake_set_state
    a.log = lambda *a_, **k_: None
    a.entity_exists = lambda eid: True  # accept every entity write

    # Defaults for read entities
    a._states: dict[str, str] = {
        INTENT_ENTITY: "0",
        ENTITY_VEG_DRYBACK_DROP: str(VEGETATIVE_PROFILE["p0_dryback_drop_pct"]),
        ENTITY_GEN_DRYBACK_DROP: str(GENERATIVE_PROFILE["p0_dryback_drop_pct"]),
    }
    a.get_state = lambda eid, *_, **__: a._states.get(eid)

    # Tiny bus that records publishes.
    class _Bus:
        def __init__(self): self.events = []
        def publish(self, topic, payload): self.events.append((topic, payload))
        def subscribe(self, *a_, **k_): pass

    a.bus = _Bus()
    return a


def _values(resolver, entity_id):
    """Return the sequence of values written to a given number entity."""
    return [kw["value"] for name, kw in resolver._service_calls
            if name == "number/set_value" and kw.get("entity_id") == entity_id]


def test_intent_zero_yields_midpoint(resolver):
    resolver._states[INTENT_ENTITY] = "0"
    resolver._publish_intent_derived_params({})

    # P0 dryback at intent=0 should be midway between veg and gen endpoints.
    veg = VEGETATIVE_PROFILE["p0_dryback_drop_pct"]
    gen = GENERATIVE_PROFILE["p0_dryback_drop_pct"]
    expected = round((veg + gen) / 2, 2)
    written = _values(resolver, "number.crop_steering_p0_dryback_drop_percent")
    assert written, "no write to interpolated p0 dryback entity"
    assert written[-1] == pytest.approx(expected, abs=0.01)


def test_intent_full_vegetative_matches_veg_endpoint(resolver):
    resolver._states[INTENT_ENTITY] = "100"
    resolver._publish_intent_derived_params({})
    written = _values(resolver, "number.crop_steering_p1_target_vwc")
    assert written[-1] == pytest.approx(VEGETATIVE_PROFILE["p1_target_vwc"], abs=0.01)


def test_intent_full_generative_matches_gen_endpoint(resolver):
    resolver._states[INTENT_ENTITY] = "-100"
    resolver._publish_intent_derived_params({})
    written = _values(resolver, "number.crop_steering_p1_target_vwc")
    assert written[-1] == pytest.approx(GENERATIVE_PROFILE["p1_target_vwc"], abs=0.01)


def test_p0_dryback_endpoints_read_live_from_sliders(resolver):
    """If the operator changes the gen/veg dryback sliders, the resolver
    must use the live values, not the static profile dict."""
    resolver._states[INTENT_ENTITY] = "100"             # full vegetative
    resolver._states[ENTITY_VEG_DRYBACK_DROP] = "8.0"   # operator override
    resolver._publish_intent_derived_params({})
    written = _values(resolver, "number.crop_steering_p0_dryback_drop_percent")
    assert written[-1] == pytest.approx(8.0, abs=0.01)


def test_derived_mode_bucketing(resolver):
    """Each intent bucket maps to a specific Steering Mode label."""
    expected = [
        (-100, "Generative"),
        (-60, "Generative"),
        (-40, "Mixed-generative"),
        (-20, "Mixed-generative"),
        (-19, "Balanced"),
        (0, "Balanced"),
        (19, "Balanced"),
        (20, "Mixed-vegetative"),
        (40, "Mixed-vegetative"),
        (60, "Vegetative"),
        (100, "Vegetative"),
    ]
    for intent, want in expected:
        resolver._service_calls.clear()
        resolver._states[INTENT_ENTITY] = str(intent)
        resolver._publish_intent_derived_params({})
        select_calls = [kw["option"] for name, kw in resolver._service_calls
                        if name == "select/select_option"]
        assert select_calls and select_calls[-1] == want, (
            f"intent={intent} produced {select_calls!r}, expected {want!r}"
        )


def test_derived_dryback_sensor_attributes(resolver):
    resolver._states[INTENT_ENTITY] = "50"
    resolver._states[ENTITY_VEG_DRYBACK_DROP] = "12.0"
    resolver._states[ENTITY_GEN_DRYBACK_DROP] = "22.0"
    resolver._publish_intent_derived_params({})

    sensor_writes = [kw for eid, kw in resolver._state_writes
                     if eid == "sensor.crop_steering_p0_dryback_drop_pct_current"]
    assert sensor_writes, "expected derived sensor publish"
    last = sensor_writes[-1]
    attrs = last["attributes"]
    assert attrs["veg_endpoint"] == 12.0
    assert attrs["gen_endpoint"] == 22.0
    assert attrs["intent"] == 50.0
    assert "drop from peak" in attrs["semantic"]
