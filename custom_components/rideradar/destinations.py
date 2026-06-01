"""Destination area helpers for RideRadar."""

from __future__ import annotations

import json
from typing import Any

from .const import CONF_CUSTOM_DESTINATIONS, CONF_DESTINATIONS, CONF_ENABLED_DEFAULT_DESTINATIONS
from .models import DestinationArea, RideRadarConfigError

DEFAULT_DESTINATIONS: tuple[DestinationArea, ...] = (
    DestinationArea("Sauerland", "Duitsland, Noordrijn-Westfalen", 51.1800, 8.2500),
    DestinationArea("Vogezen", "Frankrijk, Grand Est", 48.1700, 7.1600),
    DestinationArea("Dolomieten", "Italie, Zuid-Tirol / Veneto", 46.4100, 11.8500),
    DestinationArea("Harz", "Duitsland, Nedersaksen / Saksen-Anhalt", 51.8000, 10.6200),
    DestinationArea("Moezel", "Duitsland / Luxemburg / Frankrijk", 49.8800, 7.0600),
    DestinationArea("Eifel", "Duitsland / Belgie", 50.4500, 6.5500),
    DestinationArea("Klein Zwitserland, Luxemburg", "Luxemburg, Mullerthal", 49.7900, 6.3300),
    DestinationArea("Zwarte Woud", "Duitsland, Baden-Wurttemberg", 48.0000, 8.1000),
    DestinationArea("Teutoburgerwoud", "Duitsland, Noordrijn-Westfalen", 51.9000, 8.8500),
)


def default_destination_names() -> list[str]:
    """Return default destination names."""
    return [destination.name for destination in DEFAULT_DESTINATIONS]


def default_destinations_as_dicts() -> list[dict[str, Any]]:
    """Return JSON-serializable default destinations."""
    return [destination.as_dict() for destination in DEFAULT_DESTINATIONS]


def destination_options(destinations: list[DestinationArea]) -> list[dict[str, str]]:
    """Return destination select options."""
    return [{"value": destination.name, "label": destination.name} for destination in destinations]


def destinations_from_config(config: dict[str, Any] | list[dict[str, Any]] | None) -> list[DestinationArea]:
    """Build enabled destinations from modern or legacy config data."""
    if config is None:
        return [destination for destination in DEFAULT_DESTINATIONS]
    if isinstance(config, list):
        destinations = [DestinationArea.from_dict(item) for item in config]
        return [destination for destination in destinations if destination.enabled]

    legacy = config.get(CONF_DESTINATIONS)
    if (
        legacy is not None
        and CONF_ENABLED_DEFAULT_DESTINATIONS not in config
        and CONF_CUSTOM_DESTINATIONS not in config
    ):
        return [destination for destination in parse_destinations_data(legacy) if destination.enabled]

    enabled_defaults = set(config.get(CONF_ENABLED_DEFAULT_DESTINATIONS) or default_destination_names())
    defaults = [
        DestinationArea(
            destination.name,
            destination.country_region,
            destination.latitude,
            destination.longitude,
            enabled=True,
            notes=destination.notes,
            preferred_route_target_address=destination.preferred_route_target_address,
        )
        for destination in DEFAULT_DESTINATIONS
        if destination.name in enabled_defaults
    ]
    custom = [destination for destination in custom_destinations_from_config(config) if destination.enabled]
    return defaults + custom


def custom_destinations_from_config(config: dict[str, Any]) -> list[DestinationArea]:
    """Return all custom destinations, including disabled ones."""
    return parse_destinations_data(config.get(CONF_CUSTOM_DESTINATIONS, []))


def parse_destinations_data(value: str | list[dict[str, Any]] | None) -> list[DestinationArea]:
    """Parse destination data from structured config or legacy JSON."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        decoded = json.loads(stripped)
    else:
        decoded = value
    if not isinstance(decoded, list):
        raise RideRadarConfigError("Destinations must be a list")
    return [DestinationArea.from_dict(item) for item in decoded]


def all_destinations_for_options(config: dict[str, Any]) -> list[DestinationArea]:
    """Return defaults and custom destinations for options editing."""
    return list(DEFAULT_DESTINATIONS) + custom_destinations_from_config(config)


def enabled_destination_keys(config: dict[str, Any]) -> list[str]:
    """Return select values for currently enabled defaults and custom destinations."""
    enabled_defaults = set(config.get(CONF_ENABLED_DEFAULT_DESTINATIONS) or default_destination_names())
    keys = [f"default:{name}" for name in enabled_defaults]
    keys.extend(
        f"custom:{destination.name}" for destination in custom_destinations_from_config(config) if destination.enabled
    )
    return keys


def destination_enable_options(config: dict[str, Any]) -> list[dict[str, str]]:
    """Return select options for enabling/disabling destinations."""
    options = [
        {"value": f"default:{destination.name}", "label": destination.name} for destination in DEFAULT_DESTINATIONS
    ]
    options.extend(
        {"value": f"custom:{destination.name}", "label": f"{destination.name} (custom)"}
        for destination in custom_destinations_from_config(config)
    )
    return options
