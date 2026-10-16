"""The Claude brain through an Anthropic-compatible router (anthropic_base_url): the requests go to the router's
address, a reply with a line after its JSON message and tool names with a suffix still answers, a router-prefixed
model is priced at its model's row, every failure keeps its classification, and an unreachable router leaves the
engine exactly as on rules. No test reaches the network: the router is a fake `post`."""
import functools
import json
from json import dumps as json_dumps
import os
from datetime import timedelta
from types import SimpleNamespace

import brain_kit as B
import jev_bridge
import pytest
import runtime_env
from jev import client as jc
from jev.client import BAD_OUTPUT, Meter, RouterClient, call_anthropic, cost, tool_name
from test_controller import _build
from test_jev_controller import KILL, NOW, _states, _switches
from test_brain_wiring import Clock, _base, _writes, _zone

ROUTER = "http://router.example.local:20128"
ROUTED = "cc/claude-haiku-5-5"


def _plain(obj):
    if isinstance(obj, SimpleNamespace):
        return {k: _plain(v) for k, v in vars(obj).items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


class Router:
    """A router that answers like the owner's: the JSON message, then a "data: [DONE]" line, and every tool name with
    "_ide" added. `script` items are as for brain_kit.FakeClient, or a response (status, body) to send as it is."""

    def __init__(self, *script):
        self.script, self.posts = list(script), []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if callable(item) and not isinstance(item, type):
            item = item(json)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, tuple):
            status, body = item
            return SimpleNamespace(status_code=status, content=body.encode(), headers={"retry-after": "30"})
        message = _plain(item)
        message["content"] = [{**b, "name": b["name"] + "_ide"} if b.get("type") == "tool_use" else b
                              for b in message["content"]]
        text = json_dumps({"type": "message", "model": "claude-haiku-5-5", **message})
        return SimpleNamespace(status_code=200, content=(text + "\n\ndata: [DONE]\n\n").encode(), headers={})


def _refused():
    """What requests raises when nothing listens at the router's address."""
    error = type("ConnectionError", (Exception,), {})
    return error("HTTPConnectionPool: Max retries exceeded (Caused by NewConnectionError('refused'))")


class Prompt(B.FakePrompt):
    """brain_kit's prompt with the tools the real one offers, which a suffixed name is matched against."""

    def request(self, model, evidence, questions, max_tokens):
        tools = [{"name": n} for n in ("answer_choice", "answer_yes_no", "answer_why", "write_report")]
        return {**super().request(model, evidence, questions, max_tokens), "tools": tools}


def _call(router, model=jc.DEFAULT_MODEL, meter=None, questions=None):
    client = RouterClient(B.SENTINEL, ROUTER + "/", post=router)
    return call_anthropic("anthropic", B.SENTINEL, B.STATE, questions or B.QUESTIONS, model=model,
                          prompt=Prompt(), meter=meter, client=client)


def test_a_reply_with_a_done_line_and_suffixed_tool_names_answers_both_lanes():
    router = Router(B.answering())
    answers, usage, error = _call(router)
    assert error is None and sorted(answers) == ["dusk_call__v0", "dusk_call__v1"]
    assert answers["dusk_call__v0"]["choice"] == "enter_p3_now" and usage["lanes_answered"] == 2
    assert usage["input_tokens"] == 2 * (800 + 1500 + 35450)
    post = router.posts[0]
    assert post["url"] == ROUTER + "/v1/messages" and post["timeout"] == 15.0
    assert post["headers"]["x-api-key"] == B.SENTINEL and post["headers"]["anthropic-version"] == "2023-06-01"
    assert post["json"]["model"] == "claude-haiku-5-5" and "timeout" not in post["json"]


def test_a_router_prefixed_model_is_sent_as_it_is_and_priced_at_its_models_row():
    meter = Meter(1.0, ROUTED, clock=lambda: 1000.0)
    router = Router(B.answering())
    answers, usage, error = _call(router, model=ROUTED, meter=meter)
    assert error is None and answers and router.posts[0]["json"]["model"] == ROUTED
    one = cost(B.usage(), "claude-haiku-5-5")
    assert usage["cost_usd"] == pytest.approx(2 * one) and meter.spent == pytest.approx(2 * one)
    assert jc.price_key(ROUTED, routed=True) == "claude-haiku-5-5"
    assert jc.price_key(ROUTED) is None and jc.price_key("/claude-haiku-5-5", routed=True) is None
    assert jc.price_key("cc/claude-x-9", routed=True) is None


