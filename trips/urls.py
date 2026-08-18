from django.urls import path
from rest_framework.routers import DefaultRouter

from trips.views import GeocodeAutocompleteView, TripViewSet


router = DefaultRouter()
router.register("trips", TripViewSet, basename="trip")


urlpatterns = [
    path("geocode/", GeocodeAutocompleteView.as_view(), name="geocode-autocomplete"),
    *router.urls,
]
