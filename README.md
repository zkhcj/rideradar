# RideRadar

RideRadar automatically analyzes weather, forecast stability, trip duration, route distance, travel effort, holidays, restriction risk, and riding opportunities to recommend motorcycle destinations that are actually worth riding.

RideRadar does not just tell you where the weather is good. It tells you where the ride is worth it.

Icon assets: `custom_components/rideradar/icon.svg`, `custom_components/rideradar/logo.svg`, and `custom_components/rideradar/assets/icon.svg`. RideRadar also uses `mdi:motorbike`/`mdi:map-marker-star` as practical fallbacks in entities and dashboards for Home Assistant UI contexts that only support MDI icons.

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

Default `ride_quality_score` weights:

| Component | Weight |
| --- | ---: |
| `weather_score` | 40% |
| `stability_score` | 20% |
| `temperature_score` | 10% |
| `distance_score` | 10% |
| `holiday_pressure_score` | 10% |
| `access_score` | 5% |
| `trip_efficiency_score` | 5% |

Bad weather is gated. If `weather_score` is below 25, RideRadar caps the final score at 60. If `weather_score` is 0, the final score is capped at 50. If both weather and stability are 0, the final score is capped at 45. Below 70, the hero treats the result as the least compromised option instead of a strong recommendation.

Top week and top forecast cards only show opportunities with `ride_quality_score >= 70`. If none are available, the dashboard shows the best rejected candidate and the main rejection reason.

Current holiday, access, traffic pressure, tourism pressure, and road-fun scoring is deterministic and offline-friendly. It uses destination profiles, public-holiday calculations, long-weekend detection, seasonality, and known regional motorcycle restriction risk. Future routing providers can replace these heuristics with live traffic and road closure data.

## 10-Step Quickstart

1. Install RideRadar through HACS as a custom repository.
2. Restart Home Assistant.
3. Go to Settings > Devices & services > Add integration.
4. Configure your start location by searching for a place or address, for example `Hardenberg, Nederland`.
5. Choose a default trip duration.
6. Choose the forecast horizon days RideRadar should evaluate.
7. Configure your maximum route distance.
8. Choose the destination areas RideRadar should compare.
9. Add the default dashboard below.
10. Check RideRadar before planning the ride.

## Ready-To-Copy Dashboard Examples

## Default Dashboard

RideRadar automatically creates its own dashboard control entities. You do not need to create `input_select`, `input_number`, or `input_boolean` helpers manually.

Paste this as a complete Lovelace view:

```yaml
title: RideRadar
path: rideradar
icon: mdi:motorbike
type: sections
max_columns: 3
sections:
  - type: grid
    cards:
      - type: markdown
        title: Status
        content: |
          {% set eval = state_attr('sensor.rideradar_evaluation_summary', 'evaluation_summary') or {} %}
          {% set eval = eval if eval is mapping else {} %}
          {% set status = states('sensor.rideradar_weather_status') %}
          {% set provider = state_attr('sensor.rideradar_weather_status', 'provider_used') or state_attr('sensor.rideradar_weather_status', 'primary_provider') or 'onbekend' %}
          {% set location = state_attr('sensor.rideradar_weather_status', 'forecast_location_name') or 'de bestemming' %}
          {% set fallback = state_attr('sensor.rideradar_weather_status', 'fallback_provider_used') %}
          {% set age = state_attr('sensor.rideradar_weather_status', 'forecast_cache_age_hours') %}
          {% set updated = state_attr('sensor.rideradar_weather_status', 'last_successful_update') %}
          {% set next = state_attr('sensor.rideradar_weather_status', 'next_scheduled_refresh') %}
          {% set calls = state_attr('sensor.rideradar_weather_status', 'calls_used_today') or {} %}
          {% set calls = calls if calls is mapping else {} %}
          {% set provider_label = provider | replace('_', '-') | title %}
          {% set age_min = (age | float(0) * 60) | round(0) %}
          {% set total = eval.get('total_candidates', 0) %}
          ## RideRadar {{ 'werkt' if total | int(0) > 0 else 'wacht op data' }}

          {% if status == 'ok' %}
          Weerdata voor **{{ location }}** is vers via **{{ provider_label }}**.
          {% elif status == 'partial' %}
          Weerdata voor **{{ location }}** is gedeeltelijk beschikbaar via **{{ provider_label }}**. Het advies is beperkt.
          {% elif status == 'stale' %}
          RideRadar gebruikt de laatst bekende weersverwachting voor **{{ location }}**. Het advies is beperkt.
          {% else %}
          Geen bruikbare weerdata beschikbaar voor **{{ location }}**. RideRadar toont alleen kandidaten zonder definitief weeradvies.
          {% endif %}

          {% if fallback %}
          Fallback actief: **{{ fallback | replace('_', '-') | title }}**.
          {% endif %}

          **Laatste update:** {{ relative_time(as_datetime(updated)) ~ ' geleden' if updated not in ['unknown', 'unavailable', none, ''] else 'Nog niet beschikbaar' }}

          **Cacheleeftijd:** {{ age_min | int }} minuten

          **Volgende update:** {{ 'over ' ~ relative_time(as_datetime(next)) if next not in ['unknown', 'unavailable', none, ''] else 'Nog niet gepland' }}

          {% for name, count in calls.items() %}
          **{{ name | replace('_', '-') | title }}-aanroepen vandaag:** {{ count }}
          {% else %}
          **Aanroepen vandaag:** niet beschikbaar
          {% endfor %}
      - type: markdown
        title: Advies
        content: |
          {% set candidate = state_attr('sensor.rideradar_evaluation_summary', 'advice_candidate') or {} %}
          {% set candidate = candidate if candidate is mapping else {} %}
          {% set result = candidate.get('result') %}
          {% if result == 'recommended' %}
          ## Aanbevolen rit: {{ candidate.get('destination', 'n.b.') }}
          {% elif result == 'eligible' %}
          ## Geen primaire match, wel geschikt alternatief
          {{ candidate.get('destination', 'n.b.') }} voldoet aan de harde eisen, maar valt buiten de actieve hoofdselectie of rangschikt lager.
          {% elif result == 'compromise' %}
          ## Beste compromis: {{ candidate.get('destination', 'n.b.') }}
          RideRadar raadt dit niet actief aan, maar dit is de minst slechte bruikbare optie.
          {% else %}
          ## Geen bruikbaar advies
          {{ candidate.get('supporting_evidence', 'Geen kandidaat kon volledig worden beoordeeld.') }}
          {% endif %}

          **Score:** {{ candidate.get('total_score', 'n.b.') }}/100

          **Modus:** {{ candidate.get('mode_label', 'n.b.') }}

          **Periode:** {{ candidate.get('period', 'Nog niet beschikbaar') }}

          **Duur:** {{ candidate.get('duration_days', 'n.b.') }} dagen

          **Datakwaliteit:** {{ candidate.get('weather_status', 'onbekend') }}

          **Waarom:** {{ candidate.get('supporting_evidence', 'Geen onderbouwing beschikbaar.') }}

      - type: markdown
        title: Afwijzingssamenvatting
        content: |
          {% set eval = state_attr('sensor.rideradar_evaluation_summary', 'evaluation_summary') or {} %}
          {% set eval = eval if eval is mapping else {} %}
          {% set reason_counts = eval.get('rejection_reason_counts', {}) if eval.get('rejection_reason_counts', {}) is mapping else {} %}
          {% set reason_labels = eval.get('rejection_reason_labels', {}) if eval.get('rejection_reason_labels', {}) is mapping else {} %}
          **{{ eval.get('total_candidates', 0) }}** kandidaten beoordeeld

          **{{ eval.get('recommended', 0) }}** aanbevolen · **{{ eval.get('eligible', 0) }}** geschikt · **{{ eval.get('compromises', 0) }}** compromis · **{{ eval.get('rejected', 0) }}** afgewezen · **{{ eval.get('unavailable', 0) }}** niet beoordeelbaar

          {% if reason_counts %}
          Belangrijkste redenen:
          {% for reason, count in reason_counts.items() %}
          - {{ count }} × {{ reason_labels.get(reason, reason) }}
          {% endfor %}
          {% else %}
          Geen afwijzingen.
          {% endif %}
  - type: grid
    cards:
      - type: markdown
        title: Beste alternatieven
        content: |
          {% set groups = [
            ('Deze week', 'direct', 'sensor.rideradar_top_week_direct_opportunities'),
            ('Deze week', 'binnendoor', 'sensor.rideradar_top_week_scenic_opportunities'),
            ('Deze week', 'aanhanger', 'sensor.rideradar_top_week_trailer_opportunities'),
            ('Deze maand', 'direct', 'sensor.rideradar_top_forecast_direct_opportunities'),
            ('Deze maand', 'binnendoor', 'sensor.rideradar_top_forecast_scenic_opportunities'),
            ('Deze maand', 'aanhanger', 'sensor.rideradar_top_forecast_trailer_opportunities')
          ] %}
          {% for period, mode, entity in groups %}
          {% set options = state_attr(entity, 'opportunities') or [] %}
          {% set rejected = state_attr(entity, 'best_rejected_candidate') %}
          **{{ period }} · {{ mode }}**
          {% if options %}
          {{ options | count }} geldige optie{{ 's' if options | count != 1 else '' }} gevonden.
          {% for item in options[:3] %}
          {% set item = item if item is mapping else {} %}
          {{ loop.index }}. {{ item.get('destination', 'n.b.') }} · {{ item.get('ride_quality_score', 'n.b.') }}/100 · {{ item.get('period', 'Nog niet beschikbaar') }} · {{ item.get('duration_days', 'n.b.') }} dagen
          {% endfor %}
          {% elif rejected is mapping %}
          Geen geldige opties. Beste compromis: {{ rejected.get('destination', 'n.b.') }} · {{ rejected.get('ride_quality_score', 'n.b.') }}/100. Reden: {{ rejected.get('main_tradeoff', 'Score blijft onder de adviesdrempel.') }}
          {% else %}
          Geen geldige opties.
          {% endif %}

          {% endfor %}
```

