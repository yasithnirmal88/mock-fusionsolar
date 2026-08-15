# mock-fusionsolar

A standalone **development/testing** simulator that acts as the Huawei FusionSolar
data source. It is the ONLY place simulated solar data is generated. The real
monitoring system (Scarda) consumes this data through the same provider/API
architecture that will later be used with the real Huawei FusionSolar Northbound
API.

## What it provides

- A live plant snapshot API (`/api/plants/{id}`, inverters, strings) with
  fake bearer-token auth (`POST /api/auth/login`, any username/password).
- A **deterministic 90-day historical dataset** (`/api/plants/{id}/history`,
  `/api/plants/{id}/weather/history`) generated from a physics model where
  power is derived from irradiance + temperature (weather-aware), so a cloud
  or night drop in generation is not a fault.
- An **anomaly log** (`/api/plants/{id}/anomalies`) documenting the exact
  timestamps/entities where a degraded string, an offline inverter, and a
  normal cloudy period were injected.

## Run

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Historical dataset

The generator (`history/generator.py`) is seeded and deterministic. It models:

```
irradiance (clear-sky Gaussian around solar noon, modulated by cloud systems)
    -> expected power (STC-scaled, temperature-corrected)
        -> actual power (per-string variability + injected anomalies)
```

Injected anomalies (documented via `/api/plants/{id}/anomalies`):

| kind              | entity            | window (relative to latest sample) |
|-------------------|-------------------|------------------------------------|
| `degraded_string` | `inv-01-str-001`  | day -5, 10:00–13:00 UTC            |
| `offline_inverter`| `inv-01`          | day -3, 11:00–13:00 UTC            |
| `cloudy_period`   | `plant`           | day -2, 10:00–14:00 UTC (NOT a fault) |

Scarda pulls this history through the API and stores it in its own TimescaleDB
`string_readings` hypertable, preserving the original measurement timestamps.
