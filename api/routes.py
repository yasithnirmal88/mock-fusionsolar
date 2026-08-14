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
    HealthResponse,
    TokenRequest,
    TokenResponse,
    PlantResponse,
    InverterResponse,
    StringResponse,
    ErrorResponse,
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
