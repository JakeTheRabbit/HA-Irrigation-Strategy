"""The Claude brain inside the real controller (brain_provider: claude_haiku): it asks through the enrichment hook and
the Anthropic transport, acts only through the envelope, falls back to exactly the base engine whenever it cannot
act, says why on the brain panel, and never lets the key out (haiku-brain-design sections 2, 9, 10, 13, 15)."""
import functools
import json
import os
from datetime import timedelta

import brain_kit as B
import jev_bridge
import pytest
from jev import client as jc
from test_controller import _build
from test_jev_controller import KILL, NOW, _p1_zone, _states, _switches


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _zone(c):
    """The ramp zone of test_jev_controller with its last shot 12 minutes old: the ramp judge is due (10 min) and no
    ramp shot is (15 min), so a pass fires nothing and takes no shot time."""
    st = _p1_zone(c)
    st["last_shot"] = NOW - timedelta(minutes=12)
    return st


@pytest.fixture
def claude(monkeypatch):
    """Build controllers whose brain is Claude with a fake SDK client, answered synchronously."""
    def make(*script, sdk=True, **options):
        fake_client = B.FakeClient(*(script or (B.judging(),)))
        made = B.FakeSDK(fake_client)
        monkeypatch.setattr(jc, "anthropic", made if sdk else None)
        clock = Clock(NOW.timestamp())
        monkeypatch.setattr(jev_bridge, "Asker", functools.partial(jc.Asker, threaded=False, clock=clock))
        monkeypatch.setattr(jev_bridge, "Meter", functools.partial(jc.Meter, clock=clock))
        monkeypatch.setattr(jev_bridge, "Routes", functools.partial(jc.Routes, sleep=lambda s: None))
        opts = {"num_zones": 1, "enable_flag": KILL, "brain_provider": "claude_haiku",
                "anthropic_api_key": B.SENTINEL, **options}
        c, fake = _build(opts, states=_states())
        c._clock, c._client, c._sdk = clock, fake_client, made
        return c, fake
    return make


def _base():
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    _zone(c)
    c.loop_once(NOW)
    return c, fake


def _writes(fake):
    return [(dom, svc, d.get("entity_id"), d.get("value")) for dom, svc, d in fake.calls if dom in ("switch", "number")]


def test_the_claude_brain_asks_with_its_evidence_and_acts_through_the_envelope(claude):
    c, fake = claude(B.judging({"ramp_state": "ec_is_feed_front"}))
    assert c.jev.status.provider == "claude_haiku" and c.jev.routes == ["Anthropic"]
    assert c._sdk.built == [{"api_key": B.SENTINEL, "base_url": "https://api.anthropic.com", "max_retries": 0}]
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests, "it asked"
    sent = c._client.requests[0]["messages"][0]["content"][0]["text"]
    assert sent.startswith('<snapshot id="default:z1:ramp:') and "numbers: {" in sent and "interlocks: kill switch on" in sent
    assert c.rooms[0].state[1]["phase"] == "P2"  # the ramp judge's admitted hand-over, as on the legacy route
    panel = fake.sets["sensor.crop_steering_jev"][1]
    assert (panel["provider"], panel["state"], panel["key_set"], panel["model"]) == (
        "claude_haiku", "acting", True, "claude-haiku-5-5")
    assert "ramp" in panel["judges_acting"] and panel["spent_usd"] > 0 and panel["cost_usd_today"] == panel["spent_usd"]


@pytest.mark.parametrize("failure", [
    B.AuthenticationError("bad key " + B.SENTINEL), B.APIStatusError(404), B.RateLimitError(), B.APIStatusError(529),
    B.APITimeoutError(), B.APIConnectionError(), B.message(B.tool("answer_choice", snapshot_id="x")),
    B.message(stop="refusal", category="bio"),
], ids=["401", "404", "429", "529", "timeout", "connection", "malformed", "refusal"])
def test_whatever_fails_the_engine_decides_exactly_as_on_rules(claude, failure, capsys):
    base, base_fake = _base()
    c, fake = claude(failure)
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests and c.rooms[0].state[1]["phase"] == base.rooms[0].state[1]["phase"] == "P1"
    assert _switches(fake) == _switches(base_fake) and _writes(fake) == _writes(base_fake)
    seen = json.dumps({k: v for k, v in fake.sets.items()}, default=str) + capsys.readouterr().out
    data = os.path.dirname(os.environ["F2_STATE_PATH"])
    for name in ("jev_usage.json", "jev_journal.jsonl"):
        path = os.path.join(data, name)
        seen += open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    assert B.SENTINEL not in seen and os.path.exists(os.path.join(data, "jev_usage.json"))


def test_a_refused_key_stops_every_call_and_says_so_once(claude):
    c, fake = claude(B.AuthenticationError())
    _zone(c)
    c.loop_once(NOW)
    asked = len(c._client.requests)
    c.loop_once(NOW + timedelta(minutes=20))
    assert len(c._client.requests) == asked == 1
    panel = fake.sets["sensor.crop_steering_jev"][1]
    assert panel["state"] == "auth_failed" and "refused" in panel["state_words"] and panel["judges_acting"] == []
    created = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]
    assert [d["notification_id"] for d in created if "(CS-709)" in d["title"]] == ["f2_jev_brain_default"]


