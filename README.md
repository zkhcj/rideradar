# RideRadar

RideRadar automatically analyzes weather, forecast stability, trip duration, route distance, travel effort, holidays, restriction risk, and riding opportunities to recommend motorcycle destinations that are actually worth riding.

RideRadar does not just tell you where the weather is good. It tells you where the ride is worth it.

Icon asset: `custom_components/rideradar/assets/icon.svg`. Home Assistant does not load arbitrary custom integration icons in every UI context, so RideRadar uses `mdi:motorbike`/`mdi:map-marker-star` as practical fallbacks in entities and dashboards.

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
        title: Advies
        content: |
          {% set best = states('sensor.rideradar_best_trip_destination') %}
          {% set score_raw = states('sensor.rideradar_best_ride_quality_score') %}
          {% set score = score_raw | int(0) %}
          {% set summary = states('sensor.rideradar_best_summary') %}
          {% set opportunity = state_attr('sensor.rideradar_best_next_available_opportunity', 'opportunity') or {} %}
          {% set opportunity = opportunity if opportunity is mapping else {} %}
          {% set period = opportunity.get('period', 'Nog niet beschikbaar') %}
          {% set duration = opportunity.get('duration_days', state_attr('sensor.rideradar_trip_duration', 'duration_label') | default('Nog niet beschikbaar')) %}
          {% set reason = opportunity.get('recommendation_reason', 'Nog geen aanbevelingsreden beschikbaar.') %}
          {% if score < 70 %}
          ## Geen sterke rit gevonden
          **Minst slechte optie:** {{ best if best not in ['unknown', 'unavailable', none, ''] else 'Nog niet beschikbaar' }}
          {% else %}
          ## {{ best if best not in ['unknown', 'unavailable', none, ''] else 'Nog niet beschikbaar' }}
          **Aanbevolen rit**
          {% endif %}

          **Score:** {{ score_raw if score_raw not in ['unknown', 'unavailable', none, ''] else 'Nog niet beschikbaar' }}/100

          **Periode:** {{ period if period not in ['unknown', 'unavailable', none, ''] else 'Nog niet beschikbaar' }}

          **Duur:** {{ duration if duration not in ['unknown', 'unavailable', none, ''] else 'Nog niet beschikbaar' }}

          {% if score < 70 %}
          RideRadar raadt deze rit niet actief aan. Dit is alleen de beste optie binnen de huidige instellingen.
          {% endif %}

          {{ summary if summary not in ['unknown', 'unavailable', none, ''] else 'Nog geen samenvatting beschikbaar. Controleer of RideRadar al forecast-data heeft opgehaald.' }}

          {{ reason }}
      - type: markdown
        title: Weekendrit
        content: |
          {% set item = state_attr('sensor.rideradar_best_weekend_opportunity', 'opportunity') %}
          {% set item = item if item is mapping else {} %}
          {% if item %}
          **{{ item.get('destination', 'Nog niet beschikbaar') }}** - {{ item.get('ride_quality_score', 'n.b.') }}/100

          {{ item.get('period', 'Nog niet beschikbaar') }}

          {{ item.get('verdict', 'n.b.') | replace('Excellent', 'Uitstekend') | replace('Very good', 'Zeer goed') | replace('Good', 'Goed') | replace('Mediocre', 'Matig') | replace('Poor', 'Slecht') | replace('Not recommended', 'Niet aanbevolen') }}

          {{ item.get('recommendation_reason', 'Nog geen aanbevelingsreden beschikbaar.') }}
          {% else %}
          Geen aparte weekendkans beschikbaar binnen de huidige instellingen.
          {% endif %}
      - type: markdown
        title: Ranking
        content: |
          {% set windows = state_attr('sensor.rideradar_best_opportunities', 'opportunities') or [] %}
          | # | Bestemming | Score | Weer | Efficiëntie | Periode |
          |---:|---|---:|---:|---:|---|
          {% for item in windows %}
          {% set item = item if item is mapping else {} %}
          | {{ loop.index }} | {{ item.get('destination', 'n.b.') }} | {{ item.get('ride_quality_score', 'n.b.') }}/100 | {{ item.get('weather_score', 'n.b.') }}/100 | {{ item.get('trip_efficiency_score', 'n.b.') }}/100 | {{ item.get('period', 'Nog niet beschikbaar') }} |
          {% endfor %}

  - type: grid
    cards:
      - type: markdown
        title: Top 3 deze week
        content: |
          {% set windows = state_attr('sensor.rideradar_top_week_opportunities', 'opportunities') or [] %}
          {% set rejected = state_attr('sensor.rideradar_top_week_opportunities', 'best_below_threshold') %}
          {% set reason_labels = {
            'below_minimum_score': 'Score onder minimum',
            'weather_too_poor': 'Weer te slecht',
            'stability_too_low': 'Stabiliteit te laag',
            'weekend_only_filter': 'Valt buiten weekendfilter',
            'preferred_start_day_filter': 'Valt buiten voorkeursdag',
            'trailer_unavailable': 'Aanhanger niet beschikbaar',
            'trailer_required_but_unavailable': 'Aanhanger nodig, maar niet beschikbaar',
            'insufficient_destination_ride_time': 'Te weinig rijtijd op bestemming',
            'approach_time_too_high': 'Aanrijtijd te hoog',
            'no_complete_window': 'Geen volledig weervenster',
            'disabled_destination': 'Bestemming uitgeschakeld',
            'too_far': 'Buiten ingestelde afstand'
          } %}
          {% if windows %}
          {% for item in windows %}
          {% set item = item if item is mapping else {} %}
          {{ loop.index }}. **{{ item.get('destination', 'n.b.') }}** - {{ item.get('ride_quality_score', 'n.b.') }}/100

          {{ item.get('period', 'Nog niet beschikbaar') }}

          {% endfor %}
          {% else %}
          Geen kansen boven 70 gevonden.

          {% if rejected %}
          {% set rejected = rejected if rejected is mapping else {} %}
          Beste optie deze week: **{{ rejected.get('destination', 'Nog niet beschikbaar') }} {{ rejected.get('ride_quality_score', 'n.b.') }}/100**

          {{ rejected.get('period', 'Nog niet beschikbaar') }}

          {% set blocking = rejected.get('main_blocking_factor', rejected.get('reason', 'onbekend')) %}
          Belangrijkste reden: {{ reason_labels.get(blocking, blocking) }}
          {% else %}
          Er zijn nog geen kandidaten binnen de huidige instellingen.
          {% endif %}
          {% endif %}
      - type: markdown
        title: Volgende kans
        content: |
          {% set item = state_attr('sensor.rideradar_best_next_available_opportunity', 'opportunity') %}
          {% set item = item if item is mapping else {} %}
          {% if item %}
          **{{ item.get('destination', 'Nog niet beschikbaar') }}** - {{ item.get('ride_quality_score', 'n.b.') }}/100

          {{ item.get('period', 'Nog niet beschikbaar') }}

          Oordeel: {{ item.get('verdict', 'n.b.') | replace('Excellent', 'Uitstekend') | replace('Very good', 'Zeer goed') | replace('Good', 'Goed') | replace('Mediocre', 'Matig') | replace('Poor', 'Slecht') | replace('Not recommended', 'Niet aanbevolen') }}
          {% else %}
          Geen bruikbare kans beschikbaar.
          {% endif %}
      - type: markdown
        title: Score-opbouw
        content: |
          {% set trace = state_attr('sensor.rideradar_best_summary', 'best_decision_trace') or {} %}
          {% set scores = trace.get('scores', {}) if trace is mapping else {} %}
          | Component | Score |
          |---|---:|
          | Weer | {{ scores.get('weather_score', 'n.b.') }}/100 |
          | Stabiliteit | {{ scores.get('stability_score', 'n.b.') }}/100 |
          | Temperatuur | {{ scores.get('temperature_score', 'n.b.') }}/100 |
          | Afstand | {{ scores.get('distance_score', 'n.b.') }}/100 |
          | Vakantiedruk | {{ scores.get('holiday_pressure_score', 'n.b.') }}/100 |
          | Toegang | {{ scores.get('access_score', 'n.b.') }}/100 |
          | Trip efficiency | {{ scores.get('trip_efficiency_score', 'n.b.') }}/100 |
          | Eindscore | {{ scores.get('ride_quality_score', 'n.b.') }}/100 |

  - type: grid
    cards:
      - type: markdown
        title: Beste kansen in forecast
        content: |
          {% set windows = state_attr('sensor.rideradar_top_month_opportunities', 'opportunities') or [] %}
          {% set rejected = state_attr('sensor.rideradar_top_month_opportunities', 'best_below_threshold') %}
          {% set reason_labels = {
            'below_minimum_score': 'Score onder minimum',
            'weather_too_poor': 'Weer te slecht',
            'stability_too_low': 'Stabiliteit te laag',
            'weekend_only_filter': 'Valt buiten weekendfilter',
            'preferred_start_day_filter': 'Valt buiten voorkeursdag',
            'trailer_unavailable': 'Aanhanger niet beschikbaar',
            'trailer_required_but_unavailable': 'Aanhanger nodig, maar niet beschikbaar',
            'insufficient_destination_ride_time': 'Te weinig rijtijd op bestemming',
            'approach_time_too_high': 'Aanrijtijd te hoog',
            'no_complete_window': 'Geen volledig weervenster',
            'disabled_destination': 'Bestemming uitgeschakeld',
            'too_far': 'Buiten ingestelde afstand'
          } %}
          {% if windows %}
          {% for item in windows %}
          {% set item = item if item is mapping else {} %}
          {{ loop.index }}. **{{ item.get('destination', 'n.b.') }}** - {{ item.get('ride_quality_score', 'n.b.') }}/100

          {{ item.get('period', 'Nog niet beschikbaar') }}

          {% endfor %}
          {% else %}
          Geen kansen boven 70 gevonden in de forecast horizon.

          {% if rejected %}
          {% set rejected = rejected if rejected is mapping else {} %}
          Beste afgewezen optie: **{{ rejected.get('destination', 'Nog niet beschikbaar') }} {{ rejected.get('ride_quality_score', 'n.b.') }}/100**

          {{ rejected.get('period', 'Nog niet beschikbaar') }}

          {% set blocking = rejected.get('main_blocking_factor', rejected.get('reason', 'onbekend')) %}
          Belangrijkste reden: {{ reason_labels.get(blocking, blocking) }}
          {% endif %}
          {% endif %}
      - type: entities
        title: Snelle instellingen
        entities:
          - entity: select.rideradar_trip_duration
            name: Ritduur
          - entity: number.rideradar_forecast_horizon_days
            name: Forecast horizon
          - entity: switch.rideradar_weekend_only
            name: Alleen weekend
          - entity: select.rideradar_travel_strategy
            name: Reisstrategie
          - entity: switch.rideradar_trailer_available
            name: Aanhanger vandaag beschikbaar
      - type: entities
        title: Geavanceerde instellingen
        entities:
          - entity: number.rideradar_trip_duration_days
            name: Aantal dagen
          - entity: select.rideradar_preferred_start_day
            name: Gewenste startdag
          - entity: number.rideradar_available_hours_per_day
            name: Beschikbare uren per dag
          - entity: number.rideradar_max_approach_time_hours
            name: Max aanrijtijd

  - type: grid
    cards:
      - type: markdown
        title: Alle kandidaten
        content: |
          {% set windows = state_attr('sensor.rideradar_best_opportunities', 'opportunities') or [] %}
          {% set strategy_labels = {
            'motorcycle_direct': 'Motor direct',
            'motorcycle_scenic': 'Scenische motorroute',
            'trailer': 'Aanhanger'
          } %}
          | Bestemming | Score | Duur | Weer | Stabiliteit | Efficiëntie | Afstand | Strategie | Verdict | Trade-off |
          |---|---:|---:|---:|---:|---:|---:|---|---|---|
          {% for item in windows %}
          {% set item = item if item is mapping else {} %}
          {% set tradeoffs = item.get('tradeoffs', ['Geen grote trade-off']) %}
          | {{ item.get('destination', 'n.b.') }} | {{ item.get('ride_quality_score', 'n.b.') }}/100 | {{ item.get('duration_days', 'n.b.') }} | {{ item.get('weather_score', 'n.b.') }}/100 | {{ item.get('stability_score', 'n.b.') }}/100 | {{ item.get('trip_efficiency_score', 'n.b.') }}/100 | {{ item.get('route_distance_km', 0) | round(0) }} km | {{ strategy_labels.get(item.get('travel_strategy'), item.get('travel_strategy', 'n.b.')) }} | {{ item.get('verdict', 'n.b.') | replace('Excellent', 'Uitstekend') | replace('Very good', 'Zeer goed') | replace('Good', 'Goed') | replace('Mediocre', 'Matig') | replace('Poor', 'Slecht') | replace('Not recommended', 'Niet aanbevolen') }} | {{ tradeoffs[0] if tradeoffs else 'Geen grote trade-off' }} |
          {% endfor %}
      - type: markdown
        title: Uitgesloten bestemmingen
        content: |
          {% set excluded = state_attr('sensor.rideradar_best_summary', 'excluded_destinations') or [] %}
          {% set reason_labels = {
            'disabled': 'Uitgeschakeld',
            'disabled_destination': 'Uitgeschakeld',
            'too_far': 'Buiten ingestelde afstand',
            'no_forecast_data': 'Geen forecast-data',
            'no_complete_window': 'Geen volledig weervenster',
            'below_minimum_score': 'Score onder minimum',
            'weather_too_poor': 'Weer te slecht',
            'stability_too_low': 'Stabiliteit te laag',
            'weekend_only_filter': 'Valt buiten weekendfilter',
            'preferred_start_day_filter': 'Valt buiten voorkeursdag',
            'trailer_required_but_unavailable': 'Aanhanger nodig, maar niet beschikbaar',
            'trailer_unavailable': 'Aanhanger niet beschikbaar',
            'approach_time_too_high': 'Aanrijtijd te hoog',
            'insufficient_destination_ride_time': 'Te weinig rijtijd op bestemming',
            'unavailable_helper_state': 'Helperwaarde niet beschikbaar',
            'invalid_configuration': 'Ongeldige configuratie'
          } %}
          | Bestemming | Reden | Details |
          |---|---|---|
          {% for item in excluded[:12] %}
          {% set item = item if item is mapping else {} %}
          | {{ item.get('destination', 'n.b.') }} | {{ reason_labels.get(item.get('reason'), item.get('reason', 'onbekend')) }} | {{ item.get('details', '') }} |
          {% endfor %}
          {% if not excluded %}
          Geen uitgesloten bestemmingen.
          {% endif %}
      - type: markdown
        title: Waarom deze keuze?
        content: |
          {% set trace = state_attr('sensor.rideradar_best_summary', 'best_decision_trace') or {} %}
          {% set result = trace.get('result', {}) if trace is mapping else {} %}
          {% set opportunity = state_attr('sensor.rideradar_best_next_available_opportunity', 'opportunity') or {} %}
          {% set opportunity = opportunity if opportunity is mapping else {} %}
          {% set rec_type = result.get('recommendation_type', opportunity.get('recommendation_type', 'recommended')) if result is mapping else opportunity.get('recommendation_type', 'recommended') %}
          {% if rec_type == 'least_bad_option' %}
          **Type advies:** Minst slechte optie
          {% else %}
          **Type advies:** Aanbevolen rit
          {% endif %}

          {{ opportunity.get('recommendation_reason', 'Nog geen aanbevelingsreden beschikbaar.') }}

          {% for tradeoff in opportunity.get('tradeoffs', []) %}
          - {{ tradeoff }}
          {% endfor %}
