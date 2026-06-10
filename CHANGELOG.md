# Changelog

## 1.0.0 - 2026-06-10

- Removed raw destination JSON editing from the normal config flow.
- Added guided start-location lookup with resolved-coordinate confirmation.
- Added structured destination options for enabling defaults, adding custom destinations, removing custom destinations, and resetting defaults.
- Added a geocoding abstraction using the free Open-Meteo geocoding API.
- Added migration from the unreleased raw JSON destination format.
- Reworked README around a normal-user quickstart and dashboard view.

## 0.1.0 - 2026-06-01

Initial RideRadar release.

- Added Home Assistant config flow and options flow.
- Added Open-Meteo forecast client.
- Added fallback route-distance estimator behind a routing client abstraction.
- Added default motorcycle-oriented destinations and guided destination management.
- Added RideScore scoring for precipitation, wind, gusts, temperature, cloud cover, and weather code.
- Added summary sensors and one distance sensor per enabled destination.
- Added diagnostics with start address redaction.
- Added README dashboard examples and development instructions.
