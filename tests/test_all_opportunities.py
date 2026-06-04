"""Tests for RideRadar all-opportunities planning table."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar.const import (
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DETOUR_FACTOR,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_ADDRESS,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    CONF_TRAILER_SUPPORT_ENABLED,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_DETOUR_FACTOR,
    DOMAIN,
)
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.models import DailyForecast, DestinationArea, RouteInfo
from custom_components.rideradar.sensor import async_setup_entry as async_setup_sensor


class FakeApiClient:
    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        return [
            DailyForecast("2026-06-04", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-05", 23, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-06", 24, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-07", 22, 0, 0, 10, 15, 20, 1),
        ][:forecast_days]


class FakeRoutingClient:
    async def get_route(self, start_latitude, start_longitude, destination, activity_profile):
        return RouteInfo(80, 45, "fake")


def _entry(trailer_support_enabled=False):
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_START_ADDRESS: "Private start",
            CONF_START_LATITUDE: 50.0,
            CONF_START_LONGITUDE: 4.0,
            CONF_MAX_ROUTE_DISTANCE_KM: 500,
            CONF_FORECAST_DAYS: 4,
            CONF_PREFERRED_TRIP_DURATION: "2",
            CONF_CUSTOM_TRIP_DURATION_DAYS: 4,
            CONF_ACTIVITY_PROFILE: DEFAULT_ACTIVITY_PROFILE,
            CONF_DETOUR_FACTOR: DEFAULT_DETOUR_FACTOR,
            "custom_destinations": [DestinationArea("Sauerland", "Germany", 51.0, 8.0).as_dict()],
            "enabled_default_destinations": [],
            CONF_TRAILER_SUPPORT_ENABLED: trailer_support_enabled,
        },
    )


async def test_all_opportunities_include_multiple_durations_and_strategies(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration_days", "4")

    data = await coordinator._async_update_data()
    opportunities = data["all_opportunities"]

    assert {item["duration_days"] for item in opportunities} == {2, 3, 4}
    assert {item["strategy"] for item in opportunities} == {"motorcycle_direct", "motorcycle_scenic"}
    assert {item["strategy_label"] for item in opportunities} == {"Direct / snelweg", "Binnendoor / scenic"}


async def test_all_opportunities_fields_are_sortable_and_scores_are_consistent(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())

    data = await coordinator._async_update_data()
    item = data["all_opportunities"][0]

    for field in ("score", "duration_days", "destination", "strategy", "start_date"):
        assert field in item
    assert item["score"] == item["ride_quality_score"]
    assert item["distance_km"] == item["route_distance_km"]
    assert item["main_reason"]
    assert item["main_tradeoff"]
    assert item["verdict"] in {
        "Excellent",
        "Excellent weekend",
        "Very good",
        "Good",
        "Mediocre",
        "Poor",
        "Not recommended",
    }


async def test_all_opportunities_hide_trailer_when_support_is_disabled(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass, _entry(trailer_support_enabled=False), FakeApiClient(), FakeRoutingClient()
    )
    coordinator.set_runtime_control("trailer_available", "on")

    data = await coordinator._async_update_data()

    assert "trailer" not in {item["strategy"] for item in data["all_opportunities"]}


async def test_all_opportunities_include_trailer_only_when_available(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass, _entry(trailer_support_enabled=True), FakeApiClient(), FakeRoutingClient()
    )
    coordinator.set_runtime_control("trailer_available", "off")

    unavailable = await coordinator._async_update_data()
    assert "trailer" not in {item["strategy"] for item in unavailable["all_opportunities"]}

    coordinator.set_runtime_control("trailer_available", "on")
    available = await coordinator._async_update_data()
    assert "trailer" in {item["strategy"] for item in available["all_opportunities"]}


async def test_all_opportunities_attribute_size_is_limited(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())

    data = await coordinator._async_update_data()

    assert len(data["all_opportunities"]) <= data["all_opportunities_attribute_limit"]
    assert data["all_opportunities_candidate_count"] >= len(data["all_opportunities"])


async def test_all_opportunities_sensor_exists(hass) -> None:
    entry = _entry()
    coordinator = RideRadarDataCoordinator(hass, entry, FakeApiClient(), FakeRoutingClient())
    coordinator.data = await coordinator._async_update_data()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    entities = []

    await async_setup_sensor(hass, entry, entities.extend)

    sensor = next(entity for entity in entities if entity.unique_id.endswith("_all_opportunities"))
    assert sensor.native_value == len(coordinator.data["all_opportunities"])
    assert sensor.extra_state_attributes["opportunities"] == coordinator.data["all_opportunities"]
