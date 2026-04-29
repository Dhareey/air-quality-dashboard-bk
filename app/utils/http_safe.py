"""
Safe messages for httpx errors when calling AirQo with ?token= in the URL.
Never use str(exception) in client-facing messages — it can include the full URL.
"""
from __future__ import annotations

import httpx


def public_airqo_http_error_message(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"AirQo API returned an error (HTTP {exc.response.status_code})."
    return "Failed to reach the AirQo API. Please try again later."
