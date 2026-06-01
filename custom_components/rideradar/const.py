"""Constants for the RideRadar integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "rideradar"
PLATFORMS: Final = [Platform.SENSOR]

ATTRIBUTION: Final = "Weather data provided by Open-Meteo"
MANUFACTURER: Final = "RideRadar"

CONF_START_ADDRESS: Final = "start_address"
CONF_START_LATITUDE: Final = "start_latitude"
CONF_START_LONGITUDE: Final = "start_longitude"
CONF_MAX_ROUTE_DISTANCE_KM: Final = "max_route_distance_km"
CONF_FORECAST_DAYS: Final = "forecast_days"
CONF_PREFERRED_TRIP_DURATION: Final = "preferred_trip_duration"
CONF_CUSTOM_TRIP_DURATION_DAYS: Final = "custom_trip_duration_days"
CONF_ACTIVITY_PROFILE: Final = "activity_profile"
CONF_DESTINATIONS: Final = "destinations"
CONF_ENABLED_DEFAULT_DESTINATIONS: Final = "enabled_default_destinations"
CONF_CUSTOM_DESTINATIONS: Final = "custom_destinations"
CONF_DETOUR_FACTOR: Final = "detour_factor"

DEFAULT_FORECAST_DAYS: Final = 3
DEFAULT_PREFERRED_TRIP_DURATION: Final = "2"
DEFAULT_CUSTOM_TRIP_DURATION_DAYS: Final = 2
DEFAULT_MAX_ROUTE_DISTANCE_KM: Final = 350.0
DEFAULT_ACTIVITY_PROFILE: Final = "motorcycle"
SUPPORTED_ACTIVITY_PROFILES: Final = (DEFAULT_ACTIVITY_PROFILE,)
DEFAULT_DETOUR_FACTOR: Final = 1.25
DEFAULT_AVERAGE_SPEED_KMH: Final = 70.0

MIN_FORECAST_DAYS: Final = 1
MAX_FORECAST_DAYS: Final = 7
MIN_TRIP_DURATION_DAYS: Final = 1
PREFERRED_TRIP_DURATION_OPTIONS: Final = ("1", "2", "3", "custom")
MIN_DETOUR_FACTOR: Final = 1.0
MAX_DETOUR_FACTOR: Final = 2.5
MIN_LATITUDE: Final = -90.0
MAX_LATITUDE: Final = 90.0
MIN_LONGITUDE: Final = -180.0
MAX_LONGITUDE: Final = 180.0
MIN_ROUTE_DISTANCE_KM: Final = 1.0
MAX_ROUTE_DISTANCE_KM_LIMIT: Final = 5000.0
MIN_GEOCODE_QUERY_LENGTH: Final = 3

UPDATE_INTERVAL: Final = timedelta(hours=3)

OPEN_METEO_FORECAST_URL: Final = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODING_URL: Final = "https://geocoding-api.open-meteo.com/v1/search"
