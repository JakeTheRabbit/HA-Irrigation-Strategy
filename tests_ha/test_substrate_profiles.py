"""The substrate profile pack in a real Home Assistant.

An upgraded room reads generic and nothing it holds moves. A room set to coco starts every moisture
band and dryback target it has no value for yet at the coco profile's numbers; every value the room
already holds stays exactly as it was."""

from conftest import fixture
from custom_components.crop_steering.generated.defaults import SUBSTRATE_PROFILES
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, _upgrade

SUBSTRATE = "select.crop_steering_substrate"
BANDS = ("field_capacity", "p1_target_vwc", "p2_vwc_threshold", "p3_emergency_vwc_threshold",
         "vegetative_dryback_target", "generative_dryback_target")


def _value(hass, entity_id):
    return float(hass.states.get(entity_id).state)


def _start(profile, key):
    return {**SUBSTRATE_PROFILES[profile]["vwc"], **SUBSTRATE_PROFILES[profile]["dryback"]}[key]


def _held(seed):
    """What the old room holds: its operator-tuned numbers, and its wizard answers (a room-wide value)."""
    held = {
        k: float(v)
        for k, v in seed["operator_tuned_numbers"].items()
        if k.startswith("number.") and not isinstance(v, list)
    }
    for key, value in seed["data"].get("parameters", {}).items():
        if key in BANDS:
            held[f"number.crop_steering_{key}"] = float(value)
    return held


def _band_ids(zones=(1, 2)):
    ids = {f"number.crop_steering_{key}": key for key in BANDS}
    ids.update({f"number.crop_steering_zone_{z}_{key}": key for z in zones for key in BANDS})
    return ids


async def test_an_upgraded_3_11_1_room_is_generic_and_nothing_it_holds_moves(hass):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    assert hass.states.get(SUBSTRATE).state == "generic"
    held = _held(seed)
    for entity_id, key in _band_ids().items():
        if entity_id in held:
            assert _value(hass, entity_id) == held[entity_id], entity_id
        else:  # no saved value: where the table starts it, as before the pack
            assert _value(hass, entity_id) == _start("generic", key), entity_id


async def test_a_coco_room_takes_the_coco_bands_for_new_values_only(hass):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"], restored={SUBSTRATE: "coco"})
    assert hass.states.get(SUBSTRATE).state == "coco"
    held = _held(seed)
    new = 0
    for entity_id, key in _band_ids().items():
        if entity_id in held:  # what the room already holds stays
            assert _value(hass, entity_id) == held[entity_id], entity_id
        else:
            new += 1
            assert _value(hass, entity_id) == _start("coco", key), entity_id
    assert new and _start("coco", "field_capacity") != _start("generic", "field_capacity")


async def test_a_new_room_is_generic_and_starts_where_the_table_does(hass):
    await _install(hass)
    for entity_id, key in _band_ids(zones=(1,)).items():
        assert _value(hass, entity_id) == _start("generic", key), entity_id
