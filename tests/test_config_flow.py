"""Tests for RideRadar config flow."""

from homeassistant import config_entries

import custom_components.rideradar
from custom_components.rideradar.const import (
    CONF_ACTIVITY_PROFILE,
    CONF_DESTINATIONS,
    CONF_DETOUR_FACTOR,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_START_ADDRESS,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_DETOUR_FACTOR,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_MAX_ROUTE_DISTANCE_KM,
    DOMAIN,
)
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.destinations import default_destinations_as_dicts


def _valid_input(**overrides):
    data = {
        CONF_START_ADDRESS: "Configured start",
        CONF_START_LATITUDE: 50.8503,
        CONF_START_LONGITUDE: 4.3517,
        CONF_MAX_ROUTE_DISTANCE_KM: DEFAULT_MAX_ROUTE_DISTANCE_KM,
        CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
        CONF_ACTIVITY_PROFILE: DEFAULT_ACTIVITY_PROFILE,
        CONF_DETOUR_FACTOR: DEFAULT_DETOUR_FACTOR,
        CONF_DESTINATIONS: default_destinations_as_dicts(),
    }
    data.update(overrides)
    return data


async def _fake_first_refresh(self):
    self.data = {
        "results": [],
        "best": None,
        "destination_count": 0,
        "summary": "No enabled destinations configured",
    }


async def _fake_setup_entry(hass, entry):
    return True


def _patch_setup(monkeypatch) -> None:
    monkeypatch.setattr(RideRadarDataCoordinator, "async_config_entry_first_refresh", _fake_first_refresh)
    monkeypatch.setattr(custom_components.rideradar, "async_setup_entry", _fake_setup_entry)


async def test_config_flow_with_coordinates(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_valid_input(),
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "RideRadar"
    assert result["data"][CONF_START_LATITUDE] == 50.8503
    assert len(result["data"][CONF_DESTINATIONS]) == 9


async def test_config_flow_rejects_invalid_destinations(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_valid_input(**{CONF_DESTINATIONS: "not json"}),
    )

    assert result["type"] == "form"
    assert result["errors"][CONF_DESTINATIONS] == "invalid_destinations"


async def test_config_flow_accepts_empty_destination_list(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_valid_input(**{CONF_DESTINATIONS: "[]"}),
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_DESTINATIONS] == []


async def test_config_flow_rejects_partial_coordinates(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_valid_input(**{CONF_START_LONGITUDE: None}),
    )

    assert result["type"] == "form"
    assert result["errors"][CONF_START_LONGITUDE] == "coordinates_required"


async def test_config_flow_rejects_out_of_range_settings(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=_valid_input(
            **{
                CONF_START_LATITUDE: 120,
                CONF_FORECAST_DAYS: 20,
                CONF_DETOUR_FACTOR: 0.5,
                CONF_MAX_ROUTE_DISTANCE_KM: 0,
            }
        ),
    )

    assert result["type"] == "form"
    assert result["errors"][CONF_START_LATITUDE] == "invalid_coordinates"
    assert result["errors"][CONF_FORECAST_DAYS] == "invalid_forecast_days"
    assert result["errors"][CONF_DETOUR_FACTOR] == "invalid_detour_factor"
    assert result["errors"][CONF_MAX_ROUTE_DISTANCE_KM] == "invalid_range"
