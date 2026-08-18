from __future__ import annotations

from datetime import datetime, timedelta

from services.hos_engine.constants import QUARTER_HOUR_MINUTES, SECONDS_PER_MINUTE
from services.hos_engine.dataclasses import Segment


def default_reverse_geocode(lat: float, lng: float) -> str:
    """Fallback for when no real reverse-geocoder is injected (e.g. tests)
    — a plain coordinate label instead of a network call."""
    return f"{lat:.4f}, {lng:.4f}"


def round_to_nearest_quarter_hour(dt: datetime) -> datetime:
    """Rounds a timestamp to the nearest :00/:15/:30/:45, matching how a
    real ELD log gets filled in. Only ever applied to DISPLAYED timestamps
    — HOS limit math always runs on the unrounded clock, so this rounding
    can never drift across a multi-day trip."""
    discard = timedelta(minutes=dt.minute % QUARTER_HOUR_MINUTES, seconds=dt.second, microseconds=dt.microsecond)
    rounded = dt - discard
    if discard >= timedelta(minutes=QUARTER_HOUR_MINUTES / 2):
        rounded += timedelta(minutes=QUARTER_HOUR_MINUTES)
    return rounded


def duration_minutes(segment: Segment) -> float:
    """A segment's length in minutes, from its own start/end timestamps."""
    start = datetime.fromisoformat(segment.start_time)
    end = datetime.fromisoformat(segment.end_time)
    return (end - start).total_seconds() / SECONDS_PER_MINUTE
