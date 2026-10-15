"""Stock tanks per room, stored and served; see stock.py for the rules.

Response-only services addressed by canonical room id, like the run and strategy services. Reading
is open to any signed-in user; changing a tank, recording a refill or a batch needs an
administrator. A batch is counted when the room's mapped tank last-fill entity moves to a newer
time, or when the operator records one; a room whose tanks run low gets a Repairs card. A tank
linked to a dosing pump is drawn by what that pump runs instead, followed here on the pump's own
entities whoever starts it (docs/DOSING.md, Stock tanks): neither way of counting a batch draws it,
and nor does the controller's report of a dose (stock_draw).
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import logging

from . import stock
from .admin import async_require_admin
from .const import DOMAIN, REPAIRS_DOCS_URL
from .room import room_prefix

_LOGGER = logging.getLogger(__name__)

SERVICES = (
    "stock_get",
    "stock_save",
    "stock_refill",
    "stock_record_batch",
    "stock_draw",
)
SIGNAL = f"{DOMAIN}_stock_changed"
ISSUE = "stock_low"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _utcnow().isoformat()


def _valid(value) -> dict:
    """A stored document, checked as strictly as an edit; anything else is refused."""
    if not isinstance(value, dict) or type(value.get("revision")) is not int:
        raise ValueError("Invalid stored revision")
    data = stock.empty()
    data["revision"] = value["revision"]
    data["tanks"] = stock.clean_tanks(value.get("tanks", []), [], _now())
    # clean_tanks gives new ids and times; the stored ones are the truth.
    for tank, raw in zip(data["tanks"], value.get("tanks", [])):
        for key in ("id", "refilled_at", "updated_at"):
            tank[key] = raw.get(key, tank[key])
    last = value.get("last_batch")
    data["last_batch"] = datetime.fromisoformat(last).isoformat() if last else None
    history = value.get("history", [])
    data["history"] = history[: stock.HISTORY] if isinstance(history, list) else []
    keys = value.get("draw_keys", [])  # a document from before dosing has none
    data["draw_keys"] = (
        [k for k in keys if isinstance(k, str)][-stock.DRAW_KEYS :]
        if isinstance(keys, list)
        else []
    )
    return data


class StockStore:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry = hass, entry
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self.slug = (getattr(entry, "data", None) or {}).get("room_slug", "default")
        self.issue_id = (
            ISSUE if self.slug in ("", "default") else f"{ISSUE}_{self.slug}"
        )
        self._store = store
        self._lock = asyncio.Lock()
        self.data = stock.empty()
        self.error = None
        self._pumps = {}  # pump id -> its setup, for each pump linked to a stock tank
        self._runs = {}  # pump id -> {"since", "flow"} while that pump is seen running
        self._watching = ()  # the pump entities followed
        self._unwatch = None

    @property
    def fill_entity(self) -> str | None:
        """The room's tank last-fill entity from Rooms & setup; None when unmapped."""
        config = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        hardware = config.get("hardware", {}) if isinstance(config, dict) else {}
        return hardware.get("tank_last_fill_sensor") or None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(
                    self.hass, 1, f"{DOMAIN}.stock.{self.entry.entry_id}"
                )
            value = await self._store.async_load()
            if value is not None:
                self.data = _valid(value)
        except Exception as error:
            self.error = (
                "Stored stock tanks could not be loaded; they have not been overwritten: "
                f"{error}"
            )

    def start(self):
        """Count batches from the fill entity, draw each tank linked to a dosing pump by what that
        pump runs, and raise the low-stock card. Returns the unsubscribe for all of it, or None
        when the stored tanks could not be loaded."""
        self._alert()
        if self.error:
            return None
        from homeassistant.core import callback
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from homeassistant.helpers.event import async_track_state_change_event

        from .dosing_api import SIGNAL as DOSING_SIGNAL

        @callback
        def rewatch(*_):
            self._watch()

        # Which pumps are linked is the room's dosing setup: followed again whenever it is saved.
        stops = [
            async_dispatcher_connect(
                self.hass, f"{DOSING_SIGNAL}_{self.entry.entry_id}", rewatch
            )
        ]
        entity = self.fill_entity
        if entity:
            # The fill time at start-up is a starting point, not a batch (stock.new_batch).
            current = self.hass.states.get(entity)
            self.hass.async_create_task(self._fill(current.state if current else None))

            @callback
            def changed(event):
                state = event.data.get("new_state")
                self.hass.async_create_task(self._fill(state.state if state else None))

            stops.append(async_track_state_change_event(self.hass, [entity], changed))
        self._watch()

        def stop():
            for unsubscribe in stops:
                unsubscribe()
            if self._unwatch is not None:
                self._unwatch()
                self._unwatch = None

        return stop

    def _dosing_pumps(self) -> list[dict]:
        """The room's dosing pumps that are linked to a stock tank, from its dosing setup."""
        dosing = (
            self.hass.data.get(DOMAIN, {}).get("_dosing", {}).get(self.entry.entry_id)
        )
        if dosing is None or dosing.error:
            return []
        return [pump for pump in dosing.data.get("pumps", []) if pump.get("stock_tank")]

    def linked(self) -> dict[str, str]:
        """Stock tank id -> the dosing pump it is linked to, from the room's dosing setup."""
        return {pump["stock_tank"]: pump["id"] for pump in self._dosing_pumps()}

    def _read(self, entity):
        state = self.hass.states.get(entity) if entity else None
        return state.state if state is not None else None

    def _watch(self):
        """Follow the pumps linked to stock tanks (docs/DOSING.md, Stock tanks): their power and
        dosing entities, as the dosing setup names them. A pump already running when it is first
        followed (a reload in the middle of a dose) has run since its entity last changed. A pump
        no longer linked is no longer followed, and a run it had going is not drawn."""
        from homeassistant.core import callback
        from homeassistant.helpers.event import async_track_state_change_event

        self._pumps = {pump["id"]: pump for pump in self._dosing_pumps()}
        self._runs = {
            pump: run for pump, run in self._runs.items() if pump in self._pumps
        }
        entities = tuple(
            sorted(
                {
                    entity
                    for pump in self._pumps.values()
                    for entity in (pump.get("power_entity"), pump.get("dosing_entity"))
                    if entity
                }
            )
        )
        if entities != self._watching:
            if self._unwatch is not None:
                self._unwatch()
            self._watching, self._unwatch = entities, None
            if entities:

                @callback
                def changed(event):
                    self._changed(event.data.get("new_state"))

                self._unwatch = async_track_state_change_event(
                    self.hass, list(entities), changed
                )
        for pump_id, pump in self._pumps.items():
            on = stock.running(pump, self._read)
            if on and pump_id not in self._runs:
                changed_at = [
                    getattr(self.hass.states.get(entity), "last_changed", None)
                    for entity in on
                ]
                self._runs[pump_id] = {
                    "since": min([t for t in changed_at if t] or [_utcnow()]),
                    "flow": self._read(pump.get("flow_entity")),
                }

    def _changed(self, new_state):
        """A followed entity changed: a linked pump that now runs begins a run, and one that no
        longer does (stopped, unavailable or gone) ends its run, at the moment the entity changed;
        what it ran is drawn from its stock tank."""
        at = getattr(new_state, "last_changed", None) or _utcnow()
        for pump_id, pump in self._pumps.items():
            on = bool(stock.running(pump, self._read))
            run = self._runs.get(pump_id)
            if on and run is None:
                self._runs[pump_id] = {
                    "since": at,
                    "flow": self._read(pump.get("flow_entity")),
                }
            elif run is not None and not on:
                del self._runs[pump_id]
                self.hass.async_create_task(self._draw_run(pump, run, at))

    async def _draw_run(self, pump, run, end):
        """A linked pump stopped: the seconds it ran times its calibrated flow (read as it started,
        or as it stopped when it could not be read then) come off its stock tank, never below
        empty, logged as "pump" under a key of the pump and the moment it started, so the same
        run is never drawn twice."""
        seconds = (end - run["since"]).total_seconds()
        flow = run["flow"]
        if stock.pumped_ml(seconds, flow) is None:
            flow = self._read(pump.get("flow_entity"))
        ml = stock.pumped_ml(seconds, flow)
        tank = pump["stock_tank"]
        if ml is None:
            _LOGGER.warning(
                "Stock tanks for %s: %s ran %.1f s, but its flow (%s) reads nothing usable, "
                "so nothing was drawn from stock tank %s",
                self.room_id,
                pump.get("name"),
                seconds,
                pump.get("flow_entity"),
                tank,
            )
            return
        ml = round(ml, 1)
        if ml <= 0:
            return
        async with self._lock:
            if self.error:
                return
            draft = deepcopy(self.data)
            counted, _ = stock.draw_dosed(
                draft,
                {tank: ml},
                end.isoformat(),
                "pump",
                f"pump:{pump['id']}:{run['since'].isoformat()}",
                f"{pump.get('name')} ran {seconds:.1f} s at {float(flow):g} mL/s",
            )
            if counted:
                await self._commit(draft)
                _LOGGER.info(
                    "Stock tanks for %s: %s ran %.1f s, %g mL drawn from %s",
                    self.room_id,
                    pump.get("name"),
                    seconds,
                    ml,
                    tank,
                )

    def doses(self) -> dict[str, float]:
        """What one batch takes from each tank right now, in mL."""
        doses = {}
        for tank in self.data["tanks"]:
            state = (
                self.hass.states.get(tank["dose_entity"])
                if tank["dose_entity"]
                else None
            )
            doses[tank["id"]] = stock.dose_ml(tank, state.state if state else None)
        return doses

    async def _fill(self, state):
        from homeassistant.util import dt as dt_util

        # get_default_time_zone arrived in Home Assistant 2024.6; older releases hold the global.
        zone = (
            dt_util.get_default_time_zone()
            if hasattr(dt_util, "get_default_time_zone")
            else dt_util.DEFAULT_TIME_ZONE
        )
        async with self._lock:
            if self.error:
                return
            fill = stock.parse_fill(state, zone)
            draft = deepcopy(self.data)
            counted = stock.new_batch(draft, fill)
            if counted and draft["tanks"]:
                # A tank linked to a dosing pump is drawn by the pump's doses, never here as well.
                linked = self.linked()
                doses = {t: ml for t, ml in self.doses().items() if t not in linked}
                stock.draw(draft, doses, fill.isoformat(), "fill")
                _LOGGER.info(
                    "Stock tanks for %s: batch at %s counted", self.room_id, fill
                )
            if counted or draft["last_batch"] != self.data["last_batch"]:
                await self._commit(draft)

    def response(self):
        doses = self.doses()
        return {
            "schema_version": 1,
            "room_id": self.room_id,
            **deepcopy(self.data),
            "fill_entity": self.fill_entity,
            "doses": doses,
            "low": [tank["id"] for tank in stock.low_tanks(self.data)],
            "max_tanks": stock.MAX_TANKS,
            "error": self.error,
        }

    async def mutate(self, action, data):
        async with self._lock:
            if self.error:
                raise ValueError(self.error)
            if data.get("expected_revision") != self.data["revision"]:
                raise ValueError("Stock tanks changed elsewhere. Reload before saving.")
            now = _now()
            draft = deepcopy(self.data)
            skipped = None
            if action == "stock_save":
                draft["tanks"] = stock.clean_tanks(
                    data.get("tanks"), draft["tanks"], now
                )
            elif action == "stock_refill":
                stock.refill(draft, data.get("id"), data.get("level_l"), now)
            elif action == "stock_record_batch":
                # A tank linked to a dosing pump is drawn by the pump's doses, as for a fill: a batch
                # the controller made and someone also records by hand never counts twice on it.
                linked, doses = self.linked(), self.doses()
                skipped = sorted(tank for tank in doses if tank in linked)
                doses = {tank: ml for tank, ml in doses.items() if tank not in linked}
                stock.draw(draft, doses, now, "manual")
            else:
                raise ValueError("Unsupported stock operation")
            await self._commit(draft)
            response = self.response()
            if skipped is not None:  # the linked tanks this batch did not draw
                response["skipped"] = skipped
            return response

    async def draw(self, data):
        """stock_draw: what the controller dosed out of linked tanks, counted once per key. A tank
        still linked to a pump is left as it is: what that pump runs draws it (_watch), whoever
        starts the dose, so the controller's report of the same dose never counts it twice. No
        expected revision: the controller cannot know it, and the key makes a repeat harmless.
        """
        async with self._lock:
            if self.error:
                raise ValueError(self.error)
            key = data.get("key")
            duplicate = key in self.data["draw_keys"]
            linked = self.linked()
            draft = deepcopy(self.data)
            counted, skipped = stock.draw_dosed(
                draft,
                data.get("draws"),
                _now(),
                data.get("source"),
                key,
                data.get("note"),
                linked,
            )
            if counted:
                await self._commit(draft)
            return {
                **self.response(),
                "counted": counted,
                "duplicate": duplicate,
                "skipped": skipped,
                # Its own tanks it left to their pumps' runs.
                "linked": sorted(
                    tank
                    for tank in data.get("draws")
                    if tank in linked and tank not in skipped
                ),
            }

    async def _commit(self, draft):
        """Store the next revision; only a saved change becomes the room's tanks."""
        draft["revision"] = self.data["revision"] + 1
        await self._store.async_save(draft)
        self.data = draft
        self._alert()
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")

    def _alert(self):
        """One Repairs card per room while any tank is at or below its low mark."""
        from homeassistant.helpers import issue_registry as ir

        low = stock.low_tanks(self.data)
        if not low:
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
            return
        doses = self.doses()
        lines = []
        for tank in low:
            left = stock.batches_left(tank, doses.get(tank["id"], 0))
            lines.append(
                f"- {tank['name']}: {tank['level_l']:g} L of {tank['capacity_l']:g} L"
                + (
                    ""
                    if left is None
                    else f", about {left} batch{'es' if left != 1 else ''} left"
                )
            )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE,
            translation_placeholders={
                "count": str(len(low)),
                "tanks": "\n".join(lines),
            },
            learn_more_url=REPAIRS_DOCS_URL,
        )


