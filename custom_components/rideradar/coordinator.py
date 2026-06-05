"""Data coordinator for RideRadar."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OpenMeteoClient
from .const import (
    CONF_ABSOLUTE_MAX_APPROACH_TIME_HOURS,
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DETOUR_FACTOR,
    CONF_DURATION_MODE,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_PREFERRED_MAX_APPROACH_TIME_HOURS,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    CONF_TRAILER_SUPPORT_ENABLED,
    CONF_WEATHER_ENTITY_MAP,
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
    DEFAULT_MAX_ROUTE_DISTANCE_KM,
    DEFAULT_PREFERRED_MAX_APPROACH_TIME_HOURS,
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
from .weather_cache import ForecastCache, HomeAssistantWeatherEntityClient

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
        self.forecast_cache = ForecastCache(hass, _weather_providers(api_client, hass, self.config))
        self._force_weather_refresh = False
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

    async def async_load_forecast_cache(self) -> None:
        """Load persisted forecast cache before the first refresh."""
        await self.forecast_cache.async_load()

    async def async_refresh_weather(self, *, force: bool = False) -> None:
        """Request a weather refresh through the normal coordinator path."""
        self._force_weather_refresh = force
        await self.async_request_refresh()

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
            "evaluated_candidates": [],
            "evaluation_summary": _evaluation_summary([]),
            "advice_candidate": None,
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
            "preferred_max_approach_time_hours": planning_profile.preferred_max_approach_time_hours,
            "absolute_max_approach_time_hours": planning_profile.absolute_max_approach_time_hours,
            "trailer_available": planning_profile.trailer_available,
            "weekend_only": window_preferences.weekend_only,
            "preferred_start_weekday": window_preferences.preferred_start_weekday,
            "active_helpers": active_helpers,
            "mode_status": _mode_status(planning_profile),
            "weather": _weather_status_with_results(self.forecast_cache.status(), []),
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
            force_weather_refresh = self._force_weather_refresh
            self._force_weather_refresh = False
            self.forecast_cache.set_providers(_weather_providers(self.api_client, self.hass, config))
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
                "evaluated_candidates": [],
                "evaluation_summary": _evaluation_summary([]),
                "advice_candidate": None,
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
                "preferred_max_approach_time_hours": planning_profile.preferred_max_approach_time_hours,
                "absolute_max_approach_time_hours": planning_profile.absolute_max_approach_time_hours,
                "trailer_available": planning_profile.trailer_available,
                "weekend_only": window_preferences.weekend_only,
                "preferred_start_weekday": window_preferences.preferred_start_weekday,
                "active_helpers": active_helpers,
                "mode_status": _mode_status(planning_profile),
                "weather": _weather_status_with_results(self.forecast_cache.status(), []),
            }

        results: list[DestinationResult] = []
        for destination in enabled_destinations:
            try:
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
                        force_weather_refresh,
                    )
                )
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
        evaluated_candidates = _evaluated_candidates(opportunities, all_opportunities, excluded_destinations)
        evaluation_summary = _evaluation_summary(evaluated_candidates)
        evaluation_summary["disabled_modes"] = _disabled_modes_from_status(_mode_status(planning_profile))
        advice_candidate = _advice_candidate(evaluated_candidates)
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
            "evaluated_candidates": evaluated_candidates,
            "evaluation_summary": evaluation_summary,
            "advice_candidate": advice_candidate,
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
            "preferred_max_approach_time_hours": planning_profile.preferred_max_approach_time_hours,
            "absolute_max_approach_time_hours": planning_profile.absolute_max_approach_time_hours,
            "trailer_available": planning_profile.trailer_available,
            "weekend_only": window_preferences.weekend_only,
            "preferred_start_weekday": window_preferences.preferred_start_weekday,
            "active_helpers": active_helpers,
            "mode_status": _mode_status(planning_profile),
            "weather": _weather_status_with_results(self.forecast_cache.status(), results),
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
        force_weather_refresh: bool = False,
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
                weather=_destination_weather_metadata(
                    destination,
                    None,
                    "unavailable",
                    "destination_not_evaluated",
                ),
            )

        absolute_approach_time = _route_approach_time_for_strategy(route.travel_time_minutes, planning_profile)
        if (
            planning_profile.absolute_max_approach_time_hours is not None
            and absolute_approach_time > planning_profile.absolute_max_approach_time_hours
        ):
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
                stability_explanation="Niet beoordeeld omdat een harde aanrijlimiet is overschreden.",
                daily_scores={},
                trip_score_breakdown=None,
                trip_explanation="Absolute aanrijlimiet overschreden.",
                ride_quality_score=None,
                ride_experience=None,
                all_trip_windows=[],
                reachable=False,
                available=True,
                explanation=(
                    f"Geschatte aanrijtijd {absolute_approach_time:.1f} uur. "
                    f"Absolute maximale aanrijtijd: "
                    f"{planning_profile.absolute_max_approach_time_hours:.1f} uur."
                ),
                exclusion_reasons=["absolute_approach_time_exceeded"],
                weather=_destination_weather_metadata(
                    destination,
                    None,
                    "unavailable",
                    "destination_not_evaluated",
                ),
            )

        cached_forecast = await self.forecast_cache.async_get_forecast(
            destination.latitude,
            destination.longitude,
            forecast_days,
            location_name=destination.name,
            force=force_weather_refresh,
        )
        forecasts = cached_forecast.forecasts
        weather_metadata = _destination_weather_metadata(
            destination,
            cached_forecast.provider,
            cached_forecast.status,
            cached_forecast.data_quality_reason,
            cache_age_hours=cached_forecast.cache_age_hours,
            fetched_at=cached_forecast.fetched_at,
            missing_fields=cached_forecast.missing_fields,
            from_cache=cached_forecast.from_cache,
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
            (window, experience) for window, experience in ride_experiences if not experience.hard_exclusion_reasons
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
            weather=weather_metadata,
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
            if experience.hard_exclusion_reasons:
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
                if experience.hard_exclusion_reasons:
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
        "preferred_duration_days": trip_duration.max_days,
        "preferred_duration_difference_days": abs(window.duration_days - trip_duration.max_days),
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
        "total_transport_time_hours": experience.total_transport_time_hours,
        "total_available_time_hours": experience.total_available_time_hours,
        "estimated_destination_ride_time_hours": experience.estimated_destination_ride_time_hours,
        "approach_enjoyment_factor": experience.approach_enjoyment_factor,
        "destination_ride_time_ratio": experience.destination_ride_time_ratio,
        "preferred_max_approach_time_hours": experience.preferred_max_approach_time_hours,
        "absolute_max_approach_time_hours": experience.absolute_max_approach_time_hours,
        "preferred_approach_time_overrun_hours": experience.preferred_approach_time_overrun_hours,
        "absolute_approach_time_overrun_hours": experience.absolute_approach_time_overrun_hours,
        "preference_warnings": experience.preference_warnings,
        "hard_exclusion_reasons": experience.hard_exclusion_reasons,
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
        "weather_evaluation": _weather_evaluation(result.forecasts, window),
        "verdict": _window_verdict(experience.ride_quality_score, _is_weekend_window(window)),
        "explanation": f"{window.trip_explanation} {experience.explanation}",
        "window_type": "weekend" if _is_weekend_window(window) else "weekday",
        "days_until": _days_until(window.start_day),
        "weather_status": (result.weather or {}).get("weather_status"),
        "weather_provider_used": (result.weather or {}).get("weather_provider_used"),
        "weather_data_quality_reason": (result.weather or {}).get("weather_data_quality_reason"),
        "forecast_location_name": (result.weather or {}).get("forecast_location_name"),
        "forecast_latitude": (result.weather or {}).get("forecast_latitude"),
        "forecast_longitude": (result.weather or {}).get("forecast_longitude"),
        "forecast_cache_age_hours": (result.weather or {}).get("forecast_cache_age_hours"),
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
            preferred_max_approach_time_hours=planning_profile.preferred_max_approach_time_hours,
            absolute_max_approach_time_hours=planning_profile.absolute_max_approach_time_hours,
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
        "preferred_duration_days": opportunity.get("preferred_duration_days"),
        "preferred_duration_difference_days": opportunity.get("preferred_duration_difference_days"),
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
        "preferred_max_approach_time_hours": opportunity.get("preferred_max_approach_time_hours"),
        "absolute_max_approach_time_hours": opportunity.get("absolute_max_approach_time_hours"),
        "preferred_approach_time_overrun_hours": opportunity.get("preferred_approach_time_overrun_hours"),
        "verdict": opportunity["verdict"],
        "main_reason": opportunity["main_reason"],
        "main_tradeoff": opportunity["main_tradeoff"],
        "weather_status": opportunity.get("weather_status"),
        "weather_provider_used": opportunity.get("weather_provider_used"),
        "forecast_location_name": opportunity.get("forecast_location_name"),
        "forecast_cache_age_hours": opportunity.get("forecast_cache_age_hours"),
    }


def _weather_evaluation(forecasts: list[Any], window: Any) -> dict[str, Any]:
    window_forecasts = [forecast for forecast in forecasts if forecast.date in window.daily_scores]
    precipitation = [forecast.precipitation_amount_mm or 0 for forecast in window_forecasts]
    precipitation_probability = [forecast.precipitation_probability or 0 for forecast in window_forecasts]
    temperatures = [forecast.temperature_c for forecast in window_forecasts if forecast.temperature_c is not None]
    wind_speeds = [forecast.wind_speed_kmh or 0 for forecast in window_forecasts]
    wind_gusts = [forecast.wind_gusts_kmh or 0 for forecast in window_forecasts]
    cloud_cover = [forecast.cloud_cover or 0 for forecast in window_forecasts]
    daily = []
    aggregate_penalties: list[dict[str, Any]] = []
    for forecast in window_forecasts:
        day_penalties = _weather_penalties_for_forecast(forecast)
        daily.append(
            {
                "date": forecast.date,
                "score": window.daily_scores.get(forecast.date),
                "precipitation_mm": forecast.precipitation_amount_mm,
                "precipitation_probability": forecast.precipitation_probability,
                "temperature_c": forecast.temperature_c,
                "wind_speed_kmh": forecast.wind_speed_kmh,
                "wind_gust_kmh": forecast.wind_gusts_kmh,
                "cloud_coverage": forecast.cloud_cover,
                "weather_code": forecast.weather_code,
                "penalties": day_penalties,
            }
        )
        aggregate_penalties.extend(day_penalties)
    return {
        "aggregate": {
            "score": window.trip_score,
            "stability_score": window.weather_stability_score,
            "minimum_temperature": min(temperatures) if temperatures else None,
            "maximum_temperature": max(temperatures) if temperatures else None,
            "total_precipitation_mm": round(sum(precipitation), 1),
            "maximum_precipitation_probability": max(precipitation_probability) if precipitation_probability else None,
            "maximum_wind_speed_kmh": max(wind_speeds) if wind_speeds else None,
            "maximum_wind_gust_kmh": max(wind_gusts) if wind_gusts else None,
            "maximum_cloud_coverage": max(cloud_cover) if cloud_cover else None,
            "evaluated_days": len(window_forecasts),
            "bad_weather_penalty": window.trip_score_breakdown.bad_weather_penalty,
        },
        "daily": daily,
        "penalties": aggregate_penalties,
    }


def _weather_penalties_for_forecast(forecast: Any) -> list[dict[str, Any]]:
    penalties: list[dict[str, Any]] = []
    precipitation_probability = forecast.precipitation_probability or 0
    if precipitation_probability:
        penalties.append(
            {
                "reason": "regenverwachting",
                "value": precipitation_probability,
                "threshold": 0,
                "penalty": round(min(35.0, precipitation_probability * 0.35)),
            }
        )
    precipitation_amount = forecast.precipitation_amount_mm or 0
    if precipitation_amount:
        penalties.append(
            {
                "reason": "neerslaghoeveelheid",
                "value": precipitation_amount,
                "threshold": 0,
                "penalty": round(min(30.0, precipitation_amount * 10)),
            }
        )
    wind_speed = forecast.wind_speed_kmh or 0
    if wind_speed > 20:
        penalties.append(
            {
                "reason": "wind",
                "value": wind_speed,
                "threshold": 20,
                "penalty": round(min(20.0, (wind_speed - 20) * 0.7)),
            }
        )
    wind_gusts = forecast.wind_gusts_kmh or 0
    if wind_gusts > 35:
        penalties.append(
            {
                "reason": "windstoten",
                "value": wind_gusts,
                "threshold": 35,
                "penalty": round(min(25.0, (wind_gusts - 35) * 0.8)),
            }
        )
    temperature = forecast.temperature_c
    if temperature is not None and (temperature < 14 or temperature > 32):
        penalties.append(
            {
                "reason": "temperatuur",
                "value": temperature,
                "threshold": "14-32",
                "penalty": _temperature_penalty(temperature),
            }
        )
    cloud_cover = forecast.cloud_cover or 0
    if cloud_cover > 60:
        penalties.append(
            {
                "reason": "bewolking",
                "value": cloud_cover,
                "threshold": 60,
                "penalty": 8 if cloud_cover > 80 else 4,
            }
        )
    bad_weather_codes = {
        51,
        53,
        55,
        56,
        57,
        61,
        63,
        65,
        66,
        67,
        71,
        73,
        75,
        77,
        80,
        81,
        82,
        85,
        86,
        95,
        96,
        99,
    }
    if forecast.weather_code in bad_weather_codes:
        penalties.append(
            {
                "reason": "weercode",
                "value": forecast.weather_code,
                "threshold": "droog/veilig",
                "penalty": 15,
            }
        )
    return penalties


def _temperature_penalty(temperature: float) -> int:
    if temperature < 8:
        return round(min(30.0, (8 - temperature) * 4))
    if temperature < 14:
        return round((14 - temperature) * 2)
    if temperature > 32:
        return round(min(25.0, (temperature - 32) * 3))
    return 0


def _strategy_label(strategy: str) -> str:
    return {
        TRAVEL_STRATEGY_MOTORCYCLE_DIRECT: "Direct / snelweg",
        TRAVEL_STRATEGY_MOTORCYCLE_SCENIC: "Binnendoor / scenic",
        TRAVEL_STRATEGY_TRAILER: "Aanhangertransport",
    }.get(strategy, strategy)


def _destination_weather_metadata(
    destination: DestinationArea,
    provider: str | None,
    status: str,
    quality_reason: str,
    *,
    cache_age_hours: float | None = None,
    fetched_at: str | None = None,
    missing_fields: list[str] | None = None,
    from_cache: bool | None = None,
) -> dict[str, Any]:
    return {
        "weather_status": status,
        "weather_provider_used": provider or "none",
        "weather_data_quality_reason": quality_reason,
        "forecast_location_name": destination.name,
        "forecast_latitude": round(destination.latitude, 3),
        "forecast_longitude": round(destination.longitude, 3),
        "forecast_cache_age_hours": cache_age_hours,
        "fetched_at": fetched_at,
        "missing_fields": missing_fields or [],
        "from_cache": from_cache,
    }


def _weather_status_with_results(status: dict[str, Any], results: list[DestinationResult]) -> dict[str, Any]:
    """Add destination-level weather coverage to the compact provider status."""
    relevant = [result for result in results if result.reachable]
    destination_status: dict[str, dict[str, Any]] = {}
    fresh = stale = without = 0
    live_calls = cache_hits = failed = 0
    last_processed: str | None = None
    for result in relevant:
        weather = result.weather or {}
        name = result.destination.name
        weather_status = str(weather.get("weather_status") or "unavailable")
        if weather_status in {"ok", "partial"}:
            fresh += 1
        elif weather_status == "stale":
            stale += 1
        else:
            without += 1
        if weather.get("from_cache") is True:
            cache_hits += 1
        elif weather_status in {"ok", "partial", "stale"}:
            live_calls += 1
        else:
            failed += 1
        last_processed = str(weather.get("forecast_location_name") or name)
        destination_status[name] = {
            "status": weather_status,
            "provider": weather.get("weather_provider_used"),
            "forecast_location": weather.get("forecast_location_name") or name,
            "cache_age_minutes": _hours_to_minutes(weather.get("forecast_cache_age_hours")),
            "from_cache": weather.get("from_cache"),
            "missing_fields": weather.get("missing_fields", []),
        }
    enriched = dict(status)
    if "forecast_location_name" in enriched:
        enriched["last_processed_forecast_location"] = enriched.pop("forecast_location_name")
    enriched["forecast_coverage"] = {
        "destinations_requested": len(relevant),
        "destinations_with_fresh_weather": fresh,
        "destinations_with_stale_weather": stale,
        "destinations_without_weather": without,
    }
    enriched["destination_weather_status"] = destination_status
    enriched["weather_fetch_summary"] = {
        "destinations_configured": len(results),
        "destinations_skipped_by_hard_constraint": len([result for result in results if not result.reachable]),
        "destinations_with_potential_windows": len(relevant),
        "live_provider_calls": live_calls,
        "cache_hits": cache_hits,
        "failed_fetches": failed,
    }
    if last_processed:
        enriched["last_processed_forecast_location"] = last_processed
    return enriched


def _mode_status(planning_profile: TripPlanningProfile) -> dict[str, dict[str, Any]]:
    return {
        TRAVEL_STRATEGY_MOTORCYCLE_DIRECT: {
            "enabled": True,
            "label": _strategy_label(TRAVEL_STRATEGY_MOTORCYCLE_DIRECT),
        },
        TRAVEL_STRATEGY_MOTORCYCLE_SCENIC: {
            "enabled": True,
            "label": _strategy_label(TRAVEL_STRATEGY_MOTORCYCLE_SCENIC),
        },
        TRAVEL_STRATEGY_TRAILER: {
            "enabled": planning_profile.trailer_support_enabled and planning_profile.trailer_available,
            "label": _strategy_label(TRAVEL_STRATEGY_TRAILER),
            "reason": None
            if planning_profile.trailer_support_enabled and planning_profile.trailer_available
            else (
                "Aanhangertransport staat uit"
                if not planning_profile.trailer_support_enabled
                else "Aanhanger vandaag niet beschikbaar"
            ),
        },
    }


def _disabled_modes_from_status(mode_status: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        mode: str(status.get("reason"))
        for mode, status in mode_status.items()
        if not status.get("enabled") and status.get("reason")
    }


def _route_approach_time_for_strategy(travel_time_minutes: int, planning_profile: TripPlanningProfile) -> float:
    approach_time = travel_time_minutes / 60
    if planning_profile.travel_strategy == TRAVEL_STRATEGY_MOTORCYCLE_SCENIC:
        return approach_time * 1.18
    return approach_time


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
        "weather_status": opportunity.get("weather_status"),
        "weather_provider_used": opportunity.get("weather_provider_used"),
        "forecast_location_name": opportunity.get("forecast_location_name"),
        "forecast_cache_age_hours": opportunity.get("forecast_cache_age_hours"),
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
        "weather_status": opportunity.get("weather_status"),
        "weather_provider_used": opportunity.get("weather_provider_used"),
        "forecast_location_name": opportunity.get("forecast_location_name"),
        "forecast_cache_age_hours": opportunity.get("forecast_cache_age_hours"),
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


def _evaluated_candidates(
    selected_opportunities: list[dict[str, Any]],
    all_opportunities: list[dict[str, Any]],
    excluded_destinations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommended_source = next(
        (opportunity for opportunity in all_opportunities if int(opportunity["ride_quality_score"]) >= 70),
        None,
    )
    recommended_key = _candidate_key(recommended_source) if recommended_source else None
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for opportunity in all_opportunities:
        key = _candidate_key(opportunity)
        if key in seen:
            continue
        seen.add(key)
        score = int(opportunity["ride_quality_score"])
        result = "recommended" if key == recommended_key else "eligible" if score >= 70 else "compromise"
        rows.append(_candidate_from_opportunity(opportunity, result))
    for item in excluded_destinations:
        rows.append(_candidate_from_exclusion(item))
    return rows


def _candidate_key(opportunity: dict[str, Any]) -> tuple[Any, ...]:
    return (
        opportunity.get("destination"),
        opportunity.get("strategy"),
        opportunity.get("start_date"),
        opportunity.get("end_date"),
        opportunity.get("duration_days"),
    )


def _candidate_from_opportunity(opportunity: dict[str, Any], result: str) -> dict[str, Any]:
    reason_code = None if result in {"recommended", "eligible"} else "below_minimum_score"
    primary_reason = _candidate_result_label(result) if reason_code is None else "Score onder adviesdrempel"
    evidence = _opportunity_evidence(opportunity, result)
    score_breakdown = opportunity.get("score_breakdown", {})
    return {
        "status": result,
        "result": result,
        "destination": opportunity.get("destination"),
        "mode": opportunity.get("strategy"),
        "mode_label": opportunity.get("strategy_label"),
        "period": opportunity.get("period"),
        "period_start": opportunity.get("start_date"),
        "period_end": opportunity.get("end_date"),
        "duration_days": opportunity.get("duration_days"),
        "total_score": opportunity.get("ride_quality_score"),
        "weather_score": opportunity.get("weather_score"),
        "stability_score": opportunity.get("stability_score"),
        "trip_efficiency_score": opportunity.get("trip_efficiency_score"),
        "approach_time_hours": opportunity.get("approach_time_hours"),
        "return_time_hours": opportunity.get("return_time_hours"),
        "total_transport_time_hours": opportunity.get("total_transport_time_hours"),
        "available_trip_hours": opportunity.get("total_available_time_hours"),
        "usable_destination_hours": opportunity.get("estimated_destination_ride_time_hours"),
        "preferred_max_approach_time_hours": opportunity.get("preferred_max_approach_time_hours"),
        "absolute_max_approach_time_hours": opportunity.get("absolute_max_approach_time_hours"),
        "preferred_approach_time_overrun_hours": opportunity.get("preferred_approach_time_overrun_hours"),
        "absolute_approach_time_overrun_hours": opportunity.get("absolute_approach_time_overrun_hours"),
        "eligibility_result": _candidate_result_label(result),
        "primary_reason_code": reason_code,
        "primary_reason": primary_reason,
        "evidence": evidence,
        "supporting_evidence": "; ".join(evidence),
        "secondary_reasons": opportunity.get("tradeoffs", []),
        "preference_warnings": opportunity.get("preference_warnings", []),
        "hard_exclusion_reasons": opportunity.get("hard_exclusion_reasons", []),
        "weather_provider": opportunity.get("weather_provider_used"),
        "forecast_location": opportunity.get("forecast_location_name"),
        "weather_status": opportunity.get("weather_status"),
        "cache_age_hours": opportunity.get("forecast_cache_age_hours"),
        "cache_age_minutes": _hours_to_minutes(opportunity.get("forecast_cache_age_hours")),
        "missing_data": [],
        "score_breakdown": {
            "weather": score_breakdown.get("weather_score"),
            "distance": score_breakdown.get("distance_score"),
            "availability": 100,
            "stability": score_breakdown.get("stability_score"),
            "temperature": score_breakdown.get("temperature_score"),
            "trip_efficiency": score_breakdown.get("trip_efficiency_score"),
            "final": score_breakdown.get("ride_quality_score"),
        },
        "weather_evaluation": opportunity.get("weather_evaluation"),
        "hard_rule_results": {
            "weather_data": opportunity.get("weather_status") in {"ok", "partial", "stale"},
            "score_threshold": (opportunity.get("ride_quality_score") or 0) >= 70,
            "approach_time": not opportunity.get("hard_exclusion_reasons"),
        },
    }


def _candidate_from_exclusion(item: dict[str, Any]) -> dict[str, Any]:
    reason_code = str(item.get("reason") or "unknown")
    status = "unavailable" if reason_code == "no_forecast_data" else "rejected"
    destination = item.get("destination")
    details = str(item.get("details") or "Geen detail beschikbaar.")
    return {
        "status": status,
        "result": status,
        "destination": destination,
        "mode": None,
        "mode_label": "n.v.t.",
        "period": "Niet beoordeeld",
        "period_start": None,
        "period_end": None,
        "duration_days": None,
        "total_score": None,
        "weather_score": None,
        "eligibility_result": _candidate_result_label(status),
        "primary_reason_code": reason_code,
        "primary_reason": _reason_label(reason_code),
        "evidence": [details],
        "supporting_evidence": details,
        "secondary_reasons": [],
        "weather_provider": item.get("weather_provider_used"),
        "forecast_location": item.get("forecast_location_name") or destination,
        "weather_status": item.get("weather_status"),
        "cache_age_hours": item.get("forecast_cache_age_hours"),
        "cache_age_minutes": _hours_to_minutes(item.get("forecast_cache_age_hours")),
        "missing_data": ["weather"] if reason_code == "no_forecast_data" else [],
        "score_breakdown": {
            "weather": None,
            "distance": None,
            "availability": None,
            "stability": None,
            "temperature": None,
            "trip_efficiency": None,
            "final": None,
        },
        "hard_rule_results": {
            "weather_data": reason_code != "no_forecast_data",
            "distance": reason_code != "too_far",
        },
    }


def _opportunity_evidence(opportunity: dict[str, Any], result: str) -> list[str]:
    score = opportunity.get("ride_quality_score")
    weather = opportunity.get("weather_score")
    duration = opportunity.get("duration_days")
    approach = opportunity.get("approach_time_hours")
    preferred_approach = opportunity.get("preferred_max_approach_time_hours")
    absolute_approach = opportunity.get("absolute_max_approach_time_hours")
    evidence = [
        f"Totaalscore {score}/100; adviesdrempel 70.",
        f"Weerscore {weather}/100.",
        f"Duur {duration} dagen.",
    ]
    preferred_duration = opportunity.get("preferred_duration_days")
    if preferred_duration is not None and preferred_duration != duration:
        evidence.append(f"Wijkt af van voorkeursduur {preferred_duration} dagen; dit is geen harde afwijzing.")
    if approach is not None:
        if preferred_approach is not None:
            evidence.append(
                f"Aanrijtijd {float(approach):.1f} uur; voorkeur maximaal {float(preferred_approach):.1f} uur."
            )
        else:
            evidence.append(f"Aanrijtijd {float(approach):.1f} uur; geen aanrijtijdvoorkeur ingesteld.")
    if absolute_approach is not None:
        evidence.append(f"Absolute aanrijlimiet {float(absolute_approach):.1f} uur.")
    else:
        evidence.append("Geen absolute aanrijlimiet ingesteld.")
    if result == "recommended":
        evidence.insert(0, "Hoogst gerangschikte geschikte kandidaat binnen de actieve instellingen.")
    elif result == "eligible":
        evidence.insert(0, "Voldoet aan harde eisen, maar een andere kandidaat staat hoger.")
    else:
        evidence.insert(0, "Bruikbaar compromis, maar onder de adviesdrempel.")
    return evidence


def _evaluation_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "recommended": 0,
        "eligible": 0,
        "compromise": 0,
        "rejected": 0,
        "unavailable": 0,
    }
    reason_counts: dict[str, int] = {}
    for candidate in candidates:
        result = str(candidate.get("result") or "unavailable")
        if result == "compromises":
            result = "compromise"
        if result in counts:
            counts[result] += 1
        reason = candidate.get("primary_reason_code")
        if result in {"rejected", "unavailable"} and reason:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    compromise_reason_counts: dict[str, int] = {}
    for candidate in candidates:
        if candidate.get("result") == "compromise" and candidate.get("primary_reason_code"):
            reason = str(candidate["primary_reason_code"])
            compromise_reason_counts[reason] = compromise_reason_counts.get(reason, 0) + 1
    return {
        "total_candidates": len(candidates),
        "recommended": counts["recommended"],
        "eligible": counts["eligible"],
        "compromises": counts["compromise"],
        "rejected": counts["rejected"],
        "unavailable": counts["unavailable"],
        "suitable": counts["recommended"] + counts["eligible"],
        "rejection_reason_counts": reason_counts,
        "rejection_reason_labels": {reason: _reason_label(reason) for reason in reason_counts},
        "compromise_reason_counts": compromise_reason_counts,
        "compromise_reason_labels": {reason: _reason_label(reason) for reason in compromise_reason_counts},
    }


def _advice_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for status in ("recommended", "eligible", "compromise", "unavailable"):
        for candidate in candidates:
            if candidate.get("result") == status:
                return candidate
    return None


def _candidate_result_label(result: str) -> str:
    return {
        "recommended": "Aanbevolen",
        "eligible": "Geschikt alternatief",
        "compromise": "Compromis",
        "rejected": "Afgewezen",
        "unavailable": "Niet beoordeelbaar",
    }.get(result, result)


def _reason_label(reason: str) -> str:
    return {
        "below_minimum_score": "Score onder adviesdrempel",
        "too_far": "Buiten ingestelde afstand",
        "no_forecast_data": "Geen bruikbare weerdata beschikbaar",
        "no_complete_window": "Geen volledig ritvenster",
        "weekend_only_filter": "Past niet binnen weekendfilter",
        "preferred_start_day_filter": "Past niet bij voorkeursdag",
        "trailer_required_but_unavailable": "Aanhanger nodig, maar niet beschikbaar",
        "trailer_disabled": "Aanhangertransport staat uit",
        "absolute_approach_time_exceeded": "Absolute aanrijlimiet overschreden",
        "approach_time_too_high": "Aanrijtijd te hoog",
        "insufficient_destination_ride_time": "Te weinig bruikbare rijtijd",
        "disabled": "Bestemming uitgeschakeld",
    }.get(reason, reason)


def _hours_to_minutes(value: Any) -> int | None:
    try:
        return round(float(value) * 60)
    except (TypeError, ValueError):
        return None


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
                "forecast_location_name": (result.weather or {}).get("forecast_location_name"),
                "weather_provider_used": (result.weather or {}).get("weather_provider_used"),
                "weather_status": (result.weather or {}).get("weather_status"),
                "forecast_cache_age_hours": (result.weather or {}).get("forecast_cache_age_hours"),
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
    if "absolute max approach time" in normalized:
        return "absolute_approach_time_exceeded"
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
        "absolute_approach_time_exceeded": (
            "De aanrijtijd is hoger dan de expliciet ingestelde absolute aanrijlimiet."
        ),
        "approach_time_too_high": "De aanrijtijd is hoger dan de ingestelde voorkeurswaarde.",
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
            "preferred_max_approach_time_hours": planning_profile.preferred_max_approach_time_hours,
            "absolute_max_approach_time_hours": planning_profile.absolute_max_approach_time_hours,
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
    min_days = MIN_TRIP_DURATION_DAYS if mode == "flexible" or max_days == 1 else min(2, max_days)
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


def _weather_providers(
    api_client: Any,
    hass: HomeAssistant | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize one or more weather provider clients."""
    if isinstance(api_client, dict):
        providers = {str(provider): client for provider, client in api_client.items()}
    elif isinstance(api_client, (list, tuple)):
        providers = {
            str(getattr(client, "provider_name", f"provider_{index + 1}")): client
            for index, client in enumerate(api_client)
        }
    else:
        providers = {str(getattr(api_client, "provider_name", "open_meteo")): api_client}
    weather_map = (config or {}).get(CONF_WEATHER_ENTITY_MAP)
    if hass is not None and isinstance(weather_map, dict) and weather_map:
        providers["home_assistant_weather_entity"] = HomeAssistantWeatherEntityClient(hass, weather_map)
    return providers


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
    preferred_approach_time = _helper_float(
        hass,
        MAX_APPROACH_TIME_ENTITY,
        float(config.get(CONF_PREFERRED_MAX_APPROACH_TIME_HOURS, DEFAULT_PREFERRED_MAX_APPROACH_TIME_HOURS)),
        minimum=0.5,
        maximum=12.0,
        native_controls=native_controls,
        control_key=CONTROL_MAX_APPROACH_TIME_HOURS,
        native_entity_id=NATIVE_MAX_APPROACH_TIME_ENTITY,
    )
    absolute_approach_time = _optional_float(config.get(CONF_ABSOLUTE_MAX_APPROACH_TIME_HOURS))
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
        max_approach_time_hours=preferred_approach_time,
        preferred_max_approach_time_hours=preferred_approach_time,
        absolute_max_approach_time_hours=absolute_approach_time,
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


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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
    if getattr(experience, "preference_warnings", []):
        tradeoffs.extend(getattr(experience, "preference_warnings", []))
    if experience.temperature_score < 80:
        tradeoffs.append(f"Temperatuurcomfort scoort {experience.temperature_score}/100.")
    if experience.distance_score < 80:
        tradeoffs.append(f"Afstand scoort {experience.distance_score}/100; de aanrijroute kan lang zijn.")
    if experience.trip_efficiency_score < 80:
        tradeoffs.append(
            f"Ritefficientie scoort {experience.trip_efficiency_score}/100; er gaat relatief veel tijd naar "
            "aan- en terugrijden."
        )
    if getattr(experience, "preferred_approach_time_overrun_hours", 0) > 0:
        tradeoffs.append(
            "Aanrijtijd overschrijdt de voorkeur: "
            f"{experience.approach_time_hours:.1f} uur tegenover "
            f"{experience.preferred_max_approach_time_hours:.1f} uur voorkeur. "
            "Dit verlaagt de ritefficientie, maar wijst de rit niet af."
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
