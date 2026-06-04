"""Forecast cache and provider budget handling for RideRadar."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from inspect import signature
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import RideRadarApiError
from .const import (
    DEFAULT_FRESH_FORECAST_MAX_AGE_HOURS,
    DEFAULT_MAX_WEATHER_CALLS_PER_DAY,
    DEFAULT_MAX_WEATHER_CALLS_PER_HOUR,
    DEFAULT_PROVIDER_BACKOFF_MINUTES_AFTER_RATE_LIMIT,
    DEFAULT_STALE_FORECAST_MAX_AGE_HOURS,
    DEFAULT_WEATHER_REFRESH_INTERVAL_HOURS,
    DOMAIN,
)
from .models import DailyForecast

STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}_forecast_cache"
FORECAST_GRANULARITY = "daily"
CRITICAL_FORECAST_FIELDS = {
    "temperature_c",
    "precipitation_probability",
    "precipitation_amount_mm",
    "wind_speed_kmh",
}
OPTIONAL_FORECAST_FIELDS = {"wind_gusts_kmh", "cloud_cover", "weather_code"}


@dataclass(frozen=True, slots=True)
class CachedForecast:
    """Forecast data returned from cache or provider."""

    forecasts: list[DailyForecast]
    provider: str | None
    status: str
    cache_age_hours: float | None
    fetched_at: str | None
    from_cache: bool
    forecast_location_name: str | None
    forecast_latitude: float | None
    forecast_longitude: float | None
    missing_fields: list[str]
    data_quality_reason: str

    @property
    def usable(self) -> bool:
        return bool(self.forecasts) and self.status in {"ok", "partial", "stale"}


class ForecastCache:
    """Cache weather forecasts and protect provider call budgets."""

    def __init__(
        self,
        hass: HomeAssistant,
        providers: dict[str, Any],
        *,
        refresh_interval_hours: int = DEFAULT_WEATHER_REFRESH_INTERVAL_HOURS,
        fresh_max_age_hours: int = DEFAULT_FRESH_FORECAST_MAX_AGE_HOURS,
        stale_max_age_hours: int = DEFAULT_STALE_FORECAST_MAX_AGE_HOURS,
        max_calls_per_hour: int = DEFAULT_MAX_WEATHER_CALLS_PER_HOUR,
        max_calls_per_day: int = DEFAULT_MAX_WEATHER_CALLS_PER_DAY,
        backoff_minutes: int = DEFAULT_PROVIDER_BACKOFF_MINUTES_AFTER_RATE_LIMIT,
    ) -> None:
        self.hass = hass
        self.providers = providers
        self.refresh_interval = timedelta(hours=refresh_interval_hours)
        self.fresh_max_age = timedelta(hours=fresh_max_age_hours)
        self.stale_max_age = timedelta(hours=stale_max_age_hours)
        self.max_calls_per_hour = max_calls_per_hour
        self.max_calls_per_day = max_calls_per_day
        self.backoff = timedelta(minutes=backoff_minutes)
        self._store = Store(hass, STORE_VERSION, STORE_KEY)
        self._entries: dict[str, dict[str, Any]] = {}
        self._provider_state: dict[str, dict[str, Any]] = {
            provider: {"status": "ok", "calls": []} for provider in providers
        }
        self._last_result: CachedForecast | None = None

    def set_providers(self, providers: dict[str, Any]) -> None:
        """Update available providers without losing cache or provider counters."""
        self.providers = providers
        for provider in providers:
            self._provider_state.setdefault(provider, {"status": "ok", "calls": []})

    async def async_load(self) -> None:
        """Load persisted forecast cache."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        entries = stored.get("entries")
        provider_state = stored.get("provider_state")
        if isinstance(entries, dict):
            self._entries = {str(key): value for key, value in entries.items() if isinstance(value, dict)}
        if isinstance(provider_state, dict):
            for provider, state in provider_state.items():
                if provider in self._provider_state and isinstance(state, dict):
                    self._provider_state[provider].update(state)

    async def async_save(self) -> None:
        """Persist forecast cache."""
        await self._store.async_save(
            {
                "entries": self._entries,
                "provider_state": self._provider_state,
            }
        )

    async def async_get_forecast(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int,
        *,
        location_name: str | None = None,
        force: bool = False,
    ) -> CachedForecast:
        """Return cached forecast, refreshing only when allowed."""
        entry = self._best_cached_entry(latitude, longitude, forecast_days)
        cached = self._cached_result(entry)
        if cached and cached.status in {"ok", "partial"} and not force:
            self._last_result = cached
            return cached
        if cached and cached.status == "stale" and not force and not self._refresh_allowed(entry):
            self._last_result = cached
            return cached

        for provider, client in self.providers.items():
            key = self.cache_key(latitude, longitude, forecast_days, provider)
            provider_entry = self._entries.get(key)
            provider_cached = self._cached_result(provider_entry)
            if provider_cached and provider_cached.status in {"ok", "partial"} and not force:
                self._last_result = provider_cached
                return provider_cached
            if provider_cached and provider_cached.status == "stale" and not force and not self._refresh_allowed(
                provider_entry
            ):
                self._last_result = provider_cached
                return provider_cached
            if not force and not self._provider_can_call(provider):
                continue
            try:
                self._record_call(provider)
                forecasts = await _fetch_provider_forecast(client, latitude, longitude, forecast_days, location_name)
            except (RideRadarApiError, TimeoutError, OSError, ValueError) as err:
                self._mark_provider_failure(provider, err)
                continue
            if not forecasts:
                self._set_provider_status(provider, "missing_fields")
                continue
            missing_fields = _missing_forecast_fields(forecasts)
            critical_missing = [field for field in missing_fields if field in CRITICAL_FORECAST_FIELDS]
            if critical_missing:
                self._set_provider_status(provider, "missing_fields")
                continue
            provider_status = "partial" if missing_fields else "ok"
            self._set_provider_status(provider, "missing_fields" if missing_fields else "ok")
            result = self._store_result(
                key,
                provider,
                forecasts,
                latitude=latitude,
                longitude=longitude,
                location_name=location_name,
                status=provider_status,
                missing_fields=missing_fields,
                data_quality_reason="required_fields_missing" if missing_fields else "fresh_provider_data",
            )
            await self.async_save()
            self._last_result = result
            return result

        if cached and cached.status == "stale":
            self._last_result = cached
            return cached
        unavailable = CachedForecast(
            [],
            None,
            "unavailable",
            None,
            None,
            True,
            location_name,
            round(latitude, 3),
            round(longitude, 3),
            [],
            "destination_weather_unavailable",
        )
        self._last_result = unavailable
        return unavailable

    def status(self) -> dict[str, Any]:
        """Return compact provider/cache status for sensors and diagnostics."""
        now = dt_util.utcnow()
        entries = [self._cached_result(entry) for entry in self._entries.values()]
        usable = [entry for entry in entries if entry and entry.usable]
        cache_ages = [entry.cache_age_hours for entry in usable if entry.cache_age_hours is not None]
        last_success = max((entry.fetched_at for entry in usable if entry.fetched_at), default=None)
        last = self._last_result
        weather_status = _aggregate_weather_status(usable, last)
        provider_used = _provider_used(usable, last)
        providers = {
            provider: self._provider_public_state(provider, now)
            for provider in self.providers
        }
        return {
            "primary_provider": next(iter(self.providers), None),
            "provider_used": provider_used,
            "forecast_location_name": last.forecast_location_name if last else None,
            "forecast_latitude": last.forecast_latitude if last else None,
            "forecast_longitude": last.forecast_longitude if last else None,
            "fallback_provider_used": _fallback_used(next(iter(self.providers), None), provider_used),
            "weather_status": weather_status,
            "weather_data_quality_reason": last.data_quality_reason if last else None,
            "missing_fields": last.missing_fields if last else [],
            "last_successful_update": last_success,
            "forecast_cache_age_hours": min(cache_ages) if cache_ages else None,
            "oldest_forecast_cache_age_hours": max(cache_ages) if cache_ages else None,
            "next_scheduled_refresh": self._next_refresh_time(now),
            "providers": providers,
            "calls_used_today": {
                provider: state["calls_today"] for provider, state in providers.items()
            },
            "calls_used_this_hour": {
                provider: state["calls_this_hour"] for provider, state in providers.items()
            },
            "cache_entry_count": len(self._entries),
        }

    @staticmethod
    def cache_key(latitude: float, longitude: float, forecast_days: int, provider: str = "any") -> str:
        """Build a deduplicated cache key."""
        return f"{provider}:{latitude:.3f}:{longitude:.3f}:{int(forecast_days)}:{FORECAST_GRANULARITY}"

    def _cached_result(self, entry: dict[str, Any] | None) -> CachedForecast | None:
        if not entry:
            return None
        fetched_at = _parse_datetime(entry.get("fetched_at"))
        if fetched_at is None:
            return None
        age = dt_util.utcnow() - fetched_at
        if age <= self.fresh_max_age:
            status = str(entry.get("status") or "ok")
        elif age <= self.stale_max_age:
            status = "stale"
        else:
            status = "expired"
        if status == "expired":
            return None
        forecasts = [
            DailyForecast(**forecast)
            for forecast in entry.get("forecasts", [])
            if isinstance(forecast, dict)
        ]
        return CachedForecast(
            forecasts,
            str(entry.get("provider")) if entry.get("provider") else None,
            status,
            round(age.total_seconds() / 3600, 2),
            fetched_at.isoformat(),
            True,
            str(entry.get("forecast_location_name")) if entry.get("forecast_location_name") else None,
            _optional_float(entry.get("forecast_latitude")),
            _optional_float(entry.get("forecast_longitude")),
            [str(field) for field in entry.get("missing_fields", []) if field],
            "cache_stale" if status == "stale" else str(entry.get("data_quality_reason") or "cache_used"),
        )

    def _best_cached_entry(self, latitude: float, longitude: float, forecast_days: int) -> dict[str, Any] | None:
        provider_keys = [*self.providers, "any"]
        entries = [
            self._entries.get(self.cache_key(latitude, longitude, forecast_days, provider))
            for provider in provider_keys
        ]
        entries = [entry for entry in entries if entry]
        fresh_or_partial = [
            entry
            for entry in entries
            if (cached := self._cached_result(entry)) and cached.status in {"ok", "partial"}
        ]
        if fresh_or_partial:
            return fresh_or_partial[0]
        stale = [
            entry
            for entry in entries
            if (cached := self._cached_result(entry)) and cached.status == "stale"
        ]
        return stale[0] if stale else None

    def _store_result(
        self,
        key: str,
        provider: str,
        forecasts: list[DailyForecast],
        *,
        latitude: float,
        longitude: float,
        location_name: str | None,
        status: str,
        missing_fields: list[str],
        data_quality_reason: str,
    ) -> CachedForecast:
        fetched_at = dt_util.utcnow().isoformat()
        self._entries[key] = {
            "provider": provider,
            "fetched_at": fetched_at,
            "status": status,
            "forecast_location_name": location_name,
            "forecast_latitude": round(latitude, 3),
            "forecast_longitude": round(longitude, 3),
            "missing_fields": missing_fields,
            "data_quality_reason": data_quality_reason,
            "forecasts": [asdict(forecast) for forecast in forecasts],
        }
        return CachedForecast(
            forecasts,
            provider,
            status,
            0.0,
            fetched_at,
            False,
            location_name,
            round(latitude, 3),
            round(longitude, 3),
            missing_fields,
            data_quality_reason,
        )

    def _refresh_allowed(self, entry: dict[str, Any] | None) -> bool:
        if not entry:
            return True
        fetched_at = _parse_datetime(entry.get("fetched_at"))
        return fetched_at is None or dt_util.utcnow() - fetched_at >= self.refresh_interval

    def _provider_can_call(self, provider: str) -> bool:
        state = self._provider_state.setdefault(provider, {"status": "ok", "calls": []})
        now = dt_util.utcnow()
        backoff_until = _parse_datetime(state.get("backoff_until"))
        if backoff_until and backoff_until > now:
            state["status"] = "backoff"
            return False
        calls = self._recent_calls(provider, now)
        if len([call for call in calls if now - call <= timedelta(hours=1)]) >= self.max_calls_per_hour:
            state["status"] = "rate_limited"
            return False
        if len([call for call in calls if now - call <= timedelta(days=1)]) >= self.max_calls_per_day:
            state["status"] = "rate_limited"
            return False
        return True

    def _record_call(self, provider: str) -> None:
        state = self._provider_state.setdefault(provider, {"status": "ok", "calls": []})
        calls = [call.isoformat() for call in self._recent_calls(provider, dt_util.utcnow())]
        calls.append(dt_util.utcnow().isoformat())
        state["calls"] = calls

    def _recent_calls(self, provider: str, now: datetime) -> list[datetime]:
        state = self._provider_state.setdefault(provider, {"status": "ok", "calls": []})
        calls = [
            call
            for call in (_parse_datetime(value) for value in state.get("calls", []))
            if call is not None and now - call <= timedelta(days=1)
        ]
        state["calls"] = [call.isoformat() for call in calls]
        return calls

    def _mark_provider_failure(self, provider: str, err: Exception) -> None:
        message = str(err).casefold()
        if "429" in message or "rate" in message or "limit" in message:
            self._provider_state[provider]["backoff_until"] = (dt_util.utcnow() + self.backoff).isoformat()
            self._set_provider_status(provider, "backoff")
            return
        if isinstance(err, TimeoutError) or "timeout" in message:
            self._set_provider_status(provider, "timeout")
            return
        if "invalid" in message or "malformed" in message:
            self._set_provider_status(provider, "invalid_response")
            return
        if "missing" in message:
            self._set_provider_status(provider, "missing_fields")
            return
        self._set_provider_status(provider, "unavailable")

    def _set_provider_status(self, provider: str, status: str) -> None:
        state = self._provider_state.setdefault(provider, {"status": "ok", "calls": []})
        state["status"] = status
        if status == "ok":
            state.pop("backoff_until", None)

    def _provider_public_state(self, provider: str, now: datetime) -> dict[str, Any]:
        state = self._provider_state.setdefault(provider, {"status": "ok", "calls": []})
        calls = self._recent_calls(provider, now)
        backoff_until = state.get("backoff_until")
        return {
            "status": state.get("status", "ok"),
            "calls_this_hour": len([call for call in calls if now - call <= timedelta(hours=1)]),
            "calls_today": len(calls),
            "backoff_until": backoff_until,
        }

    def _next_refresh_time(self, now: datetime) -> str | None:
        fetched = [
            _parse_datetime(entry.get("fetched_at"))
            for entry in self._entries.values()
            if isinstance(entry, dict)
        ]
        fetched = [value for value in fetched if value is not None]
        if not fetched:
            return None
        return (min(fetched) + self.refresh_interval).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed.astimezone(dt_util.UTC)


