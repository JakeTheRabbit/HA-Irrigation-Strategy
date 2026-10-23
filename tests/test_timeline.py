"""Timeline (G5): timeline.build and timeline.summarise over journal events and projection_app intents. Pure.

The producers are not built yet (Task 8: shot.* data; Task 15: sensor.crop_steering_<px>projection_app), so the
events and intents here are synthetic, shaped by their contracts:
- shot.started data {phase, kind, reason, size_pct, duration_s, commanded_l, vwc_before, vwc_expected,
  requested_at, pump_wait_s}, with a new correlation.intent_id;
- shot.completed {elapsed_s, commanded_l, metered_l, vwc_before, ec_before} and shot.aborted (outcome aborted or
  failed, a CS-30x code), each with the started intent_id;
- projection_app attribute intents: [{id, zone, at, duration_s, source: timer|engine, program_id?, expected}].
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.crop_steering import timeline
from custom_components.crop_steering.generated.ids import new_id

NZ = ZoneInfo("Pacific/Auckland")
F2, F1 = "room:f2_", "room:f1_"
START = datetime(2026, 10, 22, 0, 0, tzinfo=NZ)
END = START + timedelta(hours=24)
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=NZ)


def _ev(
    kind,
    ts,
    *,
    room=F2,
    zone=3,
    intent=None,
    outcome="ok",
    code=None,
    actor="engine",
    **data,
):
    return {
        "v": 1,
        "id": new_id(),
        "ts": ts.isoformat(),
        "room_id": room,
        "zone": zone,
        "kind": kind,
        "outcome": outcome,
        "code": code,
        "source": {"actor": actor},
        "correlation": {"intent_id": intent},
        "data": data,
    }


def _room(room_id=F2, **over):
    return {
        "room_id": room_id,
        "lights_hours": (6.0, 18.0),
        "pump": None,
        "capacity_lph": None,
        "planned_source": "projection_app",
        "skips": [],
        **over,
    }


def _build(events=(), planned=(), rooms=None, **kw):
    return timeline.build(
        rooms or [_room()],
        list(events),
        list(planned),
        START,
        END,
        now=NOW,
        tz=NZ,
        **kw,
    )


def _blocks(out, room=0):
    return [b for row in out["rooms"][room]["rows"] for b in row["blocks"]]


def _shot(at, *, intent=None, zone=3, end=True, **started):
    intent = intent or new_id()
    data = {
        "phase": "P1",
        "reason": "P1 ramp shot 4",
        "commanded_l": 9.84,
        "duration_s": 60,
        **started,
    }
    out = [_ev("shot.started", at, zone=zone, intent=intent, **data)]
    if end:
        out.append(
            _ev(
                "shot.completed",
                at + timedelta(seconds=60),
                zone=zone,
                intent=intent,
                elapsed_s=60,
                commanded_l=9.84,
                metered_l=None,
            )
        )
    return intent, out


def test_completed_shot_is_a_done_block_with_metered_litres():
    at = datetime(2026, 10, 22, 7, 0, tzinfo=NZ)
    intent, events = _shot(at)
    events.append(
        _ev(
            "flow.reconciled",
            at + timedelta(seconds=61),
            intent=intent,
            ratio=0.946,
            commanded_l=9.84,
            metered_l=9.31,
        )
    )
    (block,) = _blocks(_build(events))
    assert (block["kind"], block["status"], block["id"]) == ("shot", "done", intent)
    assert block["start"] == at.isoformat()
    assert block["end"] == (at + timedelta(seconds=60)).isoformat()
    assert (block["litres"], block["metered_l"]) == (9.84, 9.31)
    assert block["source"] == "engine" and block["code"] is None
    assert block["event_id"] == events[1]["id"]  # the completion
    assert block["skippable"] is False


def test_a_shot_without_a_meter_has_no_metered_litres_and_completed_data_wins():
    _, events = _shot(datetime(2026, 10, 22, 7, 0, tzinfo=NZ))
    (block,) = _blocks(_build(events))
    assert block["metered_l"] is None
    _, events = _shot(datetime(2026, 10, 22, 7, 0, tzinfo=NZ))
    events[1]["data"]["metered_l"] = 9.5
    (block,) = _blocks(_build(events))
    assert block["metered_l"] == 9.5


def test_aborted_shot_is_an_error_block_with_its_code():
    at = datetime(2026, 10, 22, 8, 0, tzinfo=NZ)
    intent, events = _shot(at, end=False)
    events.append(
        _ev(
            "shot.aborted",
            at + timedelta(seconds=20),
            intent=intent,
            outcome="failed",
            code="CS-302",
        )
    )
    out = _build(events)
    (block,) = _blocks(out)
    assert (block["kind"], block["status"], block["code"]) == (
        "shot",
        "error",
        "CS-302",
    )
    assert out["errors"]["count"] == 1
    (marker,) = out["errors"]["markers"]
    assert marker == {
        "room_id": F2,
        "zone": 3,
        "t": at.isoformat(),
        "code": "CS-302",
        "block_id": intent,
    }


def test_planned_blocks_come_from_projection_app_after_now_only():
    past = {
        "id": "p1",
        "zone": 3,
        "at": (NOW - timedelta(hours=1)).isoformat(),
        "duration_s": 120,
        "source": "timer",
        "program_id": "prog",
        "expected": False,
    }
    future = {**past, "id": "p2", "at": (NOW + timedelta(hours=1)).isoformat()}
    out = _build(planned=[{**past, "room_id": F2}, {**future, "room_id": F2}])
    (block,) = _blocks(out)
    assert (block["id"], block["kind"], block["status"]) == ("p2", "planned", "planned")
    assert block["start"] == (NOW + timedelta(hours=1)).isoformat()
    assert block["end"] == (NOW + timedelta(hours=1, seconds=120)).isoformat()
    assert block["skippable"] is True and block["source"] == "timer"
    assert block["litres"] is None  # never invented
    # No projection_app: no planned blocks at all, and the answer says so.
    out = _build(rooms=[_room(planned_source="unavailable")])
    assert out["rooms"][0]["planned_source"] == "unavailable"
    assert _blocks(out) == []


def test_a_planned_block_carries_the_phase_its_intent_expects():
    slot = {
        "id": "t1",
        "zone": 3,
        "at": (NOW + timedelta(hours=2)).isoformat(),
        "duration_s": 60,
        "source": "timer",
        "expected": False,
        "room_id": F2,
    }
    phased = [
        {**slot, "phase": "P2"},
        {
            **slot,
            "id": "t2",
            "at": (NOW + timedelta(hours=3)).isoformat(),
            "phase": None,
        },
        {
            **slot,
            "id": "t3",
            "at": (NOW + timedelta(hours=4)).isoformat(),
            "phase": "x",
        },
        {
            **slot,
            "id": "t4",
            "at": (NOW + timedelta(hours=5)).isoformat(),
        },  # an older controller
    ]
    out = _build(planned=phased)
    assert {b["id"]: b["phase"] for b in _blocks(out)} == {
        "t1": "P2",
        "t2": None,
        "t3": None,
        "t4": None,
    }


def test_a_planned_timer_block_is_drawn_once():
    slot = {
        "id": "t1",
        "zone": 3,
        "at": (NOW + timedelta(hours=2)).isoformat(),
        "duration_s": 60,
        "source": "timer",
        "program_id": "prog",
        "expected": False,
        "room_id": F2,
    }
    out = _build(planned=[slot, dict(slot)])
    assert [b["id"] for b in _blocks(out)] == ["t1"]


def test_engine_expectation_is_marked_expected():
    guess = {
        "id": "e1",
        "zone": 3,
        "at": (NOW + timedelta(minutes=30)).isoformat(),
        "duration_s": 45,
        "source": "engine",
        "expected": True,
        "room_id": F2,
    }
    (block,) = _blocks(_build(planned=[guess]))
    assert block["expected"] is True and block["source"] == "engine"
    assert block["skippable"] is True


def test_span_over_48h_is_refused():
    with pytest.raises(ValueError, match="timeline span is at most 48 h"):
        timeline.build(
            [_room()],
            [],
            [],
            START,
            START + timedelta(hours=48, seconds=1),
            now=NOW,
            tz=NZ,
        )
    out = timeline.build(
        [_room()], [], [], START, START + timedelta(hours=48), now=NOW, tz=NZ
    )
    assert out["rooms"][0]["room_id"] == F2


def test_block_carries_reason_phase_vwc_and_pump_wait():
    at = datetime(2026, 10, 22, 7, 0, tzinfo=NZ)
    requested = (at - timedelta(seconds=75)).isoformat()
    _, events = _shot(
        at, vwc_before=51.2, vwc_expected=53.4, requested_at=requested, pump_wait_s=75.0
    )
    (block,) = _blocks(_build(events))
    assert (block["reason"], block["phase"]) == ("P1 ramp shot 4", "P1")
    assert (block["vwc_before"], block["vwc_expected"]) == (51.2, 53.4)
    assert (block["requested_at"], block["pump_wait_s"]) == (requested, 75.0)
    # A producer that does not send them yet: every one is None.
    intent = new_id()
    bare = [
        _ev("shot.started", at, intent=intent),
        _ev("shot.completed", at + timedelta(seconds=30), intent=intent),
    ]
    (block,) = _blocks(_build(bare))
    assert [block[k] for k in timeline.STARTED_FIELDS] == [None] * 6
    assert (block["litres"], block["metered_l"]) == (None, None)


def test_held_queued_and_alert_are_warning_blocks():
    at = datetime(2026, 10, 22, 9, 0, tzinfo=NZ)
    events = [
        _ev("intent.held", at, outcome="held", code="CS-901", reason="BLOCK tank low"),
        _ev(
            "intent.queued",
            at,
            outcome="queued",
            position=1,
            requested_at=at.isoformat(),
        ),
        _ev(
            "alert.raised",
            at,
            zone=None,
            code="CS-214",
            key="k",
            title="Zone needs more",
        ),
    ]
    out = _build(events)
    kinds = {b["kind"]: b for b in _blocks(out)}
    assert set(kinds) == {"held", "queued", "alert"}
    assert {b["status"] for b in kinds.values()} == {"warning"}
    assert (
        kinds["held"]["reason"] == "BLOCK tank low"
        and kinds["held"]["code"] == "CS-901"
    )
    assert [row["zone"] for row in out["rooms"][0]["rows"]] == [3, None]
    assert out["errors"]["count"] == 0


def test_zones_filter_keeps_only_those_rows():
    _, three = _shot(datetime(2026, 10, 22, 7, 0, tzinfo=NZ), zone=3)
    _, four = _shot(datetime(2026, 10, 22, 7, 5, tzinfo=NZ), zone=4)
    out = _build(three + four, zones=[4])
    assert [row["zone"] for row in out["rooms"][0]["rows"]] == [4]


def test_lights_windows_in_local_time():
    out = _build()
    assert out["rooms"][0]["lights"] == [
        {
            "on": datetime(2026, 10, 22, 6, 0, tzinfo=NZ).isoformat(),
            "off": datetime(2026, 10, 22, 18, 0, tzinfo=NZ).isoformat(),
        }
    ]
    over_midnight = _build(rooms=[_room(lights_hours=(20.0, 8.0))])
    assert [w["on"][:16] for w in over_midnight["rooms"][0]["lights"]] == [
        "2026-10-21T20:00",
        "2026-10-22T20:00",
    ]
    assert _build(rooms=[_room(lights_hours=None)])["rooms"][0]["lights"] == []


PUMP = "switch.main_pump"


def test_pump_load_is_demand_over_capacity_and_none_without_capacity():
    at = datetime(2026, 10, 22, 7, 0, tzinfo=NZ)
    _, events = _shot(at)
    pumps = {PUMP: {F2: {"3": 300.0}}}
    out = _build(events, rooms=[_room(pump=PUMP, capacity_lph=1200.0)], pumps=pumps)
    assert out["rooms"][0]["pump_load"] == [
        {"t": at.isoformat(), "pct": 25.0},
        {"t": (at + timedelta(seconds=60)).isoformat(), "pct": 0.0},
    ]
    assert (out["rooms"][0]["pump"], out["rooms"][0]["pump_rooms"]) == (PUMP, [F2])
    out = _build(events, rooms=[_room(pump=PUMP, capacity_lph=None)], pumps=pumps)
    assert [p["pct"] for p in out["rooms"][0]["pump_load"]] == [None, None]
    out = _build(
        events, rooms=[_room(pump=PUMP, capacity_lph=1200.0)], pumps={PUMP: {F2: {}}}
    )
    assert out["rooms"][0]["pump_load"][0]["pct"] is None
    out = _build(events)  # no pump known
    assert [p["pct"] for p in out["rooms"][0]["pump_load"]] == [None, None]


def test_pump_load_is_the_shared_pumps_total_across_rooms():
    # F1 and F2 share one pump; only F2 is asked for, F1's overlapping shot still loads the pump.
    at = datetime(2026, 10, 22, 7, 0, tzinfo=NZ)
    _, f2 = _shot(at)
    _, f1 = _shot(at + timedelta(seconds=30), zone=1)
    for ev in f1:
        ev["room_id"] = F1
    out = _build(
        f2 + f1,
        rooms=[_room(pump=PUMP, capacity_lph=1200.0)],
        pumps={PUMP: {F2: {"3": 300.0}, F1: {"1": 300.0}}},
    )
    (room,) = out["rooms"]
    assert room["pump_rooms"] == [F1, F2]
    assert [p["pct"] for p in room["pump_load"]] == [25.0, 50.0, 25.0, 0.0]
    assert [r["zone"] for r in room["rows"]] == [3]  # F1's shots are not drawn as F2's


def test_too_many_blocks_answers_the_newest_and_says_truncated(monkeypatch):
    monkeypatch.setattr(timeline, "MAX_BLOCKS", 2)
    events = []
    for minute in range(3):
        events += _shot(datetime(2026, 10, 22, 7, minute, tzinfo=NZ))[1]
    out = _build(events)
    assert out["truncated"] is True
    assert [b["start"][11:16] for b in _blocks(out)] == ["07:01", "07:02"]


def test_summary_counts_failed_and_warning_blocks_per_local_day():
    # 23:30 NZ on the 22nd is 10:30 UTC the same day; 00:30 NZ on the 23rd is still the 22nd in UTC.
    late = datetime(2026, 10, 22, 23, 30, tzinfo=NZ)
    early = datetime(2026, 10, 23, 0, 30, tzinfo=NZ)
    assert early.astimezone(UTC).date().isoformat() == "2026-10-22"
    intent = new_id()
    events = [
        _ev("shot.started", late, intent=intent),
        _ev(
            "shot.aborted",
            late + timedelta(seconds=5),
            intent=intent,
            outcome="aborted",
            code="CS-301",
        ),
        *_shot(early)[1],
        _ev("intent.held", early, outcome="held", reason="BLOCK daily-cap"),
        _ev("intent.queued", early, outcome="queued"),
        _ev("alert.raised", early, zone=None, code="CS-214"),
    ]
    out = timeline.summarise(
        events, ["2026-10-22", "2026-10-23"], rooms=[F2, F1], tz=NZ
    )
    assert out == [
        {
            "date": "2026-10-22",
            "rooms": [
                {
                    "room_id": F2,
                    "shots": 1,
                    "failed": 1,
                    "warnings": 0,
                    "held": 0,
                    "queued": 0,
                },
                {
                    "room_id": F1,
                    "shots": 0,
                    "failed": 0,
                    "warnings": 0,
                    "held": 0,
                    "queued": 0,
                },
            ],
        },
        {
            "date": "2026-10-23",
            "rooms": [
                {
                    "room_id": F2,
                    "shots": 1,
                    "failed": 0,
                    "warnings": 1,
                    "held": 1,
                    "queued": 1,
                },
                {
                    "room_id": F1,
                    "shots": 0,
                    "failed": 0,
                    "warnings": 0,
                    "held": 0,
                    "queued": 0,
                },
            ],
        },
    ]


def test_summary_refuses_more_than_14_days():
    days = [f"2026-10-{d:02d}" for d in range(1, 16)]
    with pytest.raises(ValueError, match="at most 14 days"):
        timeline.summarise([], days, rooms=[F2], tz=NZ)
    assert len(timeline.summarise([], days[:14], rooms=[F2], tz=NZ)) == 14


def _read(events, since, until, *, openers):
    """What the service reads from the journal for [since, until): timeline.windows over the stored events, with
    journal_query's bounds (ts >= since, ts < until, kinds)."""
    out = []
    for low, high, kinds in timeline.windows(since, until, openers=openers):
        out += [
            e
            for e in events
            if e["kind"] in kinds and low <= datetime.fromisoformat(e["ts"]) < high
        ]
    return out


