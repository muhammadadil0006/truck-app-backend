from datetime import datetime

from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from services.hos_engine.dataclasses import RouteLeg
from services.hos_engine.engine import plan_trip
from services.open_routing.client import OpenRouteServiceClient, get_client
from services.open_routing.exceptions import RoutingError
from trips.models import Trip
from trips.persistence import save_trip
from trips.serializers import (
    GeocodeSuggestionSerializer,
    TripInputSerializer,
    TripListItemSerializer,
    TripSerializer,
)
from trips.validators import require_guest_id


class GeocodeAutocompleteView(APIView):
    """Location-autocomplete proxy. Keeps ORS_API_KEY off the browser, and
    keeps suggestions from the same geocoder that later resolves the route
    — so what the user picks is exactly where the trip gets planned from."""

    def get(self, request, *args, **kwargs):
        """Skips calling ORS for short queries (nothing useful to suggest
        yet), otherwise returns its autocomplete results."""
        query = request.query_params.get("q", "").strip()
        if len(query) < 3:
            return Response([])

        try:
            suggestions = get_client().autocomplete(query)
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
    """The trip resource: plan, browse history, view one by its link, or
    delete. Ownership is a client-generated guest id, not a login — list
    and destroy are scoped to it, retrieve isn't, since a trip's link is
    meant to be shareable with anyone who has it. Immutable once created:
    no update/partial_update."""

    queryset = Trip.objects.prefetch_related("daily_logs")
    lookup_field = "id"

    def get_serializer_class(self):
        if self.action == "create":
            return TripInputSerializer
        if self.action == "list":
            return TripListItemSerializer
        return TripSerializer

    def get_queryset(self):
        """Scopes list/destroy to the calling guest; retrieve stays open."""
        queryset = super().get_queryset()
        if self.action in ("list", "destroy"):
            return queryset.filter(guest_id=require_guest_id(self.request))
        return queryset

    def create(self, request, *args, **kwargs):
        """Resolves the route, runs the HOS engine over it, and persists
        the result for the calling guest."""
        guest_id = require_guest_id(request)
        input_serializer = TripInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        client = get_client()

        try:
            route = client.get_route(
                [
                    (data["current_location_lat"], data["current_location_lng"]),
                    (data["pickup_location_lat"], data["pickup_location_lng"]),
                    (data["dropoff_location_lat"], data["dropoff_location_lng"]),
                ]
            )
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
