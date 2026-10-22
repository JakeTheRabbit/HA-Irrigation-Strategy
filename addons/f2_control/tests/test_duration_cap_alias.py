"""Room cap aliases must match the exact entity used by manual settings."""

from datetime import datetime

import pytest

pytest_plugins = ("test_safety_regressions",)


def shot(rig, monkeypatch, prefix="", size=2):
    c, fake, _clock = rig
    room = c.rooms[0]
    room.prefix = prefix
    room.slug = prefix.rstrip("_") or "default"
    for key, value in {
        "plant_count": 42,
        "substrate_volume": 6.75,
        "drippers_per_plant": 1,
        "dripper_flow_rate": 4,
    }.items():
        fake.set_state(f"number.crop_steering_{prefix}zone_1_{key}", str(value))
    calls = []
    monkeypatch.setattr(c, "_execute_shot", lambda *args, **kwargs: calls.append(args))
    c._act_zone(
        room,
        1,
        None,
        None,
        (True, size, "cap compatibility"),
        None,
        True,
        datetime.now(),
    )
    return [args[2] for args in calls]


@pytest.mark.parametrize("prefix", ["", "veg_"])
def test_actual_act_zone_uses_same_room_legacy_cap(rig, monkeypatch, prefix):
    _c, fake, _clock = rig
    fake.set_state(f"number.crop_steering_{prefix}maximum_shot_duration", "60")
    assert shot(rig, monkeypatch, prefix) == [60]


@pytest.mark.parametrize("prefix", ["", "veg_"])
def test_canonical_room_cap_precedes_legacy(rig, monkeypatch, prefix):
    _c, fake, _clock = rig
    fake.set_state(f"number.crop_steering_{prefix}maximum_shot_duration", "60")
    fake.set_state(f"number.crop_steering_{prefix}max_shot_duration", "70")
    assert shot(rig, monkeypatch, prefix) == [70]


@pytest.mark.parametrize("suffix", ["max_shot_duration", "maximum_shot_duration"])
@pytest.mark.parametrize(
    "value", ["unknown", "unavailable", "", "bad", "NaN", "inf", "-1", "0", "4"]
)
def test_invalid_selected_cap_holds_shot_without_legacy_or_default_substitution(
    rig, monkeypatch, suffix, value
):
    _c, fake, _clock = rig
    fake.set_state("number.crop_steering_veg_maximum_shot_duration", "60")
    fake.set_state(f"number.crop_steering_veg_{suffix}", value)
    assert shot(rig, monkeypatch, "veg_") == []
    assert not any(data.get("entity_id") == "switch.p" for _, _, data in fake.calls)


def test_named_room_does_not_borrow_default_or_zone_caps(rig, monkeypatch):
    _c, fake, _clock = rig
    fake.set_state("number.crop_steering_max_shot_duration", "5")
    fake.set_state("number.crop_steering_maximum_shot_duration", "6")
    fake.set_state("number.crop_steering_veg_zone_1_max_shot_duration", "7")
    assert shot(rig, monkeypatch, "veg_", size=20) == [900]


def test_default_room_does_not_borrow_named_room_cap(rig, monkeypatch):
    _c, fake, _clock = rig
    fake.set_state("number.crop_steering_veg_maximum_shot_duration", "5")
    assert shot(rig, monkeypatch, size=20) == [900]


def test_existing_null_canonical_state_is_not_treated_as_missing(rig, monkeypatch):
    _c, fake, _clock = rig
    fake.states["number.crop_steering_veg_max_shot_duration"] = (
        None,
        {},
        "2026-09-08T04:00:00+00:00",
    )
    fake.set_state("number.crop_steering_veg_maximum_shot_duration", "60")
    assert shot(rig, monkeypatch, "veg_") == []


def blip(c, monkeypatch, controller, fake, status=None):
    """Every read of a room cap entity fails (timeout: status None, or an HA error status)."""

    def failed(entity, timeout=8):
        return status, controller.HAState()

    def get_status(entity, timeout=8):
        return (
            failed(entity)
            if "shot_duration" in entity
            else fake.ha_get_status(entity, timeout)
        )

    def get(entity, timeout=8):
        return (
            controller.HAState()
            if "shot_duration" in entity
            else fake.ha_get(entity, timeout)
        )

    monkeypatch.setattr(controller, "ha_get_status", get_status)
    monkeypatch.setattr(controller, "ha_get", get)


@pytest.mark.parametrize("status", [None, 500, 401])
def test_failed_cap_read_keeps_the_cap_read_earlier(rig, monkeypatch, status):
    import controller

    c, fake, _clock = rig
    fake.set_state("number.crop_steering_max_shot_duration", "120")
    assert shot(rig, monkeypatch, size=20) == [120]
    blip(c, monkeypatch, controller, fake, status)
    assert shot(rig, monkeypatch, size=20) == [120]


@pytest.mark.parametrize("status", [None, 500])
def test_failed_cap_read_with_nothing_read_earlier_holds(rig, monkeypatch, status):
    import controller

    c, fake, _clock = rig
    fake.set_state("number.crop_steering_max_shot_duration", "120")
    blip(c, monkeypatch, controller, fake, status)
    assert shot(rig, monkeypatch, size=20) == []
    assert any(
        d.get("notification_id") == "f2_duration_config_default"
        and "(CS-203)" in d.get("title", "")
        for _, _, d in fake.calls
    )
