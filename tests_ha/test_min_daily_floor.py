"""The minimum daily water per plant is a real per-zone setting.

The controller used to read it only from an input_number helper that nothing in the product creates,
so on a stranger's Home Assistant the floor could never be turned on. Each zone now has
number.crop_steering_zone_N_min_daily_ml_per_plant. A fresh room starts at 0 (off: the floor waters
whatever the probe reads). An upgraded room that set the old helper keeps its value: the new entity
takes it on its first start.
"""

import json
from pathlib import Path

from homeassistant.setup import async_setup_component
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

ENTITY = "number.crop_steering_zone_{}_min_daily_ml_per_plant"
HELPER = "input_number.crop_steering_zone_1_min_daily_ml_per_plant"


async def _helper(hass, value):
    """The old helper as an operator made it, by hand, with the integration's input_number."""
    assert await async_setup_component(
        hass,
        "input_number",
        {
            "input_number": {
                HELPER.split(".", 1)[1]: {"min": 0, "max": 5000, "initial": value}
            }
        },
    )
    await hass.async_block_till_done()


async def test_a_fresh_room_starts_with_the_floor_off(hass):
    await _install(hass)
    new = ENTITY.replace("crop_steering_", "crop_steering_tent_")  # every new room has a slug, tent_
    assert float(hass.states.get(new.format(1)).state) == 0


async def test_an_upgraded_room_keeps_the_value_its_old_helper_held(hass):
    await _helper(hass, 250)
    await _upgrade(hass, JEV_3_11_1)
    assert float(hass.states.get(ENTITY.format(1)).state) == 250
    assert float(hass.states.get(ENTITY.format(2)).state) == 0  # no helper: still off


async def test_the_controller_waters_the_upgraded_floor_from_the_new_setting(
    hass, controller_for
):
    await _helper(hass, 250)
    await _upgrade(hass, JEV_3_11_1)
    c, fake, _clock = controller_for({})
    fake.set_state(HELPER, "unavailable")  # the setting alone carries the value now
    room = c.rooms[0]
    room.strategy_snapshot = None
    plants = float(hass.states.get("number.crop_steering_zone_1_plant_count").state)
    fc = c._zone_num(room, 1, "field_capacity", 0)
    p = c._params(room, 1, ec_known=False)
    assert p.min_daily_volume == 250 * plants / 1000
    assert p.drown_ceiling == max(50.0, min(100.0, fc + 5))


def test_the_helper_is_set_up_before_the_integration_reads_it():
    manifest = Path(__file__).resolve().parents[1] / (
        "custom_components/crop_steering/manifest.json"
    )
    assert "input_number" in json.loads(manifest.read_text(encoding="utf-8"))[
        "after_dependencies"
    ]
