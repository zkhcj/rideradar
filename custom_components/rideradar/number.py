"""Number controls for RideRadar."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONTROL_AVAILABLE_HOURS_PER_DAY,
    CONTROL_FORECAST_HORIZON_DAYS,
    CONTROL_MAX_APPROACH_TIME_HOURS,
    CONTROL_TRIP_DURATION_DAYS,
    DEFAULT_AVAILABLE_HOURS_PER_DAY,
    DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_MAX_APPROACH_TIME_HOURS,
    DOMAIN,
    MANUFACTURER,
    MAX_FORECAST_DAYS,
    MIN_FORECAST_DAYS,
    MIN_TRIP_DURATION_DAYS,
)
from .coordinator import RideRadarDataCoordinator


@dataclass(frozen=True, slots=True)
class RideRadarNumberDescription:
    """Description for a RideRadar number control."""

    key: str
    name: str
    icon: str
    minimum: float
    maximum: float
    step: float
    default: float
    unit: str | None = None


NUMBERS = (
    RideRadarNumberDescription(
        key=CONTROL_TRIP_DURATION_DAYS,
        name="Trip Duration Days",
        icon="mdi:calendar-range",
        minimum=MIN_TRIP_DURATION_DAYS,
        maximum=MAX_FORECAST_DAYS,
        step=1,
        default=DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
        unit=UnitOfTime.DAYS,
    ),
    RideRadarNumberDescription(
        key=CONTROL_FORECAST_HORIZON_DAYS,
        name="Forecast Horizon Days",
        icon="mdi:calendar-search",
        minimum=MIN_FORECAST_DAYS,
        maximum=MAX_FORECAST_DAYS,
        step=1,
        default=DEFAULT_FORECAST_DAYS,
        unit=UnitOfTime.DAYS,
    ),
    RideRadarNumberDescription(
        key=CONTROL_AVAILABLE_HOURS_PER_DAY,
        name="Available Hours Per Day",
        icon="mdi:clock-outline",
        minimum=1,
        maximum=18,
        step=0.5,
        default=DEFAULT_AVAILABLE_HOURS_PER_DAY,
        unit=UnitOfTime.HOURS,
    ),
    RideRadarNumberDescription(
        key=CONTROL_MAX_APPROACH_TIME_HOURS,
        name="Max Approach Time Hours",
        icon="mdi:map-clock",
        minimum=0.5,
        maximum=12,
        step=0.5,
        default=DEFAULT_MAX_APPROACH_TIME_HOURS,
        unit=UnitOfTime.HOURS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RideRadar number controls."""
    coordinator: RideRadarDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RideRadarNumber(entry, coordinator, description) for description in NUMBERS])


class RideRadarNumber(NumberEntity, RestoreEntity):
    """Restoreable RideRadar number control."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RideRadarDataCoordinator,
        description: RideRadarNumberDescription,
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_name = description.name
        self._attr_icon = description.icon
        self._attr_native_min_value = description.minimum
        self._attr_native_max_value = description.maximum
        self._attr_native_step = description.step
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_info = _device_info(entry)
        self._value = self._default_value()

    async def async_added_to_hass(self) -> None:
        """Restore previous number value."""
        if last_state := await self.async_get_last_state():
            try:
                self._value = self._clamp(float(last_state.state))
            except ValueError:
                pass
        self._coordinator.set_runtime_control(self._description.key, self._value)

    @property
    def native_value(self) -> float:
        """Return current value."""
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        """Set current value."""
        self._value = self._clamp(value)
        self._coordinator.set_runtime_control(self._description.key, self._value)
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()

    def _default_value(self) -> float:
        config = {**self._entry.data, **self._entry.options}
        if self._description.key == CONTROL_TRIP_DURATION_DAYS:
            return self._clamp(float(config.get("custom_trip_duration_days", self._description.default)))
        if self._description.key == CONTROL_FORECAST_HORIZON_DAYS:
            return self._clamp(float(config.get("forecast_days", self._description.default)))
        return self._description.default

    def _clamp(self, value: float) -> float:
        return max(self._description.minimum, min(value, self._description.maximum))


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        name="RideRadar",
        model="Weather destination recommender",
    )
