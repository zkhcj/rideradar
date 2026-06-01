"""Tests for RideRadar config and options flows."""

import json

from homeassistant import config_entries
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.rideradar
from custom_components.rideradar import async_migrate_entry
from custom_components.rideradar.const import (
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_DESTINATIONS,
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DESTINATIONS,
    CONF_DETOUR_FACTOR,
    CONF_ENABLED_DEFAULT_DESTINATIONS,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_ADDRESS,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
    DEFAULT_DETOUR_FACTOR,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_MAX_ROUTE_DISTANCE_KM,
    DEFAULT_PREFERRED_TRIP_DURATION,
    DOMAIN,
)
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.destinations import default_destination_names, default_destinations_as_dicts
from custom_components.rideradar.geocoding import LocationResult, OpenMeteoGeocodingClient
from custom_components.rideradar.models import DestinationArea


async def _fake_first_refresh(self):
    self.data = {
        "results": [],
        "best": None,
        "destination_count": 0,
        "summary": "No enabled destinations configured",
    }


async def _fake_setup_entry(hass, entry):
    return True


async def _fake_search(self, query, limit=5):
    return [LocationResult("Brussels, Belgium", 50.8503, 4.3517, "Belgium")]


async def _fake_multi_search(self, query, limit=5):
    return [
        LocationResult("Luxembourg City, Luxembourg", 49.6116, 6.1319, "Luxembourg"),
        LocationResult("Luxembourg, Belgium", 49.8120, 5.5330, "Belgium"),
    ]


def _patch_setup(monkeypatch, search=_fake_search) -> None:
    monkeypatch.setattr(RideRadarDataCoordinator, "async_config_entry_first_refresh", _fake_first_refresh)
    monkeypatch.setattr(custom_components.rideradar, "async_setup_entry", _fake_setup_entry)
    monkeypatch.setattr("custom_components.rideradar.async_get_clientsession", lambda hass: object())
    monkeypatch.setattr("custom_components.rideradar.config_flow.async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(OpenMeteoGeocodingClient, "search", search)


def _settings_input(**overrides):
    data = {
        CONF_MAX_ROUTE_DISTANCE_KM: DEFAULT_MAX_ROUTE_DISTANCE_KM,
        CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
        CONF_PREFERRED_TRIP_DURATION: DEFAULT_PREFERRED_TRIP_DURATION,
        CONF_CUSTOM_TRIP_DURATION_DAYS: DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
        CONF_ACTIVITY_PROFILE: DEFAULT_ACTIVITY_PROFILE,
        CONF_DETOUR_FACTOR: DEFAULT_DETOUR_FACTOR,
        CONF_ENABLED_DEFAULT_DESTINATIONS: default_destination_names(),
    }
    data.update(overrides)
    return data


def _entry(data=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data
        or {
            CONF_START_ADDRESS: "Brussels, Belgium",
            CONF_START_LATITUDE: 50.8503,
            CONF_START_LONGITUDE: 4.3517,
            CONF_MAX_ROUTE_DISTANCE_KM: DEFAULT_MAX_ROUTE_DISTANCE_KM,
            CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
            CONF_PREFERRED_TRIP_DURATION: DEFAULT_PREFERRED_TRIP_DURATION,
            CONF_CUSTOM_TRIP_DURATION_DAYS: DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
            CONF_ACTIVITY_PROFILE: DEFAULT_ACTIVITY_PROFILE,
            CONF_DETOUR_FACTOR: DEFAULT_DETOUR_FACTOR,
            CONF_ENABLED_DEFAULT_DESTINATIONS: default_destination_names(),
            CONF_CUSTOM_DESTINATIONS: [],
        },
    )
    return entry


async def test_config_flow_saves_geocoded_start_location(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "Brussels"},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "confirm_location"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    assert result["step_id"] == "settings"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=_settings_input())
    assert result["type"] == "create_entry"
    assert result["data"][CONF_START_ADDRESS] == "Brussels, Belgium"
    assert result["data"][CONF_START_LATITUDE] == 50.8503
    assert CONF_DESTINATIONS not in result["data"]
    assert result["data"][CONF_ENABLED_DEFAULT_DESTINATIONS] == default_destination_names()
    assert result["data"][CONF_CUSTOM_DESTINATIONS] == []


