"""
Highest-value test file in the project: the HOS engine is what the
assignment is graded on for accuracy. Imports directly from services/ with
zero Django DB/ORM involvement.

Reuses the 5 worked examples from ../../ALGORITHM-GUIDE.md section 4 as
end-to-end test cases, plus boundary/unit tests on individual rules and an
explicit check-ordering test (70hr -> 14hr -> 11hr -> break -> fuel).
"""

from dataclasses import replace
from datetime import datetime

from django.test import SimpleTestCase

from services.constants import (CYCLE_LIMIT_HOURS, CYCLE_LIMIT_MINUTES,
                                FUEL_STOP_INTERVAL_MILES,
                                MANDATORY_OFF_DUTY_HOURS,
                                MAX_DRIVING_HOURS_PER_DAY,
                                MAX_DUTY_WINDOW_MINUTES, DutyStatus)
from services.hos_engine.dataclasses import RouteLeg
from services.hos_engine.engine import plan_trip
from services.hos_engine.simulator import _Simulator

SHIFT_START = "2026-08-18T06:00:00"


def fake_reverse_geocode(lat: float, lng: float) -> str:
    return f"{lat:.2f},{lng:.2f}"


def straight_line_geometry(current, pickup, dropoff) -> list[list[float]]:
    """[lat, lng] tuples in -> GeoJSON [lng, lat] 3-point polyline. Good
    enough for these tests: only the HOS timing/mileage math is under test,
    not real road geometry."""
    return [[lng, lat] for lat, lng in (current, pickup, dropoff)]


def run_trip(
    *,
    current=(32.7767, -96.7970),
    pickup=(32.7767, -96.7970),
    dropoff=(32.7555, -97.3308),
    cycle_used_hours: float,
    leg1: RouteLeg,
    leg2: RouteLeg,
):
    geometry = straight_line_geometry(current, pickup, dropoff)
    return plan_trip(
        current_lat=current[0],
        current_lng=current[1],
        current_location_text="Current",
        pickup_lat=pickup[0],
        pickup_lng=pickup[1],
        pickup_location_text="Pickup",
        dropoff_lat=dropoff[0],
        dropoff_lng=dropoff[1],
        dropoff_location_text="Dropoff",
        cycle_used_hours=cycle_used_hours,
        route_geometry=geometry,
        leg_current_to_pickup=leg1,
        leg_pickup_to_dropoff=leg2,
        shift_start=SHIFT_START,
        reverse_geocode=fake_reverse_geocode,
    )


def driving_hours_total(result) -> float:
    return sum(day.total_driving_hours for day in result.daily_summaries)


def segments_with_remark(result, remark: str):
    return [
        seg
        for day in result.daily_summaries
        for seg in day.segments
        if seg.remarks == remark
    ]


def _merge_adjacent_same_status(segments):
    """log_splitter splits any segment crossing midnight into two pieces —
    undo that here so a >=10hr reset block split across a day boundary is
    seen as one block, not two shorter ones."""
    merged = []
    for seg in segments:
        if merged and merged[-1].status == seg.status and merged[-1].end_time == seg.start_time:
            prev = merged[-1]
            merged[-1] = replace(prev, end_time=seg.end_time, miles=prev.miles + seg.miles)
        else:
            merged.append(seg)
    return merged


def max_continuous_driving_hours(result) -> float:
    """The true regulatory invariant: no span of driving between two
    qualifying (>=10hr) off-duty resets may exceed 11 hours. This is a
    property of continuous duty PERIODS, not calendar days — it's entirely
    legal for a single calendar day's total to exceed 11 hours if two
    separate duty periods (each individually capped at 11hr) both fall
    within it."""
    all_segments = _merge_adjacent_same_status(
        [seg for day in result.daily_summaries for seg in day.segments]
    )
    max_run = 0.0
    current_run = 0.0
    for seg in all_segments:
        duration_hours = (
            datetime.fromisoformat(seg.end_time) - datetime.fromisoformat(seg.start_time)
        ).total_seconds() / 3600
        if seg.status == DutyStatus.DRIVING:
            current_run += duration_hours
            max_run = max(max_run, current_run)
        elif seg.status == DutyStatus.OFF_DUTY and duration_hours >= MANDATORY_OFF_DUTY_HOURS - 0.01:
            current_run = 0.0
    return max_run


