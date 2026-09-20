"""First-run setup: problems appear beside the field that caused them, and a tent can be set up.

Reported from a first install (a single-zone tent, one switch for all fertigation): three screens
of answers, then "Setup could not be saved: switch.gt1_irrigation_switch must read OFF before
changing setup" and a Close button. Every rule ran once, after the last screen, and answered
with an abort that threw the answers away. The same happened for a probe in the wrong unit.
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.crop_steering import room
from custom_components.crop_steering import setup_api as api

from .test_setup_flows import flow_module  # noqa: F401  (pytest fixture)

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "crop_steering"
TENT = "switch.gt1_irrigation_switch"


def _hass(states, entries=()):
    table = {
        eid: SimpleNamespace(entity_id=eid, state=state, attributes=attrs)
        for eid, (state, attrs) in states.items()
    }
    return SimpleNamespace(
        states=SimpleNamespace(get=table.get, async_all=lambda: list(table.values())),
        config_entries=SimpleNamespace(async_entries=lambda domain: list(entries)),
        config=SimpleNamespace(units=SimpleNamespace(volume_unit="L")),
        data={},
        _table=table,
    )


def _tent_states(switch="off", ec_unit="µS/cm"):
    return {
        TENT: (switch, {}),
        "sensor.gt1_vwc": ("48", {"unit_of_measurement": "%"}),
        "sensor.gt1_ec": ("2300", {"unit_of_measurement": ec_unit} if ec_unit else {}),
    }


def _tent_payload(**extra):
    return {
        "room_name": "Grow tent 1",
        "zones": [
            {
                "id": 1,
                "valve": TENT,
                "vwc_sensors": ["sensor.gt1_vwc"],
                "ec_sensors": ["sensor.gt1_ec"],
                "plant_count": 4,
            }
        ],
        "hardware": {},
        **extra,
    }


# ------------------------------------------------------------------ the reported failure
def test_a_switch_that_is_on_is_reported_as_on():
    hass = _hass(_tent_states(switch="on"))
    data = api.prepare_setup(hass, _tent_payload(plumbing="valves_only"))
    assert api.safety_report(hass, proposed=data) == [
        {"entity_id": TENT, "reason": "on", "detail": "is ON"}
    ]
    assert api.safety_blockers(hass, proposed=data) == [
        f"{TENT} must read OFF before changing setup"
    ]  # the sentence callers already know


@pytest.mark.parametrize(
    "state, says",
    [
        ("unavailable", "offline"),
        ("unknown", "has not reported"),
        ("standby", "not reporting on/off"),
    ],
)
def test_a_switch_that_is_not_off_for_another_reason_says_which(state, says):
    """'Must read OFF' alone sent people hunting for a running pump when the plug was offline."""
    hass = _hass(_tent_states(switch=state))
    data = api.prepare_setup(hass, _tent_payload(plumbing="valves_only"))
    (blocker,) = api.safety_blockers(hass, proposed=data)
    assert says in blocker and "OFF" in blocker and TENT in blocker


def test_the_wizard_shows_the_on_switch_beside_its_picker_and_keeps_every_answer(
    flow_module,
):
    hass = _hass(_tent_states(switch="on"))
    flow = flow_module.ConfigFlow()
    flow.hass = hass
    flow._data.update(name="Grow tent 1", room_name="Grow tent 1", room_prefix="")
    asyncio.run(
        flow.async_step_manual_zones(
            {
                "num_zones": 1,
                "plumbing": "valves_only",
                "volume_unit": "us_gallons",
                "flow_unit": "gph",
            }
        )
    )
    answers = {
        "ec_unit": "auto",
        "zone_1_name": "Tent",
        "zone_1_active": True,
        "zone_1_switch": TENT,
        "zone_1_vwc": ["sensor.gt1_vwc"],
        "zone_1_ec": ["sensor.gt1_ec"],
        "zone_1_plant_count": 4,
    }

    result = asyncio.run(flow.async_step_zones(answers))

    assert result["type"] == "form" and result["step_id"] == "zones"  # not an abort
    assert result["errors"] == {"zone_1_switch": "must_read_off"}
    assert TENT in result["description_placeholders"]["blockers"]
    assert flow._data["zones"]["1"]["vwc_sensors"] == [
        "sensor.gt1_vwc"
    ]  # nothing typed is lost

    hass._table[TENT].state = "off"  # the grower switches it off and presses Next again
    result = asyncio.run(flow.async_step_zones(answers))
    assert result["step_id"] == "hardware" and not result.get("errors")


# ------------------------------------------------------------------ a tent, start to finish
def test_a_single_switch_tent_completes_the_wizard_in_its_own_units(flow_module):
    hass = _hass(_tent_states())
    flow = flow_module.ConfigFlow()
    flow.hass = hass
    flow._data.update(name="Grow tent 1", room_name="Grow tent 1", room_prefix="")
    run = asyncio.run
    run(
        flow.async_step_manual_zones(
            {
                "num_zones": 1,
                "plumbing": "valves_only",
                "volume_unit": "us_gallons",
                "flow_unit": "gph",
            }
        )
    )
    step = run(
        flow.async_step_zones(
            {
                "ec_unit": "auto",
                "zone_1_switch": TENT,
                "zone_1_vwc": ["sensor.gt1_vwc"],
                "zone_1_ec": ["sensor.gt1_ec"],
                "zone_1_plant_count": 4,
            }
        )
    )
    # A tent is never asked for a pump or a main-line valve it does not have.
    shown = {flow_module._field_name(m) for m in step["data_schema"]}
    assert shown == {"lights_on_hour", "lights_off_hour"}
    run(flow.async_step_hardware({"lights_on_hour": 6, "lights_off_hour": 0}))
    step = run(
        flow.async_step_substrate(
            {
                "substrate_preset": "pot_3gal",
                "substrate_volume": 1,
                "dripper_flow_rate": 1,
                "drippers_per_plant": 2,
                "field_capacity": 70,
                "max_ec": 9,
                "have_catch_test": False,
            }
        )
    )
    assert step["step_id"] == "extras" and step["last_step"] is True
    result = run(flow.async_step_extras({}))

    assert result["type"] == "create_entry"
    data = result["data"]
    assert data["plumbing"] == "valves_only" and data["setup_revision"] == 1
    assert (
        data["hardware"]["pump_switch"] == ""
        and data["hardware"]["main_line_switch"] == ""
    )
    assert (
        data["parameters"]["substrate_volume"] == 11.4
    )  # the 3 gal preset, not the typed 1
    assert data["parameters"]["dripper_flow_rate"] == pytest.approx(
        3.785, abs=1e-3
    )  # 1 GPH
    assert data["parameters"]["lights_on_hour"] == 6
    descriptor = room.build_engine_config(
        "", "default", 1, data["zones"], data["hardware"], data
    )
    assert descriptor["plumbing"] == "valves_only" and descriptor["valves"] == {1: TENT}


def test_a_catch_test_in_the_wizard_replaces_the_packet_rating(flow_module):
    flow = flow_module.ConfigFlow()
    flow.hass = _hass(_tent_states())
    flow._data.update(parameters={"dripper_flow_rate": 2.0}, flow_unit="lph")
    bad = asyncio.run(
        flow.async_step_catch_test(
            {"catch_seconds": 10, "catch_ml": 5000, "catch_drippers": 1}
        )
    )
    assert bad["step_id"] == "catch_test" and bad["errors"] == {
        "base": "catch_test_out_of_range"
    }
    assert (
        flow._data["parameters"]["dripper_flow_rate"] == 2.0
    )  # a nonsense result is not saved
    done = asyncio.run(
        flow.async_step_catch_test(
            {"catch_seconds": 60, "catch_ml": 200, "catch_drippers": 4}
        )
    )
    assert (
        done["step_id"] == "extras"
        and "3 L/hr" in done["description_placeholders"]["measured"]
    )
    assert flow._data["parameters"]["dripper_flow_rate"] == 3.0


def test_a_size_outside_the_limits_is_explained_in_the_growers_own_unit(flow_module):
    flow = flow_module.ConfigFlow()
    flow.hass = _hass(_tent_states())
    flow._data.update(volume_unit="us_gallons", flow_unit="gph")
    step = asyncio.run(
        flow.async_step_substrate(
            {
                "substrate_preset": "custom",
                "substrate_volume": 80,
                "dripper_flow_rate": 1,
                "drippers_per_plant": 1,
                "field_capacity": 70,
                "max_ec": 9,
                "have_catch_test": False,
            }
        )
    )
    assert step["errors"] == {"substrate_volume": "sizing_range"}  # 80 gal = 303 L
    assert step["description_placeholders"]["high"].endswith(" gal")


# ------------------------------------------------------------------ plumbing layouts
def test_both_layers_agree_on_what_each_layout_needs():
    addon = str(ROOT / "addons" / "f2_control" / "f2_control")
    sys.path.insert(0, addon)
    sys.modules.setdefault(
        "requests", SimpleNamespace(Session=lambda: SimpleNamespace(headers={}))
    )
    try:
        import controller
    finally:
        sys.path.remove(addon)
    assert api.PLUMBING_LAYOUTS == controller.PLUMBING_LAYOUTS


def test_a_layout_is_a_promise_checked_both_ways():
    states = {**_tent_states(), "switch.pump": ("off", {})}
    with pytest.raises(api.SetupError) as needs:
        api.prepare_setup(_hass(states), _tent_payload(plumbing="pump_valves"))
    assert (needs.value.key, needs.value.path) == (
        "plumbing_needs_pump",
        ("hardware", "pump_switch"),
    )
    with pytest.raises(api.SetupError) as unused:
        api.prepare_setup(
            _hass(states),
            _tent_payload(
                plumbing="valves_only", hardware={"pump_switch": "switch.pump"}
            ),
        )
    assert unused.value.key == "plumbing_unused_pump"
    with pytest.raises(api.SetupError) as unknown:
        api.prepare_setup(_hass(states), _tent_payload(plumbing="gravity_fed"))
    assert unknown.value.path == ("plumbing",)


def test_one_switch_cannot_be_both_the_zone_and_the_pump_and_the_error_says_what_to_do_instead():
    with pytest.raises(api.SetupError) as error:
        api.prepare_setup(
            _hass(_tent_states()), _tent_payload(hardware={"pump_switch": TENT})
        )
    assert error.value.key == "valve_is_shared" and error.value.path == (
        "hardware",
        "pump_switch",
    )
    assert (
        str(error.value) == "A valve cannot also be pump, mainline or waste"
    )  # unchanged sentence


# ------------------------------------------------------------------ EC in the probe's own unit
def test_a_microsiemens_substrate_probe_is_accepted_not_rejected():
    data = api.prepare_setup(_hass(_tent_states(ec_unit="µS/cm")), _tent_payload())
    assert data["zones"]["1"]["ec_sensors"] == ["sensor.gt1_ec"]


@pytest.mark.parametrize(
    "unit, problem",
    [("ppm", "ec_unit_ppm_scale"), (None, "ec_unit_missing"), ("%", "ec_unit_unknown")],
)
def test_an_ec_probe_that_cannot_be_interpreted_is_flagged_on_its_own_field(
    unit, problem
):
    with pytest.raises(api.SetupError) as error:
        api.prepare_setup(_hass(_tent_states(ec_unit=unit)), _tent_payload())
    assert error.value.key == problem and error.value.path == ("zone", 1, "ec_sensors")
    assert error.value.placeholders["entity"] == "sensor.gt1_ec"


def test_choosing_the_scale_is_what_lets_a_ppm_probe_through():
    data = api.prepare_setup(
        _hass(_tent_states(ec_unit="ppm")), _tent_payload(ec_unit="ppm_700")
    )
    assert data["ec_unit"] == "ppm_700"


def test_the_feed_probes_factor_is_saved_and_published_for_the_controller():
    states = {
        **_tent_states(),
        "sensor.feed": ("2300", {"unit_of_measurement": "uS/cm"}),
    }
    data = api.prepare_setup(
        _hass(states),
        _tent_payload(
            plumbing="valves_only", hardware={"feed_ec_sensor": "sensor.feed"}
        ),
    )
    assert data["feed_ec_factor"] == pytest.approx(0.001)
    descriptor = room.build_engine_config(
        "", "default", 1, data["zones"], data["hardware"], data
    )
    assert descriptor["feed_ec_factor"] == pytest.approx(0.001)
    cleared = api.prepare_setup(
        _hass(states), _tent_payload(hardware={"feed_ec_sensor": ""}), data
    )
    assert (
        cleared["feed_ec_factor"] == 1.0
    )  # unmapping the probe must not leave its factor behind


# ------------------------------------------------------------------ in-place upgrade
def _legacy_room():
    """A room exactly as a 2.17 wizard saved it: no plumbing, no ec_unit, no feed factor."""
    return {
        "room_name": "F2",
        "name": "F2",
        "room_prefix": "",
        "room_slug": "default",
        "active": True,
        "num_zones": 1,
        "setup_revision": 4,
        "zones": {
            "1": {
                "zone_number": 1,
                "name": "Row 1",
                "active": True,
                "zone_switch": "switch.v1",
                "vwc_sensors": ["sensor.vwc"],
                "ec_sensors": ["sensor.ec"],
                "vwc_front": "sensor.vwc",
                "vwc_back": "",
                "ec_front": "sensor.ec",
                "ec_back": "",
                "plant_count": 36,
            }
        },
        "hardware": {"pump_switch": "switch.p", "main_line_switch": "switch.m"},
        "parameters": {"substrate_volume": 6.0},
    }


def _legacy_hass():
    return _hass(
        {
            "switch.v1": ("off", {}),
            "switch.p": ("off", {}),
            "switch.m": ("off", {}),
            "sensor.vwc": ("50", {"unit_of_measurement": "%"}),
            "sensor.ec": ("3.1", {"unit_of_measurement": "mS/cm"}),
        }
    )


def test_re_saving_an_existing_room_adds_none_of_the_new_fields():
    old = _legacy_room()
    saved = api.prepare_setup(
        _legacy_hass(), api.configuration_payload(old), old, "one"
    )
    assert saved == old  # byte-for-byte: nothing declared, nothing invented


def test_an_existing_rooms_descriptor_is_exactly_what_it_published_before():
    """The controller fingerprints the descriptor to resume after a restart without a disarm
    cycle. A key that appeared on upgrade would break that for every install at once."""
    old = _legacy_room()
    descriptor = room.build_engine_config(
        "", "default", 1, old["zones"], old["hardware"], old
    )
    assert "plumbing" not in descriptor and "feed_ec_factor" not in descriptor
    assert (descriptor["pump"], descriptor["mainline"]) == ("switch.p", "switch.m")


def test_an_undeclared_layout_makes_no_demands_so_an_old_room_with_no_pump_still_saves():
    old = _legacy_room()
    old["hardware"] = {}
    assert (
        api.prepare_setup(_legacy_hass(), api.configuration_payload(old), old, "one")[
            "hardware"
        ]
        == {}
    )


# ------------------------------------------------------------------ every message exists
def _flow_source():
    return (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")


def _strings():
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert (
        strings == english
    ), "strings.json and translations/en.json have drifted apart"
    return strings


def test_every_setup_rule_has_a_message_in_both_flows():
    source = (INTEGRATION / "setup_api.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'key="([a-z_]+)"', source))
    keys |= {
        f"plumbing_{verb}_{part}"
        for verb in ("needs", "unused")
        for part in ("pump", "mainline")
    }
    keys |= {f"{kind}_unit" for kind in api.UNITS}
    keys |= {"ec_unit_ppm_scale", "ec_unit_missing", "ec_unit_unknown"}
    # ...plus the ones the flow raises itself (an errors={...: "key"} or a `problem = "key"`).
    keys |= set(re.findall(r'(?:: |problem = )"([a-z_]+)"\}?', _flow_source())) & {
        "must_read_off",
        "setup_invalid_detail",
        "sizing_range",
        "calibration_no_entity",
    }
    keys |= {"catch_test_invalid", "catch_test_out_of_range"}
    assert {
        "must_read_off",
        "sizing_range",
        "calibration_no_entity",
    } <= keys  # the scan still works
    strings = _strings()
    for section in ("config", "options"):
        missing = keys - set(strings[section]["error"])
        assert not missing, f"{section}.error has no message for {sorted(missing)}"


def test_every_abort_reason_and_menu_entry_has_a_message():
    strings = _strings()
    config_part, options_part = _flow_source().split("class OptionsFlowHandler")
    for section, source in (("config", config_part), ("options", options_part)):
        reasons = set(re.findall(r'reason="([a-z_]+)"', source))
        missing = reasons - set(strings[section]["abort"])
        assert not missing, f"{section}.abort has no message for {sorted(missing)}"
    menu = re.search(r"menu_options=\[(.*?)\]", options_part, re.S).group(1)
    entries = set(re.findall(r'"([a-z_]+)"', menu))
    assert len(entries) >= 4  # the scan still works
    assert entries == set(strings["options"]["step"]["init"]["menu_options"])


def test_every_wizard_field_has_a_label_a_tooltip_and_every_dropdown_its_options(
    flow_module,
):
    strings = _strings()
    fm = flow_module
    forms = {
        ("config", "manual_zones"): fm._system_schema({}, True),
        ("config", "zones"): {"ec_unit": None, **fm._zone_schema(24)},
        ("config", "hardware"): fm._plumbing_schema("pump_mainline_valves", {}, {}),
        ("config", "substrate"): fm._substrate_schema({}, "litres", "lph"),
        ("config", "catch_test"): fm._catch_test_schema(),
        ("config", "extras"): fm._extras_schema(),
        ("options", "calibrate_flow"): {**fm._catch_test_schema(), "zone": None},
        ("options", "edit_zones_map"): fm.OptionsFlowHandler._map_form(24, {}),
    }
    for (section, step), schema in forms.items():
        text = strings[section]["step"][step]
        fields = {fm._field_name(marker) for marker in schema}
        assert not fields - set(
            text["data"]
        ), f"{section}.{step}: no label for {sorted(fields - set(text['data']))}"
        untold = fields - set(text["data_description"])
        assert not untold, f"{section}.{step}: no tooltip for {sorted(untold)}"
    for key, options in (
        ("plumbing", api.PLUMBING_LAYOUTS),
        ("ec_unit", fm.EC_UNIT_CHOICES),
        ("volume_unit", fm.VOLUME_UNITS),
        ("flow_unit", fm.FLOW_UNITS),
        ("substrate_preset", fm.SUBSTRATE_PRESETS),
    ):
        assert set(options) == set(strings["selector"][key]["options"]), key


def test_tooltips_name_the_units_a_newcomer_has_to_choose_between():
    """The reason this file exists: nobody should need an assistant to know what to type."""
    steps = _strings()["config"]["step"]
    ec_help = (
        steps["zones"]["data_description"]["ec_unit"]
        + steps["zones"]["data_description"]["zone_1_ec"]
    )
    for term in ("mS/cm", "dS/m", "µS/cm", "ppm", "500", "700", "CF"):
        assert term in ec_help, term
    assert "0-100" in steps["zones"]["data_description"]["zone_1_vwc"]
    assert "PER PLANT" in steps["substrate"]["data"]["substrate_volume"]
    assert "24-hour" in steps["hardware"]["data_description"]["lights_on_hour"]
    assert "does NOT operate" in steps["extras"]["data_description"]["waste_switch"]


def test_translations_follow_the_hassfest_rules_that_are_easy_to_break():
    """hassfest only runs in CI (it is a container action), so the rules a new form field or
    message is most likely to trip are checked here with hassfest's OWN patterns (copied from
    script/hassfest/translations.py), where a failure takes seconds to see. All three were hit
    while writing this wizard, and each would have failed the whole repository's validation:

    1. every translation key is a lowercase slug. A dropdown's option VALUES are translation
       keys, so an option stored as "L/hr" or "gal" is invalid;
    2. no placeholder inside single quotes. Home Assistant formats messages with ICU
       MessageFormat, where single quotes ESCAPE braces: '{unit}' shows the grower the
       literal text {unit} instead of their sensor's unit;
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
