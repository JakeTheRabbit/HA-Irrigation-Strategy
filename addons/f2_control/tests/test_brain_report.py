"""The daily grower report (haiku-brain-design section 5): a room task under claude_haiku, asked once a grow-day three
hours after lights-off (after the setpoints judge's window), only when the budget allows; ADVISES only, published on
its own sensor and kept in /data across a restart."""
import json
import re
from datetime import datetime

import brain_kit as B
import brain_bridge
import pytest
from brain.client import HA_STATE_MAX, MAX_TEXT, validate_answer
from brain.prompt import REPORT_MAX_TOKENS, Prompt
from test_brain_wiring import claude  # noqa: F401 - the fixture
from test_jev_controller import KILL

LANE = brain_bridge.REPORT_QUESTION
SNAP = "default:zroom:report:2026-09-28T01:30:abcd"
NIGHT = datetime(2026, 9, 28, 1, 30)  # lights 10-22: three and a half hours after lights-off
EARLY = datetime(2026, 9, 27, 23, 30)  # an hour and a half after: the setpoints judge's window


def _report(snap, **over):
    args = {"snapshot_id": snap, "headline": "A steady day in every zone.",
            "zones": [{"zone": 1, "line": "Drank 1.2 L a plant; dried back 9 % overnight."}],
            "watch": ["Check the zone 1 drippers."], **over}
    return B.tool("write_report", **args)


def reporting(request):
    """Answer a report request with write_report, and every judge's question as brain_kit.judging() does."""
    text = request["messages"][0]["content"][1]["text"]
    if 'id="report"' in text:
        return B.message(_report(re.search(r'snapshot_id="([^"]+)"', text).group(1)))
    return B.judging()(request)


def _asked(c):
    return [r for r in c._client.requests if 'id="report"' in r["messages"][0]["content"][1]["text"]]


def test_a_report_call_is_cleaned_and_capped():
    long = "sensor.crop_steering_vwc_zone_1 reads high.\n" + "x" * 400
    qid, ans = validate_answer(_report(SNAP, headline=long, watch=["a", "", "b", "c", "d", 7],
                                       zones=[{"zone": 1, "line": "ok\tfine"}, {"zone": True, "line": "no"},
                                              {"zone": 2}, "z3"]), SNAP, LANE)
    assert qid == "report" and ans["type"] == "report"
    assert len(ans["headline"]) == HA_STATE_MAX and "sensor." not in ans["headline"] and "\n" not in ans["headline"]
    assert ans["zones"] == [{"zone": 1, "line": "ok fine"}] and ans["watch"] == ["a", "b", "c"]
    assert len(validate_answer(_report(SNAP, watch=["y" * 900]), SNAP, LANE)[1]["watch"][0]) == MAX_TEXT


def test_a_report_call_that_does_not_fit_is_no_report():
    assert validate_answer(_report("another:snapshot"), SNAP, LANE) is None
    assert validate_answer(_report(SNAP, headline=None), SNAP, LANE) is None
    assert validate_answer(_report(SNAP, zones="all fine"), SNAP, LANE) is None
    dusk = {"dusk_call__v0": {"type": "choice", "instructions": "stop?", "criteria": B.DUSK}}
    assert validate_answer(_report(SNAP), SNAP, dusk) is None  # no report asked in this lane


def test_the_report_question_is_one_lane_with_room_for_the_report():
    text = Prompt.questions(SNAP, 0, LANE)
    assert '<question id="report" kind="report">' in text and "write_report" in text and "<allowed>" not in text
    assert Prompt.max_tokens(LANE) == REPORT_MAX_TOKENS


def test_the_report_is_asked_once_a_grow_day_after_the_setpoints_window(claude):  # noqa: F811
    c, fake = claude(reporting)
    room = c.rooms[0]
    room.state[1].update(daily_vol=4.8, shots=9, peak=41.2)
    c._clock.t = EARLY.timestamp()
    c.loop_once(EARLY)
    assert not _asked(c), "not inside the setpoints judge's window"
    c._clock.t = NIGHT.timestamp()
    c.loop_once(NIGHT)
    assert len(_asked(c)) == 1
    sent = _asked(c)[0]["messages"][0]["content"][0]["text"]
    assert ":zroom:report:" in sent and "grow_day: 2026-09-27" in sent and '"water_l": 4.8' in sent
    c.loop_once(NIGHT)  # the answer is published on the next pass, and nothing is asked again
    assert len(_asked(c)) == 1
    state, attrs = fake.sets["sensor.crop_steering_brain_report"]
    assert state == "A steady day in every zone." and attrs["grow_day"] == "2026-09-27"
    assert attrs["zones"][0]["zone"] == 1 and attrs["watch"] == ["Check the zone 1 drippers."]
    assert attrs["cost_usd"] > 0
    assert "report" in fake.sets["sensor.crop_steering_jev"][1]["judges_advising"]
    saved = json.load(open(c.jev.report_path, encoding="utf-8"))
    assert saved["default"]["grow_day"] == "2026-09-27" and saved["default"]["report"]["headline"]

    c2, fake2 = claude(reporting)  # a restart the same night: the report is kept and not asked again
    c2._clock.t = NIGHT.timestamp()
    c2.loop_once(NIGHT)
    assert not _asked(c2)
    assert fake2.sets["sensor.crop_steering_brain_report"][0] == "A steady day in every zone."


def test_a_spent_budget_asks_for_no_report(claude):  # noqa: F811
    c, fake = claude(reporting, anthropic_daily_budget_usd=0.0)
    c._clock.t = NIGHT.timestamp()
    c.loop_once(NIGHT)
    c.loop_once(NIGHT)
    assert not _asked(c) and "sensor.crop_steering_brain_report" not in fake.sets


def test_the_report_is_off_when_it_is_not_among_the_judges(claude):  # noqa: F811
    c, fake = claude(reporting, ai_judges="dawn,ramp,setpoints")
    c._clock.t = NIGHT.timestamp()
    c.loop_once(NIGHT)
    assert not _asked(c) and "report" not in fake.sets["sensor.crop_steering_jev"][1]["judges_advising"]


@pytest.mark.parametrize("entity", [KILL, "sensor.crop_steering_vwc_zone_1"])
def test_no_report_with_the_kill_switch_off_or_stale_readings(claude, entity):  # noqa: F811
    c, fake = claude(reporting)
    fake.set_state(entity, "off" if entity == KILL else "unavailable")
    c._clock.t = NIGHT.timestamp()
    c.loop_once(NIGHT)
    c.loop_once(NIGHT)
    assert not _asked(c) and "sensor.crop_steering_brain_report" not in fake.sets
