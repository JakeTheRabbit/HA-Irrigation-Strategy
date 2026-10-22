"""Pump prime and calibration (G3), integration side: the pump catalogue, the interlock blockers, a timed
prime or calibrate request for the controller, a pump stop that pre-empts it, the runner's ran_s copied
into the calibration session, and a commit that stores the pump's calibrated flow (and writes its flow
number). A calibration run is never drawn from stock, and a pump stored before any of this loads as it was.
"""

import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest

from . import ha_stubs
from .test_dosing import BATCH, KNOWN, PUMP

ha_stubs.install()

from custom_components.crop_steering import (  # noqa: E402
    calibration,
    dosing,
    dosing_api,
    stock_api,
)
from custom_components.crop_steering.const import DOMAIN  # noqa: E402

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
STATUS = "sensor.crop_steering_f2_dosing"
HEARTBEAT = "sensor.crop_steering_f2_ai_heartbeat"
FLOW = PUMP["flow_entity"]  # number.doser_balance_flow
WHO = {"actor": "manual", "user_id": "u1", "client": None}


class MemoryStore:
    def __init__(self, value=None):
        self.value, self.saves = value, 0

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value, self.saves = copy.deepcopy(value), self.saves + 1


class Services(ha_stubs.FakeServices):
    """number/input_number set_value lands in the state, like Home Assistant's own."""

    def __init__(self, states, sticky=False):
        super().__init__()
        self.states, self.sticky = states, sticky

    async def async_call(self, domain, service, data, blocking=False):
        await super().async_call(domain, service, data, blocking)
        if service == "set_value" and not self.sticky:
            self.states.set(data["entity_id"], str(data["value"]))


class Rig:
    """Room f2_ with one dosing pump (Balance), its calibration store and a fresh controller."""

    def __init__(self, monkeypatch, stored=None, sticky=False):
        self.clock = {"at": NOW}
        monkeypatch.setattr(dosing_api, "_now", lambda: self.clock["at"])
        monkeypatch.setattr(dosing_api, "_today", lambda: self.clock["at"].date())
        monkeypatch.setattr(calibration, "_later", lambda hass, s, a: lambda: None)
        self.events = []
        monkeypatch.setattr(
            dosing_api,
            "note",
            lambda hass, room_id, kind, **kw: self.events.append((kind, kw)),
        )
        self.hass = ha_stubs.FakeHass(states={e: "off" for e in KNOWN})
        self.hass.states.set(FLOW, "11.06")
        self.hass.states.set(HEARTBEAT, "ok", last_updated=NOW - timedelta(seconds=30))
        self.hass.services = Services(self.hass.states, sticky)
        self.hass.tasks = []
        self.hass.async_create_task = self.hass.tasks.append
        self.hass.data = {DOMAIN: {}}
        self.entry = ha_stubs.FakeEntry(
            data={"room_prefix": "f2_", "room_slug": "f2"}, entry_id="e2"
        )
        self.cal = calibration.CalibrationStore(
            self.hass, self.entry, MemoryStore(), now=lambda: self.clock["at"]
        )
        asyncio.run(self.cal.async_init())
        self.hass.data[DOMAIN]["_calibration"] = {"e2": self.cal}
        value = (
            stored
            if stored is not None
            else {
                "revision": 1,
                "pumps": [copy.deepcopy(PUMP)],
                "batch": copy.deepcopy(BATCH),
            }
        )
        self.backing = MemoryStore(value)
        self.dosing = dosing_api.DosingStore(self.hass, self.entry, self.backing)
        asyncio.run(self.dosing.async_init())
        self.hass.data[DOMAIN]["_dosing"] = {"e2": self.dosing}

    def run(self, coro):
        return asyncio.run(coro)

    def report(self, request_id, ran_s, result="done"):
        """The controller publishes what it did with a timed request (Task 20's handled_result)."""
        self.hass.states.set(
            STATUS,
            "idle",
            {
                "handled": request_id,
                "handled_result": {
                    "id": request_id,
                    "action": "calibrate",
                    "pump": "balance",
                    "ran_s": ran_s,
                    "result": result,
                },
            },
        )
        self.dosing._status_changed(self.hass.states.get(STATUS))
        while self.hass.tasks:
            asyncio.run(self.hass.tasks.pop(0))

    def calibrate(self, seconds=30):
        return self.run(self.dosing.pump_calibrate("balance", seconds, "Alex", WHO))

    def commit(self, session_id, measured_ml):
        return self.run(
            self.dosing.pump_calibration_commit(session_id, measured_ml, WHO)
        )


