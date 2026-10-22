"""The feed pH/EC calibration wizard (G2), integration side: sessions, applied corrections, due dates.

CalibrationStore driven over an in-memory store with a fixed clock and a stand-in for Home Assistant's
state tracker: a session watches the raw probe, a point is captured only when the reading held still,
a status read stores nothing, a commit that passes is applied (the room's corrected sensors and the
engine_config `feed_calibration` follow it), a fail is kept but never applied, a revert puts back the
one before, and a record from before this upgrade never goes due (ruling R6).
"""

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import calibration  # noqa: E402
from custom_components.crop_steering.calibration import (  # noqa: E402
    correct,
    gain_bias,
    stable,
)
from custom_components.crop_steering.dosing_api import DosingStore  # noqa: E402
from custom_components.crop_steering.room import build_engine_config  # noqa: E402

DOMAIN = "crop_steering"
PH, EC, TEMP = "sensor.feed_ph", "sensor.feed_ec", "sensor.tank_temp"
DUE = f"binary_sensor.{DOMAIN}_f2_calibration_due"
START = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.saves = value, 0

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value, self.saves = copy.deepcopy(value), self.saves + 1


class States:
    def __init__(self):
        self.items = {}

    def async_set(self, entity_id, state, attributes=None, at=None):
        self.items[entity_id] = SimpleNamespace(
            state=state,
            attributes=attributes or {},
            last_changed=at,
            last_reported=at,
            last_updated=at,
        )

    def async_remove(self, entity_id):
        self.items.pop(entity_id, None)

    def get(self, entity_id):
        return self.items.get(entity_id)


class Clock:
    def __init__(self):
        self.at = START

    def __call__(self):
        return self.at


class Rig:
    """One room (prefix f2_) with its feed probes, a dosing store, and the raw probe's tracker."""

    def __init__(self, monkeypatch, value=None):
        self.clock = Clock()
        self.hass = SimpleNamespace(states=States(), data={DOMAIN: {}}, _issues={})
        self.entry = SimpleNamespace(
            entry_id="e2", data={"room_prefix": "f2_", "room_slug": "f2"}, options={}
        )
        self.hass.states.async_set(
            f"sensor.{DOMAIN}_f2_engine_config",
            "f2",
            {
                "feed_ph_sensor": PH,
                "feed_ec_sensor": EC,
                "tank_temperature_sensor": TEMP,
            },
        )
        self.listeners, self.timers, self.events = {}, [], []
        monkeypatch.setattr(calibration, "_track", self._track)
        monkeypatch.setattr(calibration, "_later", self._later)
        monkeypatch.setattr(
            calibration,
            "note",
            lambda hass, room_id, kind, **kw: self.events.append((kind, kw)),
        )
        self.backing = MemoryStore(value)
        self.cal = calibration.CalibrationStore(
            self.hass, self.entry, self.backing, now=self.clock
        )
        asyncio.run(self.cal.async_init())
        self.hass.data[DOMAIN]["_calibration"] = {"e2": self.cal}
        self.dosing = DosingStore(self.hass, self.entry, MemoryStore())
        asyncio.run(self.dosing.async_init())
        self.hass.data[DOMAIN]["_dosing"] = {"e2": self.dosing}

    def _track(self, hass, entity_id, on_reading):
        self.listeners[entity_id] = on_reading
        return lambda: self.listeners.pop(entity_id, None)

    def _later(self, hass, seconds, action):
        self.timers.append((seconds, action))
        return lambda: None

    def read(self, entity_id, value, ago=0):
        """The probe reports `value` (it changed `ago` seconds before now)."""
        at = self.clock.at - timedelta(seconds=ago)
        self.hass.states.async_set(entity_id, str(value), {}, at)
        if entity_id in self.listeners:
            self.listeners[entity_id](str(value), at)

    def tick(self, seconds):
        self.clock.at += timedelta(seconds=seconds)

    def start(self, probe="feed_ph", **kw):
        return asyncio.run(self.cal.start(probe, kw.get("solutions"), WHO))

    def capture(self, session_id, point, force=False):
        return asyncio.run(self.cal.capture(session_id, point, force, WHO))

    def commit(self, session_id):
        return asyncio.run(self.cal.commit(session_id, WHO))

    def calibrate(self, high, low, probe="feed_ph", entity=PH):
        """A whole wizard run: steady reading `high` in the first solution, `low` in the second."""
        self.read(entity, high, ago=60)
        session = self.start(probe)["session_id"]
        assert self.capture(session, 0)["stable"] is True
        self.read(entity, low, ago=0)
        self.tick(45)
        assert self.capture(session, 1)["stable"] is True
        return self.commit(session)


WHO = {"actor": "manual", "user_id": "u1", "client": None}


@pytest.fixture
def rig(monkeypatch):
    return Rig(monkeypatch)


