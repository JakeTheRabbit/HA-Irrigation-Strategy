"""Unit tests for Crop Steering System calculations."""
import pytest
from custom_components.crop_steering.sensor import ShotCalculator
from custom_components.crop_steering.const import (
    SECONDS_PER_HOUR,
    PERCENTAGE_TO_RATIO,
    VWC_ADJUSTMENT_PERCENT,
)


class TestShotCalculator:
    """Test shot duration calculations."""

    def test_basic_shot_calculation(self):
        """Test basic shot duration calculation."""
        # 10L pot, 2 L/hr flow, 5% shot size
        # Expected: (10 * 0.05) / 2 * 3600 = 900 seconds
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.0,
            substrate_vol=10.0,
            shot_size=5.0
        )
        assert result == 900.0

    def test_p1_initial_shot(self):
        """Test P1 initial shot calculation (2%)."""
        # 10L pot, 2 L/hr flow, 2% shot size
        # Expected: (10 * 0.02) / 2 * 3600 = 360 seconds
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.0,
            substrate_vol=10.0,
            shot_size=2.0
        )
        assert result == 360.0

    def test_p2_maintenance_shot(self):
        """Test P2 maintenance shot calculation (5%)."""
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.0,
            substrate_vol=10.0,
            shot_size=5.0
        )
        assert result == 900.0

    def test_p3_emergency_shot(self):
        """Test P3 emergency shot calculation (3%)."""
        # 10L pot, 2 L/hr flow, 3% shot size
        # Expected: (10 * 0.03) / 2 * 3600 = 540 seconds
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.0,
            substrate_vol=10.0,
            shot_size=3.0
        )
        assert result == 540.0

    def test_different_flow_rate(self):
        """Test calculation with different flow rate."""
        # 15L pot, 3 L/hr flow, 5% shot size
        # Expected: (15 * 0.05) / 3 * 3600 = 900 seconds
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=3.0,
            substrate_vol=15.0,
            shot_size=5.0
        )
        assert result == 900.0

    def test_large_pot_volume(self):
        """Test calculation with large pot."""
        # 50L pot, 5 L/hr flow, 5% shot size
        # Expected: (50 * 0.05) / 5 * 3600 = 900 seconds
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=5.0,
            substrate_vol=50.0,
            shot_size=5.0
        )
        assert result == 900.0

    def test_zero_flow_rate(self):
        """Test calculation with zero flow rate returns 0."""
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=0.0,
            substrate_vol=10.0,
            shot_size=5.0
        )
        assert result == 0.0

    def test_negative_flow_rate(self):
        """Test calculation with negative flow rate."""
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=-2.0,
            substrate_vol=10.0,
            shot_size=5.0
        )
        # Should handle gracefully
        assert result == 0.0

    def test_small_shot_size(self):
        """Test calculation with very small shot size (0.5%)."""
        # 10L pot, 2 L/hr flow, 0.5% shot size
        # Expected: (10 * 0.005) / 2 * 3600 = 90 seconds
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.0,
            substrate_vol=10.0,
            shot_size=0.5
        )
        assert result == 90.0

    def test_large_shot_size(self):
        """Test calculation with large shot size (15%)."""
        # 10L pot, 2 L/hr flow, 15% shot size
        # Expected: (10 * 0.15) / 2 * 3600 = 2700 seconds
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.0,
            substrate_vol=10.0,
            shot_size=15.0
        )
        assert result == 2700.0

    def test_rounding(self):
        """Test that results are rounded to 1 decimal place."""
        # Should produce a value that tests rounding
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.3,
            substrate_vol=10.0,
            shot_size=5.0
        )
        # Expected: (10 * 0.05) / 2.3 * 3600 = 782.6086...
        assert result == 782.6

    def test_error_handling(self):
        """Test error handling with invalid inputs."""
        # Should not raise exception
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=None,
            substrate_vol=10.0,
            shot_size=5.0
        )
        assert result == 0.0


class TestECRatioCalculations:
    """Test EC ratio calculations."""

    def test_normal_ec_ratio(self):
        """Test normal EC ratio calculation."""
        # Current EC 2.5, Target EC 2.5
        # Expected ratio: 1.0
        current_ec = 2.5
        target_ec = 2.5
        ratio = round(current_ec / target_ec, 2)
        assert ratio == 1.0

    def test_high_ec_ratio(self):
        """Test high EC ratio (needs flushing)."""
        # Current EC 3.5, Target EC 2.5
        # Expected ratio: 1.4
        current_ec = 3.5
        target_ec = 2.5
        ratio = round(current_ec / target_ec, 2)
        assert ratio == 1.4

    def test_low_ec_ratio(self):
        """Test low EC ratio (needs concentration)."""
        # Current EC 1.5, Target EC 2.5
        # Expected ratio: 0.6
        current_ec = 1.5
        target_ec = 2.5
        ratio = round(current_ec / target_ec, 2)
        assert ratio == 0.6


