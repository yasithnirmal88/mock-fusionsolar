"""
API router placeholders.

This module exposes an APIRouter instance that will be used to register
endpoints in later iterations. For the MVP there are intentionally no routes.
"""
from fastapi import APIRouter

router = APIRouter()

# Example:
# @router.get("/health")
# async def health():
#     return {"status": "ok"}
