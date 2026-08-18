from rest_framework import serializers

from services.constants import CYCLE_LIMIT_HOURS
from trips.models import DailyLog, Trip


class TripInputSerializer(serializers.Serializer):
    """The 4 inputs needed to plan a trip.

    Locations arrive as (text, lat, lng) triples already resolved by the
    frontend's autocomplete — no free-text geocoding happens here, so the
    point the user picked is exactly the point routing/HOS math runs on.

    cycle_used_hrs allows the full 0-70 range, including near-max values
    like 68 — still valid, and succeeds via a forced 34-hr restart rather
    than getting rejected as out of range.
    """

    current_location_text = serializers.CharField(max_length=255)
    current_location_lat = serializers.FloatField()
    current_location_lng = serializers.FloatField()

    pickup_location_text = serializers.CharField(max_length=255)
    pickup_location_lat = serializers.FloatField()
    pickup_location_lng = serializers.FloatField()

    dropoff_location_text = serializers.CharField(max_length=255)
    dropoff_location_lat = serializers.FloatField()
    dropoff_location_lng = serializers.FloatField()

    cycle_used_hrs = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=CYCLE_LIMIT_HOURS
    )


class GeocodeSuggestionSerializer(serializers.Serializer):
    """One location-autocomplete suggestion: a label plus its coordinates."""

    label = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class DailyLogSerializer(serializers.ModelSerializer):
    """One 24-hour log sheet, nested under a trip's full detail."""

    class Meta:
        model = DailyLog
        fields = [
            "day_index", "log_date", "total_driving_hours", "total_on_duty_hours",
            "total_off_duty_hours", "total_sleeper_berth_hours", "total_miles_today",
            "recap_a_last_7_days", "recap_b_available_tomorrow", "recap_c_last_8_days_if_restart",
            "segments", "transitions",
        ]


class TripSerializer(serializers.ModelSerializer):
    """Full trip detail, including its daily logs. guest_id is left out on
    purpose — it's an internal ownership key, never user-facing data."""

    daily_logs = DailyLogSerializer(many=True, read_only=True)

    class Meta:
        model = Trip
        fields = [
            "id", "current_location_text", "current_location_lat", "current_location_lng",
            "pickup_location_text", "pickup_location_lat", "pickup_location_lng",
            "dropoff_location_text", "dropoff_location_lat", "dropoff_location_lng",
            "cycle_used_hrs", "total_distance_miles", "total_duration_hours",
            "route_geometry", "stops", "status", "error_message", "created_at", "daily_logs",
        ]


class TripListItemSerializer(serializers.ModelSerializer):
    """Lighter shape for trip history — omits the nested daily logs, which
    are only needed on the detail view."""

    class Meta:
        model = Trip
        fields = [
            "id", "current_location_text", "pickup_location_text",
            "dropoff_location_text", "total_distance_miles", "status", "created_at",
        ]