If the native control entities are missing, reload the RideRadar integration from Settings > Devices & services. A full Home Assistant restart should not be required during normal configuration changes.

Screenshot placeholder: add your dashboard screenshot at `docs/images/rideradar-dashboard-hero.png` after importing the view above.

## Optional: RideRadar Settings & Debug View

The default dashboard is intentionally rider-first. Use this optional view when you want controls and diagnostics on a separate page. RideRadar creates these controls automatically; legacy `input_*` helpers are only read as fallback for older dashboards.

```yaml
title: RideRadar Settings & Debug
path: rideradar-debug
icon: mdi:tune-variant
type: sections
max_columns: 2
sections:
  - type: grid
    cards:
      - type: entities
        title: Scenario
        entities:
          - entity: select.rideradar_trip_duration
            name: Ritduur
          - entity: number.rideradar_trip_duration_days
            name: Aangepaste/flexibele maximumduur
          - entity: number.rideradar_forecast_horizon_days
            name: Weersverwachtingsperiode
          - entity: select.rideradar_preferred_start_day
            name: Voorkeursdag
          - entity: switch.rideradar_weekend_only
            name: Alleen weekend
          - entity: select.rideradar_travel_strategy
            name: Reisstrategie
          - entity: switch.rideradar_trailer_available
            name: Aanhanger vandaag beschikbaar
          - entity: number.rideradar_available_hours_per_day
            name: Beschikbare uren per dag
          - entity: number.rideradar_max_approach_time_hours
            name: Maximale aanrijtijd
      - type: markdown
        title: Debug trace
        content: |
          {% set summary = 'sensor.rideradar_best_summary' %}
          {% set duration = 'sensor.rideradar_trip_duration' %}
          {% set trace = state_attr(summary, 'best_decision_trace') or {} %}
          {% set inputs = trace.get('inputs', {}) if trace is mapping else {} %}
          {% set result = trace.get('result', {}) if trace is mapping else {} %}
          {% set breakdown = trace.get('scores', {}) if trace is mapping else {} %}
          {% set weights = trace.get('weights', {}) if trace is mapping else {} %}
          {% set caps = trace.get('caps', []) if trace is mapping else [] %}

          Strategie: **{{ inputs.get('travel_strategy', 'onbekend') }}**

          Aanhanger beschikbaar: **{{ inputs.get('trailer_available', 'onbekend') }}**

          Duur: **{{ state_attr(duration, 'duration_label') or states(duration) ~ ' dagen' }}**

          Weersverwachtingsperiode: **{{ inputs.get('forecast_horizon_days', 'onbekend') }} dagen**

          Alleen weekend: **{{ inputs.get('weekend_only', 'onbekend') }}**

          Voorkeursdag: **{{ inputs.get('preferred_start_day', 'any') }}**

          Beste bestemming: **{{ states('sensor.rideradar_best_trip_destination') }}**

          Beste score: **{{ states('sensor.rideradar_best_ride_quality_score') }}/100**

          Adviesstatus: **{{ result.get('verdict', 'onbekend') }}**

          Belangrijkste uitsluiting: **{{ state_attr(summary, 'top_exclusion_reason') or 'geen' }}**

          Scores:
          - Weer: {{ breakdown.get('weather_score', 'onbekend') }}/100
          - Stabiliteit: {{ breakdown.get('stability_score', 'onbekend') }}/100
          - Temperatuur: {{ breakdown.get('temperature_score', 'onbekend') }}/100
          - Afstand: {{ breakdown.get('distance_score', 'onbekend') }}/100
          - Vakantiedruk: {{ breakdown.get('holiday_pressure_score', 'onbekend') }}/100
          - Toegang: {{ breakdown.get('access_score', 'onbekend') }}/100
          - Ritefficiëntie: {{ breakdown.get('trip_efficiency_score', 'onbekend') }}/100

          Gewichten:
          - Weer: {{ weights.get('weather_score', 'onbekend') }}%
          - Stabiliteit: {{ weights.get('stability_score', 'onbekend') }}%
          - Temperatuur: {{ weights.get('temperature_score', 'onbekend') }}%
          - Afstand: {{ weights.get('distance_score', 'onbekend') }}%
          - Vakantiedruk: {{ weights.get('holiday_pressure_score', 'onbekend') }}%
          - Toegang: {{ weights.get('access_score', 'onbekend') }}%
          - Ritefficiëntie: {{ weights.get('trip_efficiency_score', 'onbekend') }}%

          Caps:
          {% for cap in caps %}
          {% set cap = cap if cap is mapping else {} %}
          - {{ cap.get('reason', 'onbekend') }}: max {{ cap.get('cap', 'onbekend') }}
          {% else %}
          - geen
          {% endfor %}
  - type: grid
    cards:
      - type: markdown
        title: Evaluatietabel
        content: |
          {% set rows = state_attr('sensor.rideradar_evaluation_summary', 'evaluated_candidates') or [] %}
          | Status | Bestemming | Modus | Periode | Dagen | Score | Weer | Reden | Bewijs | Provider | Forecastlocatie | Cache | Ontbrekend |
          |---|---|---|---|---:|---:|---:|---|---|---|---|---:|---|
          {% for item in rows %}
          {% set item = item if item is mapping else {} %}
          | {{ item.get('eligibility_result', 'n.b.') }} | {{ item.get('destination', 'n.b.') }} | {{ item.get('mode_label', 'n.v.t.') }} | {{ item.get('period', 'n.b.') }} | {{ item.get('duration_days', 'n.b.') }} | {{ item.get('total_score', 'n.b.') }} | {{ item.get('weather_score', 'n.b.') }} | {{ item.get('primary_reason', 'n.b.') }} | {{ item.get('supporting_evidence', 'Geen bewijs beschikbaar.') }} | {{ item.get('weather_provider', 'n.b.') }} | {{ item.get('forecast_location', 'n.b.') }} | {{ item.get('cache_age_minutes', 'n.b.') }} min | {{ item.get('missing_data', []) | join(', ') if item.get('missing_data') else '-' }} |
          {% else %}
          | Geen kandidaten | - | - | - | - | - | - | Wachten op data | RideRadar heeft nog geen evaluatie gemaakt. | - | - | - | - |
          {% endfor %}
```