@pytest.mark.parametrize("name, offered, want", [
    ("answer_choice_ide", {"answer_choice", "answer_yes_no"}, "answer_choice"),
    ("answer_choice", {"answer_choice"}, "answer_choice"),
    ("answer_choicex", {"answer_choice"}, "answer_choicex"),
    ("write_report_ide", {"answer_choice"}, "write_report_ide"),
    ("answer_yes_no_x", {"answer", "answer_yes_no"}, "answer_yes_no"),
    (None, {"answer_choice"}, None),
])
def test_a_suffixed_name_is_only_ever_one_of_the_offered_tools(name, offered, want):
    assert tool_name(name, offered) == want


def test_a_tool_the_request_did_not_offer_is_still_no_answer():
    def other(request):
        return B.message(B.tool("delete_everything", snapshot_id=B.FakePrompt.snap, question_id="dusk_call__v0"))
    answers, _usage, error = _call(Router(other))
    assert answers is None and error == BAD_OUTPUT


def test_a_body_with_no_json_message_is_bad_output_and_charged_an_estimate():
    meter = Meter(1.0, clock=lambda: 1000.0)
    answers, _usage, error = _call(Router((200, "data: [DONE]\n")), meter=meter)
    assert answers is None and error == BAD_OUTPUT and meter.spent > 0 and meter.calls == 2


@pytest.mark.parametrize("status, said, state", [
    (401, "HTTP 401: authentication_error", "auth_failed"),
    (404, "HTTP 404: not_found_error", "model_invalid"),
    (429, "HTTP 429: rate_limit_error", "paused"),
    (503, "HTTP 503: api_error", None),
])
def test_an_http_error_from_the_router_is_classified_as_from_the_api(status, said, state):
    meter = Meter(1.0, clock=lambda: 1000.0)
    answers, _usage, error = _call(Router((status, "{\"error\": \"" + B.SENTINEL + "\"}")), meter=meter)
    assert answers is None and error == said and meter.state() == state and meter.spent == 0
    if status == 429:
        assert meter.paused_until == 1030.0  # the router's retry-after


def test_an_unreachable_router_is_a_connection_error_and_costs_nothing():
    meter = Meter(1.0, clock=lambda: 1000.0)
    answers, _usage, error = _call(Router(_refused()), meter=meter)
    assert answers is None and error == "APIConnectionError" and jc.retryable(error) and meter.spent == 0


def test_a_router_that_times_out_once_it_was_asked_is_charged_an_estimate():
    meter = Meter(1.0, clock=lambda: 1000.0)
    answers, _usage, error = _call(Router(type("ReadTimeout", (Exception,), {})(B.SENTINEL)), meter=meter)
    assert answers is None and error == "APITimeoutError" and meter.spent > 0


def test_the_router_client_needs_no_sdk_and_never_shows_the_key(monkeypatch):
    monkeypatch.setattr(jc, "anthropic", None)
    made = jc.make_client(B.SENTINEL, ROUTER)
    assert isinstance(made, RouterClient) and made.url == ROUTER + "/v1/messages"
    assert B.SENTINEL not in repr(made) and jc.make_client("", ROUTER) is None
    assert jc.make_client(B.SENTINEL) is None  # the Anthropic API itself still needs the SDK
    assert jc.show_url("https://user:" + B.SENTINEL + "@router.example.local:8443/api") == \
        "https://router.example.local:8443/api"


@pytest.mark.parametrize("url, ok", [
    (ROUTER, True), ("https://router.example.local/anthropic", True), ("ftp://router.example.local", False),
    ("router.example.local:20128", False), ("http://", False), ("http://router.example.local:port", False),
])
def test_only_an_http_or_https_address_is_a_router(url, ok):
    assert jc.base_url_ok(url) is ok


def test_the_option_is_stripped_and_blank_is_the_api():
    assert jc.anthropic_base_url({"anthropic_base_url": f"  {ROUTER}/ "}) == ROUTER
    assert jc.anthropic_base_url({"anthropic_base_url": None}) == "" == jc.anthropic_base_url({})


def _resolve(tmp_path, **options):
    return jev_bridge.resolve_provider({"brain_provider": "claude_haiku", "anthropic_api_key": "k", **options},
                                       str(tmp_path))


def test_which_brain_runs_with_a_router(tmp_path, monkeypatch):
    monkeypatch.setattr(jc, "anthropic", None)  # a router needs no SDK, so it also runs on 32-bit ARM
    got = _resolve(tmp_path, anthropic_base_url=ROUTER, anthropic_model=ROUTED)
    assert (got.provider, got.state, got.model) == ("claude_haiku", "acting", ROUTED)
    got = _resolve(tmp_path, anthropic_base_url="router.example.local:20128")
    assert (got.provider, got.state) == ("rules", "start_failed") and "anthropic_base_url" in got.words
    got = _resolve(tmp_path, anthropic_base_url=ROUTER, anthropic_model="cc/claude-x-9")
    assert (got.provider, got.state) == ("rules", "model_invalid") and "prefix" in got.words


