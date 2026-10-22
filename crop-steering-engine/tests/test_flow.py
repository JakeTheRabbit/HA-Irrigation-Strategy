from crop_steering_engine.flow import HIGH, LOW, reconcile, to_litres


def test_half_the_water_is_low():
    assert reconcile(2.4, 1.2) == {"ratio": 0.5, "verdict": "low"}


def test_no_meter_is_unmetered():
    assert reconcile(2.4, None)["verdict"] == "unmetered"


def test_ratio_bounds_are_inclusive_ok():
    assert reconcile(1.0, 0.8)["verdict"] == reconcile(1.0, 1.2)["verdict"] == "ok"


def test_more_than_commanded_is_high():
    assert reconcile(1.0, 1.5) == {"ratio": 1.5, "verdict": "high"}


def test_nothing_commanded_has_no_ratio():
    assert reconcile(0, 1.0) == {"ratio": None, "verdict": "unmetered"}


def test_bounds_are_pinned():
    assert (LOW, HIGH) == (0.80, 1.20)


def test_unknown_unit_is_not_guessed():
    assert to_litres(5, "pulses") is None and to_litres(1, "m³") == 1000.0
    assert to_litres(5, None) is None


def test_litres_and_us_gallons():
    assert to_litres(2.5, "L") == to_litres(2.5, "l") == 2.5
    assert to_litres(1, "gal") == 3.785411784
