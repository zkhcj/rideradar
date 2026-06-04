"""Constants for the RideRadar integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "rideradar"
PLATFORMS: Final = [Platform.SENSOR, Platform.SELECT, Platform.NUMBER, Platform.SWITCH]
INTEGRATION_VERSION: Final = "0.1.1"

ATTRIBUTION: Final = "Weather data provided by Open-Meteo"
MANUFACTURER: Final = "RideRadar"

CONF_START_ADDRESS: Final = "start_address"
CONF_START_LATITUDE: Final = "start_latitude"
CONF_START_LONGITUDE: Final = "start_longitude"
CONF_MAX_ROUTE_DISTANCE_KM: Final = "max_route_distance_km"
CONF_FORECAST_DAYS: Final = "forecast_days"
CONF_PREFERRED_TRIP_DURATION: Final = "preferred_trip_duration"
CONF_CUSTOM_TRIP_DURATION_DAYS: Final = "custom_trip_duration_days"
CONF_DURATION_MODE: Final = "duration_mode"
CONF_TRAILER_SUPPORT_ENABLED: Final = "trailer_support_enabled"
CONF_ACTIVITY_PROFILE: Final = "activity_profile"
CONF_DESTINATIONS: Final = "destinations"
CONF_ENABLED_DEFAULT_DESTINATIONS: Final = "enabled_default_destinations"
CONF_CUSTOM_DESTINATIONS: Final = "custom_destinations"
CONF_DETOUR_FACTOR: Final = "detour_factor"

DEFAULT_FORECAST_DAYS: Final = 8
DEFAULT_PREFERRED_TRIP_DURATION: Final = "2"
DEFAULT_CUSTOM_TRIP_DURATION_DAYS: Final = 2
DEFAULT_DURATION_MODE: Final = "fixed"
DEFAULT_TRAILER_SUPPORT_ENABLED: Final = False
DEFAULT_TRAVEL_STRATEGY: Final = "motorcycle_direct"
DEFAULT_AVAILABLE_HOURS_PER_DAY: Final = 8.0
DEFAULT_MAX_APPROACH_TIME_HOURS: Final = 4.0
DEFAULT_MAX_ROUTE_DISTANCE_KM: Final = 350.0
DEFAULT_ACTIVITY_PROFILE: Final = "motorcycle"
SUPPORTED_ACTIVITY_PROFILES: Final = (DEFAULT_ACTIVITY_PROFILE,)
DEFAULT_DETOUR_FACTOR: Final = 1.25
DEFAULT_AVERAGE_SPEED_KMH: Final = 70.0
DEFAULT_WEATHER_REFRESH_INTERVAL_HOURS: Final = 4
DEFAULT_FRESH_FORECAST_MAX_AGE_HOURS: Final = 4
DEFAULT_STALE_FORECAST_MAX_AGE_HOURS: Final = 24
DEFAULT_ALLOW_STALE_FORECAST_FALLBACK: Final = True
DEFAULT_MAX_WEATHER_CALLS_PER_HOUR: Final = 60
DEFAULT_MAX_WEATHER_CALLS_PER_DAY: Final = 500
DEFAULT_PROVIDER_BACKOFF_MINUTES_AFTER_RATE_LIMIT: Final = 60

MIN_FORECAST_DAYS: Final = 1
MAX_FORECAST_DAYS: Final = 16
MIN_TRIP_DURATION_DAYS: Final = 1
PREFERRED_TRIP_DURATION_OPTIONS: Final = ("1", "2", "3", "flexible", "custom")
DURATION_MODE_OPTIONS: Final = ("fixed", "flexible")
TRAVEL_STRATEGY_MOTORCYCLE_DIRECT: Final = "motorcycle_direct"
TRAVEL_STRATEGY_MOTORCYCLE_SCENIC: Final = "motorcycle_scenic"
TRAVEL_STRATEGY_TRAILER: Final = "trailer"
TRAVEL_STRATEGY_OPTIONS: Final = (
    TRAVEL_STRATEGY_MOTORCYCLE_DIRECT,
    TRAVEL_STRATEGY_MOTORCYCLE_SCENIC,
    TRAVEL_STRATEGY_TRAILER,
)
CONTROL_TRIP_DURATION: Final = "trip_duration"
CONTROL_TRIP_DURATION_DAYS: Final = "trip_duration_days"
CONTROL_FORECAST_HORIZON_DAYS: Final = "forecast_horizon_days"
CONTROL_PREFERRED_START_DAY: Final = "preferred_start_day"
CONTROL_WEEKEND_ONLY: Final = "weekend_only"
CONTROL_TRAVEL_STRATEGY: Final = "travel_strategy"
CONTROL_TRAILER_AVAILABLE: Final = "trailer_available"
CONTROL_AVAILABLE_HOURS_PER_DAY: Final = "available_hours_per_day"
CONTROL_MAX_APPROACH_TIME_HOURS: Final = "max_approach_time_hours"
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
