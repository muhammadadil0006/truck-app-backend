"""
The duty-status decision loop: walks one trip forward in time, emitting
segments and map-marker stops as HOS limits are hit.

Check order matters: 70-hour cycle check, then 14-hour window, then 11-hour
driving, then the 30-minute break, then the 1000-mile fuel stop — enforced
by the elif cascade in drive_leg() below.

Internal time bookkeeping uses integer minutes (not float hours, not raw
datetime comparisons) to avoid boundary bugs like `7.999999 >= 8.0`. Wall
clock (an actual datetime, for segment start/end timestamps and day
boundaries) advances alongside the minute counters.

plan_trip() (services/hos_engine/engine.py) is what actually drives one of
these through a trip's current->pickup->dropoff shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from services.constants import (
    BREAK_DURATION_MINUTES,
    BREAK_REQUIRED_AFTER_DRIVING_MINUTES,
    CYCLE_LIMIT_MINUTES,
    FUEL_STOP_DURATION_MINUTES,
    FUEL_STOP_INTERVAL_MILES,
    MANDATORY_OFF_DUTY_MINUTES,
    MAX_DRIVING_MINUTES_PER_DAY,
    MAX_DUTY_WINDOW_MINUTES,
    MINUTES_PER_HOUR,
    RESTART_OFF_DUTY_MINUTES,
    DutyStatus,
    StopType,
)
from services.hos_engine.dataclasses import RouteLeg, Segment, Stop
from services.hos_engine.helpers import round_to_nearest_quarter_hour
from services.hos_engine.route_geometry import build_cumulative_distances, interpolate_point_at_distance

ReverseGeocodeFn = Callable[[float, float], str]


@dataclass
class _Clock:
    """Mutable simulation state, passed through the drive/rest steps instead
    of a pile of nonlocal variables. duty_window_minutes tracks the current
    14-hr window; driving_minutes_this_period tracks elapsed driving since
    the last 10-hr/34-hr reset; driving_minutes_since_break tracks elapsed
    driving since the last qualifying break — three separate clocks because
    each resets under different conditions."""

    wall_clock: datetime
    cycle_used_minutes: int
    duty_window_minutes: int
    driving_minutes_this_period: int
    driving_minutes_since_break: int
    miles_since_fuel: float
    total_miles_driven: float


class _Simulator:
    """Walks one trip forward in time, emitting duty-status segments and
    map-marker stops as HOS limits are hit. See engine.plan_trip() for the
    actual trip-shaped sequence this gets driven through.

    Remarks convention (see CLAUDE.md / the John Doe example): a location is
    logged at the START of each duty-status segment — the point where the
    PREVIOUS status ended. last_stop_label/lat/lng track that point, so a
    driving segment's start location is always already known from whatever
    preceded it, never re-derived by interpolating the segment's own end
    point — which would mislabel it if a later midnight-split cut the
    segment short before it actually reached that point."""

    def __init__(
        self,
        *,
        shift_start: datetime,
        cycle_used_hours: float,
        route_geometry: list[list[float]],
        reverse_geocode: ReverseGeocodeFn,
        start_location_text: str = "",
        start_lat: float = 0.0,
        start_lng: float = 0.0,
    ):
        self.clock = _Clock(
            wall_clock=shift_start,
            cycle_used_minutes=round(cycle_used_hours * MINUTES_PER_HOUR),
            duty_window_minutes=0,
            driving_minutes_this_period=0,
            driving_minutes_since_break=0,
            miles_since_fuel=0.0,
            total_miles_driven=0.0,
        )
        self.route_geometry = route_geometry
        self.cumulative_distances = build_cumulative_distances(route_geometry) if route_geometry else []
        self.reverse_geocode = reverse_geocode
        self.segments: list[Segment] = []
        self.stops: list[Stop] = []

        self.last_stop_label = start_location_text
        self.last_stop_lat = start_lat
        self.last_stop_lng = start_lng

    def _position_at_current_mileage(self) -> tuple[float, float]:
        if not self.route_geometry:
            return (0.0, 0.0)
        return interpolate_point_at_distance(
            self.route_geometry, self.cumulative_distances, self.clock.total_miles_driven
        )

    def _label_at_current_position(self) -> str:
        lat, lng = self._position_at_current_mileage()
        return self.reverse_geocode(lat, lng)

    def _add_segment(
        self,
        status: DutyStatus,
        minutes: float,
        location_text: str,
        lat: float,
        lng: float,
        remarks: str = "",
        miles: float = 0.0,
    ) -> None:
        """Records one duty-status interval. HOS math always uses the
        precise (unrounded) clock; only the stored/displayed timestamps get
        rounded to the nearest quarter hour — so a sub-quarter-hour sliver
        can round away to nothing and simply not appear on the grid, though
        its effect on the counters/mileage below still applies regardless.

        A non-driving interval of at least the break duration satisfies the
        30-minute break requirement regardless of its actual duty status —
        a fuel stop, the pickup/dropoff stop, or a full 10-hr/34-hr reset
        all qualify just as much as a dedicated break does. Any non-driving
        interval also becomes the last known position, so the next driving
        segment (if any) starts from here."""
        start = self.clock.wall_clock
        end = start + timedelta(minutes=minutes)
        display_start = round_to_nearest_quarter_hour(start)
        display_end = round_to_nearest_quarter_hour(end)
        self.clock.wall_clock = end

        if display_start != display_end:
            self.segments.append(
                Segment(
                    status=status,
                    start_time=display_start.isoformat(),
                    end_time=display_end.isoformat(),
                    location_text=location_text,
                    lat=lat,
                    lng=lng,
                    remarks=remarks,
                    miles=miles,
                )
            )

        if status != DutyStatus.DRIVING:
            if minutes >= BREAK_DURATION_MINUTES:
                self.clock.driving_minutes_since_break = 0

            self.last_stop_label = location_text
            self.last_stop_lat = lat
            self.last_stop_lng = lng

    def _add_stop(self, stop_type: StopType, location_text: str, lat: float, lng: float, duration_minutes: float) -> None:
        """Records a map-marker stop — separate from a duty-status segment,
        since not every segment (e.g. a plain 30-min break) is a stop."""
        arrival = round_to_nearest_quarter_hour(self.clock.wall_clock)
        departure = round_to_nearest_quarter_hour(self.clock.wall_clock + timedelta(minutes=duration_minutes))
        self.stops.append(
            Stop(
                type=stop_type,
                location_text=location_text,
                lat=lat,
                lng=lng,
                arrival=arrival.isoformat(),
                departure=departure.isoformat(),
            )
        )

    def _insert_restart_34hr(self) -> None:
        """Zeroes every clock — the full 70-hr/8-day cycle resets."""
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_stop(StopType.RESTART_34HR, label, lat, lng, RESTART_OFF_DUTY_MINUTES)
        self._add_segment(DutyStatus.OFF_DUTY, RESTART_OFF_DUTY_MINUTES, label, lat, lng, "34-hour restart")
        self.clock.cycle_used_minutes = 0
        self.clock.duty_window_minutes = 0
        self.clock.driving_minutes_this_period = 0
        self.clock.driving_minutes_since_break = 0

    def _insert_10hr_reset(self) -> None:
        """Resets the 14-hr window and 11-hr driving clocks; the 70-hr
        cycle total is untouched — only a 34-hr restart clears that."""
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_stop(StopType.REST_10HR, label, lat, lng, MANDATORY_OFF_DUTY_MINUTES)
        self._add_segment(DutyStatus.OFF_DUTY, MANDATORY_OFF_DUTY_MINUTES, label, lat, lng, "10-hour rest")
        self.clock.duty_window_minutes = 0
        self.clock.driving_minutes_this_period = 0
        self.clock.driving_minutes_since_break = 0

    def _insert_30min_break(self) -> None:
        """Clears the break clock only — doesn't touch the window/driving
        clocks, since a break doesn't extend either limit."""
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_segment(DutyStatus.OFF_DUTY, BREAK_DURATION_MINUTES, label, lat, lng, "30-minute break")
        self.clock.duty_window_minutes += BREAK_DURATION_MINUTES

    def _insert_fuel_stop(self) -> None:
        """Resets miles-since-fuel; counts as on-duty time like any other
        working stop, so it still adds to the cycle/window clocks."""
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_stop(StopType.FUEL, label, lat, lng, FUEL_STOP_DURATION_MINUTES)
        self._add_segment(DutyStatus.ON_DUTY_NOT_DRIVING, FUEL_STOP_DURATION_MINUTES, label, lat, lng, "Fuel stop")
        self.clock.cycle_used_minutes += FUEL_STOP_DURATION_MINUTES
        self.clock.duty_window_minutes += FUEL_STOP_DURATION_MINUTES
        self.clock.miles_since_fuel = 0.0

    def drive_leg(self, leg: RouteLeg) -> None:
        """Drives one leg to completion, inserting whatever resets/breaks/
        fuel stops the HOS limits force along the way. Checks run biggest
        limit first — 70hr cycle, then 14hr window, then 11hr driving, then
        the 30-min break, then the 1000mi fuel stop — so nothing gets
        scheduled moments before a bigger reset was already due. Each drive
        chunk runs up to whichever limit is closest, clamped to at least 1
        minute so a rounding edge case can't produce a zero-length chunk
        and loop forever without making progress. A chunk's segment starts
        from last_stop_label/lat/lng (see the class docstring), not from
        interpolating this chunk's own end point."""
        remaining_minutes = round(leg.duration_hours * MINUTES_PER_HOUR)
        if remaining_minutes <= 0 or leg.distance_miles <= 0:
            return

        mph = leg.distance_miles / leg.duration_hours

        while remaining_minutes > 0:
            c = self.clock

            if c.cycle_used_minutes >= CYCLE_LIMIT_MINUTES:
                self._insert_restart_34hr()
                continue
            if c.duty_window_minutes >= MAX_DUTY_WINDOW_MINUTES:
                self._insert_10hr_reset()
                continue
            if c.driving_minutes_this_period >= MAX_DRIVING_MINUTES_PER_DAY:
                self._insert_10hr_reset()
                continue
            if c.driving_minutes_since_break >= BREAK_REQUIRED_AFTER_DRIVING_MINUTES:
                self._insert_30min_break()
                continue
            if c.miles_since_fuel >= FUEL_STOP_INTERVAL_MILES:
                self._insert_fuel_stop()
                continue

            minutes_to_cycle = CYCLE_LIMIT_MINUTES - c.cycle_used_minutes
            minutes_to_window = MAX_DUTY_WINDOW_MINUTES - c.duty_window_minutes
            minutes_to_driving_limit = MAX_DRIVING_MINUTES_PER_DAY - c.driving_minutes_this_period
            minutes_to_break = BREAK_REQUIRED_AFTER_DRIVING_MINUTES - c.driving_minutes_since_break
            minutes_to_fuel = ((FUEL_STOP_INTERVAL_MILES - c.miles_since_fuel) / mph) * MINUTES_PER_HOUR

            chunk_minutes = min(
                remaining_minutes,
                minutes_to_cycle,
                minutes_to_window,
                minutes_to_driving_limit,
                minutes_to_break,
                minutes_to_fuel,
            )
            chunk_minutes = max(chunk_minutes, 1)
            chunk_miles = chunk_minutes / MINUTES_PER_HOUR * mph

            self._add_segment(
                DutyStatus.DRIVING,
                chunk_minutes,
                self.last_stop_label,
                self.last_stop_lat,
                self.last_stop_lng,
                miles=chunk_miles,
            )

            c.cycle_used_minutes += chunk_minutes
            c.duty_window_minutes += chunk_minutes
            c.driving_minutes_this_period += chunk_minutes
            c.driving_minutes_since_break += chunk_minutes
            c.miles_since_fuel += chunk_miles
            c.total_miles_driven += chunk_miles

            remaining_minutes -= chunk_minutes
