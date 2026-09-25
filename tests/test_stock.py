"""Stock tanks: checked edits, the draw per batch, refills, and counting each batch exactly once."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.crop_steering import stock

NZ = timezone(timedelta(hours=12))
NOW = "2026-09-25T08:00:00+12:00"


def tanks(*items):
    return stock.clean_tanks(list(items), [], NOW)


def test_a_new_tank_starts_full_with_a_low_mark_at_a_fifth():
    [bloom] = tanks({"name": "Bloom", "capacity_l": 50, "dose_ml": 1800})
    assert bloom["id"] == "bloom"
    assert bloom["level_l"] == 50
    assert bloom["low_l"] == 10
    assert bloom["dose_entity"] is None


def test_edits_keep_the_id_and_a_smaller_capacity_brings_the_level_down():
    [bloom] = tanks({"name": "Bloom", "capacity_l": 50, "dose_ml": 1800})
    [edited] = stock.clean_tanks(
        [{"id": "bloom", "name": "Bloom A", "capacity_l": 20, "dose_ml": 900}],
        [bloom],
        NOW,
    )
    assert edited["id"] == "bloom"
    assert edited["level_l"] == 20
    assert edited["low_l"] == 10


def test_names_ids_and_numbers_are_checked():
    with pytest.raises(stock.StockError, match="name"):
        tanks({"name": "", "capacity_l": 5})
    with pytest.raises(stock.StockError, match="capacity l"):
        tanks({"name": "A", "capacity_l": 0})
    with pytest.raises(stock.StockError, match="two stock tanks"):
        tanks({"name": "A", "capacity_l": 5}, {"name": "a", "capacity_l": 5})
    with pytest.raises(stock.StockError, match="not a number"):
        tanks({"name": "A", "capacity_l": 5, "dose_entity": "switch.pump"})
    # Two names that slug alike still get distinct ids.
    first, second = tanks(
        {"name": "Part A", "capacity_l": 5}, {"name": "Part-A!", "capacity_l": 5}
    )
    assert (first["id"], second["id"]) == ("part_a", "part_a_2")


def test_a_batch_draws_each_dose_and_never_below_empty():
    data = stock.empty()
    data["tanks"] = tanks(
        {"name": "Bloom", "capacity_l": 50, "dose_ml": 1800},
        {"name": "Cal", "capacity_l": 1, "level_l": 0.1, "dose_ml": 250},
    )
    stock.draw(data, {"bloom": 1800, "cal": 250}, NOW, "fill")
    assert [t["level_l"] for t in data["tanks"]] == [48.2, 0]
    assert data["history"][0]["draw_ml"] == {"bloom": 1800.0, "cal": 100.0}


def test_the_dose_entity_wins_while_it_reads_a_number():
    tank = {"dose_ml": 200, "dose_entity": "number.doser_bloom_dose"}
    assert stock.dose_ml(tank, "1800") == 1800
    assert stock.dose_ml(tank, "unavailable") == 200
    assert stock.dose_ml(tank, "not a number") == 200
    assert stock.dose_ml({"dose_ml": 200, "dose_entity": None}, "1800") == 200


def test_refilled_and_set_level():
    data = stock.empty()
    data["tanks"] = tanks({"name": "Bloom", "capacity_l": 50, "level_l": 4})
    stock.refill(data, "bloom", None, NOW)
    assert (data["tanks"][0]["level_l"], data["tanks"][0]["refilled_at"]) == (50, NOW)
    stock.refill(data, "bloom", 12.5, NOW)
    assert data["tanks"][0]["level_l"] == 12.5
    with pytest.raises(stock.StockError):
        stock.refill(data, "bloom", 60, NOW)
    with pytest.raises(stock.StockError):
        stock.refill(data, "nope", None, NOW)


def test_low_and_batches_left():
    data = stock.empty()
    data["tanks"] = tanks(
        {"name": "Bloom", "capacity_l": 50, "level_l": 9.9, "dose_ml": 1800}
    )
    assert [t["id"] for t in stock.low_tanks(data)] == ["bloom"]
    assert stock.batches_left(data["tanks"][0], 1800) == 5
    assert stock.batches_left(data["tanks"][0], 0) is None
    assert stock.batches_left({"level_l": 0.29}, 290) == 1  # not 0: float rounding


def test_fill_times_from_a_timestamp_sensor_and_a_date_time_helper():
    assert stock.parse_fill("2026-09-24T07:16:08+00:00", NZ) == datetime(
        2026, 9, 24, 7, 16, 8, tzinfo=timezone.utc
    )
    # input_datetime states are local and naive.
    assert stock.parse_fill("2026-09-24 19:16:08", NZ) == datetime(
        2026, 9, 24, 19, 16, 8, tzinfo=NZ
    )
    assert stock.parse_fill("unavailable", NZ) is None
    assert stock.parse_fill("yesterday", NZ) is None


def test_each_fill_counts_once_and_the_first_only_sets_the_start():
    data = stock.empty()
    first = datetime(2026, 9, 24, 19, 16, tzinfo=NZ)
    assert (
        stock.new_batch(data, first) is False
    )  # set up after this fill: not this batch's stock
    assert stock.new_batch(data, first) is False  # a restart replays the same time
    assert stock.new_batch(data, first + timedelta(days=1)) is True
    assert stock.new_batch(data, first + timedelta(days=1)) is False
    # An older time (a helper edited backwards) is not a batch and does not move the start back.
    assert stock.new_batch(data, first) is False
    assert data["last_batch"] == (first + timedelta(days=1)).isoformat()
    assert stock.new_batch(data, None) is False