Supported `select.rideradar_trip_duration` values include `1 day`, `2 days`, `3 days`, `flexible`, and `custom`.
Supported `select.rideradar_travel_strategy` values include `Motorcycle Direct`, `Motorcycle Scenic Approach`, and `Trailer Transport`.
Trailer recommendations only appear when trailer transport mode is enabled in configuration and `switch.rideradar_trailer_available` is on. Configuration support means "this rider can use trailer transport"; runtime availability means "the trailer is available today".

## All Options Dashboard

The default dashboard stays rider-first. For power users, RideRadar also exposes `sensor.rideradar_all_opportunities`.

This sensor compares realistic opportunities side by side across multiple durations and strategies. By default the public table attribute contains candidates scoring 60+ and is capped to a reasonable size. It evaluates 2-day through 4-day windows when the forecast horizon allows it, and extends higher when the configured/custom maximum trip duration is higher. Direct and scenic strategies are shown side by side. Trailer opportunities are hidden unless trailer transport support is enabled and `switch.rideradar_trailer_available` is on; if trailer is unavailable, exclusion/debug data still explains why trailer options are absent.

For sorting/filtering, install `custom:flex-table-card` through HACS. Its documentation describes selecting entity attributes as columns and expanding list attributes into rows, which is how the `opportunities` attribute is used here: https://github.com/custom-cards/flex-table-card

