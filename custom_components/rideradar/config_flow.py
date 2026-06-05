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
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DESTINATIONS,
    CONF_DETOUR_FACTOR,
    CONF_ENABLED_DEFAULT_DESTINATIONS,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_MOTORCYCLE_DIRECT_ENABLED,
    CONF_MOTORCYCLE_DIRECT_JOKER_MAX_APPROACH_TIME_HOURS,
    CONF_MOTORCYCLE_DIRECT_NORMAL_MAX_APPROACH_TIME_HOURS,
    CONF_MOTORCYCLE_SCENIC_ENABLED,
    CONF_MOTORCYCLE_SCENIC_JOKER_MAX_APPROACH_TIME_HOURS,
    CONF_MOTORCYCLE_SCENIC_NORMAL_MAX_APPROACH_TIME_HOURS,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_ADDRESS,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    CONF_TRAILER_AVAILABLE,
    CONF_TRAILER_JOKER_MAX_APPROACH_TIME_HOURS,
    CONF_TRAILER_NORMAL_MAX_APPROACH_TIME_HOURS,
    CONF_TRAILER_SUPPORT_ENABLED,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
    DEFAULT_DETOUR_FACTOR,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_MAX_ROUTE_DISTANCE_KM,
    DEFAULT_PREFERRED_TRIP_DURATION,
    DEFAULT_TRAILER_SUPPORT_ENABLED,
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
    MIN_TRIP_DURATION_DAYS,
    PREFERRED_TRIP_DURATION_OPTIONS,
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
from .travel_modes import flat_travel_mode_options, travel_mode_options_from_input, travel_mode_validation_errors

FIELD_ADDRESS = "address"
FIELD_LOCATION = "location"
FIELD_ENABLED_DESTINATIONS = "enabled_destinations"
FIELD_DESTINATION_NAME = "destination_name"
FIELD_COUNTRY_REGION = "country_region"
FIELD_ENABLED = "enabled"
FIELD_NOTES = "notes"
FIELD_IMPORT_EXPORT_JSON = "destinations_json"


class RideRadarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle RideRadar config flow."""

    VERSION = 4

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._location_results: list[LocationResult] = []
        self._pending_destination: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect a start address or place name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = str(user_input.get(CONF_START_ADDRESS, "")).strip()
            if len(query) < MIN_GEOCODE_QUERY_LENGTH:
                errors[CONF_START_ADDRESS] = "query_too_short"
            else:
                results = await self._geocode(query, errors, CONF_START_ADDRESS)
                if results:
                    self._data[CONF_START_ADDRESS] = query
                    self._location_results = results
                    return await self.async_step_choose_location()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_START_ADDRESS): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                }
            ),
            errors=errors,
        )

    async def async_step_choose_location(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user choose among geocoding matches."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = _selected_location_result(self._location_results, user_input.get(FIELD_LOCATION), errors)
            if result is not None:
                self._store_start_location(result)
                return await self.async_step_settings()
        return self.async_show_form(
            step_id="choose_location",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_LOCATION): SelectSelector(
                        SelectSelectorConfig(
                            options=_location_options(self._location_results),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
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
                errors = travel_mode_validation_errors(user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                self._data.update(_normalized_settings(user_input))
                self._data.update(travel_mode_options_from_input(user_input))
                self._data[CONF_ENABLED_DEFAULT_DESTINATIONS] = list(user_input[CONF_ENABLED_DEFAULT_DESTINATIONS])
                self._data[CONF_CUSTOM_DESTINATIONS] = []
                return self.async_create_entry(title="RideRadar", data=self._data)
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(
                {CONF_ENABLED_DEFAULT_DESTINATIONS: default_destination_names()},
                include_trailer=False,
                include_travel_modes=True,
            ),
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
        self._pending_options: dict[str, Any] = {}

    @property
    def _config(self) -> dict[str, Any]:
        return {**self._config_entry.data, **self._config_entry.options}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show one normal settings screen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _settings_errors(user_input)
            if not errors:
                errors = travel_mode_validation_errors(user_input)
            query = str(user_input.get(CONF_START_ADDRESS, "")).strip()
            if len(query) < MIN_GEOCODE_QUERY_LENGTH:
                errors[CONF_START_ADDRESS] = "query_too_short"
            if not errors:
                self._pending_options = {
                    **_normalized_settings(user_input),
                    **travel_mode_options_from_input(user_input),
                    **_destination_options_from_selection(self._config, user_input[FIELD_ENABLED_DESTINATIONS]),
                }
                if query != str(self._config.get(CONF_START_ADDRESS, "")).strip():
                    results = await self._geocode(query, errors, CONF_START_ADDRESS)
                    if results:
                        self._location_results = results
                        return await self.async_step_choose_location()
                elif not errors:
                    return self._save_options(
                        {**self._pending_options, **_current_start_location_options(self._config)}
                    )
        return self.async_show_form(
            step_id="init",
            description_placeholders=_current_location_placeholders(self._config),
            data_schema=_normal_options_schema(self._config),
            errors=errors,
        )

    async def async_step_start_location(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change start location."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = str(user_input.get(CONF_START_ADDRESS, "")).strip()
            if len(query) < MIN_GEOCODE_QUERY_LENGTH:
                errors[CONF_START_ADDRESS] = "query_too_short"
            else:
                results = await self._geocode(query, errors, CONF_START_ADDRESS)
                if results:
                    self._location_results = results
                    return await self.async_step_choose_location()
        return self.async_show_form(
            step_id="start_location",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_START_ADDRESS, default=self._config.get(CONF_START_ADDRESS, "")): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_choose_location(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose start location result."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = _selected_location_result(self._location_results, user_input.get(FIELD_LOCATION), errors)
            if result is not None:
                self._pending_destination = _start_location_options(result)
                return self._save_options({**self._pending_options, **self._pending_destination})
        return self.async_show_form(
            step_id="choose_location",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_LOCATION): SelectSelector(
                        SelectSelectorConfig(
                            options=_location_options(self._location_results),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_manual_start_location(
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
            step_id="manual_start_location",
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
                errors = travel_mode_validation_errors(user_input)
            if not errors:
                return self._save_options(
                    {
                        **_normalized_settings(user_input),
                        **travel_mode_options_from_input(user_input),
                    }
                )
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(
                self._config,
                include_destinations=False,
                include_trailer=False,
                include_travel_modes=True,
            ),
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
        errors: dict[str, str] = {}
        if user_input is not None:
            result = _selected_location_result(self._location_results, user_input.get(FIELD_LOCATION), errors)
            if result is not None:
                return self._save_custom_destination(result)
        return self.async_show_form(
            step_id="choose_custom_location",
            data_schema=vol.Schema(
                {
                    vol.Required(FIELD_LOCATION): SelectSelector(
                        SelectSelectorConfig(
                            options=_location_options(self._location_results),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
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


def _settings_schema(
    defaults: dict[str, Any],
    include_destinations: bool = True,
    include_trailer: bool = False,
    include_travel_modes: bool = False,
) -> vol.Schema:
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
            CONF_PREFERRED_TRIP_DURATION,
            default=defaults.get(CONF_PREFERRED_TRIP_DURATION, DEFAULT_PREFERRED_TRIP_DURATION),
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": "1", "label": "1 day"},
                    {"value": "2", "label": "2 days"},
                    {"value": "3", "label": "3 days"},
                    {"value": "flexible", "label": "Flexible"},
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
    if include_trailer:
        schema[
            vol.Required(
                CONF_TRAILER_SUPPORT_ENABLED,
                default=defaults.get(CONF_TRAILER_SUPPORT_ENABLED, DEFAULT_TRAILER_SUPPORT_ENABLED),
            )
        ] = BooleanSelector()
    if include_travel_modes:
        mode_defaults = flat_travel_mode_options(defaults)
        schema.update(_travel_mode_schema_fields(mode_defaults))
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


def _normal_options_schema(defaults: dict[str, Any]) -> vol.Schema:
    schema = dict(
        _settings_schema(defaults, include_destinations=False, include_trailer=False, include_travel_modes=True).schema
    )
    return vol.Schema(
        {
            vol.Required(CONF_START_ADDRESS, default=defaults.get(CONF_START_ADDRESS, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            **schema,
            vol.Required(FIELD_ENABLED_DESTINATIONS, default=enabled_destination_keys(defaults)): SelectSelector(
                SelectSelectorConfig(options=destination_enable_options(defaults), multiple=True)
            ),
        }
    )


def _travel_mode_schema_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    number = NumberSelector(
        NumberSelectorConfig(
            mode=NumberSelectorMode.BOX,
            min=0.5,
            max=12,
            step=0.25,
            unit_of_measurement="hours",
        )
    )
    return {
        vol.Required(
            CONF_MOTORCYCLE_DIRECT_ENABLED,
            default=defaults[CONF_MOTORCYCLE_DIRECT_ENABLED],
        ): BooleanSelector(),
        vol.Required(
            CONF_MOTORCYCLE_DIRECT_NORMAL_MAX_APPROACH_TIME_HOURS,
            default=defaults[CONF_MOTORCYCLE_DIRECT_NORMAL_MAX_APPROACH_TIME_HOURS],
        ): number,
        vol.Required(
            CONF_MOTORCYCLE_DIRECT_JOKER_MAX_APPROACH_TIME_HOURS,
            default=defaults[CONF_MOTORCYCLE_DIRECT_JOKER_MAX_APPROACH_TIME_HOURS],
        ): number,
        vol.Required(
            CONF_MOTORCYCLE_SCENIC_ENABLED,
            default=defaults[CONF_MOTORCYCLE_SCENIC_ENABLED],
        ): BooleanSelector(),
        vol.Required(
            CONF_MOTORCYCLE_SCENIC_NORMAL_MAX_APPROACH_TIME_HOURS,
            default=defaults[CONF_MOTORCYCLE_SCENIC_NORMAL_MAX_APPROACH_TIME_HOURS],
        ): number,
        vol.Required(
            CONF_MOTORCYCLE_SCENIC_JOKER_MAX_APPROACH_TIME_HOURS,
            default=defaults[CONF_MOTORCYCLE_SCENIC_JOKER_MAX_APPROACH_TIME_HOURS],
        ): number,
        vol.Required(CONF_TRAILER_AVAILABLE, default=defaults[CONF_TRAILER_AVAILABLE]): BooleanSelector(),
        vol.Required(
            CONF_TRAILER_NORMAL_MAX_APPROACH_TIME_HOURS,
            default=defaults[CONF_TRAILER_NORMAL_MAX_APPROACH_TIME_HOURS],
        ): number,
        vol.Required(
            CONF_TRAILER_JOKER_MAX_APPROACH_TIME_HOURS,
            default=defaults[CONF_TRAILER_JOKER_MAX_APPROACH_TIME_HOURS],
        ): number,
    }


def _destination_options_from_selection(config: dict[str, Any], selected_values: list[str]) -> dict[str, Any]:
    selected = set(selected_values)
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
    return {
        CONF_ENABLED_DEFAULT_DESTINATIONS: [
            destination.name for destination in DEFAULT_DESTINATIONS if f"default:{destination.name}" in selected
        ],
        CONF_CUSTOM_DESTINATIONS: custom,
    }


def _current_location_placeholders(config: dict[str, Any]) -> dict[str, str]:
    latitude = _as_float(config.get(CONF_START_LATITUDE))
    longitude = _as_float(config.get(CONF_START_LONGITUDE))
    return {
        "address": str(config.get(CONF_START_ADDRESS, "")),
        "latitude": f"{latitude:.5f}" if latitude is not None else "unknown",
        "longitude": f"{longitude:.5f}" if longitude is not None else "unknown",
    }


def _settings_errors(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    max_distance = _as_float(data.get(CONF_MAX_ROUTE_DISTANCE_KM))
    if max_distance is None or not MIN_ROUTE_DISTANCE_KM <= max_distance <= MAX_ROUTE_DISTANCE_KM_LIMIT:
        errors[CONF_MAX_ROUTE_DISTANCE_KM] = "invalid_range"
    forecast_days = _as_int(data.get(CONF_FORECAST_DAYS))
    if forecast_days is None or not MIN_FORECAST_DAYS <= forecast_days <= MAX_FORECAST_DAYS:
        errors[CONF_FORECAST_DAYS] = "invalid_forecast_days"
    preferred_duration = str(data.get(CONF_PREFERRED_TRIP_DURATION, ""))
    if preferred_duration not in PREFERRED_TRIP_DURATION_OPTIONS:
        errors[CONF_PREFERRED_TRIP_DURATION] = "invalid_trip_duration"
    custom_duration = _as_int(data.get(CONF_CUSTOM_TRIP_DURATION_DAYS, DEFAULT_CUSTOM_TRIP_DURATION_DAYS))
    if custom_duration is None or custom_duration < MIN_TRIP_DURATION_DAYS:
        errors[CONF_CUSTOM_TRIP_DURATION_DAYS] = "invalid_trip_duration"
    elif preferred_duration in {"custom", "flexible"} and forecast_days is not None and custom_duration > forecast_days:
        errors[CONF_CUSTOM_TRIP_DURATION_DAYS] = "invalid_trip_duration"
    elif custom_duration > MAX_FORECAST_DAYS:
        errors[CONF_CUSTOM_TRIP_DURATION_DAYS] = "invalid_trip_duration"
    elif (
        preferred_duration in {"1", "2", "3"}
        and forecast_days is not None
        and int(preferred_duration) > forecast_days
    ):
        errors[CONF_PREFERRED_TRIP_DURATION] = "invalid_trip_duration"
    detour_factor = _as_float(data.get(CONF_DETOUR_FACTOR, DEFAULT_DETOUR_FACTOR))
    if detour_factor is None or not MIN_DETOUR_FACTOR <= detour_factor <= MAX_DETOUR_FACTOR:
        errors[CONF_DETOUR_FACTOR] = "invalid_detour_factor"
    if data.get(CONF_ACTIVITY_PROFILE, DEFAULT_ACTIVITY_PROFILE) not in SUPPORTED_ACTIVITY_PROFILES:
        errors[CONF_ACTIVITY_PROFILE] = "invalid_activity_profile"
    return errors


def _normalized_settings(data: dict[str, Any]) -> dict[str, Any]:
    settings = {
        CONF_MAX_ROUTE_DISTANCE_KM: float(data[CONF_MAX_ROUTE_DISTANCE_KM]),
        CONF_FORECAST_DAYS: int(data[CONF_FORECAST_DAYS]),
        CONF_PREFERRED_TRIP_DURATION: str(data[CONF_PREFERRED_TRIP_DURATION]),
        CONF_CUSTOM_TRIP_DURATION_DAYS: int(
            data.get(CONF_CUSTOM_TRIP_DURATION_DAYS, DEFAULT_CUSTOM_TRIP_DURATION_DAYS)
        ),
        CONF_ACTIVITY_PROFILE: str(data.get(CONF_ACTIVITY_PROFILE, DEFAULT_ACTIVITY_PROFILE)),
        CONF_DETOUR_FACTOR: float(data.get(CONF_DETOUR_FACTOR, DEFAULT_DETOUR_FACTOR)),
    }
    if CONF_TRAILER_SUPPORT_ENABLED in data:
        settings[CONF_TRAILER_SUPPORT_ENABLED] = bool(
            data.get(CONF_TRAILER_SUPPORT_ENABLED, DEFAULT_TRAILER_SUPPORT_ENABLED)
        )
    return settings


def _start_location_options(result: LocationResult) -> dict[str, Any]:
    return {
        CONF_START_ADDRESS: result.label,
        CONF_START_LATITUDE: result.latitude,
        CONF_START_LONGITUDE: result.longitude,
    }


def _current_start_location_options(config: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_START_ADDRESS: str(config.get(CONF_START_ADDRESS, "")),
        CONF_START_LATITUDE: config.get(CONF_START_LATITUDE),
        CONF_START_LONGITUDE: config.get(CONF_START_LONGITUDE),
    }


def _location_options(results: list[LocationResult]) -> list[dict[str, str]]:
    return [
        {
            "value": str(index),
            "label": f"{result.label} ({result.latitude:.2f}, {result.longitude:.2f})",
        }
        for index, result in enumerate(results)
    ]


def _selected_location_result(
    results: list[LocationResult],
    value: Any,
    errors: dict[str, str],
) -> LocationResult | None:
    try:
        index = int(value)
    except (TypeError, ValueError):
        errors[FIELD_LOCATION] = "invalid_location_choice"
        return None
    if index < 0 or index >= len(results):
        errors[FIELD_LOCATION] = "invalid_location_choice"
        return None
    return results[index]


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