def _midnight_shot():
    intent = new_id()
    at = datetime(2026, 10, 22, 23, 58, tzinfo=NZ)
    return [
        _ev("shot.started", at, intent=intent, duration_s=240),
        _ev("shot.completed", at + timedelta(minutes=4), intent=intent, elapsed_s=240),
    ]


def _day(day):
    since = datetime(2026, 10, day, 0, 0, tzinfo=NZ)
    return since, since + timedelta(days=1)


def test_a_shot_across_midnight_counts_once_on_its_start_day():
    events = _midnight_shot()
    zero = {"shots": 0, "failed": 0, "warnings": 0, "held": 0, "queued": 0}
    done = {**zero, "shots": 1}
    late = timeline.summarise(
        _read(events, *_day(22), openers=False),
        ["2026-10-22"],
        rooms=[F2],
        tz=NZ,
        now=NOW + timedelta(days=2),
    )
    assert late[0]["rooms"][0] == {"room_id": F2, **done}  # done, not an open warning
    early = timeline.summarise(
        _read(events, *_day(23), openers=False),
        ["2026-10-23"],
        rooms=[F2],
        tz=NZ,
        now=NOW + timedelta(days=2),
    )
    assert early[0]["rooms"][0] == {
        "room_id": F2,
        **zero,
    }  # the completion alone is not a shot
    both = timeline.summarise(
        _read(events, *_day(22), openers=False)
        + _read(events, *_day(23), openers=False),
        ["2026-10-22", "2026-10-23"],
        rooms=[F2],
        tz=NZ,
        now=NOW + timedelta(days=2),
    )
    assert [d["rooms"][0] for d in both] == [
        {"room_id": F2, **done},
        {"room_id": F2, **zero},
    ]


