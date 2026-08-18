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

from services.open_routing.constants import (
    AUTOCOMPLETE_CACHE_TTL_SECONDS,
    AUTOCOMPLETE_RESULT_SIZE,
    METERS_PER_MILE,
    REQUEST_TIMEOUT_SECONDS,
    REVERSE_GEOCODE_CACHE_TTL_SECONDS,
    SECONDS_PER_HOUR,
)
from services.open_routing.exceptions import RoutingError
from services.open_routing.helpers import extract_ors_error_message


class OpenRouteServiceClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.ORS_API_KEY
        self.base_url = base_url or settings.ORS_BASE_URL
        self._session = requests.Session()

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
            response = self._session.get(
                f"{self.base_url}/geocode/autocomplete",
                params={"api_key": self.api_key, "text": text, "size": AUTOCOMPLETE_RESULT_SIZE},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except requests.HTTPError as exc:
            raise RoutingError(
                f"OpenRouteService autocomplete failed: {extract_ors_error_message(exc.response)}"
            ) from exc
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
            response = self._session.get(
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
        coordinates = [[lng, lat] for lat, lng in waypoints]

        try:
            response = self._session.post(
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
        except requests.HTTPError as exc:
            raise RoutingError(extract_ors_error_message(exc.response)) from exc
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


_singleton: OpenRouteServiceClient | None = None


def get_client() -> OpenRouteServiceClient:
    """Returns one shared, settings-configured OpenRouteServiceClient per
    worker process, created lazily on first use.

    A singleton is worth it here specifically because the client now holds
    a requests.Session — reusing it across requests keeps the underlying
    TCP/TLS connection to ORS warm instead of renegotiating one on every
    call. It would NOT have been worth it while the client was stateless
    (plain module-level requests.get/post calls) — there'd have been
    nothing to actually share.

    Not implemented as a classic __new__-override singleton, because tests
    (and anything else needing a specific api_key/base_url, e.g. against a
    fake host) still need to construct isolated instances directly via
    OpenRouteServiceClient(...) — a singleton that silently ignored those
    constructor args would break that. This factory is the version of
    "shared instance" that coexists with that need: call get_client() for
    the shared, settings-backed default; construct the class directly for
    anything else.
    """
    global _singleton
    if _singleton is None:
        _singleton = OpenRouteServiceClient()
    return _singleton
