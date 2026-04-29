"""
AirQo HTTP helper with retries.

AirQo's auth path can intermittently return 401 for valid tokens
(observed in production from EC2). It can also return transient 5xx / 429.
This helper retries those cases with a random sleep between attempts.
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

_RETRY_STATUSES: frozenset[int] = frozenset({401, 408, 425, 429, 500, 502, 503, 504})


async def airqo_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    max_retries: int = 3,
    min_sleep_seconds: float = 10.0,
    max_sleep_seconds: float = 60.0,
) -> httpx.Response:
    """
    GET an AirQo URL with up to (1 + max_retries) total attempts.

    Retries on:
      - httpx transport errors (httpx.HTTPError subclasses raised before a response),
      - upstream HTTP statuses in _RETRY_STATUSES.

    Sleeps a uniformly random duration in [min_sleep_seconds, max_sleep_seconds]
    between attempts. Raises the final httpx exception (incl. HTTPStatusError)
    on the last failure.
    """
    total_attempts = max_retries + 1
    last_exc: BaseException | None = None

    for attempt in range(1, total_attempts + 1):
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= total_attempts:
                raise
            await asyncio.sleep(random.uniform(min_sleep_seconds, max_sleep_seconds))
            continue

        if response.status_code in _RETRY_STATUSES and attempt < total_attempts:
            await asyncio.sleep(random.uniform(min_sleep_seconds, max_sleep_seconds))
            continue

        response.raise_for_status()
        return response

    # Defensive — loop should always return or raise above.
    if last_exc:
        raise last_exc
    raise httpx.HTTPError("AirQo request failed after retries")
