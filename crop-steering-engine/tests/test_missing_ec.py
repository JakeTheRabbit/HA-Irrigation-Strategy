"""Missing EC is an explicit, conservative VWC-driven fallback."""
import pytest

from crop_steering_engine import decide, ec_adjust, zone_safety_status, system_safety_status
from test_core import P, S


@pytest.mark.parametrize("ec", [None, float("nan"), float("inf"), float("-inf")])
def test_missing_ec_does_not_scale_water_or_infer_flush(ec):
    assert ec_adjust(5, ec, 6) == 5
    for phase, expected in (("P1", 2), ("P2", 5)):
        _, _, fire, size, reason = decide(S(phase=phase, ec=ec, vwc=44), P())
        assert fire and size == expected
        assert "EC unknown" in reason and "FLUSH" not in reason
    assert not decide(S(phase="P2", ec=ec, vwc=55), P())[2]


def test_missing_ec_p1_exit_requires_watered_ceiling_or_existing_timeout_limit():
    assert decide(S(phase="P1", ec=None, vwc=60, shot_count=0), P())[0] == "P1"
    result = decide(S(phase="P1", ec=None, vwc=60, shot_count=1), P())
    assert result[0] == "P2" and "flush unverified" in result[4]
    assert decide(S(phase="P1", ec=None, vwc=45, shot_count=12), P())[0] == "P2"
    assert decide(S(phase="P1", ec=None, vwc=45, phase_minutes=120), P())[0] == "P2"


def test_missing_ec_preserves_budget_dry_rescue_and_safety_warning():
    result = decide(S(ec=None, vwc=44, daily_vol=300), P())
    assert not result[2] and "daily-cap" in result[4]
    result = decide(S(phase="P3", ec=None, vwc=35, daily_vol=300, lights_on=False), P())
    assert result[2] and result[3] == 2 and "emergency" in result[4]
    assert zone_safety_status(45, None, 70, 9) == "ec_unknown"
    assert system_safety_status(["ec_unknown"]) == ("warning", 0, 1, 0)
    assert zone_safety_status(80, None, 70, 9) == "over_saturated"