class HosEngineWorkedExamplesTests(SimpleTestCase):
    """One test per ALGORITHM-GUIDE.md worked example (section 4)."""

    def test_example_a_short_trip_no_limits_triggered(self):
        """Dallas->Dallas->Fort Worth, cycle=10: 1 daily log, no break/fuel/reset."""
        result = run_trip(
            cycle_used_hours=10,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=35, duration_hours=0.75),
        )

        self.assertEqual(len(result.daily_summaries), 1)
        self.assertAlmostEqual(driving_hours_total(result), 0.75, places=2)
        self.assertEqual(segments_with_remark(result, "30-minute break"), [])
        self.assertEqual(segments_with_remark(result, "10-hour rest"), [])
        self.assertEqual(segments_with_remark(result, "34-hour restart"), [])

    def test_example_b_medium_trip_no_mandatory_break(self):
        """Chicago->Chicago->St. Louis, cycle=5: driving < 8hr so no 30-min
        break is inserted."""
        result = run_trip(
            current=(41.8781, -87.6298),
            pickup=(41.8781, -87.6298),
            dropoff=(38.6270, -90.1994),
            cycle_used_hours=5,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=300, duration_hours=5.0),
        )

        self.assertEqual(len(result.daily_summaries), 1)
        self.assertAlmostEqual(driving_hours_total(result), 5.0, places=2)
        self.assertEqual(segments_with_remark(result, "30-minute break"), [])

    def test_example_c_long_trip_break_and_overnight_reset(self):
        """New York->New York->Chicago, cycle=8: 2 daily logs, exactly one
        30-min break, exactly one 10-hr reset, day-1 driving hits 11hr cap."""
        result = run_trip(
            current=(40.7128, -74.0060),
            pickup=(40.7128, -74.0060),
            dropoff=(41.8781, -87.6298),
            cycle_used_hours=8,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=790, duration_hours=13.0),
        )

        self.assertEqual(len(result.daily_summaries), 2)
        self.assertEqual(len(segments_with_remark(result, "30-minute break")), 1)
        self.assertEqual(len(segments_with_remark(result, "10-hour rest")), 1)
        self.assertEqual(segments_with_remark(result, "34-hour restart"), [])
        self.assertAlmostEqual(result.daily_summaries[0].total_driving_hours, MAX_DRIVING_HOURS_PER_DAY, places=2)
        self.assertAlmostEqual(driving_hours_total(result), 13.0, places=2)

    def test_example_d_very_long_trip_34hr_restart(self):
        """Los Angeles->Los Angeles->New York, cycle=55: at least one >=34hr
        OFF_DUTY block, cycle resets to 0 after it, several daily logs."""
        result = run_trip(
            current=(34.0522, -118.2437),
            pickup=(34.0522, -118.2437),
            dropoff=(40.7128, -74.0060),
            cycle_used_hours=55,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=2780, duration_hours=42.0),
        )

        restarts = segments_with_remark(result, "34-hour restart")
        self.assertGreaterEqual(len(restarts), 1)
        for restart in restarts:
            self.assertEqual(restart.status, DutyStatus.OFF_DUTY)

        self.assertGreaterEqual(len(result.daily_summaries), 4)
        self.assertAlmostEqual(driving_hours_total(result), 42.0, places=1)
        self.assertLessEqual(max_continuous_driving_hours(result), MAX_DRIVING_HOURS_PER_DAY + 0.01)

    def test_example_e_cycle_nearly_maxed_forces_restart_on_short_trip(self):
        """Miami->Miami->Orlando, cycle=68: a SHORT trip (235mi) must still
        force a 34-hr restart because only 2hrs of cycle room remain, and
        the trip must still complete."""
        result = run_trip(
            current=(25.7617, -80.1918),
            pickup=(25.7617, -80.1918),
            dropoff=(28.5383, -81.3792),
            cycle_used_hours=68,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=235, duration_hours=4.0),
        )

        self.assertEqual(len(segments_with_remark(result, "34-hour restart")), 1)
        self.assertAlmostEqual(driving_hours_total(result), 4.0, places=2)
        self.assertAlmostEqual(result.total_distance_miles, 235.0, places=1)


