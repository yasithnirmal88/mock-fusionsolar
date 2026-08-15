"""Application entrypoint.

Creates the FastAPI application via the factory in ``app`` and exposes it as
``app`` for ``uvicorn main:app``.

Run locally:

    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

from app import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn
    from config import settings

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
