"""Config flow for RideRadar."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_DESTINATIONS,
    CONF_DESTINATIONS,
    CONF_DETOUR_FACTOR,
    CONF_ENABLED_DEFAULT_DESTINATIONS,
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
    MAX_DETOUR_FACTOR,
    MAX_FORECAST_DAYS,
    MAX_LATITUDE,
    MAX_LONGITUDE,
    MAX_ROUTE_DISTANCE_KM_LIMIT,
    MIN_DETOUR_FACTOR,
    MIN_FORECAST_DAYS,
    MIN_GEOCODE_QUERY_LENGTH,
    MIN_LATITUDE,
    MIN_LONGITUDE,
    MIN_ROUTE_DISTANCE_KM,
    SUPPORTED_ACTIVITY_PROFILES,
)
from .destinations import (
    DEFAULT_DESTINATIONS,
    custom_destinations_from_config,
    default_destination_names,
    destination_enable_options,
    enabled_destination_keys,
    parse_destinations_data,
)
from .geocoding import GeocodingError, LocationResult, OpenMeteoGeocodingClient
from .models import DestinationArea, RideRadarConfigError

FIELD_ACTION = "action"
FIELD_ADDRESS = "address"
FIELD_LOCATION = "location"
FIELD_ENABLED_DESTINATIONS = "enabled_destinations"
FIELD_DESTINATION_NAME = "destination_name"
FIELD_COUNTRY_REGION = "country_region"
FIELD_ENABLED = "enabled"
FIELD_NOTES = "notes"
FIELD_IMPORT_EXPORT_JSON = "destinations_json"
FIELD_MANUAL_MODE = "manual_mode"

ACTION_START = "start_location"
ACTION_SETTINGS = "settings"
ACTION_DESTINATIONS = "destinations"
ACTION_ADD_CUSTOM = "add_custom_destination"
ACTION_REMOVE_CUSTOM = "remove_custom_destination"
ACTION_RESET_DEFAULTS = "reset_defaults"
ACTION_ADVANCED = "advanced_import_export"


class RideRadarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle RideRadar config flow."""

    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._location_results: list[LocationResult] = []
        self._pending_destination: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect a start address or route to manual coordinate entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(FIELD_MANUAL_MODE):
                self._data[CONF_START_ADDRESS] = str(user_input.get(CONF_START_ADDRESS, "")).strip()
                return await self.async_step_manual_location()
            query = str(user_input.get(CONF_START_ADDRESS, "")).strip()
            if len(query) < MIN_GEOCODE_QUERY_LENGTH:
                errors[CONF_START_ADDRESS] = "query_too_short"
            else:
                results = await self._geocode(query, errors, CONF_START_ADDRESS)
                if results:
                    self._data[CONF_START_ADDRESS] = query
                    self._location_results = results
                    if len(results) == 1:
                        self._store_start_location(results[0])
                        return await self.async_step_confirm_location()
                    return await self.async_step_choose_location()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_START_ADDRESS): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(FIELD_MANUAL_MODE, default=False): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_choose_location(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user choose among geocoding matches."""
        if user_input is not None:
            self._store_start_location(self._location_results[int(user_input[FIELD_LOCATION])])
            return await self.async_step_confirm_location()
        return self.async_show_form(
            step_id="choose_location",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_LOCATION): SelectSelector(
                        SelectSelectorConfig(
                            options=[result.as_option(index) for index, result in enumerate(self._location_results)],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_confirm_location(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm resolved start coordinates."""
        if user_input is not None:
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="confirm_location",
            description_placeholders={
                "address": str(self._data.get(CONF_START_ADDRESS, "")),
                "latitude": f"{float(self._data[CONF_START_LATITUDE]):.5f}",
                "longitude": f"{float(self._data[CONF_START_LONGITUDE]):.5f}",
            },
            data_schema=vol.Schema({}),
        )

    async def async_step_manual_location(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Advanced manual coordinate entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            latitude = _as_float(user_input.get(CONF_START_LATITUDE))
            longitude = _as_float(user_input.get(CONF_START_LONGITUDE))
            if latitude is None or not MIN_LATITUDE <= latitude <= MAX_LATITUDE:
                errors[CONF_START_LATITUDE] = "invalid_coordinates"
            if longitude is None or not MIN_LONGITUDE <= longitude <= MAX_LONGITUDE:
                errors[CONF_START_LONGITUDE] = "invalid_coordinates"
            if not errors:
                self._data[CONF_START_ADDRESS] = str(user_input.get(CONF_START_ADDRESS, "Manual location")).strip()
                self._data[CONF_START_LATITUDE] = latitude
                self._data[CONF_START_LONGITUDE] = longitude
                return await self.async_step_settings()
        return self.async_show_form(
            step_id="manual_location",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_START_ADDRESS, default=self._data.get(CONF_START_ADDRESS, "Manual location")
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(CONF_START_LATITUDE): NumberSelector(
                        NumberSelectorConfig(mode=NumberSelectorMode.BOX)
                    ),
                    vol.Required(CONF_START_LONGITUDE): NumberSelector(
                        NumberSelectorConfig(mode=NumberSelectorMode.BOX)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect trip settings and enabled default destinations."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _settings_errors(user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                self._data.update(_normalized_settings(user_input))
                self._data[CONF_ENABLED_DEFAULT_DESTINATIONS] = list(user_input[CONF_ENABLED_DEFAULT_DESTINATIONS])
                self._data[CONF_CUSTOM_DESTINATIONS] = []
                return self.async_create_entry(title="RideRadar", data=self._data)
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema({CONF_ENABLED_DEFAULT_DESTINATIONS: default_destination_names()}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> RideRadarOptionsFlow:
        """Return the options flow."""
        return RideRadarOptionsFlow(config_entry)

    async def _geocode(self, query: str, errors: dict[str, str], field: str) -> list[LocationResult]:
        try:
            results = await OpenMeteoGeocodingClient(async_get_clientsession(self.hass)).search(query)
        except GeocodingError:
            errors[field] = "geocoding_failed"
            return []
        if not results:
            errors[field] = "address_not_found"
        return results

    def _store_start_location(self, result: LocationResult) -> None:
        self._data[CONF_START_ADDRESS] = result.label
        self._data[CONF_START_LATITUDE] = result.latitude
        self._data[CONF_START_LONGITUDE] = result.longitude


class RideRadarOptionsFlow(config_entries.OptionsFlow):
    """Handle RideRadar options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._location_results: list[LocationResult] = []
        self._pending_destination: dict[str, Any] = {}

    @property
    def _config(self) -> dict[str, Any]:
        return {**self._config_entry.data, **self._config_entry.options}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show options menu."""
        if user_input is not None:
            return await getattr(self, f"async_step_{user_input[FIELD_ACTION]}")()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_ACTION): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": ACTION_START, "label": "Change start location"},
                                {"value": ACTION_SETTINGS, "label": "Trip settings"},
                                {"value": ACTION_DESTINATIONS, "label": "Enable or disable destinations"},
                                {"value": ACTION_ADD_CUSTOM, "label": "Add custom destination"},
                                {"value": ACTION_REMOVE_CUSTOM, "label": "Remove custom destination"},
                                {"value": ACTION_RESET_DEFAULTS, "label": "Reset destinations to defaults"},
                                {"value": ACTION_ADVANCED, "label": "Advanced import/export"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_start_location(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change start location."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(FIELD_MANUAL_MODE):
                return await self.async_step_manual_location()
            query = str(user_input.get(CONF_START_ADDRESS, "")).strip()
            if len(query) < MIN_GEOCODE_QUERY_LENGTH:
                errors[CONF_START_ADDRESS] = "query_too_short"
            else:
                results = await self._geocode(query, errors, CONF_START_ADDRESS)
                if results:
                    self._location_results = results
                    if len(results) == 1:
                        return self._save_options(_start_location_options(results[0]))
                    return await self.async_step_choose_location()
        return self.async_show_form(
            step_id="start_location",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_START_ADDRESS, default=self._config.get(CONF_START_ADDRESS, "")): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Optional(FIELD_MANUAL_MODE, default=False): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_choose_location(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose start location result."""
        if user_input is not None:
            return self._save_options(_start_location_options(self._location_results[int(user_input[FIELD_LOCATION])]))
        return self.async_show_form(
            step_id="choose_location",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_LOCATION): SelectSelector(
                        SelectSelectorConfig(
                            options=[result.as_option(index) for index, result in enumerate(self._location_results)],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_manual_location(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Advanced manual start coordinate edit."""
        errors: dict[str, str] = {}
        if user_input is not None:
            latitude = _as_float(user_input.get(CONF_START_LATITUDE))
            longitude = _as_float(user_input.get(CONF_START_LONGITUDE))
            if latitude is None or not MIN_LATITUDE <= latitude <= MAX_LATITUDE:
                errors[CONF_START_LATITUDE] = "invalid_coordinates"
            if longitude is None or not MIN_LONGITUDE <= longitude <= MAX_LONGITUDE:
                errors[CONF_START_LONGITUDE] = "invalid_coordinates"
            if not errors:
                return self._save_options(
                    {
                        CONF_START_ADDRESS: str(user_input.get(CONF_START_ADDRESS, "Manual location")).strip(),
                        CONF_START_LATITUDE: latitude,
                        CONF_START_LONGITUDE: longitude,
                    }
                )
        return self.async_show_form(
            step_id="manual_location",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_START_ADDRESS, default=self._config.get(CONF_START_ADDRESS, "Manual location")
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(CONF_START_LATITUDE, default=self._config.get(CONF_START_LATITUDE)): NumberSelector(
                        NumberSelectorConfig(mode=NumberSelectorMode.BOX)
                    ),
                    vol.Required(CONF_START_LONGITUDE, default=self._config.get(CONF_START_LONGITUDE)): NumberSelector(
                        NumberSelectorConfig(mode=NumberSelectorMode.BOX)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Change trip settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _settings_errors(user_input)
            if not errors:
                return self._save_options(_normalized_settings(user_input))
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(self._config, include_destinations=False),
            errors=errors,
        )

    async def async_step_destinations(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Enable or disable destinations."""
        config = self._config
        if user_input is not None:
            selected = set(user_input[FIELD_ENABLED_DESTINATIONS])
            custom = []
            for destination in custom_destinations_from_config(config):
                custom.append(
                    DestinationArea(
                        destination.name,
                        destination.country_region,
                        destination.latitude,
                        destination.longitude,
                        enabled=f"custom:{destination.name}" in selected,
                        notes=destination.notes,
                        preferred_route_target_address=destination.preferred_route_target_address,
                    ).as_dict()
                )
            return self._save_options(
                {
                    CONF_ENABLED_DEFAULT_DESTINATIONS: [
                        destination.name
                        for destination in DEFAULT_DESTINATIONS
                        if f"default:{destination.name}" in selected
                    ],
                    CONF_CUSTOM_DESTINATIONS: custom,
                }
            )
        return self.async_show_form(
            step_id="destinations",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_ENABLED_DESTINATIONS, default=enabled_destination_keys(config)): SelectSelector(
                        SelectSelectorConfig(
                            options=destination_enable_options(config),
                            multiple=True,
                        )
                    )
                }
            ),
        )

    async def async_step_add_custom_destination(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect custom destination details and geocode its address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = str(user_input.get(FIELD_ADDRESS, "")).strip()
            if len(query) < MIN_GEOCODE_QUERY_LENGTH:
                errors[FIELD_ADDRESS] = "query_too_short"
            else:
                results = await self._geocode(query, errors, FIELD_ADDRESS)
                if results:
                    self._pending_destination = dict(user_input)
                    self._location_results = results
                    if len(results) == 1:
                        return self._save_custom_destination(results[0])
                    return await self.async_step_choose_custom_location()
        return self.async_show_form(
            step_id="add_custom_destination",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_DESTINATION_NAME): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(FIELD_COUNTRY_REGION): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(FIELD_ADDRESS): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(FIELD_ENABLED, default=True): BooleanSelector(),
                    vol.Optional(FIELD_NOTES, default=""): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                }
            ),
            errors=errors,
        )

    async def async_step_choose_custom_location(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose custom destination geocoding result."""
        if user_input is not None:
            return self._save_custom_destination(self._location_results[int(user_input[FIELD_LOCATION])])
        return self.async_show_form(
            step_id="choose_custom_location",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_LOCATION): SelectSelector(
                        SelectSelectorConfig(
                            options=[result.as_option(index) for index, result in enumerate(self._location_results)],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_remove_custom_destination(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Remove custom destinations."""
        custom = custom_destinations_from_config(self._config)
        if user_input is not None:
            remove = set(user_input[CONF_CUSTOM_DESTINATIONS])
            return self._save_options(
                {
                    CONF_CUSTOM_DESTINATIONS: [
                        destination.as_dict() for destination in custom if destination.name not in remove
                    ]
                }
            )
        if not custom:
            return self.async_abort(reason="no_custom_destinations")
        return self.async_show_form(
            step_id="remove_custom_destination",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CUSTOM_DESTINATIONS, default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=[{"value": destination.name, "label": destination.name} for destination in custom],
                            multiple=True,
                        )
                    )
                }
            ),
        )

    async def async_step_reset_defaults(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reset destinations to enabled defaults and remove custom destinations."""
        if user_input is not None:
            return self._save_options(
                {
                    CONF_ENABLED_DEFAULT_DESTINATIONS: default_destination_names(),
                    CONF_CUSTOM_DESTINATIONS: [],
                }
            )
        return self.async_show_form(step_id="reset_defaults", data_schema=vol.Schema({}))

    async def async_step_advanced_import_export(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Advanced structured destination import/export."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                imported = parse_destinations_data(user_input[FIELD_IMPORT_EXPORT_JSON])
            except (json.JSONDecodeError, RideRadarConfigError, TypeError, ValueError):
                errors[FIELD_IMPORT_EXPORT_JSON] = "invalid_destinations"
            else:
                return self._save_options(
                    {
                        CONF_ENABLED_DEFAULT_DESTINATIONS: [],
                        CONF_CUSTOM_DESTINATIONS: [destination.as_dict() for destination in imported],
                    }
                )
        current = [destination.as_dict() for destination in custom_destinations_from_config(self._config)]
        return self.async_show_form(
            step_id="advanced_import_export",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_IMPORT_EXPORT_JSON, default=json.dumps(current, indent=2)): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
                    )
                }
            ),
            errors=errors,
        )

    async def _geocode(self, query: str, errors: dict[str, str], field: str) -> list[LocationResult]:
        try:
            results = await OpenMeteoGeocodingClient(async_get_clientsession(self.hass)).search(query)
        except GeocodingError:
            errors[field] = "geocoding_failed"
            return []
        if not results:
            errors[field] = "address_not_found"
        return results

    def _save_custom_destination(self, result: LocationResult) -> config_entries.ConfigFlowResult:
        config = self._config
        custom = custom_destinations_from_config(config)
        name = str(self._pending_destination[FIELD_DESTINATION_NAME]).strip()
        custom = [destination for destination in custom if destination.name != name]
        custom.append(
            DestinationArea(
                name=name,
                country_region=str(self._pending_destination[FIELD_COUNTRY_REGION]).strip(),
                latitude=result.latitude,
                longitude=result.longitude,
                enabled=bool(self._pending_destination.get(FIELD_ENABLED, True)),
                notes=str(self._pending_destination.get(FIELD_NOTES, "")).strip() or None,
                preferred_route_target_address=result.label,
            )
        )
        return self._save_options({CONF_CUSTOM_DESTINATIONS: [destination.as_dict() for destination in custom]})

    def _save_options(self, updates: dict[str, Any]) -> config_entries.ConfigFlowResult:
        options = {**self._config_entry.options, **updates}
        options.pop(CONF_DESTINATIONS, None)
        return self.async_create_entry(title="", data=options)


def _settings_schema(defaults: dict[str, Any], include_destinations: bool = True) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Required(
            CONF_MAX_ROUTE_DISTANCE_KM,
            default=defaults.get(CONF_MAX_ROUTE_DISTANCE_KM, DEFAULT_MAX_ROUTE_DISTANCE_KM),
        ): NumberSelector(
            NumberSelectorConfig(
                mode=NumberSelectorMode.BOX,
                min=MIN_ROUTE_DISTANCE_KM,
                max=MAX_ROUTE_DISTANCE_KM_LIMIT,
                step=1,
                unit_of_measurement="km",
            )
        ),
        vol.Required(
            CONF_FORECAST_DAYS, default=defaults.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS)
        ): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=MIN_FORECAST_DAYS, max=MAX_FORECAST_DAYS, step=1)
        ),
        vol.Required(
            CONF_ACTIVITY_PROFILE,
            default=defaults.get(CONF_ACTIVITY_PROFILE, DEFAULT_ACTIVITY_PROFILE),
        ): SelectSelector(
            SelectSelectorConfig(options=list(SUPPORTED_ACTIVITY_PROFILES), mode=SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(
            CONF_DETOUR_FACTOR, default=defaults.get(CONF_DETOUR_FACTOR, DEFAULT_DETOUR_FACTOR)
        ): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=MIN_DETOUR_FACTOR, max=MAX_DETOUR_FACTOR, step=0.05)
        ),
    }
    if include_destinations:
        schema[
            vol.Required(
                CONF_ENABLED_DEFAULT_DESTINATIONS,
                default=defaults.get(CONF_ENABLED_DEFAULT_DESTINATIONS, default_destination_names()),
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": destination.name, "label": destination.name} for destination in DEFAULT_DESTINATIONS
                ],
                multiple=True,
            )
        )
    return vol.Schema(schema)


def _settings_errors(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    max_distance = _as_float(data.get(CONF_MAX_ROUTE_DISTANCE_KM))
    if max_distance is None or not MIN_ROUTE_DISTANCE_KM <= max_distance <= MAX_ROUTE_DISTANCE_KM_LIMIT:
        errors[CONF_MAX_ROUTE_DISTANCE_KM] = "invalid_range"
    forecast_days = _as_int(data.get(CONF_FORECAST_DAYS))
    if forecast_days is None or not MIN_FORECAST_DAYS <= forecast_days <= MAX_FORECAST_DAYS:
        errors[CONF_FORECAST_DAYS] = "invalid_forecast_days"
    detour_factor = _as_float(data.get(CONF_DETOUR_FACTOR))
    if detour_factor is None or not MIN_DETOUR_FACTOR <= detour_factor <= MAX_DETOUR_FACTOR:
        errors[CONF_DETOUR_FACTOR] = "invalid_detour_factor"
    if data.get(CONF_ACTIVITY_PROFILE) not in SUPPORTED_ACTIVITY_PROFILES:
        errors[CONF_ACTIVITY_PROFILE] = "invalid_activity_profile"
    return errors


def _normalized_settings(data: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_MAX_ROUTE_DISTANCE_KM: float(data[CONF_MAX_ROUTE_DISTANCE_KM]),
        CONF_FORECAST_DAYS: int(data[CONF_FORECAST_DAYS]),
        CONF_ACTIVITY_PROFILE: str(data[CONF_ACTIVITY_PROFILE]),
        CONF_DETOUR_FACTOR: float(data[CONF_DETOUR_FACTOR]),
    }


def _start_location_options(result: LocationResult) -> dict[str, Any]:
    return {
        CONF_START_ADDRESS: result.label,
        CONF_START_LATITUDE: result.latitude,
        CONF_START_LONGITUDE: result.longitude,
    }


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
