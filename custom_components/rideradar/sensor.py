"""Sensors for RideRadar."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
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
from .destinations import destinations_from_config
from .models import DestinationResult
from .scoring import calculate_ride_experience


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
            lambda data: _best_attr(data, "ride_quality_score"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="best_ride_quality_score",
                name="Best Ride Quality Score",
                icon="mdi:road-variant",
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            lambda data: _best_attr(data, "ride_quality_score"),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="best_trip_start_day", name="Best Trip Start Day", icon="mdi:calendar-start"),
            lambda data: _best_attr(data, "trip_start_day"),
            lambda data: {
                "date": _best_attr(data, "trip_start_day_iso"),
                "date_display": _best_attr(data, "trip_start_day"),
            },
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
            lambda data: data.get("trip_duration"),
            lambda data: {
                "duration_mode": data.get("duration_mode"),
                "duration_label": data.get("trip_duration_label"),
                "duration_source": data.get("trip_duration_source"),
                "min_duration_days": data.get("min_duration_days"),
                "max_duration_days": data.get("max_duration_days"),
                "selected_duration_days": data.get("selected_duration_days"),
                "best_duration_days": data.get("best_duration_days"),
                "weekend_only": data.get("weekend_only"),
                "preferred_start_weekday": data.get("preferred_start_weekday"),
            },
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
            lambda data: _best_attr(data, "ride_quality_score"),
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
            lambda data: data.get("summary")
            or "Nog geen samenvatting beschikbaar. Controleer of RideRadar al forecast-data heeft opgehaald.",
            lambda data: {
                "active_helpers": data.get("active_helpers", {}),
                "excluded_destinations": data.get("excluded_destinations", []),
                "evaluation_summary": data.get("evaluation_summary", {}),
                "evaluated_candidates": data.get("evaluated_candidates", []),
                "advice_candidate": data.get("advice_candidate"),
                "mode_status": data.get("mode_status", {}),
                "top_exclusion_reason": _top_exclusion_reason(data.get("excluded_destinations")),
                "best_decision_trace": _best_decision_trace(data),
            },
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="evaluation_summary", name="Evaluation Summary", icon="mdi:clipboard-list"),
            lambda data: (data.get("evaluation_summary") or {}).get("total_candidates", 0),
            lambda data: {
                "evaluation_summary": data.get("evaluation_summary", {}),
                "evaluated_candidates": data.get("evaluated_candidates", []),
                "advice_candidate": data.get("advice_candidate"),
                "mode_status": data.get("mode_status", {}),
            },
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="weather_status", name="Weather Status", icon="mdi:cloud-refresh"),
            lambda data: (data.get("weather") or {}).get("weather_status", "unavailable"),
            lambda data: data.get("weather", {}),
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key="best_opportunities", name="Best Opportunities", icon="mdi:calendar-star"),
            lambda data: _opportunity_summary(data.get("opportunities")),
            lambda data: {
                "opportunities": data.get("opportunities", []),
                "excluded_destinations": data.get("excluded_destinations", []),
            },
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="all_opportunities",
                name="All Opportunities",
                icon="mdi:table-search",
                state_class=SensorStateClass.MEASUREMENT,
            ),
            lambda data: len(data.get("all_opportunities") or []),
            lambda data: {
                "opportunities": data.get("all_opportunities", []),
                "candidate_count": data.get("all_opportunities_candidate_count", 0),
                "hidden_below_threshold_count": data.get("all_opportunities_hidden_below_threshold_count", 0),
                "minimum_visible_score": 60,
                "attribute_limit": data.get("all_opportunities_attribute_limit", 100),
            },
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="top_week_opportunities",
                name="Top Week Opportunities",
                icon="mdi:calendar-week",
            ),
            lambda data: _top_opportunity_summary(data.get("top_week_opportunities"))
            or "Geen kansen boven 70 gevonden",
            lambda data: {
                "opportunities": data.get("top_week_opportunities", []),
                "candidate_count": data.get("top_week_candidate_count", 0),
                "rejected_count": data.get("top_week_rejected_count", 0),
                "best_below_threshold": data.get("top_week_best_below_threshold"),
            },
        ),
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(
                key="top_month_opportunities",
                name="Top Month Opportunities",
                icon="mdi:calendar-month",
            ),
            lambda data: _top_opportunity_summary(data.get("top_month_opportunities"))
            or "Geen kansen boven 70 gevonden",
            lambda data: {
                "opportunities": data.get("top_month_opportunities", []),
                "candidate_count": data.get("top_month_candidate_count", 0),
                "rejected_count": data.get("top_month_rejected_count", 0),
                "best_below_threshold": data.get("top_month_best_below_threshold"),
            },
        ),
        *_strategy_top_sensors(entry, coordinator),
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
    for destination in destinations_from_config(coordinator.config):
        entities.append(RideRadarDestinationSensor(entry, coordinator, destination.name))
        entities.append(RideRadarDestinationFutureWindowSensor(entry, coordinator, destination.name))
    async_add_entities(entities)


def _strategy_top_sensors(entry: ConfigEntry, coordinator: RideRadarDataCoordinator) -> list[SensorEntity]:
    descriptions = [
        ("top_week_direct_opportunities", "Top Week Direct Opportunities", "mdi:highway"),
        ("top_week_scenic_opportunities", "Top Week Scenic Opportunities", "mdi:map-marker-path"),
        ("top_forecast_direct_opportunities", "Top Forecast Direct Opportunities", "mdi:highway"),
        ("top_forecast_scenic_opportunities", "Top Forecast Scenic Opportunities", "mdi:map-marker-path"),
    ]
    descriptions.extend(
        [
            ("top_week_trailer_opportunities", "Top Week Trailer Opportunities", "mdi:trailer"),
            ("top_forecast_trailer_opportunities", "Top Forecast Trailer Opportunities", "mdi:trailer"),
        ]
    )
    return [
        RideRadarSensor(
            entry,
            coordinator,
            SensorEntityDescription(key=key, name=name, icon=icon),
            lambda data, data_key=key: _strategy_top_summary(data.get(data_key)),
            lambda data, data_key=key: data.get(data_key, {}),
        )
        for key, name, icon in descriptions
    ]


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
        planning_profile = (self.coordinator.data or {}).get("planning_profile")
        return {
            "trip_score": result.trip_score,
            "ride_quality_score": result.ride_quality_score,
            "ride_experience": _experience_attributes(result),
            "best_future_window": _best_future_window(result, planning_profile),
            "best_trip_window": _trip_window_attributes(result, planning_profile),
            "all_trip_windows": _trip_windows_attributes(result, planning_profile=planning_profile),
            "next_good_window": _next_good_window(result, planning_profile),
            "weekend_windows": _trip_windows_attributes(result, "weekend", planning_profile),
            "weekday_windows": _trip_windows_attributes(result, "weekday", planning_profile),
            "best_start_day": _format_date(result.best_start_day),
            "best_start_day_iso": result.best_start_day,
            "trip_duration": result.trip_duration,
            "duration_mode": (self.coordinator.data or {}).get("duration_mode"),
            "min_duration_days": (self.coordinator.data or {}).get("min_duration_days"),
            "max_duration_days": (self.coordinator.data or {}).get("max_duration_days"),
            "selected_duration_days": (self.coordinator.data or {}).get("selected_duration_days"),
            "best_duration_days": result.trip_duration if result.best_trip_window else None,
            "weather_stability_score": result.weather_stability_score,
            "stability_explanation": result.stability_explanation,
            "daily_scores": result.daily_scores,
            "trip_score_breakdown": _breakdown_attributes(result),
            "score_breakdown": _score_breakdown_attributes(result),
            "trip_explanation": result.trip_explanation,
            "recommendation_reason": _recommendation_reason(result),
            "tradeoffs": _tradeoffs(result),
            "score_per_day": {date: score.score for date, score in result.scores.items()},
            "explanation_per_day": {date: score.explanation for date, score in result.scores.items()},
            "best_day": result.best_day,
            "route_distance_km": route.distance_km if route else None,
            "estimated_travel_time": _format_minutes(route.travel_time_minutes) if route else None,
            "travel_strategy": (self.coordinator.data or {}).get("travel_strategy"),
            "available_hours_per_day": (self.coordinator.data or {}).get("available_hours_per_day"),
            "max_approach_time_hours": (self.coordinator.data or {}).get("max_approach_time_hours"),
            "weekend_only": (self.coordinator.data or {}).get("weekend_only"),
            "preferred_start_weekday": (self.coordinator.data or {}).get("preferred_start_weekday"),
            "temperature": forecast.temperature_c if forecast else None,
            "precipitation_probability": forecast.precipitation_probability if forecast else None,
            "precipitation_amount": forecast.precipitation_amount_mm if forecast else None,
            "wind_speed": forecast.wind_speed_kmh if forecast else None,
            "wind_gusts": forecast.wind_gusts_kmh if forecast else None,
            "cloud_cover": forecast.cloud_cover if forecast else None,
            "weather_code": forecast.weather_code if forecast else None,
            "weather": result.weather or {},
            "reachable": result.reachable,
            "explanation": result.explanation,
            "exclusion_reasons": result.exclusion_reasons,
            "routing_provider": route.provider if route else None,
            "routing_confidence": route.confidence if route else None,
            "routing_distance_method": route.distance_method if route else None,
            "routing_time_method": route.time_method if route else None,
            "direct_distance_km": route.direct_distance_km if route else None,
            "assumed_average_speed_kmh": route.assumed_average_speed_kmh if route else None,
            "detour_factor": route.detour_factor if route else None,
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


class RideRadarDestinationFutureWindowSensor(CoordinatorEntity[RideRadarDataCoordinator], SensorEntity):
    """Per-destination best future riding window sensor."""

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
            key=f"destination_{slug}_best_future_window",
            name=f"{destination_name} Best Future Window",
            icon="mdi:calendar-star",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        )
        self._attr_device_info = _device_info(entry)
        self._attr_unique_id = f"{entry.entry_id}_destination_{slug}_best_future_window"

    @property
    def available(self) -> bool:
        """Return whether this destination has current coordinator data."""
        return super().available and self._result is not None

    @property
    def native_value(self) -> int | None:
        """Return the best future window score."""
        window = self._best_future_window
        if window is None:
            return None
        return int(window["score"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return best future window details."""
        return self._best_future_window or {}

    @property
    def _best_future_window(self) -> dict[str, Any] | None:
        result = self._result
        if result is None:
            return None
        return _best_future_window(result, (self.coordinator.data or {}).get("planning_profile"))

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
    if key == "ride_quality_score":
        return best.ride_quality_score
    if key == "score":
        return best.best_score
    if key == "trip_start_day":
        return _format_date(best.best_start_day)
    if key == "trip_start_day_iso":
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