def test_known_offset_corrects_within_005_ph(rig):
    out = rig.calibrate(7.12, 4.12)
    # Reads 0.12 high: drifting, and a drifting probe is corrected like a passing one.
    assert (out["verdict"], out["applied"]) == ("drifting", True)
    assert (out["slope_pct"], out["offset"]) == (100.0, 0.12)
    rig.read(PH, 4.12)
    value, attributes = rig.cal.corrected("feed_ph")
    assert abs(value - 4.00) <= 0.05
    assert attributes["source"] == PH and attributes["applied"] is True
    record = rig.cal.document["records"][0]
    assert (record["applied"], record["committed_by"], record["due_days"]) == (
        True,
        "u1",
        30,
    )
    assert record["superseded_by"] is None
    assert [p["reading"] for p in record["points"]] == [7.12, 4.12]
    kinds = [kind for kind, _ in rig.events]
    assert kinds == [
        "calibration.started",
        "calibration.captured",
        "calibration.captured",
        "calibration.committed",
    ]
    committed = rig.events[-1][1]["data"]
    captured = rig.events[1][1]["data"]
    # One event shape for a check, whichever path recorded it (calibration_record journals the same keys).
    assert set(committed) >= {
        "applied",
        "record_id",
        "probe",
        "kind",
        "entity_id",
        "slope_pct",
        "offset",
        "verdict",
        "points",
        "note",
    }
    assert set(captured) >= set(calibration.event_data({}))


def test_unsteady_reading_is_not_captured_without_force(rig):
    rig.read(PH, 7.0, ago=60)
    session = rig.start()["session_id"]
    rig.tick(10)
    rig.read(PH, 7.05)  # moved 0.05 within the last 30 s
    out = rig.capture(session, 0)
    assert out["stable"] is False and out["drift"] == pytest.approx(0.05)
    assert rig.cal.status(session)["points_captured"] == 0
    forced = rig.capture(session, 0, force=True)
    assert forced["stable"] is False
    assert rig.cal.status(session)["points_captured"] == 1
    rig.tick(31)  # held at 7.05 for 31 s: steady now
    out = rig.capture(session, 0)
    assert out["stable"] is True and out["stable_s"] >= 30


def test_status_reports_stability_and_never_stores_a_point(rig):
    rig.read(PH, 7.0, ago=60)
    session = rig.start()
    revision, saves = rig.cal.document["revision"], rig.backing.saves
    for _ in range(3):
        rig.tick(5)
        out = rig.cal.status(session["session_id"])
        assert out["stable"] is True and out["points_captured"] == 0
        assert out["raw"] == 7.0 and out["expires_at"] == session["expires_at"]
    assert (rig.cal.document["revision"], rig.backing.saves) == (revision, saves)
    # A status read is not activity: 30 min after the start the session is gone.
    rig.tick(30 * 60)
    with pytest.raises(ValueError, match="Calibration session expired. Start again."):
        rig.cal.status(session["session_id"])
    with pytest.raises(ValueError, match="Calibration session expired. Start again."):
        rig.cal.status("nope")


def test_a_failed_verdict_is_kept_but_never_applied(rig):
    with pytest.raises(ValueError, match="not applied"):
        rig.calibrate(7.0, 4.6)  # response 80 %: fail
    record = rig.cal.document["records"][0]
    assert (record["verdict"], record["applied"]) == ("fail", False)
    assert rig.cal.corrected("feed_ph") == (
        None,
        {
            "source": PH,
            "applied": False,
            "slope_pct": None,
            "offset": None,
            "gain": None,
            "bias": None,
            "calibrated_at": None,
        },
    )
    assert rig.cal.feed_calibration() == {}
    assert "calibrating" not in rig.dosing.sensor()[1]  # the session ended


def test_a_failed_verdict_leaves_the_applied_calibration_in_force(rig):
    rig.calibrate(7.12, 4.12)
    with pytest.raises(ValueError, match="not applied"):
        rig.calibrate(7.0, 4.6)
    assert rig.cal.feed_calibration()["ph"]["calibrated_at"] == (
        rig.cal.document["records"][1]["at"]
    )


def test_revert_restores_the_raw_value(rig):
    rig.calibrate(7.12, 4.12)
    assert set(rig.cal.feed_calibration()) == {"ph"}
    out = asyncio.run(rig.cal.revert("feed_ph", WHO))
    assert (out["applied"], out["record_id"]) == (False, None)
    value, attributes = rig.cal.corrected("feed_ph")
    assert value is None and attributes["applied"] is False
    assert rig.cal.feed_calibration() == {}
    assert "feed_calibration" not in build_engine_config(
        "f2_", "f2", 1, {}, {}, feed_calibration=rig.cal.feed_calibration()
    )
    assert rig.events[-1][0] == "calibration.reverted"
    with pytest.raises(ValueError, match="put back"):
        asyncio.run(rig.cal.revert("feed_ph", WHO))


