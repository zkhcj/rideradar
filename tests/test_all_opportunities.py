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
    CONF_TRAVEL_MODES,
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


def _entry(trailer_support_enabled=False, destinations=None, options=None):
    data = {
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
    }
    if options and CONF_TRAVEL_MODES in options:
        data[CONF_TRAVEL_MODES] = options[CONF_TRAVEL_MODES]
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options=options or {},
    )


def _entry_with_modes(travel_modes, destinations=None):
    return _entry(destinations=destinations, options={CONF_TRAVEL_MODES: travel_modes})


def _travel_modes(*, direct=True, scenic=True, trailer=False, direct_normal=3.0, direct_joker=3.5):
    return {
        "motorcycle_direct": {
            "enabled": direct,
            "normal_max_approach_time_hours": direct_normal,
            "joker_max_approach_time_hours": direct_joker,
        },
        "motorcycle_scenic": {
            "enabled": scenic,
            "normal_max_approach_time_hours": 2.5,
            "joker_max_approach_time_hours": 3.0,
        },
        "trailer": {
            "enabled": trailer,
            "normal_max_approach_time_hours": 4.0,
            "joker_max_approach_time_hours": 5.0,
        },
    }


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


async def test_all_opportunities_include_trailer_when_mode_enabled_even_if_legacy_switch_off(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass, _entry_with_modes(_travel_modes(trailer=True)), FakeApiClient(), FakeRoutingClient()
    )
    coordinator.set_runtime_control("trailer_available", "off")

    data = await coordinator._async_update_data()

    assert "trailer" in {item["strategy"] for item in data["all_opportunities"]}


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


async def test_strategy_trailer_sensors_are_created_for_empty_reason_visibility(hass) -> None:
    disabled_entry = _entry(trailer_support_enabled=False)
    disabled_coordinator = RideRadarDataCoordinator(hass, disabled_entry, FakeApiClient(), FakeRoutingClient())
    disabled_coordinator.data = await disabled_coordinator._async_update_data()
    hass.data[DOMAIN] = {disabled_entry.entry_id: disabled_coordinator}
    disabled_entities = []

    await async_setup_sensor(hass, disabled_entry, disabled_entities.extend)

    assert any(entity.unique_id.endswith("_top_week_trailer_opportunities") for entity in disabled_entities)
    trailer_sensor = next(
        entity for entity in disabled_entities if entity.unique_id.endswith("_top_week_trailer_opportunities")
    )
    assert trailer_sensor.extra_state_attributes["empty_reason"] == "Aanhangertransport staat uit"
    assert trailer_sensor.extra_state_attributes["candidate_count"] == 0

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
    assert all(
        row["result"] in {"recommended", "eligible", "joker", "compromise", "rejected", "unavailable"}
        for row in rows
    )


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


