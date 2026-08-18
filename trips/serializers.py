from rest_framework import serializers

from services.constants import CYCLE_LIMIT_HOURS
from trips.models import DailyLog, Trip


class TripInputSerializer(serializers.Serializer):
    """Write-only input for POST /api/trips/.

    Location fields arrive as (text, lat, lng) triples already resolved by
    the frontend via GET /api/geocode/ (LocationAutocomplete.tsx) — no
    free-text geocoding happens here. This guarantees the exact point the
    user picked in the UI is the exact point routing/HOS math runs on;
    there's no second, independently-resolved geocode step that could land
    on a different place for the same text.
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

    # Must NOT reject high values like 68 or 70 — a near-maxed cycle is a
    # valid input that should still succeed via a forced 34-hr restart
    # (see ALGORITHM-GUIDE.md Example E).
    cycle_used_hrs = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=CYCLE_LIMIT_HOURS
    )


class GeocodeSuggestionSerializer(serializers.Serializer):
    """Shape returned by GET /api/geocode/ — one autocomplete suggestion."""

    label = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class DailyLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyLog
        fields = [
            "day_index",
            "log_date",
            "total_driving_hours",
            "total_on_duty_hours",
            "total_off_duty_hours",
            "total_sleeper_berth_hours",
            "total_miles_today",
            "recap_a_last_7_days",
            "recap_b_available_tomorrow",
            "recap_c_last_8_days_if_restart",
            "segments",
            "transitions",
        ]


class TripSerializer(serializers.ModelSerializer):
    daily_logs = DailyLogSerializer(many=True, read_only=True)

    class Meta:
        model = Trip
        fields = [
            "id",
            "current_location_text",
            "current_location_lat",
            "current_location_lng",
            "pickup_location_text",
            "pickup_location_lat",
            "pickup_location_lng",
            "dropoff_location_text",
            "dropoff_location_lat",
            "dropoff_location_lng",
            "cycle_used_hrs",
            "total_distance_miles",
            "total_duration_hours",
            "route_geometry",
            "stops",
            "status",
            "error_message",
            "created_at",
            "daily_logs",
        ]


class TripListItemSerializer(serializers.ModelSerializer):
    """Lighter shape for GET /api/trips/ (history list) — omits the nested
    daily_logs/segments payload, which is only needed on the detail view."""

    class Meta:
        model = Trip
        fields = [
            "id",
            "current_location_text",
            "pickup_location_text",
            "dropoff_location_text",
            "total_distance_miles",
            "status",
            "created_at",
        ]
