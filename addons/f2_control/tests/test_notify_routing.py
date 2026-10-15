"""Who gets a phone push is the integration's to say (docs/NOTIFICATIONS.md).

Every alert is a card first, exactly as before, and Jev's Alerts judge still decides whether a repeat pushes at
all. The push itself: with a phone set up in the integration (sensor.crop_steering_notify_config), it is handed to
crop_steering.notify and nothing is pushed here; with none, or when that call fails, it goes to the notify_service
option as it always has. Never both, and never lost to the router. Phase changes and the settings Jev moves go to
the phones that ask for them, never to the option. And CS-209: a room with its lights on and a zone in P1 or P2
that has watered nothing for a while.
"""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import controller
import jev_kit as K
from test_controller import _build
from test_jev_controller import NOW as JEV_NOW
from test_jev_controller import _p1_zone, jev_with  # noqa: F401 (jev_with: a pytest fixture)
from test_zone_count import KILL, _room

CONFIG = "sensor.crop_steering_notify_config"
OPTION = "notify/mobile_app_old_phone"  # the notify_service option, as an install before this has it
FOOTER = "\n\nCode {}. What it means and what to do: Crop Steering → Help & tools → Error codes."
TOOK = {"sent_to": ["notify.mobile_app_a"], "error": None}


def _setup(recipients=1, idle_hours=3, notify_service=OPTION):
    """A one-zone room; `recipients` None is an integration from before notifications (no sensor at all)."""
    states = _room(1)
    if recipients is not None:
        states[CONFIG] = (str(recipients), {"recipients": recipients, "idle_hours": idle_hours})
    return _build({"notify_service": notify_service, "num_zones": 1}, states=states)


class Router:
    """crop_steering.notify as the controller reaches it over REST (ha_service_response): records, answers."""

    def __init__(self, status=200, answer=TOOK):
        self.status, self.answer, self.calls = status, answer, []

    def __call__(self, domain, service, data, timeout=12):
        self.calls.append((domain, service, dict(data), timeout))
        return self.status, self.answer

    @property
    def sent(self):
        return [data for _domain, _service, data, _timeout in self.calls]


@pytest.fixture
def router(monkeypatch):
    def install(**answer):
        routed = Router(**answer)
        monkeypatch.setattr(controller, "ha_service_response", routed)
        return routed

    return install


def _option(fake):
    """What went to the notify_service option, the vitals report aside (it has always gone there)."""
    return [(svc, d) for dom, svc, d in fake.calls
            if dom == "notify" and not d.get("title", "").endswith("vitals")]


def _cards(fake, notification_id):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and d["notification_id"] == notification_id]


# ------------------------------------------------------------------ an alert's push
def test_with_a_phone_set_up_the_push_goes_through_the_integration_and_nowhere_else(router):
    c, fake = _setup(recipients=2)
    routed = router()
    assert c._alert("blind_default_z1", "CS-102", "moisture sensor not reporting", "Detail.",
                    room=c.rooms[0], zone=1)
    [(domain, service, data, timeout)] = routed.calls
    assert (domain, service, timeout) == ("crop_steering", "notify", controller.NOTIFY_TIMEOUT_S)
    assert data == {
        "key": "blind_default_z1",
        "code": "CS-102",
        "room": "",
        "zone": 1,
        "title": "Zone 1: moisture sensor not reporting (CS-102)",
        "message": "Detail." + FOOTER.format("CS-102"),
    }
    assert _option(fake) == []  # never both
    assert _cards(fake, "f2_blind_default_z1")  # the card, as always


def test_a_critical_code_goes_as_urgent_and_nothing_else_does(router):
    c, _fake = _setup()
    routed = router()
    room = c.rooms[0]
    c._alert("hw_default_z1", "CS-301", "hardware fault", "m", room=room, zone=1)
    c._alert("block_default_z1", "CS-205", "daily water limit reached", "m", room=room, zone=1)
    c._alert("tz_mismatch", "CS-405", "timezone mismatch", "m")
    critical, info, clock = routed.sent
    assert critical["urgent"] is True and "urgent" not in info and "urgent" not in clock
    assert "room" not in clock and "zone" not in clock  # about no room in particular


@pytest.mark.parametrize("recipients", [0, None], ids=["nobody set up", "an older integration"])
def test_with_no_phone_set_up_the_push_goes_to_the_option_exactly_as_before(router, recipients):
    c, fake = _setup(recipients=recipients)
    routed = router()
    c._alert("k", "CS-102", "moisture sensor not reporting", "m", room=c.rooms[0], zone=1)
    assert routed.calls == []
    assert _option(fake) == [("mobile_app_old_phone", {
        "title": "Zone 1: moisture sensor not reporting (CS-102)",
        "message": "m" + FOOTER.format("CS-102"),
    })]