def _format_hours_human(hours: float | None) -> str:
    """Return a Dutch human-readable duration from decimal hours."""
    if hours is None:
        return "n.v.t."
    total_minutes = int(round(float(hours) * 60))
    whole_hours, minutes = divmod(total_minutes, 60)
    if whole_hours and minutes:
        return f"{whole_hours} uur en {minutes} minuten"
    if whole_hours:
        return f"{whole_hours} uur"
    return f"{minutes} minuten"


def _trip_window_attributes(result: DestinationResult, planning_profile: Any = None) -> dict[str, Any] | None:
    window = result.best_trip_window
    if window is None:
        return None
    return _window_attributes(result, window, planning_profile)


def _trip_windows_attributes(
    result: DestinationResult,
    window_type: str | None = None,
    planning_profile: Any = None,
) -> list[dict[str, Any]]:
    windows = [_window_attributes(result, window, planning_profile) for window in result.all_trip_windows]
    if window_type is None:
        return windows
    return [window for window in windows if window["window_type"] == window_type]


def _next_good_window(result: DestinationResult, planning_profile: Any = None) -> dict[str, Any] | None:
    return next(
        (
            window
            for window in _trip_windows_attributes(result, planning_profile=planning_profile)
            if int(window["ride_quality_score"]) >= 70 and not window["exclusion_reasons"]
        ),
        None,
    )