async def _fetch_provider_forecast(
    client: Any,
    latitude: float,
    longitude: float,
    forecast_days: int,
    location_name: str | None,
) -> list[DailyForecast]:
    method = client.get_daily_forecast
    if "location_name" in signature(method).parameters:
        return await method(latitude, longitude, forecast_days, location_name=location_name)
    return await method(latitude, longitude, forecast_days)


def _missing_forecast_fields(forecasts: list[DailyForecast]) -> list[str]:
    missing: set[str] = set()
    for forecast in forecasts:
        for field in CRITICAL_FORECAST_FIELDS | OPTIONAL_FORECAST_FIELDS:
            if getattr(forecast, field) is None:
                missing.add(field)
    return sorted(missing)


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fallback_used(primary: str | None, used: str | None) -> str | None:
    if primary and used and primary != used:
        return used
    return None


def _aggregate_weather_status(usable: list[CachedForecast], last: CachedForecast | None) -> str:
    if last and last.status == "ok":
        return "ok"
    if any(entry.status == "ok" for entry in usable):
        return "ok"
    if last and last.status == "partial":
        return "partial"
    if any(entry.status == "partial" for entry in usable):
        return "partial"
    if last and last.status == "stale":
        return "stale"
    if any(entry.status == "stale" for entry in usable):
        return "stale"
    return "unavailable"


