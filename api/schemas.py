"""
Pydantic request and response schemas for the API.

These models are used for validation and OpenAPI documentation.
"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional


class TokenRequest(BaseModel):
    username: str = Field(..., json_schema_extra={"example": "devuser"})
    password: str = Field(..., json_schema_extra={"example": "password"})


class TokenResponse(BaseModel):
    access_token: str = Field(..., json_schema_extra={"example": "uuid4-token"})
    token_type: str = Field("bearer", json_schema_extra={"example": "bearer"})


class HealthResponse(BaseModel):
    status: str = Field(..., json_schema_extra={"example": "ok"})
    timestamp: datetime


class StringResponse(BaseModel):
    string_id: str
    inverter_id: str
    current_a: float
    voltage_v: float
    power_w: float
    status: str
    timestamp: datetime


class InverterResponse(BaseModel):
    inverter_id: str
    power_w: float
    status: str


class PlantMetricsResponse(BaseModel):
    irradiance_w_m2: float
    ambient_temp_c: float
    panel_temp_c: float


class PlantResponse(BaseModel):
    plant_id: str
    timestamp: datetime
    power_kw: Optional[float]
    energy_today_kwh: Optional[float]
    status: str
    metrics: PlantMetricsResponse
    inverters: List[InverterResponse]
    strings: List[StringResponse]


class ErrorResponse(BaseModel):
    detail: str
