"""
Plant domain models.

Pydantic models are used for serialization, validation, and type hints across
the application.

This module contains models for per-string, per-inverter, plant-level metrics
and the consolidated PlantData returned by providers.
"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from pydantic import ConfigDict


class StringData(BaseModel):
    """Measurements for a single string (series-connected panels).

    Attributes:
        string_id: unique identifier for the string
        inverter_id: identifier of the parent inverter
        current_a: current in amperes
        voltage_v: voltage in volts
        power_w: instantaneous power in watts
        status: status of the string (ok, degraded, disconnected)
        timestamp: measurement timestamp (UTC)
    """

    string_id: str = Field(...)
    inverter_id: str = Field(...)
    current_a: float = Field(...)
    voltage_v: float = Field(...)
    power_w: float = Field(...)
    status: Literal["ok", "degraded", "disconnected", "unknown"] = Field("unknown")
    timestamp: datetime = Field(...)


class InverterData(BaseModel):
    """Aggregated data for an inverter."""

    inverter_id: str = Field(...)
    power_w: float = Field(...)
    status: Literal["ok", "offline", "degraded", "unknown"] = Field("unknown")


class PlantMetrics(BaseModel):
    """Environmental and plant-level measured values."""

    irradiance_w_m2: float = Field(..., description="Irradiance in W/m^2")
    ambient_temp_c: float = Field(..., description="Ambient temperature in °C")
    panel_temp_c: float = Field(..., description="Module/panel temperature in °C")


class PlantData(BaseModel):
    """Consolidated plant data returned by providers.

    This model includes per-string measurements as well as plant-wide metrics
    so that the REST API can expose both granular and aggregated information.
    """

    plant_id: str = Field(..., description="Unique plant identifier")
    timestamp: datetime = Field(..., description="UTC timestamp for the measurement")
    power_kw: Optional[float] = Field(None, description="Total plant power in kW")
    energy_today_kwh: Optional[float] = Field(None, description="Energy produced since midnight in kWh")
    status: str = Field("unknown", description="Overall plant status")

    metrics: PlantMetrics = Field(...)
    inverters: List[InverterData] = Field(...)
    strings: List[StringData] = Field(...)


    model_config = ConfigDict(from_attributes=True)

