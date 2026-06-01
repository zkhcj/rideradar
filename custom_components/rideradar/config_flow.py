"""Config flow for RideRadar."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
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

from .api import OpenMeteoClient, RideRadarApiError
from .const import (
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
    MAX_DETOUR_FACTOR,
    MAX_FORECAST_DAYS,
    MAX_LATITUDE,
    MAX_LONGITUDE,
    MAX_ROUTE_DISTANCE_KM_LIMIT,
    MIN_DETOUR_FACTOR,
    MIN_FORECAST_DAYS,
    MIN_LATITUDE,
    MIN_LONGITUDE,
    MIN_ROUTE_DISTANCE_KM,
    SUPPORTED_ACTIVITY_PROFILES,
)
from .destinations import default_destinations_as_dicts
from .models import DestinationArea, RideRadarConfigError


class RideRadarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle RideRadar config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Create a RideRadar config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await _validate_and_normalize(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="RideRadar", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> RideRadarOptionsFlow:
        """Return the options flow."""
        return RideRadarOptionsFlow(config_entry)


class RideRadarOptionsFlow(config_entries.OptionsFlow):
    """Handle RideRadar options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage RideRadar options."""
        errors: dict[str, str] = {}
        defaults = {**self._config_entry.data, **self._config_entry.options}
        if user_input is not None:
            data, errors = await _validate_and_normalize(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(user_input or defaults),
            errors=errors,
        )


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_START_ADDRESS,
                default=defaults.get(CONF_START_ADDRESS, ""),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            _optional_number_key(CONF_START_LATITUDE, defaults): NumberSelector(
                NumberSelectorConfig(mode=NumberSelectorMode.BOX)
            ),
            _optional_number_key(CONF_START_LONGITUDE, defaults): NumberSelector(
                NumberSelectorConfig(mode=NumberSelectorMode.BOX)
            ),
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
                CONF_FORECAST_DAYS,
                default=defaults.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
            ): NumberSelector(
                NumberSelectorConfig(
                    mode=NumberSelectorMode.BOX,
                    min=MIN_FORECAST_DAYS,
                    max=MAX_FORECAST_DAYS,
                    step=1,
                )
            ),
            vol.Required(
                CONF_ACTIVITY_PROFILE,
                default=defaults.get(CONF_ACTIVITY_PROFILE, DEFAULT_ACTIVITY_PROFILE),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(SUPPORTED_ACTIVITY_PROFILES),
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_DETOUR_FACTOR,
                default=defaults.get(CONF_DETOUR_FACTOR, DEFAULT_DETOUR_FACTOR),
            ): NumberSelector(
                NumberSelectorConfig(
                    mode=NumberSelectorMode.BOX,
                    min=MIN_DETOUR_FACTOR,
                    max=MAX_DETOUR_FACTOR,
                    step=0.05,
                )
            ),
            vol.Required(
                CONF_DESTINATIONS,
                default=_destinations_to_json(defaults.get(CONF_DESTINATIONS)),
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)),
        }
    )


def _optional_number_key(key: str, defaults: dict[str, Any]) -> vol.Optional:
    if defaults.get(key) is None:
        return vol.Optional(key)
    return vol.Optional(key, default=defaults[key])


async def _validate_and_normalize(
    hass: HomeAssistant,
    user_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate user input and return normalized config data."""
    errors: dict[str, str] = {}
    data = dict(user_input)

    try:
        destinations = _parse_destinations(data.get(CONF_DESTINATIONS, []))
    except (TypeError, ValueError, json.JSONDecodeError, RideRadarConfigError):
        errors[CONF_DESTINATIONS] = "invalid_destinations"
        destinations = []

    latitude, longitude = await _resolve_start_coordinates(hass, data, errors)
    _validate_numeric_settings(data, errors)

    if errors:
        return {}, errors

    return {
        CONF_START_ADDRESS: str(data.get(CONF_START_ADDRESS, "")).strip(),
        CONF_START_LATITUDE: float(latitude),
        CONF_START_LONGITUDE: float(longitude),
        CONF_MAX_ROUTE_DISTANCE_KM: float(data[CONF_MAX_ROUTE_DISTANCE_KM]),
        CONF_FORECAST_DAYS: int(data[CONF_FORECAST_DAYS]),
        CONF_ACTIVITY_PROFILE: str(data[CONF_ACTIVITY_PROFILE]),
        CONF_DETOUR_FACTOR: float(data[CONF_DETOUR_FACTOR]),
        CONF_DESTINATIONS: [destination.as_dict() for destination in destinations],
    }, {}


