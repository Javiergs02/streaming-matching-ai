"""Shared MongoDB match filter helpers for monthly and yearly aggregation scripts."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

PLATFORM_EVENT_TYPES: Dict[str, Any] = {
    "amazon": [
        "amazon.video.performance_recorded",
        "amazon.video.performance_svod",
        "amazon.video.performance_tvod",
    ],
    "youtube": "youtube.video.performance_recorded",
    "tencent": "tencent.video.performance_recorded",
    "youku": "youku.video.performance_recorded",
    "iqiyi": "iqiyi.video.performance_recorded",
}


def build_events_platform_filter(platform: Optional[str]) -> Dict[str, Any]:
    """Builds the platform filter for `video_performance_events` queries."""
    if not platform:
        return {}

    p_clean = platform.strip().lower()
    if not p_clean:
        return {}

    event_types = PLATFORM_EVENT_TYPES.get(p_clean)
    if isinstance(event_types, list):
        return {"metadata.event_type": {"$in": event_types}}
    if isinstance(event_types, str):
        return {"metadata.event_type": event_types}
    return {"payload.platform": p_clean}


def build_events_match_query(
    platform: Optional[str] = None,
    year: Optional[int] = None,
    run_all: bool = False,
    incremental_window: str = "60d",
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Builds the `$match` stage for pipelines reading `video_performance_events`."""
    match_query = build_events_platform_filter(platform)
    ref_now = now_utc or datetime.now(timezone.utc)

    if year:
        match_query["payload.date"] = {
            "$gte": f"{year}-01-01",
            "$lte": f"{year}-12-31",
        }
    elif not run_all:
        if incremental_window == "2y":
            prev_year = ref_now.year - 1
            match_query["payload.date"] = {"$gte": f"{prev_year}-01-01"}
        else:
            sixty_days_ago = (ref_now - timedelta(days=60)).strftime("%Y-%m-%d")
            match_query["payload.date"] = {"$gte": sixty_days_ago}

    return match_query


def build_summary_cleanup_filter(
    platform: Optional[str],
    year: Optional[int] = None,
    run_all: bool = False,
    time_field: str = "_id.month",
) -> Optional[Dict[str, Any]]:
    """Returns a safe purge filter before full-year/full-history Amazon summary rebuilds.

    Returns `None` for partial incremental runs and for YouTube so reconciled
    accounting summaries (e.g. 2024-2025) are never wiped accidentally.
    """
    if not platform or platform.strip().lower() != "amazon":
        return None
    if not (year is not None or run_all):
        return None

    purge_filter: Dict[str, Any] = {"_id.platform": "amazon"}
    if year is not None:
        purge_filter[time_field] = (
            {"$regex": f"^{year}"} if time_field == "_id.month" else str(year)
        )
    return purge_filter
