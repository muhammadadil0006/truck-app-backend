"""
The trip-planning / HOS-compliance simulator.

Implements the decision loop documented in ../../ALGORITHM-GUIDE.md section 2
("The Duty-Status Simulator — Decision Loop"), using the thresholds from
services.constants exclusively (no magic numbers here).

Check order matters (see ALGORITHM-GUIDE.md's note under the flowchart):
70-hour cycle check, then 14-hour window, then 11-hour driving, then the
30-minute break, then the 1000-mile fuel stop — enforced by the elif cascade
in _drive_leg() below.

Internal time bookkeeping uses integer minutes (not float hours, not raw
datetime comparisons) to avoid boundary bugs like `7.999999 >= 8.0`. Wall
clock (an actual datetime, for segment start/end timestamps and day
boundaries) advances alongside the minute counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from services.constants import (
    BREAK_DURATION_MINUTES,
    BREAK_REQUIRED_AFTER_DRIVING_MINUTES,
    CYCLE_LIMIT_MINUTES,
    DROPOFF_DURATION_MINUTES,
    DutyStatus,
    FUEL_STOP_DURATION_MINUTES,
    FUEL_STOP_INTERVAL_MILES,
    MANDATORY_OFF_DUTY_MINUTES,
    MAX_DRIVING_MINUTES_PER_DAY,
    MAX_DUTY_WINDOW_MINUTES,
    MINUTES_PER_HOUR,
    PICKUP_DURATION_MINUTES,
    RESTART_OFF_DUTY_MINUTES,
    StopType,
)
from services.hos_engine.dataclasses import RouteLeg, Segment, SimulationResult, Stop
from services.hos_engine.log_splitter import split_into_daily_summaries
from services.hos_engine.route_geometry import build_cumulative_distances, interpolate_point_at_distance

ReverseGeocodeFn = Callable[[float, float], str]


def _default_reverse_geocode(lat: float, lng: float) -> str:
    """Fallback used when no real reverse-geocoder is injected (e.g. unit
    tests) — a plain coordinate label instead of a network call."""
    return f"{lat:.4f}, {lng:.4f}"


QUARTER_HOUR_MINUTES = 15


def _round_to_nearest_quarter_hour(dt: datetime) -> datetime:
    """Real drivers fill paper/ELD logs to the nearest 15 minutes, not the
    second — every segment boundary shown on the grid must land on :00,
    :15, :30, or :45. Applied only to the DISPLAYED timestamps (see
    _add_segment): the internal wall_clock stays minute-precise so HOS
    limit math never drifts across a long multi-day trip."""
    discard = timedelta(
        minutes=dt.minute % QUARTER_HOUR_MINUTES, seconds=dt.second, microseconds=dt.microsecond
    )
    rounded = dt - discard
    if discard >= timedelta(minutes=QUARTER_HOUR_MINUTES / 2):
        rounded += timedelta(minutes=QUARTER_HOUR_MINUTES)
    return rounded


@dataclass
class _Clock:
    """Mutable simulation state, threaded through the drive/rest helpers.
    Kept as one small object instead of a dozen nonlocal variables."""

    wall_clock: datetime
    cycle_used_minutes: int
    duty_window_minutes: int  # elapsed since the current 14-hr window started
    driving_minutes_this_period: int  # elapsed since the last 10-hr/34-hr reset
    driving_minutes_since_break: int  # elapsed since the last qualifying break
    miles_since_fuel: float
    total_miles_driven: float


class _Simulator:
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
        self.cumulative_distances = (
            build_cumulative_distances(route_geometry) if route_geometry else []
        )
        self.reverse_geocode = reverse_geocode
        self.segments: list[Segment] = []
        self.stops: list[Stop] = []

        # Remarks convention (see CLAUDE.md / the John Doe example): a
        # location is logged at the START of each duty-status segment (the
        # point where the PREVIOUS status ended). A driving segment's start
        # location is therefore always already known from whatever preceded
        # it — never re-derived by interpolating the segment's own end
        # point, which would mislabel it if a later midnight-split cut the
        # segment short before it actually reached that point.
        self.last_stop_label = start_location_text
        self.last_stop_lat = start_lat
        self.last_stop_lng = start_lng

    # --- position helpers ---

    def _position_at_current_mileage(self) -> tuple[float, float]:
        if not self.route_geometry:
            return (0.0, 0.0)
        return interpolate_point_at_distance(
            self.route_geometry, self.cumulative_distances, self.clock.total_miles_driven
        )

    def _label_at_current_position(self) -> str:
        lat, lng = self._position_at_current_mileage()
        return self.reverse_geocode(lat, lng)

    # --- segment emission ---

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
        # start/end below are the precise instants used for state
        # advancement; display_start/display_end (rounded to the nearest
        # quarter hour) are what actually gets stored on the Segment. Two
        # consecutive segments share the same precise boundary instant, so
        # rounding it once here keeps them continuous after rounding too —
        # no gap or overlap is introduced on the grid.
        start = self.clock.wall_clock
        end = start + timedelta(minutes=minutes)
        display_start = _round_to_nearest_quarter_hour(start)
        display_end = _round_to_nearest_quarter_hour(end)
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
        # else: this slice rounds away to nothing on the displayed grid
        # (can happen for a sub-quarter-hour sliver right before a limit
        # triggers) — its effect on HOS counters/mileage already applied
        # via the precise `end` above regardless of whether it's drawn.

        if status != DutyStatus.DRIVING:
            # Any non-driving stop of at least the break duration satisfies
            # the 30-minute break requirement, regardless of duty status —
            # a fuel stop, the pickup/dropoff stop, or a full 10-hr/34-hr
            # reset all qualify just as much as a dedicated break does.
            if minutes >= BREAK_DURATION_MINUTES:
                self.clock.driving_minutes_since_break = 0

            # This is now the last known position — the next driving
            # segment (if any) starts here.
            self.last_stop_label = location_text
            self.last_stop_lat = lat
            self.last_stop_lng = lng

    def _add_stop(self, stop_type: StopType, location_text: str, lat: float, lng: float, duration_minutes: float) -> None:
        arrival = _round_to_nearest_quarter_hour(self.clock.wall_clock)
        departure = _round_to_nearest_quarter_hour(self.clock.wall_clock + timedelta(minutes=duration_minutes))
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

    # --- the four "reset" actions ---

    def _insert_restart_34hr(self) -> None:
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_stop(StopType.RESTART_34HR, label, lat, lng, RESTART_OFF_DUTY_MINUTES)
        self._add_segment(DutyStatus.OFF_DUTY, RESTART_OFF_DUTY_MINUTES, label, lat, lng, "34-hour restart")
        self.clock.cycle_used_minutes = 0
        self.clock.duty_window_minutes = 0
        self.clock.driving_minutes_this_period = 0
        self.clock.driving_minutes_since_break = 0

    def _insert_10hr_reset(self) -> None:
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_stop(StopType.REST_10HR, label, lat, lng, MANDATORY_OFF_DUTY_MINUTES)
        self._add_segment(DutyStatus.OFF_DUTY, MANDATORY_OFF_DUTY_MINUTES, label, lat, lng, "10-hour rest")
        self.clock.duty_window_minutes = 0
        self.clock.driving_minutes_this_period = 0
        self.clock.driving_minutes_since_break = 0

    def _insert_30min_break(self) -> None:
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_segment(DutyStatus.OFF_DUTY, BREAK_DURATION_MINUTES, label, lat, lng, "30-minute break")
        self.clock.duty_window_minutes += BREAK_DURATION_MINUTES

    def _insert_fuel_stop(self) -> None:
        lat, lng = self._position_at_current_mileage()
        label = self._label_at_current_position()
        self._add_stop(StopType.FUEL, label, lat, lng, FUEL_STOP_DURATION_MINUTES)
        self._add_segment(DutyStatus.ON_DUTY_NOT_DRIVING, FUEL_STOP_DURATION_MINUTES, label, lat, lng, "Fuel stop")
        self.clock.cycle_used_minutes += FUEL_STOP_DURATION_MINUTES
        self.clock.duty_window_minutes += FUEL_STOP_DURATION_MINUTES
        self.clock.miles_since_fuel = 0.0

    # --- driving a leg ---

    def drive_leg(self, leg: RouteLeg) -> None:
        remaining_minutes = round(leg.duration_hours * MINUTES_PER_HOUR)
        if remaining_minutes <= 0 or leg.distance_miles <= 0:
            return

        mph = leg.distance_miles / leg.duration_hours

        while remaining_minutes > 0:
            c = self.clock

            # Check order: 70hr cycle -> 14hr window -> 11hr driving ->
            # 30-min break -> 1000mi fuel -> drive. See module docstring.
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

            # Drive up to whichever limit is reached first.
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
            chunk_minutes = max(chunk_minutes, 1)  # guard against a zero-length chunk from rounding
            chunk_miles = chunk_minutes / MINUTES_PER_HOUR * mph

            # This segment starts where the last stop left off — see the
            # last_stop_* comment in __init__/_add_segment for why we don't
            # interpolate this chunk's own end point instead.
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
    shift_start: str,  # ISO 8601 — actual trip-submission time
    reverse_geocode: ReverseGeocodeFn | None = None,
) -> SimulationResult:
    """Run the full simulation for one trip and return everything needed to
    persist a Trip + its DailyLogs and to render the map + log sheets.

    current->pickup is simulated as a REAL driving leg (burns HOS hours like
    any other driving), not just a map marker — charged before the 1-hour
    pickup stop, per the approved plan.
    """
    sim = _Simulator(
        shift_start=datetime.fromisoformat(shift_start),
        cycle_used_hours=cycle_used_hours,
        route_geometry=route_geometry,
        reverse_geocode=reverse_geocode or _default_reverse_geocode,
        start_location_text=current_location_text,
        start_lat=current_lat,
        start_lng=current_lng,
    )

    # Log the driver as OFF_DUTY from midnight up to shift_start — without
    # this, day 1's segments start mid-day and never sum to 24hrs, violating
    # CLAUDE.md's "total hours per row must sum to 24" requirement. Mirrors
    # the symmetric "close out the final calendar day" block further down.
    start_of_day = datetime.combine(sim.clock.wall_clock.date(), datetime.min.time())
    if start_of_day < sim.clock.wall_clock:
        seconds_per_minute = 60
        leading_off_duty_minutes = (sim.clock.wall_clock - start_of_day).total_seconds() / seconds_per_minute
        sim.clock.wall_clock = start_of_day
        sim._add_segment(
            DutyStatus.OFF_DUTY, leading_off_duty_minutes, current_location_text, current_lat, current_lng
        )

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

    # Close out the final calendar day so its log sheet sums to 24 hours.
    end_of_day = datetime.combine(sim.clock.wall_clock.date(), datetime.min.time()) + timedelta(days=1)
    if sim.clock.wall_clock < end_of_day:
        seconds_per_minute = 60
        remaining_minutes = (end_of_day - sim.clock.wall_clock).total_seconds() / seconds_per_minute
        sim._add_segment(
            DutyStatus.OFF_DUTY, remaining_minutes, dropoff_location_text, dropoff_lat, dropoff_lng, "Trip complete"
        )

    daily_summaries = split_into_daily_summaries(sim.segments, cycle_used_hours)

    return SimulationResult(
        total_distance_miles=round(
            leg_current_to_pickup.distance_miles + leg_pickup_to_dropoff.distance_miles, 2
        ),
        total_duration_hours=round(
            leg_current_to_pickup.duration_hours + leg_pickup_to_dropoff.duration_hours, 2
        ),
        route_geometry=route_geometry,
        stops=sim.stops,
        daily_summaries=daily_summaries,
    )
