from rest_framework.exceptions import ValidationError

from trips.constants import GUEST_ID_HEADER


def require_guest_id(request) -> str:
    """Pull the calling client's guest id off the request, or reject it.

    There's no login in this app — ownership of a trip is a client-generated
    id (see frontend's utils/guestId.ts), sent as the X-Guest-Id header on
    every request that needs to read or mutate a specific client's history.
    Called from TripViewSet.create/get_queryset (trips/views.py) wherever
    that scoping applies.

    Args:
        request: the current DRF request.

    Returns:
        The header's value, stripped of surrounding whitespace.

    Raises:
        ValidationError: the header is missing or blank — surfaces to the
            caller as a 400, not a silent "no trips" or an unscoped query.
    """
    guest_id = request.headers.get(GUEST_ID_HEADER, "").strip()
    if not guest_id:
        raise ValidationError({"detail": f"{GUEST_ID_HEADER} header is required."})
    return guest_id
