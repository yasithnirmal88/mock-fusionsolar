"""
API route implementations.

Routes intentionally communicate only with AbstractDataProvider via the
service layer. Authentication is provided by services.auth_service.validate_token
used as a dependency on protected endpoints.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List

from services.provider_factory import ProviderFactory
from services.provider_service import ProviderService
from services.auth_service import auth_service
from api.schemas import (
    AnomalyEventResponse,
    AnomalyLogResponse,
    ErrorResponse,
    HealthResponse,
    HistoryResponse,
    HistoryStringPoint,
    HistoryWeatherPoint,
    HistoryWeatherResponse,
    PlantResponse,
    InverterResponse,
    StringResponse,
    TokenRequest,
    TokenResponse,
)

router = APIRouter()

# Security scheme for OpenAPI / Swagger UI (adds Authorize button)
bearer_scheme = HTTPBearer(auto_error=False)


def _get_service() -> ProviderService:
    # ProviderFactory returns an AbstractDataProvider; ProviderService depends on the abstraction.
    # We intentionally create a new provider/service per-request here to avoid
    # exposing provider implementation details and to keep lifecycle management
    # delegated to the ProviderFactory and app startup/shutdown hooks.
    provider = ProviderFactory.get_provider()
    return ProviderService(provider=provider)


@router.get("/health", response_model=HealthResponse, responses={401: {"model": ErrorResponse}})
def health() -> HealthResponse:
    """Health check endpoint (public).

    Returns current service status and timestamp.
    """
    from datetime import datetime, timezone

    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@router.post("/auth/login", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
def login(payload: TokenRequest) -> TokenResponse:
    """Fake login: accepts any username/password and returns a bearer token.

    This endpoint returns a token that must be supplied as "Authorization: Bearer <token>"
    for protected endpoints.
    """
    token = auth_service.login(payload.username, payload.password)
    return TokenResponse(access_token=token, token_type="bearer")


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme)) -> str:
    """FastAPI dependency that validates a bearer token using AuthService.

    This integrates with FastAPI's HTTPBearer security scheme so Swagger UI
    exposes the Authorize button. The dependency returns the username for the
    authenticated user or raises HTTPException(401) if the token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    token = credentials.credentials
    try:
        username = auth_service.validate_token(token)
    except HTTPException:
        # Re-raise HTTPExceptions from auth_service.validate_token
        raise
    return username