def test_a_spent_budget_runs_rules_until_lights_on_and_says_so(claude):
    c, fake = claude(B.judging(), anthropic_daily_budget_usd=0.0001)
    _zone(c)
    c.loop_once(NOW)
    asked = len(c._client.requests)
    c.loop_once(NOW + timedelta(minutes=20))
    assert len(c._client.requests) == asked  # no new ask once it is spent
    panel = fake.sets["sensor.crop_steering_jev"][1]
    assert panel["state"] == "budget_spent" and "Rules until the next lights-on" in panel["state_words"]
    assert jev_bridge.judge_levers(c, c.rooms[0]) == ()  # the learner holds the Setpoints judge's numbers
    created = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]
    assert [d["notification_id"] for d in created if "(CS-708)" in d["title"]] == ["f2_jev_spent_default"]
    c._clock.t += 21 * 3600
    jev_bridge.lights_on(c, c.rooms[0], NOW + timedelta(hours=21))
    assert c.jev.asker.meter.state() is None and jev_bridge.judge_levers(c, c.rooms[0])


def test_dry_run_journals_what_it_would_do_and_moves_nothing(claude):
    base, base_fake = _base()
    c, fake = claude(B.judging({"ramp_state": "ec_is_feed_front"}), brain_dry_run=True)
    _zone(c)
    c.loop_once(NOW)
    assert c.rooms[0].state[1]["phase"] == "P1" and _switches(fake) == _switches(base_fake)
    assert c.jev.ledger.entries == []
    entry = next(e for e in c.jev.journal.recent("default") if e["judge"] == "ramp")
    assert entry["result"] == "would act" and entry["action"] == "hand over to maintenance"
    assert fake.sets["sensor.crop_steering_jev"][1]["mode"] == "dry_run"
    assert jev_bridge.judge_levers(c, c.rooms[0]) == ()


@pytest.mark.parametrize("options, sdk, state", [
    ({"brain_provider": "auto", "anthropic_api_key": ""}, True, "rules"),
    ({"anthropic_api_key": ""}, True, "rules_no_key"),
    ({"anthropic_model": "claude-x-9"}, True, "model_invalid"),
    ({}, False, "sdk_missing"),
    ({"brain_provider": "rules"}, True, "rules"),
], ids=["fresh", "no-key", "model", "sdk", "rules"])
def test_every_rules_case_reaches_the_brain_panel(claude, options, sdk, state):
    c, fake = claude(sdk=sdk, **options)
    assert c.jev is None and c.brain_status.state == state
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests == []
    room, attrs = fake.sets["sensor.crop_steering_jev"]
    assert room == "rules" and attrs["state"] == state and attrs["state_words"] and attrs["provider"] == "rules"
    assert fake.sets["sensor.crop_steering_zone_1_jev"][0] == "rules"


def test_a_start_that_raises_runs_rules_and_says_so(claude, monkeypatch):
    monkeypatch.setattr(jev_bridge, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(B.SENTINEL)))
    c, fake = claude()
    assert c.jev is None and c.brain_status.state == "start_failed"
    _zone(c)
    c.loop_once(NOW)
    assert fake.sets["sensor.crop_steering_jev"][1]["state"] == "start_failed"


def test_cloudflare_settings_no_brain_uses_raise_the_retired_route_card_once_a_release(monkeypatch):
    c, fake = _build({"num_zones": 1, "enable_flag": KILL, "cf_account_id": "acct", "cf_api_token": "tok"},
                     states=_states())
    assert c.jev is None and c.brain_status.notice == "cloudflare_route_retired"
    _zone(c)
    c.loop_once(NOW)
    c.loop_once(NOW + timedelta(minutes=1))
    created = [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]
    assert [d["notification_id"] for d in created if "(CS-712)" in d["title"]] == ["f2_jev_route_default"]
    again, fake2 = _build({"num_zones": 1, "enable_flag": KILL, "cf_account_id": "acct", "cf_api_token": "tok"},
                          states=_states())
    again._state_path = c._state_path  # the same /data after a restart
    _zone(again)
    again.loop_once(NOW)
    assert not [d for dom, svc, d in fake2.calls if "(CS-712)" in str(d.get("title"))]


def test_a_legacy_install_switched_to_rules_shows_rules_on_its_first_pass():
    import jev_kit as K

    K.has_run()
    c, fake = _build({"num_zones": 1, "enable_flag": KILL, "cf_account_id": "acct", "cf_api_token": "tok",
                      "brain_provider": "rules"}, states=_states())
    fake.set_state("sensor.crop_steering_jev", "on", {"routes": ["Cloudflare"]})
    _zone(c)
    c.loop_once(NOW)
    state, attrs = fake.sets["sensor.crop_steering_jev"]
    assert state == "rules" and "routes" not in attrs


def test_the_usage_file_names_the_brain_before_its_first_ask(claude):
    c, _ = claude()
    with open(c.jev.usage_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["provider"] == "claude_haiku" and saved["meter"]["cost_usd"] == 0 and B.SENTINEL not in str(saved)
