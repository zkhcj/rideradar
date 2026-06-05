"""Routing abstractions for RideRadar."""

from __future__ import annotations

from abc import ABC, abstractmethod
from math import asin, cos, radians, sin, sqrt

from .const import (
    DEFAULT_AVERAGE_SPEED_KMH,
    DEFAULT_DETOUR_FACTOR,
    TRAVEL_STRATEGY_MOTORCYCLE_DIRECT,
    TRAVEL_STRATEGY_MOTORCYCLE_SCENIC,
    TRAVEL_STRATEGY_TRAILER,
)
from .models import DestinationArea, RouteInfo


class RoutingClient(ABC):
    """Interface for route distance/time providers."""

    @abstractmethod
    async def get_route(
        self,
        start_latitude: float,
        start_longitude: float,
        destination: DestinationArea,
        activity_profile: str,
    ) -> RouteInfo:
        """Return route information for a destination."""


class FallbackRoutingClient(RoutingClient):
    """Estimate realistic route distance from haversine distance and a detour factor."""

    def __init__(
        self,
        detour_factor: float = DEFAULT_DETOUR_FACTOR,
        average_speed_kmh: float = DEFAULT_AVERAGE_SPEED_KMH,
    ) -> None:
        if detour_factor < 1:
            raise ValueError("detour_factor must be at least 1")
        if average_speed_kmh <= 0:
            raise ValueError("average_speed_kmh must be positive")
        self._detour_factor = detour_factor
        self._average_speed_kmh = average_speed_kmh

    async def get_route(
        self,
        start_latitude: float,
        start_longitude: float,
        destination: DestinationArea,
        activity_profile: str,
    ) -> RouteInfo:
        """Return an estimated route using a configurable detour factor."""
        direct_distance_km = haversine_distance_km(
            start_latitude,
            start_longitude,
            destination.latitude,
            destination.longitude,
        )
        assumptions = fallback_assumptions(activity_profile, self._detour_factor, self._average_speed_kmh)
        distance_km = direct_distance_km * assumptions["detour_factor"]
        travel_time_minutes = round((distance_km / assumptions["average_speed_kmh"]) * 60)
        return RouteInfo(
            distance_km=round(distance_km, 1),
            travel_time_minutes=max(1, travel_time_minutes),
            provider="fallback",
            confidence="low",
            distance_method="haversine_detour",
            time_method="average_speed_estimate",
            direct_distance_km=round(direct_distance_km, 1),
            assumed_average_speed_kmh=assumptions["average_speed_kmh"],
            detour_factor=assumptions["detour_factor"],
        )


def fallback_assumptions(activity_profile: str, detour_factor: float, average_speed_kmh: float) -> dict[str, float]:
    """Return strategy-aware fallback assumptions."""
    normalized = activity_profile.strip().casefold()
    if normalized == TRAVEL_STRATEGY_MOTORCYCLE_SCENIC:
        return {
            "detour_factor": max(detour_factor, 1.35),
            "average_speed_kmh": min(average_speed_kmh, 58.0),
        }
    if normalized == TRAVEL_STRATEGY_TRAILER:
        return {
            "detour_factor": max(detour_factor, 1.2),
            "average_speed_kmh": max(average_speed_kmh, 78.0),
        }
    if normalized == TRAVEL_STRATEGY_MOTORCYCLE_DIRECT:
        return {
            "detour_factor": max(detour_factor, 1.18),
            "average_speed_kmh": max(average_speed_kmh, 82.0),
        }
    return {
        "detour_factor": detour_factor,
        "average_speed_kmh": average_speed_kmh,
    }


def haversine_distance_km(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    """Calculate direct geographic distance in km before applying routing detour."""
    radius_km = 6371.0
    lat_1 = radians(start_latitude)
    lat_2 = radians(end_latitude)
    delta_lat = radians(end_latitude - start_latitude)
    delta_lon = radians(end_longitude - start_longitude)

    haversine = sin(delta_lat / 2) ** 2 + cos(lat_1) * cos(lat_2) * sin(delta_lon / 2) ** 2
    return 2 * radius_km * asin(sqrt(haversine))
