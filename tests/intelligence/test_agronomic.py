"""Unit tests for AgronomicIntelligence transpiration and VPD math."""
from __future__ import annotations

import math

import pytest

from . import _appdaemon_stub  # noqa: F401

from crop_steering.intelligence.agronomic import AgronomicIntelligence  # noqa: E402
from crop_steering.intelligence.bus import RootSenseBus  # noqa: E402


@pytest.fixture
def agro(tmp_path):
    a = AgronomicIntelligence.__new__(AgronomicIntelligence)
    a.app_dir = str(tmp_path)
    a.args = {}
    from collections import defaultdict, deque
    a.bus = RootSenseBus.instance()
    # Mirror what AgronomicIntelligence.initialize() sets up — we skip
    # initialize() in tests to avoid AppDaemon I/O.
    a._samples = defaultdict(lambda: deque(maxlen=720))
    a._dryback_window = defaultdict(lambda: deque(maxlen=120))
    a.air_movement_m_s = 0.3
    a.canopy_temp_entity = None
    a.air_temp_entity = "sensor.test_air_temp"
    a.rh_entity = "sensor.test_rh"
    a.ppfd_entity = None
    a.lights_off_entity = "binary_sensor.test_lights"
    a._is_module_enabled = lambda: True

    a._states: dict[str, str | None] = {}
    a.get_state = lambda eid, *_, **__: a._states.get(eid)
    a.set_state = lambda *args, **kw: None
    a.log = lambda *args, **kw: None
    a.fire_event = lambda *args, **kw: None
    a.entity_exists = lambda eid: True
    return a


# ---------------------------------------------------------------------------
# VPD calculation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("temp_c, rh_pct, expected_kpa", [
    (20.0, 50.0, 1.17),   # cold + half humidity
    (25.0, 50.0, 1.58),
    (28.0, 60.0, 1.51),
    (30.0, 80.0, 0.85),   # hot but humid
])
def test_vpd_falls_within_expected_envelope(agro, temp_c, rh_pct, expected_kpa):
    """Sanity-check VPD math against published Athena VPD chart values."""
    agro._states["sensor.test_air_temp"] = str(temp_c)
    agro._states["sensor.test_rh"] = str(rh_pct)
    vpd = agro._read_vpd_kpa()
    assert vpd is not None
    assert vpd == pytest.approx(expected_kpa, abs=0.10), (
        f"VPD({temp_c}°C, {rh_pct}% RH) = {vpd:.3f} kPa; expected ≈ {expected_kpa}"
    )


def test_vpd_returns_none_when_sensors_missing(agro):
    """If temp/RH sensors are unavailable VPD must be None, not 0 or NaN."""
    # Both sensors absent
    assert agro._read_vpd_kpa() is None

    # Only one absent
    agro._states["sensor.test_air_temp"] = "25.0"
    assert agro._read_vpd_kpa() is None


def test_vpd_uses_precomputed_sensor_when_present(agro):
    """If the user already publishes a VPD sensor, use it directly."""
    agro._states["sensor.crop_steering_vpd"] = "1.42"
    assert agro._read_vpd_kpa() == pytest.approx(1.42, abs=0.001)


# ---------------------------------------------------------------------------
# Penman-Monteith approximation
# ---------------------------------------------------------------------------

def test_transpiration_increases_with_vpd(agro):
    low = agro._penman_monteith_ml_per_hr(vpd_kpa=0.4, ppfd=800)
    mid = agro._penman_monteith_ml_per_hr(vpd_kpa=1.0, ppfd=800)
    high = agro._penman_monteith_ml_per_hr(vpd_kpa=1.6, ppfd=800)
    assert low < mid < high


def test_transpiration_increases_with_ppfd(agro):
    """At fixed VPD, more light → more transpiration."""
    dim = agro._penman_monteith_ml_per_hr(vpd_kpa=1.0, ppfd=200)
    bright = agro._penman_monteith_ml_per_hr(vpd_kpa=1.0, ppfd=1500)
    assert bright > dim


def test_transpiration_zero_at_zero_vpd(agro):
    """No driving gradient → zero transpiration."""
    assert agro._penman_monteith_ml_per_hr(vpd_kpa=0.0, ppfd=800) == 0.0


def test_transpiration_within_realistic_envelope(agro):
    """A 1 m² canopy at typical grow-room conditions should fall in
    a plausible range. We're sanity-checking the model isn't returning
    pathological values like 10 L/h."""
    typical = agro._penman_monteith_ml_per_hr(vpd_kpa=1.2, ppfd=900)
    # Anchor: a healthy cannabis plant transpires roughly 50-300 mL/h
    # depending on size, canopy density, and conditions. The model is
    # scaled per-plant via a /4 fudge factor — assert we land in the
    # right order of magnitude.
    assert 10 < typical < 500, f"transpiration outside plausible range: {typical}"


# ---------------------------------------------------------------------------
# VPD ceiling correlation
# ---------------------------------------------------------------------------

def test_vpd_ceiling_published_after_enough_samples(agro):
    """After ≥10 dryback events with rising velocity past a VPD threshold,
    the agronomic module publishes a vpd_ceiling sensor."""
    captured: list[tuple[str, dict]] = []

    def fake_set_state(entity_id, **kw):
        captured.append((entity_id, kw))

    agro.set_state = fake_set_state

    agro._states["select.crop_steering_zone_1_crop_type"] = "Cannabis_Athena"
    # 12 samples: half at low VPD/low velocity, half at high VPD/high velocity
    for i in range(6):
        agro._on_dryback_complete("dryback.complete", {
            "zone": 1, "slope_pct_h": 0.5, "vpd_avg": 0.8,
        })
    for i in range(6):
        agro._on_dryback_complete("dryback.complete", {
            "zone": 1, "slope_pct_h": 1.6, "vpd_avg": 1.6,
        })
    ceiling_writes = [eid for eid, _ in captured
                      if "vpd_ceiling_kpa" in eid]
    assert ceiling_writes, "expected a vpd_ceiling sensor publish"
