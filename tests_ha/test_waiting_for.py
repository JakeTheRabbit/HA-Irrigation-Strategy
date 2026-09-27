"""What each zone waits for next, from the real controller, in a real Home Assistant.

The controller publishes sensor.crop_steering_zone_N_waiting_for_app over REST (its write is replayed
into Home Assistant here) with the thresholds its engine compares. The dashboard shows them as the
zone's "Next:", so they have to be the room's own setpoints, read from the integration's entities.
"""

from datetime import datetime

from test_setup_entry import _install

WAITING = "sensor.crop_steering_zone_1_waiting_for_app"


def _setpoint(hass, key):
    """As the controller reads it: the zone's own number when it has one, else the room's."""
    own = hass.states.get(f"number.crop_steering_zone_1_{key}")
    return float((own or hass.states.get(f"number.crop_steering_{key}")).state)


async def test_a_zone_in_p2_waits_for_its_own_trigger_and_lights_off(hass, controller_for):
    await _install(hass)
    # The probe's reading is only fresh on the real clock: put the lights around it instead, so the
    # zone is mid-photoperiod whenever this runs.
    now = datetime.now()
    off = (now.hour + 8) % 24
    for key, hour in (("lights_on_hour", (now.hour - 4) % 24), ("lights_off_hour", off)):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": f"number.crop_steering_{key}", "value": hour},
            blocking=True,
        )
    c, fake, _clock = controller_for({})
    c.loop_once(datetime.now())  # the first pass starts the grow-day
    c.rooms[0].state[1]["phase"] = "P2"
    c.loop_once(datetime.now())
    for entity_id, (state, attributes) in fake.sets.items():  # what its REST writes put in HA
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()

    shown = hass.states.get(WAITING)
    assert shown.state == "P2"
    at = datetime.fromisoformat(shown.attributes["at"])
    conditions = {item["rule"]: item for item in shown.attributes["conditions"]}
    topup = conditions["p2_topup"]
    assert (topup["op"], topup["value"]) == ("<", _setpoint(hass, "p2_vwc_threshold"))
    assert topup["now"] == float(hass.states.get("sensor.crop_steering_vwc_zone_1").state)
    to_off = (off * 60 - (at.hour * 60 + at.minute + at.second / 60)) % 1440
    assert abs(conditions["lights_off"]["in_min"] - to_off) <= 1