def _window_attributes(result: DestinationResult, window: Any, planning_profile: Any = None) -> dict[str, Any]:
    route = result.route
    weekend = _is_weekend(window.start_day, window.end_day)
    experience = None
    if route is not None:
        experience = calculate_ride_experience(result.destination, route, window, result.forecasts, planning_profile)
    return {
        "destination": result.destination.name,
        "start_date": window.start_day,
        "end_date": window.end_day,
        "start_date_display": _format_date(window.start_day),
        "end_date_display": _format_date(window.end_day),
        "period": _format_period(window.start_day, window.end_day),
        "start_day": window.start_day,
        "end_day": window.end_day,
        "duration_days": window.duration_days,
        "trip_score": window.trip_score,
        "ride_quality_score": experience.ride_quality_score if experience else window.trip_score,
        "weather_score": experience.weather_score if experience else window.trip_score,
        "stability_score": window.weather_stability_score,
        "traffic_score": experience.traffic_score if experience else None,
        "traffic_level": _pressure_level(experience.traffic_score) if experience else None,
        "tourism_pressure_score": experience.tourism_pressure_score if experience else None,
        "tourism_level": _pressure_level(experience.tourism_pressure_score) if experience else None,
        "holiday_pressure_score": experience.holiday_pressure_score if experience else None,
        "holiday_score": experience.holiday_score if experience else None,
        "access_score": experience.access_score if experience else None,
        "motorcycle_access_score": experience.motorcycle_access_score if experience else None,
        "access_status": _access_status(experience.motorcycle_access_score) if experience else None,
        "distance_score": experience.distance_score if experience else None,
        "temperature_score": experience.temperature_score if experience else None,
        "trip_efficiency_score": experience.trip_efficiency_score if experience else None,
        "score_weights": experience.score_weights if experience else None,
        "score_caps": experience.score_caps if experience else [],
        "recommendation_type": experience.recommendation_type if experience else None,
        "travel_strategy": experience.travel_strategy if experience else None,
        "approach_time_hours": experience.approach_time_hours if experience else None,
        "approach_time_human_readable": _format_hours_human(experience.approach_time_hours) if experience else None,
        "return_time_hours": experience.return_time_hours if experience else None,
        "total_transport_time_hours": experience.total_transport_time_hours if experience else None,
        "total_available_time_hours": experience.total_available_time_hours if experience else None,
        "estimated_destination_ride_time_hours": (
            experience.estimated_destination_ride_time_hours if experience else None
        ),
        "approach_enjoyment_factor": experience.approach_enjoyment_factor if experience else None,
        "destination_ride_time_ratio": experience.destination_ride_time_ratio if experience else None,
        "preferred_max_approach_time_hours": experience.preferred_max_approach_time_hours if experience else None,
        "absolute_max_approach_time_hours": experience.absolute_max_approach_time_hours if experience else None,
        "normal_max_approach_time_hours": experience.normal_max_approach_time_hours if experience else None,
        "joker_max_approach_time_hours": experience.joker_max_approach_time_hours if experience else None,
        "normal_limit_overrun_minutes": experience.normal_limit_overrun_minutes if experience else 0,
        "joker_limit_overrun_minutes": experience.joker_limit_overrun_minutes if experience else 0,
        "approach_time_classification": experience.approach_time_classification if experience else None,
        "approach_time": {
            "hours": experience.approach_time_hours if experience else None,
            "human_readable": _format_hours_human(experience.approach_time_hours) if experience else None,
            "normal_max_hours": experience.normal_max_approach_time_hours if experience else None,
            "joker_max_hours": experience.joker_max_approach_time_hours if experience else None,
            "normal_max": _format_hours_human(experience.normal_max_approach_time_hours) if experience else None,
            "joker_max": _format_hours_human(experience.joker_max_approach_time_hours) if experience else None,
            "classification": experience.approach_time_classification if experience else None,
            "normal_limit_overrun_minutes": experience.normal_limit_overrun_minutes if experience else 0,
            "joker_limit_overrun_minutes": experience.joker_limit_overrun_minutes if experience else 0,
        },
        "preferred_approach_time_overrun_hours": (
            experience.preferred_approach_time_overrun_hours if experience else None
        ),
        "absolute_approach_time_overrun_hours": (
            experience.absolute_approach_time_overrun_hours if experience else None
        ),
        "preference_warnings": experience.preference_warnings if experience else [],
        "hard_exclusion_reasons": experience.hard_exclusion_reasons if experience else [],
        "score_breakdown": _window_score_breakdown(experience, window) if experience else None,
        "recommendation_reason": _window_recommendation_reason(result.destination.name, experience, window)
        if experience
        else window.trip_explanation,
        "tradeoffs": _window_tradeoffs(experience, window) if experience else [],
        "road_fun_score": experience.road_fun_score if experience else None,
        "holiday_names": experience.holiday_names if experience else [],
        "access_notes": experience.access_notes if experience else [],
        "access_warnings": experience.access_warnings if experience else [],
        "known_restrictions": experience.known_restrictions if experience else [],
        "exclusion_reasons": experience.exclusion_reasons if experience else [],
        "days_until": _days_until(window.start_day),
        "daily_scores": window.daily_scores,
        "route_distance_km": route.distance_km if route else None,
        "routing_provider": route.provider if route else None,
        "routing_confidence": route.confidence if route else None,
        "routing_distance_method": route.distance_method if route else None,
        "routing_time_method": route.time_method if route else None,
        "direct_distance_km": route.direct_distance_km if route else None,
        "assumed_average_speed_kmh": route.assumed_average_speed_kmh if route else None,
        "detour_factor": route.detour_factor if route else None,
        "estimated_travel_time": _format_minutes(route.travel_time_minutes) if route else None,
        "verdict": _verdict(experience.ride_quality_score if experience else window.trip_score, weekend),
        "explanation": f"{window.trip_explanation} {experience.explanation}" if experience else window.trip_explanation,
        "window_type": "weekend" if weekend else "weekday",
        "weather_stability_score": window.weather_stability_score,
        "stability_explanation": window.stability_explanation,
    }


