"""A hold entity Home Assistant does not have is named at start, before anything is watered (CS-210).

A hold in the `hold_entities` option that does not exist (a typo, a helper deleted) holds every shot of
every room (_blocked, test_hold_entity_unreadable.py). That hold only shows once the kill switch is on,
in a zone's status. Now the controller asks Home Assistant for each hold when it starts, whatever the
kill switches say, and one card names every missing one. It goes once each one exists.
"""

import pytest

import controller
from test_controller import _build, _desc

pytestmark = pytest.mark.usefixtures("settings_built_in")

KILL = "input_boolean.kill"
DOSING = "input_boolean.tank_dosing"
FILL = "input_boolean.tank_fill"
FLUSH = "input_boolean.flush"
CARD = "f2_holds_missing"


class _Stop(BaseException):
    """Ends run()'s endless loop: an Exception would be logged as a loop error and the loop carry on."""


def _build_with(holds, present=(DOSING,), kill="off"):
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL)),
        KILL: (kill, {}),
        "switch.crop_steering_zone_1_enabled": ("on", {}),
        "switch.crop_steering_zone_1_manual_override": ("off", {}),
    }
    states.update({entity: ("off", {}) for entity in present})
    return _build({"num_zones": 1, "enable_flag": KILL, "hold_entities": list(holds)}, states=states)


def _cards(fake, service="create"):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", service) and d["notification_id"] == CARD]


def _start(c, fake, monkeypatch, passes=1):
    """run() as the app starts it, for `passes` loops -> how many calls had gone to Home Assistant as
    each loop began."""
    seen = []
    monkeypatch.setattr(c, "_log_timezone", lambda: None)
    monkeypatch.setattr(c, "_start_dosing", lambda: None)
    monkeypatch.setattr(c, "loop_once", lambda now: seen.append(len(fake.calls)))

    def sleep(_seconds):
        if len(seen) >= passes:
            raise _Stop

    monkeypatch.setattr(c, "_sleep_for", sleep)
    with pytest.raises(_Stop):
        c.run()
    return seen


def test_the_start_names_every_missing_hold_in_one_card_with_the_kill_switch_off(monkeypatch):
    c, fake = _build_with([DOSING, FILL, FLUSH], present=(DOSING,))
    seen = _start(c, fake, monkeypatch)
    [card] = _cards(fake)
    assert card["title"] == "2 hold entities not in Home Assistant, no shots (CS-210)"
    assert f"Not in Home Assistant: {FILL}, {FLUSH}" in card["message"]
    assert DOSING not in card["message"]
    assert "remove it from the app's hold entities, or create it" in card["message"]
    assert card["message"].endswith("Code CS-210. What it means and what to do: "
                                    "Crop Steering → Help & tools → Error codes.")
    # raised before the first loop began, while nothing is watered: the kill switch is off
    assert fake.calls.index(("persistent_notification", "create", card)) < seen[0]
    assert fake.states[KILL][0] == "off"
    assert not [call for call in fake.calls if call[0] in ("switch", "valve")]


def test_one_missing_hold_is_named_on_its_own():
    c, fake = _build_with([DOSING, FILL], present=(DOSING,))
    c._check_holds()
    [card] = _cards(fake)
    assert card["title"] == "Hold entity not in Home Assistant, no shots (CS-210)"
    assert card["message"].count(FILL) == 1 and "For it: remove it" in card["message"]


def test_a_missing_hold_still_holds_every_shot():
    c, fake = _build_with([FILL], present=(), kill="on")
    c._check_holds()
    assert c._blocked(c.rooms[0], 1) == (
        f"Hold entity {FILL} does not exist in Home Assistant. Remove it from the app's hold entities, "
        "or create it.")


def test_no_missing_hold_raises_no_card_and_takes_down_one_a_previous_run_left(monkeypatch):
    c, fake = _build_with([DOSING], present=(DOSING,))
    _start(c, fake, monkeypatch, passes=3)
    assert _cards(fake) == []
    assert len(_cards(fake, "dismiss")) == 1  # once, at start; then nothing more is asked
    assert c._holds_card is False


def test_the_card_goes_once_each_missing_hold_exists(monkeypatch):
    c, fake = _build_with([DOSING, FILL], present=(DOSING,))
    c._check_holds()
    assert len(_cards(fake)) == 1 and c._holds_card is True
    c._check_holds()  # still missing: the same card, inside its quiet period, nothing new
    assert len(_cards(fake)) == 1 and _cards(fake, "dismiss") == []
    fake.set_state(FILL, "off")  # created
    c._check_holds()
    assert len(_cards(fake, "dismiss")) == 1 and c._holds_card is False


def test_a_hold_nothing_answered_for_is_asked_again_not_called_missing(monkeypatch):
    """Home Assistant still starting: no 404, so no card, and no dismiss on a guess either."""
    c, fake = _build_with([DOSING], present=(DOSING,))
    monkeypatch.setattr(controller, "ha_get_status", lambda entity, timeout=8: (None, controller.HAState()))
    c._check_holds()
    assert _cards(fake) == [] and _cards(fake, "dismiss") == [] and c._holds_card is None
    monkeypatch.setattr(controller, "ha_get_status", fake.ha_get_status)
    c._check_holds()
    assert len(_cards(fake, "dismiss")) == 1 and c._holds_card is False


def test_no_hold_set_up_asks_nothing(monkeypatch):
    """An old install without the option: no read, no card, no dismiss, at start or after."""
    c, fake = _build_with([], present=())
    asked = []
    monkeypatch.setattr(controller, "ha_get_status", lambda entity, timeout=8: asked.append(entity))
    fake.calls.clear()
    _start(c, fake, monkeypatch, passes=3)
    assert asked == [] and fake.calls == []


def test_the_start_check_needs_nothing_new_in_the_options():
    c, fake = _build({"num_zones": 1, "enable_flag": KILL},
                     states={"sensor.crop_steering_engine_config": ("ok", _desc(enable_flag=KILL))})
    assert c.hold_entities == [] and c._holds_card is None
