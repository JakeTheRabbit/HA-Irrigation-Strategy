"""Spec section 7: a 3.11.1 install with a setpoint change log updates in place, the journal backfills
that log, and history_changes then lists exactly the old log's rows, newest first, each by who it
was (tests_ha/fixtures/entry_3_11_1_pumped_room.json plus a seeded setpoint_log store)."""

from conftest import fixture
from homeassistant.core import Context
from test_upgrade_in_place import JEV_3_11_1, _upgrade

DOMAIN = "crop_steering"
ROOM = "room:"
ACTORS = {"operator": "manual", "home_assistant": "automation", "learner": "learner", "brain": "ai"}


def _rows():
    def row(at, field, old, new, who, **extra):
        return {
            "at": at,
            "entity_id": f"number.crop_steering_zone_1_{field}",
            "field": field,
            "zone": 1,
            "old": old,
            "new": new,
            "who": who,
            **extra,
        }

    return [
        row("2026-10-12T14:05:00+00:00", "p2_vwc_threshold", 42.0, 43.0, "operator"),
        row("2026-10-13T06:00:00+00:00", "dryback_target", 12.0, 13.5, "learner"),
        row(
            "2026-10-13T09:30:00+00:00",
            "p2_shot_size",
            4.0,
            4.5,
            "brain",
            reason="P2 shots run off too little",
            expected="runoff back to 15 %",
        ),
        row("2026-10-14T08:00:00+00:00", "field_capacity", 55.0, 56.0, "home_assistant"),
    ]


async def test_upgrade_then_backfill_then_history_changes_equals_the_old_setpoint_log(
    hass, hass_storage, hass_admin_user
):
    seed = fixture(JEV_3_11_1)
    key = f"{DOMAIN}.setpoint_log.{seed['entry_id']}"
    rows = _rows()
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"changes": rows},
    }
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    await hass.data[DOMAIN]["_journal"]._ready.wait()
    await hass.async_block_till_done()

    out = await hass.services.async_call(
        DOMAIN,
        "history_changes",
        {"room_id": ROOM, "since": "2026-01-01T00:00:00+00:00"},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    got = [
        (c["ts"], c["key"], c["scope"], c["old"], c["new"], c["actor"], c["reason"])
        for c in out["changes"]
    ]
    assert got == [
        (r["at"], r["field"], "zone:1", r["old"], r["new"], ACTORS[r["who"]], r.get("reason"))
        for r in reversed(rows)
    ]
    assert {c["kind"] for c in out["changes"]} == {"setpoint"}
    by_key = {c["key"]: c for c in out["changes"]}
    # The learner and the AI rows carry their limits and the outcome line; the others do not.
    assert by_key["dryback_target"]["limits"]["writer"] == "learner"
    assert by_key["p2_shot_size"]["limits"]["writer"] == "brain"
    assert by_key["p2_shot_size"]["outcome"].startswith("Too soon to judge")
    assert by_key["p2_vwc_threshold"]["limits"] is None
    assert by_key["p2_vwc_threshold"]["outcome"] is None
    # The old log is only read: it is still exactly what it was.
    assert hass_storage[key]["data"]["changes"] == rows