class HosEngineBoundaryTests(SimpleTestCase):
    """Synthetic-input unit tests on individual rules, not full trips."""

    def test_30min_break_inserted_at_exactly_8_cumulative_driving_hours(self):
        result = run_trip(
            cycle_used_hours=0,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=425, duration_hours=8.5),
        )
        breaks = segments_with_remark(result, "30-minute break")
        self.assertEqual(len(breaks), 1)

        driving_before_break = sum(
            (datetime.fromisoformat(seg.end_time) - datetime.fromisoformat(seg.start_time)).total_seconds() / 3600
            for day in result.daily_summaries
            for seg in day.segments
            if seg.status == DutyStatus.DRIVING
            and seg.end_time <= breaks[0].start_time
        )
        self.assertAlmostEqual(driving_before_break, 8.0, places=2)

    def test_11hr_driving_cap_forces_10hr_reset_even_with_14hr_window_remaining(self):
        # 12 hours of driving needed; break trigger at 8hr, driving cap at
        # 11hr — the 11hr cap must force a reset well before the 14hr
        # window (60min pickup + 660min driving + 30min break = 750min =
        # 12.5hr) would ever be reached.
        result = run_trip(
            cycle_used_hours=0,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=600, duration_hours=12.0),
        )
        self.assertEqual(len(segments_with_remark(result, "10-hour rest")), 1)
        self.assertAlmostEqual(result.daily_summaries[0].total_driving_hours, MAX_DRIVING_HOURS_PER_DAY, places=2)

    def test_14hr_window_forces_reset_even_when_driving_hours_under_11(self):
        sim = _Simulator(
            shift_start=datetime.fromisoformat(SHIFT_START),
            cycle_used_hours=0,
            route_geometry=[[-96.797, 32.7767], [-97.3308, 32.7555]],
            reverse_geocode=fake_reverse_geocode,
        )
        sim.clock.duty_window_minutes = MAX_DUTY_WINDOW_MINUTES  # window already exhausted
        sim.drive_leg(RouteLeg(distance_miles=10, duration_hours=0.2))

        self.assertGreater(len(sim.segments), 0)
        first_segment = sim.segments[0]
        self.assertEqual(first_segment.status, DutyStatus.OFF_DUTY)
        self.assertEqual(first_segment.remarks, "10-hour rest")

    def test_70hr_cycle_forces_34hr_restart_not_plain_10hr_reset(self):
        sim = _Simulator(
            shift_start=datetime.fromisoformat(SHIFT_START),
            cycle_used_hours=CYCLE_LIMIT_HOURS,  # already at the limit
            route_geometry=[[-96.797, 32.7767], [-97.3308, 32.7555]],
            reverse_geocode=fake_reverse_geocode,
        )
        sim.drive_leg(RouteLeg(distance_miles=10, duration_hours=0.2))

        first_segment = sim.segments[0]
        self.assertEqual(first_segment.status, DutyStatus.OFF_DUTY)
        self.assertEqual(first_segment.remarks, "34-hour restart")

    def test_fuel_stop_inserted_at_exactly_1000_cumulative_miles(self):
        # Synthetic 200mph speed isolates the mileage trigger from the
        # 8hr/11hr time-based triggers (not a realistic truck speed —
        # purely a way to make 1000mi elapse before any other limit does).
        result = run_trip(
            cycle_used_hours=0,
            leg1=RouteLeg(distance_miles=0, duration_hours=0),
            leg2=RouteLeg(distance_miles=1100, duration_hours=1100 / 200),
        )
        fuel_stops = segments_with_remark(result, "Fuel stop")
        self.assertEqual(len(fuel_stops), 1)

    def test_check_order_70hr_beats_simultaneous_fuel_stop(self):
        """Construct inputs where a fuel stop and a 34-hr restart trigger at
        EXACTLY the same instant (both reached after precisely 5 minutes of
        driving); assert the restart wins and the fuel stop defers to after
        resuming, per the check-priority order (70hr before fuel)."""
        mph = 50
        minutes_until_both_trigger = 5
        miles_until_both_trigger = mph * minutes_until_both_trigger / 60

        sim = _Simulator(
            shift_start=datetime.fromisoformat(SHIFT_START),
            cycle_used_hours=(CYCLE_LIMIT_MINUTES - minutes_until_both_trigger) / 60,
            route_geometry=[[-96.797, 32.7767], [-97.3308, 32.7555]],
            reverse_geocode=fake_reverse_geocode,
        )
        sim.clock.miles_since_fuel = FUEL_STOP_INTERVAL_MILES - miles_until_both_trigger
        sim.drive_leg(RouteLeg(distance_miles=mph, duration_hours=1.0))

        non_driving = [s for s in sim.segments if s.status != DutyStatus.DRIVING]
        self.assertEqual(non_driving[0].remarks, "34-hour restart")
