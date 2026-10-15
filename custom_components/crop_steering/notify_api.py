"""Who gets which alerts, for the whole site (docs/NOTIFICATIONS.md).

One store for the site (`crop_steering.notify`), not one per room: it is set up with the first room that loads
and kept while any room is loaded. The page reads and saves it through notify_get and notify_save and sends a
test push with notify_test. The controller app hands each push to notify, which sends it to every phone whose
row ticks one of its kinds (notify_catalog.py) and covers its room; sensor.crop_steering_notify_config (state
the revision, `recipients` how many rows) tells the controller whether anyone is set up at all, and with nobody
it pushes to its own notify_service option as it always did. The integration's own Repairs cards go out the
same way when one is raised.

Nothing here is needed for watering: a store that can't be read, a phone that fails, or no store at all only
changes who gets a push.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import logging
import re
import time

from . import notify_catalog
from .admin import async_require_admin
from .const import DOMAIN
from .room import room_prefix
from .setup_panel import PANEL

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}.notify"
SERVICES = ("notify_get", "notify_save", "notify_test", "notify")
SENSOR = f"sensor.{DOMAIN}_notify_config"
IDLE_HOURS = 3
IDLE_RANGE = (1, 12)
MAX_RECIPIENTS = 20
# One phone's push. The controller app waits 12 s for the whole call, and the phones are sent to at once.
SEND_TIMEOUT_S = 8
# What a push for an emergency adds, for a row that asks for high priority: Android's keys, then iOS's (each
# app ignores the other's). Sent to mobile_app services only, as is every push's tag.
URGENT = {
    "priority": "high",
    "channel": "Crop Steering urgent",
    "push": {"interruption-level": "time-sensitive"},
}
# Tapping a push opens the Crop Steering panel: iOS reads `url`, Android `clickAction`.
LINK = {"url": f"/{PANEL}", "clickAction": f"/{PANEL}"}
ISSUE_EVENT = "repairs_issue_registry_updated"  # issue_registry.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED
# A Repairs card cleared and raised again within this long is not pushed again (a probe going on and off
# line), as the controller app repeats an alert at most every 30 minutes.
CARD_QUIET_S = 1800
SERVICE_ID = re.compile(r"notify\.[a-z0-9_]+")
# A room prefix: "" (the default room) or "<slug>_".
ROOM = re.compile(r"(?:[a-z0-9_]*_)?")
UNNAMED = ("default", "crop steering", "crop steering system")


class NotifyError(ValueError):
    """A save refused, with a message the page can show."""


def empty() -> dict:
    return {"revision": 0, "idle_hours": IDLE_HOURS, "recipients": []}


def _kinds(value, where) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(k, str) for k in value):
        raise NotifyError(f"{where}: kinds must be a list of kind ids")
    unknown = sorted(set(value) - set(notify_catalog.KIND_IDS))
    if unknown:
        raise NotifyError(f"{where}: unknown kind {', '.join(unknown)}")
    return [kind for kind in notify_catalog.KIND_IDS if kind in value]


def _rooms(value, where) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(room, str) and ROOM.fullmatch(room) for room in value
    ):
        raise NotifyError(
            f'{where}: rooms must be room prefixes ("" for the default room, or "f1_")'
        )
    return sorted(set(value))


def _flag(value, where) -> bool:
    if value is None:  # high priority for emergencies unless the row says otherwise
        return True
    if not isinstance(value, bool):
        raise NotifyError(f"{where}: urgent_high_priority must be true or false")
    return value


def clean_recipient(raw, index=1, phones=None) -> dict:
    """One row as it is stored, or NotifyError. `phones` (service -> a phone notify_get lists) names a row
    saved without a name, and says whose phone it is when the row does not."""
    where = f"phone {index}"
    if not isinstance(raw, dict):
        raise NotifyError(f"{where}: not a row")
    service = raw.get("service")
    service = service.strip() if isinstance(service, str) else ""
    if not SERVICE_ID.fullmatch(service):
        raise NotifyError(f"{where}: its service must be notify.<name>")
    phone = (phones or {}).get(service) or {}
    name = raw.get("name")
    name = (name.strip() if isinstance(name, str) else "") or phone.get("name")
    user_id = raw.get("user_id")
    if user_id is not None and not isinstance(user_id, str):
        raise NotifyError(f"{where}: user_id must be a Home Assistant user id")
    return {
        "service": service,
        "name": (name or service)[:40],
        "user_id": user_id or phone.get("user_id") or None,
        "kinds": _kinds(raw.get("kinds"), where),
        "rooms": _rooms(raw.get("rooms"), where),
        "urgent_high_priority": _flag(raw.get("urgent_high_priority"), where),
    }


def clean_recipients(value, phones=None) -> list[dict]:
    if not isinstance(value, list):
        raise NotifyError("recipients must be a list")
    if len(value) > MAX_RECIPIENTS:
        raise NotifyError(f"at most {MAX_RECIPIENTS} phones")
    rows = [clean_recipient(raw, index, phones) for index, raw in enumerate(value, 1)]
    services = [row["service"] for row in rows]
    for service in services:
        if services.count(service) > 1:
            raise NotifyError(f"{service} is listed twice")
    return rows


def clean_idle(value):
    """The watering-stopped threshold in hours (CS-209): 1 to 12."""
    low, high = IDLE_RANGE
    if type(value) not in (int, float) or not low <= value <= high:
        raise NotifyError(f"idle_hours must be a number of hours from {low} to {high}")
    return int(value) if float(value).is_integer() else float(value)


def own_edit(stored, submitted, user_id) -> list[dict]:
    """A non-administrator's save, applied to the stored rows: the kinds, rooms and high-priority flag of the
    rows whose user_id is theirs, and nothing else. They cannot add or remove a row, rename one or change
    whose it is, and another person's row must come back as it was."""
    if not isinstance(submitted, list) or not all(
        isinstance(r, dict) for r in submitted
    ):
        raise NotifyError("recipients must be a list of rows")
    given = {}
    for raw in submitted:
        service = raw.get("service")
        service = service.strip() if isinstance(service, str) else None
        if service is None or service in given:
            raise NotifyError("each row names its phone's service once")
        given[service] = raw
    if set(given) != {row["service"] for row in stored}:
        raise NotifyError(
            "not allowed: only an administrator can add or remove a phone"
        )
    rows = []
    for index, row in enumerate(stored, 1):
        raw, where = given[row["service"]], f"phone {index}"
        wanted = {
            "kinds": _kinds(raw.get("kinds"), where),
            "rooms": _rooms(raw.get("rooms"), where),
            "urgent_high_priority": _flag(raw.get("urgent_high_priority"), where),
        }
        if not (row["user_id"] and row["user_id"] == user_id):
            if any(wanted[key] != row[key] for key in wanted):
                raise NotifyError(f"not allowed: {row['name']} is not your phone")
            rows.append(row)
            continue
        name = raw.get("name", row["name"])
        if (name.strip() if isinstance(name, str) else name) != row["name"]:
            raise NotifyError("not allowed: only an administrator can rename a phone")
        if raw.get("user_id", row["user_id"]) != row["user_id"]:
            raise NotifyError(
                "not allowed: only an administrator can change whose phone it is"
            )
        rows.append({**row, **wanted})
    return rows


