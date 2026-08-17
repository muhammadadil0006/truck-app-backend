"""
Splits a flat, chronological list of duty-status segments (which may span
multiple calendar days) into one DailySummary per day, and computes each
day's recap-box numbers (rolling cycle totals).

Policy: always emit exactly one DailySummary per calendar day the trip
spans, even if a day is 100% off duty (e.g. during a 34-hour restart) —
CLAUDE.md's "may be combined" wording for consecutive off-duty days is
optional, not required, and always-one-page-per-day is the simpler,
unambiguous default.

Any segment that crosses midnight is split into pieces, one per day it
touches, with `miles` divided proportionally by duration.

Known simplification on the recap boxes: the app's single scalar
"Current Cycle Used (Hrs)" input has no day-by-day breakdown of the driver's
actual last 7/8 days before the trip started, so a rolling accumulator is
used instead — it starts at that scalar and adds each simulated day's
on-duty hours, resetting to zero the moment a >=34-hour OFF_DUTY block
appears. This is exact for everything that happens during the simulated
trip; only the (unknowable) pre-trip history is approximated.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from services.constants import CYCLE_LIMIT_HOURS, MINUTES_PER_HOUR, DutyStatus, RESTART_OFF_DUTY_HOURS
from services.hos_engine.dataclasses import DailySummary, Segment

SECONDS_PER_MINUTE = 60


def _duration_minutes(segment: Segment) -> float:
    start = datetime.fromisoformat(segment.start_time)
    end = datetime.fromisoformat(segment.end_time)
    return (end - start).total_seconds() / SECONDS_PER_MINUTE


def _split_at_midnight(segment: Segment) -> list[Segment]:
    start = datetime.fromisoformat(segment.start_time)
    end = datetime.fromisoformat(segment.end_time)
    if start.date() == end.date():
        return [segment]

    total_minutes = _duration_minutes(segment)
    pieces: list[Segment] = []
    cursor = start
    is_first_piece = True

    while cursor.date() != end.date():
        midnight = datetime.combine(cursor.date(), datetime.min.time()) + timedelta(days=1)
        piece_minutes = (midnight - cursor).total_seconds() / SECONDS_PER_MINUTE
        piece_miles = segment.miles * (piece_minutes / total_minutes) if total_minutes else 0.0
        pieces.append(
            Segment(
                status=segment.status,
                start_time=cursor.isoformat(),
                end_time=midnight.isoformat(),
                location_text=segment.location_text if is_first_piece else "",
                lat=segment.lat,
                lng=segment.lng,
                remarks=segment.remarks if is_first_piece else "",
                miles=piece_miles,
            )
        )
        cursor = midnight
        is_first_piece = False

    remaining_minutes = (end - cursor).total_seconds() / SECONDS_PER_MINUTE
    remaining_miles = segment.miles * (remaining_minutes / total_minutes) if total_minutes else 0.0
    pieces.append(
        Segment(
            status=segment.status,
            start_time=cursor.isoformat(),
            end_time=end.isoformat(),
            location_text="",
            lat=segment.lat,
            lng=segment.lng,
            remarks="",
            miles=remaining_miles,
        )
    )
    return [p for p in pieces if p.start_time != p.end_time]


def split_into_daily_summaries(
    segments: list[Segment],
    cycle_used_hours_at_start: float,
) -> list[DailySummary]:
    all_pieces: list[Segment] = []
    for seg in segments:
        all_pieces.extend(_split_at_midnight(seg))

    days: dict[str, list[Segment]] = {}
    for piece in all_pieces:
        day_key = piece.start_time[:10]  # "YYYY-MM-DD"
        days.setdefault(day_key, []).append(piece)

    summaries: list[DailySummary] = []
    rolling_cycle_hours = cycle_used_hours_at_start

    for day_index, day_key in enumerate(sorted(days.keys()), start=1):
        day_segments = days[day_key]

        driving_minutes = sum(
            _duration_minutes(s) for s in day_segments if s.status == DutyStatus.DRIVING
        )
        on_duty_minutes = sum(
            _duration_minutes(s) for s in day_segments if s.status == DutyStatus.ON_DUTY_NOT_DRIVING
        )
        off_duty_minutes = sum(
            _duration_minutes(s) for s in day_segments if s.status == DutyStatus.OFF_DUTY
        )
        sleeper_minutes = sum(
            _duration_minutes(s) for s in day_segments if s.status == DutyStatus.SLEEPER_BERTH
        )
        miles_today = sum(s.miles for s in day_segments)

        day_on_duty_hours = (driving_minutes + on_duty_minutes) / MINUTES_PER_HOUR

        had_restart_today = any(
            s.status == DutyStatus.OFF_DUTY and _duration_minutes(s) / MINUTES_PER_HOUR >= RESTART_OFF_DUTY_HOURS
            for s in day_segments
        )

        rolling_cycle_hours = day_on_duty_hours if had_restart_today else rolling_cycle_hours + day_on_duty_hours

        recap_a = round(rolling_cycle_hours, 2)
        recap_b = round(max(0.0, CYCLE_LIMIT_HOURS - recap_a), 2)
        recap_c = float(CYCLE_LIMIT_HOURS)  # full cycle restored if a 34-hr restart were taken

        summaries.append(
            DailySummary(
                day_index=day_index,
                log_date=day_key,
                segments=day_segments,
                total_driving_hours=round(driving_minutes / MINUTES_PER_HOUR, 2),
                total_on_duty_hours=round(on_duty_minutes / MINUTES_PER_HOUR, 2),
                total_off_duty_hours=round(off_duty_minutes / MINUTES_PER_HOUR, 2),
                total_sleeper_berth_hours=round(sleeper_minutes / MINUTES_PER_HOUR, 2),
                total_miles_today=round(miles_today, 2),
                recap_a_last_7_days=recap_a,
                recap_b_available_tomorrow=recap_b,
                recap_c_last_8_days_if_restart=recap_c,
            )
        )

    return summaries
