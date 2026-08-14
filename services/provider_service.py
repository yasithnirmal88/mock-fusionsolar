"""
Provider service.

A thin service layer that depends on the AbstractDataProvider interface. It
is responsible for higher-level use cases like fetching and transforming the
provider's raw data into domain models consumed by the API.
"""
from __future__ import annotations

from typing import Protocol

from models.plant import PlantData
from providers.abstract import AbstractDataProvider
from core.logger import get_logger

logger = get_logger(__name__)


class ProviderService:
    """Service that uses an AbstractDataProvider to fetch plant data."""

    def __init__(self, provider: AbstractDataProvider):
        self._provider = provider

    def fetch_plant_data(self, plant_id: str) -> PlantData:
        """Fetch the latest plant data via the configured provider.

        This method simply delegates to the provider and may include additional
        transformation, caching, or validation logic in the future.
        """
        logger.debug("Fetching plant data for %s", plant_id)
        data = self._provider.get_plant_data(plant_id)
        # Potential place for validation or normalization
        return data