def test_revert_puts_back_the_calibration_before(rig):
    rig.calibrate(7.12, 4.12)
    first = rig.cal.document["records"][0]["id"]
    rig.tick(60)
    rig.calibrate(7.05, 4.05)
    second = rig.cal.document["records"][0]
    assert rig.cal.document["records"][1]["superseded_by"] == second["id"]
    out = asyncio.run(rig.cal.revert("feed_ph", WHO))
    assert (out["applied"], out["record_id"], out["reverted_record_id"]) == (
        True,
        first,
        second["id"],
    )
    rig.read(PH, 4.12)
    assert rig.cal.corrected("feed_ph")[0] == pytest.approx(4.0)


def test_gain_bias_reproduce_correct():
    for slope, offset, anchor in ((97.3, 0.12, 7.0), (104.1, -0.07, 0.0)):
        gain, bias = gain_bias(slope, offset, anchor)
        for raw in (0.0, 1.413, 4.12, 6.5, 9.9):
            assert abs(raw * gain + bias - correct(raw, slope, offset, anchor)) < 1e-9


def test_engine_config_carries_only_applied_calibrations(rig):
    plain = build_engine_config("f2_", "f2", 1, {}, {})
    assert build_engine_config("f2_", "f2", 1, {}, {}, feed_calibration={}) == plain
    rig.calibrate(7.12, 4.12)
    published = rig.cal.feed_calibration()
    record = rig.cal.document["records"][0]
    assert published == {
        "ph": {
            "gain": 1.0,
            "bias": pytest.approx(-0.12),
            "calibrated_at": record["at"],
        }
    }
    with_it = build_engine_config("f2_", "f2", 1, {}, {}, feed_calibration=published)
    assert with_it == {**plain, "feed_calibration": published}


def test_a_calibration_of_another_probe_is_not_applied(rig):
    rig.calibrate(7.12, 4.12)
    config = rig.hass.states.get(f"sensor.{DOMAIN}_f2_engine_config")
    rig.hass.states.async_set(
        f"sensor.{DOMAIN}_f2_engine_config",
        "f2",
        {**config.attributes, "feed_ph_sensor": "sensor.new_ph"},
    )
    assert rig.cal.feed_calibration() == {}
    assert rig.cal.corrected("feed_ph")[1]["applied"] is False


def test_a_record_from_before_the_upgrade_never_goes_due(monkeypatch):
    old = {
        "id": "old",
        "probe": "feed_ph",
        "kind": "ph",
        "entity_id": PH,
        "at": (START - timedelta(days=400)).isoformat(),
        "points": [],
        "slope_pct": 99.0,
        "offset": 0.0,
        "verdict": "pass",
        "note": "",
    }
    rig = Rig(monkeypatch, {"revision": 1, "records": [old]})
    rig.cal.publish_due()
    assert rig.hass.states.get(DUE).state == "off"
    assert rig.hass._issues == {}
    assert rig.cal.feed_calibration() == {}  # nothing was ever applied


def test_due_after_30_days_raises_cs_612(rig):
    rig.calibrate(7.12, 4.12)
    rig.cal.publish_due()
    assert rig.hass.states.get(DUE).state == "off"
    rig.tick(30 * 86400)
    rig.cal.publish_due()
    due = rig.hass.states.get(DUE)
    assert due.state == "on" and due.attributes["probes"] == ["feed_ph"]
    issue = rig.hass._issues["calibration_due_f2"]
    assert issue["translation_key"] == "calibration_due"
    assert "feed pH" in issue["translation_placeholders"]["probes"]
    rig.read(PH, 7.12, ago=60)  # calibrated again: the card goes
    rig.calibrate(7.12, 4.12)
    assert rig.hass.states.get(DUE).state == "off"
    assert rig.hass._issues == {}


def test_idle_session_expires_after_30_min(rig):
    rig.read(PH, 7.0, ago=60)
    session = rig.start()["session_id"]
    assert rig.dosing.sensor()[1]["calibrating"]["session_id"] == session
    rig.tick(20 * 60)
    rig.capture(session, 0)  # activity: the 30 min start again
    rig.tick(20 * 60)
    assert rig.cal.status(session)["points_captured"] == 1
    rig.tick(10 * 60 + 1)
    seconds, action = rig.timers[-1]
    assert seconds >= 30 * 60
    action(None)
    assert "calibrating" not in rig.dosing.sensor()[1]
    assert rig.cal.sessions == {}
    with pytest.raises(ValueError, match="expired"):
        rig.capture(session, 1)


