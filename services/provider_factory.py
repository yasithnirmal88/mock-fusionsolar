"""
Provider factory.

Creates a concrete provider instance based on application configuration.
The factory returns objects that implement AbstractDataProvider so callers
never need to import provider implementations directly.
"""
from __future__ import annotations
from typing import cast

from config import settings
from core.logger import get_logger
from providers.abstract import AbstractDataProvider
from providers.simulator import SimulatorDataProvider
from providers.huawei import HuaweiDataProvider
from core.errors import ConfigurationError

logger = get_logger(__name__)


class ProviderFactory:
    """Factory responsible for creating providers based on configuration.

    This factory caches a single provider instance per process. It ensures the
    simulator's background thread is created only once and provides a single
    point to change the provider selection logic in the future.
    """

    _instance: AbstractDataProvider | None = None

    @classmethod
    def get_provider(cls) -> AbstractDataProvider:
        if cls._instance is not None:
            return cls._instance

        provider_name = settings.PROVIDER.lower()
        logger.info("Resolving provider: %s", provider_name)

        if provider_name == "simulator":
            # Return simulator instance configured from settings
            from providers.simulator import SimulatorConfig

            sim_cfg = SimulatorConfig(
                plant_id="sim-plant-001",
                seed=0,
                update_interval_seconds=settings.SIM_INTERVAL,
                scenario=settings.SIM_SCENARIO,
                inverters=settings.SIM_INVERTERS,
                strings_per_inverter=settings.SIM_STRINGS_PER_INVERTER,
            )
            cls._instance = SimulatorDataProvider(config=sim_cfg)
            return cls._instance

        if provider_name == "huawei":
            cls._instance = HuaweiDataProvider()
            return cls._instance

        raise ConfigurationError(f"Unknown provider configured: {settings.PROVIDER}")

    @classmethod
    def reset_provider(cls) -> None:
        """Reset the cached provider (useful for tests). If the provider has
        a stop() method it will be called to clean up resources.
        """
        if cls._instance is not None:
            stop = getattr(cls._instance, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    logger.exception("Error stopping provider during reset")
            cls._instance = None



