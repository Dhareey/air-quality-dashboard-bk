import httpx
from fastapi import APIRouter, HTTPException, Request

from app.config.settings import settings
from app.repository.grid_filter import build_filter_config_response
from app.utils.airqo_client import airqo_get
from app.utils.http_safe import public_airqo_http_error_message

router = APIRouter(tags=["dashboard"])


@router.get("/filter_config")
async def filter_config(request: Request) -> list[dict[str, dict[str, list[dict]]]]:
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        r = await airqo_get(client, settings.AIRQO_GRIDS_SUMMARY_URL)
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502, detail=public_airqo_http_error_message(e)
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
