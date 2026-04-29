import json
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.config.settings import settings
from app.utils.http_safe import public_airqo_http_error_message
from app.repository.llm_summary import (
    CerebrasSettings,
    build_summary_context,
    call_cerebras_bullet_summary,
)
from app.repository.measurement_formatting import round_number

cerebras = CerebrasSettings(
        api_key=settings.CEREBRAS_API_KEY,
        base_url=settings.CEREBRAS_BASE_URL,
        model=settings.CEREBRAS_MODEL,
        max_tokens=settings.CEREBRAS_MAX_TOKENS,
        temperature=settings.CEREBRAS_TEMPERATURE,
    )
    
AIRQO_HISTORICAL_PATH = "https://api.airqo.net/api/v2/devices/measurements/sites/{site_id}/historical"
AIRQO_RECENT_PATH = "https://api.airqo.net/api/v2/devices/measurements/sites/{site_id}/recent"

# Fallback when the recent API fails or has no aqi_ranges
DEFAULT_AQI_RANGES: dict[str, dict[str, float | None]] = {
    "good": {"min": 0, "max": 9.1},
    "moderate": {"min": 9.101, "max": 35.49},
    "u4sg": {"min": 35.491, "max": 55.49},
    "unhealthy": {"min": 55.491, "max": 125.49},
    "very_unhealthy": {"min": 125.491, "max": 225.49},
    "hazardous": {"min": 225.491, "max": None},
}

_AQI_RANGE_ORDER: tuple[str, ...] = (
    "good",
    "moderate",
    "u4sg",
    "unhealthy",
    "very_unhealthy",
    "hazardous",
)

_AQI_DISPLAY_NAME: dict[str, str] = {
    "good": "Good",
    "moderate": "Moderate",
    "u4sg": "Unhealthy for Sensitive Groups",
    "unhealthy": "Unhealthy",
    "very_unhealthy": "Very Unhealthy",
    "hazardous": "Hazardous",
}


def _copy_default_aqi_ranges() -> dict[str, dict[str, float | None]]:
    return {k: dict(v) for k, v in DEFAULT_AQI_RANGES.items()}


def _aqi_ranges_from_recent_payload(body: Any) -> dict[str, Any] | None:
    if not isinstance(body, dict) or not body.get("success"):
        return None
    measurements = body.get("measurements")
    if not isinstance(measurements, list) or not measurements:
        return None
    first = measurements[0]
    if not isinstance(first, dict):
        return None
    ar = first.get("aqi_ranges")
    if not isinstance(ar, dict) or not ar:
        return None
    return ar


def _classify_pm25_to_range_key(
    value: float, aqi_ranges: dict[str, Any]
) -> str | None:
    """Return first matching band key in fixed order, or None."""
    for key in _AQI_RANGE_ORDER:
        band = aqi_ranges.get(key)
        if not isinstance(band, dict):
            continue
        lo = band.get("min")
        hi = band.get("max")
        if not isinstance(lo, (int, float)):
            continue
        lo = float(lo)
        if hi is None:
            if value >= lo:
                return key
        elif isinstance(hi, (int, float)) and lo <= value <= float(hi):
            return key
    return None


