"""The vitals notification: under each zone, while the room's "Include Predictions in Notifications" switch is
on, what it will do next, in the words of the dashboard's "Next:"; and its push goes to the phones that tick
Vitals once the integration lists that kind, else to the notify_service option exactly as before."""
from datetime import datetime

import pytest

import controller
from test_controller import _build

AT = datetime(2026, 9, 27, 7, 36)
NOW = datetime(2026, 9, 27, 8, 5)
PREDICT = "switch.crop_steering_notify_predictions"
CONFIG = "sensor.crop_steering_notify_config"
OPTION = "notify/mobile_app_old_phone"
HARDWARE = {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1"}}
PUB = {"default": {1: {"phase": "P2", "vwc": 84.1, "ec": 0.5}}}
ZONE = "  Z1 P2: VWC 84% EC 0.5 (FC~—) | 0.0L day | last never"
P2 = [
    {"rule": "p2_topup", "shot": True, "metric": "vwc", "op": "<", "value": 70, "now": 84.1},
    {"rule": "p2_dilute", "shot": True, "metric": "ec", "op": ">", "value": 3.84, "now": 0.5},
    {"rule": "lights_off", "to": "P3", "in_min": 600},
]


def _vitals(states=None, waiting=P2, options=None, router=None):
    c, fake = _build({"num_zones": 1, "hardware": HARDWARE, **(options or {})}, states=states or {})
    if router is not None:  # crop_steering.notify as the controller reaches it over REST
        controller.ha_service_response = router
    if waiting is not None:
        c.rooms[0]._waiting = {1: (waiting, AT)}
    c._maybe_notify(PUB, NOW)
    (message,) = [d["message"] for dom, svc, d in fake.calls if dom == "persistent_notification"]
    return c, fake, message.splitlines()


# ---------------------------------------------------------------- what comes next, in words
def test_p0_its_latest_time_or_sooner_at_the_level_drying_reaches_first():
    p0 = [
        {"rule": "p0_timeout", "to": "P1", "in_min": 30},
        {"rule": "p0_bypass", "to": "P1", "metric": "vwc", "op": "<=", "value": 70, "now": 84.1},
        {"rule": "p0_dryback", "to": "P1", "metric": "vwc", "op": "<=", "value": 42.9, "now": 84.1},
    ]
    assert controller.next_text(p0, AT) == "P1 by 08:06, or sooner at VWC ≤ 70% (now 84.1%)"
    assert controller.next_text([{"rule": "p0_timeout", "to": "P1", "in_min": 0}], AT) == "P1 now"


def test_p1_the_next_ramp_shot_and_what_hands_over_to_p2():
    p1 = [
        {"rule": "p1_ramp", "shot": True, "metric": "vwc", "op": "<", "value": 85, "now": 84.2, "in_min": 0},
        {"rule": "p1_done", "to": "P2", "metric": "vwc", "op": ">=", "value": 85, "now": 84.2,
         "shots_left": 2, "ec_max": 3.45, "ec_now": 0.5},
        {"rule": "p1_max_shots", "to": "P2", "shots_left": 5},
    ]
    assert controller.next_text(p1, AT) == (
        "ramp shot due (VWC 84.2% under 85%) · P2 at VWC ≥ 85% after 2 more shots with pwEC ≤ 3.45"
        " (now 0.5), or after 5 more ramp shots"
    )
    full = [
        {"rule": "p1_ramp", "shot": True, "metric": "vwc", "op": "<", "value": 85, "now": 86, "in_min": 10},
        {"rule": "p1_done", "to": "P2", "metric": "vwc", "op": ">=", "value": 85, "now": 86, "shots_left": 1},
    ]
    assert controller.next_text(full, AT) == "ramp shot when VWC < 85% (now 86%) · P2 at VWC ≥ 85% after 1 more shot"


def test_p2_p3_and_a_held_plan():
    assert controller.next_text(P2, AT) == (
        "shot when VWC < 70% (now 84.1%) · dilution if pwEC > 3.84 (now 0.5) · P3 by 17:36"
    )
    assert controller.next_text([{"rule": "lights_off", "to": "P3", "in_min": 600}], AT) == "P3 by 17:36"
    p3 = [
        {"rule": "p3_emergency", "shot": True, "metric": "vwc", "op": "<", "value": 60, "now": 84.1},
        {"rule": "lights_on", "to": "P0", "in_min": 660},
    ]
    assert controller.next_text(p3, AT) == "rescue shot if VWC < 60% (now 84.1%) · P0 at 18:36"
    # A reading it could not take: the threshold alone, no empty brackets.
    assert controller.next_text([{**P2[0], "now": None}], AT) == "shot when VWC < 70%"
    assert controller.next_text([], AT) == ""
    assert controller.next_text(None, AT) == ""


# ---------------------------------------------------------------- the notification
def test_each_zone_says_what_comes_next_under_its_line():
    _c, _fake, lines = _vitals()
    assert lines[-2:] == [
        ZONE,
        "  Next: shot when VWC < 70% (now 84.1%) · dilution if pwEC > 3.84 (now 0.5) · P3 by 17:36",
    ]


def test_with_predictions_switched_off_only_the_zone_line():
    _c, _fake, lines = _vitals({PREDICT: ("off", {})})
    assert lines[-1] == ZONE and not [line for line in lines if "Next:" in line]
    _c, _fake, lines = _vitals({PREDICT: ("on", {})})
    assert lines[-1].startswith("  Next: ")


def test_a_zone_the_controller_has_nothing_to_say_about_gets_no_next_line():
    assert _vitals(waiting=[])[2][-1] == ZONE
    assert _vitals(waiting=None)[2][-1] == ZONE


def test_publishing_what_a_zone_waits_for_keeps_it_for_the_vitals():
    c, _ = _build({"num_zones": 1, "hardware": HARDWARE})
    room = c.rooms[0]
    controller.Controller._publish_waiting_for(room, 1, None, None, NOW)
    assert room._waiting == {1: ([], NOW)}


# ---------------------------------------------------------------- where its push goes
class Router:
    def __init__(self, status=200, answer=None):
        self.status, self.answer, self.sent = status, answer or {"sent_to": [], "error": None}, []

    def __call__(self, domain, service, data, timeout=12):
        self.sent.append((domain, service, dict(data)))
        return self.status, self.answer


def _option(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("notify", "mobile_app_old_phone")]


KINDS = ["emergency", "hardware", "sensors", "watering", "phases", "vitals", "stock", "dosing", "jev", "setup"]


def test_with_a_phone_set_up_the_vitals_go_as_their_kind_and_never_to_the_option(monkeypatch):
    routed = Router()
    monkeypatch.setattr(controller, "ha_service_response", controller.ha_service_response)
    states = {CONFIG: ("4", {"recipients": 2, "idle_hours": 3, "kinds": KINDS})}
    c, fake, lines = _vitals(states, options={"notify_service": OPTION}, router=routed)
    [(domain, service, data)] = routed.sent
    assert (domain, service) == ("crop_steering", "notify")
    assert data == {"key": "vitals", "event": "vitals", "title": f"{c.instance_name} vitals",
                    "message": "\n".join(lines)}
    assert _option(fake) == []  # nobody ticking Vitals is not a failure: the option gets nothing


@pytest.mark.parametrize(
    "attrs",
    [
        None,  # an integration from before notifications
        {"recipients": 0, "idle_hours": 3, "kinds": KINDS},  # nobody set up
        {"recipients": 2, "idle_hours": 3},  # an integration without the vitals kind
        {"recipients": 2, "idle_hours": 3, "kinds": [k for k in KINDS if k != "vitals"]},
    ],
)
def test_otherwise_the_vitals_go_to_the_option_exactly_as_before(monkeypatch, attrs):
    routed = Router()
    monkeypatch.setattr(controller, "ha_service_response", controller.ha_service_response)
    states = {CONFIG: ("4", attrs)} if attrs is not None else {}
    c, fake, lines = _vitals(states, options={"notify_service": OPTION}, router=routed)
    assert routed.sent == []
    assert _option(fake) == [{"title": f"{c.instance_name} vitals", "message": "\n".join(lines)}]


@pytest.mark.parametrize("status, answer", [(500, None), (200, {"sent_to": [], "error": "every phone failed"})])
def test_vitals_the_integration_did_not_take_go_to_the_option_once(monkeypatch, status, answer):
    routed = Router(status, answer)
    monkeypatch.setattr(controller, "ha_service_response", controller.ha_service_response)
    states = {CONFIG: ("4", {"recipients": 1, "idle_hours": 3, "kinds": KINDS})}
    _c, fake, _lines = _vitals(states, options={"notify_service": OPTION}, router=routed)
    assert len(routed.sent) == 1 and len(_option(fake)) == 1
