"""Task 18: the source-water gate, the mix check and pH auto-correct read the CALIBRATED feed pH / EC (ruling R4), and
dosing holds while a calibration is open.

- No calibration applied for a quantity: the raw probe is read, exactly as before (not one extra read).
- Applied, and sensor.crop_steering_<px>feed_<q>_corrected is a live number for the room's own probe: it is used.
- Applied, and the corrected sensor is unavailable, missing, restored after a restart or for another probe: the
  controller computes raw x gain + bias itself. A raw probe with no number is a dead probe, whatever the corrected
  sensor says: the gate's dead-probe hold (fail-closed after its grace) stands.
- The calibration is engine_config's `feed_calibration`, kept in the room's state block `_feed_calibration` so a
  restart with Home Assistant down still corrects. Only a readable descriptor replaces it; one without the key clears
  it.
- dosing_config's `calibrating` (any entry: a feed probe's or a dosing pump's session, or a prime) holds batches and
  pH auto-correct (guard dosing_lockout) and the mix check waits for a probe's. A single dose by hand goes on during a
  feed probe calibration; during a pump's calibration or prime it is refused, as the integration refuses it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import controller
import dosing_runner
from test_dosing_runner import BALANCE, BATCH, BLOOM, CONFIG, _full_batch, make_rig
from test_held_reasons_pinned import FEED_EC, FEED_PH, _room
from test_ph_correct import build, minutes, presses  # noqa: F401  (build: the pH rig fixture)

pytestmark = pytest.mark.usefixtures("settings_built_in")

DESC = "sensor.crop_steering_engine_config"
PH_FIXED = "sensor.crop_steering_feed_ph_corrected"
EC_FIXED = "sensor.crop_steering_feed_ec_corrected"
PH_MIN, PH_MAX = "number.crop_steering_irrigation_ph_min", "number.crop_steering_irrigation_ph_max"
# raw 5.4 reads 5.6 corrected: 5.4 * 1.05 - 0.07
PH_FIX = {"gain": 1.05, "bias": -0.07, "calibrated_at": "2026-10-20T09:00:00+00:00"}
DEAD = "source-water pH probe dead >30min — holding (fail-closed)"
PROBE_HOLD = "feed probe calibration in progress"
PUMP_HOLD = "dosing pump calibration or prime in progress"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _ph_room(raw="5.4"):
    c, fake, room = _room()
    room.feed_ph_sensor = FEED_PH
    fake.set_state(FEED_PH, raw)
    fake.set_state(PH_MIN, "5.5")
    fake.set_state(PH_MAX, "6.5")
    return c, fake, room


def _describe(c, fake, **extra):
    """engine_config republished with `extra` (feed_calibration=None drops the key), then read as the rediscovery
    reads it."""
    attrs = {k: v for k, v in {**fake.states[DESC][1], **extra}.items() if v is not None}
    fake.set_state(DESC, "ok", attrs)
    c._apply_setup_descriptors()


def _fixed(fake, state, entity=PH_FIXED, source=FEED_PH, **attrs):
    fake.set_state(entity, state, {"source": source, "applied": True, "gain": PH_FIX["gain"],
                                   "bias": PH_FIX["bias"], **attrs})


def _reads(c, monkeypatch):
    seen = []
    get = controller.ha_get

    def read(entity, *a, **k):
        seen.append(entity)
        return get(entity, *a, **k)

    monkeypatch.setattr(controller, "ha_get", read)
    return seen


# ------------------------------------------------------------------------------------------------- the gate
def test_no_calibration_reads_raw_as_before(monkeypatch):
    c, fake, room = _ph_room()
    _fixed(fake, "5.6")  # a corrected sensor the descriptor does not apply: never read
    seen = _reads(c, monkeypatch)
    assert c._blocked(room, 1) == "source-water pH 5.40 out of [5.5,6.5]"
    assert c._feed_value(room, "ph") == (5.4, FEED_PH)
    assert PH_FIXED not in seen and EC_FIXED not in seen
    assert getattr(room, "_feed_calibration", {}) == {}
    assert "_feed_calibration" not in (c._read_state_file().get("default") or {})


def test_applied_correction_moves_the_source_water_gate():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    _fixed(fake, "5.6")
    assert c._feed_value(room, "ph") == (5.6, PH_FIXED)
    assert c._blocked(room, 1) is None
    _fixed(fake, "5.3")  # and a corrected reading out of band holds, as a raw one did
    assert c._blocked(room, 1) == "source-water pH 5.30 out of [5.5,6.5]"


def test_an_unavailable_corrected_ph_is_computed_from_raw_and_the_calibration():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    for state in ("unavailable", "unknown"):
        _fixed(fake, state)
        value, entity = c._feed_value(room, "ph")
        assert entity == FEED_PH and value == pytest.approx(5.6)
        assert c._blocked(room, 1) is None
    del fake.states[PH_FIXED]  # missing altogether
    assert c._feed_value(room, "ph")[0] == pytest.approx(5.6)
    assert c._blocked(room, 1) is None


def test_a_restored_corrected_value_is_computed_not_trusted():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    _fixed(fake, "6.0", restored=True)  # the value before a restart, the probe not reported yet
    value, entity = c._feed_value(room, "ph")
    assert entity == FEED_PH and value == pytest.approx(5.6)


def test_applied_calibration_with_a_dead_raw_probe_holds_like_a_dead_probe():
    c, fake, room = _ph_room(raw="unavailable")
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    room._feed_ph_last_good_time = None
    _fixed(fake, "5.9", restored=True)
    assert c._feed_value(room, "ph") == (None, FEED_PH)
    assert c._blocked(room, 1) == DEAD
    _fixed(fake, "5.9")  # even a corrected sensor that still shows a number: no raw number is a dead probe
    assert c._feed_value(room, "ph") == (None, FEED_PH)
    assert c._blocked(room, 1) == DEAD
    # inside the grace a dead probe passes, as before; after it, it holds again
    room._feed_ph_last_good_time = datetime.now() - timedelta(minutes=5)
    assert c._blocked(room, 1) is None
    room._feed_ph_last_good_time = datetime.now() - timedelta(minutes=31)
    assert c._blocked(room, 1) == DEAD


def test_an_unreadable_band_still_holds_with_a_calibration_applied():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    _fixed(fake, "5.6")
    fake.set_state(PH_MIN, "unavailable")
    assert c._blocked(room, 1) == f"source-water pH band unreadable ({PH_MIN}) — holding (fail-closed)"


def test_ha_restart_keeps_the_last_calibration():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    saved = c._read_state_file()["default"]["_feed_calibration"]
    assert saved == {"ph": {"gain": 1.05, "bias": -0.07}}
    # A new controller on the same state.json, with Home Assistant's descriptor not readable yet.
    again, fake2, room2 = _ph_room()
    again._state_path = c._state_path
    again._load_state()
    room2 = again.rooms[0]
    room2.feed_ph_sensor = FEED_PH
    readable = fake2.states[DESC][1]
    fake2.set_state(DESC, "unavailable", {})
    again._apply_setup_descriptors()
    value, entity = again._feed_value(room2, "ph")
    assert entity == FEED_PH and value == pytest.approx(5.6)  # computed, never the raw 5.4
    assert again._blocked(room2, 1) is None
    # a readable descriptor without feed_calibration clears it: raw again
    fake2.set_state(DESC, "ok", readable)
    _describe(again, fake2, feed_calibration=None)
    assert again._feed_value(room2, "ph") == (5.4, FEED_PH)
    assert "_feed_calibration" not in again._read_state_file()["default"]


def test_a_malformed_feed_calibration_keeps_the_last_one():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    _describe(c, fake, feed_calibration={"ph": {"gain": "x", "bias": 0}})
    assert room._feed_calibration == {"ph": {"gain": 1.05, "bias": -0.07}}
    _describe(c, fake, feed_calibration={"ph": {"gain": 0, "bias": 0}})  # no gain is no calibration
    assert room._feed_calibration == {"ph": {"gain": 1.05, "bias": -0.07}}


def test_a_corrected_sensor_for_another_probe_is_computed_not_trusted():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    _fixed(fake, "6.4", source="sensor.old_feed_ph")
    value, entity = c._feed_value(room, "ph")
    assert entity == FEED_PH and value == pytest.approx(5.6)
    _fixed(fake, "6.4", source="sensor.old_feed_ph", applied=False)  # another probe's "not applied" says nothing
    assert c._feed_value(room, "ph")[0] == pytest.approx(5.6)


def test_a_revert_reads_raw_on_the_next_pass_before_the_descriptor_follows():
    """Fix round 1, ruling (1): the corrected sensor of the room's own probe reading `applied: false` wins over the
    cached descriptor at once; a NEW calibration may still wait for the rediscovery."""
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX})
    _fixed(fake, "5.6")
    assert c._blocked(room, 1) is None
    fake.set_state(PH_FIXED, "unknown", {"source": FEED_PH, "applied": False, "gain": None, "bias": None})
    assert room._feed_calibration == {"ph": {"gain": 1.05, "bias": -0.07}}  # the descriptor not read again yet
    assert c._feed_value(room, "ph") == (5.4, FEED_PH)
    assert c._blocked(room, 1) == "source-water pH 5.40 out of [5.5,6.5]"
    fake.set_state(PH_FIXED, "unavailable", {})  # an unavailable sensor is not a revert: computed, as before
    assert c._feed_value(room, "ph")[0] == pytest.approx(5.6)


# ------------------------------------------------------------------------------------------------- calibrating: gate
CAL = "feed probe calibration in progress"


def _ec_room(raw="1.2"):
    c, fake, room = _room()
    room.feed_ec_sensor = FEED_EC
    fake.set_state(FEED_EC, raw)
    fake.set_state("number.crop_steering_irrigation_ec_min", "1.0")
    fake.set_state("number.crop_steering_irrigation_ec_max", "2.0")
    return c, fake, room


def test_the_gate_holds_its_ph_while_the_feed_ph_probe_is_calibrated():
    """Fix round 1, ruling (5): the quantity being calibrated is unreadable: the gate holds at once (no grace, no
    rescue), whatever the buffer reads; the other quantity and a pump's session change nothing."""
    c, fake, room = _ph_room(raw="6.0")  # in band: a pH buffer could read anything
    assert c._blocked(room, 1) is None
    room._feed_calibrating = {"probe": "feed_ph", "session_id": "s", "until": "x"}
    assert c._blocked(room, 1) == CAL
    assert c._read_feed_ph(room) is None
    room._feed_calibrating = {"probe": "feed_ec", "session_id": "s", "until": "x"}
    assert c._blocked(room, 1) is None
    room._feed_calibrating = {"pump": "balance", "session_id": "s", "until": "x"}
    assert c._blocked(room, 1) is None
    room._feed_calibrating = None
    assert c._blocked(room, 1) is None


