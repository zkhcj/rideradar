"""Tests for RideRadar scoring."""

from custom_components.rideradar.models import DailyForecast, DestinationArea, RouteInfo
from custom_components.rideradar.scoring import (
    RIDE_QUALITY_WEIGHTS,
    TripPlanningProfile,
    calculate_best_trip_window,
    calculate_duration_preference_score,
    calculate_ride_experience,
    calculate_ride_score,
    calculate_trip_efficiency,
    calculate_trip_windows,
    calculate_variable_trip_windows,
    calculate_weather_stability_score,
)


def test_score_good_motorcycle_weather() -> None:
    forecast = DailyForecast(
        date="2026-06-02",
        temperature_c=22,
        precipitation_probability=5,
        precipitation_amount_mm=0,
        wind_speed_kmh=12,
        wind_gusts_kmh=20,
        cloud_cover=35,
        weather_code=1,
    )

    result = calculate_ride_score(forecast)

    assert result.score >= 95
    assert result.explanation in {"Good riding weather", "rain probability 5%"}


def test_score_penalizes_rain_wind_and_bad_weather_code() -> None:
    forecast = DailyForecast(
        date="2026-06-02",
        temperature_c=9,
        precipitation_probability=85,
        precipitation_amount_mm=6.5,
        wind_speed_kmh=38,
        wind_gusts_kmh=58,
        cloud_cover=95,
        weather_code=95,
    )

    result = calculate_ride_score(forecast)

    assert result.score < 20
    assert "rain probability" in result.explanation
    assert "gusts" in result.explanation


def test_best_trip_window_uses_complete_consecutive_days() -> None:
    forecasts = [
        DailyForecast("Friday", 22, 0, 0, 10, 15, 20, 1),
        DailyForecast("Saturday", 23, 0, 0, 12, 18, 25, 1),
        DailyForecast("Sunday", 21, 20, 0.3, 18, 25, 55, 3),
        DailyForecast("Monday", 15, 80, 9, 45, 70, 95, 95),
    ]

    best = calculate_best_trip_window(forecasts, 2)

    assert best is not None
    assert best.start_day == "Friday"
    assert best.duration_days == 2
    assert best.trip_score >= 90


def test_stability_prefers_consistently_good_weather() -> None:
    stable, _ = calculate_weather_stability_score([90, 88, 92])
    unstable, explanation = calculate_weather_stability_score([100, 100, 30])

    assert stable > unstable
    assert stable >= 85
    assert unstable < 65
    assert "Weather consistency is low" in explanation


def test_trip_score_applies_non_linear_bad_weather_penalty() -> None:
    forecasts = [
        DailyForecast("Friday", 24, 0, 0, 10, 15, 10, 1),
        DailyForecast("Saturday", 24, 0, 0, 10, 15, 10, 1),
        DailyForecast("Sunday", 17, 95, 12, 50, 75, 100, 95),
    ]

    best = calculate_best_trip_window(forecasts, 3)

    assert best is not None
    assert best.trip_score < 55
    assert best.trip_score_breakdown.bad_weather_penalty >= 30
    assert "because Sunday has" in best.trip_explanation


def test_different_trip_durations_change_window_selection() -> None:
    forecasts = [
        DailyForecast("Friday", 20, 0, 0, 10, 15, 20, 1),
        DailyForecast("Saturday", 21, 0, 0, 10, 15, 20, 1),
        DailyForecast("Sunday", 10, 90, 8, 40, 60, 95, 61),
    ]

    one_day = calculate_best_trip_window(forecasts, 1)
    two_days = calculate_best_trip_window(forecasts, 2)

    assert one_day is not None
    assert two_days is not None
    assert one_day.duration_days == 1
    assert two_days.duration_days == 2
    assert two_days.start_day == "Friday"


def test_variable_duration_scores_all_supported_windows() -> None:
    forecasts = [
        DailyForecast("2026-06-01", 20, 0, 0, 10, 15, 20, 1),
        DailyForecast("2026-06-02", 21, 0, 0, 10, 15, 20, 1),
        DailyForecast("2026-06-03", 10, 90, 8, 40, 60, 95, 61),
    ]

    windows = calculate_variable_trip_windows(forecasts, 1, 3)

    assert [window.duration_days for window in windows].count(1) == 3
    assert [window.duration_days for window in windows].count(2) == 2
    assert [window.duration_days for window in windows].count(3) == 1


def test_limited_forecast_data_has_no_complete_trip_window() -> None:
    forecasts = [DailyForecast("Friday", 22, 0, 0, 10, 15, 20, 1)]

    assert calculate_trip_windows(forecasts, 2) == []
    assert calculate_best_trip_window(forecasts, 2) is None


def test_ride_experience_penalizes_holiday_long_weekend_traffic() -> None:
    forecasts = [
        DailyForecast("2026-05-14", 22, 0, 0, 10, 15, 20, 1),
        DailyForecast("2026-05-15", 22, 0, 0, 10, 15, 20, 1),
    ]
    window = calculate_best_trip_window(forecasts, 2)

    assert window is not None
    experience = calculate_ride_experience(
        DestinationArea("Sauerland", "Duitsland, Noordrijn-Westfalen", 51.18, 8.25),
        RouteInfo(190, 150, "test"),
        window,
        forecasts,
    )

    assert experience.ride_quality_score < window.trip_score
    assert experience.holiday_pressure_score < 60
    assert experience.traffic_score < 80
    assert "Ascension Day" in experience.holiday_names
    assert "Vakantiedruk" in experience.explanation


