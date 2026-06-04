# RideRadar

RideRadar automatically analyzes weather, forecast stability, trip duration, route distance, travel effort, holidays, restriction risk, and riding opportunities to recommend motorcycle destinations that are actually worth riding.

RideRadar does not just tell you where the weather is good. It tells you where the ride is worth it.

![RideRadar dashboard hero](docs/images/rideradar-dashboard-hero.png)

![RideRadar destination roads](docs/images/rideradar-destination-collage.png)

## Why RideRadar?

Normally riders check Buienradar, Windy, Google Maps, ANWB, Google Traffic, holiday calendars, motorcycle forums, and local closure notices before deciding where to ride.

RideRadar combines those signals into one Home Assistant recommendation:

- where to ride
- when to ride
- why that destination is recommended
- whether traffic or holidays will hurt the ride
- whether motorcycle restrictions may affect the route
- whether the destination is worth the travel effort
- whether this week is good enough or a better forecast window is coming

## Ride Quality, Not Weather Alone

Motorcyclists do not care about weather in isolation. Perfect weather can still mean a poor ride if roads are full of holiday traffic, caravans, tourists, roadworks, or motorcycle restrictions.

RideRadar exposes a rider-facing `ride_quality_score` built from:

| Signal | Purpose |
| --- | --- |
| Weather score | Dry, calm, comfortable riding conditions |
| Stability score | Consistency across the complete trip |
| Temperature score | Comfortable temperatures for riding gear |
| Distance score | Whether the destination is within a sensible range |
| Holiday pressure score | Public holiday, school holiday, and long-weekend impact |
| Access score | Motorcycle restriction and closure risk |
| Trip efficiency score | How much useful riding time remains after approach and return travel |
| Road fun score | Destination suitability for enjoyable motorcycle roads |

Current holiday, access, traffic pressure, tourism pressure, and road-fun scoring is deterministic and offline-friendly. It uses destination profiles, public-holiday calculations, long-weekend detection, seasonality, and known regional motorcycle restriction risk. Future routing providers can replace these heuristics with live traffic and road closure data.

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
  {% set item = state_attr('sensor.rideradar_best_next_available_opportunity', 'opportunity') %}
  ## {{ states('sensor.rideradar_best_trip_destination') }}

  Ride quality: **{{ states('sensor.rideradar_best_ride_quality_score') }}/100**

  Best window: **{{ item.period if item else 'unknown' }}**

  Duration: **{{ state_attr('sensor.rideradar_trip_duration', 'duration_label') or states('sensor.rideradar_trip_duration') ~ ' days' }}**

  {{ states('sensor.rideradar_best_summary') }}
```

### Dashboard Duration Controls

Create any helpers you want to control from the dashboard, then place them above the RideRadar cards.

```yaml
type: entities
title: RideRadar controls
entities:
  - entity: input_select.rideradar_trip_duration
    name: Trip duration
  - entity: input_number.rideradar_trip_duration_days
    name: Custom or flexible maximum days
  - entity: input_number.rideradar_forecast_horizon_days
    name: Forecast horizon
  - entity: input_select.rideradar_preferred_start_day
    name: Preferred start day
  - entity: input_boolean.rideradar_weekend_only
    name: Weekend only
  - entity: input_select.rideradar_travel_strategy
    name: Travel strategy
  - entity: input_boolean.rideradar_trailer_available
    name: Trailer available
  - entity: input_number.rideradar_available_hours_per_day
    name: Available hours per day
  - entity: input_number.rideradar_max_approach_time_hours
    name: Max approach time
```

Supported `input_select.rideradar_trip_duration` values include `1 day`, `2 days`, `3 days`, `flexible`, and `custom`.
`input_number.rideradar_trip_duration_days` is read dynamically on every RideRadar refresh.
Supported `input_select.rideradar_travel_strategy` values include `Motorcycle Direct`, `Motorcycle Scenic Approach`, and `Trailer Transport`.
Trailer recommendations only appear when trailer support is enabled in configuration and `input_boolean.rideradar_trailer_available` is on.

### This Week: Top 3

```yaml
type: markdown
title: RideRadar this week
content: >
  {% set windows = state_attr('sensor.rideradar_top_week_opportunities', 'opportunities') or [] %}
  {% if windows %}
  {% for item in windows %}
  {{ loop.index }}. **{{ item.destination }}**
  {{ item.ride_quality_score }}/100
  {{ item.period }}

  {% endfor %}
  {% else %}
  No 70+ RideRadar opportunities start within the next 7 days.
  {% endif %}
