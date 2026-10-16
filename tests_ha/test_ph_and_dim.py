"""pH auto-correct, light dimming on dry substrate and the shots-held alert, in a real Home Assistant.

Every setting is a room entity under the id the controller app reads, and starts so that nothing changes:
both switches OFF and the shots-held hours at 0, on a fresh room and on an upgraded 3.11.1 room (F-3111),
whose dosing store loads unchanged with no pump in a pH role. A pH role saved through the real dosing_save
service reaches sensor.crop_steering_dosing_config, a save from a page that does not know roles keeps it,
and the REAL controller app then corrects that room's low tank once a person turns pH auto-correct on (and
never while it is off): held, mixed, one 5 s dose of the pH-up pump, mixed, read, released.
"""

import json
from datetime import datetime, timezone

from conftest import fixture
from test_dosing import _call as _dosing_call
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
SWITCHES = {"ph_auto_correct": "off", "dry_dim": "off"}
NUMBERS = {
    "ph_correct_dose_s": 5,
    "ph_correct_max_tries": 2,
    "ph_correct_mix_min": 5,
    "ph_correct_daily_max": 3,
    "ph_correct_margin": 0.1,
    "dry_dim_floor_vwc": 15,
    "dry_dim_level_pct": 50,
    "dry_dim_after_min": 10,
    "dry_dim_max_h": 4,
    "held_alert_hours": 0,
}
DEVICES = {
    "number.doser_a_volume": "25",
    "button.doser_a_start": "unknown",
    "binary_sensor.doser_a_dosing": "off",
    "switch.doser_a_power": "off",
    "number.doser_a_flow": "11.06",
    "number.doser_b_volume": "25",
    "button.doser_b_start": "unknown",
    "binary_sensor.doser_b_dosing": "off",
    "switch.doser_b_power": "off",
    "number.doser_b_flow": "11.06",
    "switch.tank_fill": "off",
    "binary_sensor.tank_full": "on",
    "switch.tank_mixer": "off",
    "input_boolean.tank_dosing": "off",
    "input_datetime.tank_filled_at": "2026-10-14 19:00:00",
}


async def _call(hass, user, name, **data):
    """test_dosing's call, for the upgraded room: it keeps its un-prefixed ids (room:)."""
    return await _dosing_call(hass, user, name, **{"room_id": "room:", **data})


def _settings(hass, prefix):
    switches = {k: hass.states.get(f"switch.{DOMAIN}_{prefix}{k}").state for k in SWITCHES}
    numbers = {k: float(hass.states.get(f"number.{DOMAIN}_{prefix}{k}").state) for k in NUMBERS}
    return switches, numbers


async def test_a_fresh_room_gets_every_setting_with_nothing_switched_on(hass):
    await _install(hass)
    assert _settings(hass, "tent_") == (SWITCHES, {k: float(v) for k, v in NUMBERS.items()})


async def _upgraded(hass, hass_storage):
    seed = fixture(JEV_3_11_1)
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    data = fixture("dosing_3_11_1.json")["dosing"]
    assert all("ph_role" not in pump for pump in data["pumps"])  # saved before roles existed
    hass_storage[store] = {"version": 1, "minor_version": 1, "key": store, "data": data}
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id, state in DEVICES.items():
        hass.states.async_set(entity_id, state)


async def test_an_upgraded_3_11_1_room_gets_them_off_and_its_dosing_store_unchanged(
    hass, hass_storage, hass_admin_user
):
    await _upgraded(hass, hass_storage)
    assert _settings(hass, "") == (SWITCHES, {k: float(v) for k, v in NUMBERS.items()})
    pumps = hass.states.get(f"sensor.{DOMAIN}_dosing_config").attributes["pumps"]
    assert [p["id"] for p in pumps] == ["part_a", "part_b"]
    assert all("ph_role" not in p for p in pumps)
    doc = await _call(hass, hass_admin_user, "dosing_get")
    assert doc["error"] is None and doc["config"]["revision"] == 1


async def _role(hass, hass_admin_user):
    doc = await _call(hass, hass_admin_user, "dosing_get")
    config = doc["config"]
    pumps = [dict(p) for p in config["pumps"]]
    pumps[0]["ph_role"] = "ph_up"
    saved = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=config["revision"],
        pumps=pumps,
        batch=config["batch"],
    )
    assert saved["error"] is None
    await hass.async_block_till_done()
    return saved


async def test_a_ph_role_reaches_the_controller_and_an_older_page_keeps_it(
    hass, hass_storage, hass_admin_user
):
    await _upgraded(hass, hass_storage)
    saved = await _role(hass, hass_admin_user)
    pumps = hass.states.get(f"sensor.{DOMAIN}_dosing_config").attributes["pumps"]
    assert pumps[0]["ph_role"] == "ph_up" and "ph_role" not in pumps[1]
    # A page from before roles sends its pumps without the key: the role is kept.
    old = [{k: v for k, v in p.items() if k != "ph_role"} for p in saved["config"]["pumps"]]
    again = await _call(
        hass,
        hass_admin_user,
        "dosing_save",
        expected_revision=saved["config"]["revision"],
        pumps=old,
        batch=saved["config"]["batch"],
    )
    assert again["error"] is None and again["config"]["pumps"][0]["ph_role"] == "ph_up"


