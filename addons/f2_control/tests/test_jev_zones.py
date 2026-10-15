"""The zones judge compares a zone's water per plant with the room's median zone, this zone included.

27 Sep 2026, the first live day on F2: zone 1 had 2477 mL a plant, zones 2 and 3 1052 and 974. Each zone
was compared with the upper of its two siblings, so zones 2 and 3 were flagged (42 % and 39 %) against
zone 1's 2477 and told of a valve or dripper fault they did not have.
"""
import jev_kit as K
from jev import council
from jev.judges.zones import ZonesJudge

LIVE = {1: 2.477, 2: 1.052, 3: 0.974}  # litres a plant, F2 at 19:28 on 27 Sep 2026


def _ctx(zone, lpp=LIVE, plants=42):
    sib = {z: {"litres_per_plant": v, "litres_per_plant_words": f"{v * 1000:.0f} mL a plant today"}
           for z, v in lpp.items() if z != zone}
    return K.ctx("P2", s=K.snap(daily_vol=lpp[zone] * plants), zone=zone, title=f"Zone {zone}",
                 siblings=sib, plants=plants)


def test_only_the_odd_zone_of_three_is_asked():
    assert [z for z in LIVE if ZonesJudge().due(_ctx(z), None)] == [1]


def test_the_odd_zone_is_compared_with_the_room_median_zone():
    _mine, typical, ratio, basis = ZonesJudge()._ratio(_ctx(1))
    assert abs(typical - 1.052) < 1e-9 and round(ratio * 100) == 235 and basis == "the room's median zone"


def test_a_room_of_two_compares_each_zone_with_the_other():
    two = {1: 1.5, 2: 1.0}
    assert ZonesJudge().due(_ctx(1, two), None) and ZonesJudge().due(_ctx(2, two), None)
    _mine, typical, ratio, basis = ZonesJudge()._ratio(_ctx(2, two))
    assert typical == 1.5 and abs(ratio - 1.0 / 1.5) < 1e-9 and basis == "the other zone"


def test_the_alert_says_what_the_zone_was_compared_with():
    answer = K.choice_answer("water_not_landing", {"water_not_landing": 0.8, "recipe_difference": 0.2})
    verdicts = {"why_different": council.combine(K.both("why_different", answer), "why_different")}
    d = ZonesJudge().decide(verdicts, _ctx(1))
    assert d.value["code"] == "CS-702"
    assert "2477 mL a plant today, 235% of the room's median zone (1052 mL)" in d.value["message"]
