"""The Claude brain's budget (brain.client.Meter and PRICES): every billed token priced at its model's row, a window
from one lights-on to the next, the reasons it may not ask, and safe under a worker thread (haiku-brain-design 10)."""
import random
import threading

import brain_kit as B
import pytest
from brain.client import DEFAULT_MODEL, PRICES, Meter, cost

H = 3600.0


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_the_price_table_is_the_allowlist_and_holds_the_default():
    assert set(PRICES) == {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}
    assert DEFAULT_MODEL in PRICES


def test_every_kind_of_token_is_priced_at_its_rate():
    m = 100_000  # at most 100k prompt tokens: the first rate card

    def priced(model="claude-haiku-5-5", **n):
        return cost(B.usage(**{"uncached": 0, "w5m": 0, "w1h": 0, "read": 0, "out": 0, **n}), model) * 1e6 / m

    assert priced(uncached=m) == pytest.approx(0.10)
    assert priced(w5m=m) == pytest.approx(0.125)
    assert priced(w1h=m) == pytest.approx(0.20)
    assert priced(read=m) == pytest.approx(0.01)
    assert priced(out=m) == pytest.approx(0.50)
    assert priced("claude-sonnet-5-5", uncached=m) == pytest.approx(2.0)
    assert priced("claude-opus-5-5", out=m) == pytest.approx(20.0)
    # the design's one ask: lane 0 writes the evidence, lane 1 reads it
    lane0 = cost(B.usage(uncached=400, w5m=1500, w1h=0, read=17000, out=350), "claude-haiku-5-5")
    assert lane0 == pytest.approx(572.5e-6)


def test_writes_with_no_split_are_priced_at_the_one_hour_rate():
    use = {"input_tokens": 0, "cache_creation_input_tokens": 100_000, "cache_read_input_tokens": 0,
           "output_tokens": 0}
    assert cost(use, "claude-haiku-5-5") == pytest.approx(0.02)


def test_a_prompt_over_100k_tokens_takes_the_dearer_card():
    use = B.usage(uncached=100_001, w5m=0, w1h=0, read=0, out=0)
    assert cost(use, "claude-haiku-5-5") == pytest.approx(100_001 * 0.50 / 1e6)


def test_spending_the_budget_stops_the_brain_and_warns_once_at_80_percent():
    m = Meter(0.001, clock=Clock())
    m.charge(B.usage(uncached=0, w5m=0, w1h=0, read=0, out=1700))  # 0.00085 of 0.001
    assert m.take("warn") and not m.take("warn") and m.can_spend()
    m.charge(B.usage(uncached=0, w5m=0, w1h=0, read=0, out=400))
    assert not m.can_spend() and m.state() == "budget_spent" and m.take("spent") and not m.take("spent")
    assert not m.live()


def test_a_budget_of_zero_never_calls():
    assert not Meter(0.0, clock=Clock()).can_spend()


def test_a_window_opened_at_start_closes_at_the_first_lights_on():
    clock = Clock()
    m = Meter(1.0, clock=clock)
    m.charge(B.usage())
    clock.t += 2 * H
    assert m.lights_on() and m.snapshot()["cost_usd"] == 0 and m.opened_by == "lights_on"
    m.charge(B.usage())
    clock.t += 2 * H
    assert not m.lights_on()  # a second room's lights-on two hours later is the same window
    clock.t += 18 * H
    assert m.lights_on()  # 20 h on: tomorrow's


def test_with_no_lights_on_a_window_closes_after_24_hours():
    clock = Clock()
    m = Meter(0.0001, clock=clock)
    m.charge(B.usage())
    m.opened_by = "lights_on"
    assert m.state() == "budget_spent"
    clock.t += 24 * H
    assert m.state() is None and m.opened_by == "timer"


def test_a_restart_restores_a_lights_on_window_but_never_a_latch():
    clock = Clock()
    m = Meter(1.0, clock=clock)
    m.lights_on()
    m.charge(B.usage())
    m.latch("auth_failed")
    saved = m.snapshot()
    clock.t += 2 * H
    again = Meter(1.0, clock=clock)
    assert again.restore(saved) and again.snapshot()["cost_usd"] == saved["cost_usd"] > 0
    assert again.state() is None  # the key may have been changed: one more try
    assert not again.lights_on()  # a window opened at a lights-on two hours ago stays open
    old = Meter(1.0, clock=clock)
    assert not old.restore({"day": "2026-09-27", "calls": 41})  # 3.11.1's file: a window opens at start
    assert old.opened_by == "start" and old.snapshot()["cost_usd"] == 0


def test_three_refusals_in_a_row_decline_a_judge_and_an_answer_clears_it():
    m = Meter(1.0, clock=Clock())
    for _ in range(2):
        m.refused("night", "bio")
    m.answered("night")
    for _ in range(2):
        m.refused("night")
    assert "night" not in m.snapshot()["declined"]
    m.refused("night")
    assert m.snapshot()["declined"] == ["night"] and m.live()
    for _ in range(3):
        m.refused("setpoints")
    assert not m.live() and m.state() is None  # the setpoints judge declining hands its levers to the learner


def test_a_pause_stops_new_asks_but_not_the_call_in_flight():
    clock = Clock()
    m = Meter(1.0, clock=clock)
    m.pause(60)
    assert m.state() == "paused" and m.can_spend() and not m.live()
    clock.t += 61
    assert m.state() is None


def test_safe_under_a_worker_thread_charging_while_the_loop_reads():
    m = Meter(1000.0)
    rng = random.Random(7)
    sizes = [rng.randint(1, 5000) for _ in range(2000)]
    stop = []

    def worker():
        for n in sizes:
            m.charge(B.usage(uncached=n, w5m=0, w1h=0, read=0, out=0))
        stop.append(1)

    t = threading.Thread(target=worker)
    t.start()
    while not stop:
        m.can_spend(), m.live(), m.snapshot()
    t.join()
    snap = m.snapshot()
    assert snap["calls"] == 2000 and snap["uncached_tokens"] == sum(sizes)
    assert snap["cost_usd"] == pytest.approx(sum(sizes) * 0.10 / 1e6, abs=1e-6)
