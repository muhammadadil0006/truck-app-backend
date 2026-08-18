import requests

from services.open_routing.constants import ORS_ERROR_MESSAGES


def extract_ors_error_message(response: requests.Response) -> str:
    """Pulls ORS's own {"error": {"code", "message"}} body out of a failed
    response instead of settling for requests' generic HTTP status text."""
    try:
        error = response.json().get("error", {})
        code = error.get("code")
        if code in ORS_ERROR_MESSAGES:
            return ORS_ERROR_MESSAGES[code]
        if error.get("message"):
            return error["message"]
    except ValueError:
        pass
    return response.text[:300] or f"HTTP {response.status_code}"
