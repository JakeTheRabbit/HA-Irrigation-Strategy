"""The "kill switch helper missing" repair, against a real Home Assistant and the real controller.

First real install, 2026-09-21: the controller app was added and started first, the integration
was set up afterwards, and sixty seconds after a clean wizard run Settings > Repairs showed an
ERROR telling the operator to create `input_boolean.f2_control_enabled` by hand. A fresh room
never uses that helper (the wizard gives it `switch.crop_steering_engine_enabled`); the name came
from the add-on's shipped `enable_flag` option, which a controller with no room to read falls
back to and reports on its heartbeat until it adopts the new setup. Following the card would have
left the room with two kill switches, one of which does nothing.

Both install orders and the in-place upgrades are here, and the health check is the real
scheduled one (sixty seconds after the entry sets up, then every five minutes), counted, so that
"no repair" can never pass because no check ran.
"""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.crop_steering import health
from test_real_flow import VALVE
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"
LEGACY = "input_boolean.f2_control_enabled"
OWN = "switch.crop_steering_engine_enabled"
HEARTBEAT = "sensor.crop_steering_ai_heartbeat"
_CONFIG = Path(__file__).resolve().parents[1] / "addons" / "f2_control" / "config.yaml"


def _shipped_options():
    """The add-on options a new install really gets: the `options:` block of config.yaml."""
    block = _CONFIG.read_text(encoding="utf-8").split("\noptions:\n", 1)[1].split("\nschema:", 1)[0]
    options = {}
    for line in block.splitlines():
        found = re.fullmatch(r"  (\w+): (.*)", line)
        if found:
            key, value = found.group(1), found.group(2).strip().strip('"')
            options[key] = [] if value == "[]" else value
    for key in ("num_zones",):
        options[key] = int(options[key])
    for key in ("lights_on_hour", "lights_off_hour", "notify_min", "substrate_l", "flow_lps",
                "loop_seconds", "rediscover_seconds"):
        options[key] = float(options[key])
    return options


def _report(hass, controller, fake):
    """The controller's next heartbeat, as Home Assistant holds it after the REST write."""
    controller._heartbeat(controller.rooms[0], datetime.now(), None)
    state, attributes = fake.sets[HEARTBEAT]
    hass.states.async_set(HEARTBEAT, state, attributes)
    return attributes


def _see(hass, fake):
    """Let the controller see Home Assistant as it is now (it reads over REST every loop)."""
    for state in hass.states.async_all():
        attributes = json.loads(json.dumps(dict(state.attributes), default=str))
        fake.set_state(state.entity_id, state.state, attributes)


@pytest.fixture
def checks(monkeypatch):
    """Every run of the REAL health check. Patched before any entry sets up, because the entry
    imports the function when it schedules it."""
    ran = []
    real = health.run_health_check

    def counted(hass, entry):
        ran.append(entry.entry_id)
        return real(hass, entry)

    monkeypatch.setattr(health, "run_health_check", counted)
    return ran


async def _health_check_fires(hass, checks):
    """Run the entry's own timers. Every timer, rather than "those due in 61 s": the controller
    harness freezes time.monotonic for the whole process, which is the clock asyncio timers are
    due by, so a time-based firing silently fires nothing once a controller has been built."""
    before = len(checks)
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()
    assert len(checks) > before, "the scheduled health check did not run"


def _repair(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, "kill_switch_missing")


def test_the_premise_a_new_install_is_shipped_the_legacy_helper_as_its_enable_flag():
    assert _shipped_options()["enable_flag"] == LEGACY


# ------------------------------------------------------------------ fresh install, app first
async def test_the_controller_started_first_and_setup_second_raises_no_repair(hass, controller_for, checks):
    c, fake, _clock = controller_for(_shipped_options())  # no integration yet: nothing to read
    c.loop_once(datetime.now())
    for entity_id, (state, attributes) in fake.sets.items():
        hass.states.async_set(entity_id, state, attributes)  # whatever it has already published
    assert _report(hass, c, fake)["enable_flag"] == LEGACY
    assert hass.states.get(LEGACY) is None  # and a fresh install has no such helper

    await _install(hass)
    assert hass.states.get(OWN).state == "off"  # the kill switch this room really has
    descriptor = hass.states.get("sensor.crop_steering_engine_config").attributes
    assert descriptor["enable_flag"] == OWN and descriptor["setup_revision"] == 1
    assert _report(hass, c, fake)["setup_revision"] == 0  # the controller has not caught up yet

    await _health_check_fires(hass, checks)
    assert _repair(hass) is None  # was: ERROR "create input_boolean.f2_control_enabled"

    # The controller catches up by itself (everything reads OFF), and nothing changes its mind.
    _see(hass, fake)
    c._rediscover(datetime.now())
    room = c.rooms[0]
    assert room.setup_revision == 1 and room._setup_pending is None
    assert room.enable_flag == OWN and sorted(room.zones) == [1]
    assert room.hw["valves"] == {1: VALVE}
    assert _report(hass, c, fake)["enable_flag"] == OWN
    await _health_check_fires(hass, checks)
    assert _repair(hass) is None


async def test_a_room_whose_own_kill_switch_is_gone_is_still_reported_while_the_engine_is_behind(
    hass, controller_for, checks
):
    c, fake, _clock = controller_for(_shipped_options())
    _report(hass, c, fake)
    await _install(hass)
    er.async_get(hass).async_remove(OWN)
    await hass.async_block_till_done()
    assert hass.states.get(OWN) is None
    await _health_check_fires(hass, checks)
    assert _repair(hass) is not None


# ------------------------------------------------------------------ fresh install, setup first
async def test_setup_first_and_the_controller_second_raises_no_repair(hass, controller_for, checks):
    await _install(hass)
    c, fake, _clock = controller_for(_shipped_options())
    assert c.rooms[0].enable_flag == OWN  # the documented order always worked
    assert _report(hass, c, fake)["enable_flag"] == OWN
    await _health_check_fires(hass, checks)
    assert _repair(hass) is None


# ------------------------------------------------------------------ upgrade in place
@pytest.mark.parametrize("name", ["entry_2_18_one_switch_tent.json", "entry_2_17_wizard.json"])
async def test_an_upgraded_wizard_room_raises_no_repair(hass, controller_for, checks, name):
    _entry, seed = await _upgrade(hass, name)
    c, fake, _clock = controller_for(
        _shipped_options(), saved_state=seed.get("controller_saved")
    )
    beat = _report(hass, c, fake)
    assert beat["enable_flag"] == OWN and beat["setup_revision"] == seed["data"]["setup_revision"]
    await _health_check_fires(hass, checks)
    assert _repair(hass) is None


async def test_an_upgraded_legacy_room_is_judged_on_its_helper_exactly_as_before(
    hass, controller_for, checks
):
    """An env-era room is gated by the legacy helper, and its controller is never "behind": the
    descriptor and the heartbeat both report revision 0. Present: no repair. Deleted: the repair,
    which is the case the card was written for."""
    hass.states.async_set(LEGACY, "off")
    await _upgrade(hass, "entry_env_era.json")
    c, fake, _clock = controller_for(_shipped_options())
    beat = _report(hass, c, fake)
    assert beat["enable_flag"] == LEGACY and beat["setup_revision"] == 0
    await _health_check_fires(hass, checks)
    assert _repair(hass) is None

    hass.states.async_remove(LEGACY)
    await _health_check_fires(hass, checks)
    assert _repair(hass) is not None
