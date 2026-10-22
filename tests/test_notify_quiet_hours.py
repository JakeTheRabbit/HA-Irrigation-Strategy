"""A phone's quiet hours (docs/NOTIFICATIONS.md): inside its window what is not critical waits in its digest queue,
digest or not, and goes to it as one push when the window ends; a critical push, or one whose code is not known,
always goes. A store saved before quiet hours loads with none. notify_test also tests several phones at once."""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import pytest

from .test_notify_api import (  # noqa: F401 (home_assistant: an autouse fixture)
    ADMIN,
    GROUP,
    PHONE_A,
    PHONE_B,
    STAFF,
    HomeAssistantError,
    home_assistant,
    notify_api,
    rig,
    row,
    save,
    saved,
    send,
    services,
)

# Home Assistant's own time zone for these tests: New Zealand daylight time.
LOCAL = timezone(timedelta(hours=13))
NOW = datetime(2026, 10, 15, 22, 0, tzinfo=LOCAL)


@pytest.fixture(autouse=True)
def local_time(monkeypatch):
    """dt_util.as_local, as Home Assistant has it: to the site's time zone."""
    monkeypatch.setattr(notify_api, "_now", lambda: NOW.astimezone(timezone.utc))
    monkeypatch.setattr(
        sys.modules["homeassistant.util.dt"],
        "as_local",
        lambda moment: moment.astimezone(LOCAL),
        raising=False,
    )


def _at(notifier, hour, minute=0, day=15, clock=1000.0):
    """The notifier's clocks at local `hour`:`minute` of 15 (or `day`) October."""
    moment = datetime(2026, 10, day, hour, minute, tzinfo=LOCAL)
    notifier._now = lambda: moment.astimezone(timezone.utc)
    notifier._clock = lambda: clock
    return notifier


def test_old_recipient_rows_have_no_quiet_hours():
    """UPGRADE IN PLACE: rows saved before quiet hours have none; a page from before keeps a row's."""
    hass, notifier = rig(saved(row(PHONE_A, kinds=["sensors"])))
    assert notifier.error is None
    assert notifier.data["recipients"][0]["quiet_hours"] is None
    answer = asyncio.run(notifier.response(ADMIN))
    assert answer["config"]["recipients"][0]["quiet_hours"] is None
    _at(notifier, 23)
    assert send(notifier, code="CS-102", room="") == {
        "sent_to": [PHONE_A],
        "error": None,
    }
    window = {"from": "22:00", "to": "06:00"}
    rows = save(notifier, recipients=[row(PHONE_A, quiet_hours=window)])["config"][
        "recipients"
    ]
    assert rows[0]["quiet_hours"] == window
    page = [{k: v for k, v in r.items() if k != "quiet_hours"} for r in rows]
    assert save(notifier, recipients=page)["config"]["recipients"][0][
        "quiet_hours"
    ] == (window)
    # None clears it.
    cleared = save(notifier, recipients=[{**page[0], "quiet_hours": None}])
    assert cleared["config"]["recipients"][0]["quiet_hours"] is None


