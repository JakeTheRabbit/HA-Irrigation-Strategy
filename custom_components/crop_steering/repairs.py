"""The Fix button of the max-run latch card (CS-312, health.py): it releases the room's zones the
controller stopped. Every other Crop Steering card is fixed where its cause is, and has no button."""

from __future__ import annotations

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant

from .const import DOMAIN


class MaxRunReset(ConfirmRepairFlow):
    """Confirm, then tell the controller through the room's max-run latch switch."""

    def __init__(self, entry_id) -> None:
        self._entry_id = entry_id

    async def async_step_confirm(self, user_input=None):
        if user_input is not None:
            switch = self.hass.data.get(DOMAIN, {}).get("_max_run_latch", {})
            switch = switch.get(self._entry_id)
            if switch is None:
                return self.async_abort(reason="room_not_loaded")
            switch.reset_latch()
        return await super().async_step_confirm(user_input)


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None
) -> RepairsFlow:
    return MaxRunReset((data or {}).get("entry_id"))
