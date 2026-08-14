"""
Compatibility helpers for Pydantic v1 and v2.

Provide small utility functions to convert models to plain dictionaries in a
version-agnostic way and to provide a compatible model config helper.
"""
from __future__ import annotations
from typing import Any


def model_to_dict(model: Any) -> dict:
    """Convert a Pydantic model instance to a plain dict in a way that works
    with both Pydantic v1 (model.dict()) and v2 (model.model_dump()).
    """
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    # Fallback: try to use __dict__ and exclude private attrs
    return {k: v for k, v in getattr(model, "__dict__", {}).items() if not k.startswith("_")}