def test_a_warning_inside_quiet_hours_is_held_until_the_end():
    hass, notifier = rig(
        saved(
            row(
                PHONE_A,
                kinds=["sensors", "watering", "hardware", "phases"],
                quiet_hours={"from": "21:00", "to": "23:00"},
            ),
            row(GROUP, kinds=["sensors"]),
        )
    )
    _at(notifier, 22, clock=1000.0)
    # No digest on the phone, and still it waits; a phone with no quiet hours gets it at once.
    assert send(notifier, key="probe", code="CS-102", room="", title="Probe") == {
        "sent_to": [GROUP],
        "error": None,
        "held": [PHONE_A],
    }
    # The controller's "not watering" warnings wait too (CS-206, CS-316): only critical codes break through.
    for key, code in (("held", "CS-206"), ("pump", "CS-316")):
        assert send(notifier, key=key, code=code, room="", title=key)["held"] == [
            PHONE_A
        ]
    send(notifier, key="phase", event="phase", room="", title="P1 → P2")
    assert hass.services.sent == [(GROUP, hass.services.sent[0][1])]
    _at(notifier, 22, 59, clock=1000.0 + 5 * 3600)  # past digest_hours, still quiet
    asyncio.run(notifier.flush())
    assert len(hass.services.sent) == 1
    _at(notifier, 23, 0, clock=1000.0 + 5 * 3600)
    asyncio.run(notifier.flush())
    [(service, payload)] = hass.services.sent[1:]
    assert service == PHONE_A
    assert payload["title"] == "Crop Steering: 4 pushes held"
    assert payload["message"] == (
        "Warnings\n• Probe\n• held\n• pump\n\nUpdates\n• P1 → P2"
    )
    assert payload["data"]["tag"] == notify_api.DIGEST_TAG
    asyncio.run(notifier.flush())
    assert len(hass.services.sent) == 2  # sent once
    # After the window, pushes go at once again.
    assert send(notifier, code="CS-102", room="")["sent_to"] == [PHONE_A, GROUP]


def test_a_digest_phone_inside_quiet_hours_gets_its_digest_at_the_end():
    hass, notifier = rig(
        {
            **saved(
                row(
                    PHONE_A,
                    kinds=["sensors"],
                    digest=True,
                    quiet_hours={"from": "21:00", "to": "23:00"},
                )
            ),
            "digest_hours": 1,
        }
    )
    _at(notifier, 20, 30, clock=1000.0)  # before the window: held for the digest
    assert send(notifier, key="a", code="CS-102", room="")["held"] == [PHONE_A]
    _at(notifier, 21, 30, clock=1000.0 + 3600)  # the digest is due, but it is quiet
    asyncio.run(notifier.flush())
    assert hass.services.sent == []
    _at(notifier, 23, 0, clock=1000.0 + 3 * 3600)
    asyncio.run(notifier.flush())
    assert [s for s, _ in hass.services.sent] == [PHONE_A]


def test_an_emergency_inside_quiet_hours_is_pushed():
    hass, notifier = rig(
        saved(
            row(
                PHONE_A,
                kinds=["emergency", "hardware", "setup", "watering"],
                quiet_hours={"from": "21:00", "to": "23:00"},
            )
        )
    )
    _at(notifier, 22)
    answer = send(notifier, key="hw", code="CS-301", room="", urgent=True)
    assert answer == {"sent_to": [PHONE_A], "error": None}
    assert hass.services.sent[-1][1]["data"]["priority"] == "high"
    # A critical code goes even when the caller did not mark it urgent.
    assert send(notifier, key="kill", code="CS-202", room="")["sent_to"] == [PHONE_A]
    # A code this version does not know, or a push with neither code nor event: fail loud, never held.
    assert send(notifier, key="new", code="CS-999", room="")["sent_to"] == [PHONE_A]
    assert send(notifier, key="bare", room="")["sent_to"] == [PHONE_A]
    assert notifier._held == {}


def test_quiet_hours_crossing_midnight():
    hass, notifier = rig(
        saved(
            row(
                PHONE_A,
                kinds=["sensors"],
                quiet_hours={"from": "22:00", "to": "06:00"},
            )
        )
    )
    for (hour, minute, day), quiet in (
        ((21, 59, 15), False),
        ((22, 0, 15), True),
        ((23, 30, 15), True),
        ((0, 0, 16), True),
        ((5, 59, 16), True),
        ((6, 0, 16), False),
        ((12, 0, 16), False),
    ):
        _at(notifier, hour, minute, day)
        answer = send(notifier, key=f"{hour}:{minute}", code="CS-102", room="")
        assert ("held" in answer) is quiet, (hour, minute)
    # Held before and after midnight, one push at 06:00.
    _at(notifier, 5, 59, 16)
    asyncio.run(notifier.flush())
    sent = len(hass.services.sent)
    _at(notifier, 6, 0, 16)
    asyncio.run(notifier.flush())
    [(service, payload)] = hass.services.sent[sent:]
    assert payload["title"] == "Crop Steering: 4 pushes held"


