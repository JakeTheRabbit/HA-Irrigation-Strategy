"""The anthropic_base_url app option in a real Home Assistant: the app's schema accepts it (blank by default, so an
old install's saved options load unchanged), and a fresh install with a router sends the Claude brain's calls there,
needs no Anthropic SDK, and keeps the key out of every state. The router is the one stand-in (no network in a test).
"""

import functools
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import yaml
from homeassistant.helpers.json import json_bytes
from test_setup_entry import _install
from test_upgrade_in_place import KILL

APP_CONFIG = Path(__file__).parents[1] / "addons" / "f2_control" / "config.yaml"
ROUTER = "http://router.example.local:20128"


def test_the_app_schema_accepts_the_router_option_and_defaults_it_blank():
    import runtime_env

    config = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8"))
    assert config["options"]["anthropic_base_url"] == ""
    assert config["schema"]["anthropic_base_url"] == "str?"
    assert runtime_env.OPTION_TYPES["anthropic_base_url"] == "str?"
    for path in sorted((Path(__file__).parent / "fixtures").glob("options_*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))["options"]
        assert set({**config["options"], **saved}) <= set(config["schema"]), path.name


async def test_a_fresh_install_with_a_router_sends_the_brain_there_and_never_shows_the_key(
    hass, controller_for, monkeypatch, capsys
):
    import brain_kit as B
    import jev_bridge
    from jev import client as jc

    def router(url, json=None, headers=None, timeout=None):
        return SimpleNamespace(status_code=503, content=b"{}", headers={})

    monkeypatch.setattr(jc, "anthropic", None)
    monkeypatch.setattr(jc, "requests", SimpleNamespace(post=router))
    monkeypatch.setattr(
        jev_bridge, "Asker", functools.partial(jc.Asker, threaded=False)
    )
    await _install(hass)
    c, fake, _clock = controller_for(
        {
            "enable_flag": KILL,
            "brain_provider": "claude_haiku",
            "anthropic_api_key": B.SENTINEL,
            "anthropic_base_url": ROUTER,
            "anthropic_model": "cc/claude-haiku-5-5",
        }
    )
    assert (c.brain_status.provider, c.brain_status.state) == ("claude_haiku", "acting")
    room = c.rooms[0]
    c.loop_once(datetime.now())

    client = c.jev.asker.transport.routes[0].fn.keywords["client"]
    assert isinstance(client, jc.RouterClient) and client.url == ROUTER + "/v1/messages"
    out = capsys.readouterr().out
    assert f"through the router at {ROUTER}" in out and B.SENTINEL not in out
    entity_id = f"sensor.crop_steering_{room.prefix}jev"
    state, attributes = fake.sets[entity_id]
    hass.states.async_set(entity_id, state, json.loads(json.dumps(attributes, default=str)))
    panel = hass.states.get(entity_id).attributes
    assert panel["provider"] == "claude_haiku" and panel["model"] == "cc/claude-haiku-5-5"
    for stored in hass.states.async_all():
        assert B.SENTINEL not in json_bytes(dict(stored.attributes)).decode()
