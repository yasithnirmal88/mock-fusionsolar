"""
Simulator provider implementation.

The simulator produces realistic live solar-plant data derived from the SAME
physics as the historical dataset generator (clear-sky irradiance, autocorrelated
cloud cover, temperature, and per-string power that tracks irradiance). This
keeps the live ``/plants/{id}`` snapshot consistent with the 90-day history so
Scarda's historical-similarity baseline compares like-for-like.

The simulation clock advances in 10-minute steps (matching the history
interval). On each ``get_plant_data`` call it advances the clock to the current
real time (aligned to the 10-min grid) and recomputes the plant state, so
Scarda sees a fresh, realistic reading every poll. Weather (irradiance,
temperature, panel temperature) and per-string power/voltage/current are all
derived from environmental conditions — power falls when irradiance falls
(clouds/night), so Scarda can distinguish weather-driven drops from faults.

A configurable scenario can inject a live fault (degraded string / offline
inverter) for end-to-end alert testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import random
import threading
from typing import Any, Dict, List, Optional

from providers.abstract import AbstractDataProvider
from models.plant import PlantData, PlantMetrics, InverterData, StringData
from core.logger import get_logger
from history.generator import (
    HistoryConfig,
    _ambient_temp,
    _clear_sky_irradiance,
    _cloud_factor,
    _expected_power,
    _strings as _layout_strings,
    _inverters as _layout_inverters,
    NIGHT_IRRADIANCE_WPM2,
    RATED_VOLTAGE_V,
)

logger = get_logger(__name__)


@dataclass
class SimulatorConfig:
    plant_id: str = "sim-plant-001"
    inverters: int = 2
    strings_per_inverter: int = 20
    seed: Optional[int] = None
    update_interval_seconds: int = 600  # 10-min simulation step
    scenario: str = "healthy"  # healthy | degraded_string | disconnected_string | offline_inverter


class SimulatorDataProvider(AbstractDataProvider):
    """Concrete simulator provider producing realistic 10-min live data.

    Public API:
      - get_plant_data(plant_id) -> PlantData
    """

    def __init__(self, config: SimulatorConfig | None = None, **kwargs: Any):
        self.config = config or SimulatorConfig()
        self._rand = random.Random(self.config.seed)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        # Build the plant layout from the same helper the history generator uses.
        self._layout: List[tuple[str, str]] = _layout_strings(
            HistoryConfig(
                plant_id=self.config.plant_id,
                inverters=self.config.inverters,
                strings_per_inverter=self.config.strings_per_inverter,
            )
        )
        self._inverter_ids: List[str] = _layout_inverters(
            HistoryConfig(
                inverters=self.config.inverters,
                strings_per_inverter=self.config.strings_per_inverter,
            )
        )

        self._last_energy_kwh = 0.0
        self._last_total_power = 0.0
        self._last_snapshot: PlantData | None = None
        self._last_t: datetime | None = None
        self._day_energy: Dict[str, float] = {}

        # Produce the first snapshot immediately so the first request is not empty.
        self._advance_to(datetime.now(timezone.utc))

        # Background thread advances the simulation clock every update_interval
        # so state stays current even without a request (keeps energy integration
        # continuous). Each step is a 10-minute simulated increment.
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Simulator started (scenario=%s, step=%ss)",
            self.config.scenario, self.config.update_interval_seconds,
        )

    def _run_loop(self) -> None:
        interval = max(1, int(self.config.update_interval_seconds))
        while not self._stop_event.is_set():
            try:
                self._advance_to(datetime.now(timezone.utc))
            except Exception:
                logger.exception("Error updating simulator state")
            self._stop_event.wait(interval)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=1.0)

    def _align_to_step(self, t: datetime) -> datetime:
        """Align a timestamp to the 10-minute grid (like the history generator)."""
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        step = timedelta(minutes=10)
        return t.replace(second=0, microsecond=0) - (t - epoch) % step

    def _advance_to(self, now: datetime) -> None:
        """Advance the simulation clock to ``now`` (aligned to 10 min) and recompute."""
        with self._lock:
            t = self._align_to_step(now)

            clear = _clear_sky_irradiance(t)
            if clear > 0:
                irradiance = clear * _cloud_factor(t, self._rand)
            else:
                irradiance = 0.0
            irradiance = round(max(0.0, irradiance), 2)
            ambient = _ambient_temp(t, irradiance)
            panel = round(ambient + 12.0 * (irradiance / 1000.0), 2)
            metrics = PlantMetrics(
                irradiance_w_m2=irradiance,
                ambient_temp_c=ambient,
                panel_temp_c=panel,
            )

            # Determine live-fault targets (deterministic: first string/inverter).
            degraded_id = self._layout[0][0] if self._layout else None
            offline_inv = self._inverter_ids[0] if self._inverter_ids else None

            strings: Dict[str, StringData] = {}
            inv_power: Dict[str, float] = {inv: 0.0 for inv in self._inverter_ids}
            total_power = 0.0

            for str_id, inv_id in self._layout:
                expected = _expected_power(irradiance, ambient)
                actual = expected * (1.0 + (self._rand.random() - 0.5) * 0.08)

                status = "ok"
                if self.config.scenario == "offline_inverter" and inv_id == offline_inv:
                    actual = 0.0
                    status = "disconnected"
                elif self.config.scenario == "degraded_string" and str_id == degraded_id:
                    actual *= 0.45
                    status = "degraded"
                elif self.config.scenario == "disconnected_string" and str_id == degraded_id:
                    actual = 0.0
                    status = "disconnected"

                if irradiance <= NIGHT_IRRADIANCE_WPM2:
                    actual = 0.0
                    voltage = 0.0
                    current = 0.0
                else:
                    voltage = round(RATED_VOLTAGE_V + (self._rand.random() - 0.5) * 8.0, 2)
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
                inv_power[inv_id] += power_w

            inverters: List[InverterData] = []
            for inv_id in self._inverter_ids:
                inv_status = "offline" if (
                    self.config.scenario == "offline_inverter" and inv_id == offline_inv
                ) else "ok"
                inverters.append(InverterData(
                    inverter_id=inv_id,
                    power_w=round(inv_power[inv_id], 2),
                    status=inv_status,  # type: ignore[arg-type]
                ))

            # Energy integration (trapezoidal) across the step since the last sample.
            day_key = t.strftime("%Y-%m-%d")
            if self._last_t is not None:
                dt_hours = (t - self._last_t).total_seconds() / 3600.0
                self._day_energy[day_key] = (
                    self._day_energy.get(day_key, 0.0)
                    + (self._last_total_power / 1000.0) * dt_hours
                )

            self._last_total_power = total_power
            self._last_t = t

            self._last_snapshot = PlantData(
                plant_id=self.config.plant_id,
                timestamp=t,
                power_kw=round(total_power / 1000.0, 3),
                energy_today_kwh=round(self._day_energy.get(day_key, 0.0), 3),
                status="ok",
                metrics=metrics,
                inverters=inverters,
                strings=list(strings.values()),
            )

    def get_plant_data(self, plant_id: str) -> PlantData:
        with self._lock:
            # Advance to "now" so each poll returns the freshest 10-min sample.
            self._advance_to(datetime.now(timezone.utc))
            return self._last_snapshot  # type: ignore[return-value]