def test_what_a_save_refuses_in_quiet_hours():
    hass, notifier = rig()
    for window, words in (
        (
            {"from": "22:00", "to": "22:00"},
            "Quiet hours need a start and an end that differ",
        ),
        ({"from": "24:00", "to": "06:00"}, "HH:MM"),
        ({"from": "7:00", "to": "08:00"}, "HH:MM"),
        ({"from": "07:60", "to": "08:00"}, "HH:MM"),
        ({"from": "07:00"}, "HH:MM"),
        ({"from": "07:00", "to": "08:00", "days": 5}, "HH:MM"),
        ("22:00-06:00", "HH:MM"),
    ):
        refused = save(notifier, recipients=[row(PHONE_A, quiet_hours=window)])
        assert words in refused["error"], window
        assert refused["config"]["revision"] == 0
    exact = save(
        notifier,
        recipients=[row(PHONE_A, quiet_hours={"from": "05:00", "to": "05:00"})],
    )["error"]
    assert exact == "phone 1: Quiet hours need a start and an end that differ"


def test_a_non_administrator_sets_the_quiet_hours_of_their_own_phone_only():
    hass, notifier = rig(
        saved(row(PHONE_A, user_id=STAFF.id), row(PHONE_B, user_id="someone"))
    )
    mine, theirs = (dict(r) for r in notifier.data["recipients"])
    window = {"from": "22:00", "to": "06:00"}
    answer = save(notifier, STAFF, recipients=[{**mine, "quiet_hours": window}, theirs])
    assert answer["error"] is None
    assert [r["quiet_hours"] for r in answer["config"]["recipients"]] == [window, None]
    mine = answer["config"]["recipients"][0]
    assert (
        "not your phone"
        in save(notifier, STAFF, recipients=[mine, {**theirs, "quiet_hours": window}])[
            "error"
        ]
    )


def test_test_several_phones_reports_each(services):  # noqa: F811 (the fixture)
    call = services.call
    answer = call("notify_test", ADMIN, services=[PHONE_A, PHONE_B, "notify.gone"])
    assert answer == {
        "results": [
            {"service": PHONE_A, "sent": True, "error": None},
            {"service": PHONE_B, "sent": True, "error": None},
            {
                "service": "notify.gone",
                "sent": False,
                "error": "notify.gone is not a notify service in Home Assistant",
            },
        ]
    }
    # A non-administrator: their own phone only, each answered on its own.
    staff = call("notify_test", STAFF, services=[PHONE_A, PHONE_B])["results"]
    assert [(r["service"], r["sent"]) for r in staff] == [
        (PHONE_A, True),
        (PHONE_B, False),
    ]
    assert staff[1]["error"].startswith("not allowed: ")
    # One phone, as before; one or the other, not both or neither.
    assert call("notify_test", ADMIN, service=PHONE_A) == {"sent": True, "error": None}
    for data in ({}, {"service": PHONE_A, "services": [PHONE_B]}):
        with pytest.raises(HomeAssistantError, match="either service or services"):
            call("notify_test", ADMIN, **data)


# ------------------------------------------------------------------ review round 1
def test_stopping_the_site_logs_what_it_drops(caplog):
    hass, notifier = rig(
        saved(
            row(
                PHONE_A, kinds=["sensors"], quiet_hours={"from": "21:00", "to": "23:00"}
            )
        )
    )
    _at(notifier, 22)
    send(notifier, key="a", code="CS-102", room="")
    send(notifier, key="b", code="CS-103", room="")
    notifier.listen()
    with caplog.at_level("WARNING"):
        notifier.stop()
    assert f"2 held pushes for {PHONE_A}" in caplog.text
    assert notifier._held == {}


