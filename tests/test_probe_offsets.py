"""A moisture probe's own offset and curve (G9), integration side.

probe_offsets.apply / read are pure. The CalibrationStore keeps `probe_user_offsets`, checks each
probe_offset_set against the revision and bounds, reads the write back and journals config.changed
{store: "calibration", section: "probe_user_offsets"}; a preview writes nothing at all. The zone
sensor applies the offsets before it fuses its probes and moves what fusion learned by the same step.
"""

import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import calibration, probe_offsets  # noqa: E402
from custom_components.crop_steering.calibration import CalibrationStore  # noqa: E402

from .test_sensor_weekly_and_fusion import sensor  # noqa: E402

DOMAIN = "crop_steering"
ROOM = "room:f2_"
A, B, C = "sensor.probe_a", "sensor.probe_b", "sensor.probe_c"
NOW = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.saves = value, 0

    async def async_load(self):
        if isinstance(self.value, Exception):
            raise self.value
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value, self.saves = copy.deepcopy(value), self.saves + 1


class States:
    def __init__(self):
        self.items = {}

    def async_set(self, entity_id, state, attributes=None):
        self.items[entity_id] = SimpleNamespace(
            state=state, attributes=attributes or {}, last_reported=NOW
        )

    def async_remove(self, entity_id):
        self.items.pop(entity_id, None)

    def get(self, entity_id):
        return self.items.get(entity_id)


@pytest.fixture
def journal(monkeypatch):
    seen = []
    monkeypatch.setattr(
        calibration,
        "note",
        lambda hass, room_id, kind, **kw: seen.append((room_id, kind, kw)),
    )
    monkeypatch.setattr(calibration, "_send", lambda hass, signal: seen.append(signal))
    return seen


@pytest.fixture(autouse=True)
def tracking(monkeypatch):
    """The raw-sensor listeners, recorded instead of subscribed."""
    monkeypatch.setattr(
        calibration, "_track", lambda hass, entity_id, on_reading: lambda: None
    )


def rig(value=None, probes=(A, B, C), unit="%"):
    hass = SimpleNamespace(
        states=States(),
        data={
            DOMAIN: {"entry": {"zones": {"1": {"vwc_sensors": list(probes)}}}},
        },
    )
    for probe, reading in zip(probes, ("49", "50", "51")):
        hass.states.async_set(probe, reading, {"unit_of_measurement": unit})
    entry = SimpleNamespace(entry_id="entry", data={"room_prefix": "f2_"}, options={})
    backing = MemoryStore(value)
    store = CalibrationStore(hass, entry, backing, now=lambda: NOW)
    asyncio.run(store.async_init())
    hass.data[DOMAIN].setdefault("_calibration", {})["entry"] = store
    return hass, store, backing


def put(store, **data):
    data.setdefault("entity_id", A)
    if not data.get("preview"):
        data.setdefault("expected_revision", store.document["revision"])
    return asyncio.run(
        store.probe_offset_set(data, {"actor": "manual", "user_id": "u1"})
    )


# ---------------------------------------------------------------- pure


def test_apply_is_offset_only_without_a_curve():
    assert probe_offsets.apply(49.0, 3.0, None) == 52.0
    assert probe_offsets.apply(49.0, 0.0, None) == 49.0


def test_apply_curve_is_a_quadratic_in_the_raw_reading():
    a, b, c = probe_offsets.CURVES["soilless"]
    assert probe_offsets.apply(20.0, 1.5, "soilless") == pytest.approx(
        a + b * 20 + c * 400 + 1.5
    )
    # Close to Topp's cubic where the fit is made: epsilon 20 is 34.5 % moisture.
    assert probe_offsets.apply(20.0, 0.0, "soilless") == pytest.approx(34.5, abs=0.5)
    with pytest.raises(ValueError):
        probe_offsets.apply(20.0, 0.0, "peat")


# ---------------------------------------------------------------- the service


def test_handheld_52_vs_probe_49_sets_plus_3(journal):
    hass, store, backing = rig()
    out = put(store, match_handheld=52.0)
    assert (out["offset"], out["corrected_now"], out["revision"]) == (3.0, 52.0, 1)
    assert backing.saves == 1
    entry = backing.value["probe_user_offsets"][A]
    assert (entry["offset"], entry["curve"], entry["by"]) == (3.0, None, "u1")
    assert entry["at"] == NOW.isoformat()
    assert store.user_corrections() == {A: (3.0, None)}
    # fused_before / fused_after: the zone's median of 49, 50, 51 then of 52, 50, 51.
    assert (out["fused_before"], out["fused_after"]) == (50.0, 51.0)
    published = hass.states.get("sensor.probe_a_corrected")
    assert published.state == "52.0"
    assert published.attributes["source"] == A and published.attributes["raw"] == 49.0
    config = [e for e in journal if isinstance(e, tuple)]
    ((room_id, kind, kw),) = config
    assert (room_id, kind) == (ROOM, "config.changed")
    data = kw["data"]
    assert (data["store"], data["section"]) == ("calibration", "probe_user_offsets")
    assert data["old"] == {} and data["new"] == backing.value["probe_user_offsets"]
    assert data["diff"]


