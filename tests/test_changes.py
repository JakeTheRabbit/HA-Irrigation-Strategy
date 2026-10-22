"""History › Changes (G8): changes.fold_changes over journal events, and history_changes /
history_revert (journal_api.py) against the stubs and a real journal file.

`ai.outcome` comes from the controller lanes, not built yet: the events here are synthetic, shaped
{kind: ai.outcome, correlation.causation_id: <the change's event id>, data.good: bool}."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.crop_steering.changes import (
    GOOD,
    NOT_YET,
    TOO_SOON,
    fold_changes,
)
from custom_components.crop_steering.generated.ids import new_id

from .test_journal_api import _rig

F2, F1 = "room:f2_", "room:f1_"
SINCE = "2026-10-01T00:00:00+00:00"


def _ev(
    kind, ts, *, room=F2, zone=None, actor="manual", user_id=None, detail=None, **data
):
    return {
        "v": 1,
        "id": new_id(),
        "room_id": room,
        "ts": ts,
        "kind": kind,
        "zone": zone,
        "outcome": "ok",
        "source": {"actor": actor, "user_id": user_id, "detail": detail},
        "correlation": {"causation_id": data.pop("causation_id", None)},
        "data": data,
    }


def _target(ts, key="p2_shot_size", old=5.0, new=6.0, zone=1, **kw):
    return _ev(
        "target.changed",
        ts,
        zone=zone,
        key=key,
        scope=f"zone:{zone}",
        layer=kw.pop("layer", "base"),
        old=old,
        new=new,
        reason=kw.pop("reason", None),
        entity_id=f"number.crop_steering_f2_zone_{zone}_{key}",
        **kw,
    )


# ------------------------------------------------------------------ the fold
def test_a_learner_nudge_and_a_manual_edit_both_appear_attributed():
    learner = _target(
        "2026-10-20T06:00:00+00:00", "p1_target_vwc", 30.0, 31.0, actor="learner"
    )
    manual = _target("2026-10-20T09:00:00+00:00", user_id="u-ben")
    rows = fold_changes([learner, manual], {})
    assert [(r["id"], r["actor"], r["user_id"]) for r in rows] == [
        (manual["id"], "manual", "u-ben"),
        (learner["id"], "learner", None),
    ]
    assert rows[0]["outcome"] is None and rows[0]["limits"] is None


def test_rows_carry_id_kind_outcome_and_limits():
    learner = _target(
        "2026-10-20T06:00:00+00:00", "dryback_target", 10.0, 12.0, actor="learner"
    )
    (row,) = fold_changes([learner], {F2: {"step_scope": "Auto setpoints and AI"}})
    assert row["id"] == row["event_id"] == learner["id"]
    assert (row["kind"], row["key"], row["scope"], row["old"], row["new"]) == (
        "setpoint",
        "dryback_target",
        "zone:1",
        10.0,
        12.0,
    )
    assert row["outcome"] == "Too soon to judge — check after the next lights-on."
    assert row["limits"] == {
        "writer": "learner",
        "min": 2.0,
        "max": 60.0,
        "step_scope": "Auto setpoints and AI",
    }
    assert row["revertible"] is True
    # An AI write: writer "brain"; an unknown step scope reads as the default.
    ai = _target("2026-10-20T07:00:00+00:00", "p2_shot_size", actor="ai")
    (row,) = fold_changes([ai], {F2: {"step_scope": "nonsense"}})
    assert row["limits"] == {
        "writer": "brain",
        "min": 0.5,
        "max": 20.0,
        "step_scope": "Auto setpoints",
    }
    # A key the engine has no bounds for: no invented limits.
    odd = _target("2026-10-20T07:00:00+00:00", "lights_on_hour", actor="learner")
    (row,) = fold_changes([odd], {})
    assert (row["limits"]["min"], row["limits"]["max"]) == (None, None)


def test_the_outcome_line_follows_the_matching_ai_outcome():
    good = _target("2026-10-20T06:00:00+00:00", actor="ai")
    flat = _target("2026-10-20T06:30:00+00:00", actor="learner")
    later = _target("2026-10-21T06:30:00+00:00", actor="learner")
    outcomes = [
        _ev(
            "ai.outcome",
            "2026-10-21T06:00:00+00:00",
            actor="ai",
            causation_id=good["id"],
            good=True,
        ),
        _ev(
            "ai.outcome",
            "2026-10-21T06:00:00+00:00",
            actor="ai",
            causation_id=flat["id"],
            good=False,
        ),
    ]
    by_id = {r["id"]: r for r in fold_changes([good, flat, later, *outcomes], {})}
    assert len(by_id) == 3  # ai.outcome is read, never listed
    assert by_id[good["id"]]["outcome"] == GOOD == "Dryback came back to target."
    assert by_id[flat["id"]]["outcome"] == NOT_YET == "No change in dryback yet."
    assert by_id[later["id"]]["outcome"] == TOO_SOON


def test_kinds_and_what_can_be_put_back():
    events = [
        _ev(
            "plan.activated",
            "2026-10-20T06:00:00+00:00",
            actor="plan",
            revision=3,
            status="active",
        ),
        _target("2026-10-20T06:01:00+00:00", detail="preset Mothers"),
        _ev(
            "config.changed",
            "2026-10-20T06:02:00+00:00",
            store="timers",
            section="programs",
            old=[],
            new=[{"id": "p"}],
        ),
        _ev(
            "config.changed",
            "2026-10-20T06:03:00+00:00",
            store="site",
            section="alert_rules",
            old=[],
            new=[{"id": "r"}],
        ),
        _ev(
            "config.changed",
            "2026-10-20T06:04:00+00:00",
            store="setup",
            section="room",
            old=None,
            new={"room_name": "F2"},
        ),
        _ev(
            "calibration.committed",
            "2026-10-20T06:05:00+00:00",
            probe="feed_ph",
            record_id="a",
            applied=True,
        ),
        _ev(
            "calibration.committed",
            "2026-10-20T06:06:00+00:00",
            probe="feed_ec",
            record_id="b",
            applied=True,
        ),
        _ev(
            "calibration.reverted",
            "2026-10-20T06:07:00+00:00",
            probe="feed_ph",
            record_id=None,
        ),
        _ev(
            "pump.calibrated",
            "2026-10-20T06:08:00+00:00",
            pump="a3",
            ml_min=50.0,
            previous_ml_min=48.0,
        ),
        _target("2026-10-20T06:09:00+00:00", detail="backfill", old=None),
        _target(
            "2026-10-20T06:10:00+00:00",
            actor="ai",
            layer="overlay",
            new=None,
            reason="undone",
        ),
        _ev("shot.completed", "2026-10-20T06:11:00+00:00", actor="engine"),
    ]
    rows = list(reversed(fold_changes(events, {})))
    assert [(r["kind"], r["revertible"]) for r in rows] == [
        ("plan", False),  # a plan activation
        ("recipe", True),
        ("setup", True),  # timers
        ("alerts", False),  # no save path for alert rules yet
        ("setup", False),  # a create: nothing before it
        ("calibration", False),  # feed_ph, superseded by the revert after it
        ("calibration", True),  # feed_ec, still applied
        ("calibration", False),
        ("calibration", False),
        ("setpoint", False),  # a legacy row without old
        ("setpoint", False),  # an overlay undo marker
    ]
    assert rows[0]["reason"] == "activated" and rows[0]["section"] == "plan"
    assert rows[3]["scope"] == "site"


def test_a_site_change_journaled_in_two_rooms_is_one_row():
    shared = new_id()
    both = [
        _ev(
            "config.changed",
            "2026-10-20T06:00:00+00:00",
            room=room,
            store="site",
            section="supply",
            old={"irrigation_pumps": []},
            new={"irrigation_pumps": [{"entity_id": "switch.p"}]},
            causation_id=shared,
        )
        for room in (F1, F2)
    ]
    assert len(fold_changes(both, {})) == 1


def test_the_fold_orders_by_ts_not_by_seq():
    late_but_first = _target("2026-10-19T06:00:00+00:00")
    late_but_first["seq"] = 99  # a backfilled row
    live = _target("2026-10-20T06:00:00+00:00")
    live["seq"] = 1
    assert [r["id"] for r in fold_changes([live, late_but_first], {})] == [
        live["id"],
        late_but_first["id"],
    ]


# ------------------------------------------------------------------ the services
class _Users:
    def __init__(self, users):
        self.users = users
        self.asked = []

    async def async_get_user(self, user_id):
        self.asked.append(user_id)
        return self.users.get(user_id)


def _site(monkeypatch, tmp_path, users=None, entries=("f2_", "f1_")):
    from tests import ha_stubs

    hass, api = _rig(monkeypatch, tmp_path)
    hass.auth = _Users(users or {})
    hass.config_entries = ha_stubs.FakeConfigEntries(
        [
            ha_stubs.FakeEntry({"room_prefix": p}, entry_id=p.rstrip("_"))
            for p in entries
        ]
    )
    return hass, api


async def _hub(api, hass, tmp_path, events_by_room):
    hub = api.JournalHub(hass, str(tmp_path / "journal.db"))
    await hub.async_init()
    for room, events in events_by_room.items():
        await hub.append(
            room, [{k: v for k, v in e.items() if k != "room_id"} for e in events]
        )
    hass.data.setdefault("crop_steering", {})["_journal"] = hub
    return hub


def test_manual_rows_name_the_user_and_automation_rows_do_not(tmp_path, monkeypatch):
    ben = SimpleNamespace(name="Ben")
    hass, api = _site(monkeypatch, tmp_path, {"u-ben": ben})
    rows = [
        _target("2026-10-20T06:00:00+00:00", user_id="u-ben"),
        _target("2026-10-20T07:00:00+00:00", user_id="u-ben", key="p1_target_vwc"),
        _target("2026-10-20T08:00:00+00:00", user_id="u-gone"),  # a deleted user
        _target("2026-10-20T09:00:00+00:00", actor="automation"),
    ]

    async def go():
        hub = await _hub(api, hass, tmp_path, {F2: rows})
        return await api.history_changes(hass, hub, {"room_id": F2, "since": SINCE})

    out = asyncio.run(go())["changes"]
    assert [(r["user_id"], r["user_name"]) for r in out] == [
        (None, None),
        ("u-gone", None),
        ("u-ben", "Ben"),
        ("u-ben", "Ben"),
    ]
    assert hass.auth.asked == ["u-gone", "u-ben"]  # each user looked up once per call


def test_until_bounds_the_range_and_no_room_merges_all_rooms(tmp_path, monkeypatch):
    hass, api = _site(monkeypatch, tmp_path)
    f2_early = _target("2026-10-20T06:00:00+00:00")
    f2_late = _target("2026-10-22T06:00:00+00:00")
    f1_mid = _target("2026-10-21T06:00:00+00:00", room=F1, zone=2)
    hass.states.set(
        "select.crop_steering_f1_setpoint_step_limit_applies_to",
        "Auto setpoints and AI",
    )
    f1_learner = _target("2026-10-21T07:00:00+00:00", room=F1, zone=2, actor="learner")

    async def go():
        hub = await _hub(
            api, hass, tmp_path, {F2: [f2_early, f2_late], F1: [f1_mid, f1_learner]}
        )
        bounded = await api.history_changes(
            hass,
            hub,
            {"room_id": F2, "since": SINCE, "until": "2026-10-21T00:00:00+00:00"},
        )
        merged = await api.history_changes(hass, hub, {"since": SINCE})
        zone_2 = await api.history_changes(hass, hub, {"since": SINCE, "zone": 2})
        return bounded, merged, zone_2

    bounded, merged, zone_2 = asyncio.run(go())
    assert [r["id"] for r in bounded["changes"]] == [f2_early["id"]]
    assert [(r["id"], r["room_id"]) for r in merged["changes"]] == [
        (f2_late["id"], F2),
        (f1_learner["id"], F1),
        (f1_mid["id"], F1),
        (f2_early["id"], F2),
    ]
    assert merged["changes"][1]["limits"]["step_scope"] == "Auto setpoints and AI"
    assert [r["id"] for r in zone_2["changes"]] == [f1_learner["id"], f1_mid["id"]]


def test_revert_refuses_when_the_value_moved_since(tmp_path, monkeypatch):
    from custom_components.crop_steering.api_v2 import StaleRevision
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.crop_steering import presets

    hass, api = _site(monkeypatch, tmp_path)
    change = _target("2026-10-20T06:00:00+00:00", old=5.0, new=6.0)
    entity_id = change["data"]["entity_id"]
    hass.states.set(entity_id, "7.0")  # someone moved it again since
    writes = []

    async def no_write(*args, **kw):
        writes.append(args)
        return []

    monkeypatch.setattr(presets, "write_numbers", no_write)
    call = SimpleNamespace(
        data={"event_id": change["id"]}, context=SimpleNamespace(user_id=None)
    )

    async def go():
        hub = await _hub(api, hass, tmp_path, {F2: [change]})
        return await api.history_revert(hass, hub, call)

    with pytest.raises(HomeAssistantError, match="has changed since") as raised:
        asyncio.run(go())
    assert isinstance(raised.value.__cause__, StaleRevision)
    assert writes == []


def test_revert_refuses_a_change_that_cannot_be_put_back(tmp_path, monkeypatch):
    from homeassistant.exceptions import HomeAssistantError

    hass, api = _site(monkeypatch, tmp_path)
    activation = _ev(
        "plan.activated", "2026-10-20T06:00:00+00:00", actor="plan", status="active"
    )
    call = SimpleNamespace(
        data={"event_id": activation["id"]}, context=SimpleNamespace(user_id=None)
    )

    async def go():
        hub = await _hub(api, hass, tmp_path, {F2: [activation]})
        return await api.history_revert(hass, hub, call)

    with pytest.raises(HomeAssistantError, match="This change can't be put back"):
        asyncio.run(go())
