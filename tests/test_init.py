"""Tests for RideRadar setup and unload."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar import async_setup_entry, async_unload_entry
from custom_components.rideradar.const import DOMAIN
from custom_components.rideradar.coordinator import RideRadarDataCoordinator


async def test_setup_and_unload_entry(hass, monkeypatch) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"start_latitude": 50, "start_longitude": 4, "destinations": []},
    )
    entry.add_to_hass(hass)

    async def fake_first_refresh(self):
        self.data = {
            "results": [],
            "best": None,
            "destination_count": 0,
            "summary": "No enabled destinations configured",
        }

    async def fake_forward_setups(config_entry, platforms):
        return True

    async def fake_unload_platforms(config_entry, platforms):
        return True

    monkeypatch.setattr(RideRadarDataCoordinator, "async_config_entry_first_refresh", fake_first_refresh)
    monkeypatch.setattr("custom_components.rideradar.async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", fake_forward_setups)
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", fake_unload_platforms)

    assert await async_setup_entry(hass, entry) is True
    assert entry.entry_id in hass.data[DOMAIN]

    assert await async_unload_entry(hass, entry) is True
    assert DOMAIN not in hass.data
