"""The zone's setpoints follow its own highest readings, in a real Home Assistant, with the real controller.

6 Oct 2026, the owner: the P1 target is the highest VWC of the grow-day before, field capacity rises as the sensor
does, and the re-water threshold moves with field capacity, within each number's own min and max. Bounded: each moves
at most a point a grow-day, the rescue floor never moves, and nothing is written until a lights-on has kept a day
before. The AI assistant's
Setpoints judge keeps its P2 shot size (and centres its range on the moved threshold); the learner writes neither
the P1 target nor field capacity.

It starts from a seeded old install (tests_ha/fixtures/entry_3_8_learned_tent.json): the state file controller 3.8.0
wrote, with none of the new keys. Every number the controller writes is replayed into the real entity, so it must be
one Home Assistant accepts, under the id the integration registered.
"""

import functools
import json
import os
from datetime import datetime
from types import SimpleNamespace

from test_recreated_room_controller import _see
from test_upgrade_in_place import _upgrade

KILL = "switch.crop_steering_engine_enabled"
# The AI assistant on, so its Setpoints judge runs. Nothing here asks it anything.
JEV = {"enable_flag": KILL, "brain_provider": "claude_haiku", "anthropic_api_key": "fixture-anthropic-key"}
NUMBER = "number.crop_steering_zone_1_"
SENSOR = "sensor.crop_steering_zone_1_auto_setpoints"


class _Clock(datetime):
    """The controller's wall clock, pinned to 6 Oct."""

    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is None else cls.current.astimezone(tz)


async def _learned_tent(hass, controller_for, monkeypatch):
    import controller
    import brain_bridge
    import jev_kit
    from brain.client import Asker

    # The brain's asker without its background worker: nothing in this test asks it anything, and a
    # worker thread would outlive the test (Home Assistant's test harness fails on that).
    monkeypatch.setattr(brain_bridge, "Asker", functools.partial(Asker, threaded=False))
    _entry, seed = await _upgrade(hass, "entry_3_8_learned_tent.json")
    assert hass.states.get("switch.crop_steering_auto_setpoints").state == "on"
    jev_kit.sdk(monkeypatch, jev_kit.FakeTransport({}))
    c, fake, _clock = controller_for(JEV, saved_state=seed["controller_saved"])
    assert brain_bridge.owns_setpoints(c)
    room = c.rooms[0]
    assert room._setup_pending is None  # 3.8.0's state file is carried straight on
    c._refresh_lights(room)
    monkeypatch.setattr(controller, "datetime", _Clock)
    return c, fake, room, seed


def _value(hass, suffix):
    return float(hass.states.get(NUMBER + suffix).state)