```

### Best Later In Forecast

```yaml
type: markdown
title: RideRadar best upcoming
content: >
  {% set windows = state_attr('sensor.rideradar_top_month_opportunities', 'opportunities') or [] %}
  {% if windows %}
  {% for item in windows %}
  {{ loop.index }}. **{{ item.destination }}**
  {{ item.ride_quality_score }}/100
  {{ item.period }}

  {% endfor %}
  {% else %}
  No 70+ RideRadar opportunities are available in the configured forecast horizon.
  {% endif %}
```

### Top 5 Reachable Destinations

```yaml
type: markdown
title: RideRadar ranking
content: >
  {% set windows = state_attr('sensor.rideradar_best_opportunities', 'opportunities') or [] %}
  | Destination | Score | Efficiency | Distance | Access |
  | --- | ---: | ---: | ---: | --- |
  {% for item in windows[:5] %}
  | {{ item.destination }} | {{ item.ride_quality_score }}/100 | {{ item.trip_efficiency_score }}/100 | {{ item.route_distance_km | round(0) }} km | {{ item.access_status or 'Unknown' }} |
  {% endfor %}
```

### Top 5 Availability Windows

```yaml
type: markdown
title: RideRadar availability
content: >
  {% set windows = state_attr('sensor.rideradar_best_opportunities', 'opportunities') or [] %}
  {% for item in windows[:5] %}
  - **{{ item.destination }}** {{ item.period }}:
    {{ item.ride_quality_score }}/100, {{ item.verdict }}
  {% endfor %}
```

### Best Weekend Opportunity

```yaml
type: markdown
title: Best weekend ride
content: >
  {% set item = state_attr('sensor.rideradar_best_weekend_opportunity', 'opportunity') %}
  {% if item %}
  **{{ item.destination }}** {{ item.period }}

  Ride quality: **{{ item.ride_quality_score }}/100**

  Why: {{ item.recommendation_reason }}

  {{ item.explanation }}
  {% else %}
  No weekend opportunity is available in the current forecast horizon.
  {% endif %}
```

### Should I Ride Now Or Wait?

```yaml
type: markdown
title: Best future window
content: >
  {% set item = state_attr('sensor.rideradar_sauerland_best_future_window', 'score') %}
  {% set window = states.sensor.rideradar_sauerland_best_future_window %}
  Sauerland best upcoming score:
  **{{ states('sensor.rideradar_sauerland_best_future_window') }}/100**

  Window:
  **{{ state_attr('sensor.rideradar_sauerland_best_future_window', 'period') or 'unknown' }}**

  {{ state_attr('sensor.rideradar_sauerland_best_future_window', 'explanation') }}
```

### Destination Detail: Why This Score?

```yaml
type: markdown
title: Sauerland detail
content: >
  {% set e = 'sensor.rideradar_sauerland' %}
  {% set breakdown = state_attr(e, 'score_breakdown') or {} %}
  Ride quality: **{{ state_attr(e, 'ride_quality_score') }}/100**

  Weather: **{{ breakdown.weather_score | default('unknown') }}/100**

  Stability: **{{ breakdown.stability_score | default('unknown') }}/100**

  Temperature: **{{ breakdown.temperature_score | default('unknown') }}/100**

  Distance: **{{ breakdown.distance_score | default('unknown') }}/100**

  Holiday pressure: **{{ breakdown.holiday_pressure_score | default('unknown') }}/100**

  Access: **{{ breakdown.access_score | default('unknown') }}/100**

  Trip efficiency: **{{ breakdown.trip_efficiency_score | default('unknown') }}/100**

  Why: {{ state_attr(e, 'recommendation_reason') or 'No explanation available yet.' }}

  {{ state_attr(e, 'trip_explanation') }}

  Trade-offs:
  {% for tradeoff in state_attr(e, 'tradeoffs') or [] %}
  - {{ tradeoff }}
  {% endfor %}
