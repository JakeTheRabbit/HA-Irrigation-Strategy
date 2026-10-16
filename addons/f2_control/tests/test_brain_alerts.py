"""The AI assistant's own alert codes reach Home Assistant (haiku-brain-design section 5): Controller._jev_alert raises
CS-708, CS-709 and CS-712 under their own notification keys, says whether Home Assistant took the card, and still
refuses a code the error-code list does not explain. The decision log stays under Home Assistant's 16 KB limit."""
import json
from datetime import datetime

from jev import journal as jn
from test_controller import _build
from test_jev_controller import KILL, _states


def _c():
    c, fake = _build({"num_zones": 1, "enable_flag": KILL}, states=_states())
    return c, fake, c.rooms[0]


def _created(fake, code):
    return [d["notification_id"] for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and f"({code})" in d["title"]]


def test_each_brain_code_has_its_own_key_and_says_it_reached_home_assistant():
    c, fake, room = _c()
    for code, label in (("CS-708", "spent"), ("CS-709", "brain"), ("CS-712", "route")):
        assert c._jev_alert(room, None, label, {"code": code, "title": "t", "message": "m"}) is True
        assert _created(fake, code) == [f"f2_jev_{label}_default"]
    assert c._jev_alert(room, None, "budget", {"code": "CS-706", "title": "t", "message": "m"}) is True
    assert c._jev_alert(room, None, "spent", {"code": "CS-708", "title": "t", "message": "m"}) is False  # its quiet


def test_an_unlisted_code_is_refused(capsys):
    c, fake, room = _c()
    assert c._jev_alert(room, None, "x", {"code": "CS-799", "title": "t", "message": "m"}) is False
    assert not _created(fake, "CS-799") and "brain alert refused" in capsys.readouterr().out


def test_a_card_home_assistant_did_not_take_is_raised_again(monkeypatch):
    import controller
    import jev_bridge

    c, fake, room = _c()
    took = controller.ha_call
    monkeypatch.setattr(controller, "ha_call", lambda *a, **k: False)
    jev_bridge.route_card(c, room)
    assert jev_bridge._route_card_due(c)
    monkeypatch.setattr(controller, "ha_call", took)
    jev_bridge.route_card(c, room)
    assert not jev_bridge._route_card_due(c) and _created(fake, "CS-712") == ["f2_jev_route_default"]


def test_thirty_entries_at_every_cap_stay_under_16_kb():
    j = jn.Journal()
    for i in range(40):
        j.add({"t": datetime(2026, 9, 27, 13, i % 60).isoformat(), "room": "default", "zone": 1, "judge": "setpoints",
               "title": "Setpoints", "kind": "decision", "verdict": "v" * 300, "p": 0.91, "agreed": True,
               "action": "a" * 300, "result": "would act", "reason": "r" * 300, "why": "w" * 300})
    shown = j.recent("default")
    assert len(shown) == 30 and [len(e.get("why", "")) for e in shown] == [jn.WHY_CAP] * 10 + [0] * 20
    assert len(json.dumps({"entries": shown})) < 16 * 1024
