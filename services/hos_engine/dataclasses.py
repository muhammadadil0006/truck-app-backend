"""
Plain-Python (no Django) data shapes produced by the HOS simulator.

Kept dependency-free from Django models so services/hos_engine can be unit
tested without a database. trips/persistence.py is responsible for
translating these into Trip/DailyLog ORM rows.
"""

from dataclasses import dataclass, field

from services.constants import DutyStatus, StopType


@dataclass
class RouteLeg:
    """One leg of the overall route (current->pickup or pickup->dropoff),
    as returned by OpenRouteServiceClient.get_route()'s per-leg breakdown."""

    distance_miles: float
    duration_hours: float


@dataclass
class Segment:
    """One duty-status interval within a single day. Chronologically contiguous
    with its neighbors within the same day (end of segment[i] == start of
    segment[i+1]) — this invariant is what lets the frontend draw one
    continuous stepped path per log sheet."""

    status: DutyStatus
    start_time: str  # ISO 8601, e.g. "2026-08-18T06:00:00"
    end_time: str
    location_text: str
    lat: float
    lng: float
    remarks: str = ""
    miles: float = 0.0  # >0 only for DRIVING segments; used to compute total_miles_today


@dataclass
class Stop:
    """A marker to plot on the route map."""

    type: StopType
    location_text: str
    lat: float
    lng: float
    arrival: str  # ISO 8601
    departure: str  # ISO 8601


@dataclass
class Transition:
    """One duty-status change. Segments alone let the frontend infer
    transitions (end of segment[i] == start of segment[i+1]), but the grid
    also needs to draw the vertical connector between two DIFFERENT row
    y-levels at that instant — storing it explicitly means the frontend
    doesn't have to diff adjacent segments/rows itself, and it survives the
    day split unambiguously (a segment crossing midnight is NOT a
    transition; see log_splitter._build_transitions, computed on the raw
    pre-split segment list)."""

    time: str  # ISO 8601 instant the duty status changed
    from_status: DutyStatus | None  # None only for the very first transition of the trip
    to_status: DutyStatus
    location_text: str
    lat: float
    lng: float
    remarks: str = ""  # copied from the destination segment's remarks (e.g. "Fuel stop")


@dataclass
class DailySummary:
    """One calendar day's worth of segments plus the recap-box numbers that
    go at the bottom of that day's log sheet. See CLAUDE.md's
    'Daily Log Sheet — Required Fields & Layout' section for what each
    recap value represents."""

    day_index: int  # 1-based
    log_date: str  # "YYYY-MM-DD"
    segments: list[Segment] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)

    total_driving_hours: float = 0.0
    total_on_duty_hours: float = 0.0
    total_off_duty_hours: float = 0.0
    total_sleeper_berth_hours: float = 0.0
    total_miles_today: float = 0.0

    recap_a_last_7_days: float = 0.0
    recap_b_available_tomorrow: float = 0.0
    recap_c_last_8_days_if_restart: float = 0.0


@dataclass
class SimulationResult:
    """Everything trips/persistence.py needs to build a Trip + its DailyLogs."""

    total_distance_miles: float
    total_duration_hours: float
    route_geometry: list[list[float]]  # GeoJSON [lng, lat] coordinate pairs
    stops: list[Stop]
    daily_summaries: list[DailySummary]