def test_preview_returns_offset_and_corrected_now_without_writing(journal):
    hass, store, backing = rig()
    out = put(store, match_handheld=52.0, preview=True)
    assert out["offset"] == 3.0 and out["corrected_now"] == 52.0
    assert out["preview"] is True and out["diff"]
    assert (out["fused_before"], out["fused_after"]) == (50.0, 51.0)
    assert backing.saves == 0 and store.document["revision"] == 0
    assert store.document["probe_user_offsets"] == {}
    assert hass.states.get("sensor.probe_a_corrected") is None
    assert store._corrected == {}
    assert journal == []


def test_a_write_needs_the_current_revision_and_a_preview_does_not(journal):
    _hass, store, backing = rig()
    with pytest.raises(ValueError, match="changed elsewhere"):
        put(store, offset=1.0, expected_revision=7)
    with pytest.raises(ValueError, match="changed elsewhere"):
        asyncio.run(store.probe_offset_set({"entity_id": A, "offset": 1.0}))
    assert put(store, offset=1.0, expected_revision=7, preview=True)["offset"] == 1.0
    assert backing.saves == 0


def test_no_offsets_publishes_no_corrected_sensors(journal):
    hass, store, _backing = rig()
    store.sync_corrected()
    assert store._corrected == {}
    assert not [e for e in hass.states.items if e.endswith("_corrected")]
    assert store.user_corrections() == {}


def test_clearing_an_offset_removes_its_sensor_and_entry(journal):
    hass, store, backing = rig()
    put(store, offset=2.0)
    assert hass.states.get("sensor.probe_a_corrected") is not None
    out = put(store, offset=0)
    assert out["revision"] == 2
    assert backing.value["probe_user_offsets"] == {}
    assert hass.states.get("sensor.probe_a_corrected") is None
    assert store._corrected == {}


def test_curve_on_a_percent_probe_is_refused(journal):
    _hass, store, backing = rig(unit="%")
    with pytest.raises(ValueError) as refused:
        put(store, curve="rockwool")
    assert str(refused.value) == (
        "This probe already converts to moisture. A curve only applies to raw readings."
    )
    assert backing.saves == 0 and store.document["probe_user_offsets"] == {}


def test_a_curve_on_a_raw_probe_is_applied_and_read_back(journal):
    hass, store, backing = rig(unit="ε")
    hass.states.async_set(A, "20", {"unit_of_measurement": "ε"})
    out = put(store, curve="soilless", offset=1.0)
    assert out["curve"] == "soilless"
    assert out["corrected_now"] == pytest.approx(
        probe_offsets.apply(20.0, 1.0, "soilless"), abs=1e-3
    )
    assert backing.value["probe_user_offsets"][A]["curve"] == "soilless"
    assert store.user_corrections() == {A: (1.0, "soilless")}
    put(store, curve="none")
    assert store.user_corrections() == {A: (1.0, None)}


@pytest.mark.parametrize(
    "data,message",
    [
        ({"offset": 21}, "Offset must be a number from -20 to 20"),
        ({"offset": float("nan")}, "Offset must be a number"),
        ({"offset": True}, "Offset must be a number"),
        ({"match_handheld": 101}, "Handheld must be a number from 0 to 100"),
        ({"curve": "peat"}, "The curve must be one of"),
        ({"offset": -31}, "Offset must be a number"),
        ({"offset": 1, "match_handheld": 50}, "not both"),
        ({}, "Give an offset"),
        ({"entity_id": "sensor.elsewhere", "offset": 1}, "not a moisture probe"),
    ],
)
def test_bad_input_is_refused_and_writes_nothing(journal, data, message):
    _hass, store, backing = rig()
    with pytest.raises(ValueError, match=message):
        put(store, **data)
    assert backing.saves == 0 and store.document["probe_user_offsets"] == {}


def test_a_handheld_far_from_the_probe_or_an_offset_off_the_scale_is_refused(journal):
    hass, store, backing = rig()
    with pytest.raises(ValueError, match="apart"):
        put(store, match_handheld=80.0)
    hass.states.async_set(A, "95", {"unit_of_measurement": "%"})
    with pytest.raises(ValueError, match="outside 0 to 100"):
        put(store, offset=10.0)
    hass.states.async_set(A, "unavailable", {"unit_of_measurement": "%"})
    with pytest.raises(ValueError, match="no reading to match"):
        put(store, match_handheld=50.0)
    assert backing.saves == 0