def _pump(rig):
    return rig.dosing.data["pumps"][0]


def test_30s_and_150ml_gives_300_ml_min(monkeypatch):
    rig = Rig(monkeypatch, sticky=True)
    rig.hass.states.set(FLOW, "11.06")
    started = rig.calibrate(30)
    assert started["outcome"] == "requested" and started["blockers"] == []
    request = rig.dosing.data["request"]
    assert (request["action"], request["pump"], request["seconds"]) == (
        "calibrate",
        "balance",
        30,
    )
    assert request["id"] == started["request_id"]
    rig.report(request["id"], 30)
    out = rig.commit(started["session_id"], 150)
    assert out["ml_min"] == 300 and out["previous_ml_min"] is None
    pump = _pump(rig)
    assert pump["calibrated_ml_min"] == 300
    [record] = pump["calibrations"]
    assert {k: record[k] for k in ("pump", "run_s", "measured_ml", "ml_min")} == {
        "pump": "balance",
        "run_s": 30,
        "measured_ml": 150,
        "ml_min": 300,
    }
    assert record["previous_ml_min"] is None and record["at"] == NOW.isoformat()
    assert rig.backing.value["pumps"][0]["calibrated_ml_min"] == 300  # stored
    kinds = [kind for kind, _ in rig.events]
    assert kinds == ["pump.calibrated"]
    data = rig.events[0][1]["data"]
    assert (data["ml_min"], data["previous_ml_min"]) == (300, None)
    # The session is over; the next calibration reports the one it replaces.
    with pytest.raises(ValueError, match="expired"):
        rig.commit(started["session_id"], 150)
    again = rig.calibrate(30)
    rig.report(rig.dosing.data["request"]["id"], 30)
    assert rig.commit(again["session_id"], 140)["previous_ml_min"] == 300
    assert [c["ml_min"] for c in _pump(rig)["calibrations"]] == [280, 300]
    # The room's pump sensors follow the store.
    sensors = rig.dosing.pump_sensors()
    flow = sensors["sensor.crop_steering_f2_dosing_pump_balance_ml_min"]
    assert flow[0] == 280 and flow[1]["unit_of_measurement"] == "mL/min"
    last = sensors["sensor.crop_steering_f2_dosing_pump_balance_last_calibrated"]
    assert last[0] == NOW.isoformat() and last[1]["device_class"] == "timestamp"


