"""
TripViewSet request/response tests. Mocks OpenRouteServiceClient so these
stay fast and network-free — the actual routing/geocoding behavior is
covered by test_routing_client.py, and the HOS math itself by
test_hos_engine.py.

Location fields are always (text, lat, lng) triples — resolved client-side
via GeocodeAutocompleteView before submission, never free-text geocoded here.
"""

from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

VALID_TRIP_PAYLOAD = {
    "current_location_text": "Dallas, TX",
    "current_location_lat": 32.7767,
    "current_location_lng": -96.7970,
    "pickup_location_text": "Dallas, TX",
    "pickup_location_lat": 32.7767,
    "pickup_location_lng": -96.7970,
    "dropoff_location_text": "Fort Worth, TX",
    "dropoff_location_lat": 32.7555,
    "dropoff_location_lng": -97.3308,
    "cycle_used_hrs": 10,
}

FAKE_ROUTE = {
    "distance_miles": 35.0,
    "duration_hours": 0.75,
    "geometry": [[-96.797, 32.7767], [-97.3308, 32.7555]],
    "legs": [
        {"distance_miles": 0.0, "duration_hours": 0.0},
        {"distance_miles": 35.0, "duration_hours": 0.75},
    ],
}


def _mock_routing_client():
    """Patches both methods the view calls on OpenRouteServiceClient."""
    return patch.multiple(
        "trips.views.OpenRouteServiceClient",
        get_route=lambda self, waypoints: FAKE_ROUTE,
        reverse_geocode=lambda self, lat, lng: f"{lat:.2f},{lng:.2f}",
    )


class TripViewSetCreateTests(APITestCase):
    def test_create_with_missing_fields_returns_400(self):
        response = self.client.post("/api/trips/", data={})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_rejects_negative_cycle_used_hrs(self):
        response = self.client.post(
            "/api/trips/", data={**VALID_TRIP_PAYLOAD, "cycle_used_hrs": -1}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_accepts_cycle_used_hrs_near_70_limit(self):
        """Must NOT reject a near-maxed cycle (e.g. 68) — see
        ALGORITHM-GUIDE.md Example E."""
        with _mock_routing_client():
            response = self.client.post(
                "/api/trips/", data={**VALID_TRIP_PAYLOAD, "cycle_used_hrs": 68}
            )
        self.assertNotEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_returns_201_with_daily_logs(self):
        with _mock_routing_client():
            response = self.client.post("/api/trips/", data=VALID_TRIP_PAYLOAD)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)
        self.assertGreaterEqual(len(response.data["daily_logs"]), 1)
        self.assertEqual(float(response.data["total_distance_miles"]), 35.0)

    def test_create_returns_502_on_routing_failure(self):
        from services.routing.exceptions import RoutingError

        with patch("trips.views.OpenRouteServiceClient.get_route", side_effect=RoutingError("boom")):
            response = self.client.post("/api/trips/", data=VALID_TRIP_PAYLOAD)

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)


class TripViewSetListRetrieveTests(APITestCase):
    def test_list_empty_history_returns_200_empty_list(self):
        response = self.client.get("/api/trips/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_retrieve_unknown_id_returns_404(self):
        response = self.client.get("/api/trips/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_created_trip_is_retrievable(self):
        with _mock_routing_client():
            create_response = self.client.post("/api/trips/", data=VALID_TRIP_PAYLOAD)
        trip_id = create_response.data["id"]

        response = self.client.get(f"/api/trips/{trip_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["pickup_location_text"], "Dallas, TX")