def test_a_failed_read_back_applies_nothing(journal):
    class Forgetful(MemoryStore):
        async def async_load(self):
            return {"revision": 0, "records": []}

    hass, store, _backing = rig()
    store._store = Forgetful()
    with pytest.raises(ValueError, match="did not read back"):
        put(store, offset=1.0)
    assert store.document["revision"] == 0 and store.user_corrections() == {}
    assert hass.states.get("sensor.probe_a_corrected") is None


def test_an_unreadable_store_refuses_saves_and_applies_nothing(journal):
    _hass, store, backing = rig(value=OSError("disk"))
    assert store.error and "has not been overwritten" in store.error
    with pytest.raises(ValueError, match="has not been overwritten"):
        put(store, offset=1.0)
    assert backing.saves == 0 and store.user_corrections() == {}


def test_stored_offsets_that_are_not_understood_are_not_loaded_half_way(journal):
    for bad in ({"sensor.a": 3}, [1], {"sensor.a": {"offset": 99}}):
        _hass, store, _backing = rig(
            value={"revision": 2, "records": [], "probe_user_offsets": bad}
        )
        assert store.error and store.user_corrections() == {}


def test_an_old_store_without_the_key_has_none_and_a_calibration_keeps_the_key(journal):
    _hass, store, backing = rig(value={"revision": 2, "records": []})
    assert store.error is None and store.document["probe_user_offsets"] == {}
    put(store, offset=2.0)
    record = {
        "expected_revision": store.document["revision"],
        "probe": "feed_ph",
        "points": [
            {"reference": 7.0, "reading": 7.0},
            {"reference": 4.0, "reading": 4.0},
        ],
    }
    asyncio.run(store.record(record))
    assert backing.value["probe_user_offsets"][A]["offset"] == 2.0
    assert backing.value["revision"] == 4


# ---------------------------------------------------------------- the zone sensor


def zone_sensor(values, fixes=None):
    states = {
        pid: SimpleNamespace(state=str(v), attributes={"unit_of_measurement": "%"})
        for pid, v in values.items()
    }
    entity = sensor(states)
    manager = SimpleNamespace(user_corrections=lambda: dict(fixes or {}))
    entity.hass.data = {DOMAIN: {"_calibration": {"entry": manager}}}
    entity._zones_config = {1: {"vwc_sensors": list(values)}}
    return entity, states, manager


def test_fused_value_moves_and_no_probe_alert_attribute_fires():
    entity, _states, _manager = zone_sensor({A: 49, B: 50, C: 51}, {A: (3.0, None)})
    assert entity._get_zone_vwc(1) == 51.0  # median of 52, 50, 51
    assert entity._fusion["excluded"] == {}
    assert {q["quality"] for q in entity._fusion["quality"].values()} == {"good"}
    plain, _s, _m = zone_sensor({A: 49, B: 50, C: 51})
    assert plain._get_zone_vwc(1) == 50.0
    assert plain._fusion["excluded"] == {}


def test_no_offsets_leaves_every_reading_as_it_was():
    entity, _states, _manager = zone_sensor({A: 49, B: 50, C: 51})
    assert entity._get_zone_vwc(1) == 50.0
    assert entity._applied_fix == {A: (0.0, None), B: (0.0, None), C: (0.0, None)}
    assert entity._probe_offsets == {A: -1.0, B: 0.0, C: 1.0}


def test_a_change_moves_what_fusion_learned_so_a_missing_probe_does_not_step():
    fixes = {}
    entity, states, _manager = zone_sensor({A: 49, B: 50, C: 51}, fixes)
    assert entity._get_zone_vwc(1) == 50.0
    assert entity._probe_offsets == {A: -1.0, B: 0.0, C: 1.0}
    # With every probe in, fusion learns the probes afresh against the corrected readings.
    fixes[A] = (3.0, None)  # the grower matches a handheld
    assert entity._get_zone_vwc(1) == 51.0
    assert entity._probe_offsets == {A: 1.0, B: -1.0, C: 0.0}
    # A change made while a probe is missing moves the learned offset by the same step, so the zone
    # reads what the probes that are in say of it and does not step.
    states[C].state = "unavailable"
    assert entity._get_zone_vwc(1) == 51.0  # A 52 - 1, B 50 + 1: the mean of 51 and 51
    fixes[A] = (5.0, None)
    assert entity._get_zone_vwc(1) == 51.0  # A 54 - 3, B 50 + 1: no step
    assert entity._probe_offsets[A] == pytest.approx(3.0)


def test_a_curve_probe_is_read_through_its_curve_not_its_unit():
    values = {A: 20, B: 38, C: 39}
    entity, states, _manager = zone_sensor(values, {A: (0.0, "soilless")})
    for state in states.values():
        state.attributes = {"unit_of_measurement": "ε" if state is states[A] else "%"}
    expected = round(probe_offsets.apply(20.0, 0.0, "soilless"), 2)
    assert entity._get_zone_vwc(1) == sorted([expected, 38.0, 39.0])[1]
