"""Batch-tank dosing: each room's dosing pumps, batch hardware and recipe, checked, and the one
request the dashboard leaves for the controller app. Pure (no Home Assistant import), so it is tested
directly; dosing_api.py stores it and serves the services. The contract is docs/DOSING.md.

The integration only ever stores this. The controller app does every action, and only on a request
younger than REQUEST_MAX_AGE_S seconds, so a request is "pending" only until the controller has
handled it or it is too old for the controller to act on.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

MAX_PUMPS = 8
MAX_MIX_VALVES = 4
MAX_CLOSE = 16
MAX_ML = 5000
REQUEST_MAX_AGE_S = 120
ACTIONS = ("dose", "batch", "stop")
# Every domain a dosing setup can use: what dosing_get offers to pick from.
CANDIDATE_DOMAINS = (
    "number",
    "input_number",
    "button",
    "input_button",
    "script",
    "binary_sensor",
    "sensor",
    "switch",
    "input_boolean",
    "input_datetime",
)
VOLUME = ("number", "input_number")
START = ("button", "input_button", "script")
DOSING = ("binary_sensor", "sensor")
POWER = ("switch",)
FLOW = ("number", "input_number", "sensor")
FULL = ("binary_sensor", "sensor")
ML_ENTITY = ("number", "input_number", "sensor")

_ID = re.compile(r"^[a-z0-9_]{1,24}$")
_OBJECT = re.compile(r"^[a-z0-9_]+$")


class DosingError(ValueError):
    """A dosing setup or request that cannot be accepted; the message is shown to the operator."""


def empty_batch() -> dict:
    return {
        "fill_valve": None,
        "full_entity": None,
        "full_state": "on",
        "fill_timeout_min": 20,
        "mix_pump": None,
        "mix_valves": [],
        "mix_power_sensor": None,
        "mix_min_w": 0,
        "premix_min": 2,
        "postmix_min": 5,
        "close_entities": [],
        "hold_entity": None,
        "filled_at_entity": None,
        "recipe": [],
    }


def empty() -> dict:
    return {
        "revision": 0,
        "pumps": [],
        "batch": empty_batch(),
        "request": None,
        "updated_at": None,
    }


def _choices(domains) -> str:
    return (
        domains[0]
        if len(domains) == 1
        else f"{', '.join(domains[:-1])} or {domains[-1]}"
    )


def _entity(value, domains, what, exists, optional=False):
    text = "" if value is None else str(value).strip()
    if not text:
        if optional:
            return None
        raise DosingError(f"{what} is required")
    domain, _, rest = text.partition(".")
    if domain not in domains or not _OBJECT.match(rest):
        raise DosingError(f"{what} must be a {_choices(domains)} entity, not {text}")
    if exists is not None and not exists(text):
        raise DosingError(f"{what}: {text} does not exist in Home Assistant")
    return text


def _entities(value, domains, what, most, exists):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > most:
        raise DosingError(f"{what}: send a list of at most {most}")
    out = [_entity(item, domains, what, exists) for item in value]
    if len(set(out)) != len(out):
        raise DosingError(f"{what}: an entity is listed twice")
    return out


def _number(value, low, high, what, default=None):
    if value is None:
        value = default
    if value is None or isinstance(value, bool):
        raise DosingError(f"{what} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DosingError(f"{what} must be a number") from None
    if not math.isfinite(number) or not low <= number <= high:
        raise DosingError(f"{what} must be between {low:g} and {high:g}")
    return int(number) if number.is_integer() else number


def _text(value, default, what):
    text = default if value in (None, "") else str(value).strip()
    if not 1 <= len(text) <= 40:
        raise DosingError(f"{what} must be 1 to 40 characters")
    return text


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "pump"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}_{n}", n + 1
    return slug


def _stock_tank(value, label, stock_tanks):
    """The id of the room's stock tank this pump doses from, or None (docs/DOSING.md, Stock tanks)."""
    if value in (None, ""):
        return None
    tank = str(value).strip()
    if stock_tanks is not None and tank not in stock_tanks:
        raise DosingError(f"{label}: {tank} is not one of this room's stock tanks")
    return tank