def test_timeline_edges_draw_a_shot_across_them_whole():
    events = _midnight_shot()
    later = NOW + timedelta(days=2)
    for since, until in (_day(22), _day(23)):
        out = timeline.build(
            [_room()],
            _read(events, since, until, openers=True),
            [],
            since,
            until,
            now=later,
            tz=NZ,
        )
        (block,) = _blocks(out)
        assert (block["status"], block["running"]) == ("done", False)
        assert block["start"][11:16] == "23:58" and block["end"][11:16] == "00:02"


def test_an_open_shot_is_running_until_its_duration_and_grace_pass():
    at = datetime(2026, 10, 22, 11, 58, tzinfo=NZ)  # 120 s shot, NOW is 12:00
    _, events = _shot(at, end=False, duration_s=120)
    (block,) = _blocks(_build(events))
    assert (block["status"], block["running"]) == ("done", True)
    stale = datetime(2026, 10, 22, 11, 55, tzinfo=NZ)  # 120 s + 120 s grace ended 11:59
    _, events = _shot(stale, end=False, duration_s=120)
    (block,) = _blocks(_build(events))
    assert (block["status"], block["running"]) == ("warning", False)
    # The summary counts a running shot as a shot, not a warning.
    _, events = _shot(at, end=False, duration_s=120)
    (day,) = timeline.summarise(events, ["2026-10-22"], rooms=[F2], tz=NZ, now=NOW)
    assert day["rooms"][0]["shots"] == 1 and day["rooms"][0]["warnings"] == 0
    # A partial completion is still a warning.
    intent, events = _shot(at)
    events[1]["outcome"] = "partial"
    (block,) = _blocks(_build(events))
    assert block["status"] == "warning"


