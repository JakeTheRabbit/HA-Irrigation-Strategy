"""What's new: the release highlights the dashboard shows once after an update.

The highlights are WHATS_NEW.md, beside this file. It is a document, so a release pull request may
add its section (.github/scripts/release_guards.py lets a release change documents and version
numbers only), and HACS installs it with the integration: the dashboard reads it from here, not
from its own bundle, which a release pull request may not rebuild.

Which release the window last showed is kept for the whole installation, not per browser or per
person, so it shows once, to the first person who opens the dashboard after an update. A new
installation starts at its own version, with nothing to catch up on. One that was already running
before this existed has missed an unknown number of releases (`seen` None): the dashboard then
shows the last 30 days of them.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from .const import DOMAIN, SOFTWARE_VERSION

STORAGE_KEY = f"{DOMAIN}.whats_new"
STORAGE_VERSION = 1
SERVICES = ("whats_new_get", "whats_new_seen")
NOTES = Path(__file__).with_name("WHATS_NEW.md")
HEADING = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})\s*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# Plenty for a window that shows at most five, and for Help & tools' recent releases.
MAX_RELEASES = 20


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def parse(text: str) -> list[dict]:
    """Each release section, newest first: {"version", "date", "items"}.

    A `## x.y.z - YYYY-MM-DD` heading opens a section and each `- ` line under it is one item; an
    indented line continues the item above it. Anything else (the writing rules above the first
    section, another heading) is not part of a release.
    """
    releases: list[dict] = []
    current = None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            current = {"version": heading[1], "date": heading[2], "items": []}
            releases.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None and line.startswith("- "):
            current["items"].append(line[2:].strip())
        elif (
            current is not None
            and current["items"]
            and line.startswith("  ")
            and line.strip()
        ):
            current["items"][-1] += " " + line.strip()
    return sorted(
        releases, key=lambda release: version_key(release["version"]), reverse=True
    )


class WhatsNew:
    """The installation's one record of the last release the window showed."""

    def __init__(self, hass) -> None:
        from homeassistant.helpers.storage import Store

        self.hass = hass
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.seen: str | None = None
        self.lock = asyncio.Lock()
        self._releases: list[dict] | None = None

    async def async_init(self, fresh: bool) -> None:
        data = await self.store.async_load()
        if isinstance(data, dict) and "seen" in data:
            seen = data["seen"]
            self.seen = seen if isinstance(seen, str) and VERSION.match(seen) else None
            return
        # The first start with this. A room set up just now is a new installation: nothing to catch
        # up on. A room that was already here has been running an older release.
        self.seen = SOFTWARE_VERSION if fresh else None
        await self.store.async_save({"seen": self.seen})

    async def releases(self) -> list[dict]:
        if self._releases is None:
            try:
                text = await self.hass.async_add_executor_job(NOTES.read_text, "utf-8")
            except OSError:
                text = ""
            installed = version_key(SOFTWARE_VERSION)
            self._releases = [
                release
                for release in parse(text)
                if version_key(release["version"]) <= installed
            ][:MAX_RELEASES]
        return self._releases

    async def response(self) -> dict:
        return {
            "version": SOFTWARE_VERSION,
            "seen": self.seen,
            "releases": await self.releases(),
        }

    async def mark_seen(self, version: str) -> dict:
        """The window has shown the highlights up to `version`. Only ever forward, and never past
        the installed version: a dashboard left open across an update cannot skip the new one.
        """
        if not VERSION.match(version):
            raise ValueError("version must be x.y.z")
        async with self.lock:
            newer = self.seen is None or version_key(version) > version_key(self.seen)
            if newer and version_key(version) <= version_key(SOFTWARE_VERSION):
                self.seen = version
                await self.store.async_save({"seen": self.seen})
        return {"seen": self.seen}


async def async_setup_whats_new(hass, entry, fresh: bool) -> None:
    """Once per start, with the first room that sets up: load the record, register the services.

    `fresh`: this room has no entities yet, so it was set up just now, not on an earlier start.
    """
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault("_whats_new_entries", set()).add(entry.entry_id)
    if "_whats_new" in data:
        return
    manager = WhatsNew(hass)
    data["_whats_new"] = manager
    await manager.async_init(fresh)

    async def handle(call):
        # Anyone who can open the dashboard may read the highlights and dismiss the window: it
        # changes nothing but whether the window shows again.
        try:
            if call.service == "whats_new_get":
                return await manager.response()
            return await manager.mark_seen(call.data["version"])
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error

    hass.services.async_register(
        DOMAIN,
        "whats_new_get",
        handle,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "whats_new_seen",
        handle,
        schema=vol.Schema({vol.Required("version"): str}),
        supports_response=SupportsResponse.ONLY,
    )


async def async_unload_whats_new(hass, entry) -> None:
    data = hass.data.get(DOMAIN, {})
    entries = data.get("_whats_new_entries", set())
    entries.discard(entry.entry_id)
    if not entries and data.pop("_whats_new", None) is not None:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