async def test_the_p1_target_and_field_capacity_follow_the_highest_reading_and_the_ladder_moves_with_them(
    hass, controller_for, monkeypatch
):
    c, fake, room, seed = await _learned_tent(hass, controller_for, monkeypatch)
    st = room.state[1]
    assert st["peak_prev"] is None  # an old install: nothing is written until a lights-on keeps a day before
    before = {s: _value(hass, s) for s in ("p1_target_vwc", "field_capacity", "p2_vwc_threshold",
                                           "p3_emergency_vwc_threshold", "p2_shot_size")}
    assert before == {"p1_target_vwc": 29.5, "field_capacity": 50.0, "p2_vwc_threshold": 27.5,
                      "p3_emergency_vwc_threshold": 20.0, "p2_shot_size": 6.0}

    st["peak"] = st["fc_follow"]["peak"] = 71.48  # a production zone's highest reading of 5 Oct
    _Clock.current = now = datetime(2026, 10, 6, 5, 0)
    st["phase"] = "P3"
    fake.calls.clear()
    c._auto_tick(room, 1, SimpleNamespace(vwc=39.3, ec=5.1, dryback_rate=0.0), c._params(room, 1), False, now)
    ladder = {NUMBER + s for s in ("field_capacity", "p1_target_vwc", "p2_vwc_threshold", "p3_emergency_vwc_threshold")}
    assert not [d for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value") and d["entity_id"] in ladder]

    st["peak_prev"], st["peak"] = 71.48, 39.3  # the lights-on keeps the grow-day's peak as the day before's
    st["fc_follow"]["peak"] = 39.3
    fake.calls.clear()
    c._auto_tick(room, 1, SimpleNamespace(vwc=39.3, ec=5.1, dryback_rate=0.0), c._params(room, 1), False, now)
    sent = [(d["entity_id"], d["value"]) for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value")]
    for entity, value in sent:  # into the real entities: Home Assistant must accept every one
        await hass.services.async_call("number", "set_value", {"entity_id": entity, "value": value}, blocking=True)
    _see(hass, fake)

    # 50 -> 71.5 is 21.5 points: one point today, the re-water threshold with it, the rescue floor where it was
    assert sent == [(NUMBER + "field_capacity", 51.0), (NUMBER + "p1_target_vwc", 30.5),
                    (NUMBER + "p2_vwc_threshold", 28.5)]
    after = {s: _value(hass, s) for s in before}
    assert after == {"p1_target_vwc": 30.5, "field_capacity": 51.0, "p2_vwc_threshold": 28.5,
                     "p3_emergency_vwc_threshold": 20.0, "p2_shot_size": 6.0}  # the judge's shot size untouched

    owners = fake.sets[SENSOR][1]["managed_by"]
    assert owners[NUMBER + "p1_target_vwc"] == "the zone's highest reading of the grow-day before"
    assert owners[NUMBER + "field_capacity"] == "the zone's highest reading of this grow-day or the one before"
    assert owners[NUMBER + "p2_shot_size"] == "the AI assistant's Setpoints judge, one notch a night"

    # The rest of the grow-day moves nothing more: its point is spent.
    fake.calls.clear()
    c._auto_tick(room, 1, SimpleNamespace(vwc=39.3, ec=5.1, dryback_rate=0.0), c._params(room, 1), False, now)
    assert not [d for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value") and d["entity_id"] in ladder]

    # The next grow-day keeps a lower day: 51 -> 48 is 3 down. One point, the ladder written from the bottom.
    _Clock.current = now = datetime(2026, 10, 7, 5, 0)
    st["peak_prev"], st["peak"], st["fc_follow"]["peak"] = 48.0, 39.3, 39.3
    fake.calls.clear()
    c._auto_tick(room, 1, SimpleNamespace(vwc=39.3, ec=5.1, dryback_rate=0.0), c._params(room, 1), False, now)
    sent = [(d["entity_id"], d["value"]) for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value")]
    for entity, value in sent:
        await hass.services.async_call("number", "set_value", {"entity_id": entity, "value": value}, blocking=True)
    _see(hass, fake)
    assert sent == [(NUMBER + "p2_vwc_threshold", 27.5), (NUMBER + "p1_target_vwc", 31.5),
                    (NUMBER + "field_capacity", 50.0)]
    assert {s: _value(hass, s) for s in before} == {"p1_target_vwc": 31.5, "field_capacity": 50.0,
                                                    "p2_vwc_threshold": 27.5, "p3_emergency_vwc_threshold": 20.0,
                                                    "p2_shot_size": 6.0}

    c._save_state()
    saved = json.loads(open(os.environ["F2_STATE_PATH"], encoding="utf-8").read())
    zone = saved["default"]["1"]
    assert zone["peak"] == 39.3 and zone["peak_prev"] == 48.0
    assert zone["fc_follow"] == {"peak": 39.3, "day": "2026-10-06",
                                 "used": {"field_capacity": 1.0, "p1_target_vwc": 1.0, "p2_vwc_threshold": 1.0}}
    assert not {"day_ceiling", "p1_entry", "stale_target"} & set(zone["learn"])  # the 2-point limit is gone
    assert saved["default"]["_setup"] == seed["controller_saved"]["default"]["_setup"]