def _provider_used(usable: list[CachedForecast], last: CachedForecast | None) -> str | None:
    if last and last.provider:
        return last.provider
    for entry in usable:
        if entry.provider:
            return entry.provider
    return None


class HomeAssistantWeatherEntityClient:
    """Forecast client backed by explicit destination-to-weather-entity mapping."""

    provider_name = "home_assistant_weather_entity"

    def __init__(self, hass: HomeAssistant, destination_entity_map: dict[str, str]) -> None:
        self.hass = hass
        self.destination_entity_map = {
            str(destination).casefold(): str(entity_id)
            for destination, entity_id in destination_entity_map.items()
            if destination and entity_id
        }

    async def get_daily_forecast(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int,
        *,
        location_name: str | None = None,
    ) -> list[DailyForecast]:
        """Read a forecast from an explicitly mapped HA weather entity."""
        if not location_name:
            raise RideRadarApiError("missing destination-specific weather entity mapping")
        entity_id = self.destination_entity_map.get(location_name.casefold())
        if not entity_id:
            raise RideRadarApiError("missing destination-specific weather entity mapping")
        state = self.hass.states.get(entity_id)
        if state is None:
            raise RideRadarApiError("mapped weather entity is unavailable")
        forecast = state.attributes.get("forecast")
        if not isinstance(forecast, list):
            raise RideRadarApiError("mapped weather entity has no daily forecast attribute")
        return [_forecast_from_ha_item(item) for item in forecast[:forecast_days] if isinstance(item, dict)]


def _forecast_from_ha_item(item: dict[str, Any]) -> DailyForecast:
    return DailyForecast(
        date=_ha_forecast_date(item),
        temperature_c=_optional_float(item.get("temperature")),
        precipitation_probability=_optional_float(item.get("precipitation_probability")),
        precipitation_amount_mm=_optional_float(item.get("precipitation")),
        wind_speed_kmh=_optional_float(item.get("wind_speed")),
        wind_gusts_kmh=_optional_float(item.get("wind_gust_speed")),
        cloud_cover=_optional_float(item.get("cloud_coverage")),
        weather_code=None,
    )


def _ha_forecast_date(item: dict[str, Any]) -> str:
    value = item.get("datetime") or item.get("date") or item.get("time")
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    raise RideRadarApiError("mapped weather entity forecast item has no date")