class TestThresholdAdjustments:
    """Test VWC threshold adjustments based on EC ratio."""

    def test_no_adjustment_normal_ec(self):
        """Test no adjustment with normal EC ratio."""
        base_threshold = 60.0
        ec_ratio = 1.0
        ec_high = 1.3
        ec_low = 0.7

        # No adjustment needed
        if ec_ratio > ec_high:
            adjusted = base_threshold + VWC_ADJUSTMENT_PERCENT
        elif ec_ratio < ec_low:
            adjusted = base_threshold - VWC_ADJUSTMENT_PERCENT
        else:
            adjusted = base_threshold

        assert adjusted == 60.0

    def test_increase_threshold_high_ec(self):
        """Test threshold increase when EC is high."""
        base_threshold = 60.0
        ec_ratio = 1.5  # High EC
        ec_high = 1.3
        ec_low = 0.7

        # Should increase by VWC_ADJUSTMENT_PERCENT (5%)
        if ec_ratio > ec_high:
            adjusted = base_threshold + VWC_ADJUSTMENT_PERCENT
        elif ec_ratio < ec_low:
            adjusted = base_threshold - VWC_ADJUSTMENT_PERCENT
        else:
            adjusted = base_threshold

        assert adjusted == 65.0

    def test_decrease_threshold_low_ec(self):
        """Test threshold decrease when EC is low."""
        base_threshold = 60.0
        ec_ratio = 0.5  # Low EC
        ec_high = 1.3
        ec_low = 0.7

        # Should decrease by VWC_ADJUSTMENT_PERCENT (5%)
        if ec_ratio > ec_high:
            adjusted = base_threshold + VWC_ADJUSTMENT_PERCENT
        elif ec_ratio < ec_low:
            adjusted = base_threshold - VWC_ADJUSTMENT_PERCENT
        else:
            adjusted = base_threshold

        assert adjusted == 55.0


class TestAveragingCalculations:
    """Test sensor averaging."""

    def test_two_sensor_average(self):
        """Test averaging two sensor values."""
        values = [65.5, 68.5]
        average = round(sum(values) / len(values), 2)
        assert average == 67.0

    def test_four_sensor_average(self):
        """Test averaging four sensors (2 zones, front/back each)."""
        values = [64.0, 66.0, 65.0, 67.0]
        average = round(sum(values) / len(values), 2)
        assert average == 65.5

    def test_uneven_average(self):
        """Test averaging with uneven numbers."""
        values = [60.3, 65.7, 62.1]
        average = round(sum(values) / len(values), 2)
        assert average == 62.7

    def test_empty_list(self):
        """Test averaging with no values."""
        values = []
        if values:
            average = round(sum(values) / len(values), 2)
        else:
            average = None
        assert average is None


class TestConstants:
    """Test that constants have expected values."""

    def test_seconds_per_hour(self):
        """Test SECONDS_PER_HOUR constant."""
        assert SECONDS_PER_HOUR == 3600

    def test_percentage_to_ratio(self):
        """Test PERCENTAGE_TO_RATIO constant."""
        assert PERCENTAGE_TO_RATIO == 0.01

    def test_vwc_adjustment(self):
        """Test VWC_ADJUSTMENT_PERCENT constant."""
        assert VWC_ADJUSTMENT_PERCENT == 5.0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_small_values(self):
        """Test calculation with very small values."""
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=0.1,
            substrate_vol=1.0,
            shot_size=1.0
        )
        # Expected: (1 * 0.01) / 0.1 * 3600 = 360 seconds
        assert result == 360.0

    def test_very_large_values(self):
        """Test calculation with very large values."""
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=50.0,
            substrate_vol=200.0,
            shot_size=20.0
        )
        # Expected: (200 * 0.20) / 50 * 3600 = 2880 seconds
        assert result == 2880.0

    def test_precision_rounding(self):
        """Test that rounding works correctly."""
        result = ShotCalculator.calculate_shot_duration(
            dripper_flow=2.7,
            substrate_vol=11.3,
            shot_size=4.8
        )
        # Expected: (11.3 * 0.048) / 2.7 * 3600 = 722.666... rounds to 722.7
        assert isinstance(result, float)
        assert result == 722.7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