def test_a_skipped_slot_is_marked_and_not_skippable():
    slot_at = NOW + timedelta(hours=2)
    timer = {
        "zone": 3,
        "at": slot_at.isoformat(),
        "duration_s": 60,
        "source": "timer",
        "room_id": F2,
    }
    other = {**timer, "zone": 4}
    engine = {
        **timer,
        "source": "engine",
        "at": (NOW + timedelta(hours=3)).isoformat(),
        "expected": True,
    }
    skips = [
        {
            "zone": 3,
            "at": slot_at.astimezone(UTC).isoformat(),
            "until": (slot_at + timedelta(hours=4)).isoformat(),
        }
    ]
    out = _build(planned=[timer, other, engine], rooms=[_room(skips=skips)])
    got = {
        (b["source"], r["zone"]): b
        for r in out["rooms"][0]["rows"]
        for b in r["blocks"]
    }
    assert (got[("timer", 3)]["skipped"], got[("timer", 3)]["skippable"]) == (
        True,
        False,
    )
    assert (got[("timer", 4)]["skipped"], got[("timer", 4)]["skippable"]) == (
        False,
        True,
    )
    assert (got[("engine", 3)]["skipped"], got[("engine", 3)]["skippable"]) == (
        True,
        False,
    )


def test_planned_intents_without_an_id_are_kept_and_deduped_by_slot():
    slot = {
        "zone": 3,
        "at": (NOW + timedelta(hours=1)).isoformat(),
        "duration_s": 60,
        "source": "timer",
        "room_id": F2,
    }
    later = {**slot, "at": (NOW + timedelta(hours=2)).isoformat()}
    out = _build(planned=[slot, dict(slot), later])
    assert len(_blocks(out)) == 2


