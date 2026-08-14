import asyncio

import httpx
import pytest

import app.services.eta_service as eta_service
from app.core.config import settings
from app.services.eta_service import get_eta, get_eta_from_routing_api

HYDERABAD_CENTER = {"lat": 17.3850, "lng": 78.4867}

ORS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, data):
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        assert url == ORS_URL
        assert json["coordinates"] == [[1.0, 1.0], [2.0, 2.0]]
        assert headers["Authorization"] == "test-key"
        return FakeResponse(self._data)


def test_same_point_returns_zero():
    result = asyncio.run(get_eta(HYDERABAD_CENTER, dict(HYDERABAD_CENTER)))
    assert result["distance_km"] == 0.0
    assert result["eta_minutes"] == 0.0
    assert result["source"] == "estimated"


def test_known_equator_distance():
    result = asyncio.run(get_eta({"lat": 0.0, "lng": 0.0}, {"lat": 0.0, "lng": 1.0}))
    assert result["distance_km"] == pytest.approx(111.19, abs=1.0)
    assert result["eta_minutes"] == pytest.approx(222.4, abs=2.0)


def test_speed_config_is_applied(monkeypatch):
    monkeypatch.setattr(settings, "AVG_URBAN_SPEED_KMH", 60.0)
    result = asyncio.run(get_eta({"lat": 0.0, "lng": 0.0}, {"lat": 0.0, "lng": 1.0}))
    assert result["eta_minutes"] == pytest.approx(result["distance_km"], abs=0.5)


def test_result_shape():
    result = asyncio.run(get_eta(HYDERABAD_CENTER, {"lat": 17.4332, "lng": 78.4202}))
    assert set(result.keys()) == {"distance_km", "eta_minutes", "source"}
    assert isinstance(result["distance_km"], float)
    assert isinstance(result["eta_minutes"], float)


def test_default_provider_ignores_routing_api(monkeypatch):
    monkeypatch.setattr(settings, "ROUTING_PROVIDER", "haversine")
    monkeypatch.setattr(settings, "ROUTING_API_KEY", "test-key")

    async def fake(origin, destination):
        return {"distance_km": 1.0, "eta_minutes": 1.0, "source": "routing_api"}

    monkeypatch.setattr(eta_service, "get_eta_from_routing_api", fake)
    result = asyncio.run(get_eta(HYDERABAD_CENTER, HYDERABAD_CENTER))
    assert result["source"] == "estimated"


def test_get_eta_uses_routing_api_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ROUTING_PROVIDER", "openrouteservice")
    monkeypatch.setattr(settings, "ROUTING_API_KEY", "test-key")

    async def fake(origin, destination):
        return {"distance_km": 12.34, "eta_minutes": 20.0, "source": "routing_api"}

    monkeypatch.setattr(eta_service, "get_eta_from_routing_api", fake)
    result = asyncio.run(get_eta(HYDERABAD_CENTER, HYDERABAD_CENTER))
    assert result == {"distance_km": 12.34, "eta_minutes": 20.0, "source": "routing_api"}


def test_get_eta_falls_back_when_routing_fails(monkeypatch):
    monkeypatch.setattr(settings, "ROUTING_PROVIDER", "openrouteservice")
    monkeypatch.setattr(settings, "ROUTING_API_KEY", "test-key")

    async def boom(origin, destination):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(eta_service, "get_eta_from_routing_api", boom)
    result = asyncio.run(get_eta({"lat": 0.0, "lng": 0.0}, {"lat": 0.0, "lng": 1.0}))
    assert result["source"] == "estimated"
    assert result["eta_minutes"] == pytest.approx(222.4, abs=2.0)


def test_routing_api_parses_response(monkeypatch):
    monkeypatch.setattr(settings, "ROUTING_API_KEY", "test-key")
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "segments": [{"distance": 15000.0, "duration": 900.0}]
                },
            }
        ],
    }
    monkeypatch.setattr(
        "app.services.eta_service.httpx.AsyncClient", lambda timeout=None: FakeClient(payload)
    )
    result = asyncio.run(
        get_eta_from_routing_api({"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0})
    )
    assert result == {"distance_km": 15.0, "eta_minutes": 15.0, "source": "routing_api"}
