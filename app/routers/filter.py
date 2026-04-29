import httpx
from fastapi import APIRouter, HTTPException, Request

from app.config.settings import settings
from app.repository.grid_filter import build_filter_config_response

router = APIRouter(tags=["dashboard"])


@router.get("/filter_config")
async def filter_config(request: Request) -> list[dict[str, dict[str, list[dict]]]]:
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        r = await client.get(settings.AIRQO_GRIDS_SUMMARY_URL)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach AirQo grids API: {e!s}"
        ) from e

    try:
        payload = r.json()
    except ValueError as e:
        raise HTTPException(
            status_code=502, detail="AirQo response was not valid JSON"
        ) from e

    if not payload.get("success", False) or "grids" not in payload:
        raise HTTPException(
            status_code=502, detail="Unexpected AirQo response shape or success=false"
        )

    return build_filter_config_response(list(payload.get("grids") or []))
