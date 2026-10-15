"""Each probe's reading quality and the reason for it, on the zone reading, in a real Home Assistant.

The zone's moisture and EC sensors already name the probes they used and left out. Each probe now
also gets a quality and a reason (fresh, stale, out_of_range, excluded_outlier, unknown_unit) beside
them, which the Probes page shows. The attributes are additive: every name an upgraded room had is
still there, and all of them stay well under what Home Assistant records (16 KB).
"""

import json

from conftest import fixture
from test_probe_fusion import A, B, C, _install, _read
from test_upgrade_in_place import JEV_3_11_1, _upgrade

# The zone reading's attributes before reading quality (3.11.1 and the guarded fusion).
BEFORE = {"probes", "used", "excluded", "spread", "method", "steered_by", "offsets_learned"}


async def test_an_upgraded_room_keeps_its_attribute_names_and_gains_quality(hass):
    seed = fixture(JEV_3_11_1)
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    for zone in (1, 2):
        for metric in ("vwc", "ec"):
            state = hass.states.get(f"sensor.crop_steering_{metric}_zone_{zone}")
            names = set(state.attributes)
            assert BEFORE <= names and "quality" in names, (zone, metric, names)
            assert set(state.attributes["quality"]) == set(state.attributes["used"]) | set(
                state.attributes["excluded"]
            )
            assert len(json.dumps(dict(state.attributes)).encode()) < 16 * 1024


async def test_a_probe_far_from_the_others_says_so(hass, freezer):
    await _install(hass, [A, B, C])
    state = await _read(hass, freezer, **{A: "40", B: "42", C: "90"})
    assert state.attributes["quality"] == {
        A: {"quality": "good", "reason": "fresh"},
        B: {"quality": "good", "reason": "fresh"},
        C: {"quality": "bad", "reason": "excluded_outlier"},
    }


async def test_a_probe_in_an_unknown_unit_says_so(hass, freezer):
    await _install(hass, [A, B])
    await _read(hass, freezer, **{A: "40", B: "42"})
    hass.states.async_set(B, "1250", {"unit_of_measurement": "mV"})
    state = await _read(hass, freezer, **{A: "40"})
    assert state.attributes["quality"][B] == {"quality": "bad", "reason": "unknown_unit"}
    assert state.attributes["excluded"] == {B: "set aside for its unit"}
