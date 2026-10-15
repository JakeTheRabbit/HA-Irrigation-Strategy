"""Every saved add-on option of an older install still fits this add-on's schema.

The Supervisor checks a box's saved /data/options.json against config.yaml `schema:` before the app
starts; a key the schema no longer knows is dropped, a value of the wrong type stops the start. So
every key in every seeded options snapshot (tests_ha/fixtures/options_*.json, each install lineage)
must still have a schema entry, and every default in `options:` must have one too.
"""
import json
import pathlib

import yaml

ADDON = pathlib.Path(__file__).parents[1]
FIXTURES = ADDON.parents[1] / "tests_ha" / "fixtures"


def _config():
    return yaml.safe_load((ADDON / "config.yaml").read_text())


def test_every_default_option_has_a_schema_entry():
    config = _config()
    assert set(config["options"]) <= set(config["schema"])


def test_every_saved_option_of_an_older_install_is_in_the_schema():
    schema = set(_config()["schema"])
    snapshots = sorted(FIXTURES.glob("options_*.json"))
    assert snapshots
    for path in snapshots:
        saved = json.loads(path.read_text(encoding="utf-8"))["options"]
        assert set(saved) <= schema, f"{path.name}: {sorted(set(saved) - schema)}"


def test_the_runtime_marker_is_environment_not_an_option():
    config = _config()
    assert "F2_RUNTIME" not in config["options"] and "F2_RUNTIME" not in config["schema"]


def test_the_anthropic_key_is_an_empty_password_by_default():
    """Shown on a fresh install's form without "unused optional options", masked, and empty means no key."""
    config = _config()
    assert config["options"]["anthropic_api_key"] == ""
    assert config["schema"]["anthropic_api_key"] == "password?"


def test_the_brain_options_and_their_defaults():
    config = _config()
    assert config["options"]["brain_provider"] == "auto"
    assert config["schema"]["brain_provider"] == "list(auto|rules|claude_haiku|jev_legacy)?"
    assert config["options"]["anthropic_daily_budget_usd"] == 1.0
    assert config["options"]["brain_dry_run"] is False
    assert config["options"]["stage_arc"] == "slab_default"


DEPRECATED = {"cf_account_id", "cf_api_token", "cf_gateway_id", "typesafe_api_key", "jev_enabled", "jev_retries"}
REUSED = {"jev_judges", "jev_reask_max", "jev_unsure_below", "jev_strict_after", "jev_strict_prob",
          "jev_flower_start", "jev_flower_days", "jev_daily_calls", "jev_budget_warn_pct"}


def test_the_deprecated_jev_route_keys_are_off_the_form_but_still_allowed():
    """A new install's form leaves the six out; the schema keeps them, so a saved value survives the update.
    The nine the brain reuses stay on the form."""
    config = _config()
    legacy = {k for k in config["schema"] if k.startswith(("cf_", "jev_")) or k == "typesafe_api_key"}
    assert legacy == DEPRECATED | REUSED
    assert DEPRECATED.isdisjoint(config["options"]) and REUSED <= set(config["options"])
    assert all(config["schema"][k].endswith("?") for k in DEPRECATED)
