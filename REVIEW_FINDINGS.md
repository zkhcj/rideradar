# RideRadar Maintainer Review Findings

## Issues Found

- Config validation was too loose: coordinates, forecast days, maximum distance, detour factor, activity profile, and destination structure were not consistently range-checked.
- Empty destination lists could accidentally fall back to defaults because destination parsing treated falsey values as absent.
- Destination models accepted malformed objects and converted many invalid values silently.
- Coordinator data was all-or-nothing but did not clearly distinguish empty config, unreachable destinations, unavailable forecasts, and invalid saved configuration.
- Coordinator scoring ignored the selected activity profile, making future profiles harder to add.
- Per-destination result modeling assumed every destination had a route and score, which was not true for unreachable destinations.
- Sensor metadata was minimal and not attached to a Home Assistant device.
- Sensor attributes did not expose per-day explanations and did not expose reachability explicitly.
- Entity slugs were built with ad hoc string replacement instead of Home Assistant slug handling.
- Integration unload could raise if domain data was already absent.
- Diagnostics support was missing, including redaction of the configured start address.
- Translations were missing several validation error keys and options-flow error entries.
- API error handling did not normalize malformed JSON, HTTP status errors, and malformed geocoding responses cleanly.
- Tests did not cover coordinator behavior, unavailable API behavior, empty destination lists, invalid coordinate/settings validation, diagnostics, or setup/unload lifecycle.
- README did not document diagnostics, empty destination behavior, validation troubleshooting, or the practical entity ID caveat.

## Decisions Made

- Kept destination management as JSON in the options flow for the MVP because Home Assistant config flows do not provide a native rich editable table suitable for destination CRUD without a custom frontend.
- Allowed an empty destination list and made it a valid loaded state with a clear summary sensor message.
- Preserved the routing abstraction and kept the fallback detour estimator as the only built-in routing provider.
- Treated Open-Meteo forecast unavailability as `UpdateFailed` so Home Assistant coordinator semantics preserve prior data when possible.
- Added activity-profile-aware scoring structure now, even though only `motorcycle` is currently selectable.
- Attached all sensors to one RideRadar device and used Home Assistant slugification for destination entity unique IDs.

## Refactors Performed

- Added strict destination model validation through `RideRadarConfigError`.
- Reworked config and options flow validation into smaller validation helpers.
- Added coordinate pair validation, numeric range validation, activity profile validation, and empty destination parsing.
- Refactored coordinator results to represent `route`, `best_score`, reachability, and availability explicitly.
- Updated scoring to use a `ScoringProfile` abstraction keyed by activity profile.
- Hardened Open-Meteo API client error handling.
- Added Home Assistant diagnostics support with start address redaction.
- Improved sensor descriptions, units, state classes, icons, device info, attribution, reachability attributes, and per-day explanations.
- Made unload idempotent against missing domain data.
- Expanded translations for all validation errors in English and Dutch.
- Expanded tests for config flow, coordinator edge cases, diagnostics, setup/unload, scoring, routing, and default destinations.
- Updated README with behavior notes, troubleshooting, diagnostics, and architecture guidance.

## Remaining Technical Debt

- Destination CRUD is still JSON-based. A richer UX would require either a custom panel/card or a multi-step flow pattern that is more cumbersome than JSON for bulk editing.
- Route distances are still estimates. Real routing providers need separate clients, provider selection, request throttling, and provider-specific tests.
- Coordinator currently fetches reachable destination forecasts sequentially. This is acceptable for the default list size but should become bounded concurrent fetching if large destination lists become common.
- Entity registry cleanup for removed destinations is left to Home Assistant/user cleanup after options reload; a future version could actively remove stale registry entries with careful migration behavior.
- No full Home Assistant runtime smoke test was possible in this container because pytest, ruff, pip, and Home Assistant test dependencies are not installed.

## Recommended Next Steps

- Add OSRM as the first real routing provider because it can be self-hosted and avoids paid API dependencies.
- Introduce bounded concurrent forecast fetches once provider rate-limit behavior is defined.
- Add more activity profiles only after defining their weather thresholds and route preferences.
- Add a repairs issue when all destinations are disabled or no destination is reachable.
- Add release metadata and real repository URLs before publishing through HACS.