def _experience_attributes(result: DestinationResult) -> dict[str, Any] | None:
    experience = result.ride_experience
    if experience is None:
        return None
    return {
        "ride_quality_score": experience.ride_quality_score,
        "weather_score": experience.weather_score,
        "stability_score": result.weather_stability_score,
        "temperature_score": experience.temperature_score,
        "distance_score": experience.distance_score,
        "duration_preference_score": experience.duration_preference_score,
        "trip_efficiency_score": experience.trip_efficiency_score,
        "score_weights": experience.score_weights,
        "score_caps": experience.score_caps,
        "verdict": experience.verdict,
        "recommendation_type": experience.recommendation_type,
        "travel_strategy": experience.travel_strategy,
        "approach_time_hours": experience.approach_time_hours,
        "return_time_hours": experience.return_time_hours,
        "total_transport_time_hours": experience.total_transport_time_hours,
        "total_available_time_hours": experience.total_available_time_hours,
        "estimated_destination_ride_time_hours": experience.estimated_destination_ride_time_hours,
        "approach_enjoyment_factor": experience.approach_enjoyment_factor,
        "destination_ride_time_ratio": experience.destination_ride_time_ratio,
        "holiday_pressure_score": experience.holiday_pressure_score,
        "access_score": experience.access_score,
        "score_breakdown": _score_breakdown_attributes(result),
        "recommendation_reason": _recommendation_reason(result),
        "tradeoffs": _tradeoffs(result),
        "traffic_score": experience.traffic_score,
        "traffic_level": _pressure_level(experience.traffic_score),
        "tourism_pressure_score": experience.tourism_pressure_score,
        "tourism_level": _pressure_level(experience.tourism_pressure_score),
        "holiday_score": experience.holiday_score,
        "motorcycle_access_score": experience.motorcycle_access_score,
        "access_status": _access_status(experience.motorcycle_access_score),
        "road_fun_score": experience.road_fun_score,
        "holiday_names": experience.holiday_names,
        "access_notes": experience.access_notes,
        "access_warnings": experience.access_warnings,
        "known_restrictions": experience.known_restrictions,
        "exclusion_reasons": experience.exclusion_reasons,
        "explanation": experience.explanation,
    }