def test_quiet_hours_never_hold_a_push_with_keep_and_undo_for_a_phone_without_a_digest():
    window = {"from": "21:00", "to": "23:00"}
    hass, notifier = rig(
        saved(
            row(PHONE_A, kinds=["jev"], quiet_hours=window),
            row(PHONE_B, kinds=["jev"], quiet_hours=window, digest=True),
        )
    )
    _at(notifier, 22)
    answer = send(
        notifier,
        key="ai",
        event="jev_setpoint",
        room="",
        overlays=["number.crop_steering_p1_target_vwc"],
    )
    # The phone that takes no digest gets the buttons now; the digest phone waits, as a digest always did.
    assert answer == {"sent_to": [PHONE_A], "error": None, "held": [PHONE_B]}
    assert "actions" in hass.services.sent[0][1]["data"]
    # Without buttons, the same push waits.
    assert sorted(send(notifier, key="ai2", event="jev_setpoint", room="")["held"]) == [
        PHONE_A,
        PHONE_B,
    ]


def test_a_phone_removed_while_pushes_wait_gets_nothing():
    hass, notifier = rig(
        saved(
            row(
                PHONE_A, kinds=["sensors"], quiet_hours={"from": "21:00", "to": "23:00"}
            ),
            row(PHONE_B, kinds=["sensors"]),
        )
    )
    _at(notifier, 22)
    assert send(notifier, code="CS-102", room="")["held"] == [PHONE_A]
    rows = notifier.data["recipients"]
    assert save(notifier, recipients=[rows[1]])["error"] is None
    assert notifier._held == {}
    _at(notifier, 23)
    asyncio.run(notifier.flush())
    assert [s for s, _ in hass.services.sent] == [PHONE_B]


def test_a_window_removed_while_pushes_wait_flushes_on_the_next_tick():
    hass, notifier = rig(
        saved(
            row(
                PHONE_A, kinds=["sensors"], quiet_hours={"from": "21:00", "to": "23:00"}
            )
        )
    )
    _at(notifier, 22)
    send(notifier, code="CS-102", room="")
    save(notifier, recipients=[{**notifier.data["recipients"][0], "quiet_hours": None}])
    _at(notifier, 22, 1)
    asyncio.run(notifier.flush())
    assert [s for s, _ in hass.services.sent] == [PHONE_A]


def test_a_window_extended_while_pushes_wait_holds_them_to_the_new_end():
    hass, notifier = rig(
        saved(
            row(
                PHONE_A, kinds=["sensors"], quiet_hours={"from": "21:00", "to": "23:00"}
            )
        )
    )
    _at(notifier, 22)
    send(notifier, code="CS-102", room="")
    later = {"from": "21:00", "to": "23:30"}
    save(
        notifier, recipients=[{**notifier.data["recipients"][0], "quiet_hours": later}]
    )
    _at(notifier, 23)
    asyncio.run(notifier.flush())
    assert hass.services.sent == []
    _at(notifier, 23, 30)
    asyncio.run(notifier.flush())
    assert [s for s, _ in hass.services.sent] == [PHONE_A]


def test_testing_several_phones_refuses_an_empty_list(services):  # noqa: F811
    with pytest.raises(HomeAssistantError, match="at least one phone"):
        services.call("notify_test", ADMIN, services=[])


def test_testing_several_phones_reports_a_phone_that_raises():
    hass, notifier = rig()
    real = notifier._has

    def has(service):
        if service == PHONE_B:
            raise OSError("registry unreadable")
        return real(service)

    notifier._has = has
    answer = asyncio.run(notifier.test_many([PHONE_A, PHONE_B], ADMIN))
    assert answer == {
        "results": [
            {"service": PHONE_A, "sent": True, "error": None},
            {"service": PHONE_B, "sent": False, "error": "registry unreadable"},
        ]
    }
