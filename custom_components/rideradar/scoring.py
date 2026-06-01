"""Ride weather scoring logic."""

from __future__ import annotations

from dataclasses import dataclass

from .const import DEFAULT_ACTIVITY_PROFILE
from .models import DailyForecast, RideScore

BAD_WEATHER_CODES = {
    51,
    53,
    55,
    56,
    57,
    61,
    63,
    65,
    66,
    67,
    71,
    73,
    75,
    77,
    80,
    81,
    82,
    85,
    86,
    95,
    96,
    99,
}


@dataclass(frozen=True, slots=True)
class ScoringProfile:
    """Activity-specific scoring thresholds."""

    ideal_min_temp_c: float
    comfortable_min_temp_c: float
    hot_temp_c: float
    wind_penalty_start_kmh: float
    gust_penalty_start_kmh: float


SCORING_PROFILES = {
    DEFAULT_ACTIVITY_PROFILE: ScoringProfile(
        ideal_min_temp_c=14,
        comfortable_min_temp_c=8,
        hot_temp_c=32,
        wind_penalty_start_kmh=20,
        gust_penalty_start_kmh=35,
    )
}


def calculate_ride_score(
    forecast: DailyForecast,
    activity_profile: str = DEFAULT_ACTIVITY_PROFILE,
) -> RideScore:
    """Calculate a 0-100 RideScore for activity-friendly outdoor weather."""
    profile = SCORING_PROFILES.get(activity_profile, SCORING_PROFILES[DEFAULT_ACTIVITY_PROFILE])
    score = 100.0
    reasons: list[str] = []

    precipitation_probability = forecast.precipitation_probability or 0
    if precipitation_probability:
        score -= min(35.0, precipitation_probability * 0.35)
        reasons.append(f"rain probability {precipitation_probability:.0f}%")

    precipitation_amount = forecast.precipitation_amount_mm or 0
    if precipitation_amount:
        score -= min(30.0, precipitation_amount * 10)
        reasons.append(f"rain amount {precipitation_amount:.1f} mm")

    wind_speed = forecast.wind_speed_kmh or 0
    if wind_speed > profile.wind_penalty_start_kmh:
        score -= min(20.0, (wind_speed - profile.wind_penalty_start_kmh) * 0.7)
        reasons.append(f"wind {wind_speed:.0f} km/h")

    wind_gusts = forecast.wind_gusts_kmh or 0
    if wind_gusts > profile.gust_penalty_start_kmh:
        score -= min(25.0, (wind_gusts - profile.gust_penalty_start_kmh) * 0.8)
        reasons.append(f"gusts {wind_gusts:.0f} km/h")

    if forecast.temperature_c is not None:
        temperature = forecast.temperature_c
        if temperature < profile.comfortable_min_temp_c:
            score -= min(30.0, (profile.comfortable_min_temp_c - temperature) * 4)
            reasons.append(f"cold {temperature:.0f} C")
        elif temperature < profile.ideal_min_temp_c:
            score -= (profile.ideal_min_temp_c - temperature) * 2
            reasons.append(f"cool {temperature:.0f} C")
        elif temperature > profile.hot_temp_c:
            score -= min(25.0, (temperature - profile.hot_temp_c) * 3)
            reasons.append(f"hot {temperature:.0f} C")

    cloud_cover = forecast.cloud_cover or 0
    if cloud_cover > 80:
        score -= 8
        reasons.append(f"cloud cover {cloud_cover:.0f}%")
    elif cloud_cover > 60:
        score -= 4
        reasons.append(f"cloud cover {cloud_cover:.0f}%")

    if forecast.weather_code in BAD_WEATHER_CODES:
        score -= 15
        reasons.append(f"weather code {forecast.weather_code}")

    final_score = max(0, min(100, round(score)))
    explanation = "Good riding weather" if not reasons else ", ".join(reasons)
    return RideScore(score=final_score, explanation=explanation)
