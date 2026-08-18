"""
Mocks ORS HTTP responses (via unittest.mock, patching requests.Session's
get/post — the client holds one shared Session, see services/open_routing/
client.py) so these tests never hit the network or burn the real free-tier
quota.
"""

from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from services.open_routing.client import OpenRouteServiceClient
from services.open_routing.exceptions import RoutingError


def _fake_response(json_body: dict, status_ok: bool = True, status_code: int = 200) -> Mock:
    response = Mock()
    response.json.return_value = json_body
    response.text = str(json_body)
    response.status_code = status_code
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        # Real requests.Response.raise_for_status() attaches itself to the
        # exception via `response=...` — replicate that so code reading
        # exc.response (to pull ORS's own error body) works the same as it
        # would against a real failed request.
        response.raise_for_status.side_effect = requests.HTTPError("error", response=response)
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
        with patch("requests.Session.get", return_value=_fake_response(body)) as mock_get:
            result = self.client.autocomplete("chicago")

        self.assertEqual(result, [{"label": "Chicago, Illinois, United States", "lat": 41.8781, "lng": -87.6298}])
        mock_get.assert_called_once()

    def test_autocomplete_returns_empty_list_for_no_matches(self):
        with patch("requests.Session.get", return_value=_fake_response({"features": []})):
            result = self.client.autocomplete("asdkfjaskldfj")
        self.assertEqual(result, [])

    def test_autocomplete_raises_routing_error_on_http_error(self):
        with patch("requests.Session.get", return_value=_fake_response({}, status_ok=False)):
            with self.assertRaises(RoutingError):
                self.client.autocomplete("chicago")

    def test_autocomplete_raises_routing_error_on_timeout(self):
        with patch("requests.Session.get", side_effect=requests.Timeout("timed out")):
            with self.assertRaises(RoutingError):
                self.client.autocomplete("chicago")

    def test_autocomplete_uses_cache_on_second_call(self):
        body = {
            "features": [
                {"properties": {"label": "Dallas, Texas"}, "geometry": {"coordinates": [-96.797, 32.7767]}}
            ]
        }
        with patch("requests.Session.get", return_value=_fake_response(body)) as mock_get:
            self.client.autocomplete("dallas")
            self.client.autocomplete("dallas")
        mock_get.assert_called_once()

    # --- reverse_geocode ---

    def test_reverse_geocode_returns_label(self):
        body = {"features": [{"properties": {"label": "Springfield, Illinois, United States"}}]}
        with patch("requests.Session.get", return_value=_fake_response(body)):
            label = self.client.reverse_geocode(39.78, -89.65)
        self.assertEqual(label, "Springfield, Illinois, United States")

    def test_reverse_geocode_falls_back_to_coordinates_on_no_match(self):
        with patch("requests.Session.get", return_value=_fake_response({"features": []})):
            label = self.client.reverse_geocode(39.78, -89.65)
        self.assertEqual(label, "39.7800, -89.6500")

    def test_reverse_geocode_falls_back_to_coordinates_on_error(self):
        with patch("requests.Session.get", side_effect=requests.ConnectionError("down")):
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
        with patch("requests.Session.post", return_value=_fake_response(body)):
            route = self.client.get_route([(32.8, -96.8), (32.9, -97.0), (32.76, -97.3)])

        self.assertAlmostEqual(route["distance_miles"], 30.0, places=1)
        self.assertAlmostEqual(route["duration_hours"], 0.75, places=2)
        self.assertEqual(len(route["legs"]), 2)
        self.assertAlmostEqual(route["legs"][0]["distance_miles"], 10.0, places=1)
        self.assertAlmostEqual(route["legs"][1]["duration_hours"], 0.5, places=2)
        self.assertEqual(route["geometry"], body["features"][0]["geometry"]["coordinates"])

    def test_get_route_raises_routing_error_on_non_200(self):
        with patch("requests.Session.post", return_value=_fake_response({}, status_ok=False)):
            with self.assertRaises(RoutingError):
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])

    def test_get_route_raises_routing_error_on_timeout(self):
        with patch("requests.Session.post", side_effect=requests.Timeout("timed out")):
            with self.assertRaises(RoutingError):
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])

    def test_get_route_raises_routing_error_on_malformed_body(self):
        with patch("requests.Session.post", return_value=_fake_response({"features": []})):
            with self.assertRaises(RoutingError):
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])

    def test_get_route_translates_distance_limit_error_to_friendly_message(self):
        """Regression test for a real bug: a route exceeding ORS's 6000km
        driving-car cap (e.g. current location far from pickup/dropoff)
        returned a bare '400 Client Error: Bad Request' with no actionable
        detail. ORS's own error code 2004 must now translate to a specific,
        useful message."""
        ors_body = {
            "error": {
                "code": 2004,
                "message": "Request parameters exceed the server configuration limits. "
                "The approximated route distance must not be greater than 6000000.0 meters.",
            }
        }
        with patch("requests.Session.post", return_value=_fake_response(ors_body, status_ok=False, status_code=400)):
            with self.assertRaises(RoutingError) as ctx:
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])

        self.assertIn("too long", str(ctx.exception))
        self.assertNotIn("400 Client Error", str(ctx.exception))

    def test_get_route_translates_unroutable_point_error_to_friendly_message(self):
        ors_body = {"error": {"code": 2010, "message": "Could not find routable point..."}}
        with patch("requests.Session.post", return_value=_fake_response(ors_body, status_ok=False, status_code=404)):
            with self.assertRaises(RoutingError) as ctx:
                self.client.get_route([(32.8, -96.8), (32.9, -97.0)])

        self.assertIn("Couldn't find a road", str(ctx.exception))
