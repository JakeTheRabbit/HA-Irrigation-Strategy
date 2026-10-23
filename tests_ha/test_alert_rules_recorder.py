"""Threshold alert rules (G6) against Home Assistant's own recorder: alert_rule_preview and
alert_rule_test replay the recorded history through the rule's lifecycle.

The recorder must be set up before Home Assistant itself, so this module's autouse fixtures ask for
it ahead of the shared ones in conftest.py (which they stand in for, unchanged otherwise).
"""

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_alert_rules import LEVEL, RULE, _call
from test_setup_entry import _install


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
    """The recorder's thread logs every SQL statement at debug; keep the run's output readable."""
    loggers = [
        logging.getLogger(n)
        for n in ("sqlalchemy", "homeassistant.components.recorder")
    ]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    yield
    for logger, level in zip(loggers, levels):
        logger.setLevel(level)


async def test_a_preview_replays_the_recorder(hass, hass_admin_user, freezer):
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    await _install(hass)
    for value, minutes in (("50", 10), ("20", 1), ("50", 10), ("20", 3), ("50", 5)):
        hass.states.async_set(LEVEL, value, {"unit_of_measurement": "%"})
        await hass.async_block_till_done()
        freezer.tick(timedelta(minutes=minutes))
    await async_wait_recording_done(hass)
    preview = await _call(hass, None, "alert_rule_preview", rule=RULE, hours=1)
    assert preview["count"] == 1 and preview["min"] == 20.0 and preview["max"] == 50.0
    (fire,) = preview["fires"]
    assert fire["end"] is not None
    assert [span["reason"] for span in preview["ignored"]] == [
        "shorter than min_duration"
    ]
    assert preview["sentence"].startswith(
        "This rule would have fired once in the last 1 h"
    )
    assert [value for _, value in preview["series"]] == [50.0, 20.0, 50.0, 20.0, 50.0]
    # A test with send pushes through the rule's routing; nobody is set up, and it says so.
    out = await _call(
        hass, hass_admin_user, "alert_rule_test", rule=RULE, hours=1, send=True
    )
    assert out["replay"]["count"] == 1
    assert out["delivery"] == [
        {"service": None, "ok": False, "error": "no phone is set up for notifications"}
    ]
