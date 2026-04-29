from pydantic import BaseModel, Field


class DailyPmPoint(BaseModel):
    date: str = Field(..., description="Calendar day, YYYY-MM-DD")
    mean: float = Field(..., description="Mean PM2.5 (µg/m³) for that day")


class SiteCompareInput(BaseModel):
    site_name: str
    daily_pm: list[DailyPmPoint]


class CompareSitesRequest(BaseModel):
    first_site: SiteCompareInput
    second_site: SiteCompareInput
    third_site: SiteCompareInput | None = None
