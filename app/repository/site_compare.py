from __future__ import annotations

import json
from typing import Any

import httpx

from app.repository.llm_summary import (
    CerebrasSettings,
    parse_bullet_lines,
    post_cerebras_chat,
)
from app.schema.compare_sites import CompareSitesRequest
from app.utils.prompts import COMPARE_SITES_SYSTEM, COMPARE_SITES_USER_FOOTER


async def compare_sites_llm(
    client: httpx.AsyncClient,
    cerebras: CerebrasSettings,
    body: CompareSitesRequest,
    max_tokens: int = 700,
) -> dict[str, Any]:
    """
    Returns {"points": list[str], "error": None} on success, or
    {"points": None, "error": str} on LLM / configuration failure.
    """
    sites: dict[str, Any] = {
        "first_site": body.first_site.model_dump(),
        "second_site": body.second_site.model_dump(),
    }
    if body.third_site is not None:
        sites["third_site"] = body.third_site.model_dump()

    user_content = json.dumps(sites, separators=(",", ":"))
    user = f"{user_content}\n\n{COMPARE_SITES_USER_FOOTER}"
    out = await post_cerebras_chat(
        client, cerebras, COMPARE_SITES_SYSTEM, user, max_tokens=max_tokens
    )
    if "error" in out:
        return {"points": None, "error": out["error"]}
    points = parse_bullet_lines(out["content"], max_bullets=10)
    return {"points": points, "error": None}
