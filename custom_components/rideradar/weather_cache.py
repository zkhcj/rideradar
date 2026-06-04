"""Forecast cache and provider budget handling for RideRadar."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
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


@dataclass(frozen=True, slots=True)
class CachedForecast:
    """Forecast data returned from cache or provider."""

    forecasts: list[DailyForecast]
    provider: str | None
    status: str
    cache_age_hours: float | None
    fetched_at: str | None
    from_cache: bool

    @property
    def usable(self) -> bool:
        return bool(self.forecasts) and self.status in {"ok", "stale"}


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
        force: bool = False,
    ) -> CachedForecast:
        """Return cached forecast, refreshing only when allowed."""
        key = self.cache_key(latitude, longitude, forecast_days)
        entry = self._entries.get(key)
        cached = self._cached_result(entry)
        if cached and cached.status == "ok" and not force:
            self._last_result = cached
            return cached
        if cached and cached.status == "stale" and not force and not self._refresh_allowed(entry):
            self._last_result = cached
            return cached

        for provider, client in self.providers.items():
            if not force and not self._provider_can_call(provider):
                continue
            try:
                self._record_call(provider)
                forecasts = await client.get_daily_forecast(latitude, longitude, forecast_days)
            except (RideRadarApiError, TimeoutError, OSError, ValueError) as err:
                self._mark_provider_failure(provider, err)
                continue
            if not forecasts:
                self._set_provider_status(provider, "missing_fields")
                continue
            self._set_provider_status(provider, "ok")
            result = self._store_result(key, provider, forecasts)
            await self.async_save()
            self._last_result = result
            return result

        if cached and cached.status == "stale":
            self._last_result = cached
            return cached
        unavailable = CachedForecast([], None, "unavailable", None, None, True)
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
            "fallback_provider_used": _fallback_used(next(iter(self.providers), None), provider_used),
            "weather_status": weather_status,
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
            status = "ok"
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
        )

    def _store_result(self, key: str, provider: str, forecasts: list[DailyForecast]) -> CachedForecast:
        fetched_at = dt_util.utcnow().isoformat()
        self._entries[key] = {
            "provider": provider,
            "fetched_at": fetched_at,
            "forecasts": [asdict(forecast) for forecast in forecasts],
        }
        return CachedForecast(forecasts, provider, "ok", 0.0, fetched_at, False)

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


def _fallback_used(primary: str | None, used: str | None) -> str | None:
    if primary and used and primary != used:
        return used
    return None


def _aggregate_weather_status(usable: list[CachedForecast], last: CachedForecast | None) -> str:
    if last and last.status == "ok":
        return "ok"
    if any(entry.status == "ok" for entry in usable):
        return "ok"
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
