from datetime import datetime

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from services.hos_engine.dataclasses import RouteLeg
from services.hos_engine.engine import plan_trip
from services.routing.client import OpenRouteServiceClient
from services.routing.exceptions import RoutingError
from trips.models import Trip
from trips.persistence import save_trip
from trips.serializers import (
    GeocodeSuggestionSerializer,
    TripInputSerializer,
    TripListItemSerializer,
    TripSerializer,
)

# Client-generated id (localStorage, no server sessions) identifying which
# browser is calling — see frontend's utils/guestId.ts + tripApi.ts.
GUEST_ID_HEADER = "X-Guest-Id"


def _require_guest_id(request) -> str:
    guest_id = request.headers.get(GUEST_ID_HEADER, "").strip()
    if not guest_id:
        raise ValidationError({"detail": f"{GUEST_ID_HEADER} header is required."})
    return guest_id


class GeocodeAutocompleteView(APIView):
    """
    GET /api/geocode/?q=<partial text> -> [{"label", "lat", "lng"}, ...]

    Proxies OpenRouteService's autocomplete endpoint so ORS_API_KEY never
    reaches the browser, and so location suggestions come from the exact
    same geocoder the directions call uses — no drift between what the user
    picks in the UI and what the backend resolves.
    """

    def get(self, request, *args, **kwargs):
        query = request.query_params.get("q", "").strip()
        if len(query) < 3:
            return Response([])

        try:
            suggestions = OpenRouteServiceClient().autocomplete(query)
        except RoutingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(GeocodeSuggestionSerializer(suggestions, many=True).data)


class TripViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    POST   /api/trips/       -> plan a trip (route, run HOS engine, persist)
    GET    /api/trips/       -> trip history (lightweight list) — scoped to
                                 the caller's X-Guest-Id, not global
    GET    /api/trips/<id>/  -> retrieve one trip in full (shareable link —
                                 deliberately NOT guest-scoped)
    DELETE /api/trips/<id>/  -> remove from history — scoped to owner

    No update/partial_update: a computed trip is treated as immutable.
    """

    queryset = Trip.objects.prefetch_related("daily_logs")
    lookup_field = "id"

    def get_serializer_class(self):
        if self.action == "create":
            return TripInputSerializer
        if self.action == "list":
            return TripListItemSerializer
        return TripSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        # Retrieve deliberately excluded: a Trip's UUID is meant to work as
        # a shareable link regardless of who's viewing it.
        if self.action in ("list", "destroy"):
            return queryset.filter(guest_id=_require_guest_id(self.request))
        return queryset

    def create(self, request, *args, **kwargs):
        guest_id = _require_guest_id(request)
        input_serializer = TripInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        client = OpenRouteServiceClient()

        try:
            route = client.get_route(
                [
                    (data["current_location_lat"], data["current_location_lng"]),
                    (data["pickup_location_lat"], data["pickup_location_lng"]),
                    (data["dropoff_location_lat"], data["dropoff_location_lng"]),
                ]
            )
        except RoutingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            simulation = plan_trip(
                current_lat=data["current_location_lat"],
                current_lng=data["current_location_lng"],
                current_location_text=data["current_location_text"],
                pickup_lat=data["pickup_location_lat"],
                pickup_lng=data["pickup_location_lng"],
                pickup_location_text=data["pickup_location_text"],
                dropoff_lat=data["dropoff_location_lat"],
                dropoff_lng=data["dropoff_location_lng"],
                dropoff_location_text=data["dropoff_location_text"],
                cycle_used_hours=float(data["cycle_used_hrs"]),
                route_geometry=route["geometry"],
                leg_current_to_pickup=RouteLeg(**route["legs"][0]),
                leg_pickup_to_dropoff=RouteLeg(**route["legs"][1]),
                shift_start=datetime.now().isoformat(),
                reverse_geocode=client.reverse_geocode,
            )
        except RoutingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        trip = save_trip(data, simulation, guest_id)
        return Response(TripSerializer(trip).data, status=status.HTTP_201_CREATED)
