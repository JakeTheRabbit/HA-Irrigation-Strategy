"""Multi-room helpers.

Each config entry is a *room*. The first/default room uses **no** entity prefix, so existing
single-room installs (e.g. F2) are completely unchanged. Additional rooms namespace their
entities as ``crop_steering_<slug>_*`` so rooms are fully isolated — own zones, sensors,
hardware and setpoints, nothing shared.
"""
from __future__ import annotations

import re


def slugify_room(name: str) -> str:
    """A safe entity-id-friendly slug for a room name."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "room"


def room_prefix(entry) -> str:
    """The entity-id prefix for this room's config entry.

    Returns ``""`` for the default room (legacy, un-prefixed) or ``"<slug>_"`` for an
    additional room. Used as ``f"{DOMAIN}_{room_prefix(entry)}{key}"``.
    """
    try:
        return entry.data.get("room_prefix", "") or ""
    except Exception:  # pragma: no cover - defensive
        return ""
