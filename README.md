# RideRadar

RideRadar recommends the best complete-trip weather destination for spontaneous motorcycle rides in Home Assistant.

## 10-Step Quickstart

1. Install RideRadar through HACS as a custom repository.
2. Restart Home Assistant.
3. Go to Settings > Devices & services.
4. Select Add integration.
5. Search for RideRadar.
6. Enter your start address or place name.
7. Confirm the resolved location shown by RideRadar.
8. Choose your maximum route distance, forecast days, preferred trip duration, and destination areas.
9. Add the dashboard view below.
10. Check RideRadar before you ride.

## Ready-To-Copy Dashboard View

Paste this into a manual dashboard view:

```yaml
title: RideRadar
path: rideradar
icon: mdi:motorbike
cards:
  - type: markdown
    title: RideRadar
    content: >
      ## {{ states('sensor.rideradar_best_trip_destination') }}

      Trip score: **{{ states('sensor.rideradar_best_trip_score') }}/100**

      Starts: **{{ states('sensor.rideradar_best_trip_start_day') }}**

      Duration: **{{ states('sensor.rideradar_trip_duration') }} days**

      {{ states('sensor.rideradar_best_summary') }}
  - type: entities
    title: RideRadar details
    entities:
      - entity: sensor.rideradar_best_trip_destination
      - entity: sensor.rideradar_best_trip_score
      - entity: sensor.rideradar_best_trip_start_day
      - entity: sensor.rideradar_trip_duration
      - entity: sensor.rideradar_best_summary
      - entity: sensor.rideradar_destination_count
```

## Screenshot Placeholders

- `docs/screenshots/config-start-location.png`: start location lookup.
- `docs/screenshots/config-confirm-location.png`: resolved location confirmation.
- `docs/screenshots/options-destinations.png`: destination enable/disable options.
- `docs/screenshots/dashboard.png`: example dashboard view.

## What RideRadar Does

RideRadar compares configured destination areas and recommends the best one for a complete short-notice trip. The first activity profile is `motorcycle`.

RideRadar uses Open-Meteo for weather forecasts and a routing abstraction for travel distance. The MVP does not use straight-line distance as the final route distance. It estimates route distance with a configurable detour factor until OSRM, GraphHopper, or OpenRouteService support is added.

RideRadar still scores each forecast day, but the primary ranking is `trip_score`: the best complete consecutive trip window for the configured duration. This prevents a destination with one excellent day and one poor day from outranking a steadier weekend.

RideRadar evaluates each day and trip window using:

- precipitation probability
- precipitation amount
- wind speed
- wind gusts
- temperature
- cloud cover
- weather code

Trip scoring adds:

- complete consecutive window analysis
- weather stability scoring
- non-linear penalties for heavy rain, strong wind, gusts, and storms
- natural-language trip explanations

## Installation Via HACS

1. Open HACS in Home Assistant.
2. Go to Integrations.
3. Open the three-dot menu and choose Custom repositories.
4. Add `https://github.com/zkhcj/rideradar` as the repository URL.
5. Select category Integration.
6. Install RideRadar.
7. Restart Home Assistant.

RideRadar requires Home Assistant 2024.12 or newer.

## Manual Installation

Copy `custom_components/rideradar` into your Home Assistant `custom_components` directory:

```text
config/
  custom_components/
    rideradar/
      __init__.py
      manifest.json
      ...
```

Restart Home Assistant after installing or updating the integration.

## Configuration

Add RideRadar from Settings > Devices & services > Add integration.

The setup flow asks for a start address or place name. Home Assistant config flows do not provide reliable dynamic autocomplete for custom integrations, so RideRadar uses a Home Assistant-native lookup flow instead:

1. Type an address or place name with at least 3 characters.
2. RideRadar geocodes it using the free Open-Meteo geocoding API.
3. If multiple matches are found, choose the correct one.
4. Confirm the resolved address, latitude, and longitude.
5. Continue with ride settings and destination selection.

Manual coordinate entry is available as an advanced path when geocoding cannot find the right location.

You can change these later from the integration options:

- start location
- maximum route distance in km
- forecast days
- preferred trip duration: 1 day, 2 days, 3 days, or custom
- custom trip duration, bounded by the available forecast range
- activity profile
- enabled destinations
- custom destinations
- fallback route detour factor

## Dashboard Examples

### Entities Card

```yaml
type: entities
title: RideRadar
entities:
  - entity: sensor.rideradar_best_destination
  - entity: sensor.rideradar_best_trip_destination
  - entity: sensor.rideradar_best_trip_score
  - entity: sensor.rideradar_best_trip_start_day
  - entity: sensor.rideradar_trip_duration
  - entity: sensor.rideradar_best_summary
  - entity: sensor.rideradar_destination_count
```

