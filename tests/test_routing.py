"""Tests for route fallback calculations."""

import pytest

from custom_components.rideradar.models import DestinationArea
from custom_components.rideradar.routing import FallbackRoutingClient, haversine_distance_km


def test_haversine_distance_known_range() -> None:
    distance = haversine_distance_km(50.8503, 4.3517, 49.8153, 6.1296)

    assert distance == pytest.approx(171, rel=0.05)


async def test_fallback_route_uses_detour_factor() -> None:
    destination = DestinationArea(
        name="Luxembourg",
        country_region="Luxembourg",
        latitude=49.8153,
        longitude=6.1296,
    )
    client = FallbackRoutingClient(detour_factor=1.3, average_speed_kmh=65)

    route = await client.get_route(50.8503, 4.3517, destination, "motorcycle")

    direct = haversine_distance_km(50.8503, 4.3517, 49.8153, 6.1296)
    assert route.distance_km == pytest.approx(direct * 1.3, abs=0.1)
    assert route.travel_time_minutes == round((route.distance_km / 65) * 60)
    assert route.provider == "fallback_detour_1.3_motorcycle"