@pytest.mark.parametrize(
    "status, answer",
    [
        (None, None),  # Home Assistant unreachable, or no answer within NOTIFY_TIMEOUT_S
        (500, None),
        (400, None),  # refused, or an integration without crop_steering.notify
        (200, {"sent_to": [], "error": "notify.mobile_app_a: device not connected"}),  # every phone failed
        (200, {"sent_to": [], "error": "no phone is set up for notifications"}),  # removed within the minute
    ],
)
def test_a_push_the_integration_did_not_take_goes_to_the_option_once(router, status, answer):
    c, fake = _setup()
    routed = router(status=status, answer=answer)
    assert c._alert("k", "CS-102", "t", "m", room=c.rooms[0], zone=1)
    assert len(routed.calls) == 1 and len(_option(fake)) == 1


@pytest.mark.parametrize(
    "answer",
    [
        TOOK,
        {"sent_to": [], "error": None},  # nobody ticks this kind: to nobody, on purpose
        {"sent_to": ["notify.mobile_app_a"], "error": "notify.mobile_app_b: rate limited"},  # one of two
        None,  # taken, with no answer to read
    ],
)
def test_a_push_the_integration_took_never_goes_to_the_option_as_well(router, answer):
    c, fake = _setup()
    router(answer=answer)
    c._alert("k", "CS-102", "t", "m", room=c.rooms[0], zone=1)
    assert _option(fake) == []


def test_whatever_goes_wrong_handing_it_over_the_push_goes_the_old_way(monkeypatch):
    c, fake = _setup()

    def broken(*_args, **_kwargs):
        raise RuntimeError("a bug")

    monkeypatch.setattr(controller, "ha_service_response", broken)
    assert c._alert("k", "CS-301", "t", "m", room=c.rooms[0], zone=1)
    assert len(_option(fake)) == 1


def test_with_no_option_a_failed_router_pushes_nothing_as_before(router):
    c, fake = _setup(notify_service="")
    routed = router(status=None, answer=None)
    assert c._alert("k", "CS-102", "t", "m", room=c.rooms[0], zone=1)
    assert len(routed.calls) == 1 and _option(fake) == []
    assert _cards(fake, "f2_k")


def test_a_repeat_jevs_alerts_judge_holds_goes_to_no_phone(router):
    for recipients, option in ((1, OPTION), (1, ""), (0, OPTION)):
        c, fake = _setup(recipients=recipients, notify_service=option)
        routed = router()
        asked = []

        def push(key, *_args):
            asked.append(key)
            return False, "Jev: quiet (p=0.90), card only"

        c.jev = SimpleNamespace(triage=SimpleNamespace(push=push))
        assert c._alert("xzone_default_1", "CS-501", "less water", "m", room=c.rooms[0], zone=1)
        assert asked == ["xzone_default_1"]  # asked whenever a phone could get it
        assert routed.calls == [] and _option(fake) == []
        assert _cards(fake, "f2_xzone_default_1")  # the card, always


def test_jev_is_not_asked_when_no_phone_could_get_the_push(router):
    c, fake = _setup(recipients=0, notify_service="")
    router()
    c.jev = SimpleNamespace(triage=SimpleNamespace(push=lambda *a: pytest.fail("asked")))
    assert c._alert("k", "CS-501", "t", "m", room=c.rooms[0], zone=1)


def test_the_integrations_setup_is_read_by_the_loop_at_most_once_a_minute_and_never_waited_on_by_an_alert(
        router, monkeypatch):
    c, fake = _setup()
    router()
    reads = []
    real = controller.ha_get
    monkeypatch.setattr(controller, "ha_get", lambda entity, **k: reads.append(entity) or real(entity, **k))
    clock = {"s": 1000.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["s"])
    for key in ("a", "b", "c"):
        c._alert(key, "CS-102", "t", "m", room=c.rooms[0], zone=1)
    assert reads.count(CONFIG) == 1  # the first alert ever has nothing to go on yet
    fake.set_state(CONFIG, "2", {"recipients": 0, "idle_hours": 20})  # nobody set up now
    clock["s"] += 10 * controller.NOTIFY_CONFIG_S
    c._alert("d", "CS-102", "t", "m", room=c.rooms[0], zone=1)
    assert reads.count(CONFIG) == 1  # however old the last reading, an alert goes on it
    assert c._notify_config(refresh=True) == (0, 12.0)  # the loop's read; idle_hours kept inside 1 to 12
    assert c._notify_config(refresh=True) == (0, 12.0)
    assert reads.count(CONFIG) == 2  # at most once a minute
    c._alert("e", "CS-102", "t", "m", room=c.rooms[0], zone=1)
    assert [svc for svc, _d in _option(fake)] == ["mobile_app_old_phone"]


