"""The second guard of a shot: switch OFF what a shot opened when the controller goes silent.

The controller is the only part that opens anything. In a shot's wait, with its valve open, it
writes `sensor.crop_steering_<prefix>shot_in_flight` = "open", with what the shot opened (valve,
main line, pump), the holds, the other valves on the same line, and two lengths in seconds:
`opened_s`, how long before the write the shot began to open, and `max_s`, by when a controller
that still runs has closed the shot. It writes "idle" once the pass is over. If the controller
dies, hangs or loses Home Assistant in the middle of a shot, the "open" stays, and nothing else
closes the valve until the controller starts again.

Each EVERY this module looks at that state. When it has seen the same "open" for `max_s` and
GRACE_S, it switches off what the shot opened and is still on. The wait is counted on this
process's monotonic clock from when the guard first saw the state: that is never before the write,
so the wait is never short, and no clock that is set forward or back, here or on the controller's
machine, changes it. It is kept over a reload of the room. The rules are the controller's own for
an interrupted shot (its _inflight_plan):

  * only a switch that went on while the shot opened (within `opened_s` and EARLY_S before the
    write). One switched at another time stays, and so does all upstream of it: a person switched
    it, or it lost its connection and came back. The controller also asks the recorder's history
    here; this guard does not;
  * valve first, then the main line, then the pump;
  * the main line and the pump stay while another valve on the line is open;
  * the pump stays while a hold is on;
  * a switch that cannot be read is not touched, and nothing upstream of it is.

It acts on the devices that the state names, in the domains the controller switches. It does not
ask for them to be in the room's map here: the map of an older room is in the controller app's
options, where this integration cannot see it.

A shot's valve that is still on past the wait is closed whatever else is known: that is the case
this guard is for. Two other cases are less clear, and in them the guard also asks whether the
controller still reports (its heartbeat was written in the last SILENT_S, and does not say
"stopped"). A controller that reports writes "idle" only when its whole pass is over, so an
"open" can stand past its wait while it waters other zones:

  * the shot's valve is off and its pump or main line is on. While the controller reports, they
    are left: it may be priming the next shot through them;
  * the shot's valve does not read off and the rules say to leave it (it cannot be read, or it
    was not switched on by this shot). While the controller reports, nothing is said; once it is
    silent, the card is raised and says why.

It acts whatever the room's kill switch reads: "Watering off" means no water. It never switches
anything on, and it does nothing before the controller's own deadline. Then it reads back, raises
the Repairs card CS-617 (kept until a person confirms it) and journals the alert. A controller
older than this state never writes it, and then nothing here ever acts.

Limits. Home Assistant does not keep this state over its own restart: after a restart in the
middle of a shot this guard knows nothing. A shot whose controller dies while it opens, before the
"open" is written, was never written. In both cases the controller closes the shot when it runs
again, if its own record of the shot is there and can be used.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, REPAIRS_DOCS_URL
from .room import room_prefix
from .safety_ops import OFF_STATES, STOP_READBACK_S, _off_call

_LOGGER = logging.getLogger(__name__)

EVERY = timedelta(seconds=30)
GRACE_S = 60.0  # after the controller's own deadline
SILENT_S = 180.0  # no heartbeat write for this long: the controller has stopped reporting (3 passes)
EARLY_S = (
    5.0  # a switch may read on this long before the write (the controller's window)
)
LONGEST_S = 4 * 3600.0  # a length over this is not a shot's: the state is not trusted
ATTEMPTS = (
    3  # times one shot's switches are sent OFF; then the card stands and a person acts
)
PAUSE_S = (
    1.0  # after the valve, before the main line and the pump, as the controller closes
)
ACTUATORS = ("switch", "input_boolean", "valve")  # the domains the controller switches
ON = ("on", "open")
HOLD_ON = ("on", "true", "open", "1", "home")  # the controller's ON_STATES
ISSUE = "shot_left_open"
CODE = "CS-617"


def _length(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 < value <= LONGEST_S
    )


def _reads_on(hass, entity_id, on=ON) -> bool:
    state = hass.states.get(entity_id)
    return state is not None and str(state.state).lower() in on


def plan(hass: HomeAssistant, state) -> tuple[list[str], str] | None:
    """What to switch off for the shot `state` describes -> ([entity ids, valve first], why the
    rest was left: "" when nothing that is on was left), or None when the state is not one this
    guard can act on. When to act is tick's."""
    attrs = state.attributes
    max_s, opened_s = attrs.get("max_s"), attrs.get("opened_s")
    if state.state != "open" or not _length(max_s) or not _length(opened_s):
        return None
    valve, pump = attrs.get("valve"), attrs.get("pump")
    order = [e for e in (valve, attrs.get("mainline"), pump) if e]
    if not order or not all(
        isinstance(e, str) and e.split(".", 1)[0] in ACTUATORS for e in order
    ):
        return None
    others = [e for e in attrs.get("line_valves") or [] if isinstance(e, str)]
    holds = [e for e in attrs.get("holds") or [] if isinstance(e, str)]
    close: list[str] = []
    for entity_id in order:
        read = hass.states.get(entity_id)
        if read is not None and read.state in OFF_STATES:
            continue
        if read is None or read.state not in ON:
            return close, f"{entity_id} cannot be read"
        since = (read.last_changed - state.last_updated).total_seconds()
        if not -(opened_s + EARLY_S) <= since <= 0:
            return close, f"{entity_id} was not switched on by this shot"
        if entity_id != valve and any(_reads_on(hass, other) for other in others):
            return close, "another valve on this line is open"
        if entity_id == pump and any(_reads_on(hass, hold, HOLD_ON) for hold in holds):
            return close, "a hold (dosing, fill, flush or circulation) is on"
        close.append(entity_id)
    return close, ""


