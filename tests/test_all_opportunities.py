"""Tests for RideRadar all-opportunities planning table."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar.const import (
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DETOUR_FACTOR,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_ADDRESS,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    CONF_TRAILER_SUPPORT_ENABLED,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_DETOUR_FACTOR,
    DOMAIN,
)
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.models import DailyForecast, DestinationArea, RouteInfo
from custom_components.rideradar.sensor import async_setup_entry as async_setup_sensor


class FakeApiClient:
    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        return [
            DailyForecast("2026-06-04", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-05", 23, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-06", 24, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-07", 22, 0, 0, 10, 15, 20, 1),
        ][:forecast_days]


class FakeRoutingClient:
    async def get_route(self, start_latitude, start_longitude, destination, activity_profile):
        return RouteInfo(80, 45, "fake")


def _entry(trailer_support_enabled=False, destinations=None):
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_START_ADDRESS: "Private start",
            CONF_START_LATITUDE: 50.0,
            CONF_START_LONGITUDE: 4.0,
            CONF_MAX_ROUTE_DISTANCE_KM: 500,
            CONF_FORECAST_DAYS: 4,
            CONF_PREFERRED_TRIP_DURATION: "2",
            CONF_CUSTOM_TRIP_DURATION_DAYS: 4,
            CONF_ACTIVITY_PROFILE: DEFAULT_ACTIVITY_PROFILE,
            CONF_DETOUR_FACTOR: DEFAULT_DETOUR_FACTOR,
            "custom_destinations": destinations or [DestinationArea("Sauerland", "Germany", 51.0, 8.0).as_dict()],
            "enabled_default_destinations": [],
            CONF_TRAILER_SUPPORT_ENABLED: trailer_support_enabled,
        },
    )


async def test_all_opportunities_include_multiple_durations_and_strategies(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration_days", "4")

    data = await coordinator._async_update_data()
    opportunities = data["all_opportunities"]

    assert {item["duration_days"] for item in opportunities} == {2, 3, 4}
    assert {item["strategy"] for item in opportunities} == {"motorcycle_direct", "motorcycle_scenic"}
    assert {item["strategy_label"] for item in opportunities} == {"Direct / snelweg", "Binnendoor / scenic"}
    assert all("duration_preference_score" in item for item in opportunities)


async def test_all_opportunities_fields_are_sortable_and_scores_are_consistent(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())

    data = await coordinator._async_update_data()
    item = data["all_opportunities"][0]

    for field in ("score", "duration_days", "destination", "strategy", "start_date"):
        assert field in item
    for field in ("routing_provider", "routing_confidence", "routing_summary"):
        assert field in item
    assert item["score"] == item["ride_quality_score"]
    assert item["distance_km"] == item["route_distance_km"]
    assert item["main_reason"]
    assert item["main_tradeoff"]
    assert item["verdict"] in {
        "Excellent",
        "Excellent weekend",
        "Very good",
        "Good",
        "Mediocre",
        "Poor",
        "Not recommended",
    }


async def test_all_opportunities_hide_trailer_when_support_is_disabled(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass, _entry(trailer_support_enabled=False), FakeApiClient(), FakeRoutingClient()
    )
    coordinator.set_runtime_control("trailer_available", "on")

    data = await coordinator._async_update_data()

    assert "trailer" not in {item["strategy"] for item in data["all_opportunities"]}


async def test_all_opportunities_include_trailer_only_when_available(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass, _entry(trailer_support_enabled=True), FakeApiClient(), FakeRoutingClient()
    )
    coordinator.set_runtime_control("trailer_available", "off")

    unavailable = await coordinator._async_update_data()
    assert "trailer" not in {item["strategy"] for item in unavailable["all_opportunities"]}

    coordinator.set_runtime_control("trailer_available", "on")
    available = await coordinator._async_update_data()
    assert "trailer" in {item["strategy"] for item in available["all_opportunities"]}


async def test_all_opportunities_attribute_size_is_limited(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())

    data = await coordinator._async_update_data()

    assert len(data["all_opportunities"]) <= data["all_opportunities_attribute_limit"]
    assert data["all_opportunities_candidate_count"] >= len(data["all_opportunities"])


async def test_all_opportunities_sensor_exists(hass) -> None:
    entry = _entry()
    coordinator = RideRadarDataCoordinator(hass, entry, FakeApiClient(), FakeRoutingClient())
    coordinator.data = await coordinator._async_update_data()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    entities = []

    await async_setup_sensor(hass, entry, entities.extend)

    sensor = next(entity for entity in entities if entity.unique_id.endswith("_all_opportunities"))
    assert sensor.native_value == len(coordinator.data["all_opportunities"])
    assert sensor.extra_state_attributes["opportunities"] == coordinator.data["all_opportunities"]


async def test_strategy_top_opportunity_groups_use_shared_payload(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration_days", "4")

    data = await coordinator._async_update_data()
    direct = data["top_week_direct_opportunities"]
    scenic = data["top_forecast_scenic_opportunities"]

    assert direct["opportunities"]
    assert scenic["opportunities"]
    assert all(item["strategy"] == "motorcycle_direct" for item in direct["opportunities"])
    assert all(item["strategy"] == "motorcycle_scenic" for item in scenic["opportunities"])
    assert all(item["ride_quality_score"] >= 70 for item in direct["opportunities"])
    for field in (
        "destination",
        "ride_quality_score",
        "period",
        "duration_days",
        "strategy",
        "strategy_label",
        "weather_score",
        "stability_score",
        "trip_efficiency_score",
        "distance_score",
        "main_reason",
        "main_tradeoff",
    ):
        assert field in direct["opportunities"][0]


async def test_strategy_week_window_uses_coming_8_days(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())

    data = await coordinator._async_update_data()

    assert data["top_week_direct_opportunities"]["candidate_count"] == data[
        "top_forecast_direct_opportunities"
    ]["candidate_count"]


async def test_strategy_top_rejected_candidate_when_no_70_plus(hass) -> None:
    class PoorApiClient:
        async def get_daily_forecast(self, latitude, longitude, forecast_days):
            return [
                DailyForecast("2026-06-04", 8, 100, 12, 55, 75, 95, 95),
                DailyForecast("2026-06-05", 8, 100, 12, 55, 75, 95, 95),
                DailyForecast("2026-06-06", 8, 100, 12, 55, 75, 95, 95),
                DailyForecast("2026-06-07", 8, 100, 12, 55, 75, 95, 95),
            ][:forecast_days]

    coordinator = RideRadarDataCoordinator(hass, _entry(), PoorApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration_days", "4")

    data = await coordinator._async_update_data()
    group = data["top_week_direct_opportunities"]

    assert group["opportunities"] == []
    assert group["best_rejected_candidate"] is not None
    assert group["best_rejected_candidate"]["ride_quality_score"] < 70


async def test_strategy_trailer_sensors_only_created_when_enabled(hass) -> None:
    disabled_entry = _entry(trailer_support_enabled=False)
    disabled_coordinator = RideRadarDataCoordinator(hass, disabled_entry, FakeApiClient(), FakeRoutingClient())
    disabled_coordinator.data = await disabled_coordinator._async_update_data()
    hass.data[DOMAIN] = {disabled_entry.entry_id: disabled_coordinator}
    disabled_entities = []

    await async_setup_sensor(hass, disabled_entry, disabled_entities.extend)

    assert not any(entity.unique_id.endswith("_top_week_trailer_opportunities") for entity in disabled_entities)

    enabled_entry = _entry(trailer_support_enabled=True)
    enabled_coordinator = RideRadarDataCoordinator(hass, enabled_entry, FakeApiClient(), FakeRoutingClient())
    enabled_coordinator.data = await enabled_coordinator._async_update_data()
    hass.data[DOMAIN] = {enabled_entry.entry_id: enabled_coordinator}
    enabled_entities = []

    await async_setup_sensor(hass, enabled_entry, enabled_entities.extend)

    assert any(entity.unique_id.endswith("_top_week_trailer_opportunities") for entity in enabled_entities)


async def test_evaluation_summary_matches_candidate_rows(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(), FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration_days", "4")

    data = await coordinator._async_update_data()
    rows = data["evaluated_candidates"]
    summary = data["evaluation_summary"]

    assert rows
    assert summary["total_candidates"] == len(rows)
    assert summary["rejected"] == len([row for row in rows if row["result"] == "rejected"])
    assert summary["unavailable"] == len([row for row in rows if row["result"] == "unavailable"])
    assert summary["recommended"] == 1
    assert all(row["result"] in {"recommended", "eligible", "compromise", "rejected", "unavailable"} for row in rows)


async def test_rejected_and_unavailable_candidates_have_reason_and_evidence(hass) -> None:
    class FailingApiClient:
        async def get_daily_forecast(self, latitude, longitude, forecast_days):
            raise ValueError("provider down")

    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FailingApiClient(),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()
    rows = data["evaluated_candidates"]
    blocked = [row for row in rows if row["result"] in {"rejected", "unavailable"}]

    assert blocked
    assert all(row["primary_reason"] for row in blocked)
    assert all(row["evidence"] for row in blocked)
    assert all(row["supporting_evidence"] for row in blocked)


async def test_eligible_candidates_are_not_rejected_when_ranked_below_best(hass) -> None:
    destinations = [
        DestinationArea("Sauerland", "Germany", 51.0, 8.0).as_dict(),
        DestinationArea("Eifel", "Germany", 50.4, 6.8).as_dict(),
    ]
    entry = _entry(destinations=destinations)
    coordinator = RideRadarDataCoordinator(hass, entry, FakeApiClient(), FakeRoutingClient())
    coordinator.set_runtime_control("trip_duration_days", "4")

    data = await coordinator._async_update_data()
    rows = data["evaluated_candidates"]

    assert any(row["result"] == "recommended" for row in rows)
    assert any(row["result"] == "eligible" for row in rows)
    assert not any(row["result"] == "rejected" and (row["total_score"] or 0) >= 70 for row in rows)
