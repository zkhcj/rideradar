"""Tests for default RideRadar destinations."""

from custom_components.rideradar.destinations import DEFAULT_DESTINATIONS, default_destinations_as_dicts


def test_default_destinations_include_required_areas() -> None:
    names = {destination.name for destination in DEFAULT_DESTINATIONS}

    assert names == {
        "Sauerland",
        "Vosges / Vogezen",
        "Dolomites / Dolomieten",
        "Harz",
        "Moselle / Moezel",
        "Eifel",
        "Little Switzerland / Klein Zwitserland, Luxembourg",
        "Black Forest / Zwarte Woud",
        "Teutoburg Forest / Teutoburgerwoud",
    }


def test_default_destinations_are_enabled_and_serializable() -> None:
    serialized = default_destinations_as_dicts()

    assert len(serialized) == 9
    assert all(destination["enabled"] is True for destination in serialized)
    assert all("latitude" in destination and "longitude" in destination for destination in serialized)

