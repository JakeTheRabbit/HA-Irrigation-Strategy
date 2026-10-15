"""A phone that takes a digest, and a room that is muted (docs/NOTIFICATIONS.md): what is not an emergency waits
for one push every digest_hours, grouped by severity; nothing but an emergency is pushed for a muted room; a
store saved before either loads with neither, and a page that does not know them keeps them."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.crop_steering import notify_api

from .test_notify_api import (  # noqa: F401 (home_assistant: an autouse fixture)
    ADMIN,
    GROUP,
    PHONE_A,
    PHONE_B,
    SENSOR,
    STAFF,
    home_assistant,
    rig,
    row,
    save,
    saved,
    send,
)

NOW = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def now(monkeypatch):
    """The time a stored mute is read at, and a notifier starts with."""
    monkeypatch.setattr(notify_api, "_now", lambda: NOW)


def _at(notifier, now=NOW, clock=1000.0):
    notifier._now = lambda: now
    notifier._clock = lambda: clock
    return notifier


def test_a_store_from_before_loads_with_no_digest_and_nothing_muted():
    """UPGRADE IN PLACE: a store saved before the digest and the mutes (no such keys anywhere)."""
    hass, notifier = rig(saved(row(PHONE_A, kinds=["stock"]), idle_hours=5, revision=7))
    assert notifier.error is None
    assert notifier.data["recipients"][0]["digest"] is False
    assert (notifier.data["digest_hours"], notifier.data["mutes"]) == (4, {})
    assert notifier.data["revision"] == 7 and notifier.data["idle_hours"] == 5
    assert "muted" not in hass.states.values[SENSOR][1]
    assert send(notifier, code="CS-608", room="") == {
        "sent_to": [PHONE_A],
        "error": None,
    }


def test_an_administrator_sets_the_digest_and_the_mutes_and_a_page_from_before_keeps_them():
    hass, notifier = rig()
    _at(notifier)
    until = (NOW + timedelta(hours=6)).astimezone(timezone(timedelta(hours=13)))
    answer = save(
        notifier,
        recipients=[row(PHONE_A, digest=True), row(PHONE_B)],
        digest_hours=8,
        mutes={"f1_": until.isoformat(), "": (NOW - timedelta(minutes=1)).isoformat()},
    )
    assert answer["error"] is None
    config = answer["config"]
    assert [r["digest"] for r in config["recipients"]] == [True, False]
    assert config["digest_hours"] == 8
    # Kept in UTC; one already over is not kept at all.
    assert config["mutes"] == {"f1_": "2026-10-15T08:00:00+00:00"}
    assert hass.states.values[SENSOR][1]["muted"] == {
        "f1_": "2026-10-15T08:00:00+00:00"
    }
    # The page as it was before: rows without `digest`, no digest_hours, no mutes. Nothing of them moves.
    page = [{k: v for k, v in r.items() if k != "digest"} for r in config["recipients"]]
    again = save(notifier, recipients=page)["config"]
    assert [r["digest"] for r in again["recipients"]] == [True, False]
    assert (again["digest_hours"], again["mutes"]) == (8, config["mutes"])
    # Unmuting is a save of the mutes without the room.
    assert save(notifier, recipients=page, mutes={})["config"]["mutes"] == {}
    assert "muted" not in hass.states.values[SENSOR][1]


def test_what_a_save_refuses():
    hass, notifier = rig()
    _at(notifier)
    for data, words in (
        ({"digest_hours": 0}, "1 to 24"),
        ({"digest_hours": 25}, "1 to 24"),
        ({"digest_hours": 1.5}, "1 to 24"),
        ({"digest_hours": "4"}, "1 to 24"),
        ({"mutes": ["f1_"]}, "map a room prefix"),
        (
            {"mutes": {"F1": (NOW + timedelta(hours=1)).isoformat()}},
            "not a room prefix",
        ),
        ({"mutes": {"f1_": "2026-10-15T08:00:00"}}, "with its offset"),
        ({"mutes": {"f1_": "tomorrow"}}, "with its offset"),
        ({"mutes": {"f1_": (NOW + timedelta(days=31)).isoformat()}}, "at most 30 days"),
        ({"recipients": [row(PHONE_A, digest="yes")]}, "digest must be true or false"),
    ):
        refused = save(notifier, **{"recipients": [], **data})
        assert words in refused["error"], data
        assert refused["config"]["revision"] == 0


def test_a_non_administrator_sets_the_digest_of_their_own_phone_and_nothing_of_the_sites():
    hass, notifier = rig(
        saved(row(PHONE_A, user_id=STAFF.id), row(PHONE_B, user_id="someone"))
    )
    mine, theirs = (dict(r) for r in notifier.data["recipients"])
    answer = save(notifier, STAFF, recipients=[{**mine, "digest": True}, theirs])
    assert answer["error"] is None
    assert [r["digest"] for r in answer["config"]["recipients"]] == [True, False]
    mine = answer["config"]["recipients"][0]
    # Sent without `digest`, their row keeps it.
    kept = save(notifier, STAFF, recipients=[{**mine, "digest": None}, theirs])
    assert kept["config"]["recipients"][0]["digest"] is True
    assert (
        "not your phone"
        in save(notifier, STAFF, recipients=[mine, {**theirs, "digest": True}])["error"]
    )
    for data, words in (
        ({"digest_hours": 2}, "how often a digest goes out"),
        ({"mutes": {"": (NOW + timedelta(hours=1)).isoformat()}}, "mute a room"),
    ):
        assert (
            words in save(notifier, STAFF, recipients=[mine, theirs], **data)["error"]
        )


def test_a_muted_room_pushes_nothing_but_an_emergency_until_its_mute_ends():
    hass, notifier = rig(
        {
            **saved(row(PHONE_A, kinds=["emergency", "sensors", "phases"])),
            "mutes": {"f1_": "2026-10-15T08:00:00+00:00"},
        }
    )
    _at(notifier)
    muted = {"sent_to": [], "error": None, "muted": True}
    assert send(notifier, code="CS-102", room="f1_") == muted
    assert send(notifier, event="phase", room="f1_") == muted
    assert send(notifier, code="CS-301", room="f1_", urgent=True)["sent_to"] == [
        PHONE_A
    ]
    # Another room, and a push about no room in particular, are not muted.
    assert send(notifier, code="CS-102", room="")["sent_to"] == [PHONE_A]
    assert send(notifier, code="CS-102")["sent_to"] == [PHONE_A]
    _at(notifier, NOW + timedelta(hours=6))  # the mute is over
    assert send(notifier, code="CS-102", room="f1_")["sent_to"] == [PHONE_A]


def test_a_digest_phone_gets_one_push_every_digest_hours_grouped_by_severity():
    hass, notifier = rig(
        {
            **saved(
                row(
                    PHONE_A,
                    kinds=["emergency", "sensors", "watering", "phases"],
                    digest=True,
                ),
                row(GROUP, kinds=["sensors"]),
            ),
            "digest_hours": 2,
        }
    )
    _at(notifier, clock=1000.0)
    # The phone that takes no digest gets it at once; the digest phone's waits.
    assert send(
        notifier, key="blind", code="CS-102", room="", title="Zone 1: probe"
    ) == {
        "sent_to": [GROUP],
        "error": None,
        "held": [PHONE_A],
    }
    _at(notifier, clock=2000.0)
    assert send(
        notifier, key="limit", code="CS-205", room="", title="Zone 1: daily limit"
    ) == {
        "sent_to": [],
        "error": None,
        "held": [PHONE_A],
    }
    send(notifier, key="phase", event="phase", room="", title="Zone 1: P1 → P2")
    send(notifier, key="blind", code="CS-102", room="", title="Zone 1: probe again")
    # An emergency never waits.
    assert send(notifier, key="hw", code="CS-301", room="", urgent=True)["sent_to"] == [
        PHONE_A
    ]
    sent = len(hass.services.sent)
    _at(notifier, clock=1000.0 + 2 * 3600 - 1)
    asyncio.run(notifier.flush())
    # Not yet: two hours after the first it holds.
    assert len(hass.services.sent) == sent
    _at(notifier, clock=1000.0 + 2 * 3600)
    asyncio.run(notifier.flush())
    [(service, payload)] = hass.services.sent[sent:]
    assert service == PHONE_A
    assert payload["title"] == "Crop Steering: 3 pushes held"
    assert payload["message"] == (
        "Warnings\n• Zone 1: probe again\n\nFor your information\n• Zone 1: daily limit"
        "\n\nUpdates\n• Zone 1: P1 → P2"
    )
    assert payload["data"]["tag"] == notify_api.DIGEST_TAG
    assert "priority" not in payload["data"]
    asyncio.run(notifier.flush())
    assert len(hass.services.sent) == sent + 1  # sent once; nothing waits now


def test_the_digest_is_checked_every_minute_while_the_site_is_set_up():
    hass, notifier = rig()
    notifier.listen()
    [(tick, interval)] = hass.intervals
    assert interval == notify_api.DIGEST_CHECK == timedelta(minutes=1)
    notifier.stop()
    assert hass.intervals == []
