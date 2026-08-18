from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from services.open_routing.exceptions import RoutingError


class GeocodeAutocompleteViewTests(APITestCase):
    def test_short_query_returns_empty_list_without_calling_ors(self):
        with patch("trips.views.OpenRouteServiceClient.autocomplete") as mock_autocomplete:
            response = self.client.get("/api/geocode/", {"q": "ch"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])
        mock_autocomplete.assert_not_called()

    def test_valid_query_returns_suggestions_from_client(self):
        fake_suggestions = [{"label": "Chicago, Illinois, United States", "lat": 41.8781, "lng": -87.6298}]
        with patch("trips.views.OpenRouteServiceClient.autocomplete", return_value=fake_suggestions):
            response = self.client.get("/api/geocode/", {"q": "chicago"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, fake_suggestions)

    def test_routing_error_returns_502(self):
        with patch("trips.views.OpenRouteServiceClient.autocomplete", side_effect=RoutingError("boom")):
            response = self.client.get("/api/geocode/", {"q": "chicago"})

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