def _pump(raw, taken, exists, stock_tanks=None) -> dict:
    if not isinstance(raw, dict):
        raise DosingError("each pump must be an object")
    name = str(raw.get("name") or "").strip()
    if not 1 <= len(name) <= 40:
        raise DosingError("each pump needs a name of 1 to 40 characters")
    given = raw.get("id")
    pump_id = str(given).strip() if given not in (None, "") else _slug(name, taken)
    if not _ID.match(pump_id):
        raise DosingError(
            f"pump {name}: its id must be 1 to 24 characters of a-z, 0-9 and _"
        )
    if pump_id in taken:
        raise DosingError(f"two pumps have the id {pump_id}")
    label = f"pump {name}"
    restore = raw.get("restore_volume", True)
    if not isinstance(restore, bool):
        raise DosingError(f"{label}: restore volume must be true or false")
    return {
        "id": pump_id,
        "name": name,
        "volume_entity": _entity(
            raw.get("volume_entity"), VOLUME, f"{label}: volume entity", exists
        ),
        "start_entity": _entity(
            raw.get("start_entity"), START, f"{label}: start entity", exists
        ),
        "dosing_entity": _entity(
            raw.get("dosing_entity"), DOSING, f"{label}: dosing entity", exists
        ),
        "dosing_prefix": _text(
            raw.get("dosing_prefix"), "Dosing", f"{label}: dosing prefix"
        ),
        "power_entity": _entity(
            raw.get("power_entity"), POWER, f"{label}: power switch", exists
        ),
        "flow_entity": _entity(
            raw.get("flow_entity"), FLOW, f"{label}: flow entity", exists
        ),
        "max_ml": _number(raw.get("max_ml"), 1, MAX_ML, f"{label}: max mL"),
        "restore_volume": restore,
        "stock_tank": _stock_tank(raw.get("stock_tank"), label, stock_tanks),
    }


def _recipe(raw, pumps: dict, exists) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_PUMPS:
        raise DosingError(f"the recipe: send a list of at most {MAX_PUMPS} doses")
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise DosingError("each recipe dose must be an object")
        pump = pumps.get(str(item.get("pump") or ""))
        if pump is None:
            raise DosingError(
                f"the recipe doses pump {item.get('pump')}, which is not set up"
            )
        if pump["id"] in seen:
            raise DosingError(f"the recipe doses {pump['name']} twice")
        seen.add(pump["id"])
        label = f"the recipe's {pump['name']} dose"
        out.append(
            {
                "pump": pump["id"],
                "ml": _number(item.get("ml"), 0, pump["max_ml"], f"{label} (mL)", 0),
                "ml_entity": _entity(
                    item.get("ml_entity"),
                    ML_ENTITY,
                    f"{label}: mL entity",
                    exists,
                    optional=True,
                ),
            }
        )
    return out


def _batch(raw, pumps: dict, exists) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DosingError("the batch must be an object")
    fill_valve = _entity(
        raw.get("fill_valve"), ("switch",), "fill valve", exists, optional=True
    )
    full_entity = _entity(
        raw.get("full_entity"), FULL, "tank full entity", exists, optional=True
    )
    if fill_valve and not full_entity:
        raise DosingError("a fill valve needs the entity that says the tank is full")
    mix_power_sensor = _entity(
        raw.get("mix_power_sensor"),
        ("sensor",),
        "mix pump power sensor",
        exists,
        optional=True,
    )
    mix_min_w = _number(
        raw.get("mix_min_w"), 0, 100000, "mix pump minimum power (W)", 0
    )
    if mix_min_w > 0 and not mix_power_sensor:
        # Without it the controller could not check the power, and would mix unchecked.
        raise DosingError(
            "a mix pump minimum power needs the mix pump power sensor that reads it"
        )
    return {
        "fill_valve": fill_valve,
        "full_entity": full_entity,
        "full_state": _text(raw.get("full_state"), "on", "the full state"),
        "fill_timeout_min": _number(
            raw.get("fill_timeout_min"), 1, 60, "fill timeout (min)", 20
        ),
        "mix_pump": _entity(
            raw.get("mix_pump"), ("switch",), "mix pump", exists, optional=True
        ),
        "mix_valves": _entities(
            raw.get("mix_valves"), ("switch",), "mix valves", MAX_MIX_VALVES, exists
        ),
        "mix_power_sensor": mix_power_sensor,
        "mix_min_w": mix_min_w,
        "premix_min": _number(raw.get("premix_min"), 0, 30, "premix (min)", 2),
        "postmix_min": _number(raw.get("postmix_min"), 0, 60, "postmix (min)", 5),
        "close_entities": _entities(
            raw.get("close_entities"),
            ("switch",),
            "switches to close",
            MAX_CLOSE,
            exists,
        ),
        "hold_entity": _entity(
            raw.get("hold_entity"), ("input_boolean",), "hold", exists, optional=True
        ),
        "filled_at_entity": _entity(
            raw.get("filled_at_entity"),
            ("input_datetime",),
            "filled-at",
            exists,
            optional=True,
        ),
        "recipe": _recipe(raw.get("recipe"), pumps, exists),
    }