```yaml
title: RideRadar All Options
path: rideradar-all-options
icon: mdi:table-search
type: sections
max_columns: 1
sections:
  - type: grid
    cards:
      - type: entities
        title: Planning filters
        entities:
          - entity: number.rideradar_trip_duration_days
            name: Max dagen voor tabel
          - entity: number.rideradar_forecast_horizon_days
            name: Weersverwachtingsperiode
          - entity: switch.rideradar_weekend_only
            name: Alleen weekend
          - entity: select.rideradar_preferred_start_day
            name: Gewenste startdag
          - entity: switch.rideradar_trailer_available
            name: Aanhanger vandaag beschikbaar
      - type: custom:flex-table-card
        title: Alle RideRadar opties
        entities:
          include:
            - sensor.rideradar_all_opportunities
        sort_by:
          - score-
        columns:
          - name: Score
            data: opportunities.score
          - name: Bestemming
            data: opportunities.destination
          - name: Strategie
            data: opportunities.strategy_label
          - name: Dagen
            data: opportunities.duration_days
          - name: Periode
            data: opportunities.period
          - name: Weer
            data: opportunities.weather_score
          - name: Stabiliteit
            data: opportunities.stability_score
          - name: Efficiëntie
            data: opportunities.trip_efficiency_score
          - name: Afstand
            data: opportunities.distance_km
          - name: Aanrijtijd
            data: opportunities.approach_time_hours
          - name: Reden
            data: opportunities.main_reason
      - type: markdown
        title: Tabelstatus
        content: |
          Zichtbare opties: **{{ states('sensor.rideradar_all_opportunities') }}**

          Alle kandidaten: **{{ state_attr('sensor.rideradar_all_opportunities', 'candidate_count') | default(0) }}**

          Verborgen onder score 60 of boven attribute-limit: **{{ state_attr('sensor.rideradar_all_opportunities', 'hidden_below_threshold_count') | default(0) }}**
```

If `custom:flex-table-card` is not installed, use this fallback markdown table. It is readable and copy-paste safe, but Home Assistant markdown tables are not truly sortable or filterable.