async def _resolve_start_coordinates(
    hass: HomeAssistant,
    data: dict[str, Any],
    errors: dict[str, str],
) -> tuple[float | None, float | None]:
    latitude = data.get(CONF_START_LATITUDE)
    longitude = data.get(CONF_START_LONGITUDE)
    has_latitude = latitude is not None
    has_longitude = longitude is not None

    if has_latitude != has_longitude:
        errors[CONF_START_LATITUDE if not has_latitude else CONF_START_LONGITUDE] = "coordinates_required"
        return None, None

    if has_latitude and has_longitude:
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            errors[CONF_START_LATITUDE] = "invalid_coordinates"
            return None, None
        if not MIN_LATITUDE <= latitude <= MAX_LATITUDE:
            errors[CONF_START_LATITUDE] = "invalid_coordinates"
        if not MIN_LONGITUDE <= longitude <= MAX_LONGITUDE:
            errors[CONF_START_LONGITUDE] = "invalid_coordinates"
        return latitude, longitude

    address = str(data.get(CONF_START_ADDRESS, "")).strip()
    if not address:
        errors[CONF_START_ADDRESS] = "address_or_coordinates_required"
        return None, None

    try:
        result = await OpenMeteoClient(async_get_clientsession(hass)).geocode(address)
    except RideRadarApiError:
        errors[CONF_START_ADDRESS] = "geocoding_failed"
        return None, None
    if result is None:
        errors[CONF_START_ADDRESS] = "address_not_found"
        return None, None
    return result


def _validate_numeric_settings(data: dict[str, Any], errors: dict[str, str]) -> None:
    try:
        max_distance = float(data[CONF_MAX_ROUTE_DISTANCE_KM])
    except (KeyError, TypeError, ValueError):
        errors[CONF_MAX_ROUTE_DISTANCE_KM] = "invalid_range"
    else:
        if not MIN_ROUTE_DISTANCE_KM <= max_distance <= MAX_ROUTE_DISTANCE_KM_LIMIT:
            errors[CONF_MAX_ROUTE_DISTANCE_KM] = "invalid_range"

    try:
        forecast_days = int(data[CONF_FORECAST_DAYS])
    except (KeyError, TypeError, ValueError):
        errors[CONF_FORECAST_DAYS] = "invalid_forecast_days"
    else:
        if not MIN_FORECAST_DAYS <= forecast_days <= MAX_FORECAST_DAYS:
            errors[CONF_FORECAST_DAYS] = "invalid_forecast_days"

    try:
        detour_factor = float(data[CONF_DETOUR_FACTOR])
    except (KeyError, TypeError, ValueError):
        errors[CONF_DETOUR_FACTOR] = "invalid_detour_factor"
    else:
        if not MIN_DETOUR_FACTOR <= detour_factor <= MAX_DETOUR_FACTOR:
            errors[CONF_DETOUR_FACTOR] = "invalid_detour_factor"

    if data.get(CONF_ACTIVITY_PROFILE) not in SUPPORTED_ACTIVITY_PROFILES:
        errors[CONF_ACTIVITY_PROFILE] = "invalid_activity_profile"


def _parse_destinations(value: str | list[dict[str, Any]]) -> list[DestinationArea]:
    if isinstance(value, str):
        stripped = value.strip()
        decoded = [] if not stripped else json.loads(stripped)
    else:
        decoded = value
    if not isinstance(decoded, list):
        raise RideRadarConfigError("Destinations must be a list")
    return [DestinationArea.from_dict(item) for item in decoded]


def _destinations_to_json(value: object | None) -> str:
    destinations = value if value is not None else default_destinations_as_dicts()
    return json.dumps(destinations, indent=2)
