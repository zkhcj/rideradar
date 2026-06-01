"""Open-Meteo API client for RideRadar."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession, ContentTypeError
from homeassistant.exceptions import HomeAssistantError

from .const import OPEN_METEO_FORECAST_URL, OPEN_METEO_GEOCODING_URL
from .models import DailyForecast


class RideRadarApiError(HomeAssistantError):
    """Raised when Open-Meteo cannot return usable data."""


class OpenMeteoClient:
    """Async Open-Meteo API client."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def geocode(self, address: str) -> tuple[float, float] | None:
        """Resolve an address or place name to latitude/longitude."""
        params = {"name": address, "count": 1, "language": "en", "format": "json"}
        payload = await self._get_json(OPEN_METEO_GEOCODING_URL, params, "geocode start address")
        results = payload.get("results") or []
        if not results:
            return None
        first = results[0]
        try:
            return float(first["latitude"]), float(first["longitude"])
        except (KeyError, TypeError, ValueError) as err:
            raise RideRadarApiError("Open-Meteo geocoding response did not include coordinates") from err

    async def get_daily_forecast(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int,
    ) -> list[DailyForecast]:
        """Fetch daily forecast data for one destination."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "forecast_days": forecast_days,
            "timezone": "auto",
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "precipitation_probability_max",
                    "precipitation_sum",
                    "wind_speed_10m_max",
                    "wind_gusts_10m_max",
                    "cloud_cover_mean",
                ]
            ),
        }
        payload = await self._get_json(OPEN_METEO_FORECAST_URL, params, "fetch forecast")
        daily = payload.get("daily")
        if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
            raise RideRadarApiError("Open-Meteo forecast response did not include daily data")

        return [
            DailyForecast(
                date=str(date),
                temperature_c=_optional_float(daily, "temperature_2m_max", index),
                precipitation_probability=_optional_float(daily, "precipitation_probability_max", index),
                precipitation_amount_mm=_optional_float(daily, "precipitation_sum", index),
                wind_speed_kmh=_optional_float(daily, "wind_speed_10m_max", index),
                wind_gusts_kmh=_optional_float(daily, "wind_gusts_10m_max", index),
                cloud_cover=_optional_float(daily, "cloud_cover_mean", index),
                weather_code=_optional_int(daily, "weather_code", index),
            )
            for index, date in enumerate(daily["time"])
        ]

    async def _get_json(self, url: str, params: dict[str, Any], action: str) -> dict[str, Any]:
        """Fetch JSON and normalize aiohttp errors for Home Assistant."""
        try:
            async with self._session.get(url, params=params, timeout=30) as response:
                response.raise_for_status()
                payload = await response.json()
        except ContentTypeError as err:
            raise RideRadarApiError(f"Could not {action}: Open-Meteo returned invalid JSON") from err
        except ClientResponseError as err:
            raise RideRadarApiError(f"Could not {action}: Open-Meteo returned HTTP {err.status}") from err
        except (TimeoutError, ClientError) as err:
            raise RideRadarApiError(f"Could not {action}: {err}") from err
        if not isinstance(payload, dict):
            raise RideRadarApiError(f"Could not {action}: Open-Meteo returned invalid JSON")
        return payload


def _optional_float(data: dict[str, Any], key: str, index: int) -> float | None:
    values = data.get(key) or []
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _optional_int(data: dict[str, Any], key: str, index: int) -> int | None:
    values = data.get(key) or []
    if index >= len(values) or values[index] is None:
        return None
    return int(values[index])
