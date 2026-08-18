class RoutingError(Exception):
    """Raised when the ORS autocomplete or directions API call fails or
    returns an unusable response. Caught in trips/views.py and translated
    into a 502 response."""