def test_an_emergency_that_reached_no_phone_through_the_integration_goes_to_the_option(router):
    """No row takes emergencies at all, or an answer with nothing to read: a critical code goes to the option.
    Anything else nobody ticked stays with nobody (above)."""
    for answer in ({"sent_to": [], "error": None}, None):
        c, fake = _setup()
        routed = router(answer=answer)
        assert c._alert("hw_default_z1", "CS-301", "hardware fault", "m", room=c.rooms[0], zone=1)
        assert routed.sent[0]["urgent"] is True
        assert [svc for svc, _d in _option(fake)] == ["mobile_app_old_phone"]


def test_a_push_with_nowhere_to_go_says_so_in_the_log(router, monkeypatch):
    for recipients, answer in ((0, TOOK), (1, {"sent_to": [], "error": "no phone takes emergencies"})):
        c, fake = _setup(recipients=recipients, notify_service="")
        router(answer=answer)
        logged = []
        monkeypatch.setattr(controller, "log", lambda *a: logged.append(" ".join(map(str, a))))
        assert c._alert("k", "CS-301", "t", "m", room=c.rooms[0], zone=1)
        assert any("went to no phone" in line for line in logged)


@pytest.mark.parametrize("attrs, expected", [
    ({"recipients": 3, "idle_hours": 0.5}, (3, 1.0)),
    ({"recipients": "x", "idle_hours": "x"}, (0, 3.0)),
    ({"recipients": -2, "idle_hours": 4.5}, (0, 4.5)),
    ({}, (0, 3.0)),
])
def test_what_the_controller_makes_of_the_integrations_setup(attrs, expected):
    c, fake = _setup(recipients=None)
    fake.set_state(CONFIG, "5", attrs)
    assert c._notify_config() == expected


# ------------------------------------------------------------------ phase changes and Jev's settings
def test_a_phase_change_goes_to_the_phones_that_ask_and_never_to_the_option(router):
    c, fake = _setup()
    routed = router()
    room = c.rooms[0]
    room.state[1].update(phase="P2", last_daily_reset=date(2026, 9, 21))
    c.loop_once(datetime(2026, 9, 21, 23, 0))  # lights-off
    assert room.state[1]["phase"] == "P3"
    assert [d for d in routed.sent if d.get("event")] == [{
        "key": "phase_default_z1",
        "event": "phase",
        "room": "",
        "zone": 1,
        "title": "Zone 1: P2 → P3",
        "message": "lights-off -> P3",
    }]
    assert _option(fake) == []
    # By hand, on the zone's Set Phase select (and the lights, still off, take it back to P3): one loop's
    # moves in a room are one push.
    fake.set_state("select.crop_steering_zone_1_set_phase", "P2")
    c.loop_once(datetime(2026, 9, 21, 23, 1))
    assert [(d["key"], d.get("zone"), d["title"], d["message"]) for d in routed.sent if d.get("event")][1:] == [(
        "phase_default", None, "Phase changes", "Zone 1: P3 → P2, set by hand\nZone 1: P2 → P3, lights-off -> P3",
    )]


def test_a_rooms_events_go_as_one_push_per_kind_within_the_loops_time(router, monkeypatch):
    """Lights-off moves every zone at once: one push for the room, not one per zone. And the lot gets
    EVENTS_BUDGET_S: a slow Home Assistant never holds the loop up for long."""
    c, fake = _setup()
    routed = router()
    room = c.rooms[0]
    c._notify_event("phase", room, 1, "P2", "P3", "lights-off -> P3")
    c._notify_event("phase", room, 2, "P2", "P3", "lights-off -> P3")
    c._notify_event("jev_setpoint", room, 2, "P2 shot 5% -> 4.5%", "Smaller shots.")
    c._send_events()
    assert [(d["key"], d.get("zone"), d["title"], d["message"]) for d in routed.sent] == [
        ("phase_default", None, "Phase changes", "Zone 1: P2 → P3, lights-off -> P3\nZone 2: P2 → P3, lights-off -> P3"),
        ("jev_setpoint_default_z2", 2, "Zone 2: Jev changed P2 shot 5% -> 4.5%", "Smaller shots."),
    ]
    clock = {"s": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: clock["s"])

    def slow(domain, service, data, timeout=12):
        routed.calls.append((domain, service, dict(data), timeout))
        clock["s"] += 11  # longer than the whole budget
        return 200, TOOK

    monkeypatch.setattr(controller, "ha_service_response", slow)
    c._notify_event("phase", room, 1, "P3", "P0", "lights-on")
    c._notify_event("jev_setpoint", room, 1, "re-water 34 -> 34.5", "Drier.")
    c._send_events()
    assert len(routed.calls) == 3  # the first went; the second was out of time, and is dropped
    assert routed.calls[-1][3] == controller.EVENTS_BUDGET_S  # never given longer than the loop has left
    c._send_events()
    assert len(routed.calls) == 3


