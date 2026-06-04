"""Tests for RideRadar diagnostics."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rideradar.const import CONF_START_ADDRESS, CONF_START_LATITUDE, CONF_START_LONGITUDE, DOMAIN
from custom_components.rideradar.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_start_address(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_START_ADDRESS: "Private address",
            CONF_START_LATITUDE: 52.12345,
            CONF_START_LONGITUDE: 6.98765,
        },
    )
    coordinator = type(
        "Coordinator",
        (),
        {
            "data": {"destination_count": 0, "summary": "No enabled destinations configured"},
            "last_update_success": True,
        },
    )()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert data["entry"]["data"][CONF_START_ADDRESS] == "**REDACTED**"
    assert data["entry"]["data"][CONF_START_LATITUDE] == "**REDACTED**"
    assert data["coordinator"]["destination_count"] == 0


async def test_diagnostics_exposes_black_box_summary(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_START_ADDRESS: "Private address"})
    opportunity = {
        "destination": "Sauerland",
        "period": "Za 13-06-2026 t/m Zo 14-06-2026",
        "duration_days": 2,
        "ride_quality_score": 88,
        "score_breakdown": {"ride_quality_score": 88, "trip_efficiency_score": 89},
        "recommendation_reason": "Best complete window.",
        "tradeoffs": [],
        "decision_trace": {
            "inputs": {CONF_START_ADDRESS: "Private address", "destination": "Sauerland"},
            "window": {"period": "Za 13-06-2026 t/m Zo 14-06-2026"},
            "scores": {"ride_quality_score": 88},
        },
    }
    coordinator = type(
        "Coordinator",
        (),
        {
            "data": {
                "destination_count": 1,
                "summary": "Sauerland wins",
                "opportunities": [opportunity],
                "top_week_opportunities": [opportunity],
                "top_month_opportunities": [opportunity],
                "excluded_destinations": [
                    {
                        "destination": "Harz",
                        "reason": "insufficient_destination_ride_time",
                        "details": "Only 24% remains.",
                    }
                ],
                "active_helpers": {"input_select.rideradar_travel_strategy": "Motorcycle Direct"},
            },
            "last_update_success": True,
        },
    )()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert data["entry"]["version"] != "unknown"
    assert data["coordinator"]["top_week_opportunities"][0]["destination"] == "Sauerland"
    assert data["coordinator"]["excluded_destinations"][0]["destination"] == "Harz"
    assert data["coordinator"]["decision_traces"][0]["inputs"][CONF_START_ADDRESS] == "**REDACTED**"
