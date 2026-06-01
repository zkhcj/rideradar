"""RideRadar integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OpenMeteoClient
from .const import (
    CONF_CUSTOM_DESTINATIONS,
    CONF_DESTINATIONS,
    CONF_ENABLED_DEFAULT_DESTINATIONS,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import RideRadarDataCoordinator
from .destinations import DEFAULT_DESTINATIONS, default_destination_names, parse_destinations_data


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RideRadar from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = RideRadarDataCoordinator(
        hass,
        entry,
        OpenMeteoClient(async_get_clientsession(hass)),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload RideRadar."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.data.pop(DOMAIN, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy raw destination JSON config to structured destination data."""
    if entry.version >= 2 and CONF_DESTINATIONS not in entry.data:
        return True

    data = dict(entry.data)
    default_names = set(default_destination_names())
    try:
        legacy_destinations = parse_destinations_data(data.pop(CONF_DESTINATIONS, None))
    except (ValueError, TypeError):
        legacy_destinations = list(DEFAULT_DESTINATIONS)

    enabled_defaults = [
        destination.name
        for destination in legacy_destinations
        if destination.enabled and destination.name in default_names
    ]
    custom = [destination.as_dict() for destination in legacy_destinations if destination.name not in default_names]
    data.setdefault(CONF_ENABLED_DEFAULT_DESTINATIONS, enabled_defaults or default_destination_names())
    data.setdefault(CONF_CUSTOM_DESTINATIONS, custom)
    hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