def test_jev_moving_a_zone_on_is_a_phase_change_like_any_other(jev_with, router):  # noqa: F811
    answers = K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8, "real_salt": 0.2}))
    c, fake = jev_with(answers)
    fake.set_state(CONFIG, "1", {"recipients": 1, "idle_hours": 3})
    fake.set_state("input_boolean.kill", "off")  # no shot to wait for: the move is Jev's either way
    routed = router()
    _p1_zone(c)
    c.loop_once(JEV_NOW)
    assert c.rooms[0].state[1]["phase"] == "P2"
    [event] = [d for d in routed.sent if d.get("event") == "phase"]
    assert event["title"] == "Zone 1: P1 → P2"
    assert event["message"].startswith("Jev's ramp judge: ramp done: ec_is_feed_front")


@pytest.mark.parametrize("recipients", [0, None])
def test_with_no_phone_set_up_a_phase_change_goes_nowhere(router, recipients):
    c, fake = _setup(recipients=recipients)
    routed = router()
    c.rooms[0].state[1].update(phase="P2", last_daily_reset=date(2026, 9, 21))
    c.loop_once(datetime(2026, 9, 21, 23, 0))
    assert c.rooms[0].state[1]["phase"] == "P3"
    assert routed.calls == [] and _option(fake) == []


def test_a_setting_jev_moved_goes_to_the_phones_that_ask_and_a_failure_is_dropped(router):
    c, fake = _setup()
    routed = router()
    room = c.rooms[0]
    c._notify_event("jev_setpoint", room, 1, "P2 shot 5% -> 4.5%", "Smaller maintenance shots tomorrow.")
    c._send_events()
    assert routed.sent == [{
        "key": "jev_setpoint_default_z1",
        "event": "jev_setpoint",
        "room": "",
        "zone": 1,
        "title": "Zone 1: Jev changed P2 shot 5% -> 4.5%",
        "message": "Smaller maintenance shots tomorrow.",
    }]
    routed.status = 500
    c._notify_event("phase", room, 1, "P1", "P2", "")
    c._send_events()
    assert len(routed.calls) == 2 and _option(fake) == []  # an event is never pushed to the option
    assert routed.sent[-1]["message"] == "P1 → P2"
    c._send_events()
    assert len(routed.calls) == 2  # and never sent again


# ------------------------------------------------------------------ CS-209, no watering for a while
def _idle_room(**options):
    """A zone in P2 since 10:30, lights on 10-22, last watered yesterday, and watering switched off."""
    c, fake = _setup(**options)
    room = c.rooms[0]
    room.state[1].update(phase="P2", last_phase_change=datetime(2026, 9, 21, 10, 30),
                         last_shot=datetime(2026, 9, 20, 21, 0), last_daily_reset=date(2026, 9, 21))
    return c, fake, room


def _at(hour, minute=0):
    return datetime(2026, 9, 21, hour, minute)


def _dismissed(fake):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "dismiss") and d["notification_id"] == "f2_idle_default"]