def test_summary_days_are_deduped():
    out = timeline.summarise([], ["2026-10-22", "2026-10-22"], rooms=[F2], tz=NZ)
    assert [d["date"] for d in out] == ["2026-10-22"]


def test_the_summary_service_reads_a_shot_across_midnight_once(tmp_path, monkeypatch):
    """timeline_summary against a real journal file: the 23:58-00:02 shot asked as D, D+1 and both."""
    import asyncio
    import sys

    from .test_changes import _hub, _site

    hass, api = _site(monkeypatch, tmp_path)
    dt = sys.modules["homeassistant.util.dt"]
    monkeypatch.setattr(dt, "get_default_time_zone", lambda: NZ, raising=False)
    monkeypatch.setattr(dt, "now", lambda: NOW + timedelta(days=2))

    async def go():
        hub = await _hub(api, hass, tmp_path, {F2: _midnight_shot()})
        return [
            await api.timeline_summary(hass, hub, {"rooms": [F2], "days": days})
            for days in (["2026-10-22"], ["2026-10-23"], ["2026-10-22", "2026-10-23"])
        ]

    d, d1, both = asyncio.run(go())

    def counts(out):
        return [
            (day["date"], day["rooms"][0]["shots"], day["rooms"][0]["warnings"])
            for day in out["days"]
        ]

    assert counts(d) == [("2026-10-22", 1, 0)]
    assert counts(d1) == [("2026-10-23", 0, 0)]
    assert counts(both) == [("2026-10-22", 1, 0), ("2026-10-23", 0, 0)]


