"""
Application-specific exceptions.

Place for domain and infrastructure exceptions that can be handled by the API
layer.
"""
from typing import Any


class ProviderError(Exception):
    """Raised when a provider implementation fails to fetch or transform data."""


class ConfigurationError(Exception):
    """Raised when application configuration is invalid or missing."""
