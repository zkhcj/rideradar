"""Geocoding abstractions for RideRadar."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession, ContentTypeError
from homeassistant.exceptions import HomeAssistantError

from .const import OPEN_METEO_GEOCODING_URL


class GeocodingError(HomeAssistantError):
    """Raised when a geocoding provider cannot return usable results."""


@dataclass(frozen=True, slots=True)
class LocationResult:
    """Resolved geocoding result."""

    label: str
    latitude: float
    longitude: float
    country_region: str | None = None

    def as_option(self, index: int) -> dict[str, str]:
        """Return a Home Assistant select option."""
        return {"value": str(index), "label": self.label}


class GeocodingClient(ABC):
    """Interface for free geocoding providers."""

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[LocationResult]:
        """Search for matching locations."""


class OpenMeteoGeocodingClient(GeocodingClient):
    """Free Open-Meteo geocoding client."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def search(self, query: str, limit: int = 5) -> list[LocationResult]:
        """Search Open-Meteo geocoding for matching locations."""
        params = {"name": query, "count": limit, "language": "en", "format": "json"}
        try:
            async with self._session.get(OPEN_METEO_GEOCODING_URL, params=params, timeout=20) as response:
                response.raise_for_status()
                payload = await response.json()
        except ContentTypeError as err:
            raise GeocodingError("Geocoding returned invalid JSON") from err
        except ClientResponseError as err:
            raise GeocodingError(f"Geocoding returned HTTP {err.status}") from err
        except (TimeoutError, ClientError) as err:
            raise GeocodingError(f"Geocoding failed: {err}") from err
        if not isinstance(payload, dict):
            raise GeocodingError("Geocoding returned invalid data")

        results = payload.get("results") or []
        if not isinstance(results, list):
            raise GeocodingError("Geocoding results were invalid")
        return [_location_from_open_meteo(item) for item in results if isinstance(item, dict)]


def _location_from_open_meteo(value: dict[str, Any]) -> LocationResult:
    name = str(value.get("name") or "").strip()
    admin = str(value.get("admin1") or "").strip()
    country = str(value.get("country") or "").strip()
    parts = [part for part in (name, admin, country) if part]
    if not parts:
        raise GeocodingError("Geocoding result did not include a name")
    try:
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
    except (KeyError, TypeError, ValueError) as err:
        raise GeocodingError("Geocoding result did not include coordinates") from err
    return LocationResult(
        label=", ".join(parts),
        latitude=latitude,
        longitude=longitude,
        country_region=", ".join(part for part in (admin, country) if part) or country or None,
    )
