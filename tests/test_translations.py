"""Every message the setup flows can show exists, and says something true.

A missing translation is silent: Home Assistant shows the raw key (`not_env_config`) in the
dialog. A wrong one is worse. Both kinds shipped: two abort reasons had no message, and the
waste-valve tooltip promised the valve is "forced closed during a shot" when nothing at runtime
has ever operated it.

hassfest only runs in CI (it is a container action), so the rules a new field or message is most
likely to trip are checked here with hassfest's OWN patterns, where a failure takes seconds.
"""

import json
import re
from pathlib import Path

from .test_setup_flows import flow_module  # noqa: F401  (pytest fixture)

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "crop_steering"


def _strings():
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert (
        strings == english
    ), "strings.json and translations/en.json have drifted apart"
    return strings


def _flow_halves():
    source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    config_part, options_part = source.split("class OptionsFlowHandler")
    return {"config": config_part, "options": options_part}


def test_every_abort_reason_has_a_message_in_the_flow_that_raises_it():
    strings = _strings()
    for section, source in _flow_halves().items():
        reasons = set(re.findall(r'reason="([a-z_]+)"', source))
        assert reasons, f"the scan of the {section} flow found nothing: fix the test"
        missing = reasons - set(strings[section]["abort"])
        assert not missing, f"{section}.abort has no message for {sorted(missing)}"


def test_every_error_key_has_a_message_in_the_flow_that_raises_it():
    strings = _strings()
    for section, source in _flow_halves().items():
        keys = set(re.findall(r'"base": "([a-z_]+)"', source))
        keys |= set(re.findall(r'errors\[[^\]]+\] = "([a-z_]+)"', source))
        missing = keys - set(strings[section].get("error", {}))
        assert not missing, f"{section}.error has no message for {sorted(missing)}"


def test_every_configure_menu_entry_has_a_label():
    menu = re.search(r"menu_options=\[(.*?)\]", _flow_halves()["options"], re.S).group(
        1
    )
    entries = set(re.findall(r'"([a-z_]+)"', menu))
    assert len(entries) >= 4  # the scan still works
    assert entries == set(_strings()["options"]["step"]["init"]["menu_options"])


def test_every_field_on_the_mapping_forms_has_a_label_and_a_tooltip(flow_module):
    strings = _strings()
    fm = flow_module
    forms = {
        ("config", "zones"): fm._zone_schema(24),
        ("config", "hardware"): fm._hardware_schema(),
        ("options", "edit_zones_map"): {
            **fm._zone_schema(24),
            **fm._hardware_schema(),
        },
    }
    for (section, step), schema in forms.items():
        text = strings[section]["step"][step]
        fields = {
            getattr(marker, "schema", getattr(marker, "key", marker))
            for marker in schema
        }
        unlabelled = fields - set(text["data"])
        assert not unlabelled, f"{section}.{step}: no label for {sorted(unlabelled)}"
        untold = fields - set(text["data_description"])
        assert not untold, f"{section}.{step}: no tooltip for {sorted(untold)}"


def test_translations_follow_the_hassfest_rules_that_are_easy_to_break():
    """Patterns copied from home-assistant/core script/hassfest/translations.py.

    1. every translation key is a lowercase slug (a dropdown's option VALUES are translation
       keys too, so an option stored as "L/hr" fails the whole repository's validation);
    2. no placeholder inside single quotes: Home Assistant formats messages with ICU
       MessageFormat, where single quotes ESCAPE braces, so '{unit}' shows the literal {unit};
    3. a tooltip (data_description) may only exist for a field that has a label (data).
    """
    translation_key = re.compile(r"^(?!.+[_-]{2})(?![_-])[a-z0-9-_]+(?<![_-])$")
    placeholder_in_single_quotes = re.compile(r"'{\w+}'")
    strings = _strings()
    bad_keys, bad_quotes = [], []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                if not translation_key.match(key):
                    bad_keys.append(f"{path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, str) and placeholder_in_single_quotes.search(node):
            bad_quotes.append(path)

    walk(strings, "strings")
    assert bad_keys == []
    assert bad_quotes == []
    for flow in ("config", "options"):
        for step, body in strings[flow]["step"].items():
            orphans = set(body.get("data_description", {})) - set(body.get("data", {}))
            assert (
                not orphans
            ), f"{flow}.{step}: tooltip without a label {sorted(orphans)}"


# ------------------------------------------------------------------ tooltips that must be TRUE
RUNTIME = [
    *INTEGRATION.glob("*.py"),
    *(ROOT / "addons" / "f2_control" / "f2_control").glob("*.py"),
    *(ROOT / "crop-steering-engine" / "src").rglob("*.py"),
]
# Modules that collect, validate or parse the answer. Using it at runtime is something else.
SETUP_ONLY = {"config_flow.py", "setup_api.py", "env_parser.py", "zone_config.py"}


def _runtime_consumers(key):
    return sorted(
        path.name
        for path in RUNTIME
        if path.name not in SETUP_ONLY and key in path.read_text(encoding="utf-8")
    )


def test_a_field_nothing_reads_does_not_promise_that_something_will():
    """If one of these gains a runtime consumer, this test fails - and that is the prompt to put
    the behaviour back into its tooltip. Until then the tooltip must not invent one: a grower
    who reads 'forced closed during a shot' will plumb a recirculating system around it.
    """
    promised = {
        "waste_switch": ("forced closed", "closed during a shot"),
        "light_entity": ("knows day", "day vs night"),
        "notification_service": ("where alerts go",),
        "humidity_sensor": ("analytics",),
        "vpd_sensor": (),
    }
    strings = _strings()
    for key, claims in promised.items():
        assert _runtime_consumers(key) == [], (
            f"{key} is now read at runtime: say what it does in its tooltip, "
            "then move it out of this test"
        )
        for flow, step in (("config", "hardware"), ("options", "edit_zones_map")):
            tooltip = strings[flow]["step"][step]["data_description"][key].lower()
            for claim in claims:
                assert (
                    claim not in tooltip
                ), f"{flow}.{step}.{key} still claims '{claim}'"
    waste = strings["config"]["step"]["hardware"]["data_description"]["waste_switch"]
    assert "does NOT operate" in waste


def test_the_pump_tooltip_says_what_leaving_it_empty_means():
    """An empty pump is accepted since 2.18.0 and means the controller never runs one. The person
    choosing that has to be told, in the place they choose it."""
    for flow, step in (("config", "hardware"), ("options", "edit_zones_map")):
        tooltip = _strings()[flow]["step"][step]["data_description"]["pump_switch"]
        assert "NEVER run a pump" in tooltip and "counts the shot" in tooltip
