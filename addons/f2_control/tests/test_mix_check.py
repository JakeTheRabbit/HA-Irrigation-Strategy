"""The mix check (docs/DOSING.md, The mix check): a finished batch's tank is read MIX_SETTLE_S after its
mix stopped, with the room's feed EC and pH probes, against the room's irrigation EC and pH bands.

A reading off its band, or a probe that can't be read, raises CS-808, leaves the batch not marked good
and refuses the next batch an automation asks for; a batch made by hand still runs. It never holds
watering. The probes are read through the device-unit table, so an EC probe in µS/cm gives the verdict
one in mS/cm gives. A room with no tank probe, or no band, has no check and doses as before.

Driven as test_dosing_runner.py drives it: the real Controller, the in-memory Home Assistant and a
fake clock.
"""
from __future__ import annotations

import pytest

import dosing_runner
from test_dosing_runner import BALANCE, BATCH, BLOOM, make_rig

TANK_EC, TANK_PH = "sensor.tank_ec", "sensor.tank_ph"
BANDS = {
    "number.crop_steering_irrigation_ec_min": ("1.5", {}),
    "number.crop_steering_irrigation_ec_max": ("2.5", {}),
    "number.crop_steering_irrigation_ph_min": ("5.6", {}),
    "number.crop_steering_irrigation_ph_max": ("6.4", {}),
}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _room_with_probes(rig, ec=("2.0", "mS/cm"), ph=("5.9", None), bands=True):
    states = dict(BANDS) if bands else {}
    states[TANK_EC] = (ec[0], {"unit_of_measurement": ec[1]} if ec[1] else {})
    states[TANK_PH] = (ph[0], {"unit_of_measurement": ph[1]} if ph[1] else {})
    r = rig(states)
    room = r.c.rooms[0]
    room.feed_ec_sensor, room.feed_ph_sensor = TANK_EC, TANK_PH
    r.config(pumps=(BALANCE, BLOOM), batch=BATCH)
    return r, room


def _batch(r, by="Alex"):
    r.ask("batch", by=by)
    r.poll()
    return r.status()[1]


def _settle(r, seconds=dosing_runner.MIX_SETTLE_S):
    r.clock.sleep(seconds)
    r.runner.poll()
    return r.status()[1]


def test_a_tank_inside_its_bands_is_marked_good_after_the_settle_delay(rig):
    r, _room = _room_with_probes(rig)
    status = _batch(r)
    assert status["handled_result"] == "finished"
    assert status["mix"]["verdict"] is None  # not read while it settles
    assert _settle(r, dosing_runner.MIX_SETTLE_S - 10)["mix"]["verdict"] is None
    status = _settle(r, 10)
    assert status["mix"]["verdict"] == "good" and status["mix"]["ec"] == 2.0 and status["mix"]["ph"] == 5.9
    assert status["history"][0]["mix"] == "good" and r.codes() == []
    # An automation's next batch runs.
    assert _batch(r, by=None)["handled_result"] == "finished"


def test_a_tank_off_its_band_alerts_and_refuses_an_automations_batch_but_never_holds_watering(rig):
    r, room = _room_with_probes(rig)
    _batch(r)
    r.fake.set_state(TANK_EC, "3.1", {"unit_of_measurement": "mS/cm"})
    status = _settle(r)
    assert status["mix"]["verdict"] == "off target" and status["history"][0]["mix"] == "off target"
    assert r.codes() == ["CS-808"]
    alert = r.alert("CS-808")
    assert alert["title"].startswith("The mix of a batch is outside its band")
    assert "its EC reads 3.1, outside the feed EC band of the room (1.5 to 2.5)" in alert["message"]
    assert r.runner.holds(room) is None and r.c._dosing_hold(room) is None
    refused = _batch(r, by=None)["handled_result"]
    assert refused.startswith("refused: the last batch's mix check failed (its EC reads 3.1")
    # A person makes the next batch; once it passes, an automation's batches run again.
    r.fake.set_state(TANK_EC, "2.1", {"unit_of_measurement": "mS/cm"})
    assert _batch(r)["handled_result"] == "finished"
    assert _settle(r)["mix"]["verdict"] == "good"
    assert _batch(r, by=None)["handled_result"] == "finished"


