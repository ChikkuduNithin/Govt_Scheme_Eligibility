import math

import httpx

from app.core.config import settings

_OPENROUTESERVICE_URL = (
    "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
)


async def get_eta(origin: dict, destination: dict) -> dict:
    if settings.ROUTING_PROVIDER == "openrouteservice" and settings.ROUTING_API_KEY:
        try:
            return await get_eta_from_routing_api(origin, destination)
        except Exception:
            # Any routing API failure degrades gracefully to the haversine estimate.
            pass
    return await _estimate_eta(origin, destination)


async def _estimate_eta(origin: dict, destination: dict) -> dict:
    distance_km = _haversine_km(
        origin["lat"],
        origin["lng"],
        destination["lat"],
        destination["lng"],
    )
    speed_kmh = settings.AVG_URBAN_SPEED_KMH
    eta_minutes = distance_km / speed_kmh * 60.0
    return {
        "distance_km": round(distance_km, 2),
        "eta_minutes": round(eta_minutes, 1),
        "source": "estimated",
    }


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


async def get_eta_from_routing_api(origin: dict, destination: dict) -> dict:
    """Real road-routing ETA via OpenRouteService.

    Requires `ROUTING_PROVIDER=openrouteservice` and a `ROUTING_API_KEY`.
    Returns the same shape as `get_eta()` but with `source: "routing_api"`.
    """
    headers = {
        "Authorization": settings.ROUTING_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "coordinates": [
            [origin["lng"], origin["lat"]],
            [destination["lng"], destination["lat"]],
        ]
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _OPENROUTESERVICE_URL, json=body, headers=headers
        )
        response.raise_for_status()
        data = response.json()

    segment = data["features"][0]["properties"]["segments"][0]
    distance_m = segment["distance"]
    duration_s = segment["duration"]
    return {
        "distance_km": round(distance_m / 1000.0, 2),
        "eta_minutes": round(duration_s / 60.0, 1),
        "source": "routing_api",
    }
