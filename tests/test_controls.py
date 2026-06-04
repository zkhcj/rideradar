"""Tests for RideRadar native control entities."""

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar.const import DOMAIN
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.models import DailyForecast
from custom_components.rideradar.number import async_setup_entry as async_setup_number
from custom_components.rideradar.select import async_setup_entry as async_setup_select
from custom_components.rideradar.switch import async_setup_entry as async_setup_switch
from tests.test_coordinator import FakeRoutingClient, _entry


class FakeApiClient:
    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        return [
            DailyForecast("2026-06-04", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-05", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1),
        ][:forecast_days]


class LongerFakeApiClient:
    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        return [
            DailyForecast("2026-06-04", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-05", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-07", 22, 0, 0, 10, 15, 20, 1),
        ][:forecast_days]


async def test_native_control_entities_are_created(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), FakeApiClient(), FakeRoutingClient())
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    entities = []

    await async_setup_select(hass, entry, entities.extend)
    await async_setup_number(hass, entry, entities.extend)
    await async_setup_switch(hass, entry, entities.extend)

    assert len(entities) == 9
    assert {entity.unique_id.rsplit("_", 1)[-1] for entity in entities}


async def test_native_control_values_override_legacy_helpers_and_options(hass) -> None:
    entry = _entry(forecast_days=3)
    coordinator = RideRadarDataCoordinator(hass, entry, FakeApiClient(), FakeRoutingClient())
    hass.states.async_set("input_number.rideradar_trip_duration_days", "1")
    coordinator.set_runtime_control("trip_duration_days", "3")

    data = await coordinator._async_update_data()

    assert data["selected_duration_days"] == 3
    assert data["max_duration_days"] == 3


async def test_native_control_entity_changes_trigger_refresh(hass, monkeypatch) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), FakeApiClient(), FakeRoutingClient())
    coordinator.async_request_refresh = AsyncMock()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    entities = []
    await async_setup_select(hass, entry, entities.extend)
    trip_duration = next(entity for entity in entities if entity.unique_id.endswith("_trip_duration"))
    monkeypatch.setattr(trip_duration, "async_write_ha_state", lambda: None)

    await trip_duration.async_select_option("1 day")

    assert coordinator.runtime_controls["trip_duration"] == "1 day"
    coordinator.async_request_refresh.assert_awaited_once()


async def test_native_trip_duration_change_changes_candidate_windows(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration", "1 day")
    one_day = await coordinator._async_update_data()
    coordinator.set_runtime_control("trip_duration", "2 days")
    two_days = await coordinator._async_update_data()

    assert len(one_day["results"][0].all_trip_windows) == 3
    assert len(two_days["results"][0].all_trip_windows) == 2


async def test_native_forecast_horizon_change_changes_opportunities(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=4), LongerFakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("forecast_horizon_days", "2")
    short = await coordinator._async_update_data()
    coordinator.set_runtime_control("forecast_horizon_days", "4")
    long = await coordinator._async_update_data()

    assert len(short["opportunities"]) < len(long["opportunities"])


async def test_native_weekend_only_filters_weekday_opportunities(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=4), LongerFakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration", "1 day")
    coordinator.set_runtime_control("weekend_only", "on")

    data = await coordinator._async_update_data()

    assert {item["start_date"] for item in data["opportunities"]} == {"2026-06-06", "2026-06-07"}


async def test_native_preferred_start_day_filters_windows(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=4), LongerFakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration", "1 day")
    coordinator.set_runtime_control("preferred_start_day", "Friday")

    data = await coordinator._async_update_data()

    assert [item["start_date"] for item in data["opportunities"]] == ["2026-06-05"]


async def test_native_travel_strategy_changes_trip_efficiency(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(forecast_days=3),
        FakeApiClient(),
        FakeRoutingClient(distance_km=260),
    )
    coordinator.set_runtime_control("travel_strategy", "Motorcycle Direct")
    direct = await coordinator._async_update_data()
    coordinator.set_runtime_control("travel_strategy", "Motorcycle Scenic Approach")
    scenic = await coordinator._async_update_data()

    assert direct["opportunities"][0]["trip_efficiency_score"] != scenic["opportunities"][0]["trip_efficiency_score"]


async def test_native_trailer_available_off_excludes_trailer_opportunities(hass) -> None:
    entry = _entry(forecast_days=3)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"trailer_support_enabled": True})
    coordinator = RideRadarDataCoordinator(hass, entry, FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("travel_strategy", "Trailer Transport")
    coordinator.set_runtime_control("trailer_available", "off")

    data = await coordinator._async_update_data()

    assert data["opportunities"] == []
    assert any(item["reason"] == "trailer_required_but_unavailable" for item in data["excluded_destinations"])


async def test_native_available_hours_changes_trip_efficiency(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("available_hours_per_day", "4")
    low_hours = await coordinator._async_update_data()
    coordinator.set_runtime_control("available_hours_per_day", "10")
    high_hours = await coordinator._async_update_data()

    assert low_hours["opportunities"][0]["trip_efficiency_score"] < high_hours["opportunities"][0][
        "trip_efficiency_score"
    ]


async def test_native_max_approach_time_changes_exclusion_reasons(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(forecast_days=3), FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("max_approach_time_hours", "0.5")

    data = await coordinator._async_update_data()

    assert data["opportunities"] == []
    assert any(item["reason"] == "approach_time_too_high" for item in data["excluded_destinations"])