def route(recipients, kinds, room) -> list[dict]:
    """The rows a push goes to: each that ticks one of its `kinds` and whose rooms are empty or include
    `room`, once per service. A push about no room in particular (`room` None: the dosing thread, the
    controller's clock) goes to every row that ticks its kind."""
    rows, seen = [], set()
    for row in recipients:
        if row["service"] in seen or not kinds.intersection(row["kinds"]):
            continue
        if room is not None and row["rooms"] and room not in row["rooms"]:
            continue
        seen.add(row["service"])
        rows.append(row)
    return rows


def push_data(service, key, urgent) -> dict | None:
    """A push's `data`, for a mobile_app service only (another notify service may refuse keys it does not
    know): the tag, so a repeat replaces the earlier push on the phone, the link that opens the Crop Steering
    panel when the push is tapped, and the high-priority keys.
    """
    if not service.startswith("notify.mobile_app_"):
        return None
    return {"tag": key, **LINK, **(deepcopy(URGENT) if urgent else {})}


def _valid(value) -> dict:
    """A stored document, checked as a save is except that a phone need not exist yet (an app that has not
    registered again since Home Assistant started); anything else is refused."""
    if not isinstance(value, dict) or type(value.get("revision")) is not int:
        raise ValueError("Invalid stored revision")
    return {
        "revision": value["revision"],
        "idle_hours": clean_idle(value.get("idle_hours", IDLE_HOURS)),
        "recipients": clean_recipients(
            [_known_kinds(row) for row in value.get("recipients", [])]
        ),
    }


