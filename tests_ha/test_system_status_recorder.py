"""System status against Home Assistant's own recorder: a probe's median report interval over the last hour
sets when it counts as silent, and uptime_7d_pct comes from the recorded state changes.

The recorder must be set up before Home Assistant itself, so this module's autouse fixtures ask for it
ahead of the shared ones in conftest.py (as in test_alert_rules_recorder.py).
"""

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import Context
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_setup_entry import _install

DOMAIN = "crop_steering"
HEALTH = "sensor.crop_steering_system_health"
VWC = "sensor.gt1_vwc"


@pytest.fixture(autouse=True)
def _custom_integrations(recorder_mock, hass, enable_custom_integrations):
    hass.config.components.update({"frontend", "http"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    yield


@pytest.fixture(autouse=True)
def _config_dir_per_test(recorder_mock, hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    yield


@pytest.fixture(autouse=True)
def _quiet_recorder():
    loggers = [logging.getLogger(n) for n in ("sqlalchemy", "homeassistant.components.recorder")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    yield
    for logger, level in zip(loggers, levels):
        logger.setLevel(level)


async def test_a_probe_reporting_every_5_min_stays_online(hass, freezer):
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    await _install(hass)
    # A probe that reports every 5 min for an hour; the EC probe and the valve stay as they were.
    for i in range(12):
        hass.states.async_set(VWC, str(40 + i % 2), {"unit_of_measurement": "%"})
        await hass.async_block_till_done()
        freezer.tick(timedelta(minutes=5))
    hass.states.async_set(VWC, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    hass.states.async_set(VWC, "41", {"unit_of_measurement": "%"})
    await async_wait_recording_done(hass)
    freezer.tick(timedelta(minutes=4))
    async_fire_time_changed(hass)  # the owner's 5-min tick reads the intervals
    await hass.async_block_till_done(wait_background_tasks=True)

    tracker = hass.data[DOMAIN]["_system_status"]
    assert tracker.medians[VWC] == 300.0
    state = hass.states.get(HEALTH)
    assert VWC not in state.attributes["silent"]  # 4 min since its report: under 3 x 5 min

    out = await hass.services.async_call(
        DOMAIN, "system_status_get", {}, blocking=True, return_response=True, context=Context()
    )
    rows = {e["entity_id"]: e for e in out["rooms"][0]["entities"]}
    # Recorded since the install: 60 min online, 30 min unavailable, 4 min online, of 7 days.
    assert rows[VWC]["uptime_7d_pct"] == pytest.approx(64 * 60 / (7 * 86400) * 100)
    assert rows["switch.gt1_irrigation_switch"]["uptime_7d_pct"] > 0
