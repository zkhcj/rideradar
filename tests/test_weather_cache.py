"""Tests for RideRadar forecast caching and provider budgeting."""

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.rideradar.api import RideRadarApiError
from custom_components.rideradar.const import CONF_WEATHER_ENTITY_MAP
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.models import DailyForecast, DestinationArea
from custom_components.rideradar.sensor import async_setup_entry as async_setup_sensor
from tests.test_coordinator import FakeRoutingClient, _entry


class CountingApiClient:
    provider_name = "openweather"

    def __init__(self, forecasts=None, error=None) -> None:
        self.calls = 0
        self.requests = []
        self.error = error
        self.forecasts = forecasts or [
            DailyForecast("2026-06-04", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-05", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1),
        ]

    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        self.calls += 1
        self.requests.append((latitude, longitude, forecast_days))
        if self.error:
            raise self.error
        return self.forecasts[:forecast_days]


async def test_forecast_is_cached_across_recalculations_and_strategies(hass) -> None:
    api = CountingApiClient()
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), api, FakeRoutingClient())

    first = await coordinator._async_update_data()
    coordinator.set_runtime_control("travel_strategy", "Motorcycle Scenic Approach")
    second = await coordinator._async_update_data()

    assert api.calls == 1
    assert first["weather"]["weather_status"] == "ok"
    assert second["weather"]["weather_status"] == "ok"
    assert second["opportunities"][0]["strategy"] == "motorcycle_scenic"


async def test_forecast_is_deduplicated_by_location_and_horizon(hass) -> None:
    api = CountingApiClient()
    destinations = [
        DestinationArea("Same A", "Test", 51.0001, 5.0001).as_dict(),
        DestinationArea("Same B", "Test", 51.0002, 5.0002).as_dict(),
    ]
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=destinations, forecast_days=3),
        api,
        FakeRoutingClient(),
    )

    await coordinator._async_update_data()

    assert api.calls == 1


async def test_distinct_destinations_use_distinct_coordinate_cache_entries(hass) -> None:
    api = CountingApiClient()
    destinations = [
        DestinationArea("Sauerland", "Duitsland", 51.18, 8.25).as_dict(),
        DestinationArea("Harz", "Duitsland", 51.80, 10.62).as_dict(),
    ]
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=destinations, forecast_days=3),
        api,
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()

    assert api.calls == 2
    assert (51.18, 8.25, 3) in api.requests
    assert (51.80, 10.62, 3) in api.requests
    assert len(coordinator.forecast_cache._entries) == 2
    assert data["results"][0].weather["forecast_location_name"] == "Sauerland"
    assert data["results"][1].weather["forecast_location_name"] == "Harz"


async def test_home_weather_entity_is_not_used_for_remote_destination_without_mapping(hass) -> None:
    hass.states.async_set(
        "weather.forecast_home",
        "sunny",
        {
            "forecast": [
                {
                    "datetime": "2026-06-04",
                    "temperature": 22,
                    "precipitation_probability": 0,
                    "precipitation": 0,
                    "wind_speed": 10,
                }
            ]
        },
    )
    api = CountingApiClient(error=RideRadarApiError("Open-Meteo down"))
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=[DestinationArea("Sauerland", "Duitsland", 51.18, 8.25).as_dict()]),
        api,
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()

    assert data["best"] is None
    assert data["results"][0].weather["weather_provider_used"] == "none"
    assert data["results"][0].weather["forecast_location_name"] == "Sauerland"


async def test_destination_specific_ha_weather_entity_mapping_works(hass) -> None:
    hass.states.async_set(
        "weather.sauerland",
        "sunny",
        {
            "forecast": [
                {
                    "datetime": "2026-06-04",
                    "temperature": 22,
                    "precipitation_probability": 0,
                    "precipitation": 0,
                    "wind_speed": 10,
                    "wind_gust_speed": 15,
                    "cloud_coverage": 20,
                },
                {
                    "datetime": "2026-06-05",
                    "temperature": 23,
                    "precipitation_probability": 0,
                    "precipitation": 0,
                    "wind_speed": 10,
                    "wind_gust_speed": 15,
                    "cloud_coverage": 20,
                },
            ]
        },
    )
    api = CountingApiClient(error=RideRadarApiError("Open-Meteo down"))
    entry = _entry(destinations=[DestinationArea("Sauerland", "Duitsland", 51.18, 8.25).as_dict()])
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_WEATHER_ENTITY_MAP: {"Sauerland": "weather.sauerland"}})
    coordinator = RideRadarDataCoordinator(hass, entry, api, FakeRoutingClient())

    data = await coordinator._async_update_data()

    assert data["best"] is not None
    assert data["results"][0].weather["weather_provider_used"] == "home_assistant_weather_entity"
    assert data["results"][0].weather["weather_status"] == "partial"
    assert "weather_code" in data["results"][0].weather["missing_fields"]


async def test_stale_cache_is_used_when_provider_fails(hass) -> None:
    api = CountingApiClient()
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), api, FakeRoutingClient())
    await coordinator._async_update_data()
    key, entry = next(iter(coordinator.forecast_cache._entries.items()))
    entry["fetched_at"] = (dt_util.utcnow() - timedelta(hours=6)).isoformat()
    coordinator.forecast_cache._entries[key] = entry
    api.error = RideRadarApiError("OpenWeather returned HTTP 502")

    data = await coordinator._async_update_data()

    assert api.calls == 2
    assert data["weather"]["weather_status"] == "stale"
    assert data["best"] is not None


async def test_expired_cache_and_provider_failure_has_no_fake_bad_weather_score(hass) -> None:
    api = CountingApiClient(error=RideRadarApiError("OpenWeather returned HTTP 502"))
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), api, FakeRoutingClient())

    data = await coordinator._async_update_data()

    assert data["weather"]["weather_status"] == "unavailable"
    assert data["best"] is None
    assert data["opportunities"] == []
    assert data["results"][0].best_score is None
    assert data["results"][0].daily_scores == {}
    assert any(item["reason"] == "no_forecast_data" for item in data["excluded_destinations"])


async def test_rate_limited_provider_uses_fallback_and_backoff(hass) -> None:
    primary = CountingApiClient(error=RideRadarApiError("OpenWeather returned HTTP 429"))
    fallback = CountingApiClient()
    fallback.provider_name = "open_meteo"
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(forecast_days=3),
        {"openweather": primary, "open_meteo": fallback},
        FakeRoutingClient(),
    )

    first = await coordinator._async_update_data()
    second = await coordinator._async_update_data()

    assert primary.calls == 1
    assert fallback.calls == 1
    assert first["weather"]["provider_used"] == "open_meteo"
    assert first["weather"]["fallback_provider_used"] == "open_meteo"
    assert second["weather"]["providers"]["openweather"]["status"] == "backoff"


async def test_dashboard_sensor_reads_cached_state_without_provider_call(hass) -> None:
    api = CountingApiClient()
    entry = _entry(forecast_days=3)
    coordinator = RideRadarDataCoordinator(hass, entry, api, FakeRoutingClient())
    coordinator.data = await coordinator._async_update_data()
    hass.data["rideradar"] = {entry.entry_id: coordinator}
    entities = []

    await async_setup_sensor(hass, entry, entities.extend)
    weather_sensor = next(entity for entity in entities if entity.unique_id.endswith("_weather_status"))

    assert weather_sensor.native_value == "ok"
    assert weather_sensor.extra_state_attributes["provider_used"] == "openweather"
    assert api.calls == 1