```yaml
type: markdown
title: Alle RideRadar opties
content: |
  {% set rows = state_attr('sensor.rideradar_all_opportunities', 'opportunities') or [] %}
  | Score | Bestemming | Strategie | Dagen | Periode | Weer | Stabiliteit | Efficiëntie | Afstand | Aanrijtijd |
  |---:|---|---|---:|---|---:|---:|---:|---:|---:|
  {% for item in rows %}
  {% set item = item if item is mapping else {} %}
  | {{ item.get('score', 'n.b.') }} | {{ item.get('destination', 'n.b.') }} | {{ item.get('strategy_label', 'n.b.') }} | {{ item.get('duration_days', 'n.b.') }} | {{ item.get('period', 'n.b.') }} | {{ item.get('weather_score', 'n.b.') }} | {{ item.get('stability_score', 'n.b.') }} | {{ item.get('trip_efficiency_score', 'n.b.') }} | {{ item.get('distance_km', 0) | round(0) }} km | {{ item.get('approach_time_hours', 0) | round(1) }} u |
  {% else %}
  | - | Nog geen opties beschikbaar | - | - | RideRadar wacht op forecast-data of alle kandidaten zijn onder de zichtbare drempel. | - | - | - | - | - |
  {% endfor %}
```

## Availability Windows

RideRadar evaluates every complete trip window inside the forecast horizon.

Example with a 2-day trip duration and 8-day forecast horizon:

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
- `sensor.rideradar_top_week_direct_opportunities`
- `sensor.rideradar_top_week_scenic_opportunities`
- `sensor.rideradar_top_week_trailer_opportunities` when trailer support is enabled
- `sensor.rideradar_top_forecast_direct_opportunities`
- `sensor.rideradar_top_forecast_scenic_opportunities`
- `sensor.rideradar_top_forecast_trailer_opportunities` when trailer support is enabled
- `sensor.rideradar_top_month_opportunities` legacy forecast-period summary
- `sensor.rideradar_best_weekend_opportunity`
- `sensor.rideradar_best_weekday_opportunity`
- `sensor.rideradar_best_next_available_opportunity`
- `sensor.rideradar_best_ride_quality_score`
- `sensor.rideradar_weather_status`

## Weather Cache And Provider Budget

RideRadar dashboard cards never call weather providers directly. Lovelace only renders the latest calculated coordinator state.

Weather forecasts are fetched for the destination or ride area coordinates, not for the Home Assistant home location. If RideRadar evaluates Sauerland, it requests Sauerland weather. If it evaluates Harz, it requests Harz weather. One destination forecast is reused across direct, binnendoor/scenic, aanhanger, week, month, advice, rejected-candidate and all-options calculations, but it is never reused for a different destination.

The default coordinate provider is Open-Meteo. Open-Meteo does not require a user API key for the default non-commercial setup. RideRadar does not ship a shared maintainer-owned API key and does not route traffic through a central RideRadar weather backend or proxy.

OpenWeather support, if added later, must use the user's own API key or the user's own Home Assistant OpenWeather integration. RideRadar must never document or embed a maintainer-owned OpenWeather key.

Home Assistant weather entities are only safe when they preserve destination correctness:

- use an explicit destination-to-weather-entity mapping, for example `Sauerland -> weather.sauerland`
- use a local/home weather entity only for local rides around home
- do not use `weather.forecast_home` for Sauerland, Harz or another remote destination unless you explicitly mapped that entity to that destination

Advanced destination weather mapping can be supplied through the `weather_entity_map` option data:

```yaml
weather_entity_map:
  Sauerland: weather.sauerland
  Harz: weather.harz
```

If no explicit mapping exists, RideRadar falls back to the coordinate-based provider and never silently applies one generic home weather entity to every destination.

Weather forecasts are cached per provider, rounded destination latitude, rounded destination longitude, forecast horizon and forecast granularity. The default refresh interval is 4 hours. A forecast that is 0-4 hours old is treated as fresh. A forecast that is 4-24 hours old is treated as stale: scoring can still use it, but the dashboard shows that the advice is limited. Forecast data older than 24 hours is considered unavailable and is not converted into a fake bad-weather score.

