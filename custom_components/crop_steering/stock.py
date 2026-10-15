"""Stock tanks: the room's nutrient concentrates, drawn down by every batch tank it makes. Pure (no
Home Assistant import), so it is tested directly; stock_api.py stores it and counts the batches.

A batch is one new fill of the room's batch tank: a newer timestamp on the tank last-fill entity
mapped in Rooms & setup (`tank_last_fill_sensor`), or the operator recording one by hand. Each stock
tank then loses its dose per batch: a fixed amount, or what a dose entity reads at that moment (a
doser's dose-volume number), so the draw follows the doser's own setting.

A tank linked to a dosing pump is drawn by what that pump runs instead (docs/DOSING.md, Stock
tanks): the seconds its motor ran times its calibrated flow, whoever started it.

The first fill time the integration ever sees is only a starting point: counting it would draw the
stock down for a batch made before the tanks were set up.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, tzinfo

MAX_TANKS = 12
HISTORY = 30
DRAW_KEYS = (
    100  # the keys of the last draws counted (stock_draw), so none is counted twice
)
_ENTITY = re.compile(r"^(number|input_number|sensor)\.[a-z0-9_]+$")
_DEAD = ("unknown", "unavailable", "none", "")


class StockError(ValueError):
    """A stock tank change that cannot be saved; the message is shown to the operator."""


def empty() -> dict:
    return {
        "revision": 0,
        "tanks": [],
        "last_batch": None,
        "history": [],
        "draw_keys": [],
    }


def _number(raw: dict, key: str, low: float, high: float, default=None) -> float:
    value = raw.get(key, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise StockError(f"{key.replace('_', ' ')} must be a number") from None
    if not low <= value <= high:
        raise StockError(
            f"{key.replace('_', ' ')} must be between {low:g} and {high:g}"
        )
    return value


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "stock"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}_{n}", n + 1
    return slug


def clean_tanks(raw: list, current: list[dict], now: str) -> list[dict]:
    """The operator's full list of tanks, checked -> the list to store.

    A tank keeps its id (and so its sensor) across edits; a new one gets an id from its name. The
    level a new tank starts at is its capacity unless given; an edit that lowers the capacity
    below the level brings the level down with it.
    """
    if not isinstance(raw, list) or len(raw) > MAX_TANKS:
        raise StockError(f"send a list of at most {MAX_TANKS} stock tanks")
    known = {tank["id"]: tank for tank in current}
    kept = {
        str(item.get("id"))
        for item in raw
        if isinstance(item, dict) and item.get("id") in known
    }
    out, names = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise StockError("each stock tank must be an object")
        name = str(item.get("name") or "").strip()
        if not 1 <= len(name) <= 40:
            raise StockError("each stock tank needs a name of 1 to 40 characters")
        if name.lower() in names:
            raise StockError(f"two stock tanks are called {name}")
        names.add(name.lower())
        old = known.get(item.get("id"))
        # A field left out of an edit keeps its stored value.
        capacity = _number(
            item, "capacity_l", 0.1, 10000, old["capacity_l"] if old else None
        )
        level = _number(item, "level_l", 0, 10000, old["level_l"] if old else capacity)
        entity = (
            item["dose_entity"]
            if "dose_entity" in item
            else (old or {}).get("dose_entity")
        )
        dose_entity = str(entity or "").strip()
        if dose_entity and not _ENTITY.match(dose_entity):
            raise StockError(
                f"{dose_entity} is not a number, input_number or sensor entity"
            )
        tank_id = old["id"] if old else _slug(name, kept | {t["id"] for t in out})
        out.append(
            {
                "id": tank_id,
                "name": name,
                "capacity_l": capacity,
                "level_l": min(level, capacity),
                "dose_ml": _number(
                    item, "dose_ml", 0, 100000, old["dose_ml"] if old else 0
                ),
                "dose_entity": dose_entity or None,
                "low_l": min(
                    _number(
                        item, "low_l", 0, 10000, old["low_l"] if old else capacity * 0.2
                    ),
                    capacity,
                ),
                "refilled_at": old.get("refilled_at") if old else None,
                "updated_at": (
                    now if old is None or _changed(old, item) else old["updated_at"]
                ),
            }
        )
    return out


def _changed(old: dict, item: dict) -> bool:
    return any(
        item.get(key) is not None and item.get(key) != old.get(key)
        for key in ("name", "capacity_l", "level_l", "dose_ml", "dose_entity", "low_l")
    )


def dose_ml(tank: dict, reading: str | None) -> float:
    """What one batch takes from this tank, in mL: the dose entity's reading when it has a usable
    one, otherwise the fixed amount."""
    if (
        tank.get("dose_entity")
        and reading is not None
        and str(reading).strip().lower() not in _DEAD
    ):
        try:
            value = float(reading)
        except (TypeError, ValueError):
            value = -1
        if 0 <= value <= 100000:
            return value
    return float(tank.get("dose_ml") or 0)


def draw(data: dict, doses: dict[str, float], at: str, source: str) -> dict:
    """One batch: every tank in `doses` loses its dose (never below empty), and the batch is logged.
    A tank left out is not drawn: one linked to a dosing pump is drawn by its pump's runs instead.
    A batch that drew no tank at all is not logged: it would only push real draws out of the
    history.
    """
    taken = {}
    for tank in data["tanks"]:
        if tank["id"] not in doses:
            continue
        ml = max(0.0, float(doses[tank["id"]]))
        before = tank["level_l"]
        tank["level_l"] = round(max(0.0, before - ml / 1000), 4)
        taken[tank["id"]] = round((before - tank["level_l"]) * 1000, 1)
    if taken:
        data["history"] = [
            {"at": at, "source": source, "draw_ml": taken},
            *data["history"],
        ][:HISTORY]
    return data


def draw_dosed(data: dict, draws, at: str, source: str, key: str, note=None, leave=()):
    """What was dosed out of stock tanks linked to pumps (docs/DOSING.md, Stock tanks): each tank
    named in `draws` loses its mL, never below empty, and the draw is logged with its key ->
    (counted, skipped ids). A key already counted changes nothing (the controller sends a draw again
    until it hears back), an id that is not one of the room's tanks is skipped, and a tank in
    `leave` is not drawn (its pump's own runs draw it).
    """
    if not isinstance(draws, dict):
        raise StockError("draws must map stock tank ids to mL")
    amounts = {}
    for tank_id, ml in draws.items():
        try:
            value = math.nan if isinstance(ml, bool) else float(ml)
        except (TypeError, ValueError):
            value = math.nan
        if not math.isfinite(value) or value < 0:
            raise StockError(
                f"the draw from {tank_id} must be a number of mL, 0 or more"
            )
        amounts[str(tank_id)] = value
    keys = [k for k in data.get("draw_keys") or [] if isinstance(k, str)]
    if key in keys:
        return False, []
    known = {tank["id"]: tank for tank in data["tanks"]}
    skipped = sorted(tank_id for tank_id in amounts if tank_id not in known)
    taken = {}
    for tank_id, ml in amounts.items():
        tank = known.get(tank_id)
        if tank is None or tank_id in leave:
            continue
        before = tank["level_l"]
        tank["level_l"] = round(max(0.0, before - ml / 1000), 4)
        taken[tank_id] = round((before - tank["level_l"]) * 1000, 1)
    if not taken:
        return False, skipped
    entry = {"at": at, "source": source, "draw_ml": taken, "key": key}
    if note:
        entry["note"] = str(note)[:200]
    data["history"] = [entry, *data["history"]][:HISTORY]
    data["draw_keys"] = [*keys, key][-DRAW_KEYS:]
    return True, skipped


def running(pump: dict, read) -> list[str]:
    """Which of a dosing pump's entities say its motor runs now (docs/DOSING.md, Stock tanks): its
    power switch reading on (the motor's own switch on the firmwares Crop Steering drives), and its
    dosing entity reading dosing (a binary sensor on; a sensor whose state starts with the pump's
    dosing prefix). Empty while it does not run: unavailable, unknown or missing never says it
    does. `read(entity_id)` is that entity's state, or None.
    """
    found = []
    power, dosing = pump.get("power_entity"), pump.get("dosing_entity")
    if power and str(read(power) or "").strip().lower() == "on":
        found.append(power)
    if dosing:
        state = str(read(dosing) or "")
        if dosing.startswith("binary_sensor."):
            on = state.strip().lower() == "on"
        else:
            on = state.startswith(pump.get("dosing_prefix") or "Dosing")
        if on:
            found.append(dosing)
    return found


def pumped_ml(seconds: float, flow) -> float | None:
    """What a pump moved running `seconds` at its calibrated flow (its flow entity's reading, in
    mL/s), or None when that reads nothing usable."""
    try:
        rate = math.nan if isinstance(flow, bool) else float(flow)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rate) or rate <= 0:
        return None
    return max(0.0, seconds) * rate


def refill(data: dict, tank_id: str, level_l: float | None, now: str) -> dict:
    """The operator refilled a tank (to capacity) or read its level off the side (`level_l`)."""
    tank = next((t for t in data["tanks"] if t["id"] == tank_id), None)
    if tank is None:
        raise StockError(f"there is no stock tank {tank_id}")
    if level_l is None:
        tank["level_l"], tank["refilled_at"] = tank["capacity_l"], now
    else:
        tank["level_l"] = _number(
            {"level_l": level_l}, "level_l", 0, tank["capacity_l"]
        )
    tank["updated_at"] = now
    return data


def batches_left(tank: dict, dose: float) -> int | None:
    """Whole batches the tank still covers at `dose` mL each; None when it doses nothing."""
    # Rounded first: 0.29 L is 289.99999999999997 mL in floating point, one batch short.
    return int(round(tank["level_l"] * 1000, 6) // dose) if dose > 0 else None


def low_tanks(data: dict) -> list[dict]:
    return [t for t in data["tanks"] if t["level_l"] <= t["low_l"]]


def parse_fill(state: str | None, zone: tzinfo) -> datetime | None:
    """A last-fill entity's state as an aware time: a timestamp sensor's ISO string, or a date-and-
    time helper's local "YYYY-MM-DD HH:MM:SS" read in the Home Assistant time zone."""
    if state is None or str(state).strip().lower() in _DEAD:
        return None
    try:
        when = datetime.fromisoformat(str(state).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=zone)


def new_batch(data: dict, fill: datetime | None) -> bool:
    """Whether `fill` is a batch not yet counted. The first fill time ever seen, and one no newer
    than the last counted, only move the starting point (see the module note)."""
    if fill is None:
        return False
    last = data.get("last_batch")
    counted = last is not None and fill > datetime.fromisoformat(last)
    if last is None or fill > datetime.fromisoformat(last):
        data["last_batch"] = fill.isoformat()
    return counted
