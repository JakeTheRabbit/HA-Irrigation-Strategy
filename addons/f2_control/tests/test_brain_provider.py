"""Which brain runs (jev_bridge.resolve_provider), one case per row, an empty key included; how an install that
chose the removed first AI route moves (to Claude with a key, else rules, said once in the log and by a CS-712
card); and which judges run: all by default, an old jev_judges list read as all, an ai_judges list as written."""
import json
import pathlib

import brain_kit as B
import jev_bridge
import pytest
from jev import client as jc

ADDON = pathlib.Path(__file__).resolve().parents[1]
KEY = {"anthropic_api_key": "k"}
CF = {"cf_account_id": "cf-acct-secret", "cf_api_token": "cf-token-secret"}
TYPESAFE = {"typesafe_api_key": "t"}
# The list a box saved for the first AI route and copied when it moved to Claude: every judge then but ramp.
LIVE = "dawn, salt, dusk, probe, shot, night, zones, stage, setpoints, channel, balance, feed, report, why, plan"


@pytest.fixture(autouse=True)
def _sdk(monkeypatch):
    monkeypatch.setattr(jc, "anthropic", B.FakeSDK(B.FakeClient(B.judging())))
    monkeypatch.setattr(jev_bridge, "_upgrade_said", False)


def _resolve(tmp_path, options):
    return jev_bridge.resolve_provider(options, str(tmp_path))


def _ran(tmp_path):
    (tmp_path / "jev_ledger.jsonl").write_text("")  # a file only the brain writes: it ran here


@pytest.mark.parametrize("options, provider, state", [
    ({}, "rules", "rules"),
    ({"brain_provider": "auto"}, "rules", "rules"),
    ({"brain_provider": "auto", **KEY}, "rules", "rules"),  # auto never starts Claude on a fresh install
    ({"brain_provider": "claude_haiku", **KEY}, "claude_haiku", "acting"),
    ({"brain_provider": "claude_haiku", **KEY, "brain_dry_run": True}, "claude_haiku", "dry_run"),
    ({"brain_provider": "claude_haiku", "anthropic_api_key": ""}, "rules", "rules_no_key"),
    ({"brain_provider": "claude_haiku", "anthropic_api_key": "   "}, "rules", "rules_no_key"),
    ({"brain_provider": "claude_haiku", **KEY, **TYPESAFE, **CF}, "claude_haiku", "acting"),
    ({"brain_provider": "rules", **TYPESAFE, **KEY}, "rules", "rules"),
    ({"jev_enabled": False, "brain_provider": "claude_haiku", **KEY}, "claude_haiku", "acting"),
    ({"brain_provider": "something_new"}, "rules", "rules"),
])
def test_one_case_per_row(tmp_path, options, provider, state):
    got = _resolve(tmp_path, options)
    assert (got.provider, got.state) == (provider, state) and got.words
    assert got.deprecated_route is False


@pytest.mark.parametrize("options, provider, state", [
    ({"brain_provider": "jev_legacy", **CF, **KEY}, "claude_haiku", "acting"),
    ({"brain_provider": "jev_legacy", **CF}, "rules", "rules_no_key"),
    ({"brain_provider": "jev_legacy"}, "rules", "rules_no_key"),
    ({**TYPESAFE, **KEY}, "claude_haiku", "acting"),  # auto, and a key only the first route had
    ({**TYPESAFE}, "rules", "rules_no_key"),
    ({"jev_enabled": False, **TYPESAFE, **KEY}, "rules", "brain_off"),
    ({"jev_enabled": False, "brain_provider": "jev_legacy", **KEY}, "rules", "brain_off"),
    ({**TYPESAFE, **KEY, "brain_dry_run": True}, "claude_haiku", "dry_run"),
])
def test_an_install_that_chose_the_removed_route_moves_to_claude_with_a_key_else_rules(tmp_path, options, provider,
                                                                                      state):
    got = _resolve(tmp_path, options)
    assert (got.provider, got.state, got.notice) == (provider, state, "legacy_route_removed")
    assert "Jev" not in got.words and got.deprecated_route is False


