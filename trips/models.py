import uuid

from django.db import models


class Trip(models.Model):
    """A planned trip: the 4 user inputs, plus everything the HOS engine
    computed from them. UUID primary key so GET /api/trips/<id>/ is a safe,
    non-enumerable shareable link.
    """

    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Client-generated id (localStorage, no server sessions/auth) identifying
    # which browser planned this trip — see trips/views.py's X-Guest-Id
    # handling. Scopes trip HISTORY (list) and deletion to the owning
    # client; retrieve-by-id stays open regardless, since a Trip's UUID is
    # meant to work as a shareable link (see the class docstring above).
    guest_id = models.CharField(max_length=64, db_index=True, blank=True, default="")

    current_location_text = models.CharField(max_length=255)
    current_location_lat = models.FloatField()
    current_location_lng = models.FloatField()

    pickup_location_text = models.CharField(max_length=255)
    pickup_location_lat = models.FloatField()
    pickup_location_lng = models.FloatField()

    dropoff_location_text = models.CharField(max_length=255)
    dropoff_location_lat = models.FloatField()
    dropoff_location_lng = models.FloatField()

    # DecimalField, not FloatField, for hours/miles: HOS math is
    # boundary-sensitive (>=11.0, >=70.0) and float drift across repeated
    # additions is a real bug vector at this boundary.
    cycle_used_hrs = models.DecimalField(max_digits=5, decimal_places=2)

    total_distance_miles = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    total_duration_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # GeoJSON [lng, lat] coordinate array from the routing API — consumed
    # directly by Leaflet's <GeoJSON> component on the frontend.
    route_geometry = models.JSONField(default=list, blank=True)

    # [{type, location_text, lat, lng, arrival, departure}, ...]
    stops = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_COMPLETED)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Trip {self.id} ({self.pickup_location_text} -> {self.dropoff_location_text})"


class DailyLog(models.Model):
    """One 24-hour log sheet belonging to a Trip. Recap-box numbers get real
    named fields (they're a fixed, small set of scalars the FMCSA form
    requires); the variable-length duty-status segment list is a JSONField
    since it's only ever written once and read as a whole to draw one grid.
    """

    trip = models.ForeignKey(Trip, related_name="daily_logs", on_delete=models.CASCADE)
    day_index = models.PositiveSmallIntegerField()  # 1-based
    log_date = models.DateField()

    total_driving_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_on_duty_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_off_duty_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_sleeper_berth_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_miles_today = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    recap_a_last_7_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    recap_b_available_tomorrow = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    recap_c_last_8_days_if_restart = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # [{status, start_time, end_time, location_text, lat, lng, remarks}, ...]
    segments = models.JSONField(default=list)

    # [{time, from_status, to_status, location_text, lat, lng}, ...] — one
    # entry per duty-status change that day, so the frontend can draw the
    # vertical connector between grid rows without re-deriving it from
    # adjacent segments.
    transitions = models.JSONField(default=list)

    class Meta:
        ordering = ["day_index"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "day_index"], name="unique_trip_day_index"),
        ]

    def __str__(self) -> str:
        return f"DailyLog day {self.day_index} for Trip {self.trip_id}"
