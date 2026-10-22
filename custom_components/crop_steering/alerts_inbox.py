"""The alerts inbox: each room's open alerts as sensor.crop_steering_<prefix>alerts_open.

open_alerts() is the pure fold. An alert is open from its alert.raised until an alert.cleared or
alert.acknowledged of the same alert (`data.rule_id` for a threshold rule, `data.key` for the
controller app's). A controller alert (actor other than system) also closes when its `f2_<key>`
persistent notification is gone, as the controller dismisses some notifications directly, with no
alert.cleared. Inbox publishes the fold for every loaded room on each stored alert.* event and every
5 min (journal_api wires it). The sensor's state is the count; `alerts` lists them, newest first.

Nothing here touches irrigation: it only reads the journal and sets a state.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

KINDS = ["alert.raised", "alert.cleared", "alert.acknowledged"]
EVERY = timedelta(minutes=5)
SINCE_EVER = "1970-01-01T00:00:00+00:00"
INBOX = "_alerts_inbox"


def _identity(event) -> tuple:
    data = event.get("data") or {}
    if data.get("rule_id"):
        return ("rule", data["rule_id"])
    if data.get("key"):
        return ("key", data["key"])
    if event.get("kind") == "alert.raised":
        return ("event", event.get("id"))
    return ("event", data.get("alert_event_id"))


def open_alerts(
    events: list[dict], live_notifications: set[str], entity_of: dict | None = None
) -> list[dict]:
    """The open alerts of `events` (one room's alert.* events, oldest first), newest first.
    `live_notifications`: the ids of the persistent notifications shown now. `entity_of`: {rule id:
    the entity its source reads}. A raise repeated while the alert is open keeps the first.
    """
    raised: dict[tuple, dict] = {}
    for event in events:
        identity = _identity(event)
        if event.get("kind") == "alert.raised":
            raised.setdefault(identity, event)
        elif event.get("kind") in ("alert.cleared", "alert.acknowledged"):
            raised.pop(identity, None)
    out = []
    for event in raised.values():
        data = event.get("data") or {}
        rule_id = data.get("rule_id")
        controller = (event.get("source") or {}).get("actor") != "system"
        if (
            controller
            and data.get("key")
            and f"f2_{data['key']}" not in live_notifications
        ):
            continue
        alert = {
            "event_id": event.get("id"),
            "ts": event.get("ts"),
            "code": event.get("code"),
            "title": data.get("title"),
            "zone": event.get("zone"),
            "entity_id": (
                (entity_of or {}).get(rule_id) if rule_id else data.get("entity_id")
            ),
        }
        if rule_id:
            alert["rule_id"] = rule_id
        out.append({**alert, "acknowledged": False})
    return sorted(out, key=lambda a: a["ts"] or "", reverse=True)


def sensor_id(room_id: str) -> str:
    return f"sensor.{DOMAIN}_{room_id[len('room:'):]}alerts_open"


def live_notifications(hass) -> set[str]:
    """The ids of the persistent notifications Home Assistant shows now."""
    from homeassistant.components import persistent_notification

    return set(persistent_notification._async_get_or_create_notifications(hass))


def rule_entities(hass, room_id) -> dict:
    """{rule id: the one entity its source reads} for the room's rules (RuleEvaluator.entities); a
    rule that reads several (more than one zone) names none."""
    site = hass.data.get(DOMAIN, {}).get("_site")
    evaluator = getattr(site, "alerts", None)
    if evaluator is None:
        return {}
    out = {}
    for rule in site.rules(room_id):
        try:
            entities = evaluator.entities(rule)
        except Exception:  # an unreadable descriptor: the alert names no entity
            continue
        if len(entities) == 1:
            out[rule["id"]] = entities[0]
    return out


async def read_open(hass, hub, room_id) -> list[dict]:
    """The room's open alerts now, from its whole alert.* history."""
    events, cursor = [], None
    while True:
        page = await hub.query(
            room_id=room_id, since=SINCE_EVER, kinds=KINDS, cursor=cursor
        )
        events += page["events"]
        cursor = page["cursor"]
        if cursor is None:
            break
    return open_alerts(events, live_notifications(hass), rule_entities(hass, room_id))


def acknowledge_rule(hass, rule_id) -> None:
    """A firing rule's live state becomes acknowledged (its binary sensor stays on until it clears)."""
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from .site_api import RULE_STATE

    site = hass.data.get(DOMAIN, {}).get("_site")
    states = getattr(getattr(site, "alerts", None), "states", {})
    if (states.get(rule_id) or {}).get("state") == "firing":
        states[rule_id] = {**states[rule_id], "state": "acknowledged"}
        async_dispatcher_send(hass, RULE_STATE.format(rule_id))


class Inbox:
    """Publishes each loaded room's alerts_open sensor."""

    def __init__(self, hass, hub):
        self.hass, self.hub = hass, hub
        self.rooms: set[str] = set()
        self._lock = asyncio.Lock()

    def join(self, room_id) -> None:
        self.rooms.add(room_id)
        self.hass.async_create_task(self.publish(room_id))

    def leave(self, room_id) -> None:
        self.rooms.discard(room_id)
        self.hass.states.async_remove(sensor_id(room_id))

    async def publish(self, room_id) -> None:
        async with self._lock:
            if room_id not in self.rooms:
                return
            try:
                alerts = await read_open(self.hass, self.hub, room_id)
            except Exception as error:  # the journal is down: say so, never raise
                _LOGGER.debug("Alerts inbox of %s not read: %s", room_id, error)
                self.hass.states.async_set(
                    sensor_id(room_id), "unavailable", {"room_id": room_id}
                )
                return
            if room_id not in self.rooms:  # the room left while it was read
                return
            self.hass.states.async_set(
                sensor_id(room_id),
                str(len(alerts)),
                {
                    "friendly_name": "Crop Steering open alerts",
                    "room_id": room_id,
                    "alerts": alerts,
                },
            )

    async def publish_all(self, *_):
        for room_id in sorted(self.rooms):
            await self.publish(room_id)

    def start(self) -> list:
        """Publish again on each stored alert.* event and every EVERY. -> unsubs."""
        from homeassistant.core import callback
        from homeassistant.helpers.event import async_track_time_interval

        from .const import EVENT_JOURNAL

        @callback
        def stored(event):
            body = event.data
            if str(body.get("kind", "")).startswith("alert.") and (
                body.get("room_id") in self.rooms
            ):
                self.hass.async_create_task(self.publish(body["room_id"]))

        return [
            self.hass.bus.async_listen(EVENT_JOURNAL, stored),
            async_track_time_interval(self.hass, self.publish_all, EVERY),
        ]

    def stop(self) -> None:
        for room_id in list(self.rooms):
            self.leave(room_id)