def _known_kinds(row):
    """A stored row without the kinds this version does not know (saved by a newer one, before a rollback):
    those are dropped, not the whole setup."""
    if isinstance(row, dict) and isinstance(row.get("kinds"), list):
        return {
            **row,
            "kinds": [k for k in row["kinds"] if k in notify_catalog.KIND_IDS],
        }
    return row


class Notifier:
    """The site's notification setup, and the pushes it sends."""

    def __init__(self, hass, store=None):
        self.hass = hass
        self._store = store
        self._lock = asyncio.Lock()
        self._unsubscribe = None
        self._cards = {}  # issue id -> when its card was last pushed, by _clock
        self._clock = time.monotonic
        self.data = empty()
        self.error = None

    async def async_init(self):
        try:
            if self._store is None:
                from homeassistant.helpers.storage import Store

                self._store = Store(self.hass, 1, STORAGE_KEY)
            value = await self._store.async_load()
            if value is not None:
                self.data = _valid(value)
        except Exception as error:
            self.error = (
                "The stored notification setup could not be loaded; it has not been "
                f"overwritten: {error}"
            )
            _LOGGER.error(
                "Crop Steering notifications: %s. Until it is fixed, alerts are pushed "
                "only to the controller app's notify_service option.",
                self.error,
            )

    def publish(self):
        """sensor.crop_steering_notify_config, which the controller app reads: the revision, how many rows and
        the watering-stopped threshold. Unavailable while the stored setup can't be read: the controller then
        pushes to its own notify_service option, as it does with no rows."""
        attributes = {"friendly_name": "Crop Steering notifications"}
        if self.error:
            attributes["error"] = self.error
            self.hass.states.async_set(SENSOR, "unavailable", attributes)
            return
        attributes["recipients"] = len(self.data["recipients"])
        attributes["idle_hours"] = self.data["idle_hours"]
        self.hass.states.async_set(SENSOR, str(self.data["revision"]), attributes)

    async def phones(self) -> list[dict]:
        """Every notify.mobile_app_* service, with the device name and the Home Assistant user whose app
        registered it (the mobile_app config entry's user)."""
        from homeassistant.util import slugify

        owners = {}
        for entry in self.hass.config_entries.async_entries("mobile_app"):
            data = getattr(entry, "data", None) or {}
            name = data.get("device_name") or getattr(entry, "title", None)
            if name:  # mobile_app names each phone's service this way
                owners[slugify(f"mobile_app_{name}")] = (name, data.get("user_id"))
        phones = []
        for service in sorted(self.hass.services.async_services().get("notify", {})):
            if not service.startswith("mobile_app_"):
                continue
            unknown = (service[len("mobile_app_") :].replace("_", " "), None)
            name, user_id = owners.get(service, unknown)
            user = await self.hass.auth.async_get_user(user_id) if user_id else None
            phones.append(
                {
                    "service": f"notify.{service}",
                    "name": name,
                    "user_id": user_id,
                    "user_name": getattr(user, "name", None),
                }
            )
        return phones

    async def response(self, user=None, error=None) -> dict:
        """What notify_get answers, and notify_save with its `error`. `can_edit_all`: the caller is an
        administrator; anyone else may tick only the rows whose user_id is `user_id`, theirs.
        """
        return {
            "schema_version": 1,
            "config": deepcopy(self.data),
            "kinds": notify_catalog.serial(),
            "phones": await self.phones(),
            "can_edit_all": bool(getattr(user, "is_admin", False)),
            "user_id": getattr(user, "id", None),
            "error": error or self.error,
        }

    async def save(self, data, user=None) -> dict:
        """notify_save. `user` None is an automation, which saves as an administrator does, as every service
        that changes something lets it. A refused save answers with the stored setup, unchanged.
        """
        async with self._lock:
            if self.error:
                return await self.response(user)
            if data.get("expected_revision") != self.data["revision"]:
                return await self.response(user, "revision")
            try:
                if user is None or user.is_admin:
                    phones = {phone["service"]: phone for phone in await self.phones()}
                    rows = clean_recipients(data.get("recipients"), phones)
                    self._exist(rows)
                    idle = clean_idle(data.get("idle_hours", self.data["idle_hours"]))
                else:
                    rows = own_edit(
                        self.data["recipients"], data.get("recipients"), user.id
                    )
                    idle = data.get("idle_hours", self.data["idle_hours"])
                    if idle != self.data["idle_hours"]:
                        raise NotifyError(
                            "not allowed: only an administrator can change after how many "
                            "hours a room that has not watered is reported"
                        )
            except NotifyError as error:
                return await self.response(user, str(error))
            draft = {
                "revision": self.data["revision"] + 1,
                "idle_hours": idle,
                "recipients": rows,
            }
            await self._store.async_save(draft)
            self.data = draft
            self.publish()
            return await self.response(user)

    def _exist(self, rows):
        """A phone added now must be a notify service Home Assistant has; one saved before may be away (an
        app not yet registered again after a restart) without stopping a save."""
        saved = {row["service"] for row in self.data["recipients"]}
        for row in rows:
            if row["service"] not in saved and not self._has(row["service"]):
                raise NotifyError(
                    f"{row['service']} is not a notify service in Home Assistant"
                )

    def _has(self, service) -> bool:
        return bool(SERVICE_ID.fullmatch(service)) and self.hass.services.has_service(
            "notify", service.split(".", 1)[1]
        )

    async def test(self, service, user=None) -> dict:
        """notify_test: one test push, for an administrator (or an automation) or the phone's own user."""
        row = next((r for r in self.data["recipients"] if r["service"] == service), {})
        if user is not None and not user.is_admin:
            phone = next(
                (p for p in await self.phones() if p["service"] == service), {}
            )
            if (row.get("user_id") or phone.get("user_id")) != user.id:
                return {
                    "sent": False,
                    "error": f"not allowed: only an administrator or the phone's own user can "
                    f"test {service}",
                }
        if not self._has(service):
            return {
                "sent": False,
                "error": f"{service} is not a notify service in Home Assistant",
            }
        names = [
            k["name"] for k in notify_catalog.KINDS if k["id"] in row.get("kinds", ())
        ]
        message = (
            f"This phone gets: {', '.join(names)}."
            if names
            else "This phone gets nothing yet: tick what it should get under Settings & help "
            "› Notifications."
        )
        error = await self._deliver(
            service, "Crop Steering: a test", message, "crop_steering_test", False
        )
        return {"sent": error is None, "error": error}

    async def send(self, data) -> dict:
        """notify: one push to every row that ticks one of its kinds and covers its room, once per service ->
        {sent_to, error}. `error` names each phone that failed (the others still got it), or says why nothing
        could be sent at all; the controller pushes to its own notify_service only when nothing was sent and
        `error` says why."""
        if self.error:
            return {"sent_to": [], "error": self.error}
        if not self.data["recipients"]:
            return {"sent_to": [], "error": "no phone is set up for notifications"}
        urgent = bool(data.get("urgent"))
        kinds = notify_catalog.kinds_for(data.get("code"), data.get("event"), urgent)
        rows = route(self.data["recipients"], kinds, data.get("room"))
        if urgent and not rows:
            # An emergency must reach someone: with no row covering its room, every phone that takes
            # emergencies for any room gets it; with none at all the controller pushes to its own option.
            rows = route(self.data["recipients"], {"emergency"}, None)
            _LOGGER.warning(
                "Crop Steering emergency %s: no phone takes emergencies for room %r; sent to %s",
                data["key"],
                data.get("room"),
                ", ".join(row["service"] for row in rows) or "nobody",
            )
            if not rows:
                return {"sent_to": [], "error": "no phone takes emergencies"}
        errors = await asyncio.gather(
            *(
                self._deliver(
                    row["service"],
                    data["title"],
                    data["message"],
                    data["key"],
                    urgent and row["urgent_high_priority"],
                )
                for row in rows
            )
        )
        failed = [f"{r['service']}: {e}" for r, e in zip(rows, errors) if e]
        if failed:
            _LOGGER.warning(
                "Crop Steering push %s not delivered: %s",
                data["key"],
                "; ".join(failed),
            )
        return {
            "sent_to": [r["service"] for r, e in zip(rows, errors) if not e],
            "error": "; ".join(failed) or None,
        }

    async def _deliver(self, service, title, message, key, urgent) -> str | None:
        """Send one push -> None, or why it failed. A phone that fails never stops the others."""
        payload = {"title": title, "message": message}
        data = push_data(service, key, urgent)
        if data is not None:
            payload["data"] = data
        domain, name = service.split(".", 1)
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(domain, name, payload, blocking=True),
                SEND_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            return f"no answer in {SEND_TIMEOUT_S} s"
        except Exception as error:  # a phone that fails never stops the others
            return str(error) or type(error).__name__
        return None

    # ------------------------------------------------------------------ Repairs cards
    def listen(self):
        """Push the integration's own Repairs cards (notify_catalog.REPAIRS) as they are raised."""
        from homeassistant.core import callback

        @callback
        def changed(event):
            data = event.data or {}
            # "create" only: an update of a card still raised (new placeholders, or raised again after a
            # restart, when Home Assistant keeps it inactive until then) is not a new card.
            if data.get("domain") == DOMAIN and data.get("action") == "create":
                self.hass.async_create_task(self.push_issue(data.get("issue_id")))

        self._unsubscribe = self.hass.bus.async_listen(ISSUE_EVENT, changed)

    def stop(self):
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    async def push_issue(self, issue_id):
        """A Repairs card just raised, pushed like any alert with key = its issue id, to the phones whose row
        ticks its code's kinds. Only once someone is set up: before this, a card pushed nothing. A card
        cleared and raised again within CARD_QUIET_S is not pushed again.
        """
        if self.error or not self.data["recipients"] or not isinstance(issue_id, str):
            return
        now = self._clock()
        if issue_id in self._cards and now - self._cards[issue_id] < CARD_QUIET_S:
            return
        base = next(
            (
                key
                for key in notify_catalog.REPAIRS
                if issue_id == key or issue_id.startswith(key + "_")
            ),
            None,
        )
        if base is None:
            return
        code = notify_catalog.REPAIRS[base]
        try:
            from homeassistant.helpers import issue_registry as ir

            issue = ir.async_get(self.hass).async_get_issue(DOMAIN, issue_id)
            placeholders = dict(getattr(issue, "translation_placeholders", None) or {})
            prefix, where = self._room(issue_id[len(base) + 1 :] or None)
            title, message = await self._issue_text(base, placeholders, code)
            answer = await self.send(
                {
                    "key": issue_id,
                    "code": code,
                    "room": prefix,
                    "title": (
                        f"{where}: {title}" if where else title[:1].upper() + title[1:]
                    ),
                    "message": message,
                    "urgent": code in notify_catalog.EMERGENCY,
                }
            )
            if answer.get(
                "sent_to"
            ):  # the quiet period starts only once a phone has it
                self._cards[issue_id] = now
        except Exception as error:  # a card's push never breaks the card
            _LOGGER.warning("Repairs card %s not pushed: %s", issue_id, error)

    def _room(self, slug):
        """(prefix, the name a push shows) of the room whose Repairs card this is: `slug` None for the default
        room. The name only when the operator gave one, or the site has more than one room.
        """
        entries = list(self.hass.config_entries.async_entries(DOMAIN))
        for entry in entries:
            data = getattr(entry, "data", None) or {}
            mine = data.get("room_slug", "default")
            if slug != mine and not (slug is None and mine in ("", "default")):
                continue
            name = data.get("room_name") or data.get("name") or ""
            name = name.strip() if isinstance(name, str) else ""
            if name.lower() in UNNAMED:
                name = ""
            if not name and len(entries) > 1:
                name = mine or "default"
            return room_prefix(entry), name[:40]
        return None, ""

    async def _issue_text(self, base, placeholders, code):
        """The card's own title and description, as Settings → Repairs shows them, or a plain stand-in when the
        translations can't be read: a push is never lost to its wording."""
        try:
            from homeassistant.helpers.translation import async_get_translations

            language = getattr(self.hass.config, "language", None) or "en"
            strings = await async_get_translations(
                self.hass, language, "issues", [DOMAIN]
            )
            head = f"component.{DOMAIN}.issues.{base}."
            title, message = strings[head + "title"], strings[head + "description"]
        except Exception:
            title = f"a card in Settings → Repairs ({code})"
            message = (
                f"Code {code}. What it means and what to do: Crop Steering → Help & tools → "
                "Error codes."
            )
        for key, value in placeholders.items():
            title = title.replace("{" + key + "}", str(value))
            message = message.replace("{" + key + "}", str(value))
        return title.removeprefix("Crop Steering: "), message


