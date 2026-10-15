"""The Alerts judge: the first raise always pushes; Jev's answer decides the repeats; safety codes always push."""
import jev_kit as K
from jev.client import Asker
from jev.triage import Triage


def _triage(answers=None, error=None):
    return Triage(Asker("a", "t", transport=K.FakeTransport(answers, error), threaded=False,
                        clock=lambda: K.NOW.timestamp()))


def test_the_first_raise_always_pushes_and_asks_jev():
    t = _triage(K.both("urgency", K.choice_answer("quiet", {"quiet": 0.9})))
    assert t.push("xzone_default_1", "CS-501", "less water", "msg", K.NOW) == (True, "first time: pushed as always")
    assert t.asker.result("alert:xzone_default_1") is not None


def test_a_quiet_repeat_is_a_card_only():
    t = _triage(K.both("urgency", K.choice_answer("quiet", {"quiet": 0.9})))
    t.push("k", "CS-501", "less water", "msg", K.NOW)
    push, why = t.push("k", "CS-501", "less water", "msg", K.NOW)
    assert push is False and "quiet" in why


def test_an_escalating_or_unsure_repeat_still_pushes():
    for answers in (K.both("urgency", K.choice_answer("escalate", {"escalate": 0.9})),
                    K.both("urgency", K.choice_answer("quiet", {"quiet": 0.9}), K.choice_answer("remind", {"remind": 0.8}))):
        t = _triage(answers)
        t.push("k", "CS-205", "t", "m", K.NOW)
        assert t.push("k", "CS-205", "t", "m", K.NOW)[0] is True


def test_pump_valve_and_probe_alerts_always_push_without_asking():
    t = _triage(K.both("urgency", K.choice_answer("quiet", {"quiet": 0.99})))
    # CS-801, CS-803 and CS-806: dosing hardware past its time, interrupted, or left on by a batch.
    for code in ("CS-301", "CS-308", "CS-102", "CS-701", "CS-704", "CS-801", "CS-803", "CS-806"):
        for _ in range(3):
            assert t.push(f"k{code}", code, "t", "m", K.NOW) == (True, "always pushed")
    assert t.asker.stats["calls"] == 0


def test_with_jev_down_every_alert_pushes():
    t = _triage(error="timeout")
    for _ in range(3):
        assert t.push("k", "CS-501", "t", "m", K.NOW)[0] is True