def test_commit_before_the_run_is_reported_is_refused(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    with pytest.raises(ValueError, match="not been reported"):
        rig.commit(started["session_id"], 150)
    assert "calibrated_ml_min" not in _pump(rig) and rig.events == []
    # A run the controller refused never gives a flow.
    rig.report(rig.dosing.data["request"]["id"], 0, "refused: a shot is in flight")
    with pytest.raises(ValueError, match="a shot is in flight"):
        rig.commit(started["session_id"], 150)
    assert "calibrated_ml_min" not in _pump(rig)


def test_prime_without_a_power_switch_names_the_blocker(monkeypatch):
    rig = Rig(monkeypatch)
    rig.dosing.data["pumps"][0]["power_entity"] = None
    out = rig.run(rig.dosing.pump_prime("balance", 10, "Alex", WHO))
    assert out["outcome"] == "refused" and out["request_id"] is None
    assert [b["code"] for b in out["blockers"]] == ["no_power_entity"]
    assert "power switch" in out["blockers"][0]["message"]
    assert rig.dosing.data["request"] is None
    # A power switch Home Assistant does not know is no switch to time a run with.
    rig.dosing.data["pumps"][0]["power_entity"] = "switch.gone"
    codes = [b["code"] for b in rig.dosing.precheck("balance")["blockers"]]
    assert codes == ["no_power_entity"]


def test_precheck_lists_every_blocker_and_writes_nothing(monkeypatch):
    rig = Rig(monkeypatch)
    assert rig.dosing.precheck("balance") == {"ok": True, "blockers": []}
    rig.dosing.data["pumps"][0]["power_entity"] = None
    rig.hass.states.set(STATUS, "batch")
    rig.hass.states.set(BATCH["mix_pump"], "on")
    rig.hass.states.set(BATCH["fill_valve"], "on")
    rig.cal.sessions["s1"] = {
        "id": "s1",
        "probe": "feed_ph",
        "active": NOW,
        "unsub": None,
    }
    rig.cal.sessions["s2"] = {"id": "s2", "pump": "bloom", "active": NOW, "unsub": None}
    rig.hass.states.set(HEARTBEAT, "ok", last_updated=NOW - timedelta(minutes=11))
    saves = rig.backing.saves
    out = rig.dosing.precheck("balance")
    assert out["ok"] is False
    assert {b["code"]: b["message"] for b in out["blockers"]} == dosing.BLOCKERS
    assert [b["code"] for b in out["blockers"]] == list(dosing.BLOCKERS)
    assert dosing.BLOCKERS["mix_pump_on"] == "Mix pump is on"
    assert rig.backing.saves == saves and rig.dosing.data["request"] is None
    with pytest.raises(ValueError, match="unknown pump"):
        rig.dosing.precheck("nope")


def test_prime_over_30_seconds_is_refused_by_schema(monkeypatch):
    rig = Rig(monkeypatch)
    for seconds in (0, 31, 120, True, "ten"):
        with pytest.raises(dosing.DosingError, match="1 to 30"):
            dosing.check_timed(rig.dosing.data, "prime", "balance", seconds)
    with pytest.raises(dosing.DosingError, match="5 to 120"):
        dosing.check_timed(rig.dosing.data, "calibrate", "balance", 4)
    assert dosing.check_timed(rig.dosing.data, "prime", "balance", 30) == (
        "balance",
        30,
    )
    with pytest.raises(dosing.DosingError):
        rig.run(rig.dosing.pump_prime("balance", 31, "Alex", WHO))
    assert rig.dosing.data["request"] is None
    # The service schema caps it as well: seconds 1..30.
    assert dosing_api.PRIME_SECONDS == (1, 30)
    assert dosing_api.CALIBRATE_SECONDS == (5, 120)


def test_pump_stop_replaces_a_pending_prime_request(monkeypatch):
    rig = Rig(monkeypatch)
    prime = rig.run(rig.dosing.pump_prime("balance", 20, "Alex", WHO))
    assert prime["outcome"] == "requested"
    assert rig.dosing.pending()
    # A second prime waits for the first.
    with pytest.raises(ValueError, match="still waiting"):
        rig.run(rig.dosing.pump_prime("balance", 20, "Alex", WHO))
    stop = rig.run(rig.dosing.pump_stop("balance", "Staff"))
    request = rig.dosing.data["request"]
    assert request["id"] == stop["request_id"] != prime["request_id"]
    assert (request["action"], request["pump"], request["by"]) == (
        "stop_pump",
        "balance",
        "Staff",
    )
    assert rig.backing.value["request"] == request
    assert stop["replaced"] == {
        "id": prime["request_id"],
        "action": "prime",
        "pump": "balance",
    }
    # The prime never ran: it no longer holds the room, and no report of it is awaited.
    assert rig.dosing.pump_hold() is None and rig.dosing._primes == {}
    with pytest.raises(ValueError, match="unknown pump"):
        rig.run(rig.dosing.pump_stop("nope", "Staff"))
    # A waiting dose or batch, which only an administrator could ask for: a non-administrator's pump
    # stop is refused and changes nothing; an administrator's replaces it and says so.
    for action in ("dose", "batch"):
        rig.dosing.data["request"] = {
            "id": "b1",
            "action": action,
            "pump": "balance" if action == "dose" else None,
            "ml": 5 if action == "dose" else None,
            "at": NOW.isoformat(),
            "by": "Alex",
        }
        with pytest.raises(ValueError) as refused:
            rig.run(rig.dosing.pump_stop("balance", "Staff", admin=False))
        assert str(refused.value) == (
            "A dose or batch is waiting — an admin, or the room Stop, can cancel it."
        )
        assert rig.dosing.data["request"]["id"] == "b1"
    stop = rig.run(rig.dosing.pump_stop("balance", "Alex", admin=True))
    assert stop["replaced"]["action"] == "batch"
    assert rig.dosing.data["request"]["action"] == "stop_pump"
    # A waiting room stop already stops this pump: it is kept, and is the answer.
    rig.dosing.data["request"] = {
        **rig.dosing.data["request"],
        "id": "s1",
        "action": "stop",
        "pump": None,
    }
    assert rig.run(rig.dosing.pump_stop("balance", "Staff")) == {
        "request_id": "s1",
        "replaced": None,
    }
    assert rig.dosing.data["request"]["id"] == "s1"


def test_a_staff_stop_with_another_pumps_prime_waiting_becomes_a_room_stop(
    monkeypatch,
):
    rig = _bloom_rig(monkeypatch)
    prime = rig.run(rig.dosing.pump_prime("bloom", 20, "Alex", WHO))
    waiting = copy.deepcopy(rig.dosing.data["request"])
    stop = rig.run(rig.dosing.pump_stop("balance", "Staff", admin=False))
    assert stop["replaced"] == {"upgraded_to": "stop", "was": waiting}
    request = rig.dosing.data["request"]
    assert request["id"] == stop["request_id"]
    assert (request["action"], request["pump"], request["by"]) == (
        "stop",
        None,
        "Staff",
    )
    # Bookkeeping as a room stop: the bloom prime never runs, so its hold and report go.
    assert prime["request_id"] not in rig.dosing._primes
    assert rig.dosing.pump_hold() is None


def test_two_pumps_stops_in_a_row_stop_both_pumps(monkeypatch):
    rig = _bloom_rig(monkeypatch)
    first = rig.run(rig.dosing.pump_stop("balance", "Staff", admin=False))
    assert first["replaced"] is None
    assert rig.dosing.data["request"]["action"] == "stop_pump"
    second = rig.run(rig.dosing.pump_stop("bloom", "Staff", admin=False))
    assert second["replaced"]["upgraded_to"] == "stop"
    assert second["replaced"]["was"]["pump"] == "balance"
    assert rig.dosing.data["request"]["action"] == "stop"  # stops every pump
    # A third stop finds a room stop waiting: kept, and it is the answer.
    third = rig.run(rig.dosing.pump_stop("balance", "Staff", admin=False))
    assert third == {"request_id": second["request_id"], "replaced": None}


def test_a_pump_stop_never_drops_another_pumps_calibration_session(monkeypatch):
    rig = _bloom_rig(monkeypatch)
    started = rig.calibrate(30)  # balance; its request is taken up by the controller
    _handled(rig)
    rig.run(rig.dosing.pump_stop("bloom", "Staff", admin=False))
    view = rig.dosing.response()["config"]["pumps"][0]["calibration_session"]
    assert view["session_id"] == started["session_id"]


def test_two_primes_hold_the_room_until_the_later_one_ends(monkeypatch):
    rig = _bloom_rig(monkeypatch)
    a = rig.run(rig.dosing.pump_prime("balance", 10, "Alex", WHO))
    _handled(rig)
    rig.clock["at"] = NOW + timedelta(seconds=5)
    b = rig.run(rig.dosing.pump_prime("bloom", 10, "Alex", WHO))
    b_until = rig.clock["at"] + timedelta(seconds=dosing.REQUEST_MAX_AGE_S + 10 + 60)
    # A reports before B is taken up: A's own hold shortens, B's still holds the room.
    rig.clock["at"] = NOW + timedelta(seconds=20)
    rig.report(a["request_id"], 10)
    held = rig.dosing.sensor()[1]["calibrating"]
    assert (held["request_id"], held["until"]) == (b["request_id"], b_until.isoformat())
    rig.clock["at"] = NOW + timedelta(seconds=90)  # A's report + 60 s is over
    assert rig.dosing.sensor()[1]["calibrating"]["request_id"] == b["request_id"]
    _handled(rig)
    assert rig.run(rig.dosing.request({"action": "batch"}, "Alex"))["error"] == (
        dosing_api.HELD
    )
    rig.report(b["request_id"], 10)
    until = rig.clock["at"] + timedelta(seconds=60)
    assert rig.dosing.sensor()[1]["calibrating"]["until"] == until.isoformat()
    rig.clock["at"] = until + timedelta(seconds=1)
    assert "calibrating" not in rig.dosing.sensor()[1]


def test_a_prime_reported_done_without_seconds_or_never_reported_is_dropped(
    monkeypatch,
):
    rig = Rig(monkeypatch)
    prime = rig.run(rig.dosing.pump_prime("balance", 10, "Alex", WHO))
    rig.report(prime["request_id"], None)  # done, no seconds
    assert rig.dosing._primes == {} and rig.events == []
    # One never reported is dropped once no report could still come.
    _handled(rig)
    stale = rig.run(rig.dosing.pump_prime("balance", 10, "Alex", WHO))
    rig.hass.states.set(STATUS, "idle", {"handled": "nothing"})
    rig.clock["at"] = NOW + timedelta(minutes=10)
    _handled(rig)
    rig.dosing._rearm()
    assert stale["request_id"] not in rig.dosing._primes


def test_abandon_releases_a_pump_calibration_hold(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    # Before its run is reported it may still start: abandon refuses, pump_stop is the way.
    with pytest.raises(ValueError, match="stop the pump first"):
        rig.cal.abandon(started["session_id"])
    rig.report(started["request_id"], 30)
    assert rig.cal.abandon(started["session_id"]) == {"abandoned": True}
    assert "calibrating" not in rig.dosing.sensor()[1]
    assert rig.dosing.pump_hold() is None
    with pytest.raises(ValueError, match="expired"):
        rig.commit(started["session_id"], 150)


def test_runner_ran_s_is_copied_into_the_session(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    view = rig.dosing.response()["config"]["pumps"][0]["calibration_session"]
    assert view["session_id"] == started["session_id"] and view["ran_s"] is None
    # Another request's result, or one without a time, changes nothing.
    rig.report("someone-else", 12)
    rig.report(started["request_id"], "soon")
    session = rig.dosing.response()["config"]["pumps"][0]["calibration_session"]
    assert session["ran_s"] is None
    rig.report(started["request_id"], 29.6, "stopped")
    session = rig.dosing.response()["config"]["pumps"][0]["calibration_session"]
    assert (session["ran_s"], session["result"]) == (29.6, "stopped")
    out = rig.commit(started["session_id"], 148)
    assert out["ml_min"] == 300  # 148 mL / 29.6 s x 60
    assert "calibration_session" not in rig.dosing.response()["config"]["pumps"][0]
    # The stored setup never carries the session: it is the response's view only.
    assert "calibration_session" not in rig.backing.value["pumps"][0]
    # A pump session holds room dosing: the descriptor carries `calibrating` for it.
    again = rig.calibrate(30)
    assert rig.dosing.sensor()[1]["calibrating"] == {
        "pump": "balance",
        "session_id": again["session_id"],
        "until": (NOW + calibration.SESSION_IDLE).isoformat(),
    }
    # ...but it is no probe session: the probe wizard refuses it.
    with pytest.raises(ValueError, match="expired"):
        asyncio.run(
            rig.cal.capture(
                rig.dosing.response()["config"]["pumps"][0]["calibration_session"][
                    "session_id"
                ],
                0,
            )
        )


def test_a_prime_reported_done_stamps_primed_at_and_journals(monkeypatch):
    rig = Rig(monkeypatch)
    prime = rig.run(rig.dosing.pump_prime("balance", 10, "Alex", WHO))
    assert "primed_at" not in _pump(rig)
    rig.clock["at"] = NOW + timedelta(seconds=12)
    rig.report(prime["request_id"], 10)
    assert _pump(rig)["primed_at"] == rig.clock["at"].isoformat()
    [(kind, kw)] = rig.events
    assert kind == "pump.primed" and kw["data"]["ran_s"] == 10
    rig.report(prime["request_id"], 10)  # republished: not twice
    assert len(rig.events) == 1


def _bloom_rig(monkeypatch):
    bloom = {
        **PUMP,
        "id": "bloom",
        "name": "Bloom",
        "volume_entity": "number.doser_bloom_volume",
        "start_entity": "button.doser_bloom_start",
        "dosing_entity": "sensor.doser_bloom_status",
        "power_entity": "switch.doser_bloom_power",
        "flow_entity": "number.doser_bloom_flow",
    }
    rig = Rig(
        monkeypatch,
        stored={
            "revision": 1,
            "pumps": [copy.deepcopy(PUMP), bloom],
            "batch": copy.deepcopy(BATCH),
        },
    )
    rig.hass.states.set("switch.doser_bloom_power", "off")
    return rig


def _handled(rig):
    """The controller took the stored request (it no longer waits)."""
    rig.hass.states.set(STATUS, "idle", {"handled": rig.dosing.data["request"]["id"]})


def test_doses_and_batches_wait_while_a_pump_is_calibrated(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    _handled(rig)
    for action, data in (("dose", {"pump": "balance", "ml": 5}), ("batch", {})):
        out = rig.run(rig.dosing.request({"action": action, **data}, "Alex"))
        assert out["request"] is None and out["error"] == dosing_api.HELD
    # A room stop always gets through.
    stop = rig.run(rig.dosing.request({"action": "stop"}, "Alex"))
    assert stop["error"] is None
    rig.report(started["request_id"], 30)
    rig.commit(started["session_id"], 150)
    _handled(rig)  # and the stop
    assert "calibrating" not in rig.dosing.sensor()[1]
    dose = rig.run(
        rig.dosing.request({"action": "dose", "pump": "balance", "ml": 5}, "Alex")
    )
    assert dose["error"] is None


def test_a_prime_holds_room_dosing_for_its_run_and_60_s(monkeypatch):
    rig = Rig(monkeypatch)
    prime = rig.run(rig.dosing.pump_prime("balance", 10, "Alex", WHO))
    held = rig.dosing.sensor()[1]["calibrating"]
    assert (held["pump"], held["request_id"]) == ("balance", prime["request_id"])
    _handled(rig)
    out = rig.run(rig.dosing.request({"action": "batch"}, "Alex"))
    assert out["error"] == dosing_api.HELD
    rig.clock["at"] = NOW + timedelta(seconds=15)
    rig.report(prime["request_id"], 10)
    until = rig.clock["at"] + timedelta(seconds=60)
    assert rig.dosing.sensor()[1]["calibrating"]["until"] == until.isoformat()
    rig.clock["at"] = until + timedelta(seconds=1)
    assert "calibrating" not in rig.dosing.sensor()[1]
    assert rig.run(rig.dosing.request({"action": "batch"}, "Alex"))["error"] is None


def test_another_pumps_open_calibration_is_a_blocker(monkeypatch):
    rig = _bloom_rig(monkeypatch)
    started = rig.calibrate(30)
    _handled(rig)
    out = rig.run(rig.dosing.pump_calibrate("bloom", 30, "Alex", WHO))
    assert out["outcome"] == "refused" and out["session_id"] is None
    assert out["blockers"] == [
        {
            "code": "pump_calibrating",
            "message": "Another pump's calibration is still open",
        }
    ]
    # Balance's session is untouched, and Balance itself may run again.
    view = rig.dosing.response()["config"]["pumps"][0]["calibration_session"]
    assert view["session_id"] == started["session_id"]
    assert rig.dosing.precheck("balance")["ok"] is True


def test_pump_stop_on_a_waiting_calibration_ends_its_session(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    rig.run(rig.dosing.pump_stop("balance", "Staff"))
    assert "calibration_session" not in rig.dosing.response()["config"]["pumps"][0]
    assert rig.cal.pump_run("balance", NOW, NOW + timedelta(seconds=5)) is False
    assert "calibrating" not in rig.dosing.sensor()[1]
    with pytest.raises(ValueError, match="expired"):
        rig.commit(started["session_id"], 150)


def test_a_refusal_without_seconds_shows_on_the_session(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    rig.hass.states.set(
        STATUS,
        "idle",
        {
            "handled": started["request_id"],
            "handled_result": {
                "id": started["request_id"],
                "result": "refused: a shot is in flight",
            },
        },
    )
    rig.dosing._status_changed(rig.hass.states.get(STATUS))
    view = rig.dosing.response()["config"]["pumps"][0]["calibration_session"]
    assert (view["ran_s"], view["result"]) == (0, "refused: a shot is in flight")
    with pytest.raises(ValueError, match="a shot is in flight"):
        rig.commit(started["session_id"], 150)


def test_old_pump_dicts_load_with_no_catalog_fields(monkeypatch):
    rig = Rig(monkeypatch)
    assert rig.dosing.error is None
    assert _pump(rig) == {
        **PUMP,
        "dosing_prefix": "Dosing",
        "restore_volume": True,
        "stock_tank": None,
    }
    for key in ("model", "solution_type", "calibrated_ml_min", "calibrations"):
        assert key not in _pump(rig)
    response = rig.dosing.response()
    assert response["catalog"]["hea_h4"]["nominal_ml_min"]["10"] == 1360
    assert response["catalog"]["peristaltic"] is None
    # A page from before the catalogue saves its pumps: the stored calibration stays.
    started = rig.calibrate(30)
    rig.report(started["request_id"], 30)
    rig.commit(started["session_id"], 150)
    saved = rig.run(
        rig.dosing.save(
            {
                "expected_revision": rig.dosing.data["revision"],
                "pumps": [
                    {
                        **copy.deepcopy(PUMP),
                        "model": {"catalog_id": "hea_p2", "dial": 5},
                    }
                ],
                "batch": copy.deepcopy(BATCH),
            }
        )
    )
    assert saved["error"] is None
    pump = _pump(rig)
    assert pump["calibrated_ml_min"] == 300 and len(pump["calibrations"]) == 1
    assert pump["model"] == {"catalog_id": "hea_p2", "dial": 5}
    assert dosing.nominal_ml_min(pump["model"]) == 340


def test_catalogue_solution_type_and_model_rules():
    exists = KNOWN.__contains__
    [p], _ = dosing.clean(
        [{**PUMP, "solution_type": "ph_down"}], copy.deepcopy(BATCH), exists
    )
    assert (p["solution_type"], p["ph_role"]) == ("ph_down", "ph_down")
    [p], _ = dosing.clean(
        [{**PUMP, "solution_type": "nutrient"}], copy.deepcopy(BATCH), exists
    )
    assert p["solution_type"] == "nutrient" and "ph_role" not in p
    with pytest.raises(dosing.DosingError, match="disagree"):
        dosing.clean(
            [{**PUMP, "solution_type": "nutrient", "ph_role": "ph_up"}],
            copy.deepcopy(BATCH),
            exists,
        )
    for model in ({"catalog_id": "acme"}, {"catalog_id": "hea_a3", "dial": 11}):
        with pytest.raises(dosing.DosingError, match="model"):
            dosing.clean([{**PUMP, "model": model}], copy.deepcopy(BATCH), exists)
    [p], _ = dosing.clean(
        [{**PUMP, "model": {"catalog_id": "other", "dial": None}}],
        copy.deepcopy(BATCH),
        exists,
    )
    assert dosing.nominal_ml_min(p["model"]) is None
    for catalog_id, ten in (
        ("hea_a3", 100),
        ("hea_p1", 340),
        ("hea_p2", 680),
        ("hea_h4", 1360),
    ):
        assert dosing.PUMP_CATALOG[catalog_id]["nominal_ml_min"][10] == ten
    with pytest.raises(dosing.DosingError, match="30"):
        dosing.clean(
            [{**PUMP, "calibrations": [{"ml_min": 1}] * 31}],
            copy.deepcopy(BATCH),
            exists,
        )


def test_a_calibration_run_is_not_drawn_from_stock(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    since = NOW + timedelta(seconds=2)
    end = since + timedelta(seconds=30)
    assert rig.cal.pump_run("balance", since, end) is True
    assert rig.cal.pump_run("other", since, end) is False
    assert (
        rig.cal.pump_run(
            "balance", NOW - timedelta(minutes=5), NOW - timedelta(minutes=4)
        )
        is False
    )
    # The stock store skips that run.
    stock = stock_api.StockStore(rig.hass, rig.entry, MemoryStore())
    asyncio.run(stock.async_init())
    stock.data["tanks"] = [{"id": "balance", "level_l": 10}]
    asyncio.run(
        stock._draw_run(
            {**_pump(rig), "stock_tank": "balance"}, {"since": since, "flow": "5"}, end
        )
    )
    assert stock.data["tanks"][0]["level_l"] == 10 and stock.data.get("history") == []
    # Once reported and committed, a later run of the same pump draws again.
    rig.report(started["request_id"], 30)
    rig.commit(started["session_id"], 150)
    later = end + timedelta(minutes=10)
    assert rig.cal.pump_run("balance", later, later + timedelta(seconds=5)) is False


def test_flow_entity_number_is_written_and_read_back(monkeypatch):
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    rig.report(started["request_id"], 30)
    out = rig.commit(started["session_id"], 150)
    assert out == {"ml_min": 300, "previous_ml_min": None, "flow_entity_written": True}
    assert rig.hass.services.calls[-1] == (
        "number",
        "set_value",
        {"entity_id": FLOW, "value": 5},
    )
    assert rig.hass.states.get(FLOW).state == "5"
    # A number that does not take the value is reported, and the calibration still stands.
    sticky = Rig(monkeypatch, sticky=True)
    started = sticky.calibrate(30)
    sticky.report(started["request_id"], 30)
    out = sticky.commit(started["session_id"], 150)
    assert (
        out["flow_entity_written"] is False
        and _pump(sticky)["calibrated_ml_min"] == 300
    )
    # A flow sensor is only read, never written.
    sensor = Rig(
        monkeypatch,
        stored={
            "revision": 1,
            "pumps": [{**PUMP, "flow_entity": "sensor.doser_balance_status"}],
            "batch": copy.deepcopy(BATCH),
        },
    )
    started = sensor.calibrate(30)
    sensor.report(started["request_id"], 30)
    calls = len(sensor.hass.services.calls)
    assert sensor.commit(started["session_id"], 150)["flow_entity_written"] is False
    assert len(sensor.hass.services.calls) == calls


# ------------------------------------------------------------------ Task 18 review: every open hold published
def test_merge_holds_keeps_one_hold_as_it_always_was_and_publishes_every_kind_together():
    probe = {
        "probe": "feed_ph",
        "session_id": "s1",
        "until": "2026-10-22T09:30:00+00:00",
    }
    pump = {"pump": "balance", "session_id": "s2", "until": "2026-10-22T09:40:00+00:00"}
    prime = {
        "pump": "balance",
        "request_id": "r1",
        "until": "2026-10-22T09:02:10+00:00",
    }
    assert (
        calibration.merge_holds([]) is None
        and calibration.merge_holds([None, None]) is None
    )
    assert (
        calibration.merge_holds([probe]) == probe
        and calibration.merge_holds([None, prime]) == prime
    )
    assert calibration.merge_holds([pump, probe]) == {
        "pump": "balance",
        "session_id": "s2",
        "probe": "feed_ph",
        "until": "2026-10-22T09:40:00+00:00",
        "sessions": [pump, probe],
    }
    merged = calibration.merge_holds([probe, prime])
    assert (merged["probe"], merged["pump"], merged["request_id"]) == (
        "feed_ph",
        "balance",
        "r1",
    )


def test_a_probe_session_opened_after_a_pump_session_is_published_with_it(monkeypatch):
    """Both sessions open: dosing_config `calibrating` carries the probe and the pump together, so the controller's
    source-water gate sees the probe in its buffer (it used to see only the first session).
    """
    rig = Rig(monkeypatch)
    pump = rig.calibrate(30)
    rig.cal.sessions["probe-1"] = {
        "id": "probe-1",
        "probe": "feed_ph",
        "kind": "ph",
        "active": NOW,
        "unsub": None,
    }
    held = rig.dosing.sensor()[1]["calibrating"]
    assert (held["pump"], held["probe"]) == ("balance", "feed_ph")
    assert [s["session_id"] for s in held["sessions"]] == [
        pump["session_id"],
        "probe-1",
    ]
    # the pump's session ends: the probe's alone, exactly as before
    del rig.cal.sessions[pump["session_id"]]
    assert rig.dosing.sensor()[1]["calibrating"] == {
        "probe": "feed_ph",
        "session_id": "probe-1",
        "until": (NOW + calibration.SESSION_IDLE).isoformat(),
    }


def test_reports_are_read_by_their_own_request_id_from_handled_results(monkeypatch):
    """The controller keeps each request's answer (handled_results): a calibration's and a prime's report are
    found by their own ids although a later request's answer stands in handled_result.
    """
    rig = Rig(monkeypatch)
    started = rig.calibrate(30)
    report = {
        "id": started["request_id"],
        "action": "calibrate",
        "pump": "balance",
        "ran_s": 29.6,
        "result": "done",
    }
    rig.hass.states.set(
        STATUS,
        "idle",
        {
            "handled": "a-dose",
            "handled_result": "refused: a pump calibration is running",
            "handled_results": {
                started["request_id"]: report,
                "a-dose": "refused: a pump calibration is running",
            },
        },
    )
    rig.dosing._status_changed(rig.hass.states.get(STATUS))
    session = rig.dosing.response()["config"]["pumps"][0]["calibration_session"]
    assert (session["ran_s"], session["result"]) == (29.6, "done")
    # handled_results present: handled_result is not read for a report (it is the dose's answer here).
    rig.hass.states.set(
        STATUS,
        "idle",
        {
            "handled": "x",
            "handled_result": dict(report, ran_s=5),
            "handled_results": {"x": "stopped"},
        },
    )
    rig.dosing._status_changed(rig.hass.states.get(STATUS))
    assert (
        rig.dosing.response()["config"]["pumps"][0]["calibration_session"]["ran_s"]
        == 29.6
    )