def test_the_gate_holds_its_ec_while_the_feed_ec_probe_is_calibrated():
    c, fake, room = _ec_room(raw="1.413")  # the EC buffer, inside the 1.0-2.0 band: never passes
    assert c._blocked(room, 1) is None
    room._feed_calibrating = {"probe": "feed_ec", "session_id": "s", "until": "x"}
    assert c._blocked(room, 1) == CAL
    import gate_report

    assert gate_report.first_hold(gate_report.report(c, room, 1)) == CAL  # the gate list says the same
    room._feed_calibrating = "something unreadable"  # an entry that can't be read holds both halves
    assert c._blocked(room, 1) == CAL


def test_the_runner_hands_the_calibrating_entry_to_the_gate(rig):
    r = rig()
    r.config()
    room = r.c.rooms[0]
    _calibrating(r, PROBE)
    r.poll()
    assert room._feed_calibrating == PROBE
    state, attributes = r.fake.states[CONFIG][:2]
    r.fake.set_state(CONFIG, "unavailable", {})  # can't be read: the last one stands (fail-closed)
    r.poll()
    assert room._feed_calibrating == PROBE
    r.fake.set_state(CONFIG, state, {k: v for k, v in attributes.items() if k != "calibrating"})
    r.poll()
    assert room._feed_calibrating is None


