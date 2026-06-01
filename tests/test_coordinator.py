"""Tests for RideRadar coordinator behavior."""

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar.api import RideRadarApiError
from custom_components.rideradar.const import (
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DESTINATIONS,
    CONF_DETOUR_FACTOR,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_ADDRESS,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
    DEFAULT_DETOUR_FACTOR,
    DEFAULT_PREFERRED_TRIP_DURATION,
    DOMAIN,
)
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.models import DailyForecast, DestinationArea, RouteInfo


class FakeApiClient:
    def __init__(self, forecasts=None, error=None) -> None:
        self.forecasts = forecasts or [
            DailyForecast("2026-06-02", 22, 5, 0, 12, 20, 30, 1),
            DailyForecast("2026-06-03", 12, 60, 2, 25, 40, 90, 61),
        ]
        self.error = error

    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        if self.error:
            raise self.error
        return self.forecasts[:forecast_days]


class FakeRoutingClient:
    def __init__(self, distance_km=100) -> None:
        self.distance_km = distance_km

    async def get_route(self, start_latitude, start_longitude, destination, activity_profile):
        return RouteInfo(self.distance_km, 90, f"fake_{activity_profile}")


class DestinationForecastApiClient:
    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        if latitude == 51.0:
            return [
                DailyForecast("Friday", 24, 0, 0, 10, 15, 10, 1),
                DailyForecast("Saturday", 12, 95, 10, 45, 70, 95, 95),
                DailyForecast("Sunday", 24, 0, 0, 10, 15, 10, 1),
            ][:forecast_days]
        return [
            DailyForecast("Friday", 22, 10, 0, 12, 18, 30, 2),
            DailyForecast("Saturday", 21, 10, 0, 12, 18, 30, 2),
            DailyForecast("Sunday", 20, 10, 0, 12, 18, 30, 2),
        ][:forecast_days]


def _entry(destinations=None, max_distance=300):
    destination_data = destinations
    if destination_data is None:
        destination_data = [
            DestinationArea("Test Destination", "Test Region", 51.0, 5.0).as_dict(),
        ]
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_START_ADDRESS: "Private start",
            CONF_START_LATITUDE: 50.0,
            CONF_START_LONGITUDE: 4.0,
            CONF_MAX_ROUTE_DISTANCE_KM: max_distance,
            CONF_FORECAST_DAYS: 2,
            CONF_PREFERRED_TRIP_DURATION: DEFAULT_PREFERRED_TRIP_DURATION,
            CONF_CUSTOM_TRIP_DURATION_DAYS: DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
            CONF_ACTIVITY_PROFILE: DEFAULT_ACTIVITY_PROFILE,
            CONF_DETOUR_FACTOR: DEFAULT_DETOUR_FACTOR,
            CONF_DESTINATIONS: destination_data,
        },
    )


async def test_coordinator_selects_best_destination(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["destination_count"] == 1
    assert data["best"].destination.name == "Test Destination"
    assert data["best"].best_start_day == "2026-06-02"
    assert data["best"].trip_score is not None
    assert "Test Destination" in data["summary"]


async def test_coordinator_ranks_destinations_by_trip_score(hass) -> None:
    destinations = [
        DestinationArea("Spiky Daily Scores", "Test Region", 51.0, 5.0).as_dict(),
        DestinationArea("Stable Trip", "Test Region", 52.0, 5.0).as_dict(),
    ]
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=destinations),
        DestinationForecastApiClient(),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["best"].destination.name == "Stable Trip"
    assert data["best"].trip_score > data["results"][0].trip_score


async def test_coordinator_handles_empty_destination_list(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(destinations=[]), FakeApiClient(), FakeRoutingClient())

    data = await coordinator._async_update_data()

    assert data["destination_count"] == 0
    assert data["best"] is None
    assert data["summary"] == "No enabled destinations configured"


async def test_coordinator_marks_unreachable_destination_without_fetching_weather(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(max_distance=50),
        FakeApiClient(),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    result = data["results"][0]
    assert result.reachable is False
    assert result.trip_score is None
    assert data["best"] is None


async def test_coordinator_does_not_rank_limited_forecast_as_complete_trip(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(forecasts=[DailyForecast("Friday", 22, 0, 0, 10, 15, 20, 1)]),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["best"] is None
    assert data["results"][0].trip_score is None


async def test_coordinator_raises_update_failed_when_api_unavailable(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(error=RideRadarApiError("Open-Meteo down")),
        FakeRoutingClient(),
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