def test_a_shot_that_closed_before_the_window_is_not_drawn():
    since, until = _day(22)
    intent = new_id()
    events = [
        _ev(
            "shot.started",
            since - timedelta(minutes=30),
            intent=intent,
            duration_s=3600,
        ),
        _ev(
            "shot.aborted",
            since - timedelta(minutes=20),
            intent=intent,
            outcome="aborted",
            code="CS-301",
        ),
    ]
    out = timeline.build(
        [_room()],
        _read(events, since, until, openers=True),
        [],
        since,
        until,
        now=NOW,
        tz=NZ,
    )
    assert _blocks(out) == [] and out["errors"]["count"] == 0


def test_shared_pump_load_is_clipped_to_the_window():
    since, until = _day(22)
    _, inside = _shot(datetime(2026, 10, 22, 7, 0, tzinfo=NZ))
    _, before = _shot(since - timedelta(minutes=30))
    for ev in before:
        ev["room_id"] = (
            F1  # another room on the pump, read whole from before the window
        )
    out = timeline.build(
        [_room(pump=PUMP, capacity_lph=1200.0)],
        inside + before,
        [],
        since,
        until,
        now=NOW,
        tz=NZ,
        pumps={PUMP: {F2: {"3": 300.0}, F1: {"3": 300.0}}},
    )
    times = [datetime.fromisoformat(p["t"]) for p in out["rooms"][0]["pump_load"]]
    assert times and all(since <= t <= until for t in times)
