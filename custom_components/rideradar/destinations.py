"""Default destination areas for RideRadar."""

from __future__ import annotations

from typing import Any

from .models import DestinationArea

DEFAULT_DESTINATIONS: tuple[DestinationArea, ...] = (
    DestinationArea("Sauerland", "Germany, North Rhine-Westphalia", 51.1800, 8.2500),
    DestinationArea("Vosges / Vogezen", "France, Grand Est", 48.1700, 7.1600),
    DestinationArea("Dolomites / Dolomieten", "Italy, South Tyrol / Veneto", 46.4100, 11.8500),
    DestinationArea("Harz", "Germany, Lower Saxony / Saxony-Anhalt", 51.8000, 10.6200),
    DestinationArea("Moselle / Moezel", "Germany / Luxembourg / France", 49.8800, 7.0600),
    DestinationArea("Eifel", "Germany / Belgium", 50.4500, 6.5500),
    DestinationArea(
        "Little Switzerland / Klein Zwitserland, Luxembourg",
        "Luxembourg, Mullerthal",
        49.7900,
        6.3300,
    ),
    DestinationArea("Black Forest / Zwarte Woud", "Germany, Baden-Wurttemberg", 48.0000, 8.1000),
    DestinationArea("Teutoburg Forest / Teutoburgerwoud", "Germany, North Rhine-Westphalia", 51.9000, 8.8500),
)


def default_destinations_as_dicts() -> list[dict[str, Any]]:
    """Return JSON-serializable default destinations."""
    return [destination.as_dict() for destination in DEFAULT_DESTINATIONS]


def destinations_from_config(value: list[dict[str, Any]] | None) -> list[DestinationArea]:
    """Parse destinations from config, falling back only when config is absent."""
    if value is None:
        return list(DEFAULT_DESTINATIONS)
    return [DestinationArea.from_dict(item) for item in value]
