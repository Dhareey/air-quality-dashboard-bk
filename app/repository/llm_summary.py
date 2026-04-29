"""
Compact Cerebras (OpenAI-compatible) chat for 7-point air-quality summaries.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import httpx

from app.utils.prompts import (
    INSIGHT_SUMMARY_SYSTEM,
    INSIGHT_SUMMARY_USER_FOOTER,
)

LLM_QUOTA_MESSAGE = (
    "Daily free LLM quota is used up. It will refresh tomorrow — summary is "
    "unavailable for now."
)
LLM_NOT_CONFIGURED = "LLM is not configured (set CEREBRAS_API_KEY in .env)."
LLM_REQUEST_FAILED = "The summary could not be generated. Please try again later."


@dataclass(frozen=True)
class CerebrasSettings:
    api_key: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float


def _build_daily_pm_compact(measurements: list[dict], max_rows: int = 31) -> list[dict[str, Any]]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for m in measurements:
        t = m.get("time")
        if not isinstance(t, str) or len(t) < 10:
            continue
        v = (m.get("pm2_5") or {}).get("value")
        if v is None or not isinstance(v, (int, float)):
            continue
        by_day[t[:10]].append(float(v))
    rows: list[dict[str, Any]] = []
    for day in sorted(by_day.keys())[-max_rows:]:
        vals = by_day[day]
        rows.append(
            {
                "date": day,
                "mean_pm2_5": round(sum(vals) / len(vals), 2),
                "readings": len(vals),
            }
        )
    return rows


def _site_device_snippet(measurements: list[dict]) -> dict[str, Any]:
    if not measurements:
        return {}
    m0 = measurements[0]
    site = m0.get("siteDetails") or {}
    devcat = m0.get("device_categories") or {}
    return {
        "device": m0.get("device"),
        "device_id": m0.get("device_id"),
        "site_name": site.get("name"),
        "city": site.get("city"),
        "region": site.get("region"),
        "country": site.get("country"),
        "location_name": site.get("location_name"),
        "data_provider": site.get("data_provider"),
        "site_category": (site.get("site_category") or {}).get("category")
        if isinstance(site.get("site_category"), dict)
        else site.get("site_category"),
        "lowcost": devcat.get("is_lowcost"),
        "static": devcat.get("is_static"),
    }


def build_summary_context(
    start_date_str: str,
    end_date_str: str,
    site_id: str,
    pm_hour_aggregate: list[dict[str, Any]],
    aqi_category_distribution: list[dict[str, Any]],
    all_measurements: list[dict],
) -> str:
    daily = _build_daily_pm_compact(all_measurements)
    site_dev = _site_device_snippet(all_measurements)

    payload = {
        "date_range_utc": {"start": start_date_str, "end": end_date_str, "site_id": site_id},
        "pm2_5_daily_mean_by_day": daily,
        "hourly_profile_utc": pm_hour_aggregate,
        "aqi_readings_count_by_category": aqi_category_distribution,
        "site_device": site_dev,
    }
    return json.dumps(payload, separators=(",", ":"))


def parse_bullet_lines(assistant_text: str, max_bullets: int = 7) -> list[str]:
    lines: list[str] = []
    for line in assistant_text.strip().split("\n"):
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[-*•]\s*", "", s)
        s = re.sub(r"^\d+[\).]\s*", "", s)
        s = s.strip()
        if s:
            lines.append(s)
    if len(lines) > max_bullets:
        return lines[:max_bullets]
    return lines


async def post_cerebras_chat(
    client: httpx.AsyncClient,
    settings: CerebrasSettings,
    system: str,
    user: str,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Single chat completion. On success: {"content": "..."} .
    On failure: {"error": "..."} (message suitable for client / HTTPException).
    """
    if not (settings.api_key and settings.api_key.strip()):
        return {"error": LLM_NOT_CONFIGURED}

    tokens = max_tokens if max_tokens is not None else settings.max_tokens
    url = settings.base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": tokens,
        "temperature": settings.temperature,
    }
    try:
        r = await client.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0),
        )
    except httpx.HTTPError as e:
        return {"error": f"{LLM_REQUEST_FAILED} ({e!s})"}

    if r.status_code == 429:
        return {"error": LLM_QUOTA_MESSAGE}

    try:
        data = r.json()
    except ValueError:
        return {"error": LLM_REQUEST_FAILED}

    if r.status_code >= 400:
        err = _extract_error_message(data) or f"HTTP {r.status_code}"
        if r.status_code == 429 or _is_quota_error_text(err):
            return {"error": LLM_QUOTA_MESSAGE}
        return {"error": err}

    try:
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
    except (IndexError, AttributeError, TypeError):
        content = ""
    if not (content and str(content).strip()):
        return {"error": LLM_REQUEST_FAILED}
    return {"content": str(content).strip()}


async def call_cerebras_bullet_summary(
    client: httpx.AsyncClient,
    settings: CerebrasSettings,
    user_content: str,
) -> dict[str, Any]:
    user = f"{user_content}\n\n{INSIGHT_SUMMARY_USER_FOOTER}"
    out = await post_cerebras_chat(
        client, settings, INSIGHT_SUMMARY_SYSTEM, user, max_tokens=None
    )
    if "error" in out:
        return {"error": out["error"], "bullets": None}
    bullets = parse_bullet_lines(out["content"], max_bullets=7)
    return {"bullets": bullets, "error": None}


def _extract_error_message(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, dict) and "message" in err:
        return str(err.get("message"))
    if isinstance(err, str):
        return err
    if "message" in data:
        return str(data.get("message"))
    return None


def _is_quota_error_text(s: str) -> bool:
    t = s.lower()
    return any(
        w in t
        for w in (
            "quota",
            "rate limit",
            "exceeded your",
            "out of",
            "billing",
            "credits",
            "limit",
        )
    )
