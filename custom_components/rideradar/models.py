"""Typed models used by RideRadar."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class RideRadarConfigError(ValueError):
    """Raised when RideRadar configuration data is invalid."""


@dataclass(frozen=True, slots=True)
class DestinationArea:
    """A destination area that can be scored for a trip."""

    name: str
    country_region: str
    latitude: float
    longitude: float
    enabled: bool = True
    notes: str | None = None
    preferred_route_target_address: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DestinationArea:
        """Create a destination area from user-editable config data."""
        if not isinstance(value, dict):
            raise RideRadarConfigError("Destination must be an object")
        try:
            name = _required_text(value, "name")
            country_region = _required_text(value, "country_region")
            latitude = float(value["latitude"])
            longitude = float(value["longitude"])
        except (KeyError, TypeError, ValueError) as err:
            raise RideRadarConfigError("Destination is missing required fields") from err

        if not -90 <= latitude <= 90:
            raise RideRadarConfigError(f"Destination latitude out of range for {name}")
        if not -180 <= longitude <= 180:
            raise RideRadarConfigError(f"Destination longitude out of range for {name}")

        return cls(
            name=name,
            country_region=country_region,
            latitude=latitude,
            longitude=longitude,
            enabled=_optional_bool(value.get("enabled", True)),
            notes=_optional_text(value.get("notes")),
            preferred_route_target_address=_optional_text(value.get("preferred_route_target_address")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the destination as Home Assistant config-friendly data."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RouteInfo:
    """Route information returned by a routing provider."""

    distance_km: float
    travel_time_minutes: int
    provider: str


@dataclass(frozen=True, slots=True)
class DailyForecast:
    """Weather forecast values for a destination on one day."""

    date: str
    temperature_c: float | None
    precipitation_probability: float | None
    precipitation_amount_mm: float | None
    wind_speed_kmh: float | None
    wind_gusts_kmh: float | None
    cloud_cover: float | None
    weather_code: int | None


@dataclass(frozen=True, slots=True)
class RideScore:
    """Score result for a destination/day pair."""

    score: int
    explanation: str


@dataclass(frozen=True, slots=True)
class TripScoreBreakdown:
    """Detailed score components for a complete trip window."""

    average_daily_score: int
    worst_daily_score: int
    weather_stability_score: int
    bad_weather_penalty: int
    duration_days: int


@dataclass(frozen=True, slots=True)
class TripWindow:
    """A consecutive forecast window evaluated as one trip."""

    start_day: str
    end_day: str
    duration_days: int
    trip_score: int
    daily_scores: dict[str, int]
    weather_stability_score: int
    stability_explanation: str
    trip_score_breakdown: TripScoreBreakdown
    trip_explanation: str


@dataclass(frozen=True, slots=True)
class RideExperience:
    """Non-weather riding quality signals for one trip window."""

    ride_quality_score: int
    weather_score: int
    traffic_score: int
    tourism_pressure_score: int
    holiday_score: int
    motorcycle_access_score: int
    distance_score: int
    temperature_score: int
    road_fun_score: int
    holiday_names: list[str]
    access_notes: list[str]
    explanation: str


@dataclass(frozen=True, slots=True)
class DestinationResult:
    """Fully evaluated destination result."""

    destination: DestinationArea
    route: RouteInfo | None
    forecasts: list[DailyForecast]
    scores: dict[str, RideScore]
    best_day: str | None
    best_score: int | None
    best_forecast: DailyForecast | None
    trip_score: int | None
    best_trip_window: TripWindow | None
    best_start_day: str | None
    trip_duration: int
    weather_stability_score: int | None
    stability_explanation: str
    daily_scores: dict[str, int]
    trip_score_breakdown: TripScoreBreakdown | None
    trip_explanation: str
    ride_quality_score: int | None
    ride_experience: RideExperience | None
    all_trip_windows: list[TripWindow]
    reachable: bool
    available: bool
    explanation: str


def _required_text(value: dict[str, Any], key: str) -> str:
    text = str(value[key]).strip()
    if not text:
        raise RideRadarConfigError(f"{key} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return bool(value)
