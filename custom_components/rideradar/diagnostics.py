"""Diagnostics support for RideRadar."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_START_ADDRESS, CONF_START_LATITUDE, CONF_START_LONGITUDE, DOMAIN, INTEGRATION_VERSION
from .destinations import destinations_from_config

TO_REDACT = {CONF_START_ADDRESS, CONF_START_LATITUDE, CONF_START_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = getattr(coordinator, "data", None) or {}
    config = {**entry.data, **entry.options}
    return {
        "entry": {
            "version": INTEGRATION_VERSION,
            "data": async_redact_data(_rounded_location(entry.data), TO_REDACT),
            "options": async_redact_data(entry.options, TO_REDACT),
        },
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "destination_count": data.get("destination_count"),
            "opportunity_count": len(data.get("opportunities") or []),
            "all_opportunity_count": data.get("all_opportunities_candidate_count", 0),
            "all_opportunities_visible": len(data.get("all_opportunities") or []),
            "all_opportunities_sample": _compact_opportunities((data.get("all_opportunities") or [])[:10]),
            "summary": data.get("summary"),
            "weather": data.get("weather", {}),
            "mode_status": data.get("mode_status", {}),
            "evaluation_summary": data.get("evaluation_summary", {}),
            "evaluated_candidates": data.get("evaluated_candidates", []),
            "active_helpers": data.get("active_helpers", {}),
            "enabled_destinations": [destination.name for destination in destinations_from_config(config)],
            "excluded_destinations": data.get("excluded_destinations", []),
            "top_week_opportunities": _compact_opportunities(data.get("top_week_opportunities")),
            "top_month_opportunities": _compact_opportunities(data.get("top_month_opportunities")),
            "best_future_windows": _best_future_windows(data),
            "decision_traces": _decision_traces(data.get("opportunities")),
            "warnings": _diagnostic_warnings(data),
        },
    }


def _rounded_location(value: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(value)
    for key in (CONF_START_LATITUDE, CONF_START_LONGITUDE):
        if key in rounded:
            try:
                rounded[key] = round(float(rounded[key]), 2)
            except (TypeError, ValueError):
                rounded[key] = "unknown"
    return rounded


def _compact_opportunities(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_compact_opportunity(item) for item in value if isinstance(item, dict)]


def _compact_opportunity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "destination": item.get("destination"),
        "strategy": item.get("strategy") or item.get("travel_strategy"),
        "strategy_label": item.get("strategy_label"),
        "period": item.get("period"),
        "duration_days": item.get("duration_days"),
        "ride_quality_score": item.get("ride_quality_score"),
        "score": item.get("score"),
        "distance_km": item.get("distance_km") or item.get("route_distance_km"),
        "approach_time_hours": item.get("approach_time_hours"),
        "score_breakdown": item.get("score_breakdown"),
        "score_weights": item.get("score_weights"),
        "score_caps": item.get("score_caps"),
        "recommendation_reason": item.get("recommendation_reason"),
        "tradeoffs": item.get("tradeoffs", []),
        "weather_evaluation": item.get("weather_evaluation"),
    }


def _decision_traces(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    traces = []
    for item in value[:10]:
        if isinstance(item, dict) and isinstance(item.get("decision_trace"), dict):
            trace = dict(item["decision_trace"])
            inputs = dict(trace.get("inputs", {}))
            inputs[CONF_START_ADDRESS] = "**REDACTED**"
            trace["inputs"] = inputs
            traces.append(trace)
    return traces


def _best_future_windows(data: dict[str, Any]) -> list[dict[str, Any]]:
    windows = []
    for result in data.get("results", []) or []:
        destination = getattr(getattr(result, "destination", None), "name", None)
        window = getattr(result, "best_trip_window", None)
        experience = getattr(result, "ride_experience", None)
        if destination and window and experience:
            windows.append(
                {
                    "destination": destination,
                    "start_date": window.start_day,
                    "end_date": window.end_day,
                    "duration_days": window.duration_days,
                    "ride_quality_score": experience.ride_quality_score,
                    "weather": getattr(result, "weather", None) or {},
                    "score_breakdown": {
                        "weather_score": experience.weather_score,
                        "stability_score": window.weather_stability_score,
                        "temperature_score": experience.temperature_score,
                        "distance_score": experience.distance_score,
                        "holiday_pressure_score": experience.holiday_pressure_score,
                        "access_score": experience.access_score,
                        "trip_efficiency_score": experience.trip_efficiency_score,
                        "ride_quality_score": experience.ride_quality_score,
                    },
                }
            )
    return windows


def _diagnostic_warnings(data: dict[str, Any]) -> list[str]:
    warnings = []
    if not data.get("best"):
        warnings.append("No best destination is currently available.")
    if data.get("excluded_destinations"):
        warnings.append("One or more destinations were excluded from recommendation ranking.")
    return warnings