def clean(pumps, batch, exists=None, stock_tanks=None) -> tuple[list[dict], dict]:
    """The operator's pumps and batch -> what is stored (docs/DOSING.md, Validation).

    `exists(entity_id)` says whether Home Assistant knows an entity, and `stock_tanks` are the ids
    of the room's stock tanks a pump may be linked to. None skips that check: a stored setup read
    back at start-up, before every device has come back, is not thrown away. A pump keeps the id
    it is sent; one sent without an id gets one from its name.
    """
    if not isinstance(pumps, list) or len(pumps) > MAX_PUMPS:
        raise DosingError(f"send a list of at most {MAX_PUMPS} pumps")
    ids = {
        str(item.get("id")).strip()
        for item in pumps
        if isinstance(item, dict) and item.get("id") not in (None, "")
    }
    out = []
    for raw in pumps:
        # Every id sent counts as taken, so a new pump's generated id never steals one.
        own = str(raw.get("id")).strip() if isinstance(raw, dict) else None
        taken = {p["id"] for p in out} | (ids - {own})
        out.append(_pump(raw, taken, exists, stock_tanks))
    links = [pump["stock_tank"] for pump in out if pump["stock_tank"]]
    twice = next((tank for tank in links if links.count(tank) > 1), None)
    if twice:
        raise DosingError(f"stock tank {twice} is linked to two pumps")
    by_id = {pump["id"]: pump for pump in out}
    cleaned = _batch(batch, by_id, exists)
    hardware = {
        cleaned["fill_valve"],
        cleaned["mix_pump"],
        *cleaned["mix_valves"],
        *cleaned["close_entities"],
    } - {None}
    for pump in out:
        if pump["power_entity"] in hardware:
            raise DosingError(
                f"{pump['power_entity']} is pump {pump['name']}'s power switch and batch "
                "hardware: it cannot be both"
            )
    return out, cleaned


def check_request(config: dict, action, pump=None, ml=None) -> tuple:
    """A request's action, pump and mL, checked against the room's setup -> (pump, ml) to store.
    A stop and a batch carry neither."""
    if action not in ACTIONS:
        raise DosingError("the action must be dose, batch or stop")
    if action != "dose":
        return None, None
    found = next((p for p in config["pumps"] if p["id"] == pump), None)
    if found is None:
        raise DosingError(f"unknown pump: {pump}")
    try:
        amount = math.nan if isinstance(ml, bool) else float(ml)
    except (TypeError, ValueError):
        amount = math.nan
    if not (math.isfinite(amount) and 0 < amount <= found["max_ml"]):
        raise DosingError(
            f"a dose of {found['name']} must be more than 0 and at most "
            f"{found['max_ml']:g} mL"
        )
    return found["id"], int(amount) if amount.is_integer() else amount


def request_time(request) -> datetime | None:
    """When a stored request was made, as an aware time, or None when it has no usable time."""
    try:
        when = datetime.fromisoformat(str(request["at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    return when if when.tzinfo else None


def pending(request, handled, now: datetime) -> bool:
    """Whether the stored request still waits for the controller: it has not published the
    request's id as handled, and the request is young enough for the controller to act on.
    """
    if not isinstance(request, dict) or not request.get("id"):
        return False
    if request["id"] == handled:
        return False
    when = request_time(request)
    return when is not None and (now - when).total_seconds() <= REQUEST_MAX_AGE_S
