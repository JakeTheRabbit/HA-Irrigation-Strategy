"""Upper limits that follow each zone's size (ZONE_BOUNDS in the one defaults table).

An edit above a limit is refused. A value a room already held above its limit is kept and used as
before, never moved, and named in one Repairs card; the limit applies to the next edit."""

from __future__ import annotations

import math

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .generated.defaults import ENTITY_DEFAULTS, ZONE_BOUNDS, ZONE_STARTS
from .health import _iid, _issue

ISSUE = "outside_zone_bounds"


def _positive(*values):
    try:
        numbers = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    return numbers if all(math.isfinite(n) and n > 0 for n in numbers) else None


def daily_volume_bound(plants, litres_per_plant):
    """Most water a zone may be given per grow-day (L), or None when its size can't be read."""
    numbers = _positive(plants, litres_per_plant)
    if numbers is None:
        return None
    rule = ZONE_BOUNDS["max_daily_volume"]
    return round(
        max(rule["floor"], numbers[0] * numbers[1] * rule["substrate_multiple"]), 1
    )


def starting_daily_volume(plants, litres_per_plant):
    """What a new zone's daily water limit starts at (L): its share of the zone's substrate, to the
    nearest litre, never less than the entity default (which is also what a zone of unknown size
    gets) and never more than the engine accepts. For the same plants and litres it is inside
    daily_volume_bound."""
    start = ENTITY_DEFAULTS["max_daily_volume"]
    numbers = _positive(plants, litres_per_plant)
    if numbers is None:
        return start
    rule = ZONE_STARTS["max_daily_volume"]
    share = numbers[0] * numbers[1] * rule["substrate_multiple"]
    return min(rule["ceiling"], max(start, float(math.floor(share + 0.5))))


def start_new_daily_limits(numbers) -> None:
    """Give each NEW zone's daily water limit its start, once every number of the room holds its
    value (restored, or from setup). The size is read from the same two numbers as the limit of the
    setting (CropSteeringNumber.zone_bound), so the start is inside that limit. A limit that
    restored its own value, and a zone that setup did not mark as new, are left as they are.
    """
    for number in numbers:
        zone = getattr(number, "_zone_num", None)
        if not getattr(number, "start_from_size", False) or number.was_restored:
            continue
        if number.hass is None:
            continue  # a number that a person disabled is not in Home Assistant
        number._attr_native_value = starting_daily_volume(
            number._sizing(zone, "plant_count"),
            number._sizing(zone, "substrate_volume"),
        )
        number.async_write_ha_state()


def shot_duration_bound(litres_per_plant, drippers_per_plant, dripper_lph):
    """Longest shot (s) for one zone, or None when its size or flow can't be read."""
    numbers = _positive(litres_per_plant, drippers_per_plant, dripper_lph)
    if numbers is None:
        return None
    litres, drippers, lph = numbers
    rule = ZONE_BOUNDS["max_shot_duration"]
    seconds = litres * rule["substrate_multiple"] * 3600 / (drippers * lph)
    return float(max(rule["floor"], math.floor(seconds)))


def check_held_values(hass: HomeAssistant, entry: ConfigEntry, numbers) -> None:
    """Publish each limit as the zone's size now gives it, and raise, or clear, the room's card
    naming each setting held above its limit."""
    outside = []
    for number in numbers:
        bound, value = number.zone_bound, number.native_value
        if bound is None:
            continue
        number.async_write_ha_state()
        if value is not None and float(value) > bound:
            outside.append(f"- `{number.entity_id}`: {value:g} (limit {bound:g})")
    _issue(
        hass,
        bool(outside),
        _iid(ISSUE, entry.data.get("room_slug", "default")),
        ir.IssueSeverity.WARNING,
        {"count": str(len(outside)), "settings": "\n".join(outside)},
    )