def test_the_ec_gate_reads_the_corrected_feed_ec():
    c, fake, room = _room()
    room.feed_ec_sensor = FEED_EC
    fake.set_state(FEED_EC, "1.6")
    fake.set_state("number.crop_steering_irrigation_ec_min", "0")
    fake.set_state("number.crop_steering_irrigation_ec_max", "1.5")
    assert c._blocked(room, 1) == "source-water EC 1.6 out of [0,1.5]"
    _describe(c, fake, feed_calibration={"ec": {"gain": 0.9, "bias": 0.0, "calibrated_at": "x"}})
    assert c._feed_value(room, "ec")[0] == pytest.approx(1.44)  # computed: no corrected sensor yet
    assert c._blocked(room, 1) is None
    _fixed(fake, "1.7", entity=EC_FIXED, source=FEED_EC)
    assert c._feed_value(room, "ec") == (1.7, EC_FIXED)
    assert c._blocked(room, 1) == "source-water EC 1.7 out of [0,1.5]"


# ------------------------------------------------------------------------------------------------- the runner
# Each test drives one rig: two rigs in one test share one tmp_path (dosing_state.json and the journal outbox).
def test_mix_check_and_ph_autocorrect_use_the_corrected_value(build):  # noqa: F811
    """pH auto-correct: the raw tank reads 6.0, inside 5.8-6.5; corrected it is 5.6, so it is corrected up to 5.9."""
    r = build(ph="6.0")
    r.c.rooms[0]._feed_calibration = {"ph": {"gain": 1.0, "bias": -0.4}}
    r.moves = [0.3]
    minutes(r, 10)
    assert presses(r) == ["button.balance_start"]
    entry = r.status()[1]["history"][0]
    assert entry["kind"] == "correct" and entry["result"] == "finished: the tank is inside its band"
    assert entry["ph"] == [pytest.approx(5.6), pytest.approx(5.9)]


