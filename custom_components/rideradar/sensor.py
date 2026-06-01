"""Sensors for RideRadar."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
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
            SensorEntityDescription(key="best_opportunities", name="Best Opportunities", icon="mdi:calendar-star"),
            lambda data: _opportunity_summary(data.get("opportunities")),
            lambda data: {"opportunities": data.get("opportunities", [])},
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="best_weekend_opportunity",
                name="Best Weekend Opportunity",
                icon="mdi:calendar-weekend",
            ),
            lambda data: _single_opportunity_summary(data.get("best_weekend_opportunity")),
            lambda data: {"opportunity": data.get("best_weekend_opportunity")},
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="best_weekday_opportunity",
                name="Best Weekday Opportunity",
                icon="mdi:calendar-week",
            ),
            lambda data: _single_opportunity_summary(data.get("best_weekday_opportunity")),
            lambda data: {"opportunity": data.get("best_weekday_opportunity")},
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="best_next_available_opportunity",
                name="Best Next Available Opportunity",
                icon="mdi:calendar-clock",
            ),
            lambda data: _single_opportunity_summary(data.get("best_next_available_opportunity")),
            lambda data: {"opportunity": data.get("best_next_available_opportunity")},
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
        attrs_fn: Callable[[dict[str, object]], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info = _device_info(entry)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._value_fn = value_fn
        self._attrs_fn = attrs_fn

    @property
    def native_value(self) -> Any:
        """Return sensor value."""
        return self._value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self._attrs_fn is None:
            return {}
        return self._attrs_fn(self.coordinator.data or {})


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
            "all_trip_windows": _trip_windows_attributes(result),
            "next_good_window": _next_good_window(result),
            "weekend_windows": _trip_windows_attributes(result, "weekend"),
            "weekday_windows": _trip_windows_attributes(result, "weekday"),
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
    return _window_attributes(result, window)


def _trip_windows_attributes(result: DestinationResult, window_type: str | None = None) -> list[dict[str, Any]]:
    windows = [_window_attributes(result, window) for window in result.all_trip_windows]
    if window_type is None:
        return windows
    return [window for window in windows if window["window_type"] == window_type]


def _next_good_window(result: DestinationResult) -> dict[str, Any] | None:
    return next(
        (window for window in _trip_windows_attributes(result) if int(window["trip_score"]) >= 70),
        None,
    )


def _window_attributes(result: DestinationResult, window: Any) -> dict[str, Any]:
    route = result.route
    weekend = _is_weekend(window.start_day, window.end_day)
    return {
        "destination": result.destination.name,
        "start_date": window.start_day,
        "end_date": window.end_day,
        "start_day": window.start_day,
        "end_day": window.end_day,
        "duration_days": window.duration_days,
        "trip_score": window.trip_score,
        "stability_score": window.weather_stability_score,
        "daily_scores": window.daily_scores,
        "route_distance_km": route.distance_km if route else None,
        "estimated_travel_time": _format_minutes(route.travel_time_minutes) if route else None,
        "verdict": _verdict(window.trip_score, weekend),
        "explanation": window.trip_explanation,
        "window_type": "weekend" if weekend else "weekday",
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


def _opportunity_summary(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    return _single_opportunity_summary(value[0])


def _single_opportunity_summary(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    return f"{value.get('destination')} from {value.get('start_date')}: {value.get('trip_score')}/100"


def _is_weekend(start_value: str, end_value: str) -> bool:
    try:
        start = date.fromisoformat(start_value)
        end = date.fromisoformat(end_value)
    except ValueError:
        return False
    days = (end - start).days + 1
    return any((start + timedelta(days=offset)).weekday() >= 5 for offset in range(days))


def _verdict(score: int, weekend: bool) -> str:
    suffix = " weekend" if weekend else " window"
    if score >= 85:
        return f"Excellent{suffix}"
    if score >= 70:
        return f"Good{suffix}"
    if score >= 55:
        return f"Marginal{suffix}"
    return f"Poor{suffix}"
