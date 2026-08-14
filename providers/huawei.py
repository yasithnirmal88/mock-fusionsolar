"""
Huawei provider placeholder.

This module defines HuaweiDataProvider which implements AbstractDataProvider
but does not perform any real network calls. It demonstrates where and how
Huawei FusionSolar integration will be added in the future. The class is a
stub that raises NotImplementedError on get_plant_data.
"""
from __future__ import annotations
from typing import Any

from providers.abstract import AbstractDataProvider
from models.plant import PlantData


class HuaweiDataProvider(AbstractDataProvider):
    """Placeholder for future Huawei FusionSolar provider.

    Intended responsibilities (future):
      - Authenticate with Huawei FusionSolar Northbound API
      - Request plant/inverter/string data and map to PlantData
      - Handle pagination, rate limits, and error handling
      - Provide the same synchronous interface as AbstractDataProvider or
        a sync adapter that wraps async HTTP calls
    """

    def __init__(self, **kwargs: Any):
        # Accept configuration like base_url, credentials, http client, etc.
        self._initialized = True

    def get_plant_data(self, plant_id: str) -> PlantData:
        raise NotImplementedError("HuaweiDataProvider is a placeholder and not implemented yet.")

