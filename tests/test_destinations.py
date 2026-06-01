"""Tests for RideRadar destinations."""

import json

import pytest

from custom_components.rideradar.const import CONF_CUSTOM_DESTINATIONS, CONF_ENABLED_DEFAULT_DESTINATIONS
from custom_components.rideradar.destinations import (
    DEFAULT_DESTINATIONS,
    default_destination_names,
    default_destinations_as_dicts,
    destinations_from_config,
    parse_destinations_data,
)
from custom_components.rideradar.models import DestinationArea, RideRadarConfigError


def test_default_destinations_include_required_areas() -> None:
    assert set(default_destination_names()) == {
        "Sauerland",
        "Vogezen",
        "Dolomieten",
        "Harz",
        "Moezel",
        "Eifel",
        "Klein Zwitserland, Luxemburg",
        "Zwarte Woud",
        "Teutoburgerwoud",
    }


@pytest.mark.parametrize("destination", DEFAULT_DESTINATIONS)
def test_default_destinations_are_enabled_and_serializable(destination: DestinationArea) -> None:
    serialized = destination.as_dict()

    assert serialized["enabled"] is True
    assert isinstance(serialized["latitude"], float)
    assert isinstance(serialized["longitude"], float)


def test_builds_enabled_default_and_custom_destinations() -> None:
    custom = DestinationArea("Ardennes", "Belgium", 50.25, 5.67).as_dict()

    destinations = destinations_from_config(
        {
            CONF_ENABLED_DEFAULT_DESTINATIONS: ["Sauerland", "Eifel"],
            CONF_CUSTOM_DESTINATIONS: [custom],
        }
    )

    assert [destination.name for destination in destinations] == ["Sauerland", "Eifel", "Ardennes"]


def test_legacy_destination_json_parsing() -> None:
    raw = json.dumps(default_destinations_as_dicts())

    destinations = parse_destinations_data(raw)

    assert len(destinations) == 9


def test_malformed_legacy_destination_json_is_rejected() -> None:
    with pytest.raises((json.JSONDecodeError, RideRadarConfigError)):
        parse_destinations_data("not json")
