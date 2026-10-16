"""A jev_judges option copied from an old install (it may still name the retired alerts judge) loads with no error
inside the real controller: it is read as all, so the brain builds every judge and never "alerts", and the log says
once a process, across restarts and passes, which judges that adds."""
import functools

import pytest

import controller
import brain_bridge
import jev_kit as K
from brain.client import Asker
from test_controller import _build
from test_jev_controller import KILL, NOW, _p1_zone, _states

OLD = "dawn,ramp,salt,dusk,probe,shot,night,zones,alerts"  # the nine judges of the first release
NOTE = "old jev_judges list"


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    monkeypatch.setattr(brain_bridge, "_upgrade_said", False)


def test_the_old_list_is_read_as_all_once_across_controller_restarts_and_passes(monkeypatch):
    said = []
    monkeypatch.setattr(controller, "log", lambda *a: said.append(" ".join(map(str, a))))
    K.sdk(monkeypatch, K.FakeTransport({}, None))
    monkeypatch.setattr(brain_bridge, "Asker", functools.partial(Asker, threaded=False, clock=lambda: NOW.timestamp()))
    for _ in range(2):
        c, _fake = _build({"num_zones": 1, "enable_flag": KILL, **K.HAIKU, "jev_judges": OLD}, states=_states())
        names = [j.name for j in c.jev.judges]
        assert "alerts" not in names and {"ramp", "stage", "setpoints", "channel", "balance"} <= set(names)
        _p1_zone(c)
        for _ in range(3):
            c.loop_once(NOW)
    notes = [s for s in said if NOTE in s]
    assert len(notes) == 1 and "stage, setpoints, channel, balance, feed, report, why, plan" in notes[0]