def _mix_rig(rig, ec):
    m = rig({"number.crop_steering_irrigation_ec_min": ("1.5", {}),
             "number.crop_steering_irrigation_ec_max": ("2.5", {}),
             "sensor.tank_ec": (ec, {"unit_of_measurement": "mS/cm"})})
    m.c.rooms[0].feed_ec_sensor = "sensor.tank_ec"
    m.config(pumps=(BALANCE, BLOOM), batch=BATCH)
    m.ask("batch")
    m.poll()
    return m


def test_the_mix_check_uses_the_corrected_value(rig):
    """The raw tank EC 2.3 is inside 1.5-2.5; corrected it is 2.8, which is not."""
    m = _mix_rig(rig, "2.3")
    m.c.rooms[0]._feed_calibration = {"ec": {"gain": 1.0, "bias": 0.5}}
    m.clock.sleep(dosing_runner.MIX_SETTLE_S)
    m.runner.poll()
    mix = m.status()[1]["mix"]
    assert mix["verdict"] == "off target" and mix["ec"] == pytest.approx(2.8)


def _calibrating(r, entry):
    state, attributes = r.fake.states[CONFIG][:2]
    r.fake.set_state(CONFIG, state, {**attributes, "calibrating": entry})


def _intents(r):
    return [(e["kind"], e["data"]) for e in r.c.journal.pending() if e["kind"].startswith("intent.")]


PROBE = {"probe": "feed_ph", "session_id": "01JC0000000000000000000000", "until": "2026-10-23T10:00:00+00:00"}
PUMP = {"pump": "balance", "session_id": "01JC0000000000000000000001", "until": "2026-10-23T10:00:00+00:00"}
PRIME = {"pump": "balance", "request_id": "r1", "until": "2026-10-23T10:00:00+00:00"}
SESSIONS = [(PROBE, PROBE_HOLD), (PUMP, PUMP_HOLD), (PRIME, PUMP_HOLD)]
IDS = ["probe", "pump_calibration", "prime"]


