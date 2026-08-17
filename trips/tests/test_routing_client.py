"""
Mocks ORS HTTP responses (via unittest.mock, patching requests.get/post) so
these tests never hit the network or burn the real free-tier quota.
"""

from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from services.routing.client import OpenRouteServiceClient
from services.routing.exceptions import RoutingError


def _fake_response(json_body: dict, status_ok: bool = True) -> Mock:
    response = Mock()
    response.json.return_value = json_body
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.HTTPError("500 error")
    return response


class OpenRouteServiceClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = OpenRouteServiceClient(api_key="fake-key", base_url="https://fake.ors")

    # --- autocomplete ---

    def test_autocomplete_returns_label_lat_lng(self):
        body = {
            "features": [
                {
                    "properties": {"label": "Chicago, Illinois, United States"},
                    "geometry": {"coordinates": [-87.6298, 41.8781]},
                }
            ]
        }
        with patch("requests.get", return_value=_fake_response(body)) as mock_get:
            result = self.client.autocomplete("chicago")

        self.assertEqual(result, [{"label": "Chicago, Illinois, United States", "lat": 41.8781, "lng": -87.6298}])
        mock_get.assert_called_once()

    def test_autocomplete_returns_empty_list_for_no_matches(self):
        with patch("requests.get", return_value=_fake_response({"features": []})):
            result = self.client.autocomplete("asdkfjaskldfj")
        self.assertEqual(result, [])

    def test_autocomplete_raises_routing_error_on_http_error(self):
        with patch("requests.get", return_value=_fake_response({}, status_ok=False)):
            with self.assertRaises(RoutingError):
                self.client.autocomplete("chicago")

    def test_autocomplete_raises_routing_error_on_timeout(self):
        with patch("requests.get", side_effect=requests.Timeout("timed out")):
            with self.assertRaises(RoutingError):
                self.client.autocomplete("chicago")

    def test_autocomplete_uses_cache_on_second_call(self):
        body = {
            "features": [
                {"properties": {"label": "Dallas, Texas"}, "geometry": {"coordinates": [-96.797, 32.7767]}}
            ]
        }
        with patch("requests.get", return_value=_fake_response(body)) as mock_get:
            self.client.autocomplete("dallas")
            self.client.autocomplete("dallas")
        mock_get.assert_called_once()

    # --- reverse_geocode ---

    def test_reverse_geocode_returns_label(self):
        body = {"features": [{"properties": {"label": "Springfield, Illinois, United States"}}]}
        with patch("requests.get", return_value=_fake_response(body)):
            label = self.client.reverse_geocode(39.78, -89.65)
        self.assertEqual(label, "Springfield, Illinois, United States")

    def test_reverse_geocode_falls_back_to_coordinates_on_no_match(self):
        with patch("requests.get", return_value=_fake_response({"features": []})):
            label = self.client.reverse_geocode(39.78, -89.65)
        self.assertEqual(label, "39.7800, -89.6500")

    def test_reverse_geocode_falls_back_to_coordinates_on_error(self):
        with patch("requests.get", side_effect=requests.ConnectionError("down")):
            label = self.client.reverse_geocode(39.78, -89.65)
        self.assertEqual(label, "39.7800, -89.6500")

    # --- get_route ---

    def test_get_route_returns_distance_duration_geometry_and_legs(self):
        body = {
            "features": [
                {
                    "properties": {
                        "segments": [
                            {"distance": 16093.4, "duration": 900.0},
                            {"distance": 32186.8, "duration": 1800.0},
                        ],
                        "summary": {"distance": 48280.2, "duration": 2700.0},
                    },
                    "geometry": {"coordinates": [[-96.8, 32.8], [-97.0, 32.9], [-97.3, 32.76]]},
                }
            ]
        }
        with patch("requests.post", return_value=_fake_response(body)):
            route = self.client.get_route([(32.8, -96.8), (32.9, -97.0), (32.76, -97.3)])

        self.assertAlmostEqual(route["distance_miles"], 30.0, places=1)
        self.assertAlmostEqual(route["duration_hours"], 0.75, places=2)
        self.assertEqual(len(route["legs"]), 2)
        self.assertAlmostEqual(route["legs"][0]["distance_miles"], 10.0, places=1)
        self.assertAlmostEqual(route["legs"][1]["duration_hours"], 0.5, places=2)
        self.assertEqual(route["geometry"], body["features"][0]["geometry"]["coordinates"])

    def test_get_route_raises_routing_error_on_non_200(self):
        with patch("requests.post", return_value=_fake_response({}, status_ok=False)):
            with self.assertRaises(RoutingError):
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])

    def test_get_route_raises_routing_error_on_timeout(self):
        with patch("requests.post", side_effect=requests.Timeout("timed out")):
            with self.assertRaises(RoutingError):
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])

    def test_get_route_raises_routing_error_on_malformed_body(self):
        with patch("requests.post", return_value=_fake_response({"features": []})):
            with self.assertRaises(RoutingError):
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])
