"""Data coordinator for RideRadar."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OpenMeteoClient, RideRadarApiError
from .const import (
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DETOUR_FACTOR,
    CONF_DURATION_MODE,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    CONF_TRAILER_SUPPORT_ENABLED,
    CONTROL_AVAILABLE_HOURS_PER_DAY,
    CONTROL_FORECAST_HORIZON_DAYS,
    CONTROL_MAX_APPROACH_TIME_HOURS,
    CONTROL_PREFERRED_START_DAY,
    CONTROL_TRAILER_AVAILABLE,
    CONTROL_TRAVEL_STRATEGY,
    CONTROL_TRIP_DURATION,
    CONTROL_TRIP_DURATION_DAYS,
    CONTROL_WEEKEND_ONLY,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_AVAILABLE_HOURS_PER_DAY,
    DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
    DEFAULT_DETOUR_FACTOR,
    DEFAULT_DURATION_MODE,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_MAX_APPROACH_TIME_HOURS,
    DEFAULT_MAX_ROUTE_DISTANCE_KM,
    DEFAULT_PREFERRED_TRIP_DURATION,
    DEFAULT_TRAILER_SUPPORT_ENABLED,
    DEFAULT_TRAVEL_STRATEGY,
    DOMAIN,
    MAX_FORECAST_DAYS,
    MIN_TRIP_DURATION_DAYS,
    TRAVEL_STRATEGY_MOTORCYCLE_DIRECT,
    TRAVEL_STRATEGY_MOTORCYCLE_SCENIC,
    TRAVEL_STRATEGY_OPTIONS,
    TRAVEL_STRATEGY_TRAILER,
    UPDATE_INTERVAL,
)
from .destinations import all_destinations_for_options, destinations_from_config
from .models import DestinationArea, DestinationResult, RideRadarConfigError
from .routing import FallbackRoutingClient, RoutingClient
from .scoring import (
    TripPlanningProfile,
    calculate_ride_experience,
    calculate_ride_score,
    calculate_variable_trip_windows,
    ride_verdict,
)

LOGGER = logging.getLogger(__name__)

CoordinatorData = dict[str, Any]

TRIP_DURATION_NUMBER_ENTITY = "input_number.rideradar_trip_duration_days"
TRIP_DURATION_SELECT_ENTITY = "input_select.rideradar_trip_duration"
NATIVE_TRIP_DURATION_NUMBER_ENTITY = "number.rideradar_trip_duration_days"
NATIVE_TRIP_DURATION_SELECT_ENTITY = "select.rideradar_trip_duration"
TRAVEL_STRATEGY_SELECT_ENTITY = "input_select.rideradar_travel_strategy"
NATIVE_TRAVEL_STRATEGY_SELECT_ENTITY = "select.rideradar_travel_strategy"
TRAILER_AVAILABLE_ENTITY = "input_boolean.rideradar_trailer_available"
NATIVE_TRAILER_AVAILABLE_ENTITY = "switch.rideradar_trailer_available"
AVAILABLE_HOURS_ENTITY = "input_number.rideradar_available_hours_per_day"
NATIVE_AVAILABLE_HOURS_ENTITY = "number.rideradar_available_hours_per_day"
MAX_APPROACH_TIME_ENTITY = "input_number.rideradar_max_approach_time_hours"
NATIVE_MAX_APPROACH_TIME_ENTITY = "number.rideradar_max_approach_time_hours"
FORECAST_HORIZON_ENTITY = "input_number.rideradar_forecast_horizon_days"
NATIVE_FORECAST_HORIZON_ENTITY = "number.rideradar_forecast_horizon_days"
WEEKEND_ONLY_ENTITY = "input_boolean.rideradar_weekend_only"
NATIVE_WEEKEND_ONLY_ENTITY = "switch.rideradar_weekend_only"
PREFERRED_START_DAY_ENTITY = "input_select.rideradar_preferred_start_day"
NATIVE_PREFERRED_START_DAY_ENTITY = "select.rideradar_preferred_start_day"

NATIVE_CONTROL_ENTITIES = {
    CONTROL_TRIP_DURATION: NATIVE_TRIP_DURATION_SELECT_ENTITY,
    CONTROL_TRIP_DURATION_DAYS: NATIVE_TRIP_DURATION_NUMBER_ENTITY,
    CONTROL_FORECAST_HORIZON_DAYS: NATIVE_FORECAST_HORIZON_ENTITY,
    CONTROL_PREFERRED_START_DAY: NATIVE_PREFERRED_START_DAY_ENTITY,
    CONTROL_WEEKEND_ONLY: NATIVE_WEEKEND_ONLY_ENTITY,
    CONTROL_TRAVEL_STRATEGY: NATIVE_TRAVEL_STRATEGY_SELECT_ENTITY,
    CONTROL_TRAILER_AVAILABLE: NATIVE_TRAILER_AVAILABLE_ENTITY,
    CONTROL_AVAILABLE_HOURS_PER_DAY: NATIVE_AVAILABLE_HOURS_ENTITY,
    CONTROL_MAX_APPROACH_TIME_HOURS: NATIVE_MAX_APPROACH_TIME_ENTITY,
}

ALL_OPPORTUNITIES_MIN_SCORE = 60
ALL_OPPORTUNITIES_ATTRIBUTE_LIMIT = 100
ALL_OPPORTUNITIES_DEFAULT_MIN_DURATION = 2
ALL_OPPORTUNITIES_DEFAULT_MAX_DURATION = 4
COMING_WEEK_DAYS = 8
TOP_STRATEGY_OPPORTUNITY_KEYS = (
    ("top_week_direct_opportunities", TRAVEL_STRATEGY_MOTORCYCLE_DIRECT, COMING_WEEK_DAYS),
    ("top_week_scenic_opportunities", TRAVEL_STRATEGY_MOTORCYCLE_SCENIC, COMING_WEEK_DAYS),
    ("top_week_trailer_opportunities", TRAVEL_STRATEGY_TRAILER, COMING_WEEK_DAYS),
    ("top_forecast_direct_opportunities", TRAVEL_STRATEGY_MOTORCYCLE_DIRECT, None),
    ("top_forecast_scenic_opportunities", TRAVEL_STRATEGY_MOTORCYCLE_SCENIC, None),
    ("top_forecast_trailer_opportunities", TRAVEL_STRATEGY_TRAILER, None),
)


@dataclass(frozen=True, slots=True)
class TripDurationSelection:
    """Resolved trip duration settings for this refresh."""

    mode: str
    min_days: int
    max_days: int
    source: str

    @property
    def label(self) -> str:
        if self.mode == "flexible":
            return f"{self.min_days}-{self.max_days} days"
        return f"{self.max_days} day" if self.max_days == 1 else f"{self.max_days} days"


@dataclass(frozen=True, slots=True)
class WindowPreferences:
    """Runtime filters for candidate trip windows."""

    weekend_only: bool = False
    preferred_start_weekday: int | None = None


class RideRadarDataCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Fetch route and forecast data, then calculate destination rankings."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api_client: OpenMeteoClient,
        routing_client: RoutingClient | None = None,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.entry = entry
        self.api_client = api_client
        self.runtime_controls: dict[str, str] = {}
        self.routing_client = routing_client or FallbackRoutingClient(
            detour_factor=float(self.config.get(CONF_DETOUR_FACTOR, DEFAULT_DETOUR_FACTOR))
        )

    @property
    def config(self) -> dict[str, Any]:
        """Return merged config entry data and options."""
        return {**self.entry.data, **self.entry.options}

    def set_runtime_control(self, key: str, value: Any) -> None:
        """Store the latest native control value for scoring precedence."""
        self.runtime_controls[key] = str(value)

    def _trip_duration_selection(self, config: dict[str, Any], forecast_days: int) -> TripDurationSelection:
        return _trip_duration_selection(config, forecast_days, self.hass, self.runtime_controls)

    def _forecast_days_selection(self, config: dict[str, Any]) -> int:
        return _forecast_days_selection(config, self.hass, self.runtime_controls)

    def _trip_planning_profile(self, config: dict[str, Any]) -> TripPlanningProfile:
        return _trip_planning_profile(config, self.hass, self.runtime_controls)

    def _window_preferences(self) -> WindowPreferences:
        return _window_preferences(self.hass, self.runtime_controls)

    def _active_helper_states(self) -> dict[str, str | None]:
        return _active_helper_states(self.hass, self.runtime_controls)

    def unavailable_data(
        self,
        message: str = "De weerservice is tijdelijk niet beschikbaar. RideRadar probeert het automatisch opnieuw.",
    ) -> CoordinatorData:
        """Return safe coordinator data for startup or temporary provider failures."""
        config = self.config
        try:
            forecast_days = self._forecast_days_selection(config)
            trip_duration = self._trip_duration_selection(config, forecast_days)
            planning_profile = self._trip_planning_profile(config)
            window_preferences = self._window_preferences()
            active_helpers = self._active_helper_states()
            disabled_destinations = _disabled_destinations(config)
        except (KeyError, TypeError, ValueError, RideRadarConfigError):
            forecast_days = DEFAULT_FORECAST_DAYS
            trip_duration = TripDurationSelection(
                mode=DEFAULT_DURATION_MODE,
                min_days=MIN_TRIP_DURATION_DAYS,
                max_days=DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
                source="safe_default",
            )
            planning_profile = TripPlanningProfile()
            window_preferences = WindowPreferences()
            active_helpers = {}
            disabled_destinations = []
        return {
            "results": [],
            "best": None,
            "opportunities": [],
            "all_opportunities": [],
            "all_opportunities_candidate_count": 0,
            "all_opportunities_hidden_below_threshold_count": 0,
            "all_opportunities_attribute_limit": ALL_OPPORTUNITIES_ATTRIBUTE_LIMIT,
            "top_week_opportunities": [],
            "top_month_opportunities": [],
            **_empty_strategy_top_data(),
            "top_week_candidate_count": 0,
            "top_week_rejected_count": 0,
            "top_week_best_below_threshold": None,
            "top_month_candidate_count": 0,
            "top_month_rejected_count": 0,
            "top_month_best_below_threshold": None,
            "best_weekend_opportunity": None,
            "best_weekday_opportunity": None,
            "best_next_available_opportunity": None,
            "destination_count": 0,
            "summary": message,
            "forecast_status": "temporarily_unavailable",
            "forecast_status_message": message,
            "excluded_destinations": disabled_destinations,
            "duration_mode": trip_duration.mode,
            "trip_duration": trip_duration.max_days,
            "trip_duration_label": trip_duration.label,
            "trip_duration_source": trip_duration.source,
            "min_duration_days": trip_duration.min_days,
            "max_duration_days": trip_duration.max_days,
            "selected_duration_days": trip_duration.max_days,
            "best_duration_days": None,
            "forecast_horizon_days": forecast_days,
            "planning_profile": planning_profile,
            "travel_strategy": planning_profile.travel_strategy,
            "available_hours_per_day": planning_profile.available_hours_per_day,
            "max_approach_time_hours": planning_profile.max_approach_time_hours,
            "trailer_available": planning_profile.trailer_available,
            "weekend_only": window_preferences.weekend_only,
            "preferred_start_weekday": window_preferences.preferred_start_weekday,
            "active_helpers": active_helpers,
        }

    async def _async_update_data(self) -> CoordinatorData:
        """Refresh route and forecast data."""
        config = self.config
        try:
            start_latitude = float(config[CONF_START_LATITUDE])
            start_longitude = float(config[CONF_START_LONGITUDE])
            max_route_distance_km = float(config.get(CONF_MAX_ROUTE_DISTANCE_KM, DEFAULT_MAX_ROUTE_DISTANCE_KM))
            forecast_days = self._forecast_days_selection(config)
            trip_duration = self._trip_duration_selection(config, forecast_days)
            planning_profile = self._trip_planning_profile(config)
            window_preferences = self._window_preferences()
            active_helpers = self._active_helper_states()
            activity_profile = str(config.get(CONF_ACTIVITY_PROFILE, DEFAULT_ACTIVITY_PROFILE))
            destinations = destinations_from_config(config)
        except (KeyError, TypeError, ValueError, RideRadarConfigError) as err:
            raise UpdateFailed(f"Invalid RideRadar configuration: {err}") from err

        enabled_destinations = [destination for destination in destinations if destination.enabled]
        disabled_destinations = _disabled_destinations(config)
        if not enabled_destinations:
            return {
                "results": [],
                "best": None,
                "opportunities": [],
                "all_opportunities": [],
                "all_opportunities_candidate_count": 0,
                "all_opportunities_hidden_below_threshold_count": 0,
                "all_opportunities_attribute_limit": ALL_OPPORTUNITIES_ATTRIBUTE_LIMIT,
                "top_week_opportunities": [],
                "top_month_opportunities": [],
                **_empty_strategy_top_data(),
                "top_week_candidate_count": 0,
                "top_week_rejected_count": 0,
                "top_week_best_below_threshold": None,
                "top_month_candidate_count": 0,
                "top_month_rejected_count": 0,
                "top_month_best_below_threshold": None,
                "best_weekend_opportunity": None,
                "best_weekday_opportunity": None,
                "best_next_available_opportunity": None,
                "destination_count": 0,
                "summary": "No enabled destinations configured",
                "excluded_destinations": disabled_destinations,
                "duration_mode": trip_duration.mode,
                "trip_duration": trip_duration.max_days,
                "trip_duration_label": trip_duration.label,
                "trip_duration_source": trip_duration.source,
                "min_duration_days": trip_duration.min_days,
                "max_duration_days": trip_duration.max_days,
                "selected_duration_days": trip_duration.max_days,
                "best_duration_days": None,
                "planning_profile": planning_profile,
                "travel_strategy": planning_profile.travel_strategy,
                "available_hours_per_day": planning_profile.available_hours_per_day,
                "max_approach_time_hours": planning_profile.max_approach_time_hours,
                "trailer_available": planning_profile.trailer_available,
                "weekend_only": window_preferences.weekend_only,
                "preferred_start_weekday": window_preferences.preferred_start_weekday,
                "active_helpers": active_helpers,
            }

        results: list[DestinationResult] = []
        try:
            for destination in enabled_destinations:
                results.append(
                    await self._evaluate_destination(
                        destination,
                        start_latitude,
                        start_longitude,
                        max_route_distance_km,
                        forecast_days,
                        trip_duration,
                        planning_profile,
                        window_preferences,
                        activity_profile,
                    )
                )
        except RideRadarApiError as err:
            raise UpdateFailed(
                "Forecast provider is temporarily unavailable. RideRadar will retry automatically."
            ) from err
        except (TimeoutError, OSError, ValueError) as err:
            raise UpdateFailed(f"Could not update RideRadar data: {err}") from err

        best = max(
            (
                result
                for result in results
                if result.available and result.reachable and result.ride_quality_score is not None
            ),
            key=lambda item: item.ride_quality_score or 0,
            default=None,
        )
        opportunities = _ranked_opportunities(
            _opportunities(
                results,
                planning_profile,
                config,
                forecast_days,
                trip_duration,
                window_preferences,
                active_helpers,
            )
        )
        all_opportunities = _ranked_opportunities(
            _all_opportunities(
                results,
                planning_profile,
                config,
                forecast_days,
                trip_duration,
                window_preferences,
                active_helpers,
            )
        )
        visible_all_opportunities = _table_opportunities(all_opportunities)
        strategy_top_opportunities = _strategy_top_opportunity_data(all_opportunities)
        top_week = _top_opportunities(opportunities, max_days_until=COMING_WEEK_DAYS)
        top_month = _top_opportunities(opportunities)
        top_week_stats = _top_opportunity_stats(opportunities, max_days_until=COMING_WEEK_DAYS)
        top_month_stats = _top_opportunity_stats(opportunities)
        excluded_destinations = _excluded_destinations(results) + disabled_destinations
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "RideRadar calculated %s candidate windows across %s destinations. "
                "Best: %s. Excluded: %s destinations.",
                len(opportunities),
                len(results),
                _best_debug_summary(best),
                len(excluded_destinations),
            )
        return {
            "results": results,
            "best": best,
            "opportunities": opportunities,
            "all_opportunities": visible_all_opportunities,
            "all_opportunities_candidate_count": len(all_opportunities),
            "all_opportunities_hidden_below_threshold_count": max(
                0, len(all_opportunities) - len(visible_all_opportunities)
            ),
            "all_opportunities_attribute_limit": ALL_OPPORTUNITIES_ATTRIBUTE_LIMIT,
            "top_week_opportunities": top_week,
            "top_month_opportunities": top_month,
            **strategy_top_opportunities,
            "top_week_candidate_count": top_week_stats["candidate_count"],
            "top_week_rejected_count": top_week_stats["rejected_count"],
            "top_week_best_below_threshold": top_week_stats["best_below_threshold"],
            "top_month_candidate_count": top_month_stats["candidate_count"],
            "top_month_rejected_count": top_month_stats["rejected_count"],
            "top_month_best_below_threshold": top_month_stats["best_below_threshold"],
            "excluded_destinations": excluded_destinations,
            "best_weekend_opportunity": _best_matching_opportunity(opportunities, "weekend"),
            "best_weekday_opportunity": _best_matching_opportunity(opportunities, "weekday"),
            "best_next_available_opportunity": opportunities[0] if opportunities else None,
            "destination_count": len(results),
            "summary": _summary(best),
            "duration_mode": trip_duration.mode,
            "trip_duration": best.trip_duration if best else trip_duration.max_days,
            "trip_duration_label": trip_duration.label,
            "trip_duration_source": trip_duration.source,
            "min_duration_days": trip_duration.min_days,
            "max_duration_days": trip_duration.max_days,
            "selected_duration_days": trip_duration.max_days,
            "best_duration_days": best.trip_duration if best else None,
            "planning_profile": planning_profile,
            "travel_strategy": planning_profile.travel_strategy,
            "available_hours_per_day": planning_profile.available_hours_per_day,
            "max_approach_time_hours": planning_profile.max_approach_time_hours,
            "trailer_available": planning_profile.trailer_available,
            "weekend_only": window_preferences.weekend_only,
            "preferred_start_weekday": window_preferences.preferred_start_weekday,
            "active_helpers": active_helpers,
        }

    async def _evaluate_destination(
        self,
        destination: DestinationArea,
        start_latitude: float,
        start_longitude: float,
        max_route_distance_km: float,
        forecast_days: int,
        trip_duration: TripDurationSelection,
        planning_profile: TripPlanningProfile,
        window_preferences: WindowPreferences,
        activity_profile: str,
    ) -> DestinationResult:
        """Evaluate route and forecast for one destination."""
        route = await self.routing_client.get_route(
            start_latitude,
            start_longitude,
            destination,
            activity_profile,
        )
        if route.distance_km > max_route_distance_km:
            return DestinationResult(
                destination=destination,
                route=route,
                forecasts=[],
                scores={},
                best_day=None,
                best_score=None,
                best_forecast=None,
                trip_score=None,
                best_trip_window=None,
                best_start_day=None,
                trip_duration=trip_duration.max_days,
                weather_stability_score=None,
                stability_explanation="Er is geen volledig ritvenster beschikbaar.",
                daily_scores={},
                trip_score_breakdown=None,
                trip_explanation="Buiten ingestelde afstand.",
                ride_quality_score=None,
                ride_experience=None,
                all_trip_windows=[],
                reachable=False,
                available=True,
                explanation=f"Deze bestemming ligt buiten de ingestelde maximale afstand ({route.distance_km:.0f} km).",
                exclusion_reasons=["too_far"],
            )

        forecasts = await self.api_client.get_daily_forecast(
            destination.latitude,
            destination.longitude,
            forecast_days,
        )
        scores = {forecast.date: calculate_ride_score(forecast, activity_profile) for forecast in forecasts}
        best_forecast = max(forecasts, key=lambda item: scores[item.date].score, default=None)
        best_score = scores[best_forecast.date].score if best_forecast else None
        best_day = best_forecast.date if best_forecast else None
        all_trip_windows = calculate_variable_trip_windows(
            forecasts,
            trip_duration.min_days,
            trip_duration.max_days,
            activity_profile,
        )
        all_trip_windows = [
            window for window in all_trip_windows if _matches_window_preferences(window, window_preferences)
        ]
        ride_experiences = [
            (window, calculate_ride_experience(destination, route, window, forecasts, planning_profile))
            for window in all_trip_windows
        ]
        viable_ride_experiences = [
            (window, experience) for window, experience in ride_experiences if not experience.exclusion_reasons
        ]
        best_trip_window, best_ride_experience = max(
            viable_ride_experiences,
            key=lambda item: item[1].ride_quality_score,
            default=(None, None),
        )
        exclusion_reasons = _result_exclusion_reasons(
            forecasts,
            all_trip_windows,
            ride_experiences,
            window_preferences,
        )
        trip_explanation = (
            f"{best_trip_window.trip_explanation} {best_ride_experience.explanation}"
            if best_trip_window and best_ride_experience
            else f"No realistic {trip_duration.label} trip window is available in the forecast."
        )
        explanation = trip_explanation if best_trip_window else "No realistic trip window available"
        return DestinationResult(
            destination=destination,
            route=route,
            forecasts=forecasts,
            scores=scores,
            best_day=best_day,
            best_score=best_score,
            best_forecast=best_forecast,
            trip_score=best_trip_window.trip_score if best_trip_window else None,
            best_trip_window=best_trip_window,
            best_start_day=best_trip_window.start_day if best_trip_window else None,
            trip_duration=best_trip_window.duration_days if best_trip_window else trip_duration.max_days,
            weather_stability_score=best_trip_window.weather_stability_score if best_trip_window else None,
            stability_explanation=best_trip_window.stability_explanation
            if best_trip_window
            else "Er is geen volledig ritvenster beschikbaar.",
            daily_scores={date: score.score for date, score in scores.items()},
            trip_score_breakdown=best_trip_window.trip_score_breakdown if best_trip_window else None,
            trip_explanation=trip_explanation,
            ride_quality_score=best_ride_experience.ride_quality_score if best_ride_experience else None,
            ride_experience=best_ride_experience,
            all_trip_windows=all_trip_windows,
            reachable=True,
            available=bool(forecasts),
            explanation=explanation,
            exclusion_reasons=exclusion_reasons,
        )


def _summary(best: DestinationResult | None) -> str:
    if best is None:
        return "Geen bereikbare bestemming met beschikbare weersverwachting."
    period = (
        _format_period(best.best_trip_window.start_day, best.best_trip_window.end_day)
        if best.best_trip_window
        else ""
    )
    return (
        f"{_summary_prefix(best)} {best.destination.name}: "
        f"{best.ride_quality_score}/100 ride quality for a {best.trip_duration}-day trip "
        f"{period}. {best.trip_explanation}"
    )


def _summary_prefix(best: DestinationResult) -> str:
    if (best.ride_quality_score or 0) < 70:
        return "Geen sterke rit gevonden. Dit is de minst slechte optie."
    return "Aanbevolen rit."


def _opportunities(
    results: list[DestinationResult],
    planning_profile: TripPlanningProfile,
    config: dict[str, Any],
    forecast_days: int,
    trip_duration: TripDurationSelection,
    window_preferences: WindowPreferences,
    active_helpers: dict[str, str | None],
) -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []
    for result in results:
        if not result.reachable or result.route is None:
            continue
        for window in result.all_trip_windows:
            experience = calculate_ride_experience(
                result.destination,
                result.route,
                window,
                result.forecasts,
                planning_profile,
            )
            if experience.exclusion_reasons:
                continue
            opportunities.append(
                _opportunity_payload(
                    result,
                    window,
                    experience,
                    config,
                    forecast_days,
                    trip_duration,
                    planning_profile,
                    window_preferences,
                    active_helpers,
                )
            )
    return opportunities


def _all_opportunities(
    results: list[DestinationResult],
    planning_profile: TripPlanningProfile,
    config: dict[str, Any],
    forecast_days: int,
    trip_duration: TripDurationSelection,
    window_preferences: WindowPreferences,
    active_helpers: dict[str, str | None],
) -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []
    table_duration = _all_opportunities_duration_selection(trip_duration, forecast_days)
    activity_profile = str(config.get(CONF_ACTIVITY_PROFILE, DEFAULT_ACTIVITY_PROFILE))
    for result in results:
        if not result.reachable or result.route is None or not result.forecasts:
            continue
        windows = calculate_variable_trip_windows(
            result.forecasts,
            table_duration.min_days,
            table_duration.max_days,
            activity_profile,
        )
        windows = [window for window in windows if _matches_window_preferences(window, window_preferences)]
        for strategy_profile in _all_opportunity_strategy_profiles(planning_profile):
            for window in windows:
                experience = calculate_ride_experience(
                    result.destination,
                    result.route,
                    window,
                    result.forecasts,
                    strategy_profile,
                )
                if experience.exclusion_reasons:
                    continue
                opportunity = _opportunity_payload(
                    result,
                    window,
                    experience,
                    config,
                    forecast_days,
                    table_duration,
                    strategy_profile,
                    window_preferences,
                    active_helpers,
                )
                opportunities.append(opportunity)
    return opportunities


def _opportunity_payload(
    result: DestinationResult,
    window: Any,
    experience: Any,
    config: dict[str, Any],
    forecast_days: int,
    trip_duration: TripDurationSelection,
    planning_profile: TripPlanningProfile,
    window_preferences: WindowPreferences,
    active_helpers: dict[str, str | None],
) -> dict[str, Any]:
    opportunity = {
        "destination": result.destination.name,
        "start_date": window.start_day,
        "end_date": window.end_day,
        "start_date_display": _format_date(window.start_day),
        "end_date_display": _format_date(window.end_day),
        "period": _format_period(window.start_day, window.end_day),
        "duration_days": window.duration_days,
        "trip_score": window.trip_score,
        "score": experience.ride_quality_score,
        "ride_quality_score": experience.ride_quality_score,
        "weather_score": experience.weather_score,
        "stability_score": window.weather_stability_score,
        "traffic_score": experience.traffic_score,
        "traffic_level": _pressure_level(experience.traffic_score),
        "tourism_pressure_score": experience.tourism_pressure_score,
        "tourism_level": _pressure_level(experience.tourism_pressure_score),
        "holiday_pressure_score": experience.holiday_pressure_score,
        "holiday_score": experience.holiday_score,
        "access_score": experience.access_score,
        "motorcycle_access_score": experience.motorcycle_access_score,
        "access_status": _access_status(experience.motorcycle_access_score),
        "distance_score": experience.distance_score,
        "temperature_score": experience.temperature_score,
        "trip_efficiency_score": experience.trip_efficiency_score,
        "score_weights": experience.score_weights,
        "score_caps": experience.score_caps,
        "recommendation_type": experience.recommendation_type,
        "strategy": experience.travel_strategy,
        "strategy_label": _strategy_label(experience.travel_strategy),
        "travel_strategy": experience.travel_strategy,
        "approach_time_hours": experience.approach_time_hours,
        "return_time_hours": experience.return_time_hours,
        "total_available_time_hours": experience.total_available_time_hours,
        "estimated_destination_ride_time_hours": experience.estimated_destination_ride_time_hours,
        "approach_enjoyment_factor": experience.approach_enjoyment_factor,
        "destination_ride_time_ratio": experience.destination_ride_time_ratio,
        "score_breakdown": _score_breakdown(experience, window),
        "recommendation_reason": _recommendation_reason(result.destination.name, experience, window),
        "main_reason": _main_reason(result.destination.name, experience, window),
        "tradeoffs": _tradeoffs(experience, window),
        "main_tradeoff": _main_tradeoff(experience, window),
        "road_fun_score": experience.road_fun_score,
        "holiday_names": experience.holiday_names,
        "access_notes": experience.access_notes,
        "access_warnings": experience.access_warnings,
        "known_restrictions": experience.known_restrictions,
        "exclusion_reasons": experience.exclusion_reasons,
        "route_distance_km": result.route.distance_km,
        "distance_km": result.route.distance_km,
        "estimated_travel_time": _format_minutes(result.route.travel_time_minutes),
        "daily_scores": window.daily_scores,
        "verdict": _window_verdict(experience.ride_quality_score, _is_weekend_window(window)),
        "explanation": f"{window.trip_explanation} {experience.explanation}",
        "window_type": "weekend" if _is_weekend_window(window) else "weekday",
        "days_until": _days_until(window.start_day),
    }
    opportunity["decision_trace"] = _decision_trace(
        opportunity,
        result,
        config,
        forecast_days,
        trip_duration,
        planning_profile,
        window_preferences,
        active_helpers,
    )
    return opportunity


def _all_opportunities_duration_selection(
    trip_duration: TripDurationSelection,
    forecast_days: int,
) -> TripDurationSelection:
    if forecast_days <= 1:
        min_days = 1
    else:
        configured_min = (
            trip_duration.min_days
            if trip_duration.mode == "flexible"
            else ALL_OPPORTUNITIES_DEFAULT_MIN_DURATION
        )
        min_days = min(forecast_days, max(ALL_OPPORTUNITIES_DEFAULT_MIN_DURATION, configured_min))
    max_days = min(forecast_days, max(ALL_OPPORTUNITIES_DEFAULT_MAX_DURATION, trip_duration.max_days))
    if max_days < min_days:
        max_days = min_days
    return TripDurationSelection("flexible", min_days, max_days, "all_opportunities_table")


def _all_opportunity_strategy_profiles(planning_profile: TripPlanningProfile) -> list[TripPlanningProfile]:
    strategies = [TRAVEL_STRATEGY_MOTORCYCLE_DIRECT, TRAVEL_STRATEGY_MOTORCYCLE_SCENIC]
    if planning_profile.trailer_support_enabled and planning_profile.trailer_available:
        strategies.append(TRAVEL_STRATEGY_TRAILER)
    return [
        TripPlanningProfile(
            travel_strategy=strategy,
            available_hours_per_day=planning_profile.available_hours_per_day,
            max_approach_time_hours=planning_profile.max_approach_time_hours,
            trailer_support_enabled=planning_profile.trailer_support_enabled,
            trailer_available=planning_profile.trailer_available,
        )
        for strategy in strategies
    ]


def _table_opportunities(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible = [
        _compact_table_opportunity(opportunity)
        for opportunity in opportunities
        if int(opportunity["ride_quality_score"]) >= ALL_OPPORTUNITIES_MIN_SCORE
    ]
    return visible[:ALL_OPPORTUNITIES_ATTRIBUTE_LIMIT]


def _compact_table_opportunity(opportunity: dict[str, Any]) -> dict[str, Any]:
    return {
        "destination": opportunity["destination"],
        "strategy": opportunity["strategy"],
        "strategy_label": opportunity["strategy_label"],
        "duration_days": opportunity["duration_days"],
        "period": opportunity["period"],
        "start_date": opportunity["start_date"],
        "end_date": opportunity["end_date"],
        "days_until": opportunity["days_until"],
        "score": opportunity["ride_quality_score"],
        "ride_quality_score": opportunity["ride_quality_score"],
        "weather_score": opportunity["weather_score"],
        "stability_score": opportunity["stability_score"],
        "trip_efficiency_score": opportunity["trip_efficiency_score"],
        "distance_km": opportunity["distance_km"],
        "route_distance_km": opportunity["route_distance_km"],
        "approach_time_hours": opportunity["approach_time_hours"],
        "verdict": opportunity["verdict"],
        "main_reason": opportunity["main_reason"],
        "main_tradeoff": opportunity["main_tradeoff"],
    }


def _strategy_label(strategy: str) -> str:
    return {
        TRAVEL_STRATEGY_MOTORCYCLE_DIRECT: "Direct / snelweg",
        TRAVEL_STRATEGY_MOTORCYCLE_SCENIC: "Binnendoor / scenic",
        TRAVEL_STRATEGY_TRAILER: "Aanhangertransport",
    }.get(strategy, strategy)


def _main_reason(destination: str, experience: Any, window: Any) -> str:
    if experience.ride_quality_score >= 70:
        return (
            f"{destination} heeft de beste balans tussen weer, stabiliteit en bruikbare rijtijd "
            f"voor {window.duration_days} dagen."
        )
    return (
        f"{destination} is alleen het overwegen waard als compromis; de score blijft onder een sterk adviesniveau."
    )


def _main_tradeoff(experience: Any, window: Any) -> str:
    tradeoffs = _tradeoffs(experience, window)
    return tradeoffs[0] if tradeoffs else "Geen grote trade-off gedetecteerd."


def _ranked_opportunities(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        opportunities,
        key=lambda item: (
            -int(item["ride_quality_score"]),
            -int(item["trip_efficiency_score"]),
            -int(item["weather_score"]),
            -int(item["stability_score"]),
            -int(item["holiday_pressure_score"]),
            -int(item["distance_score"]),
            str(item["start_date"]),
        ),
    )
    for rank, opportunity in enumerate(ranked, start=1):
        trace = opportunity.get("decision_trace")
        if isinstance(trace, dict):
            trace.setdefault("result", {})["rank"] = rank
    return ranked


def _top_opportunities(
    opportunities: list[dict[str, Any]],
    max_days_until: int | None = None,
    minimum_score: int = 70,
    limit: int = 3,
) -> list[dict[str, Any]]:
    top = [
        opportunity
        for opportunity in opportunities
        if int(opportunity["ride_quality_score"]) >= minimum_score
        and (
            max_days_until is None
            or (opportunity.get("days_until") is not None and opportunity["days_until"] <= max_days_until)
        )
    ]
    return top[:limit]


def _empty_strategy_top_data() -> dict[str, dict[str, Any]]:
    return {
        key: {
            "opportunities": [],
            "candidate_count": 0,
            "rejected_count": 0,
            "best_rejected_candidate": None,
        }
        for key, _, _ in TOP_STRATEGY_OPPORTUNITY_KEYS
    }


def _strategy_top_opportunity_data(opportunities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        key: _strategy_top_opportunities(
            opportunities,
            strategy=strategy,
            max_days_until=max_days_until,
        )
        for key, strategy, max_days_until in TOP_STRATEGY_OPPORTUNITY_KEYS
    }


def _strategy_top_opportunities(
    opportunities: list[dict[str, Any]],
    strategy: str,
    max_days_until: int | None = None,
    minimum_score: int = 70,
    limit: int = 3,
) -> dict[str, Any]:
    candidates = [
        opportunity
        for opportunity in opportunities
        if opportunity.get("strategy") == strategy
        and (
            max_days_until is None
            or (opportunity.get("days_until") is not None and opportunity["days_until"] <= max_days_until)
        )
    ]
    accepted = [
        _compact_strategy_opportunity(opportunity)
        for opportunity in candidates
        if int(opportunity["ride_quality_score"]) >= minimum_score
    ][:limit]
    rejected = [opportunity for opportunity in candidates if int(opportunity["ride_quality_score"]) < minimum_score]
    return {
        "opportunities": accepted,
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "best_rejected_candidate": _strategy_rejection_summary(rejected[0]) if rejected else None,
    }


def _compact_strategy_opportunity(opportunity: dict[str, Any]) -> dict[str, Any]:
    return {
        "destination": opportunity["destination"],
        "ride_quality_score": opportunity["ride_quality_score"],
        "score": opportunity["ride_quality_score"],
        "period": opportunity["period"],
        "duration_days": opportunity["duration_days"],
        "strategy": opportunity["strategy"],
        "strategy_label": opportunity["strategy_label"],
        "weather_score": opportunity["weather_score"],
        "stability_score": opportunity["stability_score"],
        "trip_efficiency_score": opportunity["trip_efficiency_score"],
        "distance_score": opportunity["distance_score"],
        "main_reason": opportunity["main_reason"],
        "main_tradeoff": opportunity["main_tradeoff"],
    }


def _strategy_rejection_summary(opportunity: dict[str, Any] | None) -> dict[str, Any] | None:
    if opportunity is None:
        return None
    return {
        "destination": opportunity["destination"],
        "ride_quality_score": opportunity["ride_quality_score"],
        "period": opportunity["period"],
        "duration_days": opportunity["duration_days"],
        "strategy": opportunity["strategy"],
        "strategy_label": opportunity["strategy_label"],
        "main_reason": opportunity["main_reason"],
        "main_tradeoff": opportunity["main_tradeoff"],
    }


def _top_opportunity_stats(
    opportunities: list[dict[str, Any]],
    max_days_until: int | None = None,
    minimum_score: int = 70,
) -> dict[str, Any]:
    candidates = [
        opportunity
        for opportunity in opportunities
        if max_days_until is None
        or (opportunity.get("days_until") is not None and opportunity["days_until"] <= max_days_until)
    ]
    rejected = [opportunity for opportunity in candidates if int(opportunity["ride_quality_score"]) < minimum_score]
    best_rejected = rejected[0] if rejected else None
    return {
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "best_below_threshold": _rejection_summary(best_rejected) if best_rejected else None,
    }


def _rejection_summary(opportunity: dict[str, Any] | None) -> dict[str, Any] | None:
    if opportunity is None:
        return None
    return {
        "destination": opportunity["destination"],
        "period": opportunity["period"],
        "ride_quality_score": opportunity["ride_quality_score"],
        "reason": _primary_rejection_reason(opportunity),
        "main_blocking_factor": _primary_rejection_detail(opportunity),
        "score_breakdown": opportunity["score_breakdown"],
    }


def _primary_rejection_reason(opportunity: dict[str, Any]) -> str:
    if int(opportunity["weather_score"]) < 25:
        return "weather_too_poor"
    if int(opportunity["stability_score"]) < 40:
        return "stability_too_low"
    return "below_minimum_score"


def _primary_rejection_detail(opportunity: dict[str, Any]) -> str:
    reason = _primary_rejection_reason(opportunity)
    if reason == "weather_too_poor":
        return f"Weer scoort {opportunity['weather_score']}/100."
    if reason == "stability_too_low":
        return f"Weerstabiliteit scoort {opportunity['stability_score']}/100."
    return f"Ritkwaliteit scoort {opportunity['ride_quality_score']}/100 en blijft onder de adviesdrempel van 70."


def _disabled_destinations(config: dict[str, Any]) -> list[dict[str, str]]:
    enabled_names = {destination.name for destination in destinations_from_config(config)}
    return [
        {
            "destination": destination.name,
            "reason": "disabled",
            "details": "Deze bestemming staat uit in de RideRadar-instellingen.",
        }
        for destination in all_destinations_for_options(config)
        if destination.name not in enabled_names
    ]


def _excluded_destinations(results: list[DestinationResult]) -> list[dict[str, str]]:
    excluded: list[dict[str, str]] = []
    for result in results:
        if result.ride_quality_score is not None:
            continue
        reason = result.exclusion_reasons[0] if result.exclusion_reasons else "no_valid_opportunity"
        excluded.append(
            {
                "destination": result.destination.name,
                "reason": reason,
                "details": _exclusion_details(reason, result),
            }
        )
    return excluded


def _result_exclusion_reasons(
    forecasts: list[Any],
    windows: list[Any],
    ride_experiences: list[tuple[Any, Any]],
    window_preferences: WindowPreferences,
) -> list[str]:
    if not forecasts:
        return ["no_forecast_data"]
    if not windows:
        if window_preferences.weekend_only:
            return ["weekend_only_filter"]
        if window_preferences.preferred_start_weekday is not None:
            return ["preferred_start_day_filter"]
        return ["no_complete_window"]
    reasons = [
        reason
        for _, experience in ride_experiences
        for reason in experience.exclusion_reasons
    ]
    if not reasons:
        return []
    return sorted(set(_canonical_exclusion_reason(reason) for reason in reasons))


def _canonical_exclusion_reason(reason: str) -> str:
    normalized = reason.casefold()
    if "trailer" in normalized and "not available" in normalized:
        return "trailer_required_but_unavailable"
    if "trailer" in normalized and "disabled" in normalized:
        return "trailer_disabled"
    if "max travel effort" in normalized:
        return "approach_time_too_high"
    return "insufficient_destination_ride_time"


def _exclusion_details(reason: str, result: DestinationResult) -> str:
    details = {
        "too_far": result.explanation,
        "no_forecast_data": "Voor deze bestemming is geen bruikbare weersverwachting beschikbaar.",
        "no_complete_window": "Er is geen volledig weervenster voor de geselecteerde ritduur.",
        "weekend_only_filter": "Geen beoordeeld venster past binnen de weekendfilter.",
        "preferred_start_day_filter": "Geen beoordeeld venster start op de voorkeursdag.",
        "trailer_required_but_unavailable": (
            "Aanhangertransport is gekozen, maar de aanhanger is vandaag niet beschikbaar."
        ),
        "trailer_disabled": "Aanhangertransport staat uit in de RideRadar-instellingen.",
        "approach_time_too_high": "De aanrijtijd is hoger dan de ingestelde maximale reistijd.",
        "insufficient_destination_ride_time": "Er blijft te weinig bruikbare rijtijd over op de bestemming.",
    }
    return details.get(reason, result.explanation)


def _decision_trace(
    opportunity: dict[str, Any],
    result: DestinationResult,
    config: dict[str, Any],
    forecast_days: int,
    trip_duration: TripDurationSelection,
    planning_profile: TripPlanningProfile,
    window_preferences: WindowPreferences,
    active_helpers: dict[str, str | None],
) -> dict[str, Any]:
    return {
        "inputs": {
            "start_location": str(config.get("start_address", "redacted")),
            "destination": result.destination.name,
            "travel_strategy": planning_profile.travel_strategy,
            "duration_days": opportunity["duration_days"],
            "duration_mode": trip_duration.mode,
            "min_duration_days": trip_duration.min_days,
            "max_duration_days": trip_duration.max_days,
            "forecast_horizon_days": forecast_days,
            "weekend_only": window_preferences.weekend_only,
            "preferred_start_day": _weekday_name(window_preferences.preferred_start_weekday),
            "trailer_support_enabled": planning_profile.trailer_support_enabled,
            "trailer_available": planning_profile.trailer_available,
            "available_hours_per_day": planning_profile.available_hours_per_day,
            "max_approach_time_hours": planning_profile.max_approach_time_hours,
            "helper_overrides": active_helpers,
        },
        "window": {
            "start_date": opportunity["start_date"],
            "end_date": opportunity["end_date"],
            "period": opportunity["period"],
        },
        "scores": opportunity["score_breakdown"],
        "weights": opportunity["score_weights"],
        "caps": opportunity["score_caps"],
        "penalties": _trace_penalties(opportunity),
        "boosts": _trace_boosts(opportunity),
        "result": {
            "rank": None,
            "verdict": opportunity["verdict"],
            "recommendation_type": opportunity["recommendation_type"],
            "recommendation_reason": opportunity["recommendation_reason"],
        },
    }


def _trace_penalties(opportunity: dict[str, Any]) -> list[dict[str, Any]]:
    penalties: list[dict[str, Any]] = []
    if int(opportunity["trip_efficiency_score"]) < 80:
        penalties.append(
            {
                "name": "trip_efficiency",
                "value": int(opportunity["trip_efficiency_score"]) - 80,
                "reason": "Travel effort reduces useful destination riding time.",
            }
        )
    if int(opportunity["holiday_pressure_score"]) < 80:
        penalties.append(
            {
                "name": "holiday_pressure",
                "value": int(opportunity["holiday_pressure_score"]) - 80,
                "reason": "Holiday or long-weekend pressure may make scenic routes busier.",
            }
        )
    if int(opportunity["access_score"]) < 80:
        penalties.append(
            {
                "name": "access",
                "value": int(opportunity["access_score"]) - 80,
                "reason": "Known regional motorcycle restriction risk affects this window.",
            }
        )
    return penalties


def _trace_boosts(opportunity: dict[str, Any]) -> list[dict[str, Any]]:
    boosts: list[dict[str, Any]] = []
    if opportunity["travel_strategy"] == "motorcycle_scenic":
        boosts.append(
            {
                "name": "scenic_approach",
                "value": round(float(opportunity["approach_enjoyment_factor"]) * 10),
                "reason": "Motorcycle scenic approach makes approach time partially enjoyable.",
            }
        )
    if int(opportunity["stability_score"]) >= 85:
        boosts.append(
            {
                "name": "stable_weather",
                "value": 3,
                "reason": "Forecast consistency is high across the complete window.",
            }
        )
    return boosts


def _best_debug_summary(best: DestinationResult | None) -> str:
    if best is None:
        return "none"
    return f"{best.destination.name} {best.ride_quality_score}/100"


def _best_matching_opportunity(opportunities: list[dict[str, Any]], window_type: str) -> dict[str, Any] | None:
    hero = opportunities[0] if opportunities else None
    return next(
        (
            opportunity
            for opportunity in opportunities
            if opportunity["window_type"] == window_type and not _same_opportunity(opportunity, hero)
        ),
        None,
    )


def _same_opportunity(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not left or not right:
        return False
    return (
        left.get("destination") == right.get("destination")
        and left.get("start_date") == right.get("start_date")
        and left.get("end_date") == right.get("end_date")
        and left.get("duration_days") == right.get("duration_days")
    )


def _is_weekend_window(window: Any) -> bool:
    try:
        start = date.fromisoformat(window.start_day)
        end = date.fromisoformat(window.end_day)
    except ValueError:
        return False
    days = (end - start).days + 1
    return any((start + timedelta(days=offset)).weekday() >= 5 for offset in range(days))


def _window_verdict(score: int, weekend: bool = False) -> str:
    suffix = " weekend" if weekend else " window"
    return f"{ride_verdict(score)}{suffix}"


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


def _format_minutes(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if hours:
        return f"{hours}h {remainder:02d}m"
    return f"{remainder}m"


def _days_until(start_day: str) -> int | None:
    try:
        start = date.fromisoformat(start_day)
    except ValueError:
        return None
    return max(0, (start - datetime.now().date()).days)


def _trip_duration_selection(
    config: dict[str, Any],
    forecast_days: int,
    hass: HomeAssistant | None = None,
    native_controls: dict[str, str] | None = None,
) -> TripDurationSelection:
    config_duration = _trip_duration_from_config(config, forecast_days)
    mode = str(config.get(CONF_DURATION_MODE, DEFAULT_DURATION_MODE))
    source = "config"
    if str(config.get(CONF_PREFERRED_TRIP_DURATION, DEFAULT_PREFERRED_TRIP_DURATION)) == "flexible":
        mode = "flexible"

    number_duration = _helper_number_duration(hass, forecast_days, native_controls)
    select_value = _state_with_precedence(
        hass,
        CONTROL_TRIP_DURATION,
        NATIVE_TRIP_DURATION_SELECT_ENTITY,
        TRIP_DURATION_SELECT_ENTITY,
        native_controls,
    )
    if select_value is not None:
        source = TRIP_DURATION_SELECT_ENTITY
        normalized = _normalize_duration_select(select_value)
        if normalized == "flexible":
            mode = "flexible"
            config_duration = number_duration or config_duration
        elif normalized == "custom":
            config_duration = number_duration or config_duration
            mode = "fixed"
            source = f"{TRIP_DURATION_SELECT_ENTITY}+{TRIP_DURATION_NUMBER_ENTITY}"
        elif normalized is not None:
            config_duration = normalized
            mode = "fixed"
    elif number_duration is not None:
        config_duration = number_duration
        mode = "fixed"
        source = TRIP_DURATION_NUMBER_ENTITY

    if mode not in {"fixed", "flexible"}:
        mode = "fixed"
    max_supported = max(MIN_TRIP_DURATION_DAYS, min(forecast_days, MAX_FORECAST_DAYS))
    max_days = max(MIN_TRIP_DURATION_DAYS, min(int(config_duration), max_supported))
    min_days = MIN_TRIP_DURATION_DAYS if mode == "flexible" else max_days
    return TripDurationSelection(mode=mode, min_days=min_days, max_days=max_days, source=source)


def _forecast_days_selection(
    config: dict[str, Any],
    hass: HomeAssistant | None = None,
    native_controls: dict[str, str] | None = None,
) -> int:
    configured = int(config.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS))
    helper_value = _state_with_precedence(
        hass,
        CONTROL_FORECAST_HORIZON_DAYS,
        NATIVE_FORECAST_HORIZON_ENTITY,
        FORECAST_HORIZON_ENTITY,
        native_controls,
    )
    if helper_value is not None:
        try:
            configured = round(float(helper_value))
        except ValueError:
            pass
    return max(MIN_TRIP_DURATION_DAYS, min(configured, MAX_FORECAST_DAYS))


def _window_preferences(
    hass: HomeAssistant | None = None,
    native_controls: dict[str, str] | None = None,
) -> WindowPreferences:
    return WindowPreferences(
        weekend_only=_helper_bool(
            hass,
            WEEKEND_ONLY_ENTITY,
            False,
            native_controls,
            CONTROL_WEEKEND_ONLY,
            NATIVE_WEEKEND_ONLY_ENTITY,
        ),
        preferred_start_weekday=_normalize_weekday(
            _state_with_precedence(
                hass,
                CONTROL_PREFERRED_START_DAY,
                NATIVE_PREFERRED_START_DAY_ENTITY,
                PREFERRED_START_DAY_ENTITY,
                native_controls,
            )
        ),
    )


def _matches_window_preferences(window: Any, preferences: WindowPreferences) -> bool:
    if preferences.weekend_only and not _is_weekend_window(window):
        return False
    if preferences.preferred_start_weekday is None:
        return True
    try:
        start = date.fromisoformat(window.start_day)
    except ValueError:
        return True
    return start.weekday() == preferences.preferred_start_weekday


def _normalize_weekday(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized in {"any", "flexible", "geen voorkeur", "no preference"}:
        return None
    weekdays = {
        "monday": 0,
        "maandag": 0,
        "mon": 0,
        "ma": 0,
        "tuesday": 1,
        "dinsdag": 1,
        "tue": 1,
        "di": 1,
        "wednesday": 2,
        "woensdag": 2,
        "wed": 2,
        "wo": 2,
        "thursday": 3,
        "donderdag": 3,
        "thu": 3,
        "do": 3,
        "friday": 4,
        "vrijdag": 4,
        "fri": 4,
        "vr": 4,
        "saturday": 5,
        "zaterdag": 5,
        "sat": 5,
        "za": 5,
        "sunday": 6,
        "zondag": 6,
        "sun": 6,
        "zo": 6,
    }
    return weekdays.get(normalized)


def _trip_duration_from_config(config: dict[str, Any], forecast_days: int) -> int:
    preferred = str(config.get(CONF_PREFERRED_TRIP_DURATION, DEFAULT_PREFERRED_TRIP_DURATION))
    if preferred == "flexible":
        duration = int(config.get(CONF_CUSTOM_TRIP_DURATION_DAYS, DEFAULT_CUSTOM_TRIP_DURATION_DAYS))
    elif preferred == "custom":
        duration = int(config.get(CONF_CUSTOM_TRIP_DURATION_DAYS, DEFAULT_CUSTOM_TRIP_DURATION_DAYS))
    else:
        duration = int(preferred)
    max_supported = max(MIN_TRIP_DURATION_DAYS, min(forecast_days, MAX_FORECAST_DAYS))
    return max(MIN_TRIP_DURATION_DAYS, min(duration, max_supported))


def _helper_number_duration(
    hass: HomeAssistant | None,
    forecast_days: int,
    native_controls: dict[str, str] | None = None,
) -> int | None:
    value = _state_with_precedence(
        hass,
        CONTROL_TRIP_DURATION_DAYS,
        NATIVE_TRIP_DURATION_NUMBER_ENTITY,
        TRIP_DURATION_NUMBER_ENTITY,
        native_controls,
    )
    if value is None:
        return None
    try:
        duration = round(float(value))
    except ValueError:
        return None
    max_supported = max(MIN_TRIP_DURATION_DAYS, min(forecast_days, MAX_FORECAST_DAYS))
    return max(MIN_TRIP_DURATION_DAYS, min(duration, max_supported))


def _helper_select_value(hass: HomeAssistant | None) -> str | None:
    if hass is None:
        return None
    state = hass.states.get(TRIP_DURATION_SELECT_ENTITY)
    if state is None or state.state in {"unknown", "unavailable", ""}:
        return None
    return state.state


def _active_helper_states(
    hass: HomeAssistant | None,
    native_controls: dict[str, str] | None = None,
) -> dict[str, str | None]:
    controls = {
        NATIVE_TRIP_DURATION_SELECT_ENTITY: _state_with_precedence(
            hass,
            CONTROL_TRIP_DURATION,
            NATIVE_TRIP_DURATION_SELECT_ENTITY,
            TRIP_DURATION_SELECT_ENTITY,
            native_controls,
        ),
        NATIVE_TRIP_DURATION_NUMBER_ENTITY: _state_with_precedence(
            hass,
            CONTROL_TRIP_DURATION_DAYS,
            NATIVE_TRIP_DURATION_NUMBER_ENTITY,
            TRIP_DURATION_NUMBER_ENTITY,
            native_controls,
        ),
        NATIVE_FORECAST_HORIZON_ENTITY: _state_with_precedence(
            hass,
            CONTROL_FORECAST_HORIZON_DAYS,
            NATIVE_FORECAST_HORIZON_ENTITY,
            FORECAST_HORIZON_ENTITY,
            native_controls,
        ),
        NATIVE_PREFERRED_START_DAY_ENTITY: _state_with_precedence(
            hass,
            CONTROL_PREFERRED_START_DAY,
            NATIVE_PREFERRED_START_DAY_ENTITY,
            PREFERRED_START_DAY_ENTITY,
            native_controls,
        ),
        NATIVE_WEEKEND_ONLY_ENTITY: _state_with_precedence(
            hass, CONTROL_WEEKEND_ONLY, NATIVE_WEEKEND_ONLY_ENTITY, WEEKEND_ONLY_ENTITY, native_controls
        ),
        NATIVE_TRAVEL_STRATEGY_SELECT_ENTITY: _state_with_precedence(
            hass,
            CONTROL_TRAVEL_STRATEGY,
            NATIVE_TRAVEL_STRATEGY_SELECT_ENTITY,
            TRAVEL_STRATEGY_SELECT_ENTITY,
            native_controls,
        ),
        NATIVE_TRAILER_AVAILABLE_ENTITY: _state_with_precedence(
            hass,
            CONTROL_TRAILER_AVAILABLE,
            NATIVE_TRAILER_AVAILABLE_ENTITY,
            TRAILER_AVAILABLE_ENTITY,
            native_controls,
        ),
        NATIVE_AVAILABLE_HOURS_ENTITY: _state_with_precedence(
            hass,
            CONTROL_AVAILABLE_HOURS_PER_DAY,
            NATIVE_AVAILABLE_HOURS_ENTITY,
            AVAILABLE_HOURS_ENTITY,
            native_controls,
        ),
        NATIVE_MAX_APPROACH_TIME_ENTITY: _state_with_precedence(
            hass,
            CONTROL_MAX_APPROACH_TIME_HOURS,
            NATIVE_MAX_APPROACH_TIME_ENTITY,
            MAX_APPROACH_TIME_ENTITY,
            native_controls,
        ),
    }
    return controls


def _trip_planning_profile(
    config: dict[str, Any],
    hass: HomeAssistant | None = None,
    native_controls: dict[str, str] | None = None,
) -> TripPlanningProfile:
    strategy = _normalize_travel_strategy(
        _state_with_precedence(
            hass,
            CONTROL_TRAVEL_STRATEGY,
            NATIVE_TRAVEL_STRATEGY_SELECT_ENTITY,
            TRAVEL_STRATEGY_SELECT_ENTITY,
            native_controls,
        )
    ) or str(config.get("travel_strategy", DEFAULT_TRAVEL_STRATEGY))
    if strategy not in TRAVEL_STRATEGY_OPTIONS:
        strategy = TRAVEL_STRATEGY_MOTORCYCLE_DIRECT
    trailer_support_enabled = _as_bool(
        config.get(CONF_TRAILER_SUPPORT_ENABLED, DEFAULT_TRAILER_SUPPORT_ENABLED),
        DEFAULT_TRAILER_SUPPORT_ENABLED,
    )
    return TripPlanningProfile(
        travel_strategy=strategy,
        available_hours_per_day=_helper_float(
            hass,
            AVAILABLE_HOURS_ENTITY,
            DEFAULT_AVAILABLE_HOURS_PER_DAY,
            minimum=1.0,
            maximum=18.0,
            native_controls=native_controls,
            control_key=CONTROL_AVAILABLE_HOURS_PER_DAY,
            native_entity_id=NATIVE_AVAILABLE_HOURS_ENTITY,
        ),
        max_approach_time_hours=_helper_float(
            hass,
            MAX_APPROACH_TIME_ENTITY,
            DEFAULT_MAX_APPROACH_TIME_HOURS,
            minimum=0.5,
            maximum=12.0,
            native_controls=native_controls,
            control_key=CONTROL_MAX_APPROACH_TIME_HOURS,
            native_entity_id=NATIVE_MAX_APPROACH_TIME_ENTITY,
        ),
        trailer_support_enabled=trailer_support_enabled,
        trailer_available=trailer_support_enabled
        and _helper_bool(
            hass,
            TRAILER_AVAILABLE_ENTITY,
            False,
            native_controls,
            CONTROL_TRAILER_AVAILABLE,
            NATIVE_TRAILER_AVAILABLE_ENTITY,
        ),
    )


def _helper_state(hass: HomeAssistant | None, entity_id: str) -> str | None:
    if hass is None:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unknown", "unavailable", ""}:
        return None
    return state.state


def _state_with_precedence(
    hass: HomeAssistant | None,
    control_key: str,
    native_entity_id: str,
    legacy_entity_id: str,
    native_controls: dict[str, str] | None = None,
) -> str | None:
    if native_controls and control_key in native_controls:
        return native_controls[control_key]
    native_value = _helper_state(hass, native_entity_id)
    if native_value is not None:
        return native_value
    return _helper_state(hass, legacy_entity_id)


def _helper_float(
    hass: HomeAssistant | None,
    entity_id: str,
    default: float,
    minimum: float,
    maximum: float,
    native_controls: dict[str, str] | None = None,
    control_key: str | None = None,
    native_entity_id: str | None = None,
) -> float:
    value = (
        _state_with_precedence(hass, control_key, native_entity_id, entity_id, native_controls)
        if control_key and native_entity_id
        else _helper_state(hass, entity_id)
    )
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(minimum, min(parsed, maximum))


def _helper_bool(
    hass: HomeAssistant | None,
    entity_id: str,
    default: bool,
    native_controls: dict[str, str] | None = None,
    control_key: str | None = None,
    native_entity_id: str | None = None,
) -> bool:
    value = (
        _state_with_precedence(hass, control_key, native_entity_id, entity_id, native_controls)
        if control_key and native_entity_id
        else _helper_state(hass, entity_id)
    )
    if value is None:
        return default
    return _as_bool(value, default)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"on", "true", "yes", "1"}:
            return True
        if normalized in {"off", "false", "no", "0"}:
            return False
    return default


def _normalize_travel_strategy(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold().replace("-", " ").replace("_", " ")
    if normalized in {"motorcycle direct", "direct", "motor direct", "motorcycle"}:
        return "motorcycle_direct"
    if normalized in {"motorcycle scenic", "scenic", "scenic approach", "motorcycle scenic approach"}:
        return "motorcycle_scenic"
    if normalized in {"trailer", "trailer transport", "car trailer"}:
        return "trailer"
    return None


def _normalize_duration_select(value: str) -> int | str | None:
    normalized = value.strip().casefold().replace("_", " ").replace("-", " ")
    if normalized in {"flexible", "flexibel"}:
        return "flexible"
    if normalized == "custom":
        return "custom"
    for duration in range(1, MAX_FORECAST_DAYS + 1):
        if normalized in {str(duration), f"{duration} day", f"{duration} days", f"{duration} dagen"}:
            return duration
    return None


def _format_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{_weekday_label(parsed)} {parsed.strftime('%d-%m-%Y')}"


def _format_period(start_value: str | None, end_value: str | None) -> str:
    start = _format_date(start_value)
    end = _format_date(end_value)
    if start and end:
        return f"{start} t/m {end}"
    return start or end or "Periode onbekend"


def _score_breakdown(experience: Any, window: Any) -> dict[str, int]:
    return {
        "weather_score": experience.weather_score,
        "stability_score": window.weather_stability_score,
        "temperature_score": experience.temperature_score,
        "distance_score": experience.distance_score,
        "holiday_pressure_score": experience.holiday_pressure_score,
        "access_score": experience.access_score,
        "trip_efficiency_score": experience.trip_efficiency_score,
        "ride_quality_score": experience.ride_quality_score,
    }


def _recommendation_reason(destination: str, experience: Any, window: Any) -> str:
    if experience.ride_quality_score < 70:
        quality = "minst slechte optie, geen sterke aanbeveling"
    elif experience.ride_quality_score >= 85:
        quality = "sterkste volledige ritvenster"
    elif experience.ride_quality_score >= 70:
        quality = "best gebalanceerde beschikbare ritvenster"
    else:
        quality = "minst slechte beschikbare ritvenster"
    return (
        f"{destination} is het {quality}: weer {experience.weather_score}/100, "
        f"stabiliteit {window.weather_stability_score}/100, afstand {experience.distance_score}/100, "
        f"vakantiedruk {experience.holiday_pressure_score}/100, toegang {experience.access_score}/100, "
        f"ritefficientie {experience.trip_efficiency_score}/100."
    )


def _tradeoffs(experience: Any, window: Any) -> list[str]:
    tradeoffs: list[str] = []
    if experience.weather_score == 0:
        tradeoffs.append("De weerscore is 0/100; dit is alleen zichtbaar als minst slechte optie.")
    if experience.weather_score < 80:
        tradeoffs.append(f"Weer scoort {experience.weather_score}/100 voor dit venster.")
    if window.weather_stability_score < 80:
        tradeoffs.append(f"Weerstabiliteit is {window.weather_stability_score}/100; een dag kan zwakker zijn.")
    if experience.temperature_score < 80:
        tradeoffs.append(f"Temperatuurcomfort scoort {experience.temperature_score}/100.")
    if experience.distance_score < 80:
        tradeoffs.append(f"Afstand scoort {experience.distance_score}/100; de aanrijroute kan lang zijn.")
    if experience.trip_efficiency_score < 80:
        tradeoffs.append(
            f"Ritefficientie scoort {experience.trip_efficiency_score}/100; er gaat relatief veel tijd naar "
            "aan- en terugrijden."
        )
    if experience.holiday_pressure_score < 80:
        tradeoffs.append(f"Vakantiedruk scoort {experience.holiday_pressure_score}/100.")
    if experience.access_score < 80:
        tradeoffs.append(f"Toegang scoort {experience.access_score}/100; controleer lokale routebeperkingen.")
    return tradeoffs or ["Geen grote trade-off gevonden in het huidige ritvenster."]


def _weekday_label(value: date) -> str:
    return ("Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo")[value.weekday()]


def _weekday_name(value: int | None) -> str:
    if value is None:
        return "any"
    return ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[value]