def resolve_stock(hass, room_id):
    if not isinstance(room_id, str) or not room_id.startswith("room:"):
        raise ValueError("A canonical room_id is required")
    matches = [
        manager
        for manager in hass.data.get(DOMAIN, {}).get("_stock", {}).values()
        if manager.room_id == room_id
    ]
    if len(matches) != 1:
        raise ValueError("Stock tank room is unknown or ambiguous")
    return matches[0]


async def async_setup_stock(hass, entry):
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = StockStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_stock", {})[entry.entry_id] = manager
    unsubscribe = manager.start()
    if unsubscribe:
        entry.async_on_unload(unsubscribe)

    async def handle(call):
        if call.service != "stock_get":
            await async_require_admin(hass, call, f"{DOMAIN}.{call.service}")
        try:
            target = resolve_stock(hass, call.data["room_id"])
            if call.service == "stock_get":
                return target.response()
            if call.service == "stock_draw":
                return await target.draw(call.data)
            return await target.mutate(call.service, call.data)
        except (ValueError, KeyError, OSError) as error:
            raise HomeAssistantError(str(error)) from error

    for service in SERVICES:
        schema = {vol.Required("room_id"): str}
        if service not in ("stock_get", "stock_draw"):
            schema[vol.Required("expected_revision")] = vol.All(int, vol.Range(min=0))
        if service == "stock_draw":
            schema[vol.Required("key")] = str
            schema[vol.Required("draws")] = dict
            schema[vol.Required("source")] = vol.In(("dose", "batch"))
            schema[vol.Optional("note")] = str
        elif service == "stock_save":
            schema[vol.Required("tanks")] = vol.All(
                list, vol.Length(max=stock.MAX_TANKS)
            )
        elif service == "stock_refill":
            schema[vol.Required("id")] = str
            # Left out: refilled to capacity. Given: the level read off the tank.
            schema[vol.Optional("level_l")] = vol.All(
                vol.Coerce(float), vol.Range(min=0, max=10000)
            )
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schema),
            # The controller app calls stock_draw over REST without asking for the answer.
            supports_response=(
                SupportsResponse.OPTIONAL
                if service == "stock_draw"
                else SupportsResponse.ONLY
            ),
        )


async def async_unload_stock(hass, entry):
    from homeassistant.helpers import issue_registry as ir

    managers = hass.data.get(DOMAIN, {}).get("_stock", {})
    manager = managers.pop(entry.entry_id, None)
    if manager is not None:
        ir.async_delete_issue(hass, DOMAIN, manager.issue_id)
    if not managers:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
