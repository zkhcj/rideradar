"""Tests for RideRadar config and options flows."""

import json

import pytest
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
from custom_components.rideradar.destinations import (
    default_destination_names,
    default_destinations_as_dicts,
    enabled_destination_keys,
)
from custom_components.rideradar.geocoding import (
    GeocodingError,
    LocationResult,
    OpenMeteoGeocodingClient,
    _location_from_open_meteo,
)
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
        CONF_ENABLED_DEFAULT_DESTINATIONS: default_destination_names(),
    }
    data.update(overrides)
    return data


def _normal_options_input(entry, **overrides):
    data = {
        CONF_START_ADDRESS: entry.data.get(CONF_START_ADDRESS, "Brussels, Belgium"),
        CONF_MAX_ROUTE_DISTANCE_KM: entry.data.get(CONF_MAX_ROUTE_DISTANCE_KM, DEFAULT_MAX_ROUTE_DISTANCE_KM),
        CONF_FORECAST_DAYS: entry.data.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
        CONF_PREFERRED_TRIP_DURATION: entry.data.get(CONF_PREFERRED_TRIP_DURATION, DEFAULT_PREFERRED_TRIP_DURATION),
        "enabled_destinations": enabled_destination_keys({**entry.data, **entry.options}),
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


async def test_config_flow_handles_no_location_result(hass, monkeypatch) -> None:
    async def fake_empty_search(self, query, limit=5):
        return []

    _patch_setup(monkeypatch, fake_empty_search)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "No such place"},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"][CONF_START_ADDRESS] == "address_not_found"


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


async def test_config_flow_confirm_location_can_search_again(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "Brussels"},
    )

    assert result["step_id"] == "confirm_location"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"confirm_location": False}
    )

    assert result["step_id"] == "user"


async def test_config_flow_settings_schema_omits_custom_duration_fields(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_START_ADDRESS: "Brussels"},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})

    schema_keys = [key.schema for key in result["data_schema"].schema]
    assert CONF_CUSTOM_TRIP_DURATION_DAYS not in schema_keys
    assert CONF_ACTIVITY_PROFILE not in schema_keys
    assert CONF_DETOUR_FACTOR not in schema_keys


async def test_config_flow_saves_flexible_trip_duration(hass, monkeypatch) -> None:
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
                CONF_PREFERRED_TRIP_DURATION: "flexible",
            }
        ),
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_PREFERRED_TRIP_DURATION] == "flexible"
    assert result["data"][CONF_CUSTOM_TRIP_DURATION_DAYS] == DEFAULT_CUSTOM_TRIP_DURATION_DAYS


async def test_options_flow_shows_all_normal_settings_without_action_dropdown(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["step_id"] == "init"
    schema_keys = [key.schema for key in result["data_schema"].schema]
    assert "action" not in schema_keys
    assert CONF_START_ADDRESS in schema_keys
    assert "enabled_destinations" in schema_keys
    assert result["description_placeholders"]["address"] == "Brussels, Belgium"
    assert result["description_placeholders"]["latitude"] == "50.85030"


async def test_options_flow_edits_normal_settings_and_destinations(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_normal_options_input(
            entry,
            **{
                CONF_MAX_ROUTE_DISTANCE_KM: 450,
                "enabled_destinations": ["default:Sauerland", "default:Eifel"],
            },
        ),
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_MAX_ROUTE_DISTANCE_KM] == 450
    assert result["data"][CONF_ENABLED_DEFAULT_DESTINATIONS] == ["Sauerland", "Eifel"]
    assert isinstance(result["data"][CONF_CUSTOM_DESTINATIONS], list)


async def test_options_flow_confirms_changed_start_location(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_normal_options_input(entry, **{CONF_START_ADDRESS: "Utrecht, Nederland"}),
    )

    assert result["step_id"] == "confirm_location"
    assert result["description_placeholders"]["address"] == "Brussels, Belgium"
    assert result["description_placeholders"]["latitude"] == "50.85030"

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_START_ADDRESS] == "Brussels, Belgium"


async def test_options_flow_confirm_location_can_search_again(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_normal_options_input(entry, **{CONF_START_ADDRESS: "Utrecht, Nederland"}),
    )

    assert result["step_id"] == "confirm_location"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"confirm_location": False}
    )

    assert result["step_id"] == "start_location"


async def test_options_flow_preserves_previous_start_location_when_not_changed(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_normal_options_input(entry, **{CONF_MAX_ROUTE_DISTANCE_KM: 500}),
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_START_ADDRESS] == "Brussels, Belgium"
    assert result["data"][CONF_START_LATITUDE] == 50.8503
    assert result["data"][CONF_START_LONGITUDE] == 4.3517


async def test_options_flow_geocoding_failure_keeps_user_on_normal_settings(hass, monkeypatch) -> None:
    async def fake_empty_search(self, query, limit=5):
        return []

    _patch_setup(monkeypatch, fake_empty_search)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_normal_options_input(entry, **{CONF_START_ADDRESS: "Nope"}),
    )

    assert result["step_id"] == "init"
    assert result["errors"][CONF_START_ADDRESS] == "address_not_found"


async def test_options_flow_multiple_location_results_are_selectable(hass, monkeypatch) -> None:
    _patch_setup(monkeypatch, _fake_multi_search)
    entry = _entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input=_normal_options_input(entry, **{CONF_START_ADDRESS: "Luxembourg"}),
    )

    assert result["step_id"] == "choose_location"


def test_open_meteo_location_result_requires_valid_coordinates() -> None:
    with pytest.raises(GeocodingError, match="coordinates"):
        _location_from_open_meteo({"name": "Broken", "country": "Nowhere"})


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
    assert entry.version == 3


async def test_migrates_011_structured_entry_defaults(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            CONF_START_ADDRESS: "Readable start",
            CONF_START_LATITUDE: 50.0,
            CONF_START_LONGITUDE: 4.0,
            CONF_ENABLED_DEFAULT_DESTINATIONS: ["Sauerland"],
            CONF_CUSTOM_DESTINATIONS: [],
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.data[CONF_START_ADDRESS] == "Readable start"
    assert entry.data[CONF_FORECAST_DAYS] == DEFAULT_FORECAST_DAYS
    assert entry.data[CONF_PREFERRED_TRIP_DURATION] == DEFAULT_PREFERRED_TRIP_DURATION
    assert entry.data[CONF_CUSTOM_DESTINATIONS] == []
    assert entry.version == 3