async def switch_off(hass: HomeAssistant, entities: list[str]) -> list[str]:
    """Send OFF to each, in order, and read back -> the ones that do not read off."""
    for i, entity_id in enumerate(entities):
        domain, service = _off_call(entity_id)
        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    domain, service, {"entity_id": entity_id}, blocking=True
                ),
                STOP_READBACK_S,
            )
        except (
            Exception
        ) as err:  # noqa: BLE001 - the read-back below says what is still on
            _LOGGER.warning("Shot guard: %s not switched off: %s", entity_id, err)
        if i == 0 and len(entities) > 1:
            await asyncio.sleep(PAUSE_S)

    def still_on():
        return [
            e
            for e in entities
            if (s := hass.states.get(e)) is None or s.state not in OFF_STATES
        ]

    waited = 0.0
    while still_on() and waited < STOP_READBACK_S:
        await asyncio.sleep(0.5)
        waited += 0.5
    return still_on()


def issue_id(entry) -> str:
    slug = entry.data.get("room_slug", "default")
    return ISSUE if slug in ("", "default") else f"{ISSUE}_{slug}"


class Backstop:
    """One room's guard. `memory` is the room's, kept over a reload: under "shot", the "open" it is
    looking at, when it first saw it by `clock`, how often its switches were sent OFF, and whether
    it has been reported; under "beat", the controller's last heartbeat write and when it was seen.
    """

    def __init__(self, hass: HomeAssistant, entry, memory: dict) -> None:
        self.hass, self.entry = hass, entry
        self.memory = memory.setdefault("shot", {})
        self.beat = memory.setdefault("beat", {})
        self.prefix = room_prefix(entry)
        self.entity_id = f"sensor.{DOMAIN}_{self.prefix}shot_in_flight"
        self.heartbeat_id = f"sensor.{DOMAIN}_{self.prefix}ai_heartbeat"
        self.clock = time.monotonic
        self._acting = False

    def silent(self) -> bool:
        """Whether the controller has stopped reporting: no heartbeat, one that says "stopped", or
        one not written for SILENT_S of this guard's clock (looked at each EVERY)."""
        state = self.hass.states.get(self.heartbeat_id)
        stamp = None if state is None else state.last_updated.isoformat()
        if self.beat.get("stamp") != stamp or "at" not in self.beat:
            self.beat.update(stamp=stamp, at=self.clock())
        if state is None or state.state == "stopped":
            return True
        return self.clock() - self.beat["at"] >= SILENT_S

    async def tick(self, _now=None) -> None:
        if self._acting:
            return
        silent = self.silent()
        state = self.hass.states.get(self.entity_id)
        if state is None or state.state != "open":
            self.memory.clear()
            return
        shot = f"{state.attributes.get('started')} {state.last_updated.isoformat()}"
        if self.memory.get("shot") != shot:
            self.memory.clear()
            self.memory.update(shot=shot, seen=self.clock(), tries=0, said=False)
        found = plan(self.hass, state)
        if not found:
            return
        if self.clock() - self.memory["seen"] < state.attributes["max_s"] + GRACE_S:
            return
        close, left = found
        valve = self.hass.states.get(state.attributes.get("valve") or "")
        valve_off = valve is not None and valve.state in OFF_STATES
        if valve_off and not silent:
            # Only a pump or a main line is on, behind the shot's closed valve, and the controller
            # reports: it is using them, or will say "idle" when its pass is over.
            return
        if not close:
            # The shot's own valve does not read off and the rules say to leave it. With the
            # controller silent that is said, once.
            if left and not valve_off and silent and not self.memory["said"]:
                _LOGGER.warning(
                    "Shot guard: the controller did not close its shot of zone %s in time; "
                    "nothing switched off: %s",
                    state.attributes.get("zone"),
                    left,
                )
                self._report(state, [], [], left)
            return
        if self.memory["tries"] >= ATTEMPTS:
            return
        self.memory["tries"] += 1
        self._acting = True
        try:
            _LOGGER.warning(
                "Shot guard: the controller did not close its shot of zone %s in time; "
                "switching off %s",
                state.attributes.get("zone"),
                ", ".join(close),
            )
            still_on = await switch_off(self.hass, close)
            self._report(state, close, still_on, left)
        finally:
            self._acting = False

    def _report(self, state, close, still_on, left) -> None:
        """The card, new or with what the last try found; the journal row once for a shot."""
        zone = state.attributes.get("zone")
        zone = zone if isinstance(zone, int) and not isinstance(zone, bool) else None
        if not close:
            action = "The integration switched nothing off."
            caution = " CAUTION: The valve of the shot does not read off. Go to the room now and look."
        elif still_on:
            action = f"The integration sent OFF to: {', '.join(close)}."
            caution = (
                f" CAUTION: These still read on: {', '.join(still_on)}. Water can still flow. "
                "Go to the room now and stop them by hand."
            )
        else:
            action = f"The integration sent OFF to: {', '.join(close)}."
            caution = " Each of them now reads off."
        first = not self.memory["said"]
        if (
            first
        ):  # a card of an earlier shot that nobody confirmed: this one is made again
            ir.async_delete_issue(self.hass, DOMAIN, issue_id(self.entry))
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id(self.entry),
            data={"entry_id": self.entry.entry_id, "kind": ISSUE},
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.CRITICAL,
            translation_key=ISSUE,
            translation_placeholders={
                "zone": "?" if zone is None else str(zone),
                "at": dt_util.now().strftime("%Y-%m-%d %H:%M"),
                "action": action,
                "caution": caution,
                "left": f" It left the rest on: {left}." if left else "",
            },
            learn_more_url=REPAIRS_DOCS_URL,
        )
        if not first:
            return
        self.memory["said"] = True
        from .journal_api import note

        note(
            self.hass,
            "room:" + self.prefix,
            "alert.raised",
            zone=zone,
            outcome="failed" if still_on or not close else "ok",
            code=CODE,
            actor="system",
            detail="shot guard",
            data={
                "key": issue_id(self.entry),
                "title": "The controller did not close a shot",
                "entity_id": state.attributes.get("valve"),
                "switched_off": [e for e in close if e not in still_on],
                "still_on": still_on,
                "left": left or None,
            },
        )


def confirmed(hass: HomeAssistant, entry_id: str | None) -> None:
    """A person confirmed the card: the alert closes in the room's journal too."""
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None:
        return
    from .journal_api import note

    note(
        hass,
        "room:" + room_prefix(entry),
        "alert.cleared",
        actor="manual",
        detail="shot guard",
        data={"key": issue_id(entry)},
    )


def async_setup_backstop(hass: HomeAssistant, entry) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    # what each guard knows of the shot it is looking at and of the heartbeat: kept when the room
    # reloads, so a reload never starts the wait again, sends more OFFs or raises a confirmed card again
    memory = data.setdefault("_shot_backstop_memory", {}).setdefault(entry.entry_id, {})
    guard = Backstop(hass, entry, memory)
    guards = data.setdefault("_shot_backstop", {})
    guards[entry.entry_id] = guard

    def forget() -> None:
        guards.pop(entry.entry_id, None)

    entry.async_on_unload(async_track_time_interval(hass, guard.tick, EVERY))
    entry.async_on_unload(forget)
