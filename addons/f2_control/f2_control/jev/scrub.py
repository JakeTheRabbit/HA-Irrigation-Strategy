"""No Home Assistant entity id ever reaches the Claude brain, or comes back from it into the journal.

Two passes over a string: every id the controller itself reads or writes (`remember()`), replaced literally, longest
first; then any `<domain>.<object>` whose domain is a Home Assistant entity domain. A bare `word.word` match is not
used: it would also eat "e.g." and host names in an alert's text. HA_DOMAINS is every `homeassistant.const.Platform`
value plus the helper and core domains; a tests_ha test fails when a Home Assistant adds a platform this list lacks.
"""
from __future__ import annotations

import re
import threading

HA_DOMAINS = (
    "ai_task", "air_quality", "alarm_control_panel", "assist_satellite", "automation", "binary_sensor", "button",
    "calendar", "camera", "climate", "conversation", "counter", "cover", "date", "datetime", "device_tracker",
    "event", "fan", "geo_location", "group", "humidifier", "image", "image_processing", "input_boolean",
    "input_button", "input_datetime", "input_number", "input_select", "input_text", "lawn_mower", "light", "lock",
    "media_player", "notify", "number", "person", "remote", "scene", "schedule", "script",
    "select", "sensor", "siren", "stt", "sun", "switch", "text", "time", "timer", "todo", "tts", "update", "vacuum",
    "valve", "wake_word", "water_heater", "weather", "zone",
)
WORDS = "a sensor"
_GENERIC = re.compile(r"\b(?:" + "|".join(sorted(HA_DOMAINS, key=len, reverse=True)) + r")\.[a-z0-9_]+\b")
_known: set = set()
_lock = threading.Lock()


def remember(ids):
    """Add the controller's own entity ids (each one it reads or writes) to the literal pass."""
    with _lock:
        _known.update(i for i in ids if isinstance(i, str) and "." in i)


def scrub(text):
    """`text` with every entity id replaced by "a sensor"."""
    if not isinstance(text, str) or "." not in text:
        return text
    with _lock:
        known = sorted(_known, key=len, reverse=True)
    for entity in known:
        if entity in text:
            text = text.replace(entity, WORDS)
    return _GENERIC.sub(WORDS, text)


def scrub_all(value):
    """Every string in a JSON-like value scrubbed (dict keys are code's own and stay as they are)."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: scrub_all(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_all(v) for v in value]
    return value
