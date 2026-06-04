"""Select controls for RideRadar."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONTROL_PREFERRED_START_DAY,
    CONTROL_TRAVEL_STRATEGY,
    CONTROL_TRIP_DURATION,
    DEFAULT_PREFERRED_TRIP_DURATION,
    DEFAULT_TRAVEL_STRATEGY,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import RideRadarDataCoordinator


@dataclass(frozen=True, slots=True)
class RideRadarSelectDescription:
    """Description for a RideRadar select control."""

    key: str
    name: str
    icon: str
    options: list[str]
    default: str


SELECTS = (
    RideRadarSelectDescription(
        key=CONTROL_TRIP_DURATION,
        name="Trip Duration",
        icon="mdi:calendar-range",
        options=["1 day", "2 days", "3 days", "flexible", "custom"],
        default="2 days",
    ),
    RideRadarSelectDescription(
        key=CONTROL_PREFERRED_START_DAY,
        name="Preferred Start Day",
        icon="mdi:calendar-start",
        options=["any", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        default="any",
    ),
    RideRadarSelectDescription(
        key=CONTROL_TRAVEL_STRATEGY,
        name="Travel Strategy",
        icon="mdi:map-marker-path",
        options=["Motorcycle Direct", "Motorcycle Scenic Approach", "Trailer Transport"],
        default="Motorcycle Direct",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RideRadar select controls."""
    coordinator: RideRadarDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RideRadarSelect(entry, coordinator, description) for description in SELECTS])


class RideRadarSelect(SelectEntity, RestoreEntity):
    """Restoreable RideRadar select control."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RideRadarDataCoordinator,
        description: RideRadarSelectDescription,
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_options = description.options
        self._attr_device_info = _device_info(entry)
        self._current_option = self._default_option()

    async def async_added_to_hass(self) -> None:
        """Restore previous selected option."""
        if (last_state := await self.async_get_last_state()) and last_state.state in self.options:
            self._current_option = last_state.state
        self._coordinator.set_runtime_control(self._description.key, self._current_option)

    @property
    def current_option(self) -> str:
        """Return selected option."""
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        """Set selected option."""
        if option not in self.options:
            return
        self._current_option = option
        self._coordinator.set_runtime_control(self._description.key, option)
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()

    def _default_option(self) -> str:
        if self._description.key == CONTROL_TRIP_DURATION:
            preferred = str(
                {**self._entry.data, **self._entry.options}.get(
                    "preferred_trip_duration",
                    DEFAULT_PREFERRED_TRIP_DURATION,
                )
            )
            return {
                "1": "1 day",
                "2": "2 days",
                "3": "3 days",
                "flexible": "flexible",
                "custom": "custom",
            }.get(preferred, self._description.default)
        if self._description.key == CONTROL_TRAVEL_STRATEGY:
            return {
                "motorcycle_direct": "Motorcycle Direct",
                "motorcycle_scenic": "Motorcycle Scenic Approach",
                "trailer": "Trailer Transport",
            }.get(str(self._entry.options.get("travel_strategy", DEFAULT_TRAVEL_STRATEGY)), self._description.default)
        return self._description.default


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        name="RideRadar",
        model="Weather destination recommender",
    )
