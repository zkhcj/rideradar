"""Ride weather scoring logic."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev

from .const import DEFAULT_ACTIVITY_PROFILE
from .models import DailyForecast, RideScore, TripScoreBreakdown, TripWindow

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


def calculate_weather_stability_score(scores: list[int]) -> tuple[int, str]:
    """Score whether all days in a trip window stay consistently usable."""
    if not scores:
        return 0, "No complete forecast window is available."
    if len(scores) == 1:
        score = scores[0]
        if score >= 80:
            return 100, "Single-day trip; no multi-day weather variation."
        return max(0, min(100, score)), "Single-day trip stability follows the daily score."

    score_average = mean(scores)
    standard_deviation = pstdev(scores)
    worst_score = min(scores)
    spread = max(scores) - worst_score
    stability = 100 - (standard_deviation * 2.2) - (spread * 0.45)
    if worst_score < 70:
        stability -= (70 - worst_score) * 0.9
    if worst_score < 50:
        stability -= (50 - worst_score) * 1.2
    final_score = max(0, min(100, round(stability)))

    if final_score >= 85:
        explanation = "Weather consistency is high across the trip."
    elif final_score >= 65:
        explanation = "Weather is mostly consistent, with some variation between days."
    else:
        explanation = (
            "Weather consistency is low because at least one trip day is much weaker "
            f"than the {score_average:.0f}/100 average."
        )
    return final_score, explanation


def calculate_trip_windows(
    forecasts: list[DailyForecast],
    trip_duration: int,
    activity_profile: str = DEFAULT_ACTIVITY_PROFILE,
) -> list[TripWindow]:
    """Evaluate every complete consecutive forecast window for a trip duration."""
    if trip_duration < 1 or len(forecasts) < trip_duration:
        return []

    daily_results = {forecast.date: calculate_ride_score(forecast, activity_profile) for forecast in forecasts}
    windows: list[TripWindow] = []
    for start_index in range(0, len(forecasts) - trip_duration + 1):
        window_forecasts = forecasts[start_index : start_index + trip_duration]
        window_scores = [daily_results[forecast.date].score for forecast in window_forecasts]
        stability_score, stability_explanation = calculate_weather_stability_score(window_scores)
        average_score = mean(window_scores)
        worst_score = min(window_scores)
        bad_weather_penalty = _bad_weather_penalty(window_scores, window_forecasts)
        trip_score = max(0, min(100, round((average_score * 0.85) + (stability_score * 0.15) - bad_weather_penalty)))
        daily_scores = {forecast.date: daily_results[forecast.date].score for forecast in window_forecasts}
        breakdown = TripScoreBreakdown(
            average_daily_score=round(average_score),
            worst_daily_score=worst_score,
            weather_stability_score=stability_score,
            bad_weather_penalty=round(bad_weather_penalty),
            duration_days=trip_duration,
        )
        windows.append(
            TripWindow(
                start_day=window_forecasts[0].date,
                end_day=window_forecasts[-1].date,
                duration_days=trip_duration,
                trip_score=trip_score,
                daily_scores=daily_scores,
                weather_stability_score=stability_score,
                stability_explanation=stability_explanation,
                trip_score_breakdown=breakdown,
                trip_explanation=_trip_explanation(
                    window_forecasts,
                    window_scores,
                    trip_score,
                    stability_score,
                    bad_weather_penalty,
                ),
            )
        )
    return windows


def calculate_best_trip_window(
    forecasts: list[DailyForecast],
    trip_duration: int,
    activity_profile: str = DEFAULT_ACTIVITY_PROFILE,
) -> TripWindow | None:
    """Return the best complete consecutive trip window."""
    return max(
        calculate_trip_windows(forecasts, trip_duration, activity_profile),
        key=lambda window: window.trip_score,
        default=None,
    )


def _bad_weather_penalty(scores: list[int], forecasts: list[DailyForecast]) -> float:
    """Apply non-linear trip penalties so one bad day hurts the full trip."""
    penalty = 0.0
    for score in scores:
        if score < 70:
            penalty += ((70 - score) ** 1.25) / 5
        if score < 50:
            penalty += (50 - score) * 0.9
        if score < 30:
            penalty += (30 - score) * 1.4

    for forecast in forecasts:
        precipitation_probability = forecast.precipitation_probability or 0
        precipitation_amount = forecast.precipitation_amount_mm or 0
        wind_speed = forecast.wind_speed_kmh or 0
        wind_gusts = forecast.wind_gusts_kmh or 0
        if precipitation_probability >= 80 or precipitation_amount >= 8:
            penalty += 10
        elif precipitation_probability >= 60 or precipitation_amount >= 4:
            penalty += 5
        if wind_speed >= 45 or wind_gusts >= 65:
            penalty += 10
        elif wind_speed >= 35 or wind_gusts >= 55:
            penalty += 5
        if forecast.weather_code in {95, 96, 99}:
            penalty += 18
    return min(75.0, penalty)


def _trip_explanation(
    forecasts: list[DailyForecast],
    scores: list[int],
    trip_score: int,
    stability_score: int,
    bad_weather_penalty: float,
) -> str:
    destination_days = f"{len(forecasts)}-day trip starting {forecasts[0].date}"
    worst_index = scores.index(min(scores))
    worst_forecast = forecasts[worst_index]
    worst_score = scores[worst_index]
    temperature_values = [forecast.temperature_c for forecast in forecasts if forecast.temperature_c is not None]
    dry_days = [
        forecast
        for forecast in forecasts
        if (forecast.precipitation_probability or 0) <= 20 and (forecast.precipitation_amount_mm or 0) <= 0.5
    ]
    wind_values = [forecast.wind_speed_kmh for forecast in forecasts if forecast.wind_speed_kmh is not None]

    if bad_weather_penalty >= 20 or worst_score < 55:
        weather_reason = _bad_weather_reason(worst_forecast)
        return (
            f"Scores {trip_score}/100 for a {destination_days} despite stronger individual days because "
            f"{worst_forecast.date} has {weather_reason}. Weather consistency is {stability_score}/100."
        )

    parts = [f"Scores {trip_score}/100 for a {destination_days}."]
    if len(dry_days) == len(forecasts):
        parts.append("All trip days are expected to remain mostly dry.")
    if temperature_values:
        parts.append(
            f"Temperatures stay between {min(temperature_values):.0f} C and {max(temperature_values):.0f} C."
        )
    if wind_values and max(wind_values) <= 25:
        parts.append("Winds remain light.")
    elif wind_values:
        parts.append(f"Peak wind is around {max(wind_values):.0f} km/h.")
    if stability_score >= 85:
        parts.append("Weather consistency is high.")
    elif stability_score < 65:
        parts.append("Weather consistency is uneven.")
    return " ".join(parts)


def _bad_weather_reason(forecast: DailyForecast) -> str:
    reasons: list[str] = []
    if (forecast.precipitation_probability or 0) >= 60:
        reasons.append(f"a {forecast.precipitation_probability:.0f}% chance of rain")
    if (forecast.precipitation_amount_mm or 0) >= 4:
        reasons.append(f"{forecast.precipitation_amount_mm:.1f} mm of rain")
    if (forecast.wind_speed_kmh or 0) >= 35:
        reasons.append(f"strong wind near {forecast.wind_speed_kmh:.0f} km/h")
    if (forecast.wind_gusts_kmh or 0) >= 55:
        reasons.append(f"gusts near {forecast.wind_gusts_kmh:.0f} km/h")
    if forecast.weather_code in {95, 96, 99}:
        reasons.append("storm risk")
    return ", ".join(reasons) if reasons else f"a weak daily score of {calculate_ride_score(forecast).score}/100"
