from __future__ import annotations

from dataclasses import asdict

from services.hos_engine.dataclasses import SimulationResult
from trips.models import DailyLog, Trip


def save_trip(validated_input: dict, simulation: SimulationResult, guest_id: str) -> Trip:
    """Persist a planned trip: a Trip row plus one DailyLog row per day the
    engine produced.

    Args:
        validated_input: TripInputSerializer's validated_data — the 4 raw
            user inputs (current/pickup/dropoff location text+lat+lng,
            cycle_used_hrs).
        simulation: the engine's full output for this trip — distance/
            duration totals, route geometry, map-marker stops, and one
            DailySummary per calendar day.
        guest_id: the owning client's id (see trips/views.py's X-Guest-Id
            handling), stamped onto the Trip so history/delete can be
            scoped to it later.

    Returns:
        The created Trip, with its daily_logs already persisted (though not
        prefetched onto the returned instance — re-fetch via the queryset
        if you need them attached).
    """
    trip = Trip.objects.create(
        guest_id=guest_id,
        current_location_text=validated_input["current_location_text"],
        current_location_lat=validated_input["current_location_lat"],
        current_location_lng=validated_input["current_location_lng"],
        pickup_location_text=validated_input["pickup_location_text"],
        pickup_location_lat=validated_input["pickup_location_lat"],
        pickup_location_lng=validated_input["pickup_location_lng"],
        dropoff_location_text=validated_input["dropoff_location_text"],
        dropoff_location_lat=validated_input["dropoff_location_lat"],
        dropoff_location_lng=validated_input["dropoff_location_lng"],
        cycle_used_hrs=validated_input["cycle_used_hrs"],
        total_distance_miles=simulation.total_distance_miles,
        total_duration_hours=simulation.total_duration_hours,
        route_geometry=simulation.route_geometry,
        stops=[asdict(stop) for stop in simulation.stops],
        status=Trip.STATUS_COMPLETED,
    )

    DailyLog.objects.bulk_create(
        DailyLog(
            trip=trip,
            day_index=day.day_index,
            log_date=day.log_date,
            total_driving_hours=day.total_driving_hours,
            total_on_duty_hours=day.total_on_duty_hours,
            total_off_duty_hours=day.total_off_duty_hours,
            total_sleeper_berth_hours=day.total_sleeper_berth_hours,
            total_miles_today=day.total_miles_today,
            recap_a_last_7_days=day.recap_a_last_7_days,
            recap_b_available_tomorrow=day.recap_b_available_tomorrow,
            recap_c_last_8_days_if_restart=day.recap_c_last_8_days_if_restart,
            segments=[asdict(seg) for seg in day.segments],
            transitions=[asdict(t) for t in day.transitions],
        )
        for day in simulation.daily_summaries
    )

    return trip
