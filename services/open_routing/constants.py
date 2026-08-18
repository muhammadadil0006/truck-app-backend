AUTOCOMPLETE_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h — place names don't change
REVERSE_GEOCODE_CACHE_TTL_SECONDS = 60 * 60 * 24
AUTOCOMPLETE_RESULT_SIZE = 8
REQUEST_TIMEOUT_SECONDS = 8

METERS_PER_MILE = 1609.34
SECONDS_PER_HOUR = 3600

# ORS's driving-car profile hard-caps the total route distance it will
# compute — see https://openrouteservice.org error code 2004. Surfaced here
# so the 400 it returns becomes an actionable message instead of a bare
# "400 Client Error: Bad Request".
MAX_ROUTE_DISTANCE_METERS = 6_000_000
MAX_ROUTE_DISTANCE_MILES = MAX_ROUTE_DISTANCE_METERS / METERS_PER_MILE

# ORS error codes worth a specific, actionable message. Anything else falls
# back to ORS's own `error.message` (still far more useful than the generic
# HTTP status text).
ORS_ERROR_MESSAGES = {
    2004: (
        f"This trip's total route distance is too long for our free routing "
        f"service (limit ~{MAX_ROUTE_DISTANCE_MILES:,.0f} miles). Try a shorter route."
    ),
    2010: "Couldn't find a road near one of the selected locations — try picking a nearby city or address instead.",
}
