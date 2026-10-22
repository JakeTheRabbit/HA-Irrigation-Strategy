"""Revisioned room context and the controller's actual prompt, never shipped doctrine edits."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re

from .api_v2 import StaleRevision
from .admin import async_require_admin
from .const import DOMAIN
from .room import room_prefix

SIGNAL = f"{DOMAIN}_brain_prompt_changed"
SERVICES = (
    "brain_prompt_get",
    "brain_prompt_save",
    "brain_prompt_rollback",
    "brain_prompt_rebuild",
    "brain_prompt_publish",
)
KEEP = 10
MAX_TEXT = 12000
PROFILE_KEYS = (
    "substrate",
    "environment",
    "genetics",
    "stage",
    "feed",
    "goals",
    "constraints",
    "calibration",
)


def defaults():
    return {
        "notes": "",
        "profile": {},
        "cache": {"ttl": "1h", "A": True, "B": True, "C": True, "evidence": True},
    }


def validate(value):
    if not isinstance(value, dict) or set(value) - {"notes", "profile", "cache"}:
        raise ValueError("Provide notes, profile and cache settings only")
    out = defaults()
    notes = value.get("notes", "")
    profile = value.get("profile", {})
    if not isinstance(notes, str) or len(notes) > MAX_TEXT:
        raise ValueError(f"House notes must be text up to {MAX_TEXT} characters")
    if not isinstance(profile, dict) or set(profile) - set(PROFILE_KEYS):
        raise ValueError("Unknown grow context field")
    for key, text in profile.items():
        if not isinstance(text, str) or len(text) > 1000:
            raise ValueError("Each context field must be text up to 1000 characters")
        if text.strip():
            out["profile"][key] = text.strip()
    out["notes"] = notes.strip()
    text = " ".join([notes, *profile.values()])
    if re.search(
        r"(?i)(?:ignore|bypass|disable|override|skip)\s+(?:all\s+|the\s+|code[- ]enforced\s+)*(?:previous instructions|safety|interlocks?|kill switch|daily cap|holds?)",
        text,
    ):
        raise ValueError(
            "Context must not ask the AI to bypass safety rules or interlocks"
        )
    cache = value.get("cache", {})
    if not isinstance(cache, dict) or set(cache) - set(out["cache"]):
        raise ValueError("Unknown cache setting")
    if cache.get("ttl", "1h") not in ("5m", "1h"):
        raise ValueError("Cache TTL must be 5m or 1h")
    for key in ("A", "B", "C", "evidence"):
        if key in cache and type(cache[key]) is not bool:
            raise ValueError("Cache breakpoints must be on or off")
    out["cache"].update(cache)
    return out


class BrainPromptStore:
    def __init__(self, hass, entry, store=None):
        self.hass, self.entry, self._store = hass, entry, store
        self.prefix = room_prefix(entry)
        self.room_id = "room:" + self.prefix
        self.revision, self.rebuild = 0, 0
        self.config, self.history, self.live = defaults(), [], None
        self._lock = asyncio.Lock()

    async def async_init(self):
        if self._store is None:
            from homeassistant.helpers.storage import Store

            self._store = Store(
                self.hass, 1, f"{DOMAIN}.brain_prompt.{self.entry.entry_id}"
            )
        saved = await self._store.async_load()
        if isinstance(saved, dict):
            try:
                config = validate(saved.get("config", {}))
                revision, rebuild = int(saved.get("revision", 0)), int(
                    saved.get("rebuild", 0)
                )
                if revision < 0 or rebuild < 0:
                    raise ValueError("Invalid revision")
                self.config, self.revision, self.rebuild = config, revision, rebuild
                self.history = [
                    h
                    for h in saved.get("history", [])
                    if isinstance(h, dict) and "config" in h
                ][-KEEP:]
                self.live = (
                    saved.get("live") if isinstance(saved.get("live"), dict) else None
                )
            except (ValueError, TypeError):
                pass  # a malformed older store never prevents a room loading

    def document(self):
        usage = self.hass.states.get(f"sensor.{DOMAIN}_{self.prefix}jev")
        telemetry = getattr(usage, "attributes", {})
        return deepcopy(
            {
                "room_id": self.room_id,
                "revision": self.revision,
                "rebuild": self.rebuild,
                "config": self.config,
                "history": self.history,
                "live": self.live,
                "telemetry": {
                    k: telemetry.get(k)
                    for k in (
                        "tokens_today",
                        "cache_hit_ratio",
                        "spent_usd",
                        "model",
                        "cache_savings_estimate_usd",
                    )
                },
            }
        )

    async def _persist(self, revision, config, history, rebuild, live):
        await self._store.async_save(
            {
                "revision": revision,
                "config": config,
                "history": history,
                "rebuild": rebuild,
                "live": live,
            }
        )
        self.revision, self.config, self.history, self.rebuild, self.live = (
            revision,
            config,
            history,
            rebuild,
            live,
        )
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(self.hass, f"{SIGNAL}_{self.entry.entry_id}")

    async def change(self, expected, config=None, rollback=None, rebuild=False):
        async with self._lock:
            if expected != self.revision:
                raise StaleRevision(
                    "Instructions changed elsewhere. Reload before saving",
                    self.revision,
                )
            if rebuild:
                await self._persist(
                    self.revision,
                    self.config,
                    self.history,
                    self.rebuild + 1,
                    self.live,
                )
                return self.document()
            if rollback is not None:
                prior = next(
                    (h for h in self.history if h.get("revision") == rollback), None
                )
                if prior is None:
                    raise ValueError("That revision is no longer available")
                config = prior["config"]
            config = validate(config)
            history = (
                self.history
                + [
                    {
                        "revision": self.revision,
                        "config": self.config,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                ]
            )[-KEEP:]
            await self._persist(
                self.revision + 1, config, history, self.rebuild, self.live
            )
            return self.document()

    async def publish(self, expected, live):
        async with self._lock:
            if expected != self.revision:
                raise StaleRevision(
                    "Controller prompt was built from an older configuration",
                    self.revision,
                )
            blocks = live.get("blocks") if isinstance(live, dict) else None
            if not isinstance(blocks, list) or [
                b.get("id") for b in blocks if isinstance(b, dict)
            ] not in (["A", "B"], ["A", "B", "C"]):
                raise ValueError("Publish the controller-built A/B[/C] blocks")
            if len(json.dumps(live)) > 400000:
                raise ValueError("Prompt exceeds the publication limit")
            for block in blocks:
                text = block.get("text")
                if not isinstance(text, str) or hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest() != block.get("hash"):
                    raise ValueError("Prompt block hash does not match its text")
            live = {
                **live,
                "revision": expected,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
            await self._persist(
                self.revision, self.config, self.history, self.rebuild, live
            )
            return {"revision": self.revision, "published": True}


async def async_setup_brain_prompt(hass, entry):
    import voluptuous as vol
    from . import api_v2
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    manager = BrainPromptStore(hass, entry)
    await manager.async_init()
    hass.data.setdefault(DOMAIN, {}).setdefault("_brain_prompt", {})[
        entry.entry_id
    ] = manager

    def handler(action):
        async def handle(call):
            if action != "brain_prompt_get":
                await async_require_admin(
                    hass,
                    call,
                    f"{DOMAIN}.{action}",
                    allow_no_user=action == "brain_prompt_publish",
                )
            managers = hass.data.get(DOMAIN, {}).get("_brain_prompt", {}).values()
            target = next(
                (m for m in managers if m.room_id == call.data["room_id"]), None
            )
            if target is None:
                raise HomeAssistantError("Unknown canonical room_id")
            try:
                if action == "brain_prompt_get":
                    return target.document()
                if action == "brain_prompt_publish":
                    return await target.publish(
                        call.data["expected_revision"], call.data["live"]
                    )
                return await target.change(
                    call.data["expected_revision"],
                    config=call.data.get("config"),
                    rollback=call.data.get("revision"),
                    rebuild=action == "brain_prompt_rebuild",
                )
            except ValueError as error:
                raise HomeAssistantError(str(error)) from error

        return handle

    for action in SERVICES:
        fields = {vol.Required("room_id"): str}
        if action != "brain_prompt_get":
            fields[vol.Required("expected_revision")] = vol.All(int, vol.Range(min=0))
        if action == "brain_prompt_save":
            fields[vol.Required("config")] = dict
        if action == "brain_prompt_rollback":
            fields[vol.Required("revision")] = vol.All(int, vol.Range(min=0))
        if action == "brain_prompt_publish":
            fields[vol.Required("live")] = dict
        hass.services.async_register(
            DOMAIN,
            action,
            api_v2.wrap(handler(action)),
            schema=vol.Schema(api_v2.fields(fields)),
            supports_response=SupportsResponse.OPTIONAL,
        )


async def async_unload_brain_prompt(hass, entry):
    managers = hass.data.get(DOMAIN, {}).get("_brain_prompt", {})
    managers.pop(entry.entry_id, None)
    if not managers:
        for action in SERVICES:
            hass.services.async_remove(DOMAIN, action)
