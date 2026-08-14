"""
Application factory and wiring.

This module provides create_app() which returns a FastAPI instance. Endpoints
are registered through routers, and long-lived resources are managed using 
a unified lifespan context manager.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI

from core.logger import configure_logging
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle tasks for startup and shutdown."""
    # --- STARTUP ACTIONS ---
    # Ensure logging has been configured
    configure_logging(settings.LOG_LEVEL)
    
    # Initialize provider early so background simulator thread is created once
    try:
        from services.provider_factory import ProviderFactory

        ProviderFactory.get_provider()
    except Exception:
        # Log and continue startup
        from core.logger import get_logger

        get_logger(__name__).exception("Error initializing provider at startup")

    yield  # Application handles requests here

    # --- SHUTDOWN ACTIONS ---
    # If the configured provider exposes a stop() method, call it to clean up background threads
    try:
        from services.provider_factory import ProviderFactory

        provider = ProviderFactory.get_provider()
        stop = getattr(provider, "stop", None)
        if callable(stop):
            stop()
    except Exception:
        # Log and continue shutdown
        from core.logger import get_logger

        get_logger(__name__).exception("Error during shutdown cleanup")


def create_app() -> FastAPI:
    """Create and configure a FastAPI application.

    The app registers routes and lifecycle hooks.
    """
    configure_logging(settings.LOG_LEVEL)

    # Initialize FastAPI with the lifespan handler to replace deprecated on_event hooks
    app = FastAPI(title="Solar Simulator (MVP)", lifespan=lifespan)

    # Register API routes
    from api.routes import router as api_router

    app.include_router(api_router, prefix="/api")

    return app