```

### Optional Debug Card

Use this while testing RideRadar decisions. It shows the selected scenario, the best score, the top exclusion reason, and the score breakdown.

```yaml
type: markdown
title: RideRadar debug
content: >
  {% set summary = 'sensor.rideradar_best_summary' %}
  {% set duration = 'sensor.rideradar_trip_duration' %}
  {% set trace = state_attr(summary, 'best_decision_trace') or {} %}
  {% set inputs = trace.inputs or {} %}
  {% set breakdown = trace.scores or {} %}

  Travel strategy: **{{ inputs.travel_strategy | default('unknown') }}**

  Trailer available: **{{ inputs.trailer_available | default('unknown') }}**

  Duration: **{{ state_attr(duration, 'duration_label') or states(duration) ~ ' days' }}**

  Forecast horizon: **{{ inputs.forecast_horizon_days | default('unknown') }} days**

  Weekend only: **{{ inputs.weekend_only | default('unknown') }}**

  Preferred start day: **{{ inputs.preferred_start_day | default('any') }}**

  Best destination: **{{ states('sensor.rideradar_best_trip_destination') }}**

  Best score: **{{ states('sensor.rideradar_best_ride_quality_score') }}/100**

  Top exclusion reason: **{{ state_attr(summary, 'top_exclusion_reason') or 'none' }}**

  Scores:
  - Weather: {{ breakdown.weather_score | default('unknown') }}/100
  - Stability: {{ breakdown.stability_score | default('unknown') }}/100
  - Temperature: {{ breakdown.temperature_score | default('unknown') }}/100
  - Distance: {{ breakdown.distance_score | default('unknown') }}/100
  - Holiday pressure: {{ breakdown.holiday_pressure_score | default('unknown') }}/100
  - Access: {{ breakdown.access_score | default('unknown') }}/100
  - Trip efficiency: {{ breakdown.trip_efficiency_score | default('unknown') }}/100
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

Each window includes destination, start date, end date, readable period, duration, ride quality score, weather score, stability score, temperature score, distance score, holiday pressure score, access score, trip efficiency score, travel strategy, route distance, travel time, daily scores, verdict, explanation, recommendation reason, trade-offs, and score breakdown.

Summary sensors:

- `sensor.rideradar_best_opportunities`
- `sensor.rideradar_top_week_opportunities`
- `sensor.rideradar_top_month_opportunities`
- `sensor.rideradar_best_weekend_opportunity`
- `sensor.rideradar_best_weekday_opportunity`
- `sensor.rideradar_best_next_available_opportunity`
- `sensor.rideradar_best_ride_quality_score`

Destination sensors expose:

- `all_trip_windows`
- `best_trip_window`
- `next_good_window`
- `weekend_windows`
- `weekday_windows`
- `ride_quality_score`
- `ride_experience`
- `best_future_window`
- `daily_scores`
- `trip_score_breakdown`
- `trip_explanation`

Example opportunity attribute:

```yaml
destination: Sauerland
start_date: "2026-05-14"
end_date: "2026-05-15"
start_date_display: "Do 14-05-2026"
end_date_display: "Vr 15-05-2026"
period: "Do 14-05-2026 t/m Vr 15-05-2026"
ride_quality_score: 78
weather_score: 95
stability_score: 88
temperature_score: 84
distance_score: 80
trip_efficiency_score: 89
travel_strategy: "motorcycle_direct"
approach_time_hours: 1.5
return_time_hours: 1.5
total_available_time_hours: 16.0
estimated_destination_ride_time_hours: 13.0
destination_ride_time_ratio: 0.812
traffic_score: 62
traffic_level: "Medium"
tourism_pressure_score: 58
tourism_level: "High"
holiday_pressure_score: 55
motorcycle_access_score: 86
access_score: 86
access_status: "Open"
route_distance_km: 190
verdict: "Good window"
score_breakdown:
  weather_score: 95
  stability_score: 88
  temperature_score: 84
  distance_score: 80
  holiday_pressure_score: 55
  access_score: 86
  trip_efficiency_score: 89
  ride_quality_score: 78
recommendation_reason: "Sauerland wins because it has the best balance of weather and trip practicality..."
tradeoffs:
  - "Holiday pressure score is 55/100."
explanation: "Excellent weather, but Ascension Day creates long-weekend traffic pressure."
```

