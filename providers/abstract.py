"""
Provider abstraction.

Defines AbstractDataProvider which is the contract that all concrete providers
must implement. The rest of the application will depend on this interface so
that providers can be swapped without affecting callers.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Protocol

from models.plant import PlantData


class AbstractDataProvider(ABC):
    """Abstract base class defining the provider interface.

    Concrete providers must implement get_plant_data which returns a
    PlantData instance for a given plant identifier.
    """

    @abstractmethod
    def get_plant_data(self, plant_id: str) -> PlantData:
        """Fetch the latest plant data for the provided plant_id.

        Implementations may perform network IO or local simulation. Callers
        should treat this as a synchronous call; async providers can be
        wrapped by a sync adapter if needed.
        """
        raise NotImplementedError
