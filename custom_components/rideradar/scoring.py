"""Ride weather scoring logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev

from .const import DEFAULT_ACTIVITY_PROFILE
from .models import DailyForecast, DestinationArea, RideExperience, RideScore, RouteInfo, TripScoreBreakdown, TripWindow

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


@dataclass(frozen=True, slots=True)
class TripPlanningProfile:
    """Runtime planning assumptions used for trip practicality scoring."""

    travel_strategy: str = "motorcycle_direct"
    available_hours_per_day: float = 8.0
    max_approach_time_hours: float = 4.0
    trailer_support_enabled: bool = False
    trailer_available: bool = False


SCORING_PROFILES = {
    DEFAULT_ACTIVITY_PROFILE: ScoringProfile(
        ideal_min_temp_c=14,
        comfortable_min_temp_c=8,
        hot_temp_c=32,
        wind_penalty_start_kmh=20,
        gust_penalty_start_kmh=35,
    )
}

DESTINATION_TRAFFIC_PROFILES = {
    "sauerland": {"popularity": 18, "fun": 86, "access": 86, "countries": {"DE": 1.0, "NL": 0.55, "BE": 0.25}},
    "vogezen": {"popularity": 22, "fun": 92, "access": 82, "countries": {"FR": 1.0, "DE": 0.45, "NL": 0.35}},
    "dolomieten": {"popularity": 30, "fun": 96, "access": 76, "countries": {"DE": 0.35, "FR": 0.2}},
    "harz": {"popularity": 20, "fun": 88, "access": 82, "countries": {"DE": 1.0, "NL": 0.35}},
    "moezel": {"popularity": 24, "fun": 84, "access": 84, "countries": {"DE": 0.8, "LU": 0.65, "FR": 0.35, "NL": 0.35}},
    "eifel": {"popularity": 26, "fun": 91, "access": 76, "countries": {"DE": 0.8, "BE": 0.65, "NL": 0.45}},
    "klein zwitserland": {"popularity": 18, "fun": 88, "access": 88, "countries": {"LU": 1.0, "DE": 0.45, "BE": 0.35}},
    "zwarte woud": {"popularity": 28, "fun": 94, "access": 72, "countries": {"DE": 1.0, "FR": 0.45, "NL": 0.25}},
    "teutoburgerwoud": {"popularity": 14, "fun": 78, "access": 90, "countries": {"DE": 1.0, "NL": 0.4}},
}

RIDE_QUALITY_WEIGHTS = {
    "weather_score": 40,
    "stability_score": 20,
    "temperature_score": 10,
    "distance_score": 10,
    "holiday_pressure_score": 10,
    "access_score": 5,
    "trip_efficiency_score": 5,
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


def calculate_variable_trip_windows(
    forecasts: list[DailyForecast],
    min_duration: int,
    max_duration: int,
    activity_profile: str = DEFAULT_ACTIVITY_PROFILE,
) -> list[TripWindow]:
    """Evaluate complete windows for every duration in the requested range."""
    if max_duration < min_duration:
        return []
    windows: list[TripWindow] = []
    for duration in range(min_duration, max_duration + 1):
        windows.extend(calculate_trip_windows(forecasts, duration, activity_profile))
    return sorted(
        windows,
        key=lambda window: (window.start_day, window.duration_days),
    )


def calculate_ride_experience(
    destination: DestinationArea,
    route: RouteInfo,
    window: TripWindow,
    forecasts: list[DailyForecast],
    planning_profile: TripPlanningProfile | None = None,
) -> RideExperience:
    """Calculate rider-facing quality for one complete trip window."""
    planning_profile = planning_profile or TripPlanningProfile()
    dates = _window_dates(window)
    profile = _destination_profile(destination)
    holiday_names = _holiday_names(dates)
    holiday_pressure = _holiday_pressure(destination, dates, holiday_names)
    long_weekend_pressure = _long_weekend_pressure(dates)
    weekend_pressure = 14 if _contains_weekend(dates) else 0
    seasonal_pressure = _seasonal_pressure(dates)
    popularity = int(profile["popularity"])

    holiday_pressure_score = _clamp_score(100 - holiday_pressure - long_weekend_pressure)
    traffic_penalty = min(85, holiday_pressure + long_weekend_pressure + weekend_pressure + (popularity * 0.35))
    traffic_score = _clamp_score(100 - traffic_penalty)
    tourism_penalty = min(85, holiday_pressure * 0.75 + seasonal_pressure + weekend_pressure + popularity)
    tourism_pressure_score = _clamp_score(100 - tourism_penalty)
    motorcycle_access_score, access_notes = _motorcycle_access(destination, dates, int(profile["access"]))
    access_score = motorcycle_access_score
    distance_score = _distance_score(route.distance_km)
    temperature_score = _temperature_score([forecast for forecast in forecasts if forecast.date in window.daily_scores])
    trip_efficiency = calculate_trip_efficiency(route, window, planning_profile)
    road_fun_score = int(profile["fun"])

    score_components = {
        "weather_score": window.trip_score,
        "stability_score": window.weather_stability_score,
        "temperature_score": temperature_score,
        "distance_score": distance_score,
        "holiday_pressure_score": holiday_pressure_score,
        "access_score": access_score,
        "trip_efficiency_score": int(trip_efficiency["trip_efficiency_score"]),
    }
    ride_quality_score = _weighted_score(score_components, RIDE_QUALITY_WEIGHTS)
    score_caps = _score_caps(score_components)
    for cap in score_caps:
        ride_quality_score = min(ride_quality_score, int(cap["cap"]))
    if trip_efficiency["exclusion_reasons"]:
        ride_quality_score = min(ride_quality_score, 45)
        score_caps.append({"reason": "excluded_by_trip_efficiency", "cap": 45})
    verdict = ride_verdict(ride_quality_score)
    recommendation_type = "least_bad_option" if ride_quality_score < 70 else "recommended"

    explanation = _experience_explanation(
        ride_quality_score,
        traffic_score,
        tourism_pressure_score,
        motorcycle_access_score,
        trip_efficiency["trip_efficiency_score"],
        holiday_names,
        access_notes,
        trip_efficiency["exclusion_reasons"],
        score_components,
        recommendation_type,
    )
    return RideExperience(
        ride_quality_score=ride_quality_score,
        weather_score=window.trip_score,
        traffic_score=traffic_score,
        tourism_pressure_score=tourism_pressure_score,
        holiday_pressure_score=holiday_pressure_score,
        holiday_score=holiday_pressure_score,
        access_score=access_score,
        motorcycle_access_score=motorcycle_access_score,
        distance_score=distance_score,
        temperature_score=temperature_score,
        trip_efficiency_score=int(trip_efficiency["trip_efficiency_score"]),
        travel_strategy=str(trip_efficiency["travel_strategy"]),
        approach_time_hours=float(trip_efficiency["approach_time_hours"]),
        return_time_hours=float(trip_efficiency["return_time_hours"]),
        total_available_time_hours=float(trip_efficiency["total_available_time_hours"]),
        estimated_destination_ride_time_hours=float(trip_efficiency["estimated_destination_ride_time_hours"]),
        approach_enjoyment_factor=float(trip_efficiency["approach_enjoyment_factor"]),
        destination_ride_time_ratio=float(trip_efficiency["destination_ride_time_ratio"]),
        score_weights=dict(RIDE_QUALITY_WEIGHTS),
        score_caps=score_caps,
        verdict=verdict,
        recommendation_type=recommendation_type,
        road_fun_score=road_fun_score,
        holiday_names=holiday_names,
        access_notes=access_notes,
        access_warnings=[] if access_score >= 80 else access_notes,
        known_restrictions=[] if "no major motorcycle restrictions" in access_notes[0] else access_notes,
        exclusion_reasons=list(trip_efficiency["exclusion_reasons"]),
        explanation=explanation,
    )


def ride_verdict(score: int) -> str:
    """Return release-facing score threshold label."""
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Very good"
    if score >= 70:
        return "Good"
    if score >= 60:
        return "Mediocre"
    if score >= 40:
        return "Poor"
    return "Not recommended"


def _weighted_score(components: dict[str, int], weights: dict[str, int]) -> int:
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0
    weighted = sum(_clamp_score(components.get(name, 0)) * weight for name, weight in weights.items())
    return _clamp_score(weighted / total_weight)


def _score_caps(components: dict[str, int]) -> list[dict[str, int | str]]:
    caps: list[dict[str, int | str]] = []
    weather_score = components["weather_score"]
    stability_score = components["stability_score"]
    if weather_score == 0:
        caps.append({"reason": "weather_score_zero", "cap": 50})
    elif weather_score < 25:
        caps.append({"reason": "weather_score_below_25", "cap": 60})
    if weather_score == 0 and stability_score == 0:
        caps.append({"reason": "weather_and_stability_zero", "cap": 45})
    return caps


def calculate_trip_efficiency(
    route: RouteInfo,
    window: TripWindow,
    planning_profile: TripPlanningProfile | None = None,
) -> dict[str, object]:
    """Calculate how much of the selected trip can be spent riding the destination."""
    planning_profile = planning_profile or TripPlanningProfile()
    strategy = planning_profile.travel_strategy
    approach_time_hours = route.travel_time_minutes / 60
    if strategy == "motorcycle_scenic":
        approach_time_hours *= 1.18
        approach_enjoyment_factor = 0.45
    elif strategy == "trailer":
        approach_enjoyment_factor = 0.0
    else:
        strategy = "motorcycle_direct"
        approach_enjoyment_factor = 0.20

    exclusion_reasons: list[str] = []
    if strategy == "trailer" and not planning_profile.trailer_support_enabled:
        exclusion_reasons.append("Trailer transport is disabled in RideRadar options.")
    if strategy == "trailer" and not planning_profile.trailer_available:
        exclusion_reasons.append("Trailer transport was selected but the trailer is not available.")
    if approach_time_hours > planning_profile.max_approach_time_hours:
        exclusion_reasons.append("Outside configured max travel effort.")

    return_time_hours = approach_time_hours
    total_available_time_hours = max(1.0, planning_profile.available_hours_per_day * window.duration_days)
    transfer_time = approach_time_hours + return_time_hours
    usable_trip_time = max(0.0, total_available_time_hours - transfer_time)
    enjoyable_approach_time = 0.0 if strategy == "trailer" else transfer_time * approach_enjoyment_factor
    enjoyable_time = min(total_available_time_hours, usable_trip_time + enjoyable_approach_time)
    destination_ride_time_ratio = usable_trip_time / total_available_time_hours
    enjoyment_ratio = enjoyable_time / total_available_time_hours

    if destination_ride_time_ratio >= 0.60:
        score = 95
    elif destination_ride_time_ratio >= 0.45:
        score = 82
    elif destination_ride_time_ratio >= 0.30:
        score = 62
    elif destination_ride_time_ratio >= 0.15:
        score = 38
    else:
        score = 18
    score = _clamp_score((score * 0.75) + (enjoyment_ratio * 100 * 0.25))
    if exclusion_reasons:
        score = min(score, 30)

    return {
        "travel_strategy": strategy,
        "approach_time_hours": round(approach_time_hours, 2),
        "return_time_hours": round(return_time_hours, 2),
        "total_available_time_hours": round(total_available_time_hours, 2),
        "estimated_destination_ride_time_hours": round(usable_trip_time, 2),
        "approach_enjoyment_factor": round(approach_enjoyment_factor, 2),
        "destination_ride_time_ratio": round(destination_ride_time_ratio, 3),
        "trip_efficiency_score": score,
        "exclusion_reasons": exclusion_reasons,
    }


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


def _destination_profile(destination: DestinationArea) -> dict[str, object]:
    name = destination.name.casefold()
    for key, profile in DESTINATION_TRAFFIC_PROFILES.items():
        if key in name:
            return profile
    return {"popularity": 16, "fun": 78, "access": 88, "countries": {"DE": 0.35, "NL": 0.35, "BE": 0.35}}


def _window_dates(window: TripWindow) -> list[date]:
    try:
        start = date.fromisoformat(window.start_day)
        end = date.fromisoformat(window.end_day)
    except ValueError:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _holiday_names(dates: list[date]) -> list[str]:
    names: list[str] = []
    for day in dates:
        names.extend(_holidays_for_day(day))
    return sorted(set(names))


def _holidays_for_day(day: date) -> list[str]:
    easter = _easter_sunday(day.year)
    holidays = {
        (1, 1): "New Year's Day",
        (5, 1): "Labour Day",
        (7, 14): "Bastille Day",
        (10, 3): "German Unity Day",
        (7, 21): "Belgian National Day",
        (6, 23): "Luxembourg National Day",
        (12, 25): "Christmas Day",
        (12, 26): "Boxing Day",
    }
    found = [name for (month, dom), name in holidays.items() if day.month == month and day.day == dom]
    relative = {
        easter: "Easter",
        easter + timedelta(days=1): "Easter Monday",
        easter + timedelta(days=39): "Ascension Day",
        easter + timedelta(days=49): "Pentecost",
        easter + timedelta(days=50): "Whit Monday",
        easter + timedelta(days=60): "Corpus Christi",
    }
    if day in relative:
        found.append(relative[day])
    return found


def _holiday_pressure(destination: DestinationArea, dates: list[date], holiday_names: list[str]) -> float:
    if not holiday_names:
        return 0
    countries = _destination_profile(destination)["countries"]
    if not isinstance(countries, dict):
        return 18
    return min(45.0, sum(float(weight) for weight in countries.values()) * 12 * len(set(holiday_names)))


def _long_weekend_pressure(dates: list[date]) -> int:
    if not dates:
        return 0
    for day in dates:
        if _holidays_for_day(day) and day.weekday() in {0, 3, 4}:
            return 20
    if any(_holidays_for_day(day - timedelta(days=1)) for day in dates if day.weekday() == 4):
        return 16
    return 0


def _seasonal_pressure(dates: list[date]) -> int:
    if any(day.month in {7, 8} for day in dates):
        return 22
    if any(day.month in {5, 6, 9} for day in dates):
        return 8
    return 0


def _contains_weekend(dates: list[date]) -> bool:
    return any(day.weekday() >= 5 for day in dates)


def _motorcycle_access(destination: DestinationArea, dates: list[date], base_score: int) -> tuple[int, list[str]]:
    name = destination.name.casefold()
    notes: list[str] = []
    penalty = 0
    if _contains_weekend(dates) and any(area in name for area in ("eifel", "zwarte woud", "vogezen", "harz")):
        penalty += 12
        notes.append("weekend motorcycle restrictions are possible on popular noise-sensitive routes")
    if any(day.month in {6, 7, 8, 9} for day in dates) and any(area in name for area in ("dolomieten", "vogezen")):
        penalty += 10
        notes.append("seasonal mountain or tourism restrictions may affect some roads")
    score = _clamp_score(base_score - penalty)
    if not notes:
        notes.append("no major motorcycle restrictions are known for this destination profile")
    return score, notes


def _distance_score(distance_km: float) -> int:
    if distance_km <= 120:
        return 95
    if distance_km <= 250:
        return 88
    if distance_km <= 400:
        return 72
    if distance_km <= 600:
        return 55
    return 35


def _temperature_score(forecasts: list[DailyForecast]) -> int:
    temperatures = [forecast.temperature_c for forecast in forecasts if forecast.temperature_c is not None]
    if not temperatures:
        return 75
    penalties = []
    for temperature in temperatures:
        if 16 <= temperature <= 26:
            penalties.append(0)
        elif 10 <= temperature < 16:
            penalties.append((16 - temperature) * 4)
        elif 26 < temperature <= 32:
            penalties.append((temperature - 26) * 3)
        else:
            penalties.append(35)
    return _clamp_score(100 - mean(penalties))


def _experience_explanation(
    ride_quality_score: int,
    traffic_score: int,
    tourism_score: int,
    access_score: int,
    trip_efficiency_score: int,
    holiday_names: list[str],
    access_notes: list[str],
    exclusion_reasons: list[str],
    score_components: dict[str, int],
    recommendation_type: str,
) -> str:
    parts = [f"Ride quality is {ride_quality_score}/100."]
    if recommendation_type == "least_bad_option":
        parts.append("No strong ride was found; this is the least compromised option within the current settings.")
    if score_components["weather_score"] == 0:
        parts.append(
            "This ride scores low because the weather score is 0/100; rain, cold, wind or unstable weather is expected."
        )
    elif score_components["weather_score"] < 25:
        parts.append("Weather is poor enough to cap the final recommendation score.")
    if score_components["stability_score"] == 0:
        parts.append("Forecast stability is 0/100, so the complete window is unreliable.")
    if exclusion_reasons:
        parts.append("This option is excluded because " + "; ".join(exclusion_reasons) + ".")
    if traffic_score >= 80:
        parts.append("Traffic pressure is expected to stay low.")
    elif traffic_score >= 60:
        parts.append("Traffic pressure is moderate and may affect busier roads.")
    else:
        parts.append("Traffic pressure is high enough to reduce ride quality.")
    if holiday_names:
        parts.append(f"Holiday pressure is elevated around {', '.join(holiday_names)}.")
    if tourism_score < 65:
        parts.append("Tourism pressure may make scenic routes busier than usual.")
    if trip_efficiency_score >= 80:
        parts.append("Travel effort leaves enough usable destination riding time.")
    elif trip_efficiency_score >= 60:
        parts.append("Travel effort is acceptable but reduces destination riding time.")
    else:
        parts.append("Travel effort leaves too little useful destination riding time for this trip type.")
    if access_score < 80:
        parts.append("Motorcycle access is partially constrained by known regional restriction risk.")
    else:
        parts.append(access_notes[0])
    return " ".join(parts)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    month_offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * month_offset) // 451
    month = (h + month_offset - 7 * m + 114) // 31
    day = ((h + month_offset - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


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