async def test_config_flow_allows_choosing_geocode_match(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch, _fake_multi_search)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "Luxembourg"},
    )

    assert result["step_id"] == "choose_location"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={"location": "1"})
    assert result["step_id"] == "confirm_location"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=_settings_input())

    assert result["type"] == "create_entry"
    assert result["data"][CONF_START_ADDRESS] == "Luxembourg, Belgium"
    assert result["data"][CONF_START_LATITUDE] == 49.812


async def test_config_flow_rejects_short_start_query(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "ab"},
    )

    assert result["type"] == "form"
    assert result["errors"][CONF_START_ADDRESS] == "query_too_short"


async def test_config_flow_start_location_uses_search_as_primary_path(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "Manual", "manual_mode": True},
    )

    assert result["step_id"] == "confirm_location"
    assert result["description_placeholders"]["address"] == "Brussels, Belgium"
    assert result["description_placeholders"]["latitude"] == "50.85030"
    assert result["description_placeholders"]["longitude"] == "4.35170"


async def test_config_flow_saves_custom_trip_duration(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "Brussels"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=_settings_input(
            **{
                CONF_FORECAST_DAYS: 5,
                CONF_PREFERRED_TRIP_DURATION: "custom",
                CONF_CUSTOM_TRIP_DURATION_DAYS: 4,
            }
        ),
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_PREFERRED_TRIP_DURATION] == "custom"
    assert result["data"][CONF_CUSTOM_TRIP_DURATION_DAYS] == 4


async def test_options_flow_edits_enabled_destinations(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={"action": "destinations"})
    assert result["step_id"] == "destinations"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"enabled_destinations": ["default:Sauerland", "default:Eifel"]},
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_ENABLED_DEFAULT_DESTINATIONS] == ["Sauerland", "Eifel"]


async def test_options_flow_confirms_changed_start_location(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "start_location"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_START_ADDRESS: "Brussels"}
    )

    assert result["step_id"] == "confirm_location"
    assert result["description_placeholders"]["address"] == "Brussels, Belgium"
    assert result["description_placeholders"]["latitude"] == "50.85030"

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_START_ADDRESS] == "Brussels, Belgium"


async def test_options_flow_allows_manual_coordinates_only_as_advanced_action(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "manual_start_location"}
    )

    assert result["step_id"] == "manual_start_location"


async def test_options_flow_adds_and_removes_custom_destination(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "add_custom_destination"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "destination_name": "Ardennes",
            "country_region": "Belgium",
            "address": "Ardennes",
            "enabled": True,
            "notes": "Nice roads",
        },
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_CUSTOM_DESTINATIONS][0]["name"] == "Ardennes"
    entry = _entry({**entry.data, **result["data"]})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "remove_custom_destination"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_CUSTOM_DESTINATIONS: ["Ardennes"]}
    )
    assert result["data"][CONF_CUSTOM_DESTINATIONS] == []


async def test_migrates_legacy_raw_json_destinations(hass) -> None:
    legacy = DestinationArea("Legacy Custom", "Test", 51.0, 5.0).as_dict()
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            CONF_START_ADDRESS: "Start",
            CONF_START_LATITUDE: 50.0,
            CONF_START_LONGITUDE: 4.0,
            CONF_DESTINATIONS: json.dumps([default_destinations_as_dicts()[0], legacy]),
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert CONF_DESTINATIONS not in entry.data
    assert entry.data[CONF_ENABLED_DEFAULT_DESTINATIONS] == ["Sauerland"]
    assert entry.data[CONF_CUSTOM_DESTINATIONS][0]["name"] == "Legacy Custom"
