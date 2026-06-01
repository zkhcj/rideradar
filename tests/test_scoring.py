"""Tests for RideRadar scoring."""

from custom_components.rideradar.models import DailyForecast
from custom_components.rideradar.scoring import calculate_ride_score


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

