"""Tests for RideRadar native control entities."""

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
