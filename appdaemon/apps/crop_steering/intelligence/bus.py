"""In-process pub/sub bus for RootSense intelligence modules.

Why a separate bus rather than reusing AppDaemon's event system:

- Some payloads are large (full dryback episodes, optimisation posteriors)
  and not interesting to HA — keeping them in-process avoids round-trips
  through the HA event bus.
- Subscribers can be plain Python callables on the AppDaemon side without
  needing `listen_event` plumbing.
- HA still receives the high-signal events (anomalies, run reports, custom
  shots) via the orchestration coordinator's bridge.

Usage::

    bus = RootSenseBus.instance()
    bus.subscribe("dryback.complete", my_callback)
    bus.publish("dryback.complete", {"zone": 1, "pct": 18.4})
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, DefaultDict

_LOGGER = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], None]


class RootSenseBus:
    _singleton: "RootSenseBus | None" = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self._subs: DefaultDict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()

    @classmethod
    def instance(cls) -> "RootSenseBus":
        if cls._singleton is None:
            with cls._singleton_lock:
                if cls._singleton is None:
                    cls._singleton = cls()
        return cls._singleton

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._subs[topic].append(handler)
        _LOGGER.debug("RootSenseBus: %s subscribed to %s", handler, topic)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._subs.get(topic, []):
                self._subs[topic].remove(handler)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            handlers = list(self._subs.get(topic, []))
        for h in handlers:
            try:
                h(topic, payload)
            except Exception:  # noqa: BLE001 — pub/sub must not crash producers
                _LOGGER.exception("RootSenseBus handler failed on %s", topic)


TOPICS = {
    "shot.requested": "An intelligence module wants a shot fired.",
    "shot.fired": "Hardware confirmed a shot was executed.",
    "shot.response": "Post-shot VWC peak observed; payload includes ΔVWC.",
    "dryback.complete": "A full dryback episode (peak → valley) was detected.",
    "field_capacity.observed": "FieldCapacityObserver published a new estimate.",
    "intent.changed": "Cultivator intent slider moved; derived params re-published.",
    "anomaly.detected": "AnomalyScanner flagged something worth surfacing.",
    "run.report": "Nightly run report ready.",
}