def _firmware(c, fake, clock, monkeypatch, tank):
    """The doser and the tank: a press doses its volume at its calibrated flow and lifts the tank's pH by
    `tank["move"]`; switches and input_booleans read back what they were sent."""
    import controller

    pressed = []

    def stamp():
        return datetime.now(timezone.utc).isoformat()

    def call(domain, service, timeout=None, **data):
        fake.calls.append((domain, service, data))
        entity = data.get("entity_id")
        if service == "set_value":
            fake.set_state(entity, f"{float(data['value']):g}")
        elif domain in ("switch", "input_boolean") and service in ("turn_on", "turn_off"):
            fake.set_state(entity, "on" if service == "turn_on" else "off")
        elif (domain, service) == ("button", "press"):
            fake.set_state("binary_sensor.doser_a_dosing", "on")
            volume = float(fake.states["number.doser_a_volume"][0])
            pressed.append(clock.seconds + volume / float(fake.states["number.doser_a_flow"][0]))
            tank["ph"] = round(tank["ph"] + tank["move"], 2)
            fake.set_state(tank["probe"], f"{tank['ph']:g}", {}, last_updated=stamp())
        return True

    def sleep(seconds):
        clock.sleep(seconds)
        if pressed and clock.seconds >= pressed[-1]:
            fake.set_state("binary_sensor.doser_a_dosing", "off")
        fake.set_state(tank["probe"], f"{tank['ph']:g}", {}, last_updated=stamp())  # the probe reports

    monkeypatch.setattr(controller, "ha_call", call)
    monkeypatch.setattr(controller.time, "sleep", sleep)
    c.dosing._mono, c.dosing._sleep = clock.monotonic, sleep


def _minutes(c, n):
    for _ in range(n):
        c.dosing._sleep(60)
        c.dosing.poll()
        while c.dosing._steps is not None:
            c.dosing._sleep(c.dosing._due - c.dosing._mono())
            c.dosing.step()


def _commands(fake, *entities):
    return [
        (service, data.get("entity_id"))
        for domain, service, data in fake.calls
        if data.get("entity_id") in entities
    ]


async def test_the_real_controller_corrects_the_tank_only_once_a_person_turns_it_on(
    hass, hass_storage, hass_admin_user, controller_for, monkeypatch
):
    import controller

    await _upgraded(hass, hass_storage)
    await _role(hass, hass_admin_user)
    c, fake, clock = controller_for()
    room = c.rooms[0]
    assert room.feed_ph_sensor == "sensor.feed_ph"  # the 3.11.1 room's own feed pH probe
    tank = {"probe": room.feed_ph_sensor, "ph": 5.6, "move": 0.3}
    _firmware(c, fake, clock, monkeypatch, tank)
    fake.set_state(controller.room_gate(room), "on")
    fake.set_state(f"number.{DOMAIN}_irrigation_ph_min", "5.8")
    fake.set_state(f"number.{DOMAIN}_irrigation_ph_max", "6.5")
    assert c.dosing.recover()

    _minutes(c, 10)  # pH auto-correct is off, as the upgrade left it
    assert _commands(fake, "button.doser_a_start") == []

    fake.set_state(f"switch.{DOMAIN}_ph_auto_correct", "on")  # a person turns it on
    _minutes(c, 8)
    assert _commands(fake, "button.doser_a_start") == [("press", "button.doser_a_start")]
    volumes = [d["value"] for dom, svc, d in fake.calls if svc == "set_value"
               and d["entity_id"] == "number.doser_a_volume"]
    assert volumes[0] == 55  # 5 s at its calibrated 11.06 mL/s, in whole mL
    assert _commands(fake, "input_boolean.tank_dosing", "switch.tank_mixer") == [
        ("turn_on", "input_boolean.tank_dosing"),
        ("turn_on", "switch.tank_mixer"),
        ("turn_off", "switch.tank_mixer"),
        ("turn_off", "input_boolean.tank_dosing"),
    ]
    status = fake.sets[f"sensor.{DOMAIN}_dosing"][1]
    assert status["history"][0]["kind"] == "correct"
    assert status["history"][0]["result"] == "finished: the tank is inside its band"
    assert status["ph_correct"]["doses"] == 1 and status["ph_correct"]["latch"] is None
    saved = json.loads(open(c.dosing.path, encoding="utf-8").read())["rooms"]["default"]
    assert saved["inflight"] is None
    assert c.dosing.holds(room) is None


async def test_the_controller_reads_the_dimming_and_held_settings_under_their_ids(
    hass, hass_storage, controller_for
):
    await _upgraded(hass, hass_storage)
    c, fake, clock = controller_for()
    room = c.rooms[0]
    assert c._dim_settings(room) == {"floor_vwc": 15, "level_pct": 50, "after_min": 10, "max_h": 4}
    assert c._num_or_none(f"number.{DOMAIN}_held_alert_hours") == 0
    assert c.dosing._ph_settings(room) == {
        "dose_s": 5, "max_tries": 2, "mix_min": 5, "daily_max": 3, "margin": 0.1,
    }
    assert room._dim is None  # an upgraded state file has no dim