@router.get("/plants/{plant_id}", response_model=PlantResponse, responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
def get_plant(plant_id: str, request_user: str = Depends(get_current_user)) -> PlantResponse:
    """Return current plant status and aggregated data.

    Protected endpoint; requires Authorization: Bearer <token> header.
    """
    service = _get_service()
    try:
        pd = service.fetch_plant_data(plant_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Return a plain dict so FastAPI/Pydantic will validate and convert values
    # against the response_model. Use compatibility helper to support pydantic v1/v2.
    from core.pydantic_utils import model_to_dict

    return model_to_dict(pd)


@router.get("/plants/{plant_id}/inverters", response_model=List[InverterResponse], responses={401: {"model": ErrorResponse}})
def get_inverters(plant_id: str, request_user: str = Depends(get_current_user)) -> List[InverterResponse]:
    """Return current inverter-level data for the plant."""
    service = _get_service()
    pd = service.fetch_plant_data(plant_id)
    from core.pydantic_utils import model_to_dict

    return [model_to_dict(inv) for inv in pd.inverters]


@router.get("/plants/{plant_id}/strings", response_model=List[StringResponse], responses={401: {"model": ErrorResponse}})
def get_strings(plant_id: str, request_user: str = Depends(get_current_user)) -> List[StringResponse]:
    """Return list of string measurements for the plant."""
    service = _get_service()
    pd = service.fetch_plant_data(plant_id)
    from core.pydantic_utils import model_to_dict

    return [model_to_dict(s) for s in pd.strings]


@router.get("/plants/{plant_id}/strings/{string_id}", response_model=StringResponse, responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
def get_string(plant_id: str, string_id: str, request_user: str = Depends(get_current_user)) -> StringResponse:
    """Return the latest measurement for a single string."""
    service = _get_service()
    pd = service.fetch_plant_data(plant_id)
    for s in pd.strings:
        if s.string_id == string_id:
            from core.pydantic_utils import model_to_dict

            return model_to_dict(s)
    raise HTTPException(status_code=404, detail=f"String {string_id} not found")


# ───────────────────────────── historical data ──────────────────────────────
# These endpoints expose the simulated 90-day historical dataset so Scarda can
# backfill its own time-series store through the API (exactly as it will later
# pull KPI history from the real Huawei Northbound API). Scarda must never
# touch this project's data layer directly.

from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402

from history.cache import (  # noqa: E402
    anomaly_events,
    dataset,
    history_between,
    weather_between,
)
from history.generator import HistoryConfig  # noqa: E402


def _parse_range(start: str | None, end: str | None):
    """Parse ISO start/end query params, defaulting to the full dataset span."""
    cfg = HistoryConfig()
    data = dataset()
    if not data:
        return _dt.now(_tz.utc), _dt.now(_tz.utc)
    default_start = data[0].timestamp
    default_end = data[-1].timestamp + _td(minutes=cfg.interval_minutes)
    s = _dt.fromisoformat(start) if start else default_start
    e = _dt.fromisoformat(end) if end else default_end
    if s.tzinfo is None:
        s = s.replace(tzinfo=_tz.utc)
    if e.tzinfo is None:
        e = e.replace(tzinfo=_tz.utc)
    return s, e


@router.get(
    "/plants/{plant_id}/history",
    response_model=HistoryResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_plant_history(
    plant_id: str,
    start: str | None = None,
    end: str | None = None,
    request_user: str = Depends(get_current_user),
) -> HistoryResponse:
    """Return timestamped historical string readings within [start, end).

    Each point carries its original measurement timestamp, irradiance,
    temperature and per-string power/voltage/current. Scarda stores these with
    their original timestamps so historical baselines and trend analysis work.
    """
    s, e = _parse_range(start, end)
    window = history_between(s, e)
    points: List[HistoryStringPoint] = []
    for pd in window:
        for st in pd.strings:
            points.append(
                HistoryStringPoint(
                    timestamp=pd.timestamp,
                    string_id=st.string_id,
                    inverter_id=st.inverter_id,
                    current_a=st.current_a,
                    voltage_v=st.voltage_v,
                    power_w=st.power_w,
                    status=st.status,
                    irradiance_w_m2=pd.metrics.irradiance_w_m2,
                    ambient_temp_c=pd.metrics.ambient_temp_c,
                    panel_temp_c=pd.metrics.panel_temp_c,
                )
            )
    return HistoryResponse(
        plant_id=plant_id,
        start=s,
        end=e,
        interval_minutes=HistoryConfig().interval_minutes,
        count=len(points),
        data=points,
    )


@router.get(
    "/plants/{plant_id}/weather/history",
    response_model=HistoryWeatherResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_plant_weather_history(
    plant_id: str,
    start: str | None = None,
    end: str | None = None,
    request_user: str = Depends(get_current_user),
) -> HistoryWeatherResponse:
    """Return timestamped historical plant weather samples within [start, end)."""
    s, e = _parse_range(start, end)
    window = weather_between(s, e)
    points = [
        HistoryWeatherPoint(
            timestamp=pd.timestamp,
            irradiance_w_m2=pd.metrics.irradiance_w_m2,
            ambient_temp_c=pd.metrics.ambient_temp_c,
            panel_temp_c=pd.metrics.panel_temp_c,
            power_kw=pd.power_kw or 0.0,
            energy_today_kwh=pd.energy_today_kwh or 0.0,
        )
        for pd in window
    ]
    return HistoryWeatherResponse(
        plant_id=plant_id,
        start=s,
        end=e,
        count=len(points),
        data=points,
    )


@router.get(
    "/plants/{plant_id}/anomalies",
    response_model=AnomalyLogResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_anomaly_log(
    plant_id: str,
    request_user: str = Depends(get_current_user),
) -> AnomalyLogResponse:
    """Document the timestamps and entities where anomalies were injected.

    Scarda's acceptance tests use this to verify a degraded string / offline
    inverter are detected, and that the cloudy period is NOT flagged.
    """
    return AnomalyLogResponse(
        plant_id=plant_id,
        anomalies=[AnomalyEventResponse(**ev.to_dict()) for ev in anomaly_events()],
    )
