"""Application configuration.

Typed configuration via pydantic-settings, read from environment variables
(with a sensible development default for every field so the simulator runs
out of the box without a .env file).

The simulator is the only data source this project exposes; ``PROVIDER`` can
be set to ``huawei`` to mount the (still stub) Huawei provider for forward
compatibility, but the default is ``simulator``.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    # General
    APP_NAME: str = "Solar Simulator (MVP)"
    LOG_LEVEL: str = "INFO"

    # Provider selection: "simulator" (default, generates the fake plant) or
    # "huawei" (stub kept for forward compatibility with the real API).
    PROVIDER: str = "simulator"

    # Plant topology used by the simulator.
    SIM_PLANT_ID: str = "sim-plant-001"
    SIM_INVERTERS: int = 2
    SIM_STRINGS_PER_INVERTER: int = 20
    SIM_INTERVAL: int = 600  # seconds between live state updates (10-min step)
    SIM_SCENARIO: str = "healthy"  # healthy | degraded_string | disconnected_string | offline_inverter

    # Historical dataset generation (development only). The simulator produces
    # this many days of history on demand for the history endpoints, so Scarda
    # can backfill its own time-series store without the real Huawei API.
    HISTORY_DAYS: int = 90
    HISTORY_INTERVAL_MINUTES: int = 10
    # Seed makes the generated history deterministic/reproducible so injected
    # anomalies land on known timestamps.
    HISTORY_SEED: int = 42

    # HTTP
    HTTP_TIMEOUT: int = 10

    # Default credentials accepted by the fake auth service (any password is
    # accepted; these are the documented dev credentials Scarda uses).
    AUTH_USERNAME: str = "huawei"
    AUTH_PASSWORD: str = "huawei"


settings = Settings()