def _best_future_window(result: DestinationResult, planning_profile: Any = None) -> dict[str, Any] | None:
    windows = [window for window in _trip_windows_attributes(result, planning_profile=planning_profile)]
    if not windows:
        return None
    first = windows[0]
    viable_windows = [window for window in windows if not window["exclusion_reasons"]]
    best = max(viable_windows or windows, key=lambda window: int(window["ride_quality_score"]))
    return {
        "score": best["ride_quality_score"],
        "current_score": first["ride_quality_score"],
        "best_future_score": best["ride_quality_score"],
        "best_future_window": best,
        "ride_quality_score": best["ride_quality_score"],
        "start_date": best["start_date"],
        "end_date": best["end_date"],
        "start_date_display": best["start_date_display"],
        "end_date_display": best["end_date_display"],
        "period": best["period"],
        "duration_days": best["duration_days"],
        "days_until": best["days_until"],
        "explanation": best["explanation"],
        "traffic_level": best["traffic_level"],
        "access_status": best["access_status"],
        "holiday_pressure_score": best["holiday_pressure_score"],
        "access_score": best["access_score"],
        "score_breakdown": best["score_breakdown"],
        "score_weights": best.get("score_weights"),
        "score_caps": best.get("score_caps"),
        "recommendation_reason": best["recommendation_reason"],
        "tradeoffs": best["tradeoffs"],
        "exclusion_reasons": best["exclusion_reasons"],
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


def _top_opportunity_summary(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    return " | ".join(
        f"{index}. {_single_opportunity_summary(opportunity)}" for index, opportunity in enumerate(value[:3], start=1)
    )


def _strategy_top_summary(value: object) -> str:
    if not isinstance(value, dict):
        return "Geen kansen boven 70 gevonden; reden nog niet beschikbaar"
    return _top_opportunity_summary(value.get("opportunities")) or str(
        value.get("empty_reason") or "Geen kansen boven 70 gevonden; reden nog niet beschikbaar"
    )


def _best_decision_trace(data: dict[str, object]) -> dict[str, Any] | None:
    opportunity = data.get("best_next_available_opportunity")
    if not isinstance(opportunity, dict):
        return None
    trace = opportunity.get("decision_trace")
    return trace if isinstance(trace, dict) else None


def _top_exclusion_reason(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if not isinstance(first, dict):
        return None
    return str(first.get("reason")) if first.get("reason") else None


def _single_opportunity_summary(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    period = value.get("period") or _format_period(value.get("start_date"), value.get("end_date"))
    return f"{value.get('destination')} {period}: {value.get('ride_quality_score')}/100"


def _format_date(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return str(value) if str(value).strip() else None
    return f"{_weekday_label(parsed)} {parsed.strftime('%d-%m-%Y')}"


def _format_period(start_value: object, end_value: object) -> str:
    start = _format_date(start_value)
    end = _format_date(end_value)
    if start and end:
        return f"{start} t/m {end}"
    return start or end or "Periode onbekend"


def _score_breakdown_attributes(result: DestinationResult) -> dict[str, int | None] | None:
    experience = result.ride_experience
    window = result.best_trip_window
    if experience is None or window is None:
        return None
    return _window_score_breakdown(experience, window)


def _window_score_breakdown(experience: Any, window: Any) -> dict[str, int]:
    return {
        "weather_score": experience.weather_score,
        "stability_score": window.weather_stability_score,
        "temperature_score": experience.temperature_score,
        "distance_score": experience.distance_score,
        "holiday_pressure_score": experience.holiday_pressure_score,
        "access_score": experience.access_score,
        "trip_efficiency_score": experience.trip_efficiency_score,
        "duration_preference_score": experience.duration_preference_score,
        "ride_quality_score": experience.ride_quality_score,
    }


def _recommendation_reason(result: DestinationResult) -> str | None:
    if result.ride_experience is None or result.best_trip_window is None:
        return result.explanation
    return _window_recommendation_reason(result.destination.name, result.ride_experience, result.best_trip_window)


def _window_recommendation_reason(destination: str, experience: Any, window: Any) -> str:
    if experience.ride_quality_score >= 85:
        quality = "wint omdat het droog, stabiel en praktisch is"
    elif experience.ride_quality_score >= 70:
        quality = "wint door de beste balans tussen weer en praktische ritkwaliteit"
    else:
        quality = "is de minst slechte optie binnen de huidige weersverwachting"
    return (
        f"{destination} {quality}: weer {experience.weather_score}/100, stabiliteit "
        f"{window.weather_stability_score}/100, temperatuur {experience.temperature_score}/100, "
        f"afstand {experience.distance_score}/100, vakantiedruk "
        f"{experience.holiday_pressure_score}/100, toegang {experience.access_score}/100, "
        f"ritefficientie {experience.trip_efficiency_score}/100."
    )


def _tradeoffs(result: DestinationResult) -> list[str]:
    if result.ride_experience is None or result.best_trip_window is None:
        return []
    return _window_tradeoffs(result.ride_experience, result.best_trip_window)


def _window_tradeoffs(experience: Any, window: Any) -> list[str]:
    tradeoffs: list[str] = []
    if experience.weather_score < 80:
        tradeoffs.append(f"Weer scoort {experience.weather_score}/100.")
    if window.weather_stability_score < 80:
        tradeoffs.append(f"Weerstabiliteit scoort {window.weather_stability_score}/100.")
    if experience.temperature_score < 80:
        tradeoffs.append(f"Temperatuur scoort {experience.temperature_score}/100.")
    if experience.distance_score < 80:
        tradeoffs.append(f"Afstand scoort {experience.distance_score}/100.")
    if experience.trip_efficiency_score < 80:
        tradeoffs.append(f"Ritefficientie scoort {experience.trip_efficiency_score}/100.")
    if experience.holiday_pressure_score < 80:
        tradeoffs.append(f"Vakantiedruk scoort {experience.holiday_pressure_score}/100.")
    if experience.access_score < 80:
        tradeoffs.append(f"Toegang scoort {experience.access_score}/100.")
    return tradeoffs or ["Geen grote trade-off gevonden."]


def _weekday_label(value: date) -> str:
    return ("Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo")[value.weekday()]


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
    if score >= 90:
        return f"Excellent{suffix}"
    if score >= 80:
        return f"Very good{suffix}"
    if score >= 70:
        return f"Good{suffix}"
    if score >= 60:
        return f"Mediocre{suffix}"
    if score >= 40:
        return f"Poor{suffix}"
    return f"Not recommended{suffix}"


def _days_until(start_day: str) -> int | None:
    try:
        start = date.fromisoformat(start_day)
    except ValueError:
        return None
    return max(0, (start - datetime.now().date()).days)


def _pressure_level(score: int) -> str:
    if score >= 80:
        return "Low"
    if score >= 60:
        return "Medium"
    if score >= 40:
        return "High"
    return "Severe"


def _access_status(score: int) -> str:
    if score >= 85:
        return "Open"
    if score >= 65:
        return "Partial"
    if score >= 35:
        return "Restricted"
    return "Avoid"
