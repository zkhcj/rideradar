"""Diagnostics support for RideRadar."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import diagnostics as diag

from .const import CONF_START_ADDRESS, DOMAIN

TO_REDACT = {CONF_START_ADDRESS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = getattr(coordinator, "data", None) or {}
    return {
        "entry": {
            "data": diag.async_redact_data(entry.data, TO_REDACT),
            "options": diag.async_redact_data(entry.options, TO_REDACT),
        },
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "destination_count": data.get("destination_count"),
            "summary": data.get("summary"),
        },
    }
