"""Cached access to the generated historical dataset.

Generating ~90 days x 144 samples/day x 40 strings on every request would be
wasteful, so the dataset is generated once per process (lazily) and reused.
The generator is deterministic (seeded), so the cached dataset is identical
across requests and the documented anomaly timestamps always match.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import List

from history.generator import (
    AnomalyEvent,
    HistoryConfig,
    generate_history,
    get_anomaly_log,
)
from models.plant import PlantData


@lru_cache(maxsize=1)
def _dataset(cfg_key: tuple) -> List[PlantData]:
    cfg = HistoryConfig(
        plant_id=cfg_key[0],
        inverters=cfg_key[1],
        strings_per_inverter=cfg_key[2],
        days=cfg_key[3],
        interval_minutes=cfg_key[4],
        seed=cfg_key[5],
        scenario=cfg_key[6],
    )
    return generate_history(cfg)


def dataset() -> List[PlantData]:
    cfg = HistoryConfig()
    return _dataset(
        (
            cfg.plant_id,
            cfg.inverters,
            cfg.strings_per_inverter,
            cfg.days,
            cfg.interval_minutes,
            cfg.seed,
            cfg.scenario,
        )
    )


def anomaly_events() -> List[AnomalyEvent]:
    return get_anomaly_log(HistoryConfig())


def history_between(start: datetime, end: datetime) -> List[PlantData]:
    """Return the subset of the cached dataset within [start, end)."""
    data = dataset()
    return [d for d in data if start <= d.timestamp < end]


def weather_between(start: datetime, end: datetime) -> List[PlantData]:
    """Same window; callers read the ``metrics`` + ``timestamp`` fields."""
    return history_between(start, end)
