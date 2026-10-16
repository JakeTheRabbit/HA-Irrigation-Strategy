"""The hourly P2 check is retired, on upgraded installs in a real Home Assistant with the real controller.

Two kinds of box had Cloudflare keys set and Auto setpoints on, so the old check asked Cloudflare once an hour
through P2: an upstream 2.25.1 app that set the keys only for that check (options_2_25_1_cf_policy*.json), and the
3.11.1 app on Cloudflare with every judge but Setpoints (options_3_11_1_jev_cf.json). After the update their
Auto setpoints pass asks nothing over the network, and the working-peak adjustment the check left
(state_3_11_1_learn_jev.json: +1 point on both zones) loads and keeps its saved value.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import fixture
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _jev_3_11_1_app, _upgrade

KILL = "switch.crop_steering_engine_enabled"
P2_HOURS = datetime(2026, 10, 14, 15, 0)  # mid-photoperiod (lights 06-18), the hour after the 3.11.1 state's last ask


class _Clock(datetime):
    current = P2_HOURS

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


@pytest.fixture
def network(monkeypatch):
    """Every way the controller could reach the network, recorded and refused."""
    import requests

    asked = []

    def refuse(*a, **k):
        asked.append((a, k))
        raise requests.ConnectionError("no network in this test")

    for owner, name in ((requests, "post"), (requests, "get"), (requests, "request"), (requests.Session, "request")):
        monkeypatch.setattr(owner, name, refuse)
    return asked


def _p2_hours(c, fake, monkeypatch, hours=3):
    """Every zone of the room through `hours` of P2 in the controller's own Auto setpoints pass, a pass every
    10 minutes, as the hourly check saw them."""
    import controller

    monkeypatch.setattr(controller, "datetime", _Clock)
    # A write lands in the test's fake, not in Home Assistant, so the next read looks like a change and the
    # controller asks Home Assistant's own logbook who made it: that is the web server, not the outside world.
    monkeypatch.setattr(controller, "ha_logbook", lambda entity, since, timeout=8: [])
    room = c.rooms[0]
    c._refresh_lights(room)
    assert c._on(f"switch.crop_steering_{room.prefix}auto_setpoints", False)  # the operator's opt-in, kept
    for zone in room.state:
        room.state[zone]["phase"] = "P2"
    fake.calls.clear()
    for minute in range(0, hours * 60, 10):
        _Clock.current = now = P2_HOURS + timedelta(minutes=minute)
        for zone in room.state:
            snap = SimpleNamespace(vwc=48.0, ec=5.0, dryback_rate=0.0)
            c._auto_tick(room, zone, snap, c._params(room, zone), True, now)
    return room


def _shot_size_writes(fake):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("number", "set_value") and d["entity_id"].endswith("_p2_shot_size")]


@pytest.mark.parametrize("options", ["options_2_25_1_cf_policy.json", "options_2_25_1_cf_policy_merged.json"])
async def test_a_2_25_1_room_with_cloudflare_set_asks_nothing_and_keeps_its_shot_size(
    hass, controller_for, monkeypatch, network, options
):
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    app = fixture(options)
    assert not app["data"]  # no the AI assistant file: no brain, so nothing but the old check ever used the keys
    c, fake, _clock = controller_for(app["options"], saved_state=seed["controller_saved"])
    assert c.jev is None
    assert c.brain_status.notice == "legacy_route_removed"  # the keys load, and nothing uses them
    room = _p2_hours(c, fake, monkeypatch)

    assert network == []
    assert _shot_size_writes(fake) == []
    for zone in room.state:
        attrs = fake.sets[f"sensor.crop_steering_{room.prefix}zone_{zone}_auto_setpoints"][1]
        assert attrs["jev"] == "disabled"
        assert "hourly" not in " ".join(attrs["managed_by"].values())
        was = seed["controller_saved"]["default"][str(zone)]["learn"]
        assert room.state[zone]["learn"]["peak_adj"] == was["peak_adj"]


async def test_a_3_11_1_room_on_cloudflare_asks_nothing_and_keeps_its_working_peak_adjustment(
    hass, controller_for, monkeypatch, network
):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")
    c, fake, _built, _usage, state = _jev_3_11_1_app(controller_for, monkeypatch, "options_3_11_1_jev_cf.json")
    assert c.jev is not None and c.jev.routes == ["Anthropic"]  # the brain moved to Claude with the key added
    old = state["default"]
    for zone in (1, 2):  # the state file loads as 3.11.1 wrote it, the check's record included
        assert c.rooms[0].state[zone]["learn"] == old[str(zone)]["learn"]

    room = _p2_hours(c, fake, monkeypatch)

    assert network == []
    assert _shot_size_writes(fake) == []
    for zone in (1, 2):
        attrs = fake.sets[f"sensor.crop_steering_{room.prefix}zone_{zone}_auto_setpoints"][1]
        assert attrs["jev"] == "disabled" and attrs["working_peak_adjust"] == 1.0
        # the saved "changed today" and last answer are days old: the dashboard is not told them
        assert attrs["jev_last"] is None and attrs["jev_changed_today"] is None
        learn, was = room.state[zone]["learn"], old[str(zone)]["learn"]
        assert learn["peak_adj"] == 1.0 and learn["jev"] == was["jev"]  # nothing writes either again

    assert c._save_state()
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))["default"]
    for zone in ("1", "2"):
        assert saved[zone]["learn"]["peak_adj"] == 1.0
        assert saved[zone]["learn"]["jev"] == old[zone]["learn"]["jev"]
