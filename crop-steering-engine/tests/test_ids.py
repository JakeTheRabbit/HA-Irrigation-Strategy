"""ULID ids — 26-char Crockford base32, time-sortable. Pure, offline."""

from datetime import UTC, datetime

from crop_steering_engine.ids import ULID_RE, derived_id, new_id


def test_new_id_is_a_26_char_ulid_sorted_by_time():
    a = new_id(datetime(2026, 10, 22, 7, 0, tzinfo=UTC), b"\0" * 10)
    b = new_id(datetime(2026, 10, 22, 7, 0, 1, tzinfo=UTC), b"\0" * 10)
    assert ULID_RE.fullmatch(a) and ULID_RE.fullmatch(b) and a < b


def test_new_id_defaults_produce_a_valid_ulid():
    assert ULID_RE.fullmatch(new_id())


def test_derived_id_is_stable_for_the_same_row():
    at = datetime(2026, 1, 1, tzinfo=UTC)
    assert derived_id(at, "setpoint_log:x:1") == derived_id(at, "setpoint_log:x:1")
    assert derived_id(at, "setpoint_log:x:1") != derived_id(at, "setpoint_log:x:2")
    assert ULID_RE.fullmatch(derived_id(at, "setpoint_log:x:1"))


def test_epoch_with_zero_random_is_all_zeros():
    assert new_id(datetime(1970, 1, 1, tzinfo=UTC), b"\0" * 10) == "0" * 26
