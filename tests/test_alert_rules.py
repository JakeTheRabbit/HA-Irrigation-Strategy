"""Threshold alert rules (G6): the pure rule, its lifecycle and replay (alert_rules.py), and the
evaluator and services in site_api.py driven over a fake Home Assistant.

Rules only notify: nothing here may call a switch, a valve or a number.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import alert_rules, site_api  # noqa: E402
from custom_components.crop_steering.alert_rules import (  # noqa: E402
    replay,
    step,
    summary_sentence,
    validate_rule,
)
from custom_components.crop_steering.const import DOMAIN  # noqa: E402

TZ = timezone(timedelta(hours=13))
T0 = datetime(2026, 10, 21, 0, 0, tzinfo=TZ)
LIGHTS = (6.0, 18.0)  # lights on 06:00, off 18:00
ROOM = "room:f2_"


def at(hh, mm=0, ss=0):
    return T0.replace(hour=hh, minute=mm, second=ss)


def rule(**kw):
    base = {
        "room_id": ROOM,
        "source": "tank.level",
        "op": "below",
        "threshold": 30,
        "min_duration_s": 120,
    }
    return validate_rule({**base, **kw})


def run(r, points, muted=False):
    """step() over [(time, value)] -> the events in order, with the final state."""
    state, events = {}, []
    for t, v in points:
        state, event = step(state, v, t, r, LIGHTS, muted)
        if event:
            events.append((event, t))
    return events, state


# ------------------------------------------------------------------ the lifecycle
def test_a_1_min_spike_does_not_fire_a_2_min_rule():
    r = rule()
    events, state = run(
        r, [(at(10), 50), (at(10, 1), 20), (at(10, 2), 50), (at(10, 3), 50)]
    )
    assert events == [] and state["state"] == "armed"


def test_a_3_min_breach_fires_once_and_clears_when_back():
    r = rule()
    points = [(at(10, m), 20) for m in range(0, 4)] + [(at(10, 4), 45)]
    events, state = run(r, points)
    assert events == [("raised", at(10, 2)), ("cleared", at(10, 4))]
    assert state["state"] == "armed"


def test_none_never_fires_and_never_clears():
    r = rule(min_duration_s=0)
    events, _ = run(r, [(at(10, m), None) for m in range(5)])
    assert events == []
    events, state = run(r, [(at(10), 20), (at(10, 1), None), (at(10, 2), None)])
    assert events == [("raised", at(10))] and state["state"] == "firing"


def test_outside_its_window_a_breach_is_ignored():
    r = rule(window="lights_on")
    events, _ = run(r, [(at(3, m), 10) for m in range(10)])  # lights off at 03:00
    assert events == []
    events, _ = run(r, [(at(7, m), 10) for m in range(10)])
    assert [e for e, _ in events] == ["raised"]


def test_muted_room_holds_non_emergency_rules():
    r = rule(min_duration_s=0)
    events, state = run(r, [(at(10, m), 10) for m in range(5)], muted=True)
    assert events == [] and state["state"] == "muted"
    # The evaluator never mutes a rule routed to emergencies.
    hass, evaluator, _ = rig({"sensor.crop_steering_f2_tank_level": "10"})
    hass.data[DOMAIN]["_notify"] = SimpleNamespace(
        error=None, muted=lambda room: room == "f2_"
    )
    assert evaluator.muted(rule()) is True
    assert evaluator.muted(rule(routing="emergency", severity="emergency")) is False


def test_an_inactive_rule_is_a_draft_and_a_firing_one_clears():
    r = rule(min_duration_s=0)
    state, event = step({}, 10, at(10), r, LIGHTS, False)
    assert event == "raised"
    state, event = step(state, 10, at(10, 1), {**r, "active": False}, LIGHTS, False)
    assert (state["state"], event) == ("draft", "cleared")


# ------------------------------------------------------------------ the rule
def test_climate_sources_are_refused():
    with pytest.raises(ValueError, match="climate"):
        validate_rule(
            {"room_id": ROOM, "source": "room.vpd", "op": "above", "threshold": 1.4}
        )
    with pytest.raises(ValueError, match="source must be one of"):
        validate_rule(
            {"room_id": ROOM, "source": "nope", "op": "above", "threshold": 1}
        )


def test_what_a_rule_must_carry():
    with pytest.raises(ValueError, match="needs at least one zone"):
        validate_rule(
            {"room_id": ROOM, "source": "zone.vwc", "op": "below", "threshold": 40}
        )
    with pytest.raises(ValueError, match="entity_id"):
        validate_rule(
            {
                "room_id": ROOM,
                "source": "probe.silence_s",
                "op": "above",
                "threshold": 600,
            }
        )
    with pytest.raises(ValueError, match="tank_id"):
        validate_rule(
            {"room_id": ROOM, "source": "stock.litres", "op": "below", "threshold": 5}
        )
    with pytest.raises(ValueError, match="routing"):
        rule(routing="nobody")
    saved = rule()
    assert saved["unit"] == "%" and saved["window"] == {"kind": "all"}
    assert saved["routing"] == "sensors" and saved["severity"] == "warning"
    assert len(saved["id"]) == 26


def test_summary_sentence():
    r = rule(min_duration_s=600, window="lights_on")
    assert summary_sentence(r) == (
        "Tell when F2 tank level stays below 30% for 10 min during lights-on."
    )


# ------------------------------------------------------------------ replay
def series(values, start=at(0), step_min=1):
    return [(start + timedelta(minutes=i * step_min), v) for i, v in enumerate(values)]


def test_replay_counts_yesterdays_fires_and_says_so():
    r = rule(min_duration_s=0)
    samples = [(at(0), 50)]
    for hh, mm in ((6, 12), (11, 40), (19, 5)):
        samples += [(at(hh, mm), 20), (at(hh, mm + 1), 50)]
    out = replay(samples, r, LIGHTS, end=at(23, 59))
    assert out["count"] == 3
    assert out["sentence"] == (
        "This rule would have fired 3 times yesterday — 06:12, 11:40, 19:05."
    )
    quiet = replay([(at(0), 50), (at(9), 41), (at(10), 60)], r, LIGHTS)
    assert quiet["count"] == 0
    assert (
        quiet["sentence"] == "It wouldn't have fired in the last 24 h. Lowest was 41%."
    )


def test_replay_warns_when_noisy():
    r = rule(min_duration_s=0)
    samples = []
    for i in range(14):
        samples += [(at(i, 0), 20), (at(i, 1), 50)]
    out = replay(samples, r, LIGHTS)
    assert out["count"] == 14
    assert out["sentence"] == (
        "That's 14 messages a day. Try a longer wait or a lower threshold."
    )


def test_replay_reports_fire_spans_and_ignored_dips():
    r = rule()  # 2 min
    samples = [
        (at(8), 50),
        (at(8, 10), 20),  # a 1-min dip
        (at(8, 11), 50),
        (at(9), 20),  # 3 minutes below
        (at(9, 3), 50),
    ]
    out = replay(samples, r, LIGHTS, end=at(10))
    assert out["fires"] == [
        {
            "start": at(9).isoformat(),
            "fired_at": (at(9) + timedelta(minutes=2)).isoformat(),
            "end": at(9, 3).isoformat(),
        }
    ]
    assert out["ignored"] == [
        {
            "start": at(8, 10).isoformat(),
            "end": at(8, 11).isoformat(),
            "reason": "shorter than min_duration",
        }
    ]
    assert (out["min"], out["max"]) == (20, 50)
    assert out["series"][0] == [at(8).isoformat(), 50]


def test_replay_names_a_breach_outside_its_window_and_one_while_muted():
    r = rule(window="lights_on", min_duration_s=0)
    out = replay([(at(3), 10), (at(4), 50)], r, LIGHTS)
    assert out["count"] == 0
    assert out["ignored"] == [
        {
            "start": at(3).isoformat(),
            "end": at(4).isoformat(),
            "reason": "outside window",
        }
    ]
    out = replay(
        [(at(9), 10), (at(10), 50)],
        rule(min_duration_s=0),
        LIGHTS,
        muted=[(at(9), at(9, 30))],
    )
    assert out["ignored"][0]["reason"] == "muted"
    assert out["fires"][0]["fired_at"] == at(9, 30).isoformat()


def test_the_series_is_downsampled_to_1440_points():
    samples = series([50] * 3000, step_min=1)
    samples[1500] = (samples[1500][0], 5)
    out = replay(samples, rule(threshold=1), LIGHTS)
    assert len(out["series"]) <= 1440
    assert min(v for _, v in out["series"]) == 5  # the worst point survives


# ------------------------------------------------------------------ the evaluator
event = sys.modules.setdefault(
    "homeassistant.helpers.event",
    __import__("types").ModuleType("homeassistant.helpers.event"),
)
event.async_track_time_interval = getattr(
    event, "async_track_time_interval", lambda hass, action, interval: (lambda: None)
)
event.async_track_state_change_event = getattr(
    event, "async_track_state_change_event", lambda hass, ids, action: (lambda: None)
)


class Store:
    def __init__(self, value=None):
        self.value = value

    async def async_load(self):
        return self.value

    async def async_save(self, value):
        self.value = value


class Notifier:
    error = None

    def __init__(self):
        self.sent = []

    def muted(self, room):
        return False

    async def send(self, data):
        self.sent.append(data)
        return {"sent_to": ["notify.mobile_app_ben"], "error": None}


class Hub:
    failed = closed = False

    def __init__(self, events):
        self.events = events
        self.asked = []

    async def query(self, **kw):
        self.asked.append(kw)
        return {
            "events": [e for e in self.events if e["kind"] in kw["kinds"]],
            "cursor": None,
        }


def rig(states=None, now=None):
    entry = ha_stubs.FakeEntry(
        data={"room_prefix": "f2_", "room_name": "F2", "num_zones": 2}, entry_id="f2"
    )
    hass = ha_stubs.FakeHass(states=states, entries=[entry], data={DOMAIN: {}})
    hass.config = SimpleNamespace(components=set())
    hass.tasks = []
    hass.async_create_task = lambda coro: hass.tasks.append(asyncio.ensure_future(coro))
    site = site_api.SiteStore(hass, Store())
    asyncio.run(site.async_init())
    evaluator = site.alerts = site_api.RuleEvaluator(hass, site)
    evaluator._now = lambda: now or at(10)
    hass.data[DOMAIN]["_site"] = site
    return hass, evaluator, site


def save(site, r):
    rev = site.document["alert_rules_revision"]
    return asyncio.run(site.save_rule({"rule": r, "expected_revision": rev}))


def test_probe_silence_rule_fires_after_its_minutes():
    probe = "sensor.f2_probe_1_vwc"
    hass, evaluator, site = rig()
    hass.states.set(probe, "41.2", last_updated=at(9, 49))  # 11 min ago
    saved = save(
        site,
        {
            "room_id": ROOM,
            "source": "probe.silence_s",
            "entity_id": probe,
            "op": "above",
            "threshold": 600,
        },
    )["rule"]
    assert evaluator.states[saved["id"]]["state"] == "firing"
    assert evaluator.value(saved, at(10)) == 660
    # Unavailable counts as silent since its last numeric report.
    hass.states.set(
        probe, "unavailable", last_updated=at(10, 5), last_changed=at(10, 5)
    )
    assert evaluator.value(saved, at(10, 6)) == 17 * 60
    # A rule on a probe that is not there at all reads nothing and does not fire.
    other = validate_rule({**saved, "entity_id": "sensor.gone"}, "x")
    assert evaluator.value(other, at(10)) is None


def test_stock_litres_rule_reads_the_stock_store():
    hass, evaluator, site = rig()
    tanks = [{"id": "bloom", "level_l": 4.0, "capacity_l": 20.0}]
    hass.data[DOMAIN]["_stock"] = {
        "f2": SimpleNamespace(room_id=ROOM, error=None, data={"tanks": tanks})
    }
    litres = rule(source="stock.litres", tank_id="bloom", threshold=5, min_duration_s=0)
    pct = rule(source="stock.pct", tank_id="bloom", threshold=25, min_duration_s=0)
    assert evaluator.value(litres, at(10)) == 4.0
    assert evaluator.value(pct, at(10)) == 20.0
    assert evaluator.value({**litres, "tank_id": "veg"}, at(10)) is None
    saved = save(site, {**litres, "id": None})["rule"]
    assert evaluator.states[saved["id"]]["state"] == "firing"


def test_sources_not_built_yet_save_and_read_none():
    """zone_N_flow_ratio and the controller heartbeat have no producer yet: the rule saves, reads None
    and never fires."""
    hass, evaluator, site = rig()
    for r in (
        {
            "room_id": ROOM,
            "source": "zone.flow_ratio",
            "zones": [1],
            "op": "below",
            "threshold": 80,
        },
        {
            "room_id": ROOM,
            "source": "controller.heartbeat",
            "op": "above",
            "threshold": 300,
        },
    ):
        saved = save(site, {**r, "min_duration_s": 0})["rule"]
        assert evaluator.value(saved, at(10)) is None
        assert evaluator.states[saved["id"]]["state"] == "armed"
    hass.states.set("sensor.crop_steering_f2_zone_1_flow_ratio", "0.5")
    flow = site.rules()[0]
    assert evaluator.value(flow, at(10)) == 50.0
    hass.states.set(
        "sensor.crop_steering_f2_ai_heartbeat", "ok", last_updated=at(9, 50)
    )
    assert evaluator.value(site.rules()[1], at(10)) == 600


def test_feed_rules_read_the_corrected_probe_only_while_applied():
    hass, evaluator, _ = rig(
        {
            "sensor.crop_steering_f2_engine_config": ha_stubs.FakeState(
                "ok", {"feed_ph_sensor": "sensor.raw_ph"}
            ),
            "sensor.raw_ph": "6.4",
            "sensor.crop_steering_f2_feed_ph_corrected": ha_stubs.FakeState(
                "5.9", {"applied": False}
            ),
        }
    )
    r = rule(source="feed.ph", threshold=5.5, op="above")
    assert evaluator.value(r, at(10)) == 6.4
    hass.states.set(
        "sensor.crop_steering_f2_feed_ph_corrected", "5.9", {"applied": True}
    )
    assert evaluator.value(r, at(10)) == 5.9


def test_a_raised_rule_is_journaled_and_pushed_by_its_routing_and_never_touches_water():
    hass, evaluator, site = rig({"sensor.crop_steering_f2_tank_level": "12"})
    notifier = hass.data[DOMAIN]["_notify"] = Notifier()
    noted = []
    site_api.note = lambda hass, room_id, kind, **kw: noted.append((room_id, kind, kw))
    try:

        async def go():
            save_result = await site.save_rule(
                {
                    "rule": {**rule(routing="stock"), "id": None, "min_duration_s": 0},
                    "expected_revision": 0,
                }
            )
            await asyncio.gather(*hass.tasks)
            return save_result

        saved = asyncio.run(go())["rule"]
    finally:
        from custom_components.crop_steering import journal_api

        site_api.note = journal_api.note
    kinds = [k for _, k, _ in noted]
    assert kinds == ["config.changed", "alert.raised"]
    raised = noted[1][2]["data"]
    assert raised == {
        "rule_id": saved["id"],
        "value": 12.0,
        "threshold": 30.0,
        "title": "F2 tank level below 30%",
    }
    assert noted[0][2]["data"]["section"] == "alert_rules"
    (push,) = notifier.sent
    assert push["kinds"] == ["stock"] and push["key"] == f"rule_{saved['id']}"
    assert push["room"] == "f2_" and push["urgent"] is False
    assert hass.services.calls == []  # nothing switched, pressed or set


def test_list_carries_last_fired_firing_since_and_current_value():
    hass, evaluator, site = rig({"sensor.crop_steering_f2_tank_level": "12"})
    saved = save(site, {**rule(min_duration_s=0), "id": None})["rule"]
    quiet = save(site, {**rule(threshold=5), "id": None})["rule"]
    hass.data[DOMAIN]["_journal"] = Hub(
        [
            {
                "kind": "alert.raised",
                "ts": "2026-10-21T09:00:00+13:00",
                "data": {"rule_id": saved["id"]},
            },
            {
                "kind": "alert.raised",
                "ts": "2026-10-20T09:00:00+13:00",
                "data": {"rule_id": saved["id"]},
            },
        ]
    )
    listed = asyncio.run(evaluator.listing())["rules"]
    first, second = listed
    assert first["id"] == saved["id"] and first["state"] == "firing"
    assert first["last_fired"] == "2026-10-21T09:00:00+13:00"
    assert first["firing_since"] == at(10).isoformat()
    assert (first["current_value"], first["unit"]) == (12.0, "%")
    assert first["summary_sentence"] == "Tell when F2 tank level goes below 30%."
    assert second["id"] == quiet["id"] and second["state"] == "armed"
    assert (second["last_fired"], second["firing_since"]) == (None, None)
    assert asyncio.run(evaluator.listing("room:veg_")) == {"rules": []}


def test_saves_take_the_revision_and_a_delete_takes_the_rule_away():
    hass, evaluator, site = rig()
    with pytest.raises(site_api.StaleRevision):
        asyncio.run(
            site.save_rule({"rule": {**rule(), "id": None}, "expected_revision": 3})
        )
    with pytest.raises(ValueError, match="unknown"):
        save(site, {**rule(), "room_id": "room:veg_", "id": None})
    saved = save(site, {**rule(), "id": None})
    assert saved["revision"] == 1
    changed = save(site, {**saved["rule"], "threshold": 25})
    assert changed["rule"]["id"] == saved["rule"]["id"] and len(site.rules()) == 1
    with pytest.raises(ValueError, match="No alert rule"):
        save(site, {**rule(), "id": "01JAAAAAAAAAAAAAAAAAAAAAAA"})
    asyncio.run(site.delete_rule({"id": saved["rule"]["id"], "expected_revision": 2}))
    assert site.rules() == [] and site.document["alert_rules_revision"] == 3
    assert evaluator.states == {}


def test_a_site_with_no_rules_watches_nothing():
    hass, evaluator, site = rig()
    evaluator.refresh()
    assert evaluator._unsubs == [] and evaluator._watching == ()


def test_a_test_send_reports_each_phone():
    answer = {
        "sent_to": ["notify.mobile_app_ben"],
        "held": ["notify.mobile_app_sam"],
        "error": "notify.mobile_app_jo: no answer in 8 s",
    }
    assert site_api.delivery(answer) == [
        {"service": "notify.mobile_app_ben", "ok": True, "error": None},
        {
            "service": "notify.mobile_app_sam",
            "ok": False,
            "error": "held for the phone's digest or quiet hours",
        },
        {"service": "notify.mobile_app_jo", "ok": False, "error": "no answer in 8 s"},
    ]
    assert site_api.delivery(
        {"sent_to": [], "error": "no phone is set up for notifications"}
    ) == [
        {"service": None, "ok": False, "error": "no phone is set up for notifications"}
    ]


def test_history_revert_puts_the_alert_rules_back():
    from custom_components.crop_steering import journal_api

    hass, evaluator, site = rig()
    save(site, {**rule(), "id": None})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    data = {
        "store": "site",
        "section": "alert_rules",
        "old": [],
        "new": site.document["alert_rules"],
    }
    out = asyncio.run(
        journal_api._put_back_section(
            hass, entry, ROOM, data, {}, SimpleNamespace(data={}), lambda *a: None
        )
    )
    assert out == {"readback": "verified"}
    assert site.rules() == [] and site.document["alert_rules_revision"] == 2
    assert site.document["presets"] == []  # never the presets


def test_a_rule_push_goes_by_its_own_kind_and_an_emergency_one_past_a_mute():
    from custom_components.crop_steering import notify_api

    hass = ha_stubs.FakeHass()
    notifier = notify_api.Notifier(hass)
    notifier.data["recipients"] = notify_api.clean_recipients(
        [
            {"service": "notify.stock_phone", "kinds": ["stock"]},
            {"service": "notify.sensor_phone", "kinds": ["sensors", "emergency"]},
        ]
    )
    evaluator = site_api.RuleEvaluator(hass, None)
    data = evaluator.push_data(rule(routing="stock"), "t", "m")
    answer = asyncio.run(notifier.send(data))
    assert answer["sent_to"] == ["notify.stock_phone"]
    notifier.data["mutes"] = {"f2_": "2999-01-01T00:00:00+00:00"}
    assert asyncio.run(notifier.send(data))["muted"] is True
    urgent = evaluator.push_data(rule(routing="emergency"), "t", "m")
    assert asyncio.run(notifier.send(urgent))["sent_to"] == ["notify.sensor_phone"]


# ------------------------------------------------------------------ fix round 1
def _raise(states, r):
    hass, evaluator, site = rig(states)
    notifier = hass.data[DOMAIN]["_notify"] = Notifier()

    async def go():
        evaluator.evaluate(r, at(10))
        await asyncio.gather(*hass.tasks)

    asyncio.run(go())
    (push,) = notifier.sent
    return push["title"], push["message"]


@pytest.mark.parametrize(
    "states,kw,title,message",
    [
        (
            {"sensor.crop_steering_f2_vwc_zone_1": "25"},
            {"source": "zone.vwc", "zones": [1], "threshold": 40},
            "F2 zone 1 VWC below 40%",
            "Zone 1 VWC is 25%. Tell when F2 zone 1 VWC goes below 40%.",
        ),
        (
            {
                "sensor.crop_steering_f2_engine_config": ha_stubs.FakeState(
                    "ok", {"feed_ph_sensor": "sensor.raw_ph"}
                ),
                "sensor.raw_ph": "6.5",
            },
            {"source": "feed.ph", "op": "above", "threshold": 6.2},
            "F2 feed pH above pH 6.2",
            "Feed pH is pH 6.5. Tell when F2 feed pH goes above pH 6.2.",
        ),
        (
            {"sensor.crop_steering_f2_ec_zone_2": "4.1"},
            {"source": "zone.ec", "zones": [2], "op": "above", "threshold": 3.5},
            "F2 zone 2 EC above 3.5 mS/cm",
            "Zone 2 EC is 4.1 mS/cm. Tell when F2 zone 2 EC goes above 3.5 mS/cm.",
        ),
    ],
)
def test_the_raised_push_says_exactly_what_crossed(states, kw, title, message):
    assert _raise(states, rule(min_duration_s=0, **kw)) == (title, message)


def test_a_pending_breach_that_leaves_its_window_is_outside_window_not_short():
    r = rule(window="lights_on", min_duration_s=600)  # lights 06:00-18:00
    out = replay([(at(17, 55), 10), (at(18, 30), 50)], r, LIGHTS)
    assert out["count"] == 0
    assert out["ignored"] == [
        {
            "start": at(17, 55).isoformat(),
            "end": at(18, 30).isoformat(),
            "reason": "outside window",
        }
    ]


def test_a_pending_breach_held_by_a_mute_is_muted_not_short():
    r = rule(min_duration_s=600)
    out = replay(
        [(at(9), 10), (at(9, 20), 50)], r, LIGHTS, muted=[(at(9, 5), at(9, 30))]
    )
    assert out["ignored"] == [
        {"start": at(9).isoformat(), "end": at(9, 20).isoformat(), "reason": "muted"}
    ]


def test_a_breach_ended_by_a_missing_reading_has_no_ignored_row():
    r = rule(min_duration_s=600)
    out = replay([(at(9), 10), (at(9, 1), None), (at(9, 10), 50)], r, LIGHTS)
    assert out["ignored"] == [] and out["count"] == 0


def test_wording_names_durations_and_windows():
    probe = rule(
        source="probe.silence_s", entity_id="sensor.slab_1", op="above", threshold=600
    )
    assert summary_sentence(probe, "F2", "Slab 1") == (
        "Tell when F2 Slab 1 silence stays above 10 min for 2 min."
    )
    assert alert_rules.amount(7200, "s") == "2 h"
    assert alert_rules.amount(45, "s") == "45 s"
    assert summary_sentence(rule(min_duration_s=600)).endswith("for 10 min.")
    with pytest.raises(ValueError, match="Start and end can't be the same"):
        rule(window={"kind": "custom", "from": "06:00", "to": "06:00"})


def test_names_come_from_the_stock_store_and_the_probe():
    hass, evaluator, site = rig(
        {"sensor.slab_1": ha_stubs.FakeState("40", {"friendly_name": "Slab 1"})}
    )
    hass.data[DOMAIN]["_stock"] = {
        "f2": SimpleNamespace(
            room_id=ROOM,
            error=None,
            data={
                "tanks": [
                    {
                        "id": "bloom",
                        "name": "Bloom A",
                        "level_l": 4.0,
                        "capacity_l": 20.0,
                    }
                ]
            },
        )
    }
    tank = rule(source="stock.litres", tank_id="bloom", threshold=5)
    assert site_api.rule_title(hass, tank) == "F2 stock tank Bloom A below 5 L"
    probe = rule(
        source="probe.silence_s", entity_id="sensor.slab_1", op="above", threshold=600
    )
    assert site_api.rule_title(hass, probe) == "F2 Slab 1 silence above 10 min"
    assert site_api.rule_title(hass, rule()) == "F2 tank level below 30%"


def test_the_last_rule_deleted_unsubscribes_everything():
    made, undone = [], []

    def track(*a):
        made.append(a)
        return lambda: undone.append(a)

    hass, evaluator, site = rig({"sensor.crop_steering_f2_tank_level": "50"})
    old = (event.async_track_time_interval, event.async_track_state_change_event)
    event.async_track_time_interval = event.async_track_state_change_event = track
    try:
        saved = save(site, {**rule(), "id": None})["rule"]
        assert len(made) == 2 and evaluator._watching
        asyncio.run(site.delete_rule({"id": saved["id"], "expected_revision": 1}))
    finally:
        event.async_track_time_interval, event.async_track_state_change_event = old
    assert len(undone) == 2
    assert evaluator._unsubs == [] and evaluator._watching == ()


def test_after_a_restart_a_silent_probe_counts_from_its_last_recorded_report(
    monkeypatch,
):
    import types

    probe = "sensor.slab_1"
    recorded = [
        ha_stubs.FakeState("41", last_updated=at(9, 20)),
        ha_stubs.FakeState("unavailable", last_updated=at(9, 40)),
    ]
    recorder = types.ModuleType("homeassistant.components.recorder")
    history = types.ModuleType("homeassistant.components.recorder.history")
    history.get_last_state_changes = lambda hass, n, entity_id: {entity_id: recorded}

    class Instance:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    recorder.get_instance = lambda hass: Instance()
    recorder.history = history
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(sys.modules, "homeassistant.components.recorder", recorder)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder.history", history
    )
    hass, evaluator, site = rig()
    hass.config.components = {"recorder"}
    hass.states.set(probe, "unavailable", last_changed=at(9, 58))  # since the restart
    r = rule(source="probe.silence_s", entity_id=probe, op="above", threshold=600)
    assert (
        evaluator.value(r, at(10)) == 120
    )  # nothing remembered: since it went unavailable
    evaluator._running = True  # as refresh() leaves it while the site has rules
    asyncio.run(evaluator.seed_reports([probe]))
    assert evaluator.value(r, at(10)) == 40 * 60  # since its last numeric report


# ------------------------------------------------------------------ fix round 2
def _slow_recorder(monkeypatch, gate, queries):
    import types

    recorder = types.ModuleType("homeassistant.components.recorder")
    history = types.ModuleType("homeassistant.components.recorder.history")

    def changes(hass, n, entity_id):
        queries.append(entity_id)
        return {entity_id: [ha_stubs.FakeState("41", last_updated=at(9))]}

    history.get_last_state_changes = changes

    class Instance:
        async def async_add_executor_job(self, func, *args):
            await gate.wait()
            return func(*args)

    recorder.get_instance = lambda hass: Instance()
    recorder.history = history
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(sys.modules, "homeassistant.components.recorder", recorder)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder.history", history
    )


SILENT = {
    "room_id": ROOM,
    "source": "probe.silence_s",
    "entity_id": "sensor.slab_1",
    "op": "above",
    "threshold": 600,
}


def test_a_seed_that_finishes_after_stop_evaluates_and_pushes_nothing(monkeypatch):
    queries = []
    hass, evaluator, site = rig()
    hass.config.components = {"recorder"}
    notifier = hass.data[DOMAIN]["_notify"] = Notifier()
    hass.states.set("sensor.slab_1", "unavailable", last_changed=at(9, 59))

    async def go():
        gate = asyncio.Event()
        _slow_recorder(monkeypatch, gate, queries)
        await site.save_rule({"rule": SILENT, "expected_revision": 0})
        evaluator.stop()  # the last room unloads while the recorder is still being read
        gate.set()
        await asyncio.gather(*hass.tasks, return_exceptions=True)
        return evaluator, notifier

    evaluator, notifier = asyncio.run(go())
    assert notifier.sent == []
    assert all(s["state"] != "firing" for s in evaluator.states.values())


def test_a_probe_with_no_recorded_number_is_looked_up_once(monkeypatch):
    queries = []
    hass, evaluator, site = rig()
    hass.config.components = {"recorder"}
    hass.states.set("sensor.slab_1", "unavailable", last_changed=at(9, 59))

    async def go():
        gate = asyncio.Event()
        gate.set()
        _slow_recorder(monkeypatch, gate, queries)
        sys.modules[
            "homeassistant.components.recorder.history"
        ].get_last_state_changes = (
            lambda hass, n, entity_id: queries.append(entity_id) or {}
        )
        await site.save_rule({"rule": SILENT, "expected_revision": 0})
        await asyncio.gather(*hass.tasks)
        await site.save_rule(
            {"rule": {**SILENT, "threshold": 900}, "expected_revision": 1}
        )
        await asyncio.gather(*hass.tasks)

    asyncio.run(go())
    assert queries == ["sensor.slab_1"]


def test_a_room_unloaded_during_a_save_gets_no_new_sensors():
    hass, evaluator, site = rig()
    managers = hass.data[DOMAIN][site_api.SENSORS] = {}
    added = []

    class Room:
        def __init__(self, entry_id, drops=None):
            self.entry_id, self.drops = entry_id, drops

        async def remove_gone(self):
            if self.drops:
                managers.pop(self.drops, None)  # that room unloads meanwhile

        def add_new(self):
            added.append(self.entry_id)

    managers["a"] = Room("a", drops="b")
    managers["b"] = Room("b")
    save(site, {**rule(), "id": None})
    assert added == ["a"]