def build_aqi_category_distribution(
    historical_measurements: list[dict],
    aqi_ranges: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Count historical pm2_5.value readings per AQI band using the given aqi_ranges
    (from recent API or default).
    """
    counts: dict[str, int] = {k: 0 for k in _AQI_RANGE_ORDER}
    for m in historical_measurements:
        raw = (m.get("pm2_5") or {}).get("value")
        if raw is None or not isinstance(raw, (int, float)):
            continue
        v = float(raw)
        key = _classify_pm25_to_range_key(v, aqi_ranges)
        if key and key in counts:
            counts[key] += 1
    return [
        {"name": _AQI_DISPLAY_NAME[k], "count": counts[k]}
        for k in _AQI_RANGE_ORDER
    ]


def build_readings_rows(
    historical_measurements: list[dict],
    aqi_ranges: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per-hour rows for streaming: time, location, device, PM, AQI band from aqi_ranges."""
    rows: list[dict[str, Any]] = []
    for m in historical_measurements:
        t = m.get("time")
        if not isinstance(t, str):
            continue
        site = m.get("siteDetails") if isinstance(m.get("siteDetails"), dict) else {}
        raw_pm25 = (m.get("pm2_5") or {}).get("value")
        raw_pm10 = (m.get("pm10") or {}).get("value")
        aqi_label: str | None = None
        if raw_pm25 is not None and isinstance(raw_pm25, (int, float)):
            key = _classify_pm25_to_range_key(float(raw_pm25), aqi_ranges)
            if key:
                aqi_label = _AQI_DISPLAY_NAME.get(key)
        rows.append(
            {
                "datetime": t,
                "country": site.get("country"),
                "city": site.get("city"),
                "site_id": m.get("site_id"),
                "device_id": m.get("device_id"),
                "pm2_5": round_number(float(raw_pm25), 2)
                if raw_pm25 is not None and isinstance(raw_pm25, (int, float))
                else None,
                "pm10": round_number(float(raw_pm10), 2)
                if raw_pm10 is not None and isinstance(raw_pm10, (int, float))
                else None,
                "aqi_category": aqi_label,
            }
        )
    rows.sort(key=lambda r: r.get("datetime") or "")
    return rows


async def fetch_effective_aqi_ranges(
    client: httpx.AsyncClient, site_id: str, token: str
) -> dict[str, Any]:
    url = AIRQO_RECENT_PATH.format(site_id=site_id)
    try:
        response = await client.get(url, params={"token": token})
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return _copy_default_aqi_ranges()
    parsed = _aqi_ranges_from_recent_payload(body)
    if parsed is not None:
        return parsed
    return _copy_default_aqi_ranges()


def _format_sse(event: str | None, data: Any) -> str:
    """One SSE message: optional `event:` line, then a single `data:` line (JSON)."""
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


def validate_and_format_historical_date_range(
    start: date, end: date
) -> tuple[str, str]:
    """Return (startTime, endTime) as YYYY-MM-DD for AirQo historical query params."""
    if start > end:
        raise ValueError("Start date must be on or before the end date.")
    today_utc = datetime.now(timezone.utc).date()
    for d in (start, end):
        if abs((d - today_utc).days) > 31:
            raise ValueError(
                "Endpoint can only support dates within 31 days from today"
            )
    return (start.isoformat(), end.isoformat())


def _parse_measurement_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_pm_hourly(measurements: list[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in measurements:
        t = m.get("time")
        raw = (m.get("pm2_5") or {}).get("value")
        if t is None or not isinstance(t, str):
            continue
        if raw is None or not isinstance(raw, (int, float)):
            continue
        rows.append(
            {
                "time": t,
                "pm2_5": round_number(float(raw), 2),
            }
        )
    rows.sort(key=lambda r: r.get("time") or "")
    return rows


def build_pm_hour_aggregate(measurements: list[dict]) -> list[dict[str, Any]]:
    by_hour: dict[int, list[float]] = defaultdict(list)
    for m in measurements:
        val = (m.get("pm2_5") or {}).get("value")
        if val is None or not isinstance(val, (int, float)):
            continue
        dt = _parse_measurement_time(m.get("time"))
        if dt is None:
            continue
        by_hour[dt.hour].append(float(val))

    out: list[dict[str, Any]] = []
    for h in range(24):
        label = f"{h:02d}:00"
        vals = by_hour[h]
        if vals:
            avg = sum(vals) / len(vals)
            out.append({"hour": label, "pm25": round_number(avg, 2)})
        else:
            out.append({"hour": label, "pm25": None})
    return out


def build_empty_placeholders() -> dict[str, list]:
    return {
        "aqi_dist": [],
        "daily_pm_trend_summary": [],
        "general_data_insight": [],
        "readings": [],
    }


def build_remaining_stream_extras() -> dict[str, list]:
    """Placeholders not yet streamed as their own events."""
    return {
        "daily_pm_trend_summary": [],
        "general_data_insight": [],
    }


def build_insight_payload(
    pm_hourly: list[dict[str, Any]],
    pm_hour_aggregate: list[dict[str, Any]],
) -> dict[str, Any]:
    p = {
        "pm_hourly": pm_hourly,
        "pm_hour_aggregate": pm_hour_aggregate,
    }
    p.update(build_empty_placeholders())
    return p


async def stream_insight_sse(
    client: httpx.AsyncClient,
    site_id: str,
    token: str,
    start_date_value: str,
    end_date_value: str,
    page_limit: int = 80,
) -> AsyncIterator[str]:
    url = AIRQO_HISTORICAL_PATH.format(site_id=site_id)
    all_measurements: list[dict] = []
    skip = 0
    first_page = True
    total_records: int = 0

    while True:
        try:
            response = await client.get(
                url,
                params={
                    "token": token,
                    "startTime": start_date_value,
                    "endTime": end_date_value,
                    "limit": page_limit,
                    "skip": skip,
                },
            )
            response.raise_for_status()
            u = response.request.url
            safe = f"{u.scheme}://{u.host}{u.path}"
            print(
                f"AirQo request: {response.request.method} {safe}",
                flush=True,
            )
        except httpx.HTTPError as e:
            yield _format_sse("error", {"message": public_airqo_http_error_message(e)})
            return

        try:
            payload = response.json()
        except ValueError:
            yield _format_sse("error", {"message": "AirQo response was not valid JSON"})
            return

        if not payload.get("success", False):
            msg = payload.get("message") or "AirQo success=false"
            yield _format_sse("error", {"message": msg})
            return

        meta = payload.get("meta") or {}
        batch: list[dict] = list(payload.get("measurements") or [])

        if first_page:
            total_records = int(meta.get("total", 0) or 0)
            yield _format_sse("total_records", {"total_records": total_records})
            first_page = False

        all_measurements.extend(batch)
        has_next = meta.get("hasNextPage")
        if has_next is None:
            t = total_records
            has_next = t > 0 and len(all_measurements) < t and len(batch) > 0
        if not has_next or not batch:
            break
        skip += len(batch)

    pm_h = build_pm_hourly(all_measurements)
    yield _format_sse("pm_hourly", {"pm_hourly": pm_h})

    pm_agg = build_pm_hour_aggregate(all_measurements)
    yield _format_sse("pm_hour_aggregate", {"pm_hour_aggregate": pm_agg})

    aqi_ranges = await fetch_effective_aqi_ranges(client, site_id, token)
    aqi_dist = build_aqi_category_distribution(all_measurements, aqi_ranges)
    yield _format_sse("aqi_category_distribution", {"aqi_category_distribution": aqi_dist})

    
    summary_context = build_summary_context(
        start_date_value,
        end_date_value,
        site_id,
        pm_agg,
        aqi_dist,
        all_measurements,
    )
    llm_payload = await call_cerebras_bullet_summary(
        client, cerebras, summary_context
    )
    yield _format_sse("llm_summary", llm_payload)

    readings_rows = build_readings_rows(all_measurements, aqi_ranges)
    yield _format_sse("readings", {"readings": readings_rows})

    yield _format_sse("complete", {})