def test_cloudflare_settings_where_the_brain_ran_move_it_and_where_it_never_ran_only_raise_the_notice(tmp_path):
    fresh = _resolve(tmp_path, {"jev_enabled": True, "brain_provider": "auto", **CF, **KEY})
    assert (fresh.provider, fresh.notice) == ("rules", "legacy_route_removed")
    _ran(tmp_path)
    ran = _resolve(tmp_path, {"jev_enabled": True, "brain_provider": "auto", **CF, **KEY})
    assert (ran.provider, ran.notice) == ("claude_haiku", "legacy_route_removed")


@pytest.mark.parametrize("name", ["jev_usage.json", "jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json"])
@pytest.mark.parametrize("content", [b"{}", b"", b"\xff not json"], ids=["file", "empty", "unreadable"])
def test_any_one_brain_file_is_lineage(tmp_path, name, content):
    (tmp_path / name).write_bytes(content)
    assert _resolve(tmp_path, {**CF, **KEY}).provider == "claude_haiku"


def test_a_usage_file_naming_its_brain_wins(tmp_path):
    for name in ("jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json"):
        (tmp_path / name).write_text("")
    (tmp_path / "jev_usage.json").write_text(json.dumps({"provider": "claude_haiku"}))
    assert _resolve(tmp_path, {**CF, **KEY}).provider == "rules"  # Claude wrote it: the first route never ran here
    (tmp_path / "jev_usage.json").write_text(json.dumps({"provider": "jev_legacy"}))
    assert _resolve(tmp_path, {**CF, **KEY}).provider == "claude_haiku"


def test_the_move_is_said_once_at_start_and_never_names_a_secret(tmp_path):
    said = []
    _ran(tmp_path)
    brain = jev_bridge.build({**CF, **KEY, "cf_gateway_id": "cf-gw-secret"}, str(tmp_path / "state.json"), said.append)
    assert brain is not None and brain.routes == ["Anthropic"]
    notes = [s for s in said if "first AI route" in s]
    assert len(notes) == 1 and "uses claude-haiku-5-5 with your Anthropic key" in notes[0]
    assert not any(secret in " ".join(said) for secret in ("cf-token-secret", "cf-acct-secret", "cf-gw-secret")) and "Jev" not in " ".join(said)
    said.clear()
    assert jev_bridge.build({**CF}, str(tmp_path / "state.json"), said.append) is None
    assert [s for s in said if "first AI route" in s and "uses its rules" in s]


def test_build_names_its_brain_in_the_usage_file_before_any_ask(tmp_path):
    brain = jev_bridge.build({"brain_provider": "claude_haiku", **KEY}, str(tmp_path / "state.json"), lambda *a: None)
    assert brain is not None and brain.asker.stats["calls"] == 0
    assert json.loads((tmp_path / "jev_usage.json").read_text())["provider"] == "claude_haiku"
    assert jev_bridge.build({"brain_provider": "rules"}, str(tmp_path / "other" / "s.json"), lambda *a: None) is None


def test_a_haiku_brain_is_built_with_its_hook_meter_and_prompt(tmp_path):
    said = []
    brain = jev_bridge.build({"brain_provider": "claude_haiku", "anthropic_api_key": B.SENTINEL,
                              "anthropic_daily_budget_usd": 2.5}, str(tmp_path / "s.json"), said.append)
    assert brain.enrich is not None and brain.asker.meter.budget == 2.5 and brain.prompt is not None
    assert brain.arc_rows and brain.arc_note is None
    assert any(line.startswith("brain: claude_haiku, model claude-haiku-5-5, budget US$2.50") for line in said)
    assert any(line.startswith("brain: prompt A=") for line in said) and B.SENTINEL not in " ".join(said)


def test_an_arc_this_release_refuses_runs_no_arc_and_says_why(tmp_path):
    brain = jev_bridge.build({"brain_provider": "claude_haiku", **KEY, "stage_arc": "rockwool_default"},
                             str(tmp_path / "s.json"), lambda *a: None)
    assert brain.arc_rows == () and "rockwool_default is not complete" in brain.arc_note


