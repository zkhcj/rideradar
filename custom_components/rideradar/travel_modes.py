"""Travel-mode configuration helpers for RideRadar."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_MOTORCYCLE_DIRECT_ENABLED,
    CONF_MOTORCYCLE_DIRECT_JOKER_MAX_APPROACH_TIME_HOURS,
    CONF_MOTORCYCLE_DIRECT_NORMAL_MAX_APPROACH_TIME_HOURS,
    CONF_MOTORCYCLE_SCENIC_ENABLED,
    CONF_MOTORCYCLE_SCENIC_JOKER_MAX_APPROACH_TIME_HOURS,
    CONF_MOTORCYCLE_SCENIC_NORMAL_MAX_APPROACH_TIME_HOURS,
    CONF_TRAILER_AVAILABLE,
    CONF_TRAILER_JOKER_MAX_APPROACH_TIME_HOURS,
    CONF_TRAILER_NORMAL_MAX_APPROACH_TIME_HOURS,
    CONF_TRAILER_SUPPORT_ENABLED,
    CONF_TRAVEL_MODES,
    DEFAULT_TRAVEL_MODES,
    TRAVEL_STRATEGY_MOTORCYCLE_DIRECT,
    TRAVEL_STRATEGY_MOTORCYCLE_SCENIC,
    TRAVEL_STRATEGY_TRAILER,
)

MODE_FIELDS = {
    TRAVEL_STRATEGY_MOTORCYCLE_DIRECT: {
        "enabled": CONF_MOTORCYCLE_DIRECT_ENABLED,
        "normal": CONF_MOTORCYCLE_DIRECT_NORMAL_MAX_APPROACH_TIME_HOURS,
        "joker": CONF_MOTORCYCLE_DIRECT_JOKER_MAX_APPROACH_TIME_HOURS,
    },
    TRAVEL_STRATEGY_MOTORCYCLE_SCENIC: {
        "enabled": CONF_MOTORCYCLE_SCENIC_ENABLED,
        "normal": CONF_MOTORCYCLE_SCENIC_NORMAL_MAX_APPROACH_TIME_HOURS,
        "joker": CONF_MOTORCYCLE_SCENIC_JOKER_MAX_APPROACH_TIME_HOURS,
    },
    TRAVEL_STRATEGY_TRAILER: {
        "enabled": CONF_TRAILER_AVAILABLE,
        "normal": CONF_TRAILER_NORMAL_MAX_APPROACH_TIME_HOURS,
        "joker": CONF_TRAILER_JOKER_MAX_APPROACH_TIME_HOURS,
    },
}


def normalize_travel_modes(config: dict[str, Any]) -> dict[str, dict[str, bool | float]]:
    """Return valid travel-mode config, migrated from old or flat options."""
    raw = config.get(CONF_TRAVEL_MODES)
    modes: dict[str, dict[str, bool | float]] = {}
    for mode, defaults in DEFAULT_TRAVEL_MODES.items():
        configured = raw.get(mode, {}) if isinstance(raw, dict) else {}
        fields = MODE_FIELDS[mode]
        normal = _float_value(
            config.get(fields["normal"], configured.get("normal_max_approach_time_hours")),
            float(defaults["normal_max_approach_time_hours"]),
        )
        joker = _float_value(
            config.get(fields["joker"], configured.get("joker_max_approach_time_hours")),
            float(defaults["joker_max_approach_time_hours"]),
        )
        enabled_default = bool(defaults["enabled"])
        if raw is None and mode == TRAVEL_STRATEGY_TRAILER:
            enabled_default = _bool_value(config.get(CONF_TRAILER_SUPPORT_ENABLED), enabled_default)
        enabled = _bool_value(
            config.get(fields["enabled"], configured.get("enabled")),
            enabled_default,
        )
        modes[mode] = {
            "enabled": enabled,
            "normal_max_approach_time_hours": max(0.5, normal),
            "joker_max_approach_time_hours": max(max(0.5, normal), joker),
        }
    if not any(mode["enabled"] for mode in modes.values()):
        modes[TRAVEL_STRATEGY_MOTORCYCLE_DIRECT]["enabled"] = True
    return modes


def flat_travel_mode_options(config: dict[str, Any]) -> dict[str, Any]:
    """Return flat fields for options-flow defaults."""
    modes = normalize_travel_modes(config)
    flat: dict[str, Any] = {CONF_TRAVEL_MODES: modes}
    for mode, fields in MODE_FIELDS.items():
        flat[fields["enabled"]] = modes[mode]["enabled"]
        flat[fields["normal"]] = modes[mode]["normal_max_approach_time_hours"]
        flat[fields["joker"]] = modes[mode]["joker_max_approach_time_hours"]
    return flat


def travel_mode_options_from_input(data: dict[str, Any]) -> dict[str, Any]:
    """Build canonical travel-mode options from options-flow input."""
    modes = {}
    for mode, fields in MODE_FIELDS.items():
        normal = float(data[fields["normal"]])
        joker = float(data[fields["joker"]])
        modes[mode] = {
            "enabled": bool(data[fields["enabled"]]),
            "normal_max_approach_time_hours": normal,
            "joker_max_approach_time_hours": joker,
        }
    flat = flat_travel_mode_options({CONF_TRAVEL_MODES: modes})
    flat[CONF_TRAVEL_MODES] = modes
    return flat


def travel_mode_validation_errors(data: dict[str, Any]) -> dict[str, str]:
    """Validate travel-mode options-flow input."""
    errors: dict[str, str] = {}
    enabled_count = 0
    for fields in MODE_FIELDS.values():
        if bool(data.get(fields["enabled"])):
            enabled_count += 1
        normal = _float_value(data.get(fields["normal"]), 0)
        joker = _float_value(data.get(fields["joker"]), 0)
        if normal <= 0:
            errors[fields["normal"]] = "invalid_approach_time"
        if joker < normal:
            errors[fields["joker"]] = "joker_below_normal"
    if enabled_count == 0:
        errors["base"] = "no_travel_mode_enabled"
    return errors


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"on", "true", "yes", "1"}:
            return True
        if normalized in {"off", "false", "no", "0"}:
            return False
    if value is None:
        return default
    return bool(value)
