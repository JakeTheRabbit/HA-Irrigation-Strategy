"""The vitals notification shows each zone's water today as the room's choice has it
(select.crop_steering_<prefix>water_today_view): the zone's total, or each plant's share of it."""
import ast
import pathlib
import re
from datetime import datetime

import controller
from test_controller import _build

HARDWARE = {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1"}}
VIEW = "select.crop_steering_water_today_view"
PLANTS = "number.crop_steering_zone_1_plant_count"


def _water(daily_litres, states):
    c, fake = _build({"num_zones": 1, "hardware": HARDWARE}, states=states)
    c.rooms[0].state[1]["daily_vol"] = daily_litres
    c._maybe_notify({"default": {1: {"phase": "P2", "vwc": 85.0, "ec": 0.7}}}, datetime(2026, 9, 27, 13, 4))
    (message,) = [d["message"] for dom, svc, d in fake.calls if dom == "persistent_notification"]
    return message.splitlines()[-1].split(" | ")[1]  # "Z1 P2: VWC … | <water> | last …"


def test_each_zones_total_until_the_room_chooses_per_plant():
    assert _water(12.4, {PLANTS: ("36", {})}) == "12.4L day"
    assert _water(12.4, {VIEW: ("Zone total", {}), PLANTS: ("36", {})}) == "12.4L day"


def test_per_plant_divides_the_zones_water_by_its_plants():
    assert _water(12.4, {VIEW: ("Per plant", {}), PLANTS: ("36", {})}) == "344 mL/plant day"
    assert _water(43.2, {VIEW: ("Per plant", {}), PLANTS: ("36", {})}) == "1.2 L/plant day"


def test_a_zone_without_a_plant_count_stays_in_litres():
    assert _water(12.4, {VIEW: ("Per plant", {})}) == "12.4L day"
    assert _water(12.4, {VIEW: ("Per plant", {}), PLANTS: ("0", {})}) == "12.4L day"


def test_the_controller_reads_the_words_the_integration_offers():
    """The controller cannot import the integration (it runs in its own container)."""
    source = (pathlib.Path(__file__).parents[3] / "custom_components/crop_steering/const.py").read_text()
    offered = re.search(r"^WATER_TODAY_VIEWS = (\[.*\])", source, re.M).group(1)
    assert controller.PER_PLANT in ast.literal_eval(offered)
