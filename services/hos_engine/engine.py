"""
The trip-planning entrypoint: plan_trip() drives one _Simulator (see
services/hos_engine/simulator.py) through a trip's actual shape —
current->pickup->dropoff — and hands the result to log_splitter to turn
into daily pages.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from services.constants import DROPOFF_DURATION_MINUTES, PICKUP_DURATION_MINUTES, DutyStatus, StopType
from services.hos_engine.constants import SECONDS_PER_MINUTE
from services.hos_engine.dataclasses import RouteLeg, SimulationResult
from services.hos_engine.helpers import default_reverse_geocode
from services.hos_engine.log_splitter import split_into_daily_summaries
from services.hos_engine.simulator import ReverseGeocodeFn, _Simulator


def plan_trip(
    *,
    current_lat: float,
    current_lng: float,
    current_location_text: str,
    pickup_lat: float,
    pickup_lng: float,
    pickup_location_text: str,
    dropoff_lat: float,
    dropoff_lng: float,
    dropoff_location_text: str,
    cycle_used_hours: float,
    route_geometry: list[list[float]],
    leg_current_to_pickup: RouteLeg,
    leg_pickup_to_dropoff: RouteLeg,
    shift_start: str,
    reverse_geocode: ReverseGeocodeFn | None = None,
) -> SimulationResult:
    """Runs the full simulation for one trip: current->pickup (a real
    driving leg, burns HOS hours like any other driving) -> 1hr pickup ->
    pickup->dropoff -> 1hr dropoff, with a leading/trailing OFF_DUTY block
    so day 1 and the final day both sum to 24 hours — without the leading
    block, day 1's segments would start mid-day and never sum to 24,
    violating CLAUDE.md's "total hours per row must sum to 24" requirement.
    Returns everything needed to persist a Trip + its DailyLogs and render
    the map + log sheets.

    shift_start is an ISO 8601 string — the actual moment the trip was
    submitted.
    """
    sim = _Simulator(
        shift_start=datetime.fromisoformat(shift_start),
        cycle_used_hours=cycle_used_hours,
        route_geometry=route_geometry,
        reverse_geocode=reverse_geocode or default_reverse_geocode,
        start_location_text=current_location_text,
        start_lat=current_lat,
        start_lng=current_lng,
    )

    start_of_day = datetime.combine(sim.clock.wall_clock.date(), datetime.min.time())
    if start_of_day < sim.clock.wall_clock:
        leading_off_duty_minutes = (sim.clock.wall_clock - start_of_day).total_seconds() / SECONDS_PER_MINUTE
        sim.clock.wall_clock = start_of_day
        sim._add_segment(DutyStatus.OFF_DUTY, leading_off_duty_minutes, current_location_text, current_lat, current_lng)

    sim.drive_leg(leg_current_to_pickup)

    sim._add_stop(StopType.PICKUP, pickup_location_text, pickup_lat, pickup_lng, PICKUP_DURATION_MINUTES)
    sim._add_segment(
        DutyStatus.ON_DUTY_NOT_DRIVING, PICKUP_DURATION_MINUTES, pickup_location_text, pickup_lat, pickup_lng, "Pickup"
    )
    sim.clock.cycle_used_minutes += PICKUP_DURATION_MINUTES
    sim.clock.duty_window_minutes += PICKUP_DURATION_MINUTES

    sim.drive_leg(leg_pickup_to_dropoff)

    sim._add_stop(StopType.DROPOFF, dropoff_location_text, dropoff_lat, dropoff_lng, DROPOFF_DURATION_MINUTES)
    sim._add_segment(
        DutyStatus.ON_DUTY_NOT_DRIVING,
        DROPOFF_DURATION_MINUTES,
        dropoff_location_text,
        dropoff_lat,
        dropoff_lng,
        "Dropoff",
    )
    sim.clock.cycle_used_minutes += DROPOFF_DURATION_MINUTES
    sim.clock.duty_window_minutes += DROPOFF_DURATION_MINUTES

    end_of_day = datetime.combine(sim.clock.wall_clock.date(), datetime.min.time()) + timedelta(days=1)
    if sim.clock.wall_clock < end_of_day:
        remaining_minutes = (end_of_day - sim.clock.wall_clock).total_seconds() / SECONDS_PER_MINUTE
        sim._add_segment(
            DutyStatus.OFF_DUTY, remaining_minutes, dropoff_location_text, dropoff_lat, dropoff_lng, "Trip complete"
        )

    daily_summaries = split_into_daily_summaries(sim.segments, cycle_used_hours)

    return SimulationResult(
        total_distance_miles=round(leg_current_to_pickup.distance_miles + leg_pickup_to_dropoff.distance_miles, 2),
        total_duration_hours=round(leg_current_to_pickup.duration_hours + leg_pickup_to_dropoff.duration_hours, 2),
        route_geometry=route_geometry,
        stops=sim.stops,
        daily_summaries=daily_summaries,
    )
