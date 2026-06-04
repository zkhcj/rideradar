"""Tests for copy-paste RideRadar dashboard examples."""

from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def test_default_dashboard_uses_safe_mapping_access() -> None:
    readme = README.read_text(encoding="utf-8")

    unsafe_patterns = [
        "trace.result",
        "trace.inputs",
        "trace.scores",
        "trace.weights",
        "trace.caps",
        "opportunity.period",
        "opportunity.recommendation_reason",
    ]
    for pattern in unsafe_patterns:
        assert pattern not in readme

    assert "trace.get('result', {}) if trace is mapping else {}" in readme
    assert "trace.get('scores', {}) if trace is mapping else {}" in readme


def test_default_dashboard_uses_native_entities_and_literal_markdown_tables() -> None:
    readme = README.read_text(encoding="utf-8")

    for entity_id in (
        "sensor.rideradar_top_week_direct_opportunities",
        "sensor.rideradar_top_week_scenic_opportunities",
        "sensor.rideradar_top_week_trailer_opportunities",
        "sensor.rideradar_top_forecast_direct_opportunities",
        "sensor.rideradar_top_forecast_scenic_opportunities",
        "sensor.rideradar_top_forecast_trailer_opportunities",
        "select.rideradar_trip_duration",
        "number.rideradar_trip_duration_days",
        "number.rideradar_forecast_horizon_days",
        "select.rideradar_preferred_start_day",
        "switch.rideradar_weekend_only",
        "select.rideradar_travel_strategy",
        "switch.rideradar_trailer_available",
        "number.rideradar_available_hours_per_day",
        "number.rideradar_max_approach_time_hours",
        "sensor.rideradar_all_opportunities",
    ):
        assert entity_id in readme

    assert "Deze week - direct" in readme
    assert "Deze week - binnendoor" in readme
    assert "Deze maand - direct" in readme
    assert "Deze maand - binnendoor" in readme
    assert "Beschikbare vensters" in readme
    assert "Coming 8 dagen" not in readme
    assert "Forecast - direct" not in readme
    assert "Forecast - binnendoor" not in readme
    assert "| Bestemming | Strategie | Score | Dagen | Periode | Aandachtspunt |" in readme
    assert "Aanhanger vandaag beschikbaar" in readme
    assert "type: custom:flex-table-card" in readme
    assert "opportunities.score" in readme
    assert "opportunities.strategy_label" in readme
