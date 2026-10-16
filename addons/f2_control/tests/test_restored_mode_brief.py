"""The prompt distinguishes opt-in modes, defaults and estimated evidence as packs are integrated."""
from dataclasses import field, make_dataclass
from types import SimpleNamespace

import controller
from crop_steering_engine import core
from brain import controller_brief as cb


def supported():
    params = make_dataclass("RestoredParams", [(key, object, field(default=None)) for key in (
        "p0_min_wait_min", "p0_stall_exit", "p2_mode", "p2_end_h_before_off", "ec_flush_target", "p2_dilute_ratio")])
    engine = SimpleNamespace(ZoneParams=params, P0_STALL_AFTER_MIN=30, P0_STALL_RATE_FLOOR=0.1,
                             EC_FLUSH_FEED_MARGIN=0.2, P2_DILUTE_RATIO=1.2,
                             _PARAM_BOUNDS={"p1_max_extra_shots": (1, 30)})
    hooks = SimpleNamespace(**{key: object() for key in (
        "_rescue_past_dead_probe", "_waste_rule", "_watch_rescues", "_watch_tank_estimate", "_watch_runoff", "_step_limit_all")})
    return engine, SimpleNamespace(Controller=hooks)


def test_old_runtime_does_not_advertise_unimplemented_modes():
    old = SimpleNamespace(ZoneParams=make_dataclass("OldParams", []))
    assert cb.restored_modes(old, SimpleNamespace(Controller=object)) == []


def test_partial_install_only_describes_capabilities_it_has():
    engine, shell = supported()
    text = "\n".join(cb.restored_modes(engine, SimpleNamespace(Controller=object)))
    assert "Timed with guards" in text and "Waste valve rule" not in text
    old = SimpleNamespace(ZoneParams=make_dataclass("OldParams", []))
    text = "\n".join(cb.restored_modes(old, shell))
    assert "Waste valve rule" in text and "Timed with guards" not in text


def test_optional_rule_summary_preserves_the_safety_distinctions():
    text = "\n".join(cb.restored_modes(*supported()))
    for fact in (
        "default 0/off", "default off", "low-moisture bypass", "AI dawn advance",
        "suspect/flat/bypassed probe", "Timed with guards", "budgeted p2_topup, not a daily-cap exemption",
        "replaces predictive P3", "feed EC + 0.2 mS/cm", "settling/minimum interval",
        "only p3_emergency and watchdog", "out-of-band reading still holds",
        "never skips the kill switch", "before the pump primes", "unreadable or invalid policy holds",
        "never opens it", "Low-estimate alerts never drive the reservoir hold",
        "not a measured zone catch", "not measured transpiration", "unknown, not zero",
        "Only ai mode", "grants no authority to act",
        "Maximum extra ramp shots accepts 1-30", "Auto setpoints and AI",
        "does not limit shot-size writes or move the rescue floor",
    ):
        assert fact in text, fact


def test_generated_copy_stays_in_sync_and_supported_modes_are_present_after_integration():
    actual = "\n".join(cb.restored_modes(core, controller))
    generated = cb.render(cb.load_codes())
    assert cb.read() == generated
    if actual:
        assert actual in generated
    if "p2_mode" in core.ZoneParams.__dataclass_fields__:
        assert "Timed with guards" in generated
    if hasattr(controller.Controller, "_waste_rule"):
        assert "unreadable or invalid policy holds" in generated
    if hasattr(controller.Controller, "_watch_runoff"):
        assert "not a measured zone catch" in generated
