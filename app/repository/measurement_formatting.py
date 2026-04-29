from typing import Any


def round_number(value: Any, digits: int = 2) -> Any:
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return value


def compact_aqi_ranges(ranges: Any) -> Any:
    if not isinstance(ranges, dict):
        return ranges
    out: dict[str, Any] = {}
    for key, band in ranges.items():
        if not isinstance(band, dict):
            out[key] = band
            continue
        out[key] = {
            "min": round_number(band.get("min"), 2),
            "max": round_number(band.get("max"), 2),
        }
    return out