Each destination also gets a best-future-window sensor:

- `sensor.rideradar_sauerland_best_future_window`
- `sensor.rideradar_harz_best_future_window`
- `sensor.rideradar_eifel_best_future_window`

Attributes include `current_score`, `best_future_score`, `best_future_window`, `score`, `start_date`, `end_date`, `start_date_display`, `end_date_display`, `period`, `duration_days`, `days_until`, `score_breakdown`, `recommendation_reason`, `tradeoffs`, and `explanation`.

## Trip Efficiency And Travel Strategy

RideRadar scores whether the destination still makes sense after approach and return travel.

The selected travel strategy changes the ranking:

- `motorcycle_direct`: approach riding counts partly as enjoyable riding.
- `motorcycle_scenic`: approach time is longer, but more of it counts as ride enjoyment.
- `trailer`: approach time does not count as motorcycle enjoyment and is only allowed when trailer support is enabled and the runtime trailer helper is on.

Trip efficiency attributes include `approach_time_hours`, `return_time_hours`, `total_available_time_hours`, `estimated_destination_ride_time_hours`, `approach_enjoyment_factor`, `destination_ride_time_ratio`, and `trip_efficiency_score`.

Interpretation:

- 60%+ destination riding time: excellent
- 45-60%: good
- 30-45%: mediocre
- below 30%: poor recommendation

## GPX Roadmap

RideRadar v1.0 prepares the architecture for route-based destinations with `RouteAnalysis` and `RouteBasedDestination` models. Full GPX upload and parsing is intentionally deferred until the region-based planner is stable.

Planned GPX support will parse route points, calculate bounding boxes and midpoints, estimate route length, sample weather at multiple route points, and score the uploaded route as a selectable destination.

## Diagnostics And Explainability

RideRadar exposes compact decision traces in sensor attributes and fuller black-box data through Home Assistant diagnostics.

Useful attributes:

- `sensor.rideradar_best_summary`: `active_helpers`, `excluded_destinations`, `top_exclusion_reason`, `best_decision_trace`
- `sensor.rideradar_best_opportunities`: ranked opportunities with `decision_trace`
- destination sensors: `exclusion_reasons`, `score_breakdown`, `tradeoffs`, `recommendation_reason`

Download diagnostics from the Home Assistant device/integration diagnostics flow when filing issues. Diagnostics include active helper states, enabled destinations, exclusions, top week/month opportunities, best future windows, score breakdowns and decision traces. Start address and exact coordinates are redacted.

## Destination Imagery

RideRadar bundles local showcase imagery for the README so the project remains offline-friendly:

- `docs/images/rideradar-dashboard-hero.png`
- `docs/images/rideradar-destination-collage.png`
- `docs/images/destinations/mosel-vineyards.png`
- `docs/images/destinations/sauerland-roads.png`
- `docs/images/destinations/harz-forests.png`
- `docs/images/destinations/ardennes-valleys.png`
- `docs/images/destinations/vosges-roads.png`
- `docs/images/destinations/black-forest-roads.png`

The destination collage represents the type of riding environments RideRadar is built for: Mosel vineyards, Sauerland hills, Harz forests, Ardennes valleys, Vosges roads, and Black Forest curves.

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
- Destination excluded: inspect `sensor.rideradar_best_summary` attribute `excluded_destinations`.
- No weekend opportunity: increase the forecast horizon or wait for more forecast data.
- Distances look approximate: RideRadar currently uses a fallback route estimate with a configurable detour factor.
- Missing destination sensor after editing destinations: reload the integration or remove stale disabled entities from Settings > Devices & services > Entities.

## Known Limitations

- GPX upload is architecturally prepared but not implemented yet.
- Traffic prediction is not included in v1.0.
- Motorcycle restriction coverage is heuristic and may be incomplete.
- Forecast accuracy depends on Open-Meteo forecast data.
- Distance and travel time use the current routing provider or fallback estimate.

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
