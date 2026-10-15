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