```

If the native control entities are missing, reload the RideRadar integration from Settings > Devices & services. A full Home Assistant restart should not be required during normal configuration changes.

Screenshot placeholder: add your dashboard screenshot at `docs/images/rideradar-dashboard-hero.png` after importing the view above.

### Native Dashboard Controls

RideRadar creates these controls automatically. Place them above the RideRadar cards if you want a compact control panel.

```yaml
type: entities
title: RideRadar controls
entities:
  - entity: select.rideradar_trip_duration
    name: Trip duration
  - entity: number.rideradar_trip_duration_days
    name: Custom or flexible maximum days
  - entity: number.rideradar_forecast_horizon_days
    name: Forecast horizon
  - entity: select.rideradar_preferred_start_day
    name: Preferred start day
  - entity: switch.rideradar_weekend_only
    name: Weekend only
  - entity: select.rideradar_travel_strategy
    name: Travel strategy
  - entity: switch.rideradar_trailer_available
    name: Trailer available today
  - entity: number.rideradar_available_hours_per_day
    name: Available hours per day
  - entity: number.rideradar_max_approach_time_hours
    name: Max approach time
```

Supported `select.rideradar_trip_duration` values include `1 day`, `2 days`, `3 days`, `flexible`, and `custom`.
Supported `select.rideradar_travel_strategy` values include `Motorcycle Direct`, `Motorcycle Scenic Approach`, and `Trailer Transport`.
Trailer recommendations only appear when trailer transport mode is enabled in configuration and `switch.rideradar_trailer_available` is on. Configuration support means "this rider can use trailer transport"; runtime availability means "the trailer is available today".

Legacy `input_*` helpers are still read as fallback for older dashboards, but new dashboards should use the native RideRadar entities above.

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
            name: Forecast horizon
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

## Optional Debug Dashboard

Use this while testing RideRadar decisions. It shows the selected scenario, the best score, the top exclusion reason, and the score breakdown.

```yaml
type: markdown
title: RideRadar debug
content: |
  {% set summary = 'sensor.rideradar_best_summary' %}
  {% set duration = 'sensor.rideradar_trip_duration' %}
  {% set trace = state_attr(summary, 'best_decision_trace') or {} %}
  {% set inputs = trace.get('inputs', {}) if trace is mapping else {} %}
  {% set breakdown = trace.get('scores', {}) if trace is mapping else {} %}
  {% set weights = trace.get('weights', {}) if trace is mapping else {} %}
  {% set caps = trace.get('caps', []) if trace is mapping else [] %}

  Travel strategy: **{{ inputs.get('travel_strategy', 'unknown') }}**

  Trailer available: **{{ inputs.get('trailer_available', 'unknown') }}**

  Duration: **{{ state_attr(duration, 'duration_label') or states(duration) ~ ' days' }}**

  Forecast horizon: **{{ inputs.get('forecast_horizon_days', 'unknown') }} days**

  Weekend only: **{{ inputs.get('weekend_only', 'unknown') }}**

  Preferred start day: **{{ inputs.get('preferred_start_day', 'any') }}**

  Best destination: **{{ states('sensor.rideradar_best_trip_destination') }}**

  Best score: **{{ states('sensor.rideradar_best_ride_quality_score') }}/100**

  Top exclusion reason: **{{ state_attr(summary, 'top_exclusion_reason') or 'none' }}**

  Scores:
  - Weather: {{ breakdown.get('weather_score', 'unknown') }}/100
  - Stability: {{ breakdown.get('stability_score', 'unknown') }}/100
  - Temperature: {{ breakdown.get('temperature_score', 'unknown') }}/100
  - Distance: {{ breakdown.get('distance_score', 'unknown') }}/100
  - Holiday pressure: {{ breakdown.get('holiday_pressure_score', 'unknown') }}/100
  - Access: {{ breakdown.get('access_score', 'unknown') }}/100
  - Trip efficiency: {{ breakdown.get('trip_efficiency_score', 'unknown') }}/100

  Weights:
  - Weather: {{ weights.get('weather_score', 'unknown') }}%
  - Stability: {{ weights.get('stability_score', 'unknown') }}%
  - Temperature: {{ weights.get('temperature_score', 'unknown') }}%
  - Distance: {{ weights.get('distance_score', 'unknown') }}%
  - Holiday pressure: {{ weights.get('holiday_pressure_score', 'unknown') }}%
  - Access: {{ weights.get('access_score', 'unknown') }}%
  - Trip efficiency: {{ weights.get('trip_efficiency_score', 'unknown') }}%

  Caps:
  {% for cap in caps %}
  {% set cap = cap if cap is mapping else {} %}
  - {{ cap.get('reason', 'unknown') }}: max {{ cap.get('cap', 'unknown') }}
  {% else %}
  - none
  {% endfor %}

  Candidate counts:
  - Week candidates: {{ state_attr('sensor.rideradar_top_week_opportunities', 'candidate_count') | default('unknown') }}
  - Week rejected: {{ state_attr('sensor.rideradar_top_week_opportunities', 'rejected_count') | default('unknown') }}
  - Forecast candidates: {{ state_attr('sensor.rideradar_top_month_opportunities', 'candidate_count') | default('unknown') }}
  - Forecast rejected: {{ state_attr('sensor.rideradar_top_month_opportunities', 'rejected_count') | default('unknown') }}
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
5. Confirm the resolved display name and rounded coordinates, or clear the confirmation checkbox to search again.

If no location is found, RideRadar keeps you in the flow and asks you to try a larger nearby town, add the country name, or use a more specific address. Invalid or partial geocoding results are not saved.

The options flow shows one normal settings screen with:

- current configured start location
- current resolved coordinates
- editable start address/place
- maximum route distance
- default trip duration
- forecast horizon days
- trailer transport support
- enabled destinations

Dynamic scenario controls such as custom trip duration, flexible duration, weekend-only, preferred start day, travel strategy, trailer availability today, available hours per day, and maximum approach time are native dashboard entities. Coordinates are internal resolved data. They are shown for confirmation, not as the primary input method. Raw destination JSON is not part of the normal setup or options experience; import/export remains an advanced maintenance path only.

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