# ------------------------------------------------------------------ which judges
def _judges(tmp_path, said=None, **options):
    brain = jev_bridge.build({"brain_provider": "claude_haiku", **KEY, **options}, str(tmp_path / "s.json"),
                             (said if said is not None else []).append)
    tasks = {name for name, on in (("feed", brain.feed), ("report", brain.report), ("why", brain.why),
                                   ("plan", brain.plan)) if on}
    return {j.name for j in brain.judges} | tasks


def test_by_default_claude_asks_every_judge_and_task_ramp_included(tmp_path):
    assert _judges(tmp_path) == set(jev_bridge.ALL) and "ramp" in jev_bridge.ALL
    assert {j.name for j in jev_bridge.judges()} | {"feed", "report", "why", "plan"} == set(jev_bridge.ALL)


@pytest.mark.parametrize("old", ["all", "", None, LIVE, "dawn,ramp,salt,dusk,probe,shot,night,zones,alerts",
                                 "ramp, salt", "setpoints"])
def test_an_old_jev_judges_value_is_read_as_all(tmp_path, old):
    assert _judges(tmp_path, jev_judges=old) == set(jev_bridge.ALL)


def test_the_live_list_without_ramp_says_once_which_judges_it_adds(tmp_path):
    said = []
    for n in range(3):
        (tmp_path / str(n)).mkdir()
        jev_bridge.build({"brain_provider": "claude_haiku", **KEY, "jev_judges": LIVE, "ai_judges": "all"},
                         str(tmp_path / str(n) / "s.json"), said.append)
    notes = [s for s in said if "old jev_judges list" in s]
    assert len(notes) == 1 and notes[0].endswith("also asks ramp, targets, shotsize. To ask fewer, list them in "
                                                 "ai_judges")
    assert any(s.startswith("brain: claude_haiku") and "ramp" in s for s in said)


def test_an_ai_judges_list_is_honoured_as_written_with_the_two_powers(tmp_path):
    got = _judges(tmp_path, ai_judges="ramp, salt", jev_judges=LIVE)
    assert got == {"ramp", "salt", "targets", "shotsize"}


def test_an_old_list_naming_a_judge_no_release_had_is_honoured_as_a_list(tmp_path):
    got = _judges(tmp_path, jev_judges="ramp,steer")
    assert got == {"ramp", "targets", "shotsize"}


def test_each_tuning_option_reads_its_new_name_then_its_old_one(tmp_path):
    old = {"jev_daily_calls": 2000, "jev_budget_warn_pct": 60, "jev_reask_max": 1, "jev_unsure_below": 0.6,
           "jev_strict_after": 4, "jev_strict_prob": 0.9, "jev_flower_days": 63}
    defaults = {"ai_daily_calls": 5000, "ai_budget_warn_pct": 80, "ai_reask_max": 2, "ai_unsure_below": 0.7,
                "ai_strict_after": 3, "ai_strict_prob": 0.8, "ai_flower_days": 56, "ai_flower_start": ""}

    def brain(**options):
        return jev_bridge.build({"brain_provider": "claude_haiku", **KEY, **options}, str(tmp_path / "s.json"),
                                lambda *a: None)

    # The Supervisor fills in every new key with its default on update: the operator's old values still count.
    b = brain(**old, **defaults)
    assert (b.asker.daily_budget, b.asker.warn_pct, b.reask_max, b.unsure_below, b.strict_after, b.strict_prob,
            b.flower_days) == (2000, 60.0, 1, 0.6, 4, 0.9, 63)
    b = brain(**old, **{**defaults, "ai_daily_calls": 3000, "ai_reask_max": 0})
    assert (b.asker.daily_budget, b.reask_max) == (3000, 0)  # a new value set on purpose wins
    b = brain()
    assert (b.asker.daily_budget, b.asker.warn_pct, b.reask_max, b.flower_days) == (5000, 80.0, 2, 56)


# ------------------------------------------------------------------ no first-route code is left
def test_no_cloudflare_or_typesafe_code_path_remains():
    assert not hasattr(jev_bridge, "routes") and not hasattr(jc, "call") and not hasattr(jc, "call_typesafe")
    for path in (ADDON / "f2_control").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for word in ("api.cloudflare.com", "api.typesafe.ai", "cf-aig-gateway", "typesafe/jev", "/ai/run"):
            assert word not in text, (path.name, word)
