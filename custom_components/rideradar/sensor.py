"""Sensors for RideRadar."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import RideRadarDataCoordinator
from .models import DestinationResult


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RideRadar sensor entities."""
    coordinator: RideRadarDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="best_destination", name="Best Destination", icon="mdi:map-marker-star"),
            lambda data: _best_attr(data, "name"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="best_trip_destination",
                name="Best Trip Destination",
                icon="mdi:map-marker-star",
            ),
            lambda data: _best_attr(data, "name"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="best_trip_score",
                name="Best Trip Score",
                icon="mdi:weather-sunny-alert",
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            lambda data: _best_attr(data, "trip_score"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="best_trip_start_day", name="Best Trip Start Day", icon="mdi:calendar-start"),
            lambda data: _best_attr(data, "trip_start_day"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="trip_duration",
                name="Trip Duration",
                icon="mdi:calendar-range",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            lambda data: _best_attr(data, "trip_duration"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="best_score",
                name="Best Score",
                icon="mdi:weather-sunny-alert",
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            lambda data: _best_attr(data, "trip_score"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="best_day", name="Best Day", icon="mdi:calendar-check"),
            lambda data: _best_attr(data, "trip_start_day"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="best_summary", name="Best Summary", icon="mdi:text-box-check"),
            lambda data: data.get("summary"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="destination_count",
                name="Destination Count",
                icon="mdi:map-marker-multiple",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            lambda data: data.get("destination_count"),
        ),
    ]
    for result in coordinator.data.get("results", []) if coordinator.data else []:
        if isinstance(result, DestinationResult):
            entities.append(RideRadarDestinationSensor(entry, coordinator, result.destination.name))
    async_add_entities(entities)


class RideRadarSensor(CoordinatorEntity[RideRadarDataCoordinator], SensorEntity):
    """Generic RideRadar summary sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RideRadarDataCoordinator,
        description: SensorEntityDescription,
        value_fn: Callable[[dict[str, object]], Any],
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info = _device_info(entry)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._value_fn = value_fn

    @property
    def native_value(self) -> Any:
        """Return sensor value."""
        return self._value_fn(self.coordinator.data or {})


class RideRadarDestinationSensor(CoordinatorEntity[RideRadarDataCoordinator], SensorEntity):
    """Per-destination RideRadar sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: RideRadarDataCoordinator,
        destination_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._destination_name = destination_name
        slug = slugify(destination_name)
        self.entity_description = SensorEntityDescription(
            key=f"destination_{slug}",
            name=destination_name,
            icon="mdi:map-marker-distance",
            device_class=SensorDeviceClass.DISTANCE,
            native_unit_of_measurement=UnitOfLength.KILOMETERS,
            state_class=SensorStateClass.MEASUREMENT,
        )
        self._attr_device_info = _device_info(entry)
        self._attr_unique_id = f"{entry.entry_id}_destination_{slug}"

    @property
    def available(self) -> bool:
        """Return whether this destination has current coordinator data."""
        return super().available and self._result is not None

    @property
    def native_value(self) -> float | None:
        """Return route distance for this destination."""
        result = self._result
        if result is None or result.route is None:
            return None
        return result.route.distance_km

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return destination attributes."""
        result = self._result
        if result is None:
            return {}
        forecast = result.best_forecast
        route = result.route
        return {
            "trip_score": result.trip_score,
            "best_trip_window": _trip_window_attributes(result),
            "best_start_day": result.best_start_day,
            "trip_duration": result.trip_duration,
            "weather_stability_score": result.weather_stability_score,
            "stability_explanation": result.stability_explanation,
            "daily_scores": result.daily_scores,
            "trip_score_breakdown": _breakdown_attributes(result),
            "trip_explanation": result.trip_explanation,
            "score_per_day": {date: score.score for date, score in result.scores.items()},
            "explanation_per_day": {date: score.explanation for date, score in result.scores.items()},
            "best_day": result.best_day,
            "route_distance_km": route.distance_km if route else None,
            "estimated_travel_time": _format_minutes(route.travel_time_minutes) if route else None,
            "temperature": forecast.temperature_c if forecast else None,
            "precipitation_probability": forecast.precipitation_probability if forecast else None,
            "precipitation_amount": forecast.precipitation_amount_mm if forecast else None,
            "wind_speed": forecast.wind_speed_kmh if forecast else None,
            "wind_gusts": forecast.wind_gusts_kmh if forecast else None,
            "cloud_cover": forecast.cloud_cover if forecast else None,
            "weather_code": forecast.weather_code if forecast else None,
            "reachable": result.reachable,
            "explanation": result.explanation,
            "routing_provider": route.provider if route else None,
            "country_region": result.destination.country_region,
            "notes": result.destination.notes,
            "preferred_route_target_address": result.destination.preferred_route_target_address,
        }

    @property
    def _result(self) -> DestinationResult | None:
        for result in (self.coordinator.data or {}).get("results", []):
            if isinstance(result, DestinationResult) and result.destination.name == self._destination_name:
                return result
        return None


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        name="RideRadar",
        model="Weather destination recommender",
    )


def _best_attr(data: dict[str, object], key: str) -> Any:
    best = data.get("best")
    if not isinstance(best, DestinationResult):
        return None
    if key == "name":
        return best.destination.name
    if key == "trip_score":
        return best.trip_score
    if key == "score":
        return best.best_score
    if key == "trip_start_day":
        return best.best_start_day
    if key == "trip_duration":
        return best.trip_duration
    if key == "day":
        return best.best_day
    return None


def _format_minutes(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if hours:
        return f"{hours}h {remainder:02d}m"
    return f"{remainder}m"


def _trip_window_attributes(result: DestinationResult) -> dict[str, Any] | None:
    window = result.best_trip_window
    if window is None:
        return None
    return {
        "start_day": window.start_day,
        "end_day": window.end_day,
        "duration_days": window.duration_days,
        "trip_score": window.trip_score,
        "daily_scores": window.daily_scores,
        "weather_stability_score": window.weather_stability_score,
        "stability_explanation": window.stability_explanation,
    }


def _breakdown_attributes(result: DestinationResult) -> dict[str, Any] | None:
    breakdown = result.trip_score_breakdown
    if breakdown is None:
        return None
    return {
        "average_daily_score": breakdown.average_daily_score,
        "worst_daily_score": breakdown.worst_daily_score,
        "weather_stability_score": breakdown.weather_stability_score,
        "bad_weather_penalty": breakdown.bad_weather_penalty,
        "duration_days": breakdown.duration_days,
    }