@pytest.mark.parametrize("entry,words", SESSIONS, ids=IDS)
def test_an_open_calibration_session_holds_batches_and_ph_correct(entry, words, rig):
    r = rig()
    _full_batch(r)
    _calibrating(r, entry)
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == f"refused: {words}"
    assert r.actions() == []
    assert _intents(r) == [("intent.refused", {"guard": "dosing_lockout", "reason": words})]


@pytest.mark.parametrize("entry,words", SESSIONS, ids=IDS)
def test_an_open_calibration_session_holds_ph_correct(entry, words, build):  # noqa: F811
    p = build(ph="5.4")
    _calibrating(p, entry)
    minutes(p, 10)
    assert presses(p) == [] and p.codes() == []  # it waits: no dose, no alert
    assert _intents(p) == [("intent.held", {"guard": "dosing_lockout", "reason": words})]
    _calibrating(p, None)  # the session ends: the tank is corrected once it has read steady again
    p.moves = [0.6]
    minutes(p, 10)
    assert presses(p) == ["button.balance_start"]


def test_a_single_dose_goes_on_during_a_probe_calibration(rig):
    r = rig()
    r.config()
    _calibrating(r, PROBE)
    r.ask(ml=50)
    r.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert _intents(r) == []


@pytest.mark.parametrize("entry", [PUMP, PRIME], ids=IDS[1:])
def test_a_single_dose_is_refused_while_a_pump_is_calibrated_or_primed(entry, rig):
    r = rig()
    r.config()
    _calibrating(r, entry)
    r.ask(ml=50)
    r.poll()
    assert r.status()[1]["handled_result"] == f"refused: {PUMP_HOLD}"
    assert r.actions() == []
    assert _intents(r) == [("intent.refused", {"guard": "dosing_lockout", "reason": PUMP_HOLD})]


def test_the_mix_check_waits_while_a_feed_probe_is_calibrated(rig):
    m = _mix_rig(rig, "2.0")
    _calibrating(m, PROBE)
    m.fake.set_state("sensor.tank_ec", "1.413", {"unit_of_measurement": "mS/cm"})  # the probe in its buffer
    m.clock.sleep(dosing_runner.MIX_SETTLE_S)
    m.runner.poll()
    m.runner.poll()
    assert m.status()[1]["mix"]["verdict"] is None  # never judged on a buffer
    _calibrating(m, None)
    m.fake.set_state("sensor.tank_ec", "3.1", {"unit_of_measurement": "mS/cm"})
    m.runner.poll()
    m.runner.poll()
    assert m.status()[1]["mix"]["verdict"] == "off target"


@pytest.mark.parametrize("absent", ["no key", None, {}])
def test_no_calibrating_attribute_means_dosing_as_before(absent, rig):
    r = rig()
    _full_batch(r)
    if absent != "no key":
        _calibrating(r, absent)
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "finished"
    r.ask(ml=50)
    r.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert _intents(r) == []


def test_no_calibrating_attribute_means_ph_correct_as_before(build):  # noqa: F811
    p = build(ph="5.6")
    p.moves = [0.3]
    minutes(p, 7)
    assert presses(p) == ["button.balance_start"]


def test_the_held_words_are_pinned():
    import guards

    assert guards.CALIBRATING_PROBE == PROBE_HOLD
    assert guards.CALIBRATING_PUMP == PUMP_HOLD
    assert controller.FEED_CALIBRATING == PROBE_HOLD  # the source-water gate's hold
    assert [(g.key, g.guard, g.code) for g in guards.CALIBRATING] == [("calibrating", "dosing_lockout", None)]


def test_the_state_file_round_trips_the_calibration():
    c, fake, room = _ph_room()
    _describe(c, fake, feed_calibration={"ph": PH_FIX, "ec": {"gain": 0.98, "bias": 0.01}})
    with open(c._state_path, encoding="utf-8") as fh:
        block = json.load(fh)["default"]
    assert block["_feed_calibration"] == {"ph": {"gain": 1.05, "bias": -0.07}, "ec": {"gain": 0.98, "bias": 0.01}}
