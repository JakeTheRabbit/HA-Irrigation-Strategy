"""A tiny in-memory Home Assistant double for driving controller.py in tests.

Patches the controller module's REST shims (ha_get / ha_call / ha_get_all / ha_set)
and load_options so a Controller can be constructed and stepped with no live HA and
no /data files.
"""
from __future__ import annotations

from datetime import datetime, timezone

_CURRENT_TIMESTAMP = object()


class _Read(tuple):
    """(state, attributes, last_updated), plus `last_changed` as Home Assistant reports it."""

    last_changed = None


class FakeHA:
    def __init__(self):
        # entity_id -> (state, attributes, last_updated_iso)
        self.states: dict[str, tuple] = {}
        self.changed: dict[str, str] = {}  # entity_id -> last_changed_iso (when the VALUE last changed)
        self.calls: list[tuple] = []  # (domain, service, data)
        self.sets: dict[str, tuple] = {}  # entity_id -> (state, attributes)
        self.history: dict[str, list] = {}  # entity_id -> what ha_history returns (a test's own)

    # ---- state helpers ----
    def set_state(self, entity_id, state, attributes=None, last_updated=_CURRENT_TIMESTAMP):
        if last_updated is _CURRENT_TIMESTAMP:
            last_updated = datetime.now(timezone.utc).isoformat()
        previous = self.states.get(entity_id)
        if previous is None or previous[0] != str(state):
            self.changed[entity_id] = last_updated
        self.states[entity_id] = (str(state), attributes or {}, last_updated)

    # ---- controller shims ----
    def ha_get(self, entity, timeout=8):
        read = _Read(self.states.get(entity, (None, {}, None)))
        read.last_changed = self.changed.get(entity) if entity in self.states else None
        return read

    def ha_call(self, domain, service, **data):
        self.calls.append((domain, service, data))
        # emulate a switch actually toggling, so valve read-back sees the new state
        if domain == "switch" and "entity_id" in data:
            self.set_state(
                data["entity_id"], "on" if service == "turn_on" else "off"
            )
        return True

    def ha_history(self, entity, since, timeout=12):
        """What the recorder holds from `since`: a test's own list, else the state the entity is in now."""
        if entity in self.history:
            return self.history[entity]
        if entity not in self.states:
            return None
        return [(self.states[entity][0], self.changed.get(entity))]

    def ha_get_all(self):
        out = []
        for eid, (state, attrs, _lu) in self.states.items():
            out.append({"entity_id": eid, "state": state, "attributes": attrs})
        return out

    def ha_set(self, entity, state, attributes=None, timeout=None):
        self.sets[entity] = (state, attributes or {})


def install(controller, fake: FakeHA, options: dict):
    """Point the controller module's IO functions at `fake` and its options at `options`.

    Returns the original callables so a test can restore them if needed.
    """
    orig = (
        controller.load_options,
        controller.ha_get,
        controller.ha_call,
        controller.ha_get_all,
        controller.ha_set,
        controller.ha_history,
    )
    controller.load_options = lambda: dict(options)
    controller.ha_get = fake.ha_get
    controller.ha_call = fake.ha_call
    controller.ha_get_all = fake.ha_get_all
    controller.ha_set = fake.ha_set
    controller.ha_history = fake.ha_history
    return orig
