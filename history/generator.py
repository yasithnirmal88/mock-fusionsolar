"""Historical dataset generator (development only).

This module is the ONLY place fake solar data is produced in this project. It
generates a deterministic, physically-coherent historical dataset for the
simulated plant so Scarda can backfill its own time-series store through the
API (exactly as it will later pull KPI history from the real Huawei Northbound
API).

Design goals (these matter because Scarda's alert engine must distinguish
"low power because of weather" from "low power because of a fault"):

* Power generation is *derived* from environmental conditions, never random:
    irradiance -> expected generation -> actual generation
* A full diurnal cycle: near-zero at night, rising after sunrise, peaking near
  solar noon, falling again at sunset.
* Weather affects irradiance: clear, partly-cloudy and cloudy periods with
  varying temperatures. Power drops when irradiance drops.
* A small number of *controlled* anomalies are injected on known timestamps
  and entities (documented in the anomaly log):
    - a degraded string that under-produces under otherwise similar weather
    - an offline inverter that produces ~0 while irradiance is sufficient
    - normal cloudy periods that MUST NOT be flagged as faults by Scarda

The generator is deterministic (seeded) so anomaly timestamps are stable
across runs and across processes.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from config import settings
from models.plant import InverterData, PlantData, PlantMetrics, StringData


# physics constants
RATED_POWER_PER_STRING_W: float = 250.0
RATED_VOLTAGE_V: float = 600.0
STC_IRRADIANCE_WPM2: float = 1000.0
TEMP_COEFFICIENT_PCT: float = -0.4
NIGHT_IRRADIANCE_WPM2: float = 20.0
DAY_WIDTH_HOURS: float = 3.0
PEAK_HOUR: float = 12.0


@dataclass
class AnomalyEvent:
    """A single injected anomaly, documented for downstream verification."""

    kind: str  # degraded_string | offline_inverter | cloudy_period
    entity: str  # string_id / inverter_id / "plant"
    start: datetime
    end: datetime
    description: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "entity": self.entity,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "description": self.description,
        }


@dataclass
class HistoryConfig:
    plant_id: str = settings.SIM_PLANT_ID
    inverters: int = settings.SIM_INVERTERS
    strings_per_inverter: int = settings.SIM_STRINGS_PER_INVERTER
    days: int = settings.HISTORY_DAYS
    interval_minutes: int = settings.HISTORY_INTERVAL_MINUTES
    seed: int = settings.HISTORY_SEED
    scenario: str = settings.SIM_SCENARIO


def _inverters(cfg: HistoryConfig) -> List[str]:
    return [f"inv-{i:02d}" for i in range(1, cfg.inverters + 1)]


def _strings(cfg: HistoryConfig) -> List[Tuple[str, str]]:
    """Return (string_id, inverter_id) pairs in stable order."""
    out: List[Tuple[str, str]] = []
    for inv_id in _inverters(cfg):
        for s in range(1, cfg.strings_per_inverter + 1):
            out.append((f"{inv_id}-str-{s:03d}", inv_id))
    return out


def _clear_sky_irradiance(t: datetime) -> float:
    """Deterministic clear-sky irradiance from time-of-day (W/m^2)."""
    tod = t.hour + t.minute / 60.0
    if tod < 5.5 or tod > 18.5:
        return 0.0
    return max(
        0.0,
        STC_IRRADIANCE_WPM2 * math.exp(-0.5 * ((tod - PEAK_HOUR) / DAY_WIDTH_HOURS) ** 2),
    )


def _cloud_factor(t: datetime, rng: random.Random) -> float:
    """Multiplicative irradiance reduction from clouds (0..1).

    Built from a few slow sinusoidal "weather systems" plus small noise, so
    cloud cover is autocorrelated (realistic ramps) rather than flickering.
    Distinct clear / partly-cloudy / cloudy periods emerge naturally.
    """
    day = (t - datetime(2026, 1, 1, tzinfo=timezone.utc)).total_seconds() / 86400.0
    c1 = 0.5 * (1.0 + math.sin(2.0 * math.pi * day / 3.7))
    c2 = 0.5 * (1.0 + math.sin(2.0 * math.pi * day / 6.1 + 1.3))
    base = 0.55 + 0.35 * c1 * c2  # 0.55 .. 0.9
    noise = 1.0 + (rng.random() - 0.5) * 0.12
    return max(0.25, min(1.0, base * noise))


def _ambient_temp(t: datetime, irradiance: float) -> float:
    """Ambient temperature: diurnal cycle warmed by daylight."""
    tod = t.hour + t.minute / 60.0
    diurnal = 6.0 * math.sin(2.0 * math.pi * (tod - 9.0) / 24.0)
    daylight_warm = 8.0 * (irradiance / STC_IRRADIANCE_WPM2)
    return round(15.0 + diurnal + daylight_warm, 2)


def _expected_power(irradiance: float, ambient_c: float) -> float:
    """Physics-model expected power for a healthy string (W)."""
    if irradiance <= NIGHT_IRRADIANCE_WPM2:
        return 0.0
    irr_factor = irradiance / STC_IRRADIANCE_WPM2
    temp_factor = 1.0 + (TEMP_COEFFICIENT_PCT / 100.0) * (ambient_c - 25.0)
    return max(0.0, RATED_POWER_PER_STRING_W * irr_factor * temp_factor)


def _align_to_interval(end: datetime, cfg: HistoryConfig) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return end - (end - epoch) % timedelta(minutes=cfg.interval_minutes)


def _build_anomaly_log(cfg: HistoryConfig, end: datetime) -> List[AnomalyEvent]:
    """Documented, deterministic anomaly schedule for the dataset.

    Windows are anchored to daylight UTC hours (10:00-13:00) on fixed day
    offsets from ``end`` so they always contain productive generation and the
    anomalies are observable. Timestamps are reproducible across runs.
    """
    log: List[AnomalyEvent] = []

    # 1) Degraded string: under-produces ~55% for a 3-hour midday window on
    #    day -5. Anchored to 10:00 UTC (well inside daylight).
    degraded_day = (end - timedelta(days=5)).date()
    degraded_start = datetime.combine(
        degraded_day, datetime.min.time(), tzinfo=timezone.utc
    ).replace(hour=10, minute=0)
    degraded_end = degraded_start + timedelta(hours=3)
    log.append(
        AnomalyEvent(
            kind="degraded_string",
            entity="inv-01-str-001",
            start=degraded_start,
            end=degraded_end,
            description="String under-produces ~55% under sufficient irradiance (soiling/partial failure).",
        )
    )

    # 2) Offline inverter: inverter 1 fully offline for 2 hours around midday
    #    on day -3.
    offline_day = (end - timedelta(days=3)).date()
    offline_start = datetime.combine(
        offline_day, datetime.min.time(), tzinfo=timezone.utc
    ).replace(hour=11, minute=0)
    offline_end = offline_start + timedelta(hours=2)
    log.append(
        AnomalyEvent(
            kind="offline_inverter",
            entity="inv-01",
            start=offline_start,
            end=offline_end,
            description="Inverter offline - all its strings report ~0 W while irradiance is sufficient.",
        )
    )

    # 3) Normal cloudy period: a 4-hour cloud ramp around midday on day -2
    #    where irradiance AND power drop together. Scarda MUST NOT flag this.
    cloudy_day = (end - timedelta(days=2)).date()
    cloudy_start = datetime.combine(
        cloudy_day, datetime.min.time(), tzinfo=timezone.utc
    ).replace(hour=10, minute=0)
    cloudy_end = cloudy_start + timedelta(hours=4)
    log.append(
        AnomalyEvent(
            kind="cloudy_period",
            entity="plant",
            start=cloudy_start,
            end=cloudy_end,
            description="Cloud cover drops irradiance 900->400 W/m^2; power drops proportionally. NOT a fault.",
        )
    )
    return log


def _sample_at(
    t: datetime,
    cfg: HistoryConfig,
    anomaly_log: List[AnomalyEvent],
    rng: random.Random,
) -> Tuple[PlantMetrics, Dict[str, StringData], Dict[str, InverterData], float]:
    """Compute one timestamped snapshot for time ``t``."""
    clear = _clear_sky_irradiance(t)

    cloud_override: float | None = None
    for ev in anomaly_log:
        if ev.kind == "cloudy_period" and ev.start <= t < ev.end:
            frac = (t - ev.start) / (ev.end - ev.start)
            dip = 1.0 - 0.6 * math.sin(math.pi * frac)
            cloud_override = dip
            break

    if cloud_override is not None:
        irradiance = clear * cloud_override
    else:
        irradiance = clear * _cloud_factor(t, rng)

    irradiance = round(max(0.0, irradiance), 2)
    ambient = _ambient_temp(t, irradiance)
    panel = round(ambient + 12.0 * (irradiance / STC_IRRADIANCE_WPM2), 2)
    metrics = PlantMetrics(
        irradiance_w_m2=irradiance,
        ambient_temp_c=ambient,
        panel_temp_c=panel,
    )

    degraded_strings = {
        ev.entity for ev in anomaly_log
        if ev.kind == "degraded_string" and ev.start <= t < ev.end
    }
    offline_inverters = {
        ev.entity for ev in anomaly_log
        if ev.kind == "offline_inverter" and ev.start <= t < ev.end
    }

    strings: Dict[str, StringData] = {}
    inverters: Dict[str, InverterData] = {inv: 0.0 for inv in _inverters(cfg)}
    total_power = 0.0

    for str_id, inv_id in _strings(cfg):
        expected = _expected_power(irradiance, ambient)
        actual = expected * (1.0 + (rng.random() - 0.5) * 0.08)

        status = "ok"
        if inv_id in offline_inverters:
            actual = 0.0
            status = "disconnected"
        elif str_id in degraded_strings:
            actual *= 0.45
            status = "degraded"

        if irradiance <= NIGHT_IRRADIANCE_WPM2:
            actual = 0.0
            voltage = 0.0
            current = 0.0
        else:
            voltage = round(RATED_VOLTAGE_V + (rng.random() - 0.5) * 8.0, 2)
            current = round(actual / max(voltage, 1.0), 3)

        power_w = round(max(0.0, actual), 2)
        strings[str_id] = StringData(
            string_id=str_id,
            inverter_id=inv_id,
            current_a=current,
            voltage_v=voltage,
            power_w=power_w,
            status=status,  # type: ignore[arg-type]
            timestamp=t,
        )
        total_power += power_w
        inverters[inv_id] = inverters[inv_id] + power_w

    inv_data: Dict[str, InverterData] = {}
    for inv_id, p in inverters.items():
        inv_status = "offline" if inv_id in offline_inverters else "ok"
        inv_data[inv_id] = InverterData(
            inverter_id=inv_id,
            power_w=round(p, 2),
            status=inv_status,  # type: ignore[arg-type]
        )

    return metrics, strings, inv_data, total_power


def generate_history(cfg: HistoryConfig | None = None) -> List[PlantData]:
    """Generate the full historical dataset as timestamped snapshots.

    Each snapshot carries per-string measurements, inverter aggregates and
    plant metrics, all stamped with their *measurement* time (not generation
    time), so Scarda can store them with their original timestamps.
    """
    cfg = cfg or HistoryConfig()
    rng = random.Random(cfg.seed)

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = _align_to_interval(end, cfg)
    start = end - timedelta(days=cfg.days)

    anomaly_log = _build_anomaly_log(cfg, end)

    steps = int(cfg.days * 24 * 60 / cfg.interval_minutes) + 1
    out: List[PlantData] = []
    prev_total_power = 0.0
    prev_t: datetime | None = None
    day_energy: Dict[str, float] = {}

    for i in range(steps):
        t = start + timedelta(minutes=i * cfg.interval_minutes)
        metrics, strings, inverters, total_power = _sample_at(t, cfg, anomaly_log, rng)

        day_key = t.strftime("%Y-%m-%d")
        if prev_t is not None:
            dt_hours = (t - prev_t).total_seconds() / 3600.0
            energy_inc = (prev_total_power / 1000.0) * dt_hours
            day_energy[day_key] = day_energy.get(day_key, 0.0) + energy_inc
        prev_total_power = total_power
        prev_t = t

        power_kw = round(total_power / 1000.0, 3)
        pd = PlantData(
            plant_id=cfg.plant_id,
            timestamp=t,
            power_kw=power_kw,
            energy_today_kwh=round(day_energy.get(day_key, 0.0), 3),
            status="ok",
            metrics=metrics,
            inverters=list(inverters.values()),
            strings=list(strings.values()),
        )
        out.append(pd)

    return out


def get_anomaly_log(cfg: HistoryConfig | None = None) -> List[AnomalyEvent]:
    """Return the documented anomaly schedule for the dataset."""
    cfg = cfg or HistoryConfig()
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = _align_to_interval(end, cfg)
    return _build_anomaly_log(cfg, end)
