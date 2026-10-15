"""The in-band skip: the probe and salt judges are not asked while code sees nothing for them to call.

A zone whose shots all kept a normal rise and whose reading is not a flat line has its probe judged every 2 hours,
not every 30 minutes; a zone whose settled pore EC is inside the steer's band and steady has no salt ask at all.
The moment code sees otherwise (a shot that kept nothing, a flat line, pore EC out of the band or moving), the judge
is back on its own 30-minute cadence. What a judge decides when it is asked does not change.
"""
from datetime import timedelta

import controller
import jev_kit as K
from jev.brain import Brain
from jev.client import Asker
from jev.context import Shot, ZoneHistory
from jev.judges.probe import ProbeJudge
from jev.judges.salt import SaltJudge
from jev.ledger import Ledger

START = K.NOW.replace(hour=8, minute=0)


def _stretch(minutes=360, stuck_after=None, ec_rise=0.0):
    """Six hours of P2, one pass a minute: an hourly shot that adds 2 points, drying 0.02 points a minute, pore EC
    4.4 against a 4.5 target. From `stuck_after` the probe reads one value whatever the shots do. Yields contexts."""
    h, vwc, ec = ZoneHistory(), 36.0, 4.4
    for m in range(minutes):
        now = START + timedelta(minutes=m)
        stuck = stuck_after is not None and m >= stuck_after
        if m % 60 == 0:
            h.add_shot(Shot(now, 60, 3.0, "p2_topup", vwc, ec))
            vwc += 0.0 if stuck else 2.0
        vwc -= 0.0 if stuck else 0.02
        ec += ec_rise / 60.0
        h.add_reading(now, vwc, ec)
        yield m, K.ctx("P2", s=K.snap(vwc=vwc, ec=ec, ec_settled=ec, ec_smooth=ec), h=h, now=now)


def _asks(judge, **kw):
    """The minutes of the stretch the judge is asked on, as the brain asks it (Brain._judge: due, then last_asked)."""
    last, out = None, []
    for m, ctx in _stretch(**kw):
        if judge.due(ctx, last):
            last = ctx.now
            out.append(m)
    return out


def test_a_working_probe_is_judged_every_2_hours_not_every_30_minutes(monkeypatch):
    assert _asks(ProbeJudge()) == [60, 180, 300]
    monkeypatch.setattr(ProbeJudge, "nominal", lambda self, ctx: False)  # JEV's cadence, for comparison
    assert _asks(ProbeJudge()) == [60, 90, 120, 150, 180, 210, 240, 270, 300, 330]


def test_a_probe_that_stops_answering_the_shots_is_back_on_its_cadence_at_once():
    asks = _asks(ProbeJudge(), stuck_after=200)
    assert asks[:2] == [60, 180]
    # stuck from 200 (the reading has not moved 0.05 points since 197): a flat line at 227, asked on that pass,
    # then every 30 minutes
    assert asks[2:] == [227, 257, 287, 317, 347]


def test_pore_ec_inside_the_band_and_steady_is_not_asked_about(monkeypatch):
    assert _asks(SaltJudge()) == [0]  # the first pass, before any readings say pore EC is steady
    monkeypatch.setattr(SaltJudge, "in_band", staticmethod(lambda ctx: False))
    assert len(_asks(SaltJudge())) == 12


def test_pore_ec_that_moves_or_leaves_the_band_is_asked_about_every_30_minutes():
    asks = _asks(SaltJudge(), ec_rise=0.3)  # climbing 0.3 mS/cm an hour: not steady, then above the band
    assert asks[0] <= 3 and all(b - a == 30 for a, b in zip(asks, asks[1:])) and len(asks) == 12


def test_the_skip_saves_asks_and_changes_no_decision():
    """Through the brain: a nominal stretch costs under a fifth of the probe and salt asks, and the directives that act
    are the same. The salt ask it saves could only say "in band, hold", which the steer at rest already does."""
    answers = {**K.both("tracking", K.noul_answer(0.95)),
               **K.both("mode", K.choice_answer("healthy", {"healthy": 0.9, "stuck": 0.1})),
               **K.both("salt_cause", K.choice_answer("in_band", {"in_band": 0.9, "feed_changed": 0.1}))}

    def run(skip):
        t, clock = K.FakeTransport(answers), {"t": 0.0}
        asker = Asker("acct", "tok", transport=t, threaded=False, clock=lambda: clock["t"])
        probe, salt = ProbeJudge(), SaltJudge()
        if not skip:
            probe.nominal = lambda ctx: False
            salt.in_band = lambda ctx: False
        brain = Brain(asker, Ledger(None), [probe, salt], log=lambda *a: None)
        acted = []
        for _, ctx in _stretch():
            clock["t"] = ctx.now.timestamp()
            acted += [(d.kind, d.value) for d, _ in brain.tick(ctx) if (d.kind, d.value) != ("ec_mode", "hold")]
        return len(t.calls), acted

    (skipped, acted_skipped), (full, acted_full) = run(True), run(False)
    assert (skipped, full) == (4, 22)
    assert acted_skipped == acted_full == []
    # inside the band the steer at rest leaves an offset at rest where it is, as a hold would
    assert controller.Controller._step_ec_offset(0.0, 4.4, 4.5, 45.0) == 0.0
