"""The controller's log in plain words (log_words.py, and where controller.py says it): why a zone
changed phase or fired, why it is held, and who changed a setting.

The transitions, shots and holds are the engine's own: these run decide() for them, so a change to the
engine's texts that the log would no longer recognise fails here, not quietly in a live log. The
setting names are the dashboard's, read from its own file."""

import re
from pathlib import Path

import pytest

import controller
import log_words
from crop_steering_engine import Reason, ZoneParams, ZoneSnapshot, decide
from test_controller import _build, _desc

ROOT = Path(__file__).resolve().parents[3]
WORDS = (ROOT / "frontend" / "src" / "lib" / "setting-words.ts").read_text(encoding="utf-8")


def P(**kw):
    d = dict(
        p1_target=60,
        p2_threshold=45,
        p2_shot_size=5,
        p1_initial=2,
        p1_incr=0.5,
        p1_max_shots=12,
        p1_time_between_min=15,
        dryback_target=20,
        p0_max_wait_min=45,
        ec_target_p0=4,
        ec_target_p1=5,
        ec_target_p2=6,
        p3_emergency_floor=40,
        p3_emergency_shot=2,
        max_daily_volume=300,
        field_capacity=70,
        max_ec=9,
        stacking_on=False,
    )
    d.update(kw)
    return ZoneParams(**d)


def S(**kw):
    d = dict(
        vwc=50,
        ec=6,
        phase="P2",
        peak_vwc=60,
        dryback_pct=0,
        dryback_rate=2,
        shot_count=0,
        phase_minutes=5,
        minutes_since_shot=99,
        daily_vol=0,
        ec_smooth=6,
        lights_on=True,
        lights_just_on=False,
        hours_to_lights_on=8,
        hours_to_lights_off=8,
        uptime_min=60,
    )
    d.update(kw)
    return ZoneSnapshot(**d)


@pytest.mark.parametrize(
    "snap, words",
    [
        (S(phase="P2", lights_on=False), "lights off"),
        (S(phase="P3", lights_just_on=True), "lights on"),
        (S(phase="P2", new_grow_day=True), "a new grow-day began before this zone finished the last one"),
        (
            S(phase="P0", vwc=44),
            "VWC 44% is at or under the maintenance trigger (45%), no morning dryback needed",
        ),
        (S(phase="P0", vwc=50, dryback_pct=25), "the morning dryback reached 25%"),
        (S(phase="P0", vwc=55, phase_minutes=50), "the latest first shot came, 50 min into P0"),
        (S(phase="P1", vwc=50, shot_count=12), "all 12 ramp shots are in"),
        (
            S(phase="P1", vwc=61, shot_count=3, p1_reached=True, p1_extra_shots=1, peak_vwc=61,
              p1_peak_before_shot=60.8, minutes_since_shot=20),
            "the last shot raised the peak only 0.2 points (under 0.5), so the slab is full",
        ),
    ],
)
def test_a_phase_change_says_why(snap, words):
    new_phase, _, _, _, reason = decide(snap, P())
    assert new_phase != snap.phase
    assert log_words.transition(reason) == words


@pytest.mark.parametrize(
    "snap, said",
    [
        (S(phase="P1", vwc=50, ec=5), ("ramp shot", "VWC 50% under the 60% peak target")),
        (
            S(phase="P1", vwc=61, ec=5, shot_count=1),
            (
                "extra ramp shot",
                "VWC reached the 60% peak target; one more shot shows whether the slab is full",
            ),
        ),
        (S(phase="P2", vwc=40), ("maintenance shot", "VWC 40% under the 45% maintenance trigger")),
        (S(phase="P3", vwc=35, lights_on=False), ("rescue shot", "VWC 35% under the 40% rescue level")),
        (
            S(phase="P2", vwc=40, ec=None, ec_smooth=None),
            (
                "maintenance shot",
                "VWC 40% under the 45% maintenance trigger; EC unknown, watering by moisture alone",
            ),
        ),
    ],
)
def test_a_shot_says_what_it_is_and_why(snap, said):
    _, _, fire, _, reason = decide(snap, P())
    assert fire
    assert log_words.shot(reason) == said


def test_a_held_zone_says_why_and_a_quiet_one_nothing():
    _, _, fire, _, reason = decide(S(phase="P2", vwc=40, daily_vol=300), P())
    assert not fire and reason.kind == "block_daily_cap"
    assert log_words.hold(reason) == (
        "the daily water limit is spent (300 of 300 L); rescue shots still run"
    )
    _, _, fire, _, reason = decide(S(phase="P2", vwc=69, ec=10, feed_ec=12), P())
    assert not fire and reason.kind == "block_high_ec"
    assert log_words.hold(reason) == (
        "EC 10.0 over the maximum and a flush can't bring it down now (feed not dilutive), "
        "so nothing runs until one can"
    )
    _, _, fire, _, reason = decide(S(phase="P2", vwc=50), P())
    assert not fire and log_words.hold(reason) == ""
    # What it does not know it says as it is.
    assert log_words.hold(Reason("something new", "new")) == "something new"
    assert log_words.shot(Reason("NEW rule 3", "new")) == ("shot", "NEW rule 3")


