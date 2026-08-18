from django.contrib import admin

from trips.models import DailyLog, Trip


class DailyLogInline(admin.TabularInline):
    model = DailyLog
    extra = 0
    fields = ["day_index", "log_date", "total_driving_hours", "total_on_duty_hours", "segments", "transitions"]
    readonly_fields = fields


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ["id", "pickup_location_text", "dropoff_location_text", "status", "created_at"]
    list_filter = ["status"]
    inlines = [DailyLogInline]