@pytest.mark.parametrize("state", ["unavailable", "unknown", "not a number"])
def test_a_dead_tank_probe_never_stops_irrigation(rig, state):
    r, room = _room_with_probes(rig)
    _batch(r)
    r.fake.set_state(TANK_PH, state, {})
    status = _settle(r)
    assert status["mix"]["verdict"] == "not read" and r.codes() == ["CS-808"]
    assert r.alert("CS-808")["title"].startswith("The mix of a batch was not checked")
    assert f"its pH probe ({TANK_PH}) is not readable (it reads {state})" in r.alert("CS-808")["message"]
    assert r.runner.holds(room) is None and r.c._dosing_hold(room) is None
    assert _batch(r, by=None)["handled_result"].startswith("refused: the last batch's mix check failed")


@pytest.mark.parametrize("reading, ec, verdict", [
    (("2000", "µS/cm"), 2.0, "good"), (("2000", "μS/cm"), 2.0, "good"), (("2", "mS/cm"), 2.0, "good"),
    (("2", "dS/m"), 2.0, "good"), (("3100", "µS/cm"), 3.1, "off target"), (("3.1", "mS/cm"), 3.1, "off target"),
])
def test_a_tank_ec_in_microsiemens_gives_the_verdict_millisiemens_gives(rig, reading, ec, verdict):
    r, _room = _room_with_probes(rig)
    _batch(r)
    r.fake.set_state(TANK_EC, reading[0], {"unit_of_measurement": reading[1]})
    status = _settle(r)
    assert status["mix"]["verdict"] == verdict and status["mix"]["ec"] == pytest.approx(ec)


def test_a_tank_ec_in_ppm_is_not_read_as_millisiemens(rig):
    r, _room = _room_with_probes(rig, ec=("1.2", "ppm"))
    _batch(r)
    assert _settle(r)["mix"]["verdict"] == "not read"
    assert "(it reads 1.2 ppm)" in r.alert("CS-808")["message"]


def test_a_check_still_settling_refuses_an_automations_batch_and_survives_a_restart(rig):
    r, room = _room_with_probes(rig)
    _batch(r)
    assert _batch(r, by=None)["handled_result"] == "refused: the last batch's mix is not checked yet"
    again = r.build(r.runner.path)  # the controller restarted while the tank settles
    r.c.dosing = r.runner = again
    again.recover()
    status = _settle(r)
    assert status["mix"]["verdict"] == "good" and r.saved()["mix"]["verdict"] == "good"


@pytest.mark.parametrize("probes, bands", [(False, True), (True, False)])
def test_a_room_with_no_tank_probe_or_no_band_doses_as_before(rig, probes, bands):
    r, room = _room_with_probes(rig, bands=bands)
    if not probes:
        room.feed_ec_sensor = room.feed_ph_sensor = ""
    status = _batch(r)
    assert status["mix"] is None and "mix" not in status["history"][0]
    assert _settle(r)["mix"] is None and r.codes() == []
    assert _batch(r, by=None)["handled_result"] == "finished"


def test_a_dosing_state_file_from_before_the_mix_check_loads_and_doses(rig):
    r, _room = _room_with_probes(rig)
    r.ask(ml=10)
    r.poll()
    saved = r.saved()
    assert "mix" not in saved  # a dose plans no check: the file is what an older controller wrote
    again = r.build(r.runner.path)
    r.c.dosing = r.runner = again
    assert again.recover()
    assert _batch(r, by=None)["handled_result"] == "finished"


@pytest.mark.parametrize("only_band", [False, True])
def test_a_batch_finished_while_its_band_is_unreadable_is_checked_once_the_band_reads_again(rig, only_band):
    """A band that can't be read when the batch finishes defers its check (never "nothing to check"): the batch is not
    marked good, an automation's next batch is refused, and the check runs once the band reads again. `only_band`: the
    room's one band is the unreadable one, so reading it as no band would plan no check at all."""
    r, room = _room_with_probes(rig)
    if only_band:
        room.feed_ph_sensor = ""
        del r.fake.states["number.crop_steering_irrigation_ec_min"]
    r.fake.set_state("number.crop_steering_irrigation_ec_max", "unavailable")
    status = _batch(r)
    assert status["handled_result"] == "finished" and status["mix"]["verdict"] is None
    assert _settle(r)["mix"]["verdict"] is None and r.codes() == []
    _settle(r, 60)
    assert sum("waits: the room's feed EC or pH band can't be read" in line for line in r.logs) == 1
    assert _batch(r, by=None)["handled_result"] == "refused: the last batch's mix is not checked yet"
    r.fake.set_state("number.crop_steering_irrigation_ec_max", "2.5")
    assert _settle(r, 60)["mix"]["verdict"] == "good"
