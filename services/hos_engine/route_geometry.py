"""
Pure geometry helpers for placing a stop marker at a given cumulative
driving distance along the trip's route polyline — used so fuel/rest/restart
stops land approximately on the actual road, not on a straight line drawn
between waypoints.
"""

from __future__ import annotations

import math

EARTH_RADIUS_MILES = 3958.8


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def build_cumulative_distances(geometry_lnglat: list[list[float]]) -> list[float]:
    """Cumulative miles walked along the polyline at each vertex, index-aligned
    with geometry_lnglat. cumulative[0] == 0.0."""
    cumulative = [0.0]
    for i in range(1, len(geometry_lnglat)):
        lng1, lat1 = geometry_lnglat[i - 1]
        lng2, lat2 = geometry_lnglat[i]
        cumulative.append(cumulative[-1] + _haversine_miles(lat1, lng1, lat2, lng2))
    return cumulative


def interpolate_point_at_distance(
    geometry_lnglat: list[list[float]],
    cumulative_distances: list[float],
    target_miles: float,
) -> tuple[float, float]:
    """Returns (lat, lng) at the given cumulative distance along the route.
    Clamps target_miles to [0, total route distance]."""
    if not geometry_lnglat:
        raise ValueError("geometry_lnglat must not be empty")

    total = cumulative_distances[-1]
    target = max(0.0, min(target_miles, total))

    for i in range(1, len(cumulative_distances)):
        if cumulative_distances[i] >= target:
            seg_start, seg_end = cumulative_distances[i - 1], cumulative_distances[i]
            lng1, lat1 = geometry_lnglat[i - 1]
            lng2, lat2 = geometry_lnglat[i]
            if seg_end == seg_start:
                return lat1, lng1
            fraction = (target - seg_start) / (seg_end - seg_start)
            return lat1 + (lat2 - lat1) * fraction, lng1 + (lng2 - lng1) * fraction

    lng, lat = geometry_lnglat[-1]
    return lat, lng
