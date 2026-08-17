"""
Single source of truth for every FMCSA Hours-of-Service numeric threshold and
duty-status label used by the trip-planning engine.

Every comparison in services/hos_engine/engine.py MUST import from here —
no magic numbers in the algorithm itself. See ../../CLAUDE.md for the full
regulatory citations (49 CFR Part 395) behind each value, and
../../ALGORITHM-GUIDE.md for how these thresholds combine in the simulator.
"""

from enum import Enum


class DutyStatus(str, Enum):
    """The 4 duty statuses drawn as rows on the FMCSA daily log grid."""

    OFF_DUTY = "OFF_DUTY"
    SLEEPER_BERTH = "SLEEPER_BERTH"
    DRIVING = "DRIVING"
    ON_DUTY_NOT_DRIVING = "ON_DUTY_NOT_DRIVING"


class StopType(str, Enum):
    """Marker types plotted on the route map."""

    PICKUP = "pickup"
    DROPOFF = "dropoff"
    FUEL = "fuel"
    REST_10HR = "rest_10hr"
    RESTART_34HR = "restart_34hr"


# --- HOS numeric limits (all expressed as integer minutes internally by the
# engine to avoid floating-point boundary-comparison bugs; hour constants are
# kept here for readability and for anything that needs the hour value directly) ---

MAX_DRIVING_HOURS_PER_DAY = 11          # §395.3(a)(3) — 11-hour driving limit
MAX_DUTY_WINDOW_HOURS = 14              # §395.3(a)(2) — 14-hour driving window
BREAK_REQUIRED_AFTER_DRIVING_HOURS = 8  # §395.3(a)(3)(ii) — 30-min break trigger
BREAK_DURATION_MINUTES = 30
MANDATORY_OFF_DUTY_HOURS = 10           # required reset for 11-hr/14-hr clocks
CYCLE_LIMIT_HOURS = 70                  # §395.3(b) — 70-hour/8-day, property-carrying
CYCLE_WINDOW_DAYS = 8
RESTART_OFF_DUTY_HOURS = 34             # §395.3(c) — 34-hour restart

FUEL_STOP_INTERVAL_MILES = 1000         # assignment assumption
FUEL_STOP_DURATION_MINUTES = 45         # midpoint of assignment's "~30-60 min"

PICKUP_DURATION_HOURS = 1               # assignment assumption
DROPOFF_DURATION_HOURS = 1              # assignment assumption

MINUTES_PER_HOUR = 60
MAX_DRIVING_MINUTES_PER_DAY = MAX_DRIVING_HOURS_PER_DAY * MINUTES_PER_HOUR
MAX_DUTY_WINDOW_MINUTES = MAX_DUTY_WINDOW_HOURS * MINUTES_PER_HOUR
BREAK_REQUIRED_AFTER_DRIVING_MINUTES = BREAK_REQUIRED_AFTER_DRIVING_HOURS * MINUTES_PER_HOUR
MANDATORY_OFF_DUTY_MINUTES = MANDATORY_OFF_DUTY_HOURS * MINUTES_PER_HOUR
CYCLE_LIMIT_MINUTES = CYCLE_LIMIT_HOURS * MINUTES_PER_HOUR
RESTART_OFF_DUTY_MINUTES = RESTART_OFF_DUTY_HOURS * MINUTES_PER_HOUR
PICKUP_DURATION_MINUTES = PICKUP_DURATION_HOURS * MINUTES_PER_HOUR
DROPOFF_DURATION_MINUTES = DROPOFF_DURATION_HOURS * MINUTES_PER_HOUR

# Assumed average driving speed used only if the routing API doesn't return a
# duration directly for a sub-segment (engine should prefer API-provided
# duration whenever available; this is a fallback, not a primary source).
FALLBACK_AVERAGE_SPEED_MPH = 55
