"""The code-only shot table (shot_audit.py): every shot's rise against what its litres should give, a verdict, and
CS-701 from code only when the room asks for it and the AI assistant is off."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import shot_audit
from brain.context import Shot
from test_zone_status_one_owner import _room

T0 = datetime(2026, 10, 10, 12, 0)


def _zone_with(room, zone, shots):
    """A zone's audit history: a flat reading every minute, and each shot's rise (points) and EC move after it."""
    z = shot_audit._zone(room, zone)
    for m in range(0, 240):
        t = T0 + timedelta(minutes=m)
        vwc, ec = 50.0, 4.0
        for start_min, _litres, rise, ec_move, _kind in shots:
            if m > start_min:
                vwc += rise
                ec += ec_move
        z["hist"].add_reading(t, vwc, ec)
    for start_min, litres, _rise, _ec, kind in shots:
        z["hist"].add_shot(Shot(T0 + timedelta(minutes=start_min), 60.0, litres, kind, None, None))
    # each shot's pre-shot reading is the reading just before it
    for s in z["hist"].shots:
        r = z["hist"].at(s.start - timedelta(minutes=1))
        s.pre_vwc, s.pre_ec = r[1], r[2]
    return z


def _room_obj():
    return SimpleNamespace(slug="default")


def test_verdicts_from_the_rise_the_litres_should_give():
    room = _room_obj()
    _zone_with(room, 1, [(10, 1.0, 2.0, 0.0, "p2_topup"),   # 1 L into 10 L: +10 expected, +2 is a share of 0.2
                         (60, 1.0, 5.0, 0.0, "p2_topup"),   # 0.5 share: landed
                         (110, 1.0, 0.0, -0.3, "p2_topup"),  # flat, EC moved
                         (160, 1.0, 0.0, 0.0, "p2_topup"),   # nothing
                         (230, 1.0, 3.0, 0.0, "p2_topup")])  # too young to judge
    rows = shot_audit.table(room, 1, T0 + timedelta(minutes=239), 10.0, 70.0)
    assert [r["verdict"] for r in rows] == ["settling", "no_sign", "flat_ec_moved", "landed", "small"]
    assert rows[1]["expected_rise_pts"] == 10.0 and rows[3]["landed_share"] == 0.5
    assert rows[0]["start"].startswith("2026-10-10T15:50")


def test_two_no_sign_shots_in_a_row_alert_once_and_flush_or_full_slab_shots_do_not_count():
    room = _room_obj()
    _zone_with(room, 1, [(10, 1.0, 0.0, 0.0, "p2_topup"), (60, 1.0, 0.0, 0.0, "p3_emergency"),
                         (110, 1.0, 0.0, 0.0, "p2_topup")])
    rows = shot_audit.table(room, 1, T0 + timedelta(minutes=200), 10.0, 70.0)
    assert [r["counted"] for r in rows] == [True, False, True]
    assert shot_audit.no_sign_in_a_row(room, 1, rows) is True
    assert shot_audit.no_sign_in_a_row(room, 1, rows) is False  # the same two shots: once
    full = shot_audit.table(room, 1, T0 + timedelta(minutes=200), 10.0, 50.5)  # every shot within 1 point of FC
    assert not any(r["counted"] for r in full)


def test_the_ai_judges_answer_sits_beside_the_code_verdict():
    room = _room_obj()
    z = _zone_with(room, 1, [(10, 1.0, 5.0, 0.0, "p2_topup")])
    judge = SimpleNamespace(name="shot", _zones={("default", 1): SimpleNamespace(
        labels=[(z["hist"].shots[0].start + timedelta(seconds=3), "landed_slow")])})
    labels = shot_audit.ai_labels(SimpleNamespace(judges=[judge]), "default", 1)
    rows = shot_audit.table(room, 1, T0 + timedelta(minutes=100), 10.0, 70.0, ai=labels)
    assert (rows[0]["verdict"], rows[0]["ai_verdict"]) == ("landed", "landed_slow")


def test_a_room_that_never_chose_has_no_table():
    c, fake = _room()
    c.loop_once(T0)
    assert c.rooms[0]._shot_check == "off"
    assert "sensor.crop_steering_zone_1_shot_log_app" not in fake.sets


def test_table_mode_publishes_the_table():
    c, fake = _room()
    fake.set_state("select.crop_steering_shot_check", "table")
    c.loop_once(T0)
    state, attrs = fake.sets["sensor.crop_steering_zone_1_shot_log_app"]
    assert (state, attrs["shots"], attrs["mode"]) == ("none", [], "table")


def _alerting(c, fake, jev):
    room = c.rooms[0]
    room._shot_check = "table_and_alert"
    _zone_with(room, 1, [(10, 1.0, 0.0, 0.0, "p2_topup"), (60, 1.0, 0.0, 0.0, "p2_topup")])
    c.jev = jev
    raised = []
    c._alert = lambda key, code, *a, **k: raised.append((key, code))
    d = {"dryback": None, "p": SimpleNamespace(field_capacity=70.0)}
    c._publish_sensing(room, 1, d, T0 + timedelta(minutes=200))
    return raised


def test_rules_mode_raises_cs_701_under_the_ai_judges_key_only_with_the_ai_off():
    c, fake = _room()
    assert _alerting(c, fake, None) == [("jev_shot_default_z1", "CS-701")]
    c2, fake2 = _room()
    assert _alerting(c2, fake2, SimpleNamespace(judges=[])) == []  # the AI judge owns the alert
