"""Data coordinator for RideRadar."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OpenMeteoClient, RideRadarApiError
from .const import (
    CONF_ACTIVITY_PROFILE,
    CONF_DESTINATIONS,
    CONF_DETOUR_FACTOR,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_DETOUR_FACTOR,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_MAX_ROUTE_DISTANCE_KM,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .destinations import destinations_from_config
from .models import DestinationArea, DestinationResult, RideRadarConfigError
from .routing import FallbackRoutingClient, RoutingClient
from .scoring import calculate_ride_score

LOGGER = logging.getLogger(__name__)

CoordinatorData = dict[str, Any]


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
        self.routing_client = routing_client or FallbackRoutingClient(
            detour_factor=float(self.config.get(CONF_DETOUR_FACTOR, DEFAULT_DETOUR_FACTOR))
        )

    @property
    def config(self) -> dict[str, Any]:
        """Return merged config entry data and options."""
        return {**self.entry.data, **self.entry.options}

    async def _async_update_data(self) -> CoordinatorData:
        """Refresh route and forecast data."""
        config = self.config
        try:
            start_latitude = float(config[CONF_START_LATITUDE])
            start_longitude = float(config[CONF_START_LONGITUDE])
            max_route_distance_km = float(config.get(CONF_MAX_ROUTE_DISTANCE_KM, DEFAULT_MAX_ROUTE_DISTANCE_KM))
            forecast_days = int(config.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS))
            activity_profile = str(config.get(CONF_ACTIVITY_PROFILE, DEFAULT_ACTIVITY_PROFILE))
            destinations = destinations_from_config(config.get(CONF_DESTINATIONS))
        except (KeyError, TypeError, ValueError, RideRadarConfigError) as err:
            raise UpdateFailed(f"Invalid RideRadar configuration: {err}") from err

        enabled_destinations = [destination for destination in destinations if destination.enabled]
        if not enabled_destinations:
            return {
                "results": [],
                "best": None,
                "destination_count": 0,
                "summary": "No enabled destinations configured",
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
                        activity_profile,
                    )
                )
        except RideRadarApiError as err:
            raise UpdateFailed(str(err)) from err
        except (TimeoutError, OSError, ValueError) as err:
            raise UpdateFailed(f"Could not update RideRadar data: {err}") from err

        best = max(
            (result for result in results if result.available and result.reachable),
            key=lambda item: item.best_score or 0,
            default=None,
        )
        return {
            "results": results,
            "best": best,
            "destination_count": len(results),
            "summary": _summary(best),
        }

    async def _evaluate_destination(
        self,
        destination: DestinationArea,
        start_latitude: float,
        start_longitude: float,
        max_route_distance_km: float,
        forecast_days: int,
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
                reachable=False,
                available=True,
                explanation=f"Outside configured range ({route.distance_km:.0f} km)",
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
        explanation = scores[best_day].explanation if best_day else "No forecast available"
        return DestinationResult(
            destination=destination,
            route=route,
            forecasts=forecasts,
            scores=scores,
            best_day=best_day,
            best_score=best_score,
            best_forecast=best_forecast,
            reachable=True,
            available=bool(forecasts),
            explanation=explanation,
        )


def _summary(best: DestinationResult | None) -> str:
    if best is None:
        return "No reachable destination with forecast data"
    return f"{best.destination.name}: {best.best_score}/100 on {best.best_day}. {best.explanation}"
