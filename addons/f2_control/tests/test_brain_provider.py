"""Which brain runs (jev_bridge.resolve_provider): one case per row of haiku-brain-design 4.3, an empty key included,
and the "Jev has run" evidence in its order (a usage file that names its brain, any file only Jev writes, a TypeSafe
key). The same evidence decides whether build() starts the legacy route."""
import json

import brain_kit as B
import jev_bridge
import pytest
from jev import client as jc

CF = ("acct", "tok", "")
NONE = ("", "", "")


@pytest.fixture(autouse=True)
def _sdk(monkeypatch):
    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(B.FakeClient(B.judging())))


def _resolve(tmp_path, options, cf=NONE):
    return jev_bridge.resolve_provider(options, cf, str(tmp_path))


@pytest.mark.parametrize("options, cf, provider, state", [
    ({}, NONE, "rules", "rules"),
    ({"brain_provider": "auto"}, NONE, "rules", "rules"),
    ({"brain_provider": "claude_haiku", "anthropic_api_key": "k"}, NONE, "claude_haiku", "acting"),
    ({"brain_provider": "claude_haiku", "anthropic_api_key": "k", "brain_dry_run": True}, NONE, "claude_haiku",
     "dry_run"),
    ({"brain_provider": "claude_haiku", "anthropic_api_key": ""}, NONE, "rules", "rules_no_key"),
    ({"brain_provider": "claude_haiku", "anthropic_api_key": "   "}, NONE, "rules", "rules_no_key"),
    ({"brain_provider": "claude_haiku", "anthropic_api_key": "k", "typesafe_api_key": "t"}, CF, "claude_haiku",
     "acting"),
    ({"brain_provider": "rules", "typesafe_api_key": "t"}, CF, "rules", "rules"),
    ({"brain_provider": "jev_legacy"}, CF, "jev_legacy", "legacy"),
    ({"brain_provider": "jev_legacy"}, NONE, "rules", "rules_no_key"),
    ({"typesafe_api_key": "t"}, NONE, "jev_legacy", "legacy"),
    ({"jev_enabled": False, "typesafe_api_key": "t"}, CF, "rules", "brain_off"),
    ({"jev_enabled": False, "brain_provider": "claude_haiku", "anthropic_api_key": "k"}, NONE, "claude_haiku",
     "acting"),
])
def test_one_case_per_row(tmp_path, options, cf, provider, state):
    got = _resolve(tmp_path, options, cf)
    assert (got.provider, got.state) == (provider, state) and got.words
    assert got.deprecated_route == (provider == "jev_legacy")


@pytest.mark.parametrize("model", ["claude-fable-5", "claude-opus-4-1", "claude-x-9", "claude-haiku-5", ""])
def test_a_model_this_release_cannot_price_runs_rules(tmp_path, model):
    got = _resolve(tmp_path, {"brain_provider": "claude_haiku", "anthropic_api_key": "k", "anthropic_model": model})
    assert (got.provider, got.state) == (("rules", "model_invalid") if model else ("claude_haiku", "acting"))


def test_no_sdk_runs_rules_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(jc, "anthropic", None)
    got = _resolve(tmp_path, {"brain_provider": "claude_haiku", "anthropic_api_key": "k"})
    assert (got.provider, got.state) == ("rules", "sdk_missing") and "32-bit ARM" in got.words


def test_an_upstream_install_after_the_supervisor_merged_the_defaults_runs_rules_with_the_notice(tmp_path):
    got = _resolve(tmp_path, {"jev_enabled": True, "brain_provider": "auto", "cf_account_id": "acct"}, CF)
    assert (got.provider, got.notice) == ("rules", "cloudflare_route_retired")


@pytest.mark.parametrize("name", ["jev_usage.json", "jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json"])
@pytest.mark.parametrize("content", [b"{}", b"", b"\xff not json"], ids=["file", "empty", "unreadable"])
def test_any_one_jev_file_is_lineage(tmp_path, name, content):
    (tmp_path / name).write_bytes(content)
    assert _resolve(tmp_path, {}, CF).provider == "jev_legacy"


def test_a_usage_file_naming_its_brain_wins_and_the_marker_is_not_sticky(tmp_path):
    for name in ("jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json"):
        (tmp_path / name).write_text("")
    (tmp_path / "jev_usage.json").write_text(json.dumps({"provider": "claude_haiku"}))
    assert _resolve(tmp_path, {}, CF).provider == "rules"
    (tmp_path / "jev_usage.json").write_text(json.dumps({"provider": "jev_legacy"}))
    assert _resolve(tmp_path, {}, CF).provider == "jev_legacy"


def test_build_names_its_brain_in_the_usage_file_before_any_ask(tmp_path, monkeypatch):
    for options, provider in (({"brain_provider": "claude_haiku", "anthropic_api_key": "k"}, "claude_haiku"),
                              ({"typesafe_api_key": "t"}, "jev_legacy")):
        (tmp_path / provider).mkdir()
        brain = jev_bridge.build(options, NONE, str(tmp_path / provider / "state.json"), lambda *a: None)
        assert brain is not None and brain.asker.stats["calls"] == 0
        assert json.loads((tmp_path / provider / "jev_usage.json").read_text())["provider"] == provider
    assert jev_bridge.build({"brain_provider": "rules"}, CF, str(tmp_path / "other" / "s.json"),
                            lambda *a: None) is None


def test_a_haiku_brain_is_built_with_its_hook_meter_prompt_and_a_noting_triage(tmp_path):
    said = []
    brain = jev_bridge.build({"brain_provider": "claude_haiku", "anthropic_api_key": B.SENTINEL,
                              "anthropic_daily_budget_usd": 2.5}, NONE, str(tmp_path / "s.json"), said.append)
    assert brain.enrich is not None and brain.asker.meter.budget == 2.5 and brain.prompt is not None
    assert brain.triage.may_quiet is False and brain.arc_rows and brain.arc_note is None
    assert any(line.startswith("brain: claude_haiku, model claude-haiku-5-5, budget US$2.50") for line in said)
    assert any(line.startswith("brain: prompt A=") for line in said) and B.SENTINEL not in " ".join(said)
    (tmp_path / "legacy").mkdir()
    legacy = jev_bridge.build({"typesafe_api_key": "t"}, NONE, str(tmp_path / "legacy" / "s.json"), said.append)
    assert legacy.enrich is None and legacy.asker.meter is None and legacy.triage.may_quiet is True


def test_an_arc_this_release_refuses_runs_no_arc_and_says_why(tmp_path):
    brain = jev_bridge.build({"brain_provider": "claude_haiku", "anthropic_api_key": "k", "stage_arc":
                              "rockwool_default"}, NONE, str(tmp_path / "s.json"), lambda *a: None)
    assert brain.arc_rows == () and "rockwool_default is not complete" in brain.arc_note
