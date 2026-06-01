"""Tests for RideRadar diagnostics."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar.const import CONF_START_ADDRESS, DOMAIN
from custom_components.rideradar.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_start_address(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_START_ADDRESS: "Private address"})
    coordinator = type(
        "Coordinator",
        (),
        {
            "data": {"destination_count": 0, "summary": "No enabled destinations configured"},
            "last_update_success": True,
        },
    )()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert data["entry"]["data"][CONF_START_ADDRESS] == "**REDACTED**"
    assert data["coordinator"]["destination_count"] == 0
