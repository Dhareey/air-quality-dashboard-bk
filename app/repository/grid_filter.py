from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

TARGET_GRID_NAMES = frozenset({"ghana", "nigeria"})
COUNTRY_KEY_ORDER: tuple[str, ...] = ("nigeria", "ghana")
RECENT_WINDOW = timedelta(days=31)


def parse_last_raw_data(value: Any) -> datetime | None:
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


def is_last_raw_data_recent(dt: datetime) -> bool:
    now = datetime.now(timezone.utc)
    oldest = now - RECENT_WINDOW
    return oldest <= dt <= now


def build_filter_config_response(grids: list) -> list[dict[str, dict[str, list[dict]]]]:
    by_country: dict[str, dict[str, list[dict]]] = {}
    for grid in grids:
        gname = (grid.get("name") or "").strip().lower()
        if gname not in TARGET_GRID_NAMES:
            continue
        by_region: dict[str, list[dict]] = defaultdict(list)
        for site in grid.get("sites", []):
            if site.get("isOnline") is not True:
                continue
            raw_ts = parse_last_raw_data(site.get("lastRawData"))
            if raw_ts is None or not is_last_raw_data_recent(raw_ts):
                continue
            region_key = (site.get("region") or "").strip() or "Unknown"
            by_region[region_key].append(
                {
                    "site_id": site.get("_id"),
                    "name": site.get("name"),
                    "city": site.get("city"),
                    "lastRawData": site.get("lastRawData"),
                }
            )
        by_country[gname] = dict(sorted(by_region.items(), key=lambda x: x[0]))

    ordered: OrderedDict[str, dict] = OrderedDict()
    for key in COUNTRY_KEY_ORDER:
        if key in by_country:
            ordered[key] = by_country[key]
    for key, value in by_country.items():
        if key not in ordered:
            ordered[key] = value

    return [dict(ordered)]