def test_without_a_router_a_prefixed_model_is_still_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(B.FakeClient(B.judging())))
    got = _resolve(tmp_path, anthropic_model=ROUTED)
    assert (got.provider, got.state) == ("rules", "model_invalid")
    assert (_resolve(tmp_path, anthropic_base_url="").state, _resolve(tmp_path).state) == ("acting", "acting")


@pytest.fixture
def routed(monkeypatch):
    """Build controllers whose brain is Claude through a fake router, answered synchronously, with no SDK at all."""
    def make(*script, **options):
        router = Router(*(script or (B.judging(),)))
        monkeypatch.setattr(jc, "anthropic", None)
        monkeypatch.setattr(jc, "requests", SimpleNamespace(post=router))
        clock = Clock(NOW.timestamp())
        monkeypatch.setattr(jev_bridge, "Asker", functools.partial(jc.Asker, threaded=False, clock=clock))
        monkeypatch.setattr(jev_bridge, "Meter", functools.partial(jc.Meter, clock=clock))
        monkeypatch.setattr(jev_bridge, "Routes", functools.partial(jc.Routes, sleep=lambda s: None))
        opts = {"num_zones": 1, "enable_flag": KILL, "brain_provider": "claude_haiku",
                "anthropic_api_key": B.SENTINEL, "anthropic_base_url": ROUTER, "anthropic_model": ROUTED, **options}
        c, fake = _build(opts, states=_states())
        return c, fake, router
    return make


def test_the_controller_asks_through_the_router_and_acts(routed, capsys):
    c, fake, router = routed(B.judging({"ramp_state": "ec_is_feed_front"}))
    assert c.jev.status.provider == "claude_haiku" and c.jev.routes == ["Anthropic"]
    _zone(c)
    c.loop_once(NOW)
    assert router.posts and all(p["url"] == ROUTER + "/v1/messages" for p in router.posts)
    assert c.rooms[0].state[1]["phase"] == "P2"  # the ramp judge's admitted hand-over
    panel = fake.sets["sensor.crop_steering_jev"][1]
    assert (panel["provider"], panel["state"], panel["model"]) == ("claude_haiku", "acting", ROUTED)
    assert panel["spent_usd"] > 0
    out = capsys.readouterr().out
    assert f"through the router at {ROUTER}" in out and B.SENTINEL not in out + json.dumps(fake.sets, default=str)


def test_an_unreachable_router_leaves_the_engine_exactly_as_on_rules(routed, capsys):
    base, base_fake = _base()
    c, fake, router = routed(_refused())
    _zone(c)
    c.loop_once(NOW)
    c.loop_once(NOW + timedelta(minutes=20))
    assert router.posts and c.rooms[0].state[1]["phase"] == base.rooms[0].state[1]["phase"] == "P1"
    assert _switches(fake) == _switches(base_fake) and _writes(fake) == _writes(base_fake)
    seen = json.dumps(fake.sets, default=str) + capsys.readouterr().out
    data = os.path.dirname(os.environ["F2_STATE_PATH"])
    for name in ("jev_usage.json", "jev_journal.jsonl"):
        path = os.path.join(data, name)
        seen += open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    assert B.SENTINEL not in seen and c.jev.asker.meter.spent == 0


def _options(tmp_path, content, env=None, container=False):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(content))
    base = {"F2_RUNTIME": "container", "HA_URL": "http://ha:8123"} if container else {"F2_RUNTIME": "addon", "SUPERVISOR_TOKEN": "t"}
    return runtime_env.load_options({**base, "F2_OPTIONS_PATH": str(path), **(env or {})}, lambda line: None)


@pytest.mark.parametrize("container", [False, True])
def test_an_old_options_file_without_the_key_loads_unchanged_and_a_new_one_keeps_it(tmp_path, container):
    old = {"num_zones": 1, "brain_provider": "claude_haiku", "anthropic_model": "claude-haiku-5-5"}
    assert _options(tmp_path, old, container=container) == old
    assert jc.anthropic_base_url(old) == ""
    new = {**old, "anthropic_base_url": ROUTER, "anthropic_model": ROUTED}
    assert _options(tmp_path, new, container=container) == new


def test_a_container_sets_the_router_through_its_variable(tmp_path):
    got = _options(tmp_path, {}, {"F2_OPT_ANTHROPIC_BASE_URL": ROUTER}, container=True)
    assert got == {"anthropic_base_url": ROUTER}