async def async_setup_notify(hass, entry) -> None:
    """Once for the site, with the first room that sets up; each room after it only joins, and the store, the
    sensor and the services stay while any room is loaded (async_unload_notify)."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault("_notify_entries", set()).add(entry.entry_id)
    if "_notify" in data:
        return
    notifier = data["_notify"] = Notifier(hass)
    await notifier.async_init()
    notifier.publish()
    notifier.listen()

    async def handle(call):
        if call.service == "notify":
            await async_require_admin(hass, call, f"{DOMAIN}.notify")
            return await notifier.send(call.data)
        user_id = getattr(call.context, "user_id", None)
        user = await hass.auth.async_get_user(user_id) if user_id else None
        if call.service == "notify_get":
            return await notifier.response(user)
        # Anyone signed in may save their own phone's row and test their own phone; a user id Home
        # Assistant does not know may not, as the administrator check refuses it.
        if user_id and user is None:
            raise HomeAssistantError(
                f"{DOMAIN}.{call.service} requires a signed-in Home Assistant user"
            )
        try:
            if call.service == "notify_save":
                return await notifier.save(call.data, user)
            return await notifier.test(call.data["service"], user)
        except OSError as error:
            raise HomeAssistantError(str(error)) from error

    schemas = {
        "notify_get": {},
        "notify_save": {
            vol.Required("expected_revision"): vol.All(int, vol.Range(min=0)),
            vol.Required("recipients"): list,
            vol.Optional("idle_hours"): vol.Coerce(float),
        },
        "notify_test": {vol.Required("service"): str},
        "notify": {
            vol.Required("key"): str,
            vol.Optional("code"): str,
            vol.Optional("event"): str,
            vol.Optional("room"): str,
            vol.Optional("zone"): vol.Coerce(int),
            vol.Required("title"): str,
            vol.Required("message"): str,
            vol.Optional("urgent", default=False): bool,
        },
    }
    for service in SERVICES:
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema(schemas[service]),
            # The controller app calls notify over REST asking for its answer; a script may call it without.
            supports_response=(
                SupportsResponse.OPTIONAL
                if service == "notify"
                else SupportsResponse.ONLY
            ),
        )


async def async_unload_notify(hass, entry) -> None:
    """The site's notification setup goes with the last room: its services, its sensor and its listener."""
    data = hass.data.get(DOMAIN, {})
    entries = data.get("_notify_entries", set())
    entries.discard(entry.entry_id)
    notifier = None if entries else data.pop("_notify", None)
    if notifier is None:
        return
    notifier.stop()
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
    hass.states.async_remove(SENSOR)
