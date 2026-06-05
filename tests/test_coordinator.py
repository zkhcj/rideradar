"""Tests for RideRadar coordinator behavior."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar.api import RideRadarApiError
from custom_components.rideradar.const import (
    CONF_ABSOLUTE_MAX_APPROACH_TIME_HOURS,
    CONF_ACTIVITY_PROFILE,
    CONF_CUSTOM_TRIP_DURATION_DAYS,
    CONF_DESTINATIONS,
    CONF_DETOUR_FACTOR,
    CONF_FORECAST_DAYS,
    CONF_MAX_ROUTE_DISTANCE_KM,
    CONF_PREFERRED_TRIP_DURATION,
    CONF_START_ADDRESS,
    CONF_START_LATITUDE,
    CONF_START_LONGITUDE,
    DEFAULT_ACTIVITY_PROFILE,
    DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
    DEFAULT_DETOUR_FACTOR,
    DEFAULT_PREFERRED_TRIP_DURATION,
    DOMAIN,
)
from custom_components.rideradar.coordinator import RideRadarDataCoordinator
from custom_components.rideradar.models import DailyForecast, DestinationArea, RouteInfo
from custom_components.rideradar.routing import FallbackRoutingClient


class FakeApiClient:
    def __init__(self, forecasts=None, error=None) -> None:
        self.calls = 0
        self.forecasts = forecasts or [
            DailyForecast("2026-06-02", 22, 5, 0, 12, 20, 30, 1),
            DailyForecast("2026-06-03", 12, 60, 2, 25, 40, 90, 61),
        ]
        self.error = error

    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        self.calls += 1
        if self.error:
            raise self.error
        return self.forecasts[:forecast_days]


class FakeRoutingClient:
    def __init__(self, distance_km=100) -> None:
        self.distance_km = distance_km

    async def get_route(self, start_latitude, start_longitude, destination, activity_profile):
        return RouteInfo(self.distance_km, 90, f"fake_{activity_profile}")


class DestinationRoutingClient:
    def __init__(self, routes: dict[str, RouteInfo]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    async def get_route(self, start_latitude, start_longitude, destination, activity_profile):
        self.requests.append(destination.name)
        return self.routes[destination.name]


class DestinationForecastApiClient:
    async def get_daily_forecast(self, latitude, longitude, forecast_days):
        if latitude == 51.0:
            return [
                DailyForecast("Friday", 24, 0, 0, 10, 15, 10, 1),
                DailyForecast("Saturday", 12, 95, 10, 45, 70, 95, 95),
                DailyForecast("Sunday", 24, 0, 0, 10, 15, 10, 1),
            ][:forecast_days]
        return [
            DailyForecast("Friday", 22, 10, 0, 12, 18, 30, 2),
            DailyForecast("Saturday", 21, 10, 0, 12, 18, 30, 2),
            DailyForecast("Sunday", 20, 10, 0, 12, 18, 30, 2),
        ][:forecast_days]


def _entry(destinations=None, max_distance=300, forecast_days=2):
    destination_data = destinations
    if destination_data is None:
        destination_data = [
            DestinationArea("Test Destination", "Test Region", 51.0, 5.0).as_dict(),
        ]
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_START_ADDRESS: "Private start",
            CONF_START_LATITUDE: 50.0,
            CONF_START_LONGITUDE: 4.0,
            CONF_MAX_ROUTE_DISTANCE_KM: max_distance,
            CONF_FORECAST_DAYS: forecast_days,
            CONF_PREFERRED_TRIP_DURATION: DEFAULT_PREFERRED_TRIP_DURATION,
            CONF_CUSTOM_TRIP_DURATION_DAYS: DEFAULT_CUSTOM_TRIP_DURATION_DAYS,
            CONF_ACTIVITY_PROFILE: DEFAULT_ACTIVITY_PROFILE,
            CONF_DETOUR_FACTOR: DEFAULT_DETOUR_FACTOR,
            CONF_DESTINATIONS: destination_data,
        },
    )


def _entry_with_options(destinations=None, max_distance=300, forecast_days=2, options=None):
    entry = _entry(destinations=destinations, max_distance=max_distance, forecast_days=forecast_days)
    return MockConfigEntry(domain=entry.domain, data=entry.data, options=options or {})


def _forecast_day(day, score_weather=1):
    return DailyForecast(day, 22, 0, 0, 10, 15, 20, score_weather)


async def test_coordinator_selects_best_destination(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["destination_count"] == 1
    assert data["best"].destination.name == "Test Destination"
    assert data["best"].best_start_day == "2026-06-02"
    assert data["best"].trip_score is not None
    assert data["opportunities"]
    assert data["best_next_available_opportunity"]["destination"] == "Test Destination"
    assert "Test Destination" in data["summary"]


async def test_coordinator_ranks_destinations_by_trip_score(hass) -> None:
    destinations = [
        DestinationArea("Spiky Daily Scores", "Test Region", 51.0, 5.0).as_dict(),
        DestinationArea("Stable Trip", "Test Region", 52.0, 5.0).as_dict(),
    ]
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=destinations),
        DestinationForecastApiClient(),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["best"].destination.name == "Stable Trip"
    assert data["best"].trip_score > data["results"][0].trip_score


async def test_coordinator_exposes_availability_windows_across_forecast_horizon(hass) -> None:
    forecasts = [
        _forecast_day("2026-06-04"),
        _forecast_day("2026-06-05"),
        _forecast_day("2026-06-06"),
        _forecast_day("2026-06-07"),
    ]
    entry = _entry(forecast_days=4)
    coordinator = RideRadarDataCoordinator(
        hass,
        entry,
        FakeApiClient(forecasts=forecasts),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    result = data["results"][0]
    assert len(result.all_trip_windows) == 3
    assert len(data["opportunities"]) == 3
    assert data["opportunities"][0]["route_distance_km"] == 100
    assert data["opportunities"][0]["traffic_level"] in {"Low", "Medium", "High", "Severe"}
    assert data["opportunities"][0]["access_status"] in {"Open", "Partial", "Restricted", "Avoid"}
    assert data["opportunities"][0]["holiday_pressure_score"] is not None
    assert data["opportunities"][0]["days_until"] is not None
    assert data["best_weekend_opportunity"]["start_date"] in {"2026-06-05", "2026-06-06"}
    assert data["best_weekday_opportunity"]["start_date"] == "2026-06-04"
    assert " t/m " in data["opportunities"][0]["period"]
    assert data["opportunities"][0]["trip_efficiency_score"] is not None
    assert data["opportunities"][0]["score_breakdown"]["ride_quality_score"] == data["opportunities"][0][
        "ride_quality_score"
    ]
    trace = data["opportunities"][0]["decision_trace"]
    assert trace["inputs"]["destination"] == "Test Destination"
    assert trace["inputs"]["travel_strategy"] == data["travel_strategy"]
    assert trace["window"]["period"] == data["opportunities"][0]["period"]
    assert trace["scores"]["trip_efficiency_score"] == data["opportunities"][0]["trip_efficiency_score"]
    assert len(data["top_week_opportunities"]) == 3
    assert len(data["top_month_opportunities"]) == 3


async def test_coordinator_handles_empty_destination_list(hass) -> None:
    coordinator = RideRadarDataCoordinator(hass, _entry(destinations=[]), FakeApiClient(), FakeRoutingClient())

    data = await coordinator._async_update_data()

    assert data["destination_count"] == 0
    assert data["best"] is None
    assert data["summary"] == "No enabled destinations configured"


async def test_coordinator_uses_trip_duration_number_helper(hass) -> None:
    forecasts = [
        _forecast_day("2026-06-04"),
        _forecast_day("2026-06-05"),
        _forecast_day("2026-06-06"),
    ]
    hass.states.async_set("input_number.rideradar_trip_duration_days", "1")
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(forecast_days=3),
        FakeApiClient(forecasts=forecasts),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["trip_duration"] == 1
    assert data["trip_duration_source"] == "input_number.rideradar_trip_duration_days"
    assert len(data["results"][0].all_trip_windows) == 3


async def test_coordinator_uses_flexible_trip_duration_select(hass) -> None:
    forecasts = [
        _forecast_day("2026-06-04"),
        _forecast_day("2026-06-05"),
        _forecast_day("2026-06-06"),
    ]
    hass.states.async_set("input_select.rideradar_trip_duration", "flexible")
    hass.states.async_set("input_number.rideradar_trip_duration_days", "3")
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(forecast_days=3),
        FakeApiClient(forecasts=forecasts),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["duration_mode"] == "flexible"
    assert data["trip_duration_label"] == "1-3 days"
    assert data["min_duration_days"] == 1
    assert data["max_duration_days"] == 3
    assert data["best_duration_days"] in {1, 2, 3}
    assert {window.duration_days for window in data["results"][0].all_trip_windows} == {1, 2, 3}


async def test_coordinator_filters_windows_by_preferred_start_day_and_weekend_only(hass) -> None:
    forecasts = [
        _forecast_day("2026-06-04"),
        _forecast_day("2026-06-05"),
        _forecast_day("2026-06-06"),
        _forecast_day("2026-06-07"),
    ]
    hass.states.async_set("input_number.rideradar_trip_duration_days", "1")
    hass.states.async_set("input_boolean.rideradar_weekend_only", "on")
    hass.states.async_set("input_select.rideradar_preferred_start_day", "Saturday")
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(forecast_days=4),
        FakeApiClient(forecasts=forecasts),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["weekend_only"] is True
    assert data["preferred_start_weekday"] == 5
    assert [opportunity["start_date"] for opportunity in data["opportunities"]] == ["2026-06-06"]


async def test_coordinator_excludes_trailer_strategy_when_trailer_is_unavailable(hass) -> None:
    forecasts = [
        _forecast_day("2026-06-04"),
        _forecast_day("2026-06-05"),
    ]
    hass.states.async_set("input_select.rideradar_travel_strategy", "Trailer Transport")
    hass.states.async_set("input_boolean.rideradar_trailer_available", "off")
    entry = _entry(forecast_days=2)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"trailer_support_enabled": True})
    coordinator = RideRadarDataCoordinator(
        hass,
        entry,
        FakeApiClient(forecasts=forecasts),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["travel_strategy"] == "trailer"
    assert data["trailer_available"] is False
    assert data["best"] is None
    assert data["opportunities"] == []
    assert data["results"][0].ride_quality_score is None
    assert any(
        item["reason"] == "trailer_required_but_unavailable" for item in data["excluded_destinations"]
    )


async def test_coordinator_marks_unreachable_destination_without_fetching_weather(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(max_distance=50),
        FakeApiClient(),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    result = data["results"][0]
    assert result.reachable is False
    assert result.trip_score is None
    assert data["best"] is None
    assert any(item["reason"] == "too_far" for item in data["excluded_destinations"])


async def test_coordinator_does_not_rank_limited_forecast_as_complete_trip(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(forecasts=[DailyForecast("Friday", 22, 0, 0, 10, 15, 20, 1)]),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()

    assert data["best"] is None
    assert data["results"][0].trip_score is None


async def test_preferred_approach_time_does_not_reject_harz_like_destination(hass) -> None:
    destinations = [
        DestinationArea("Harz", "Duitsland", 51.8, 10.62).as_dict(),
    ]
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=destinations, max_distance=1350, forecast_days=3),
        FakeApiClient(
            forecasts=[
                _forecast_day("2026-06-04"),
                _forecast_day("2026-06-05"),
                _forecast_day("2026-06-06"),
            ]
        ),
        DestinationRoutingClient({"Harz": RouteInfo(365, 260, "test")}),
    )
    coordinator.set_runtime_control("trip_duration", "3 days")
    coordinator.set_runtime_control("max_approach_time_hours", "3.5")

    data = await coordinator._async_update_data()

    assert data["opportunities"]
    assert data["best"].destination.name == "Harz"
    assert data["opportunities"][0]["preferred_approach_time_overrun_hours"] > 0
    assert data["opportunities"][0]["absolute_max_approach_time_hours"] is None
    assert not any(item["reason"] == "approach_time_too_high" for item in data["excluded_destinations"])


async def test_explicit_absolute_approach_limit_rejects_candidate(hass) -> None:
    destinations = [DestinationArea("Harz", "Duitsland", 51.8, 10.62).as_dict()]
    api = FakeApiClient(
        forecasts=[
            _forecast_day("2026-06-04"),
            _forecast_day("2026-06-05"),
            _forecast_day("2026-06-06"),
        ]
    )
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry_with_options(
            destinations=destinations,
            max_distance=1350,
            forecast_days=3,
            options={CONF_ABSOLUTE_MAX_APPROACH_TIME_HOURS: 3.0},
        ),
        api,
        DestinationRoutingClient({"Harz": RouteInfo(365, 260, "test")}),
    )

    data = await coordinator._async_update_data()

    assert data["opportunities"] == []
    assert any(item["reason"] == "absolute_approach_time_exceeded" for item in data["excluded_destinations"])
    assert api.calls == 0
    assert data["weather"]["weather_fetch_summary"]["destinations_skipped_by_hard_constraint"] == 1


async def test_highest_eligible_candidate_becomes_recommended(hass) -> None:
    destinations = [DestinationArea("Sauerland", "Duitsland", 51.18, 8.25).as_dict()]
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=destinations, max_distance=1350, forecast_days=3),
        FakeApiClient(
            forecasts=[
                _forecast_day("2026-06-04"),
                _forecast_day("2026-06-05"),
                DailyForecast("2026-06-06", 12, 80, 6, 35, 55, 90, 61),
            ]
        ),
        FakeRoutingClient(distance_km=220),
    )
    coordinator.set_runtime_control("trip_duration", "3 days")

    data = await coordinator._async_update_data()
    recommended = [candidate for candidate in data["evaluated_candidates"] if candidate["result"] == "recommended"]

    assert recommended
    assert recommended[0]["destination"] == data["best"].destination.name
    assert data["evaluation_summary"]["recommended"] == 1


async def test_weather_score_zero_has_weather_evidence(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(forecast_days=2),
        FakeApiClient(
            forecasts=[
                DailyForecast("2026-06-04", 2, 100, 20, 70, 95, 100, 95),
                DailyForecast("2026-06-05", 2, 100, 20, 70, 95, 100, 95),
            ]
        ),
        FakeRoutingClient(distance_km=100),
    )

    data = await coordinator._async_update_data()
    candidate = data["evaluated_candidates"][0]

    assert candidate["weather_score"] == 0
    assert candidate["weather_evaluation"]["aggregate"]["total_precipitation_mm"] == 40
    assert candidate["weather_evaluation"]["penalties"]
    assert candidate["result"] == "compromise"


async def test_duration_summary_exposes_best_candidate_per_duration(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(forecast_days=4),
        FakeApiClient(
            forecasts=[
                _forecast_day("2026-06-04"),
                _forecast_day("2026-06-05"),
                _forecast_day("2026-06-06"),
                _forecast_day("2026-06-07"),
            ]
        ),
        FakeRoutingClient(distance_km=100),
    )
    coordinator.set_runtime_control("trip_duration", "3 days")

    data = await coordinator._async_update_data()
    duration_summary = data["evaluation_summary"]["duration_summary"]

    assert set(duration_summary) == {2, 3, 4}
    assert duration_summary[2]["candidate_count"] > 0
    assert duration_summary[3]["candidate_count"] > 0
    assert duration_summary[4]["candidate_count"] > 0
    assert duration_summary[3]["best_candidate"]["duration_days"] == 3


async def test_fallback_routing_metadata_is_exposed_for_vogezen(hass) -> None:
    destinations = [DestinationArea("Vogezen", "Frankrijk", 48.0, 7.0).as_dict()]
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(destinations=destinations, max_distance=1350, forecast_days=3),
        FakeApiClient(
            forecasts=[
                _forecast_day("2026-06-04"),
                _forecast_day("2026-06-05"),
                _forecast_day("2026-06-06"),
            ]
        ),
        FallbackRoutingClient(),
    )

    data = await coordinator._async_update_data()
    opportunity = data["opportunities"][0]

    assert opportunity["destination"] == "Vogezen"
    assert opportunity["routing_provider"] == "fallback"
    assert opportunity["routing_confidence"] == "low"
    assert opportunity["routing_distance_method"] == "haversine_detour"
    assert opportunity["routing_time_method"] == "average_speed_estimate"
    assert opportunity["direct_distance_km"] is not None
    assert opportunity["assumed_average_speed_kmh"] >= 70
    assert "fallbackschatting, geen echte route" in opportunity["routing_summary"]
    assert any("Aangenomen gemiddelde snelheid" in item for item in opportunity["routing_evidence"])


async def test_coordinator_marks_weather_unavailable_when_api_unavailable(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(error=RideRadarApiError("Open-Meteo down")),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()

    assert data["weather"]["weather_status"] == "unavailable"
    assert data["best"] is None
    assert any(item["reason"] == "no_forecast_data" for item in data["excluded_destinations"])


async def test_coordinator_provider_failure_status_is_provider_friendly(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(error=RideRadarApiError("Open-Meteo returned HTTP 502")),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()

    assert data["weather"]["weather_status"] == "unavailable"
    assert data["weather"]["providers"]["open_meteo"]["status"] == "unavailable"


async def test_coordinator_replaces_previous_data_with_limited_state_after_provider_failure(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(error=RideRadarApiError("Open-Meteo returned HTTP 502")),
        FakeRoutingClient(),
    )
    coordinator.data = {"summary": "previous valid data", "results": ["previous"]}

    await coordinator.async_refresh()

    assert coordinator.data["weather"]["weather_status"] == "unavailable"
    assert coordinator.data["summary"] == "Geen bereikbare bestemming met beschikbare weersverwachting."
    assert coordinator.last_update_success is True


async def test_coordinator_unavailable_data_is_dashboard_safe(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(error=RideRadarApiError("Open-Meteo returned HTTP 502")),
        FakeRoutingClient(),
    )

    data = coordinator.unavailable_data()

    assert data["forecast_status"] == "temporarily_unavailable"
    assert data["best_next_available_opportunity"] is None
    assert data["top_week_opportunities"] == []
    assert data["top_month_best_below_threshold"] is None
    assert "weerservice is tijdelijk niet beschikbaar" in data["summary"]


async def test_coordinator_handles_timeout_as_weather_unavailable(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(error=TimeoutError("timeout")),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()

    assert data["weather"]["weather_status"] == "unavailable"
    assert data["weather"]["providers"]["open_meteo"]["status"] == "timeout"


async def test_coordinator_handles_malformed_provider_data_as_weather_unavailable(hass) -> None:
    coordinator = RideRadarDataCoordinator(
        hass,
        _entry(),
        FakeApiClient(error=ValueError("malformed response")),
        FakeRoutingClient(),
    )

    data = await coordinator._async_update_data()

    assert data["weather"]["weather_status"] == "unavailable"
    assert data["weather"]["providers"]["open_meteo"]["status"] == "invalid_response"
