# RideRadar

RideRadar recommends the best complete motorcycle trip windows from your configured start location and destinations.

## 10-Step Quickstart

1. Install RideRadar through HACS as a custom repository.
2. Restart Home Assistant.
3. Go to Settings > Devices & services > Add integration.
4. Configure your start location by searching for a place or address, for example `Hardenberg, Nederland`.
5. Choose your trip duration, such as 1 day, 2 days, 3 days, or custom.
6. Choose the forecast horizon days RideRadar should evaluate.
7. Configure your maximum route distance.
8. Choose the destination areas RideRadar should compare.
9. Add one of the dashboard cards below.
10. Check RideRadar before planning the ride.

## Ready-To-Copy Dashboard Examples

### Best Trip

```yaml
type: markdown
title: RideRadar best trip
content: >
  ## {{ states('sensor.rideradar_best_trip_destination') }}

  Trip score: **{{ states('sensor.rideradar_best_trip_score') }}/100**

  Starts: **{{ states('sensor.rideradar_best_trip_start_day') }}**

  Duration: **{{ states('sensor.rideradar_trip_duration') }} days**

  {{ states('sensor.rideradar_best_summary') }}
```

### Top 5 Reachable Destinations

```yaml
type: entities
title: RideRadar destinations
entities:
  - entity: sensor.rideradar_best_trip_destination
  - entity: sensor.rideradar_best_trip_score
  - entity: sensor.rideradar_best_opportunities
  - entity: sensor.rideradar_destination_count
```

### Top 5 Availability Windows

```yaml
type: markdown
title: RideRadar availability
content: >
  {% set windows = state_attr('sensor.rideradar_best_opportunities', 'opportunities') or [] %}
  {% for item in windows[:5] %}
  - **{{ item.destination }}** from {{ item.start_date }} to {{ item.end_date }}:
    {{ item.trip_score }}/100, {{ item.verdict }}
  {% endfor %}
```

### Best Weekend Opportunity

```yaml
type: markdown
title: Best weekend ride
content: >
  {% set item = state_attr('sensor.rideradar_best_weekend_opportunity', 'opportunity') %}
  {% if item %}
  **{{ item.destination }}** from {{ item.start_date }} to {{ item.end_date }}

  Score: **{{ item.trip_score }}/100**

  {{ item.explanation }}
  {% else %}
  No weekend opportunity is available in the current forecast horizon.
  {% endif %}
```

### Destination Detail: Why This Score?

```yaml
type: markdown
title: Sauerland detail
content: >
  {% set e = 'sensor.rideradar_sauerland' %}
  Trip score: **{{ state_attr(e, 'trip_score') }}/100**

  Stability: **{{ state_attr(e, 'weather_stability_score') }}/100**

  {{ state_attr(e, 'trip_explanation') }}

  Daily scores:
  {{ state_attr(e, 'daily_scores') }}
```

## Availability Windows

RideRadar evaluates every complete trip window inside the forecast horizon.

Example with a 2-day trip duration and 7-day forecast horizon:

- Monday-Tuesday
- Tuesday-Wednesday
- Wednesday-Thursday
- Thursday-Friday
- Friday-Saturday
- Saturday-Sunday

Each window includes destination, start date, end date, duration, trip score, stability score, route distance, travel time, daily scores, verdict, and explanation.

Summary sensors:

- `sensor.rideradar_best_opportunities`
- `sensor.rideradar_best_weekend_opportunity`
- `sensor.rideradar_best_weekday_opportunity`
- `sensor.rideradar_best_next_available_opportunity`

Destination sensors expose:

- `all_trip_windows`
- `best_trip_window`
- `next_good_window`
- `weekend_windows`
- `weekday_windows`
- `daily_scores`
- `trip_score_breakdown`
- `trip_explanation`

## Configuration Guide

Initial setup uses a Home Assistant-native location flow:

1. Enter a readable place or address, for example `Hardenberg, Nederland`, `Rheezerveen, Nederland`, or `Utrecht, Nederland`.
2. RideRadar geocodes it using Open-Meteo.
3. If one result is found, RideRadar shows a confirmation screen.
4. If multiple results are found, choose from readable candidate locations.
5. Confirm the resolved display name and coordinates.

The options flow shows one normal settings screen with:

- current configured start location
- current resolved coordinates
- editable start address/place
- maximum route distance
- trip duration
- forecast horizon days
- activity profile
- enabled destinations

Coordinates are internal resolved data. They are shown for confirmation, not as the primary input method. Raw destination JSON is not part of the normal setup or options experience; import/export remains an advanced maintenance path only.

## Troubleshooting

- Start location not found: try a nearby town, a larger city, or add the country name.
- Wrong location found: choose a different candidate or search with more context.
- No best destination: enable at least one destination or increase maximum route distance.
- No weekend opportunity: increase the forecast horizon or wait for more forecast data.
- Distances look approximate: RideRadar currently uses a fallback route estimate with a configurable detour factor.
- Missing destination sensor after editing destinations: reload the integration or remove stale disabled entities from Settings > Devices & services > Entities.

## Development

Create a virtual environment and install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run tests:

```bash
PYTHONPATH=. pytest
```

Run Ruff:

```bash
ruff check .
```

Run hassfest if installed:

```bash
hassfest
```

## Roadmap

- Add OSRM routing provider support.
- Add GraphHopper and OpenRouteService provider adapters.
- Add richer activity profiles for camping, hiking, and longer touring.
- Add calendar-aware availability.
- Add repairs when all destinations are disabled or unreachable.
- Add screenshots for setup, options, and dashboard examples.