def test_start_returns_raw_and_temperature_entities_and_pauses_dosing(rig):
    rig.read(EC, 1.42, ago=60)
    out = rig.start("feed_ec")
    assert out["raw_entity_id"] == EC and out["temperature_entity_id"] == TEMP
    assert out["dosing_paused"] is True
    assert out["solutions"] == [1.413, 2.77]
    assert out["expires_at"] == (START + timedelta(minutes=30)).isoformat()
    assert rig.dosing.sensor()[1]["calibrating"] == {
        "probe": "feed_ec",
        "session_id": out["session_id"],
        "until": out["expires_at"],
    }
    # EC is steady within 1 % of the reading.
    assert stable([(0, 1.40), (20, 1.41), (40, 1.41)], "ec") == (
        True,
        pytest.approx(0.01),
    )
    assert stable([(0, 1.40), (20, 1.43), (40, 1.43)], "ec")[0] is False
    # Without a tank temperature probe there is none to show.
    config = rig.hass.states.get(f"sensor.{DOMAIN}_f2_engine_config")
    rig.hass.states.async_set(
        f"sensor.{DOMAIN}_f2_engine_config",
        "f2",
        {**config.attributes, "tank_temperature_sensor": ""},
    )
    rig.read(PH, 7.0, ago=60)
    out = rig.start("feed_ph")
    assert out["temperature_entity_id"] is None and out["solutions"] == [7.0, 4.0]
    # One session per room: the new one replaced the EC one.
    assert list(rig.cal.sessions) == [out["session_id"]]


def test_a_probe_silent_for_2_min_is_refused(rig):
    rig.read(PH, 7.0, ago=121)
    with pytest.raises(
        ValueError,
        match="No reading from the feed pH probe for 2 min. Check it's plugged in.",
    ):
        rig.start()
    rig.hass.states.async_set(PH, "unavailable", {}, START)
    with pytest.raises(ValueError, match="feed pH probe for 2 min"):
        rig.start()
    assert "calibrating" not in rig.dosing.sensor()[1]


def test_no_session_means_the_dosing_descriptor_as_before(rig):
    state, attributes = rig.dosing.sensor()
    assert set(attributes) == {"pumps", "batch", "profile", "request", "feed"}


def test_calibration_record_keeps_applied_false_and_gains_a_due_date(rig):
    doc = asyncio.run(
        rig.cal.record(
            {
                "expected_revision": 0,
                "probe": "feed_ph",
                "points": [
                    {"reference": 7.0, "reading": 7.05},
                    {"reference": 4.0, "reading": 4.1},
                ],
            },
            WHO,
        )
    )
    record = doc["records"][0]
    assert (record["applied"], record["due_days"], record["committed_by"]) == (
        False,
        30,
        "u1",
    )
    assert rig.cal.feed_calibration() == {}


def test_a_capture_moves_the_dosing_hold_on_with_the_session(rig):
    rig.read(PH, 7.0, ago=60)
    session = rig.start()["session_id"]
    first = rig.dosing.sensor()[1]["calibrating"]["until"]
    rig.tick(10 * 60)
    rig.capture(session, 0)
    until = rig.dosing.sensor()[1]["calibrating"]["until"]
    assert until > first
    assert until == (rig.clock.at + timedelta(minutes=30)).isoformat()
    assert until == rig.cal.status(session)["expires_at"]


def test_a_failed_calibration_does_not_clear_a_due_card(rig):
    rig.calibrate(7.12, 4.12)
    rig.tick(31 * 86400)
    rig.cal.publish_due()
    assert "calibration_due_f2" in rig.hass._issues
    with pytest.raises(ValueError, match="not applied"):
        rig.calibrate(7.0, 4.6)
    assert rig.hass.states.get(DUE).state == "on"
    assert "calibration_due_f2" in rig.hass._issues


def test_abandon_ends_the_session_and_an_unknown_one_is_refused(rig):
    rig.read(PH, 7.0, ago=60)
    session = rig.start()["session_id"]
    assert rig.cal.abandon(session) == {"abandoned": True}
    assert "calibrating" not in rig.dosing.sensor()[1]
    with pytest.raises(ValueError, match="Calibration session expired. Start again."):
        rig.cal.abandon(session)


def test_a_session_commits_once_however_the_calls_race(rig):
    class SlowStore(MemoryStore):
        async def async_save(self, value):
            await asyncio.sleep(0)
            await super().async_save(value)

    rig.cal._store = SlowStore()
    rig.read(PH, 7.12, ago=60)
    session = rig.start()["session_id"]
    rig.capture(session, 0)
    rig.read(PH, 4.12)
    rig.tick(45)
    rig.capture(session, 1)

    async def both():
        return await asyncio.gather(
            rig.cal.commit(session, WHO),
            rig.cal.commit(session, WHO),
            return_exceptions=True,
        )

    first, second = asyncio.run(both())
    assert first["applied"] is True
    assert isinstance(second, ValueError) and "expired" in str(second)
    assert len(rig.cal.document["records"]) == 1