### Markdown Card

```yaml
type: markdown
title: RideRadar
content: >
  ## {{ states('sensor.rideradar_best_trip_destination') }}

  Trip score: **{{ states('sensor.rideradar_best_trip_score') }}/100**

  Best start: **{{ states('sensor.rideradar_best_trip_start_day') }}**

  Duration: **{{ states('sensor.rideradar_trip_duration') }} days**

  {{ states('sensor.rideradar_best_summary') }}
```

### Mushroom Template Card

```yaml
type: custom:mushroom-template-card
primary: "{{ states('sensor.rideradar_best_trip_destination') }}"
secondary: >
  {{ states('sensor.rideradar_best_trip_score') }}/100 from
  {{ states('sensor.rideradar_best_trip_start_day') }}
icon: mdi:motorbike
icon_color: >
  {% set score = states('sensor.rideradar_best_trip_score') | int(0) %}
  {% if score >= 80 %} green
  {% elif score >= 60 %} amber
  {% else %} red
  {% endif %}
tap_action:
  action: more-info
entity: sensor.rideradar_best_summary
```

## Destination Areas

Default destination areas:

- Sauerland
- Vogezen
- Dolomieten
- Harz
- Moezel
- Eifel
- Klein Zwitserland, Luxemburg
- Zwarte Woud
- Teutoburgerwoud

In the options flow you can:

- enable or disable default destinations
- add a custom destination with name, country/region, address/place, enabled state, and notes
- geocode custom destinations without entering coordinates manually
- remove custom destinations
- reset destinations to defaults

RideRadar stores destinations internally as structured data. Normal users do not need to edit JSON. An advanced import/export option exists only for deliberate structured data import.

## Trip-Based Output

RideRadar's dashboard recommendation is based on the best complete trip window, not the best isolated day.

Example destination attributes:

```yaml
trip_score: 87
best_trip_window:
  start_day: "2026-06-06"
  end_day: "2026-06-07"
  duration_days: 2
  trip_score: 87
  daily_scores:
    "2026-06-06": 91
    "2026-06-07": 84
weather_stability_score: 92
stability_explanation: "Weather consistency is high across the trip."
trip_score_breakdown:
  average_daily_score: 88
  worst_daily_score: 84
  weather_stability_score: 92
  bad_weather_penalty: 0
trip_explanation: "Scores 87/100 for a 2-day trip starting 2026-06-06. All trip days are expected to remain mostly dry. Temperatures stay between 18 C and 22 C. Winds remain light. Weather consistency is high."
```

A destination with daily scores like `100 / 100 / 30` is penalized because the weak day reduces the whole trip. A steadier `90 / 88 / 92` trip receives a higher stability score and should rank better for multi-day planning.

## Sensors

RideRadar creates these summary sensors:

- `sensor.rideradar_best_destination`
- `sensor.rideradar_best_score`
- `sensor.rideradar_best_day`
- `sensor.rideradar_best_trip_destination`
- `sensor.rideradar_best_trip_score`
- `sensor.rideradar_best_trip_start_day`
- `sensor.rideradar_trip_duration`
- `sensor.rideradar_best_summary`
- `sensor.rideradar_destination_count`

The legacy best destination, score, and day sensors now mirror the trip recommendation for dashboard compatibility.

It also creates one distance sensor per enabled destination. Each destination sensor includes attributes for `trip_score`, `best_trip_window`, `best_start_day`, `trip_duration`, `weather_stability_score`, `daily_scores`, `trip_score_breakdown`, `trip_explanation`, route distance, estimated travel time, weather values, reachability, explanation, and routing provider.

## Troubleshooting

- Start location not found: try a nearby town or use advanced manual coordinates.
- No best destination: enable at least one destination or increase maximum route distance.
- Forecast unavailable: Open-Meteo may be temporarily unavailable; RideRadar retries on the next update.
- Distances look approximate: the MVP uses fallback route estimates. Tune the detour factor in options.
- Missing destination sensor after editing destinations: reload the integration or remove stale disabled entities from Settings > Devices & services > Entities.
- HACS cannot find RideRadar: confirm the custom repository URL is `https://github.com/zkhcj/rideradar` and category is Integration.

## Development

Create a virtual environment and install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run Ruff:

```bash
ruff check .
```

Run hassfest if installed:

```bash
hassfest
```

A lightweight syntax check can be run without the full test environment:

```bash
python3 -m compileall custom_components tests
```

## Roadmap

- Add OSRM routing provider support.
- Add GraphHopper and OpenRouteService provider adapters.
- Add more activity profiles after defining their scoring thresholds.
- Add bounded concurrent forecast fetching for large destination lists.
- Add Home Assistant repairs when all destinations are disabled or unreachable.
- Add screenshots for the setup flow and dashboard.