async def test_disabled_modes_generate_no_candidates_or_rejections(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_modes(_travel_modes(direct=True, scenic=False, trailer=False)),
        FakeApiClient(),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()
    rows = data["evaluated_candidates"]
    assert {row["mode"] for row in rows} == {"motorcycle_direct"}
    assert data["mode_status"]["motorcycle_scenic"]["enabled"] is False
    assert data["mode_status"]["trailer"]["enabled"] is False
    assert data["evaluation_summary"]["travel_mode_summary"]["motorcycle_scenic"]["rejected"] == 0
    assert data["evaluation_summary"]["travel_mode_summary"]["trailer"]["rejected"] == 0


async def test_candidate_within_normal_limit_exposes_mode_limits(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_modes(_travel_modes(direct=True, scenic=False, trailer=False, direct_normal=1.0, direct_joker=1.5)),
        FakeApiClient(),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()
    row = data["evaluated_candidates"][0]

    assert row["mode"] == "motorcycle_direct"
    assert row["approach_time_classification"] == "within_normal_limit"
    assert row["approach_time"]["normal_max"] == "1 uur"
    assert row["approach_time"]["joker_max"] == "1 uur en 30 minuten"
    assert row["normal_limit_overrun_minutes"] == 0


async def test_exceptional_candidate_between_normal_and_joker_becomes_joker(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_modes(
            _travel_modes(direct=True, scenic=False, trailer=False, direct_normal=0.5, direct_joker=1.0)
        ),
        FakeApiClient(),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()
    rows = data["evaluated_candidates"]
    joker = next(row for row in rows if row["result"] == "joker")

    assert joker["approach_time_classification"] == "within_joker_limit"
    assert joker["normal_limit_overrun_minutes"] == 15
    assert data["top_week_direct_opportunities"]["opportunities"] == []
    assert data["joker_opportunities"]


async def test_weak_candidate_between_normal_and_joker_is_compromise_not_joker(hass) -> None:
    class PoorApiClient:
        async def get_daily_forecast(self, latitude, longitude, forecast_days):
            return [
                DailyForecast("2026-06-04", 10, 90, 4, 35, 45, 70, 61),
                DailyForecast("2026-06-05", 10, 90, 4, 35, 45, 70, 61),
                DailyForecast("2026-06-06", 10, 90, 4, 35, 45, 70, 61),
                DailyForecast("2026-06-07", 10, 90, 4, 35, 45, 70, 61),
            ][:forecast_days]

    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_modes(
            _travel_modes(direct=True, scenic=False, trailer=False, direct_normal=0.5, direct_joker=1.0)
        ),
        PoorApiClient(),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()
    rows = data["evaluated_candidates"]

    assert any(row["approach_time_classification"] == "within_joker_limit" for row in rows)
    assert not any(row["result"] == "joker" for row in rows)
    assert any(row["result"] == "compromise" for row in rows)


async def test_candidate_beyond_joker_limit_is_rejected_with_evidence(hass) -> None:
    class LongRoutingClient:
        async def get_route(self, start_latitude, start_longitude, destination, activity_profile):
            return RouteInfo(160, 90, "fake")

    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_modes(
            _travel_modes(direct=True, scenic=False, trailer=False, direct_normal=0.25, direct_joker=0.5)
        ),
        FakeApiClient(),
        LongRoutingClient(),
    )

    data = await coordinator._async_update_data()
    rejected = [
        row
        for row in data["evaluated_candidates"]
        if row["result"] == "rejected" and row.get("primary_reason_code") == "joker_approach_time_exceeded"
        and row.get("approach_time_classification") == "joker_limit_exceeded"
    ]

    assert rejected
    assert all(row["approach_time_classification"] == "joker_limit_exceeded" for row in rejected)
    assert all(row["primary_reason_code"] == "joker_approach_time_exceeded" for row in rejected)
    evidence = " ".join(" ".join(row["evidence"]) for row in rejected)
    assert "Jokerlimiet:" in evidence
    assert "Overschrijding jokerlimiet:" in evidence


async def test_same_destination_can_classify_differently_by_travel_mode(hass) -> None:
    class FallbackRoutingClient:
        async def get_route(self, start_latitude, start_longitude, destination, activity_profile):
            return RouteInfo(
                distance_km=250,
                travel_time_minutes=180,
                provider="fallback",
                direct_distance_km=200,
                confidence="low",
                distance_method="haversine_detour",
                time_method="average_speed_estimate",
                detour_factor=1.0,
                assumed_average_speed_kmh=70,
            )

    modes = _travel_modes(direct=True, scenic=True, trailer=True, direct_normal=3.0, direct_joker=3.5)
    modes["motorcycle_scenic"]["normal_max_approach_time_hours"] = 2.5
    modes["motorcycle_scenic"]["joker_max_approach_time_hours"] = 3.0
    modes["trailer"]["normal_max_approach_time_hours"] = 4.0
    modes["trailer"]["joker_max_approach_time_hours"] = 5.0
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_modes(modes),
        FakeApiClient(),
        FallbackRoutingClient(),
    )

    data = await coordinator._async_update_data()
    classifications = {
        row["mode"]: row["approach_time_classification"]
        for row in data["evaluated_candidates"]
        if row["duration_days"] == 2
    }

    assert classifications["motorcycle_direct"] == "within_normal_limit"
    assert classifications["motorcycle_scenic"] in {"within_joker_limit", "joker_limit_exceeded"}
    assert classifications["trailer"] == "within_normal_limit"


async def test_sauerland_generates_trailer_candidate_when_trailer_mode_enabled(hass) -> None:
    destinations = [DestinationArea("Sauerland", "Germany", 51.0, 8.0).as_dict()]
    modes = _travel_modes(direct=True, scenic=True, trailer=True)
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_modes(modes, destinations=destinations),
        FakeApiClient(),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()
    trailer_candidates = [
        item
        for item in data["all_opportunities"]
        if item["destination"] == "Sauerland" and item["strategy"] == "trailer"
    ]

    assert trailer_candidates
    assert trailer_candidates[0]["approach_time_classification"] == "within_normal_limit"
    assert trailer_candidates[0]["normal_max_approach_time_hours"] == 4.0
    assert data["top_week_trailer_opportunities"]["candidate_count"] > 0
    assert data["top_week_trailer_opportunities"]["empty_reason"] is None
