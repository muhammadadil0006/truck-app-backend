"""
Thin wrapper around OpenRouteService (ORS) for location autocomplete,
directions, and reverse geocoding.

Why ORS: single free API key covers all three (2,000 req/day free, no card
required at signup) — see PLANNING.md's "Map/Routing API" decision for the
full reasoning and rejected alternatives (Nominatim/public-OSRM demo server
explicitly disallow production use; Mapbox requires a card at signup).

Why autocomplete-only, no free-text geocode-by-address for trip creation:
the frontend never sends raw location text for current/pickup/dropoff —
LocationAutocomplete.tsx resolves an exact (text, lat, lng) via the
/api/geocode/ proxy endpoint (backed by autocomplete() below) at selection
time, and that exact point is what gets submitted. This removes an entire
class of bugs where the frontend's displayed suggestion and a second,
independent backend re-geocode of the same text resolve to two different
places.

reverse_geocode() is used by the HOS engine to label mid-route stops (fuel,
rest, restart) with a real city/state, per CLAUDE.md's requirement that the
Remarks section show a location at every duty-status change — these points
fall between waypoints, so there's no user-provided text for them.

Repeated identical autocomplete/reverse-geocode lookups are cached via
Django's cache framework (LocMemCache — see config/settings.py's CACHES; no
Redis needed for this) to avoid burning the free daily quota.
"""

from __future__ import annotations

import requests
from django.conf import settings
from django.core.cache import cache

from services.routing.exceptions import RoutingError

AUTOCOMPLETE_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h — place names don't change
REVERSE_GEOCODE_CACHE_TTL_SECONDS = 60 * 60 * 24
AUTOCOMPLETE_RESULT_SIZE = 8
REQUEST_TIMEOUT_SECONDS = 8

METERS_PER_MILE = 1609.34
SECONDS_PER_HOUR = 3600


class OpenRouteServiceClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.ORS_API_KEY
        self.base_url = base_url or settings.ORS_BASE_URL

    def autocomplete(self, text: str) -> list[dict]:
        """Return up to AUTOCOMPLETE_RESULT_SIZE place suggestions for the
        given partial text, as [{"label": str, "lat": float, "lng": float}].

        Returns an empty list on no matches (not an error — the frontend
        just shows "no results"). Raises RoutingError on a genuine API
        failure (non-2xx, timeout, malformed body).
        """
        cache_key = f"ors_autocomplete:{text.strip().lower()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            response = requests.get(
                f"{self.base_url}/geocode/autocomplete",
                params={"api_key": self.api_key, "text": text, "size": AUTOCOMPLETE_RESULT_SIZE},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RoutingError(f"OpenRouteService autocomplete failed: {exc}") from exc

        suggestions = [
            {
                "label": feature["properties"]["label"],
                "lat": feature["geometry"]["coordinates"][1],
                "lng": feature["geometry"]["coordinates"][0],
            }
            for feature in body.get("features", [])
        ]

        cache.set(cache_key, suggestions, AUTOCOMPLETE_CACHE_TTL_SECONDS)
        return suggestions

    def reverse_geocode(self, lat: float, lng: float) -> str:
        """Best-effort place label for a coordinate that wasn't picked by
        the user (e.g. a fuel stop mid-route). Degrades to a plain
        coordinate string on any failure or no-match rather than raising —
        a missing Remarks label shouldn't fail the whole trip plan."""
        cache_key = f"ors_reverse:{round(lat, 3)}:{round(lng, 3)}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            response = requests.get(
                f"{self.base_url}/geocode/reverse",
                params={"api_key": self.api_key, "point.lat": lat, "point.lon": lng, "size": 1},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            features = response.json().get("features", [])
            label = features[0]["properties"]["label"] if features else f"{lat:.4f}, {lng:.4f}"
        except (requests.RequestException, ValueError, KeyError, IndexError):
            label = f"{lat:.4f}, {lng:.4f}"

        cache.set(cache_key, label, REVERSE_GEOCODE_CACHE_TTL_SECONDS)
        return label

    def get_route(self, waypoints: list[tuple[float, float]]) -> dict:
        """waypoints: [(lat, lng), ...] in visit order (>= 2 points).

        Returns:
            {
                "distance_miles": float,   # total across all legs
                "duration_hours": float,   # total across all legs
                "geometry": [[lng, lat], ...],  # full route polyline, GeoJSON order
                "legs": [{"distance_miles": float, "duration_hours": float}, ...],
            }
        One leg per consecutive waypoint pair, in the same order as `waypoints`.

        Raises RoutingError on non-2xx response, timeout, or malformed body.
        """
        coordinates = [[lng, lat] for lat, lng in waypoints]  # ORS wants [lng, lat]

        try:
            response = requests.post(
                f"{self.base_url}/v2/directions/driving-car/geojson",
                headers={"Authorization": self.api_key, "Content-Type": "application/json"},
                json={"coordinates": coordinates},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
            feature = body["features"][0]
            segments = feature["properties"]["segments"]
            summary = feature["properties"]["summary"]
            geometry = feature["geometry"]["coordinates"]
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            raise RoutingError(f"OpenRouteService directions failed: {exc}") from exc

        return {
            "distance_miles": summary["distance"] / METERS_PER_MILE,
            "duration_hours": summary["duration"] / SECONDS_PER_HOUR,
            "geometry": geometry,
            "legs": [
                {
                    "distance_miles": seg["distance"] / METERS_PER_MILE,
                    "duration_hours": seg["duration"] / SECONDS_PER_HOUR,
                }
                for seg in segments
            ],
        }
