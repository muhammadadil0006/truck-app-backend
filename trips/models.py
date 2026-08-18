import uuid

from django.db import models


class Trip(models.Model):
    """A planned trip: the 4 user inputs, plus everything the HOS engine
    computed from them.

    UUID primary key so GET /api/trips/<id>/ is a safe, non-enumerable
    shareable link — retrieve-by-id is deliberately open to anyone holding
    the id, unlike list/delete below.

    There's no login or server session in this app. `guest_id` is a
    client-generated id (persisted in the browser's localStorage, sent as
    the X-Guest-Id header — see trips/views.py) identifying which browser
    planned this trip. It scopes trip HISTORY (list) and deletion to the
    owning client, so one browser never sees another's trips; it does not
    restrict retrieve, since a trip's UUID already works as a shareable
    link on its own.

    Hours and miles use DecimalField rather than FloatField: HOS math is
    boundary-sensitive (>=11.0, >=70.0), and float drift across repeated
    additions is a real bug vector right at that boundary.

    `route_geometry` is the routing API's own GeoJSON polyline, stored
    exactly as received — the frontend's Leaflet map consumes it directly
    with no reshaping needed. `stops` is the map-marker list (pickup,
    dropoff, fuel stops, mandatory rests, any 34-hr restart) the frontend
    plots alongside that route.
    """

    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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

    cycle_used_hrs = models.DecimalField(max_digits=5, decimal_places=2)

    total_distance_miles = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    total_duration_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    route_geometry = models.JSONField(default=list, blank=True)
    stops = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_COMPLETED)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Trip {self.id} ({self.pickup_location_text} -> {self.dropoff_location_text})"


class DailyLog(models.Model):
    """One 24-hour log sheet belonging to a Trip.

    Recap-box numbers get real named fields (they're a fixed, small set of
    scalars the FMCSA form requires, worth querying/validating on their
    own). The duty-status data doesn't: it's variable-length, written once
    by the HOS engine, and always read back as a whole to draw one grid —
    normalizing it into rows would add joins with no actual benefit.

    `segments` and `transitions` both describe the same day's duty-status
    history, but answer different questions. `segments` is every interval
    with its own status, including ones that merely continue an earlier
    status across midnight (e.g. the middle of an overnight reset).
    `transitions` is only the *real* status changes — computed on the
    engine's raw, pre-midnight-split timeline, so a continuation is never
    mistaken for a fresh change. The frontend grid draws its horizontal
    lines from `segments` but places its change-point dots, its vertical
    connectors between rows, and its Remarks list from `transitions` — a
    day-local segment list alone can't tell "this is a new status" apart
    from "this is just where the day starts."
    """

    trip = models.ForeignKey(Trip, related_name="daily_logs", on_delete=models.CASCADE)
    day_index = models.PositiveSmallIntegerField()
    log_date = models.DateField()

    total_driving_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_on_duty_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_off_duty_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_sleeper_berth_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    total_miles_today = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    recap_a_last_7_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    recap_b_available_tomorrow = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    recap_c_last_8_days_if_restart = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    segments = models.JSONField(default=list)
    transitions = models.JSONField(default=list)

    class Meta:
        ordering = ["day_index"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "day_index"], name="unique_trip_day_index"),
        ]

    def __str__(self) -> str:
        return f"DailyLog day {self.day_index} for Trip {self.trip_id}"
