"""Dosing on an upgraded install, after the dosing runner learned units and the actuator table.

The 3.11.1 room's own dosing store (tests_ha/fixtures/dosing_3_11_1.json, F-3111) loads unchanged
and a dose asked for through the real dosing_request service is dosed by the REAL controller app
with exactly the calls 3.11.1 sent: its volume set, its start pressed, its volume put back, nothing
else. Its pumps' numbers carry no unit, as most firmwares' do, so they are read as mL and mL/s as
they always were. The 3.8 tent (F-38), from before dosing, loads with no dosing and sends nothing.
"""

from conftest import fixture
from test_dosing import _call
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
DOSER = {
    "number.doser_a_volume": "25",
    "button.doser_a_start": "unknown",
    "binary_sensor.doser_a_dosing": "off",
    "switch.doser_a_power": "off",
    "number.doser_a_flow": "11.06",
}


def _firmware(c, fake, clock, monkeypatch):
    """The doser's firmware, as test_dosing_controller.py scripts it: a press doses for 2 s."""
    import controller

    pressed = []

    def call(domain, service, timeout=None, **data):
        fake.calls.append((domain, service, data))
        if service == "set_value":
            fake.set_state(data["entity_id"], f"{float(data['value']):g}")
        if (domain, service) == ("button", "press"):
            fake.set_state("binary_sensor.doser_a_dosing", "on")
            pressed.append(clock.seconds)
        return True

    def sleep(seconds):
        clock.sleep(seconds)
        if pressed and clock.seconds - pressed[0] >= 2:
            fake.set_state("binary_sensor.doser_a_dosing", "off")

    monkeypatch.setattr(controller, "ha_call", call)
    c.dosing._mono, c.dosing._sleep = clock.monotonic, sleep


def _run(runner):
    """What the controller's main loop does for dosing (Controller._sleep_for): the requests read now,
    then a wake whenever the dose it took is due, until it has ended."""
    runner.poll()
    while runner._steps is not None:
        runner._sleep(runner._due - runner._mono())
        runner.step()


def _commands(fake):
    return [
        [domain, service, data]
        for domain, service, data in fake.calls
        if domain not in ("persistent_notification", DOMAIN)
    ]


async def test_a_3_11_1_dosing_store_doses_with_the_calls_3_11_1_sent(
    hass, hass_storage, hass_admin_user, controller_for, monkeypatch
):
    seed = fixture(JEV_3_11_1)
    store = f"{DOMAIN}.dosing.{seed['entry_id']}"
    dosing = fixture("dosing_3_11_1.json")["dosing"]
    hass_storage[store] = {
        "version": 1,
        "minor_version": 1,
        "key": store,
        "data": dosing,
    }
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for entity_id, state in DOSER.items():
        hass.states.async_set(entity_id, state)
    asked = await _call(
        hass,
        hass_admin_user,
        "dosing_request",
        room_id="room:",  # the upgraded room keeps its un-prefixed ids
        action="dose",
        pump="part_a",
        ml=22,
    )
    assert asked["error"] is None
    await hass.async_block_till_done()

    c, fake, clock = controller_for()
    _firmware(c, fake, clock, monkeypatch)
    assert c.dosing.recover()
    _run(c.dosing)

    assert _commands(fake) == [
        ["number", "set_value", {"entity_id": "number.doser_a_volume", "value": 22}],
        ["button", "press", {"entity_id": "button.doser_a_start"}],
        ["number", "set_value", {"entity_id": "number.doser_a_volume", "value": 25.0}],
    ]
    state, attributes = fake.sets["sensor.crop_steering_dosing"]
    assert attributes["handled_result"] == "finished"
    assert attributes["pumps"]["part_a"]["flow_ml_s"] == 11.06


async def test_a_3_8_tent_from_before_dosing_loads_with_none_and_sends_nothing(
    hass, controller_for, monkeypatch
):
    await _upgrade(hass, "entry_3_8_learned_tent.json")
    shown = hass.states.get("sensor.crop_steering_dosing_config")
    assert (shown.state, shown.attributes["pumps"]) == ("0", [])

    c, fake, clock = controller_for()
    _firmware(c, fake, clock, monkeypatch)
    assert c.dosing.recover()
    _run(c.dosing)
    assert _commands(fake) == []
    assert c.dosing.holds(c.rooms[0]) is None
