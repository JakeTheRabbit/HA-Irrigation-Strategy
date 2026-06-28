"""Named-stage recipes for Crop Steering.

A recipe is a small data table (growth stage -> the handful of setpoints that
change by stage). Applying a stage writes that row into the EXISTING per-zone
`number.crop_steering_*` entities the engine already reads — no new per-stage
entities, no engine change. The recipe is stored server-side, per room, via the
HA Store helper, so it survives a restart and an add-on rebuild.

`build_targets` is pure (no HA) so the entity-id / value mapping is unit-tested
offline; `RecipeManager` is the thin IO shell around the Store + service calls.
"""

from __future__ import annotations

import copy
import logging

from .const import (
    DOMAIN,
    CONF_NUM_ZONES,
    RECIPE_STAGES,
    RECIPE_STORAGE_VERSION,
    DEFAULT_RECIPE,
)
from .room import room_prefix

try:  # pragma: no cover - guarded so build_targets imports without HA installed
    from homeassistant.helpers.storage import Store
except ImportError:  # pragma: no cover
    Store = None  # type: ignore

_LOGGER = logging.getLogger(__name__)


def build_targets(stage, recipe, num_zones, prefix=""):
    """Pure: (entity_id, value) pairs to write for `stage`.

    Each recipe param is written to its global entity AND each per-zone copy;
    the caller skips any that don't exist on this install. Engine reads per-zone
    first, global as the template default — writing both keeps them consistent.
    """
    targets = []
    stage_vals = (recipe.get("stages") or {}).get(stage, {})
    for param, val in stage_vals.items():
        targets.append((f"number.{DOMAIN}_{prefix}{param}", val))
        for n in range(1, int(num_zones) + 1):
            targets.append((f"number.{DOMAIN}_{prefix}zone_{n}_{param}", val))
    return targets


class RecipeManager:
    """Per-room recipe: load/seed/save via Store, apply a stage to the numbers."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.recipe = copy.deepcopy(DEFAULT_RECIPE)
        self._store = (
            Store(hass, RECIPE_STORAGE_VERSION, f"{DOMAIN}_recipes_{entry.entry_id}")
            if Store is not None
            else None
        )

    async def async_init(self):
        """Load the stored recipe, or seed the default on first run."""
        if self._store is not None:
            data = await self._store.async_load()
            if data:
                self.recipe = data
            else:
                await self._store.async_save(self.recipe)
        return self

    @property
    def active_stage(self):
        stage = self.recipe.get("active_stage", RECIPE_STAGES[0])
        return stage if stage in RECIPE_STAGES else RECIPE_STAGES[0]

    async def async_save(self, recipe):
        """Replace the whole recipe table (dashboard authoring)."""
        self.recipe = recipe
        if self._store is not None:
            await self._store.async_save(self.recipe)

    async def async_apply(self, stage=None):
        """Write `stage`'s setpoints into the number entities. Returns count written.

        Operator-initiated only; every value is still clamped by each number
        entity's min/max, and the kill switch independently gates actuation.
        """
        stage = stage or self.active_stage
        if stage not in RECIPE_STAGES:
            _LOGGER.warning("crop_steering: unknown recipe stage %s", stage)
            return 0
        num_zones = self.hass.data[DOMAIN][self.entry.entry_id].get(CONF_NUM_ZONES, 1)
        targets = build_targets(stage, self.recipe, num_zones, room_prefix(self.entry))
        applied = 0
        for eid, val in targets:
            if self.hass.states.get(eid) is None:
                continue  # not every param has a per-zone copy on every install
            try:
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": eid, "value": float(val)},
                    blocking=True,
                )
                applied += 1
            except Exception as err:  # pragma: no cover - defensive
                _LOGGER.warning("crop_steering: recipe apply failed for %s: %s", eid, err)
        self.recipe["active_stage"] = stage
        if self._store is not None:
            await self._store.async_save(self.recipe)
        _LOGGER.info(
            "crop_steering: applied recipe stage '%s' to %d entities", stage, applied
        )
        return applied


def get_manager(hass, entry):
    """Fetch the RecipeManager for this entry, if set up."""
    return hass.data.get(DOMAIN, {}).get("_recipe", {}).get(entry.entry_id)
