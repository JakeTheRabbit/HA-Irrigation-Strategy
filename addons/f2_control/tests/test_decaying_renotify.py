"""A standing alert's phone push decays by the severity of its code (docs/error-codes.json), the AI assistant or not.

Every raise is still a card. The push: a critical code, or a warning that means a zone is not being watered,
every 30 minutes for as long as it lasts; any other warning after 15 minutes, then 1, 2 and 4 hours, then
every 8 hours; an info code once. The schedule starts again with each episode: the alert cleared and raised
again, raised under another code, or back after an hour without being raised. Before this a repeat pushed
every 30 minutes forever, unless an LLM judge held it, and its verdict outlived the incident.
"""
from datetime import datetime, timedelta

from test_notify_routing import OPTION, _cards, _option, _setup

T0 = datetime(2026, 10, 15, 2, 0, 0)


def _pushes(code, minutes, key="k"):
    """The minutes at which a card raised at each of `minutes` (after T0) also pushed."""
    c, _fake = _setup(recipients=0)
    pushed = []
    for m in minutes:
        now = T0 + timedelta(minutes=m)
        if c._push_due(key, code, now):
            pushed.append(m)
        c._alerted[key] = now
    return pushed


EVERY_HALF_HOUR_FOR_A_DAY = range(0, 24 * 60 + 1, 30)


def test_critical_and_not_watering_codes_push_every_30_minutes_for_as_long_as_they_last():
    for code in ("CS-207", "CS-301", "CS-801", "CS-206", "CS-208", "CS-209", "CS-602"):
        assert _pushes(code, EVERY_HALF_HOUR_FOR_A_DAY) == list(EVERY_HALF_HOUR_FOR_A_DAY), code


def test_a_warning_decays_to_every_8_hours():
    # The card updates every 30 minutes: each step goes with the first update at or after it.
    assert _pushes("CS-102", EVERY_HALF_HOUR_FOR_A_DAY) == [0, 30, 90, 210, 450, 930, 1410]
    # A card raised every minute (an event) meets each step on time.
    assert _pushes("CS-802", range(0, 16 * 60))[:6] == [0, 15, 75, 195, 435, 915]


def test_an_info_code_pushes_once():
    assert _pushes("CS-501", EVERY_HALF_HOUR_FOR_A_DAY) == [0]


def test_a_cleared_alert_starts_again_at_its_first_push():
    c, _fake = _setup(recipients=0)
    assert c._push_due("k", "CS-501", T0)
    c._alerted["k"] = T0
    assert not c._push_due("k", "CS-501", T0 + timedelta(minutes=30))
    c._alerted.pop("k")  # cleared: the card was taken down
    assert c._push_due("k", "CS-501", T0 + timedelta(minutes=35))


def test_another_code_under_the_same_key_or_an_hour_unraised_is_a_new_episode():
    c, _fake = _setup(recipients=0)
    for m, code, due in ((0, "CS-101", True), (30, "CS-101", True), (60, "CS-101", False),
                         (65, "CS-102", True),  # another diagnosis: pushed at once
                         (95, "CS-102", True), (125, "CS-102", False),
                         (190, "CS-102", True),  # not raised for over an hour: the condition went and came back
                         (220, "CS-102", True), (250, "CS-102", False)):
        now = T0 + timedelta(minutes=m)
        assert c._push_due("k", code, now) is due, m
        c._alerted["k"] = now


def test_a_held_repeat_is_still_a_card_and_goes_to_no_phone():
    c, fake = _setup(recipients=0, notify_service=OPTION)
    for _ in range(2):
        assert c._alert("x", "CS-501", "less water", "m", room=c.rooms[0], zone=1)
        c._alerted["x"] -= timedelta(minutes=31)  # out of the card's 30-minute window
    assert len(_cards(fake, "f2_x")) == 2
    assert len(_option(fake)) == 1


def test_jev_has_no_say_in_the_push():
    c, fake = _setup(recipients=0, notify_service=OPTION)
    c.jev = object()  # whatever the AI assistant is, the alert does not ask it
    assert c._alert("k", "CS-207", "drying out", "m", room=c.rooms[0], zone=1)
    assert len(_option(fake)) == 1
