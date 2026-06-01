"""Tests for RideRadar scoring."""

from custom_components.rideradar.models import DailyForecast, DestinationArea, RouteInfo
from custom_components.rideradar.scoring import (
    calculate_best_trip_window,
    calculate_ride_experience,
    calculate_ride_score,
    calculate_trip_windows,
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
    assert "Holiday pressure" in experience.explanation


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
