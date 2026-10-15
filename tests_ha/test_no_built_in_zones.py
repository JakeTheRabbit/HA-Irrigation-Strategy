"""No built-in zones, and the lights hours keep the source each room uses today.

The app's `options:` still ship `num_zones: 3` and lights 10-22, because the Supervisor merges them
into every saved options file and an older room may rely on them. What they may do is pinned here,
in a real Home Assistant, on seeded old installs:

- the zones come from the integration's room. `num_zones` counts zones only for a room hand-mapped
  in a `hardware` option (3 when that file has no `num_zones`). With Home Assistant unreachable at
  start the room has no zones, so none is invented, until Home Assistant answers with its own.
- the lights hours come from the room's `number.crop_steering_<prefix>lights_on_hour`/`_off_hour`,
  then the hours last read this run, then the app option only while nothing has been read since
  start. The "lights hours now come from the integration" alert (CS-403) fires on exactly the
  rooms it fired on before.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from conftest import fixture, switch_calls
from test_recreated_room_controller import _see
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

HELPER = "input_boolean.f2_control_enabled"
SHIPPED = {"num_zones": 3, "lights_on_hour": 10, "lights_off_hour": 22, "enable_flag": HELPER}
ON = "number.crop_steering_lights_on_hour"
OFF = "number.crop_steering_lights_off_hour"
F_ENV = "entry_env_era.json"
F_217 = "entry_2_17_wizard.json"
F_2251 = "entry_2_25_1_pumped_room.json"
F_3111 = "entry_3_11_1_pumped_room.json"
NOW = datetime(2026, 10, 14, 15, 0, 0)


def _lights_logs(out):
    return [line for line in out.splitlines() if "config: lights" in line]


def _zones_published(fake):
    return {
        int(entity_id.split("_zone_")[1].split("_")[0]) for entity_id in fake.sets if "_zone_" in entity_id
    }


def _cs403(fake):
    return [
        d for domain, service, d in fake.calls
        if (domain, service) == ("persistent_notification", "create")
        and d["notification_id"] == "f2_lights_source"
    ]


# ------------------------------------------------------------------ lights: where the hours come from
async def test_an_env_era_room_runs_on_its_integration_lights_not_the_app_option(
    hass, controller_for, capsys
):
    await _upgrade(hass, F_ENV)
    hass.states.async_set(ON, "7")
    hass.states.async_set(OFF, "19")
    c, _fake, _clock = controller_for(dict(SHIPPED))
    room = c.rooms[0]
    capsys.readouterr()
    c._refresh_lights(room)
    assert (room.lights_on_hour, room.lights_off_hour) == (7.0, 19.0)
    assert _lights_logs(capsys.readouterr().out) == [
        "[Crop Steering Controller] config: lights 7:00-19:00 (source: integration)"
    ]


async def test_a_2_25_1_room_keeps_its_own_lights_and_drives_only_its_two_zones(
    hass, controller_for
):
    """Its options file says 3 zones and 10-22, as the Supervisor wrote it. The room has 2 zones and
    runs 6-18 from the integration, and nothing about a third zone is published or driven."""
    seed = fixture(F_2251)
    assert seed["addon_options"]["num_zones"] == 3
    await _upgrade(hass, F_2251, registry_ids=seed["registry"])
    hass.states.async_set("switch.crop_steering_engine_enabled", "on")
    c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert sorted(room.zones) == [1, 2] and not c._default_provisional
    assert room.hw["valves"] == {1: "switch.zone_1_valve", 2: "switch.zone_2_valve"}
    c.loop_once(NOW)
    assert (room.lights_on_hour, room.lights_off_hour) == (6.0, 18.0)
    assert _zones_published(fake) <= {1, 2}
    driven = {entity for _service, entity in switch_calls(fake)}
    assert driven <= {"switch.irrigation_pump", "switch.irrigation_main_line",
                      "switch.zone_1_valve", "switch.zone_2_valve"}


async def test_a_lights_number_unreadable_at_start_uses_the_option_until_it_reads(
    hass, controller_for, capsys
):
    """As today: the option only while nothing has been read since start; once the number reads it
    wins; a later unreadable loop keeps the last reading, never the option."""
    seed = fixture(F_2251)
    await _upgrade(hass, F_2251, registry_ids=seed["registry"])
    hass.states.async_set(ON, "unavailable")
    hass.states.async_set(OFF, "unavailable")
    c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    capsys.readouterr()
    c._refresh_lights(room)
    assert (room.lights_on_hour, room.lights_off_hour) == (10.0, 22.0)
    assert _lights_logs(capsys.readouterr().out) == [
        "[Crop Steering Controller] config: lights 10:00-22:00 (source: add-on option (integration entity missing))"
    ]

    fake.set_state(ON, "6")
    fake.set_state(OFF, "18")
    c._refresh_lights(room)
    assert (room.lights_on_hour, room.lights_off_hour) == (6.0, 18.0)

    fake.set_state(ON, "unavailable")
    c._refresh_lights(room)
    assert (room.lights_on_hour, room.lights_off_hour) == (6.0, 18.0)


# Which rooms get CS-403, as the controller before this change decided it (its lights code is
# unchanged here; this table stops a later change moving it silently). Each room runs on the app
# options its install really has: the Supervisor-merged defaults, or its recorded options file.
CS403 = [
    ("env era, merged defaults", F_ENV, None, True),
    ("2.17 wizard, merged defaults", F_217, None, False),
    ("2.25.1, its options file", F_2251, "addon_options", False),
    ("3.11.1, its options file", F_3111, "options_3_11_1_jev_typesafe.json", False),
    ("fresh wizard room, merged defaults", None, None, False),
]


@pytest.mark.parametrize(("seeded", "options", "fires"), [row[1:] for row in CS403], ids=[r[0] for r in CS403])
async def test_the_lights_source_alert_fires_on_exactly_the_rooms_it_did(
    hass, controller_for, seeded, options, fires
):
    if seeded is None:
        await _install(hass)
        app = dict(SHIPPED)
    else:
        seed = fixture(seeded)
        await _upgrade(hass, seeded, registry_ids=seed.get("registry"))
        if options is None:
            app = dict(SHIPPED)
        elif options == "addon_options":
            app = seed["addon_options"]
        else:  # only the keys that decide lights and the gate; the brain is not under test here
            recorded = fixture(options)["options"]
            app = {k: recorded[k] for k in SHIPPED}
    c, fake, _clock = controller_for(app)
    c._refresh_lights(c.rooms[0])
    assert bool(_cs403(fake)) is fires


# ------------------------------------------------------------------ zones: never invented
@pytest.mark.parametrize("options", [dict(SHIPPED), {"enable_flag": HELPER}], ids=["merged", "raw"])
async def test_an_env_era_room_without_num_zones_still_waters_its_zone(hass, controller_for, options):
    """`num_zones` merged in by the Supervisor, or absent from a raw options file: the room has the
    zone its integration publishes either way, and waters it."""
    await _upgrade(hass, F_ENV)
    hass.states.async_set(HELPER, "on")
    c, fake, _clock = controller_for(options)
    room = c.rooms[0]
    assert sorted(room.zones) == [1] and not c._default_provisional
    assert room.enable_flag == HELPER and room.hw["valves"] == {1: "switch.veg_valve"}
    _see(hass, fake)
    assert c._blocked(room, 1) is None


async def test_a_hand_mapped_room_with_no_num_zones_still_gets_three(hass, controller_for):
    c, _fake, _clock = controller_for(
        {"enable_flag": HELPER, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                             "valves": {"1": "switch.v1", "2": "switch.v2", "3": "switch.v3"}}}
    )
    assert sorted(c.rooms[0].zones) == [1, 2, 3] and not c._default_provisional


async def test_started_while_home_assistant_is_unreachable_no_zone_until_it_answers(
    hass, controller_for
):
    """The 2.25.1 box restarting while Home Assistant is down: its controller sees nothing at all
    (every read fails). It used to stand three zones in from `num_zones`; it now has none, drives
    nothing, and the moment Home Assistant answers it has its own two, counters intact."""
    seed = fixture(F_2251)
    c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room.zones == {} and c._default_provisional
    c.loop_once(NOW)
    assert switch_calls(fake) == [] and _zones_published(fake) == set()

    await _upgrade(hass, F_2251, registry_ids=seed["registry"])
    _see(hass, fake)
    c.loop_once(NOW)
    assert sorted(room.zones) == [1, 2] and not c._default_provisional
    old = seed["controller_saved"]["default"]
    assert [room.state[z]["shots"] for z in (1, 2)] == [old["1"]["shots"], old["2"]["shots"]]
    assert [room.state[z]["daily_vol"] for z in (1, 2)] == [old["1"]["daily_vol"], old["2"]["daily_vol"]]
    assert switch_calls(fake) == []  # its engine switch is off: still nothing driven

    assert c._save_state()
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))["default"]
    assert saved["_setup"] == old["_setup"] and "3" not in saved


async def test_a_controller_with_no_integration_room_drives_nothing(hass, controller_for):
    """Home Assistant answers, switches and probes exist, and no Crop Steering room is set up."""
    hass.states.async_set("switch.some_valve", "off")
    hass.states.async_set("sensor.some_vwc", "41", {"unit_of_measurement": "%"})
    c, fake, _clock = controller_for(dict(SHIPPED))
    assert c.rooms[0].zones == {} and c._default_provisional
    for _ in range(3):
        c.loop_once(NOW)
    assert switch_calls(fake) == [] and _zones_published(fake) == set()


def test_the_app_options_keep_their_shipped_defaults():
    """They stay: the Supervisor merges them into saved files, and a room hand-mapped before the
    wizard may rely on that 3 and that 10-22."""
    import yaml

    config = Path(__file__).resolve().parents[1] / "addons" / "f2_control" / "config.yaml"
    options = yaml.safe_load(config.read_text(encoding="utf-8"))["options"]
    assert {k: options[k] for k in ("num_zones", "lights_on_hour", "lights_off_hour")} == {
        "num_zones": 3, "lights_on_hour": 10, "lights_off_hour": 22,
    }
