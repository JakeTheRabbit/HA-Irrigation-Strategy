"""The Feed task (haiku-brain-design section 5): only in a room whose feed EC sensor is mapped, asked once a grow-day an
hour after lights-on, a firm proposal is a CS-711 card for a person, and it never writes anything."""
from datetime import timedelta

import brain_kit as B
import jev_bridge
import pytest
from jev import council, feed
from test_brain_wiring import _writes, _zone, claude  # noqa: F401 - claude is a fixture
from test_jev_controller import NOW, _switches

FEED = "sensor.feed_ec"
ALL_BUT_FEED = ",".join(j for j in jev_bridge.ALL if j != "feed")


def _feed_asks(c):
    return [r for r in c._client.requests if 'judge="feed"' in r["messages"][0]["content"][0]["text"]]


def _created(fake, code):
    return [d["notification_id"] for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and f"({code})" in d["title"]]


def _run(make, pick, passes=2, **options):
    c, fake = make(B.judging({"proposal": pick}), **options)
    fake.set_state(FEED, "2.4", {"unit_of_measurement": "mS/cm"})
    for _ in range(passes):
        _zone(c)
        c.loop_once(NOW)
    return c, fake


def test_a_firm_proposal_is_a_cs711_card_for_a_person_and_nothing_is_written(claude):  # noqa: F811
    c, fake = _run(claude, "feed_ec_down_small", feed_ec_sensor=FEED)
    [ask] = _feed_asks(c)[:1]
    sent = ask["messages"][0]["content"][0]["text"]
    assert sent.startswith('<snapshot id="default:zroom:feed:') and "feed_ec: 2.40 mS/cm" in sent
    assert "pore EC 6.50 mS/cm" in sent
    assert _created(fake, "CS-711") == ["f2_jev_feed_default"]
    assert "feed" in fake.sets["sensor.crop_steering_jev"][1]["judges_advising"]
    without, without_fake = _run(claude, "feed_ec_down_small", feed_ec_sensor=FEED, jev_judges=ALL_BUT_FEED)
    assert not _feed_asks(without) and not _created(without_fake, "CS-711")
    assert _writes(fake) == _writes(without_fake) and _switches(fake) == _switches(without_fake)


@pytest.mark.parametrize("pick", ["keep_feed", "insufficient_evidence"])
def test_keeping_the_feed_or_not_knowing_raises_nothing(claude, pick):  # noqa: F811
    c, fake = _run(claude, pick, feed_ec_sensor=FEED)
    assert _feed_asks(c) and not _created(fake, "CS-711")


def test_no_feed_sensor_no_ask(claude):  # noqa: F811
    c, fake = _run(claude, "feed_ec_down_small")
    assert c.jev.feed is not None and not _feed_asks(c) and not _created(fake, "CS-711")


def test_asked_once_a_grow_day_and_not_before_an_hour_after_lights_on(claude):  # noqa: F811
    c, fake = _run(claude, "feed_ec_down_small", passes=3, feed_ec_sensor=FEED)
    assert len(_feed_asks(c)) == 2  # lane 0 and lane 1 of the one ask
    early = NOW.replace(hour=10, minute=30)  # lights on at 10:00: half an hour in
    c2, _ = claude(B.judging({"proposal": "feed_ec_down_small"}), feed_ec_sensor=FEED)
    c2._clock.t = early.timestamp()
    c2.loop_once(early)
    assert not _feed_asks(c2)
    nxt = NOW + timedelta(days=1)  # the next grow-day it is asked again
    c._clock.t = nxt.timestamp()
    _zone(c)
    c.loop_once(nxt)
    assert len(_feed_asks(c)) == 4


def test_the_legacy_route_never_builds_it(tmp_path):
    brain = jev_bridge.build({"jev_judges": "all"}, ("acct", "tok", None), str(tmp_path / "state.json"), print,
                             jev_bridge.BrainStatus("jev_legacy", "legacy", "Jev."))
    assert brain.feed is None


def test_only_a_firm_change_is_a_proposal():
    def v(label, prob, agreed=True):
        return council.Verdict("proposal", "choice", label, prob, 0.8, agreed, 2)

    assert feed.proposal(v("feed_ec_up_small", 0.8)) == "feed_ec_up_small"
    assert feed.proposal(v("feed_ec_up_small", 0.5)) is None
    assert feed.proposal(v("feed_ec_up_small", 0.8, agreed=False)) is None
    assert feed.proposal(v("keep_feed", 0.9)) is None and feed.proposal(None) is None
    assert set(feed.WORDS) < set(feed.PROPOSAL) and "insufficient_evidence" in feed.PROPOSAL
