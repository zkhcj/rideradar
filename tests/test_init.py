"""Tests for RideRadar setup and unload."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar import async_setup_entry, async_unload_entry
from custom_components.rideradar.const import DOMAIN
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.sensor import async_setup_entry as async_setup_sensor


async def test_setup_and_unload_entry(hass, monkeypatch) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"start_latitude": 50, "start_longitude": 4, "destinations": []},
    )
    entry.add_to_hass(hass)

    async def fake_refresh(self):
        return None

    async def fake_forward_setups(config_entry, platforms):
        return True

    async def fake_unload_platforms(config_entry, platforms):
        return True

    monkeypatch.setattr(RideRadarDataCoordinator, "async_refresh", fake_refresh)
    monkeypatch.setattr("custom_components.rideradar.async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", fake_forward_setups)
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", fake_unload_platforms)

    assert await async_setup_entry(hass, entry) is True
    assert entry.entry_id in hass.data[DOMAIN]
    assert hass.data[DOMAIN][entry.entry_id].data["forecast_status"] == "temporarily_unavailable"

    assert await async_unload_entry(hass, entry) is True
    assert DOMAIN not in hass.data


async def test_destination_sensors_are_created_before_first_forecast(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "start_latitude": 50,
            "start_longitude": 4,
            "enabled_default_destinations": ["Sauerland"],
            "custom_destinations": [],
        },
    )
    coordinator = RideRadarDataCoordinator(hass, entry, api_client=object())
    coordinator.data = coordinator.unavailable_data()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    entities = []

    await async_setup_sensor(hass, entry, entities.extend)

    unique_ids = {entity.unique_id for entity in entities}
    assert f"{entry.entry_id}_destination_sauerland" in unique_ids
    assert f"{entry.entry_id}_destination_sauerland_best_future_window" in unique_ids
