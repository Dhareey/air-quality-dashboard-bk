from datetime import date
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config.settings import settings
from app.utils.http_safe import public_airqo_http_error_message
from app.repository.insight import stream_insight_sse, validate_and_format_historical_date_range
from app.repository.llm_summary import CerebrasSettings
from app.repository.measurement_formatting import compact_aqi_ranges, round_number
from app.repository.site_compare import compare_sites_llm
from app.schema.compare_sites import CompareSitesRequest

router = APIRouter(tags=["dashboard"])


@router.post("/compare_sites", response_model=list[str])
async def compare_sites(request: Request, body: CompareSitesRequest) -> list[str]:
    client: httpx.AsyncClient = request.app.state.http_client
    cerebras = CerebrasSettings(
        api_key=settings.CEREBRAS_API_KEY,
        base_url=settings.CEREBRAS_BASE_URL,
        model=settings.CEREBRAS_MODEL,
        max_tokens=settings.CEREBRAS_MAX_TOKENS,
        temperature=settings.CEREBRAS_TEMPERATURE,
    )
    result = await compare_sites_llm(
        client,
        cerebras,
        body,
        max_tokens=settings.CEREBRAS_COMPARE_MAX_TOKENS,
    )
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result.get("points") or []


@router.get("/generate_insight")
async def generate_insight(
    request: Request,
    site_id: str = Query(..., description="AirQo site _id"),
    start_date: date = Query(..., description="Start date (UTC) inclusive"),
    end_date: date = Query(..., description="End date (UTC) inclusive"),
) -> StreamingResponse:
    try:
        start_time, end_time = validate_and_format_historical_date_range(
            start_date, end_date
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    client: httpx.AsyncClient = request.app.state.http_client
    return StreamingResponse(
        stream_insight_sse(
            client,
            site_id,
            settings.AIRQO_API_KEY,
            start_time,
            end_time,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/dashboard-cards/{site_id}")
async def dashboard_cards(site_id: str, request: Request) -> dict[str, Any]:
    client: httpx.AsyncClient = request.app.state.http_client
    url = f"https://api.airqo.net/api/v2/devices/measurements/sites/{site_id}/recent"

    try:
        response = await client.get(url, params={"token": settings.AIRQO_API_KEY})
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=public_airqo_http_error_message(e),
        ) from e

    try:
        payload = response.json()
    except ValueError as e:
        raise HTTPException(
            status_code=502, detail="AirQo response was not valid JSON"
        ) from e

    measurements = payload.get("measurements") or []
    if not payload.get("success", False) or not measurements:
        raise HTTPException(status_code=404, detail="No measurements found for this site_id")

    measurement = measurements[0]
    site_details = measurement.get("siteDetails") or {}

    return {
        "aqi_color": measurement.get("aqi_color"),
        "aqi_category": measurement.get("aqi_category"),
        "aqi_color_name": measurement.get("aqi_color_name"),
        "aqi_ranges": compact_aqi_ranges(measurement.get("aqi_ranges")),
        "site_id": measurement.get("site_id"),
        "device_id": measurement.get("device_id"),
        "city": site_details.get("city"),
        "country": site_details.get("country"),
        "time": measurement.get("time"),
        "pm2_5_value": round_number((measurement.get("pm2_5") or {}).get("value")),
        "pm_10": round_number((measurement.get("pm10") or {}).get("value")),
    }
