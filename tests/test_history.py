"""Tests for the Mock FusionSolar simulator and historical dataset.

Run with: pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def client():
    import main  # noqa: F401
    from services.provider_factory import ProviderFactory

    try:
        ProviderFactory.reset_provider()
    except Exception:
        pass
    with TestClient(main.app) as c:  # type: ignore[arg-type]
        yield c
    try:
        ProviderFactory.reset_provider()
    except Exception:
        pass


def _auth_headers(client):
    r = client.post("/api/auth/login", json={"username": "huawei", "password": "huawei"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ────────────────────────────── generator ───────────────────────────────────

class TestGenerator:
    def test_history_is_timestamped_and_diurnal(self) -> None:
        from history.generator import HistoryConfig, generate_history

        data = generate_history(HistoryConfig(days=2, interval_minutes=60))
        assert len(data) > 0
        assert len(data[0].strings) == 40
        for a, b in zip(data, data[1:]):
            assert b.timestamp > a.timestamp
        assert data[0].timestamp.tzinfo is not None

    def test_power_follows_irradiance(self) -> None:
        from history.generator import HistoryConfig, generate_history

        data = generate_history(HistoryConfig(days=3, interval_minutes=30))
        violations = 0
        for a, b in zip(data, data[1:]):
            if b.metrics.irradiance_w_m2 < a.metrics.irradiance_w_m2 - 50:
                if b.power_kw > a.power_kw + 1.0:
                    violations += 1
        assert violations < len(data) * 0.1

    def test_night_near_zero(self) -> None:
        from history.generator import HistoryConfig, generate_history

        data = generate_history(HistoryConfig(days=2, interval_minutes=60))
        night = [d for d in data if d.metrics.irradiance_w_m2 <= 20.0]
        assert night
        for d in night:
            assert d.power_kw == 0.0
            for s in d.strings:
                assert s.power_w == 0.0

    def test_anomalies_documented(self) -> None:
        from history.generator import HistoryConfig, get_anomaly_log

        log = get_anomaly_log(HistoryConfig(days=2, interval_minutes=60))
        kinds = {e.kind for e in log}
        assert kinds == {"degraded_string", "offline_inverter", "cloudy_period"}
        for e in log:
            assert e.entity
            assert e.end > e.start


# ──────────────────────────────── API ───────────────────────────────────────

class TestLiveApi:
    def test_health(self, client) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_plant_snapshot(self, client) -> None:
        h = _auth_headers(client)
        r = client.get("/api/plants/sim-plant-001", headers=h)
        assert r.status_code == 200
        pd = r.json()
        assert pd["plant_id"] == "sim-plant-001"
        assert len(pd["strings"]) > 0
        assert "metrics" in pd


class TestHistoryApi:
    def test_history_requires_auth(self, client) -> None:
        r = client.get("/api/plants/sim-plant-001/history")
        assert r.status_code == 401

    def test_history_returns_timestamped_points(self, client) -> None:
        h = _auth_headers(client)
        r = client.get("/api/plants/sim-plant-001/history", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plant_id"] == "sim-plant-001"
        assert body["count"] > 0
        assert body["count"] == len(body["data"])
        p = body["data"][0]
        for key in (
            "timestamp", "string_id", "inverter_id", "current_a",
            "voltage_v", "power_w", "irradiance_w_m2", "ambient_temp_c",
        ):
            assert key in p

    def test_history_range_filter(self, client) -> None:
        h = _auth_headers(client)
        full = client.get("/api/plants/sim-plant-001/history", headers=h).json()
        first_ts = full["data"][0]["timestamp"]
        end = full["data"][-1]["timestamp"]
        r = client.get(
            f"/api/plants/sim-plant-001/history?start={first_ts}&end={end}",
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["count"] <= full["count"]

    def test_weather_history(self, client) -> None:
        h = _auth_headers(client)
        r = client.get("/api/plants/sim-plant-001/weather/history", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["count"] > 0
        assert "irradiance_w_m2" in body["data"][0]

    def test_anomaly_log_endpoint(self, client) -> None:
        h = _auth_headers(client)
        r = client.get("/api/plants/sim-plant-001/anomalies", headers=h)
        assert r.status_code == 200
        anomalies = r.json()["anomalies"]
        kinds = {a["kind"] for a in anomalies}
        assert "degraded_string" in kinds
        assert "cloudy_period" in kinds


# ─────────────────── verify injected anomalies are real ─────────────────────

class TestInjectedAnomalies:
    def test_degraded_string_underproduces(self) -> None:
        from history.generator import HistoryConfig, generate_history, get_anomaly_log

        cfg = HistoryConfig(days=10, interval_minutes=30)
        data = generate_history(cfg)
        log = get_anomaly_log(cfg)
        deg = next(e for e in log if e.kind == "degraded_string")
        target = deg.entity

        snap = next(
            d for d in data
            if deg.start <= d.timestamp < deg.end and d.metrics.irradiance_w_m2 > 200
        )
        by_id = {s.string_id: s for s in snap.strings}
        target_power = by_id[target].power_w
        sibling = next(
            s.string_id for s in snap.strings
            if s.inverter_id == by_id[target].inverter_id and s.string_id != target
        )
        sibling_power = by_id[sibling].power_w
        assert target_power < sibling_power * 0.6, (
            f"degraded {target_power=} should be <60% of sibling {sibling_power=}"
        )

    def test_offline_inverter_zero_power(self) -> None:
        from history.generator import HistoryConfig, generate_history, get_anomaly_log

        cfg = HistoryConfig(days=10, interval_minutes=30)
        data = generate_history(cfg)
        log = get_anomaly_log(cfg)
        off = next(e for e in log if e.kind == "offline_inverter")
        snap = next(
            d for d in data
            if off.start <= d.timestamp < off.end and d.metrics.irradiance_w_m2 > 200
        )
        inv = next(i for i in snap.inverters if i.inverter_id == off.entity)
        assert inv.power_w == 0.0
        assert inv.status == "offline"

    def test_cloudy_period_is_not_a_fault(self) -> None:
        from history.generator import HistoryConfig, generate_history, get_anomaly_log

        cfg = HistoryConfig(days=10, interval_minutes=30)
        data = generate_history(cfg)
        log = get_anomaly_log(cfg)
        cloudy = next(e for e in log if e.kind == "cloudy_period")

        cloudy_snaps = [
            d for d in data
            if cloudy.start <= d.timestamp < cloudy.end and d.metrics.irradiance_w_m2 > 50
        ]
        assert cloudy_snaps, "cloudy window should contain daylight samples"
        for d in cloudy_snaps:
            for s in d.strings:
                if d.metrics.irradiance_w_m2 > 0 and s.status == "ok":
                    ratio = s.power_w / d.metrics.irradiance_w_m2
                    assert 0.05 < ratio < 0.6