def test_ride_experience_penalizes_weekend_motorcycle_restriction_risk() -> None:
    forecasts = [
        DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1),
        DailyForecast("2026-06-07", 22, 0, 0, 10, 15, 20, 1),
    ]
    window = calculate_best_trip_window(forecasts, 2)

    assert window is not None
    experience = calculate_ride_experience(
        DestinationArea("Eifel", "Duitsland / Belgie", 50.45, 6.55),
        RouteInfo(220, 170, "test"),
        window,
        forecasts,
    )

    assert experience.access_score < 80
    assert experience.motorcycle_access_score == experience.access_score
    assert experience.tourism_pressure_score < 80
    assert experience.access_notes


def test_trip_efficiency_penalizes_far_day_trips_more_than_multi_day_trips() -> None:
    day_window = calculate_best_trip_window([DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1)], 1)
    multi_day_window = calculate_best_trip_window(
        [
            DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-07", 22, 0, 0, 10, 15, 20, 1),
            DailyForecast("2026-06-08", 22, 0, 0, 10, 15, 20, 1),
        ],
        3,
    )

    assert day_window is not None
    assert multi_day_window is not None
    route = RouteInfo(420, 180, "test")

    day_efficiency = calculate_trip_efficiency(route, day_window, TripPlanningProfile())
    multi_day_efficiency = calculate_trip_efficiency(route, multi_day_window, TripPlanningProfile())

    assert day_efficiency["trip_efficiency_score"] < multi_day_efficiency["trip_efficiency_score"]
    assert day_efficiency["destination_ride_time_ratio"] < 0.30
    assert multi_day_efficiency["destination_ride_time_ratio"] >= 0.45


def test_trailer_strategy_requires_enabled_and_available_trailer() -> None:
    window = calculate_best_trip_window([DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1)], 1)

    assert window is not None
    efficiency = calculate_trip_efficiency(
        RouteInfo(150, 90, "test"),
        window,
        TripPlanningProfile(travel_strategy="trailer", trailer_support_enabled=True, trailer_available=False),
    )

    assert efficiency["trip_efficiency_score"] <= 30
    assert "trailer is not available" in efficiency["exclusion_reasons"][0]


def test_zero_weather_score_caps_ride_quality() -> None:
    forecasts = [
        DailyForecast("2026-06-06", 2, 100, 20, 70, 95, 100, 95),
    ]
    window = calculate_best_trip_window(forecasts, 1)

    assert window is not None
    experience = calculate_ride_experience(
        DestinationArea("Sauerland", "Duitsland", 51.18, 8.25),
        RouteInfo(180, 90, "test"),
        window,
        forecasts,
    )

    assert experience.weather_score == 0
    assert experience.ride_quality_score <= 50
    assert {"reason": "weather_score_zero", "cap": 50} in experience.score_caps
    assert experience.score_weights["weather_score"] == 40
    assert experience.recommendation_type == "least_bad_option"


def test_poor_weather_score_caps_ride_quality_at_60() -> None:
    forecasts = [
        DailyForecast("2026-06-06", 14, 30, 1.5, 35, 40, 80, 61),
    ]
    window = calculate_best_trip_window(forecasts, 1)

    assert window is not None
    experience = calculate_ride_experience(
        DestinationArea("Sauerland", "Duitsland", 51.18, 8.25),
        RouteInfo(120, 75, "test"),
        window,
        forecasts,
    )

    assert 0 < experience.weather_score < 25
    assert experience.ride_quality_score <= 60
    assert {"reason": "weather_score_below_25", "cap": 60} in experience.score_caps


def test_ride_quality_weights_sum_to_100() -> None:
    assert sum(RIDE_QUALITY_WEIGHTS.values()) == 100
    assert RIDE_QUALITY_WEIGHTS["weather_score"] == 40
    assert RIDE_QUALITY_WEIGHTS["duration_preference_score"] == 3


def test_duration_preference_score_curve_is_soft() -> None:
    assert calculate_duration_preference_score(3, 3) == 100
    assert calculate_duration_preference_score(2, 3) == 85
    assert calculate_duration_preference_score(4, 2) == 65
    assert calculate_duration_preference_score(6, 2) == 35


def test_preferred_duration_affects_ride_quality_without_excluding() -> None:
    forecasts = [
        DailyForecast("2026-06-06", 22, 0, 0, 10, 15, 20, 1),
        DailyForecast("2026-06-07", 22, 0, 0, 10, 15, 20, 1),
        DailyForecast("2026-06-08", 22, 0, 0, 10, 15, 20, 1),
    ]
    two_day = calculate_best_trip_window(forecasts[:2], 2)
    three_day = calculate_best_trip_window(forecasts, 3)

    assert two_day is not None
    assert three_day is not None
    destination = DestinationArea("Sauerland", "Duitsland", 51.18, 8.25)
    route = RouteInfo(180, 120, "test")
    profile = TripPlanningProfile(preferred_duration_days=3)

    two_day_experience = calculate_ride_experience(destination, route, two_day, forecasts[:2], profile)
    three_day_experience = calculate_ride_experience(destination, route, three_day, forecasts, profile)

    assert two_day_experience.duration_preference_score == 85
    assert three_day_experience.duration_preference_score == 100
    assert not two_day_experience.exclusion_reasons
    assert three_day_experience.ride_quality_score >= two_day_experience.ride_quality_score
