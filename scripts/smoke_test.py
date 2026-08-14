"""
Smoke test script that exercises the main API using FastAPI's TestClient.

This script programmatically performs the manual steps you would do in /docs:
- GET /api/health
- POST /api/auth/login
- GET /api/plants/sim-plant-001 (with token)
- GET /api/plants/.../strings
- GET single string
"""
from __future__ import annotations
import json

from fastapi.testclient import TestClient

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app
from services.provider_factory import ProviderFactory


def test_smoke_workflow():
    """Execute the full end-to-end API smoke test using pytest assertions."""
    # Reset provider cache to ensure a fresh simulator instance
    try:
        ProviderFactory.reset_provider()
    except Exception:
        pass

    with TestClient(app) as client:
        # 1. Health Check
        r = client.get("/api/health")
        print("GET /api/health ->", r.status_code)
        assert r.status_code == 200, f"Health check failed: {r.text}"
        print(r.json())

        # 2. Authentication Login
        r = client.post("/api/auth/login", json={"username": "tester", "password": "x"})
        print("POST /api/auth/login ->", r.status_code)
        assert r.status_code == 200, f"Login failed: {r.text}"
        
        token = r.json().get("access_token")
        assert token is not None, "Authentication did not return an access token"
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Retrieve Plant Metrics
        r = client.get("/api/plants/sim-plant-001", headers=headers)
        print("GET /api/plants/sim-plant-001 ->", r.status_code)
        assert r.status_code == 200, f"Failed to get plant details: {r.text}"
        pd = r.json()
        print("Plant keys:", list(pd.keys()))

        # 4. Fetch Strings Associated with Plant
        r = client.get("/api/plants/sim-plant-001/strings", headers=headers)
        print("GET /api/plants/sim-plant-001/strings ->", r.status_code)
        assert r.status_code == 200, f"Failed to fetch strings list: {r.text}"
        strings = r.json()
        print(f"strings count: {len(strings)}")
        assert len(strings) > 0, "The application returned an empty string collection"

        # 5. Extract Details for a Single String Instance
        first_id = strings[0]["string_id"]
        r = client.get(f"/api/plants/sim-plant-001/strings/{first_id}", headers=headers)
        print(f"GET single string {first_id} ->", r.status_code)
        assert r.status_code == 200, f"Failed to query details for string {first_id}: {r.text}"
        s = r.json()
        print(json.dumps(s, indent=2))

    # Clean up provider
    try:
        ProviderFactory.reset_provider()
    except Exception:
        pass

    print("Smoke test completed successfully")

