"""THE AI ASSISTANT PANEL'S SENSORS, as Home Assistant stores them.

The dashboard's AI assistant page reads the room's brain sensor (`sensor.crop_steering_<prefix>jev`), its decision
log and each zone's brain sensor. The controller writes them over REST, so nothing in Home Assistant registers
them: their ids are the ones Jev 3.11.1 wrote, kept so an upgraded install's history and cards still find them.
These tests run the real controller, put what it published into the real state machine, and check what the
recorder would get: every set of attributes under its 16 KB limit (a larger one is dropped from the database),
the panel's fields where the page looks for them, and no key anywhere.
"""

import functools
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from homeassistant.helpers.json import json_bytes
from test_upgrade_in_place import JEV_3_11_1, KILL, _jev_3_11_1_app, _upgrade
from test_setup_entry import _install

from conftest import fixture

# homeassistant.components.recorder.const.MAX_STATE_ATTRS_BYTES: attributes over it are not recorded.
MAX_STATE_ATTRS_BYTES = 16384
RECORDED = Path(__file__).parent / "fixtures" / "data_3_11_1_files"


def _stored(hass, fake, prefix, zones):
    """Each brain sensor the controller published, written into Home Assistant and read back from it."""
    ids = [
        f"sensor.crop_steering_{prefix}jev",
        f"sensor.crop_steering_{prefix}jev_log",
    ] + [f"sensor.crop_steering_{prefix}zone_{zone}_jev" for zone in zones]
    out = {}
    for entity_id in ids:
        if entity_id not in fake.sets:
            continue
        state, attributes = fake.sets[entity_id]
        hass.states.async_set(
            entity_id, state, json.loads(json.dumps(attributes, default=str))
        )
        out[entity_id] = hass.states.get(entity_id)
    return out


def _sizes_fit(stored):
    for entity_id, state in stored.items():
        size = len(json_bytes(dict(state.attributes)))
        assert size < MAX_STATE_ATTRS_BYTES, f"{entity_id}: {size} bytes of attributes"


async def test_a_3_11_1_room_publishes_its_brain_under_the_ids_it_always_had_and_within_the_limit(
    hass, controller_for, monkeypatch
):
    """F-3111 on Cloudflare, with the journal, ledger and setpoint memory its brain wrote: the room keeps the
    old route, and the panel's sensors carry its words under the 3.11.1 ids, each under the recorder's limit.
    """
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    data = Path(os.environ["F2_STATE_PATH"]).parent
    for path in RECORDED.iterdir():
        if path.name.startswith("jev_"):
            shutil.copy(path, data / path.name)
    c, fake, _built, usage, _state = _jev_3_11_1_app(
        controller_for, monkeypatch, "options_3_11_1_jev_cf.json"
    )
    room = c.rooms[0]
    c.loop_once(datetime.fromisoformat(usage["day"]).replace(hour=12))

    stored = _stored(hass, fake, room.prefix, room.zones)
    room_id = f"sensor.crop_steering_{room.prefix}jev"
    assert {room_id, f"sensor.crop_steering_{room.prefix}jev_log"} <= set(stored)
    assert all(
        f"sensor.crop_steering_{room.prefix}zone_{z}_jev" in stored for z in room.zones
    )
    _sizes_fit(stored)
    panel = stored[room_id].attributes
    assert (panel["provider"], panel["state"], panel["deprecated_route"]) == (
        "jev_legacy",
        "legacy",
        True,
    )
    assert isinstance(panel["key_set"], bool) and panel["state_words"]
    assert panel["stage"] is None or isinstance(panel["stage"], dict)
    assert stored[f"sensor.crop_steering_{room.prefix}jev_log"].attributes["entries"]


async def test_a_claude_brain_that_cannot_reach_anthropic_publishes_its_panel_within_the_limit(
    hass, controller_for, monkeypatch
):
    """A fresh install on Claude Haiku whose every call fails (the Anthropic API is the one stand-in): the
    panel says so, carries its spend and judges, stays under the recorder's limit, and holds no key.
    """
    import brain_kit as B
    import jev_bridge
    from jev import client as jc

    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(B.FakeClient(B.APIStatusError(503))))
    monkeypatch.setattr(
        jev_bridge, "Asker", functools.partial(jc.Asker, threaded=False)
    )
    await _install(hass)
    c, fake, _clock = controller_for(
        {
            "enable_flag": KILL,
            "brain_provider": "claude_haiku",
            "anthropic_api_key": B.SENTINEL,
        }
    )
    room = c.rooms[0]
    c.loop_once(datetime.now())

    stored = _stored(hass, fake, room.prefix, room.zones)
    _sizes_fit(stored)
    panel = stored[f"sensor.crop_steering_{room.prefix}jev"].attributes
    assert panel["provider"] == "claude_haiku" and panel["key_set"] is True
    assert panel["budget_usd"] == 1.0 and panel["spent_usd"] >= 0
    for state in hass.states.async_all():
        assert B.SENTINEL not in json_bytes(dict(state.attributes)).decode()
