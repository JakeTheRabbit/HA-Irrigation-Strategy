"""The batch tank's refill reminder (docs/DOSING.md, Refill reminder; CS-906): nothing refills a batch
tank by itself, so once its level reads at or under the room's reminder level on three reads a minute
apart, a person is told to refill it; again each day it stays low, a restart included; taken down once
it reads 5 points above. Never while a dose or batch runs in the room, never from a level that reads
nothing, and never for a setup without the reminder (every one from before it).

Driven as test_dosing_runner.py drives the runner: the real Controller, the in-memory Home Assistant
and a fake clock.
"""
from __future__ import annotations

import pytest

import dosing_runner
from test_dosing_runner import BATCH, make_rig

LEVEL = "sensor.tank_level"
NOTE = "f2_dosing_default_906_remind"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _reminding(rig, pct, remind=20):
    r = rig({LEVEL: (str(pct), {"unit_of_measurement": "%"})})
    r.config(batch=dict(BATCH, recipe=[], level_entity=LEVEL, remind_pct=remind))
    return r


def _reads(r, count=1, runner=None):
    """`count` reads of the level, a minute apart, as the main loop polls dosing."""
    for _ in range(count):
        (runner or r.runner).poll()
        r.clock.sleep(dosing_runner.REMIND_CHECK_S)


def _dismissed(r):
    return [data for domain, service, data in r.fake.calls
            if (domain, service) == ("persistent_notification", "dismiss") and data["notification_id"] == NOTE]


def test_a_low_tank_is_told_after_three_reads_and_not_again_that_day(rig):
    r = _reminding(rig, 19)
    _reads(r, 2)
    assert r.creates("CS-906") == []  # one bad echo is not a low tank
    _reads(r)
    (alert,) = r.creates("CS-906")
    assert alert["notification_id"] == NOTE
    assert alert["title"].endswith("Batch tank at 19%, refill it (CS-906)")
    assert alert["message"].startswith(
        "The batch tank reads 19%, at or below its refill reminder (20%). Refill the tank by hand, or "
        "make a batch. Nothing refills the tank automatically. This alert comes again each day while the "
        "tank stays at or below 20%. It clears when the tank reads 25%."
    )
    _reads(r, 90)
    assert len(r.creates("CS-906")) == 1
    assert r.actions() == []  # a reminder moves nothing


def test_it_comes_again_each_day_and_a_restart_does_not_say_it_sooner(rig, tmp_path):
    r = _reminding(rig, 18)
    _reads(r, 3)
    assert r.saved()["reminded_at"] is not None
    r.clock.sleep(20 * 3600)
    again = r.build(tmp_path / "dosing_state.json")  # the app started again, on the same /data
    r.c._alerted, r.c._alert_codes = {}, {}
    _reads(r, 5, runner=again)
    assert len(r.creates("CS-906")) == 1  # said 20 hours ago: kept across the restart
    r.clock.sleep(4 * 3600)
    _reads(r, 1, runner=again)
    assert len(r.creates("CS-906")) == 2  # a day on, it comes again, on the same card
    assert {a["notification_id"] for a in r.creates("CS-906")} == {NOTE}


def test_it_goes_once_the_tank_reads_five_points_above_and_can_then_come_again_at_once(rig):
    r = _reminding(rig, 19)
    _reads(r, 3)
    r.set(LEVEL, "23")  # topped up a little: still under 25%, the reminder stays up
    _reads(r, 3)
    assert r.saved()["reminded_at"] is not None and _dismissed(r) == []
    r.set(LEVEL, "90")  # refilled
    _reads(r)
    assert r.saved()["reminded_at"] is None and len(_dismissed(r)) == 1
    r.set(LEVEL, "20")  # drawn down again: told at once, not a day after the last
    _reads(r, 3)
    assert len(r.creates("CS-906")) == 2


def test_a_level_that_reads_nothing_changes_nothing(rig):
    r = _reminding(rig, 19)
    _reads(r, 2)
    r.set(LEVEL, "unavailable")
    _reads(r, 5)
    assert r.creates("CS-906") == []
    r.set(LEVEL, "19")
    _reads(r)
    assert len(r.creates("CS-906")) == 1  # its third low read


def test_never_while_a_dose_or_batch_runs_in_the_room(rig):
    r = _reminding(rig, 10)
    r.runner._job = dosing_runner._Job(r.c.rooms[0], {"pumps": [], "batch": {}}, {"id": "x"}, "batch")
    _reads(r, 10)
    assert r.creates("CS-906") == []
    r.runner._job = None
    _reads(r, 3)
    assert len(r.creates("CS-906")) == 1


def test_a_setup_without_the_reminder_reads_no_level_and_turning_it_off_takes_it_down(rig):
    r = rig({LEVEL: ("5", {})})
    r.config()  # a setup from before the reminder: neither key
    seen = []
    original = r.fake.ha_get

    def get(entity, **kw):
        seen.append(entity)
        return original(entity, **kw)

    r.runner._get = get
    _reads(r, 10)
    assert LEVEL not in seen and r.creates("CS-906") == []
    r.runner._get = original
    r.config(batch=dict(BATCH, recipe=[], level_entity=LEVEL, remind_pct=20))
    _reads(r, 3)
    assert len(r.creates("CS-906")) == 1
    r.config(batch=dict(BATCH, recipe=[], level_entity=LEVEL, remind_pct=0))
    _reads(r)
    assert r.saved()["reminded_at"] is None and len(_dismissed(r)) == 1


def test_a_dosing_state_file_from_before_the_reminder_loads(rig, tmp_path):
    r = _reminding(rig, 19)
    path = tmp_path / "dosing_state.json"
    path.write_text('{"rooms": {"default": {"handled": "abc", "history": []}}, "outbox": []}', encoding="utf-8")
    old = r.build(path)
    _reads(r, 3, runner=old)
    assert len(r.creates("CS-906")) == 1 and r.saved()["handled"] == "abc"
