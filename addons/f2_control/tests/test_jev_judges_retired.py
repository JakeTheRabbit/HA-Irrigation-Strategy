"""A jev_judges option copied from an old install still names the retired alerts judge: the name is dropped like any
unknown one (no error, the brain starts), and the log says once a process which newer judges the list leaves off and
that `all` asks every judge. `all`, an empty option and a list without alerts say nothing."""
import functools

import pytest

import controller
import jev_bridge
import jev_kit as K
from jev.client import Asker
from test_controller import _build
from test_jev_controller import KILL, NOW, _p1_zone, _states

OLD = "dawn,ramp,salt,dusk,probe,shot,night,zones,alerts"  # the nine judges of the first release
NOTE = "names the retired alerts judge"


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    monkeypatch.setattr(jev_bridge, "_retired_said", False)


def _brain(tmp_path, judges, said, name="s"):
    (tmp_path / name).mkdir()
    return jev_bridge.build({"typesafe_api_key": "t", "jev_judges": judges}, ("", "", ""),
                            str(tmp_path / name / "state.json"), lambda *a: said.append(" ".join(map(str, a))))


def test_the_retired_alerts_judge_is_dropped_without_an_error(tmp_path):
    said = []
    brain = _brain(tmp_path, OLD, said)
    names = [j.name for j in brain.judges]
    assert "alerts" not in names
    assert names == ["dawn", "ramp", "salt", "dusk", "probe", "shot", "night", "zones"]
    assert not [s for s in said if "unknown" in s or "error" in s.lower()]


def test_the_note_names_the_newer_judges_and_all(tmp_path):
    said = []
    _brain(tmp_path, OLD, said)
    notes = [s for s in said if NOTE in s]
    assert notes == ["brain: jev_judges names the retired alerts judge, which is ignored. It lists its judges one by "
                     "one, so the newer judges stage, setpoints, channel, balance, feed, report, why, plan are not "
                     "asked. Set jev_judges to all to ask every judge"]


def test_the_note_is_logged_once_across_rebuilds(tmp_path):
    said = []
    for n in range(3):
        _brain(tmp_path, OLD, said, name=f"s{n}")
    assert len([s for s in said if NOTE in s]) == 1


@pytest.mark.parametrize("judges", ["all", "", None, "dawn,ramp,salt", "dawn, ramp, setpoints"])
def test_no_note_without_the_retired_name(tmp_path, judges):
    said = []
    _brain(tmp_path, judges, said)
    assert not [s for s in said if NOTE in s]


def test_no_note_when_the_list_already_names_every_newer_judge(tmp_path):
    said = []
    brain = _brain(tmp_path, ",".join([*jev_bridge.ALL, "alerts"]), said)
    assert not [s for s in said if NOTE in s]
    assert "alerts" not in [j.name for j in brain.judges]


def test_the_note_is_logged_once_across_controller_restarts_and_passes(monkeypatch):
    said = []
    monkeypatch.setattr(controller, "log", lambda *a: said.append(" ".join(map(str, a))))
    monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: K.FakeTransport({}, None))
    monkeypatch.setattr(jev_bridge, "Asker", functools.partial(Asker, threaded=False, clock=lambda: NOW.timestamp()))
    K.has_run()
    for _ in range(2):
        c, _fake = _build({"num_zones": 1, "enable_flag": KILL, "cf_account_id": "acct", "cf_api_token": "tok",
                           "jev_judges": OLD}, states=_states())
        assert c.jev is not None and "alerts" not in [j.name for j in c.jev.judges]
        _p1_zone(c)
        for _ in range(3):
            c.loop_once(NOW)
    assert len([s for s in said if NOTE in s]) == 1
