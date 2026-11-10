"""The container's health check, with the real controller on a room a real Home Assistant set up.

The controller's own loop (Controller.run) writes the alive file after a pass that completed, and healthcheck.py,
which Docker runs inside the container, then says healthy. Nothing is asked of Home Assistant for it.
"""

import os

import pytest
from test_setup_entry import _install


async def test_a_fresh_install_goes_healthy_after_its_first_pass(hass, controller_for, monkeypatch):
    import alive
    import healthcheck

    await _install(hass)
    c, _fake, _clock = controller_for({})
    assert healthcheck.main(os.environ) == 1  # not before a pass has completed
    assert alive.health(os.environ) == (False, "the controller has not completed a pass since it started")

    class Done(Exception):
        pass

    def stop_after_the_first_pass(seconds):
        raise Done

    monkeypatch.setattr(c, "_sleep_for", stop_after_the_first_pass)
    monkeypatch.setattr(c, "_start_dosing", lambda: None)
    with pytest.raises(Done):
        await hass.async_add_executor_job(c.run)

    assert healthcheck.main(os.environ) == 0
    with open(os.environ["F2_ALIVE_PATH"], encoding="utf-8") as fh:
        assert float(fh.read()) == 3 * c.loop_seconds + 120  # good for three passes and two minutes
