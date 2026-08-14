"""
Simulator provider implementation.

This simulator generates an in-memory representation of a solar plant with:
- 2 inverters
- 20 strings per inverter (40 strings total)

It updates its internal state periodically and returns the latest snapshot
when get_plant_data is called. The simulator supports configurable fault
scenarios (only one active at a time): healthy, one degraded string, one
disconnected string, one offline inverter.

Design notes:
- The provider implements the same interface as other providers so it can be
  replaced without changing consumers.
- The simulator uses deterministic seeding by default but allows a seed to be
  provided for reproducible behavior during tests.
- All data is stored in memory; no external persistence is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
import random
import threading
import time
from typing import Any, Dict, List, Optional

from providers.abstract import AbstractDataProvider
from models.plant import PlantData, PlantMetrics, InverterData, StringData
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SimulatorConfig:
    plant_id: str = "sim-plant-001"
    inverters: int = 2
    strings_per_inverter: int = 20
    seed: Optional[int] = None
    update_interval_seconds: int = 5  # how often internal state is advanced
    scenario: str = "healthy"  # one of: healthy, degraded_string, disconnected_string, offline_inverter


class SimulatorDataProvider(AbstractDataProvider):
    """Concrete simulator provider.

    Public API:
      - get_plant_data(plant_id) -> PlantData
    """

    def __init__(self, config: SimulatorConfig | None = None, **kwargs: Any):
        self.config = config or SimulatorConfig()
        self._rand = random.Random(self.config.seed)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        # internal state
        self._strings: Dict[str, StringData] = {}
        self._inverters: Dict[str, InverterData] = {}
        self._metrics: PlantMetrics
        self._last_energy_kwh = 0.0
        self._start_time = datetime.now(timezone.utc)

        self._build_initial_state()

        # Start background thread to update state periodically
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Simulator started with scenario=%s", self.config.scenario)

    def _build_initial_state(self) -> None:
        now = datetime.now(timezone.utc)
        # Initialize inverters
        for inv_idx in range(1, self.config.inverters + 1):
            inv_id = f"inv-{inv_idx:02d}"
            self._inverters[inv_id] = InverterData(inverter_id=inv_id, power_w=0.0, status="ok")

            # Initialize strings
            for s_idx in range(1, self.config.strings_per_inverter + 1):
                str_id = f"{inv_id}-str-{s_idx:03d}"
                sd = StringData(
                    string_id=str_id,
                    inverter_id=inv_id,
                    current_a=0.0,
                    voltage_v=0.0,
                    power_w=0.0,
                    status="ok",
                    timestamp=now,
                )
                self._strings[str_id] = sd

        # Initial environmental metrics (will be updated by the loop)
        self._metrics = PlantMetrics(irradiance_w_m2=0.0, ambient_temp_c=15.0, panel_temp_c=20.0)
        self._last_update = now

    def _run_loop(self) -> None:
        # Background loop advances the simulated time and updates measurements
        interval = max(1, int(self.config.update_interval_seconds))
        while not self._stop_event.is_set():
            try:
                self._advance_state()
            except Exception:
                logger.exception("Error updating simulator state")
            time.sleep(interval)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=1.0)

    def _advance_state(self) -> None:
        """Advance internal state by a small time step."""
        with self._lock:
            now = datetime.now(timezone.utc)
            elapsed = (now - self._last_update).total_seconds()
            # Update environmental variables based on time of day
            tod = now.astimezone(timezone.utc).hour + now.minute / 60.0
            # Model irradiance as a simple bell curve around midday (12:00)
            irradiance = self._compute_irradiance(tod)
            ambient = 10.0 + 10.0 * math.sin((tod / 24.0) * 2.0 * math.pi)  # simple diurnal temp
            panel_temp = ambient + 10.0 * (irradiance / 1000.0)

            self._metrics = PlantMetrics(
                irradiance_w_m2=irradiance,
                ambient_temp_c=round(ambient + self._noise(0.5), 2),
                panel_temp_c=round(panel_temp + self._noise(0.5), 2),
            )

            # Update strings and inverters
            total_power = 0.0
            for s_id, s in list(self._strings.items()):
                # Base power proportional to irradiance
                base_power = irradiance * 0.3  # scaled per-string base (W)
                # add variation per string
                variability = 1.0 + (self._rand.random() - 0.5) * 0.1
                power_w = max(0.0, base_power * variability)

                # Apply time-of-day behavior: at night zero
                if irradiance < 5:
                    power_w = 0.0
                    current_a = 0.0
                    voltage_v = 0.0
                else:
                    # assume string voltage ~ 600V, current derived
                    voltage_v = 600.0 + self._noise(2.0)
                    current_a = power_w / max(1e-6, voltage_v)

                # Apply scenario-based faults
                status = "ok"
                if self.config.scenario == "degraded_string":
                    # degrade one string: reduce power by 50%
                    # pick the first string deterministically
                    degraded_id = sorted(self._strings.keys())[0]
                    if s_id == degraded_id:
                        power_w *= 0.5
                        status = "degraded"
                elif self.config.scenario == "disconnected_string":
                    disc_id = sorted(self._strings.keys())[0]
                    if s_id == disc_id:
                        power_w = 0.0
                        current_a = 0.0
                        voltage_v = 0.0
                        status = "disconnected"

                # store
                s.current_a = round(current_a + self._noise(0.05), 3)
                s.voltage_v = round(voltage_v + self._noise(0.5), 2)
                s.power_w = round(power_w + self._noise(5.0), 2)
                s.status = status
                s.timestamp = now

                total_power += s.power_w

            # Inverter aggregation and possible offline inverter scenario
            for inv_id, inv in self._inverters.items():
                # sum strings for this inverter
                inv_power = sum(s.power_w for s in self._strings.values() if s.inverter_id == inv_id)
                inv_status = "ok"
                if self.config.scenario == "offline_inverter":
                    # take the first inverter offline
                    offline_id = sorted(self._inverters.keys())[0]
                    if inv_id == offline_id:
                        inv_power = 0.0
                        inv_status = "offline"
                inv.power_w = round(inv_power, 2)
                inv.status = inv_status

            # energy integration (very simple trapezoidal approx)
            # energy (kWh) += power_kW * hours
            dt_hours = elapsed / 3600.0
            energy_kwh = (total_power / 1000.0) * dt_hours
            self._last_energy_kwh += energy_kwh

            self._last_update = now
            self._last_total_power = total_power

    def _compute_irradiance(self, tod_hour: float) -> float:
        # Peak at 12:00, zero at night. Use a Gaussian-like curve.
        peak_hour = 12.0
        width = 4.0  # controls how quickly irradiance rises/falls
        value = 1000.0 * math.exp(-0.5 * ((tod_hour - peak_hour) / width) ** 2)
        # Add small random fluctuation
        return max(0.0, value + self._noise(20.0))

    def _noise(self, scale: float = 1.0) -> float:
        return (self._rand.random() - 0.5) * 2.0 * scale

    def get_plant_data(self, plant_id: str) -> PlantData:
        with self._lock:
            now = datetime.now(timezone.utc)
            power_kw = round(getattr(self, "_last_total_power", 0.0) / 1000.0, 3)
            pd = PlantData(
                plant_id=self.config.plant_id,
                timestamp=now,
                power_kw=power_kw,
                energy_today_kwh=round(self._last_energy_kwh, 3),
                status="ok",
                metrics=self._metrics,
                inverters=list(self._inverters.values()),
                strings=list(self._strings.values()),
            )
            return pd

