"""Switch controls for RideRadar."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONTROL_TRAILER_AVAILABLE, CONTROL_WEEKEND_ONLY, DOMAIN, MANUFACTURER
from .coordinator import RideRadarDataCoordinator


@dataclass(frozen=True, slots=True)
class RideRadarSwitchDescription:
    """Description for a RideRadar switch control."""

    key: str
    name: str
    icon: str
    default: bool = False


SWITCHES = (
    RideRadarSwitchDescription(
        key=CONTROL_WEEKEND_ONLY,
        name="Weekend Only",
        icon="mdi:calendar-weekend",
    ),
    RideRadarSwitchDescription(
        key=CONTROL_TRAILER_AVAILABLE,
        name="Trailer Available",
        icon="mdi:trailer",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RideRadar switch controls."""
    coordinator: RideRadarDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RideRadarSwitch(entry, coordinator, description) for description in SWITCHES])


class RideRadarSwitch(SwitchEntity, RestoreEntity):
    """Restoreable RideRadar switch control."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RideRadarDataCoordinator,
        description: RideRadarSwitchDescription,
    ) -> None:
        self._coordinator = coordinator
        self._description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_device_info = _device_info(entry)
        self._attr_is_on = description.default

    async def async_added_to_hass(self) -> None:
        """Restore previous switch value."""
        if last_state := await self.async_get_last_state():
            self._attr_is_on = last_state.state == "on"
        self._coordinator.set_runtime_control(self._description.key, "on" if self.is_on else "off")

    async def async_turn_on(self, **kwargs: object) -> None:
        """Turn control on."""
        self._attr_is_on = True
        self._coordinator.set_runtime_control(self._description.key, "on")
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        """Turn control off."""
        self._attr_is_on = False
        self._coordinator.set_runtime_control(self._description.key, "off")
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        name="RideRadar",
        model="Weather destination recommender",
    )