def test_a_room_with_nothing_watered_for_idle_hours_says_so_again_and_clears_at_the_next_shot(router):
    c, fake, room = _idle_room()
    routed = router()
    c.loop_once(_at(13, 0))  # 2.5 hours since the zone came into P2
    assert _cards(fake, "f2_idle_default") == []
    c.loop_once(_at(13, 31))
    [card] = _cards(fake, "f2_idle_default")
    assert card["title"] == "No watering for a while (CS-209)"
    assert "watered for 3.0 hours" in card["message"]
    assert f"Watering is switched off in this room: its engine switch ({KILL}) is off." in card["message"]
    assert "said again every 3 hours while it lasts" in card["message"]
    [push] = [d for d in routed.sent if d.get("code") == "CS-209"]
    assert push["key"] == "idle_default" and "urgent" not in push and push["room"] == ""
    c.loop_once(_at(14, 0))
    c.loop_once(_at(16, 0))
    assert len(_cards(fake, "f2_idle_default")) == 1  # once per stretch...
    c.loop_once(_at(16, 31))
    assert len(_cards(fake, "f2_idle_default")) == 2  # ...and again every idle_hours while it lasts
    dismissed = len(_dismissed(fake))
    room.state[1]["last_shot"] = _at(16, 40)  # a shot in the room
    c.loop_once(_at(16, 45))
    assert len(_dismissed(fake)) == dismissed + 1 and "idle_default" not in c._alerted
    c.loop_once(_at(19, 30))
    assert len(_cards(fake, "f2_idle_default")) == 2  # the clock started again at the shot
    c.loop_once(_at(19, 41))
    assert len(_cards(fake, "f2_idle_default")) == 3


def test_the_hours_come_from_the_integration(router):
    c, fake, room = _idle_room(idle_hours=1)
    router()
    c.loop_once(_at(11, 29))
    assert _cards(fake, "f2_idle_default") == []
    c.loop_once(_at(11, 31))
    assert "said again every hour while" in _cards(fake, "f2_idle_default")[0]["message"]


def test_lights_off_or_a_room_in_p0_and_p3_ends_it_and_never_starts_it(router):
    c, fake, room = _idle_room()
    router()
    c.loop_once(_at(13, 31))
    assert len(_cards(fake, "f2_idle_default")) == 1
    c.loop_once(_at(23, 0))  # lights-off: P3
    assert room.state[1]["phase"] == "P3" and len(_dismissed(fake)) >= 1
    assert "idle_default" not in c._alerted
    # The morning dry-back, however long it takes, and an early P3 with the lights still on: never CS-209.
    room.state[1].update(phase="P0", last_phase_change=datetime(2026, 9, 22, 10, 0))
    for hour in (11, 14, 17, 20):
        c._watch_idle(room, datetime(2026, 9, 22, hour, 0), True, {})
    room.state[1]["phase"] = "P3"
    c._watch_idle(room, datetime(2026, 9, 22, 21, 30), True, {})
    assert len(_cards(fake, "f2_idle_default")) == 1


def test_a_room_switched_off_has_no_clock(router):
    c, fake, room = _idle_room()
    router()
    c.loop_once(_at(12, 0))  # on: its clock has run since 10:30
    fake.set_state("switch.crop_steering_room_active", "off")
    for hour, minute in ((13, 31), (16, 31), (19, 39)):
        c.loop_once(_at(hour, minute))
    assert _cards(fake, "f2_idle_default") == []
    fake.set_state("switch.crop_steering_room_active", "on")  # back on within the day: carries on in P2
    c.loop_once(_at(19, 40))
    assert room.state[1]["phase"] == "P2"
    c.loop_once(_at(21, 59))
    assert _cards(fake, "f2_idle_default") == []  # its clock started again at switch-on


def test_a_restart_in_the_middle_does_not_restart_the_clock(router):
    """After a restart the saved state says when the zone came into P2 and when it was last watered."""
    c, fake, room = _idle_room()
    router()
    c.loop_once(_at(13, 40))  # the first loop of a controller started at 13:40
    assert len(_cards(fake, "f2_idle_default")) == 1


def test_it_says_which_hold_or_that_nothing_called_for_water(router):
    c, fake, room = _idle_room()
    router()
    fake.set_state(KILL, "on")
    fake.set_state("switch.crop_steering_zone_1_enabled", "off")
    assert c._idle_why(room, {}) == "Watering is held. Zone 1: zone disabled."
    assert c._idle_why(room, {1: {"block": "making a batch"}}) == "Watering is held. Zone 1: making a batch."
    fake.set_state("switch.crop_steering_zone_1_enabled", "on")
    assert c._idle_why(room, {}).startswith("Nothing called for water: no zone in P1 or P2 dried")


def test_an_install_from_before_notifications_pushes_as_it_always_did(router):
    """UPGRADE IN PLACE: no sensor.crop_steering_notify_config. Every alert still goes to the option (CS-209 too,
    after the default 3 hours), and a phase change goes nowhere."""
    c, fake, room = _idle_room(recipients=None)
    routed = router()
    assert c._notify_config() == (0, controller.IDLE_HOURS)
    c.loop_once(_at(13, 31))
    c.loop_once(_at(23, 0))
    assert routed.calls == []
    assert [d["title"] for _svc, d in _option(fake)] == ["No watering for a while (CS-209)"]