def test_setting_names_are_the_dashboards():
    short = dict(re.findall(r'\n  (\w+): \{\n    label: "[^"]+",\n    short: "([^"]+)"', WORDS))
    assert len(short) >= 20, "setting-words.ts no longer reads as this test expects"
    assert log_words.SETTING_NAMES == short
    ec = dict(re.findall(r'\n  "(\d)": \{\n    label: "[^"]+",\n    short: "([^"]+)"', WORDS))
    assert set(ec) == {"0", "1", "2"}
    for phase, name in ec.items():
        assert log_words.setting_name(f"ec_target_p{phase}") == name
        assert log_words.setting_name(f"ec_target_veg_p{phase}") == f"{name} (vegetative)"
    dryback = re.search(r"const DRYBACK_WORDS: SettingWords = \{\n  label: \"[^\"]+\",\n  short: \"([^\"]+)\"", WORDS)
    assert log_words.setting_name("dryback_target") == dryback[1]
    assert log_words.setting_name("generative_dryback_target") == f"{dryback[1]} (generative)"
    assert log_words.setting_name("maximum_shot_duration") == "Longest shot"
    assert log_words.setting_name("some_new_knob") == "Some new knob"


def test_a_change_is_one_sentence_as_the_dashboard_says_it():
    assert log_words.change("Most P1 shots", "", 6, 10, "Sam") == "Sam raised Most P1 shots to 10 (was 6)"
    assert log_words.change("Maintenance trigger", "%", 71.3, 63.3, "Automation \"Tweak\"") == (
        "Automation \"Tweak\" lowered Maintenance trigger to 63.3% (was 71.3%)"
    )
    assert log_words.change("Maximum EC", "mS/cm", 8.5, 9, None) == "Maximum EC raised to 9 mS/cm (was 8.5 mS/cm)"
    assert log_words.amount(12.345, "min") == "12.35 min"


def test_who_from_the_logbook():
    people = {"u1": "Sam"}
    entry = {"state": "10.0", "context_user_id": "u1"}
    assert log_words.who([entry], 10, people) == "Sam"
    assert log_words.who([{**entry, "context_user_id": "supervisor"}], 10, people) is None
    automation = {"state": "10", "context_event_type": "automation_triggered", "context_name": "Tweak"}
    assert log_words.who([automation], 10, people) == 'Automation "Tweak"'
    assert log_words.who([{"state": "10", "context_event_type": "script_started"}], 10, people) == "A script"
    # The newest entry to that value; another value, or no state, is another change.
    assert log_words.who([{**entry, "context_user_id": "u2"}, entry], 10, people) == "Sam"
    assert log_words.who([{"state": "9", "context_user_id": "u1"}, {"message": "x"}], 10, people) is None


# ---------------------------------------------------------------- the controller's own lines
SHOTS = "number.crop_steering_zone_1_p1_maximum_shots"


def _room(monkeypatch, logbook):
    """The default room with one zone and Sam, a person; the logbook's entries are `logbook`."""
    c, fake = _build(
        {"num_zones": 1},
        states={
            "sensor.crop_steering_engine_config": ("ok", _desc()),
            SHOTS: ("6", {}),
            "person.sam": ("home", {"user_id": "u1", "friendly_name": "Sam"}),
        },
    )
    asked = []

    def read(entity, since, timeout=8):
        asked.append(entity)
        return logbook

    monkeypatch.setattr(controller, "ha_logbook", read)
    return c, fake, asked


def test_a_setting_change_is_logged_with_who_made_it(monkeypatch, capsys):
    c, fake, asked = _room(monkeypatch, [{"entity_id": SHOTS, "state": "10.0", "context_user_id": "u1"}])
    slug = c.rooms[0].slug
    assert c._zone_num(c.rooms[0], 1, "p1_maximum_shots", 12) == 6  # the first read only notes it
    capsys.readouterr()
    fake.set_state(SHOTS, "10")
    assert c._zone_num(c.rooms[0], 1, "p1_maximum_shots", 12) == 10
    said = [line for line in capsys.readouterr().out.splitlines() if "Most P1 shots" in line]
    assert said == [f"[f2-control] [{slug}] Z1 Sam raised Most P1 shots to 10 (was 6)"]
    assert asked == [SHOTS]
    # Said once: the next read has nothing new.
    c._zone_num(c.rooms[0], 1, "p1_maximum_shots", 12)
    assert "Most P1 shots" not in capsys.readouterr().out


def test_a_change_nobody_can_be_named_for_is_still_said(monkeypatch, capsys):
    c, fake, _ = _room(monkeypatch, [])
    c._zone_num(c.rooms[0], 1, "p1_maximum_shots", 12)
    fake.set_state(SHOTS, "4")
    c._zone_num(c.rooms[0], 1, "p1_maximum_shots", 12)
    assert "Most P1 shots lowered to 4 (was 6)" in capsys.readouterr().out


def test_the_controllers_own_write_is_not_said_twice(monkeypatch, capsys):
    c, fake, asked = _room(monkeypatch, [])
    room = c.rooms[0]
    c._zone_num(room, 1, "p1_maximum_shots", 12)
    from datetime import datetime

    assert c._auto_write(room, 1, "p1_maximum_shots", 6, 8, {}, datetime.now())
    fake.set_state(SHOTS, "8")  # Home Assistant reflects the write
    capsys.readouterr()
    c._zone_num(room, 1, "p1_maximum_shots", 12)
    assert "Most P1 shots" not in capsys.readouterr().out
    assert asked == []