Important defaults:

| Setting | Default |
| --- | ---: |
| Weather refresh interval | 4 hours |
| Fresh forecast max age | 4 hours |
| Stale forecast fallback max age | 24 hours |
| Max provider calls per hour | 60 |
| Max provider calls per day | 500 |
| Provider backoff after rate limit | 60 minutes |

One destination forecast is reused for direct, binnendoor/scenic, aanhanger, week, month, advice, rejected-candidate and all-options calculations. Changing dashboard controls recalculates RideRadar from cached forecasts unless the weather cache is stale enough for a scheduled refresh.

Provider state is exposed through `sensor.rideradar_weather_status`. It shows the primary provider, provider used, forecast location, forecast coordinates, fallback provider when one is used, last successful update, cache age, calls used today, provider states and next scheduled refresh.

Manual refresh is available through:

```yaml
service: rideradar.refresh_weather
data:
  force: false
```

With `force: false`, RideRadar still respects cache freshness and provider budgets. Use `force: true` only for manual testing because it bypasses normal cache and budget protection.

RideRadar v1 ships with the Open-Meteo coordinate provider client. The coordinator cache layer supports multiple provider clients internally so fallback providers can be added without changing dashboard behavior. If a provider is rate-limited or unavailable, RideRadar uses a configured fallback provider when present, otherwise it keeps using the best available cached forecast for the same destination coordinates within the stale fallback window.

Rejected destinations include structured evidence such as destination, reason, details, forecast location, provider used, weather status and cache age. Bad-weather rejection is only valid when real destination weather data exists. Missing weather data is shown as unavailable, not as `weather_score: 0`.

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

Download diagnostics from the Home Assistant device/integration diagnostics flow when filing issues. Diagnostics include active helper states, enabled destinations, exclusions, top week and forecast opportunities, best future windows, score breakdowns and decision traces. Start address and exact coordinates are redacted.

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
3. RideRadar shows readable candidate locations in a dropdown.
4. Select the correct result. Selecting the result is the confirmation.
5. If the result is wrong, go back and search again with a more specific place or address.

If no location is found, RideRadar keeps you in the flow and asks you to try a larger nearby town, add the country name, or use a more specific address. Invalid or partial geocoding results are not saved.

The options flow shows one normal settings screen with:

- current configured start location
- current resolved coordinates
- editable start address/place
- maximum route distance
- default trip duration
- forecast horizon days
- destination enablement
- enabled destinations

Trailer transport support is an advanced option. Dynamic scenario controls such as custom trip duration, flexible duration, weekend-only, preferred start day, travel strategy, trailer availability today, available hours per day, and maximum approach time are native dashboard entities. Coordinates are internal resolved data. Raw destination JSON is not part of the normal setup or options experience; import/export remains an advanced maintenance path only.

## Troubleshooting

- Start location not found: try a nearby town, a larger city, or add the country name.
- Wrong location found: choose a different candidate or search with more context.
- No best destination: enable at least one destination or increase maximum route distance.
- Destination excluded: inspect `sensor.rideradar_best_summary` attribute `excluded_destinations`.
- No weekend opportunity: increase the forecast horizon or wait for more forecast data.
- Forecast provider unavailable: Open-Meteo may occasionally return temporary errors such as HTTP 502. RideRadar keeps the dashboard readable and retries automatically.
- Distances look approximate: RideRadar currently uses a fallback route estimate with a configurable detour factor.
- Missing destination sensor after editing destinations: reload the integration or remove stale disabled entities from Settings > Devices & services > Entities.

## Known Limitations

- GPX upload is architecturally prepared but not implemented yet.
- Traffic prediction is not included in v1.0.
- Motorcycle restriction coverage is heuristic and may be incomplete.
- Forecast accuracy depends on Open-Meteo forecast data.
- If Open-Meteo returns temporary errors, RideRadar retries automatically and keeps previous valid data where Home Assistant has it.
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
