"""Parser and MongoDB event builder for Tencent Video historical datasets (AVOD + SVOD)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl

from core.domain.china import (
    TENCENT_AVOD_META,
    TENCENT_SVOD_SERIES_MAP,
    convert_cny_to_usd,
    normalize_excel_date,
    parse_cny_amount,
)


def _safe_int(val: Any) -> int:
    if val is None or str(val).strip() == "":
        return 0
    try:
        return int(round(float(str(val).replace(",", "").strip())))
    except ValueError:
        return 0


def _build_tencent_event(
    video_id: str,
    date_str: str,
    rev_cny: float,
    views: int,
    meta: dict[str, str],
    occurred_at: str,
) -> dict[str, Any]:
    rev_usd, rate = convert_cny_to_usd(rev_cny, date_str)
    rev_usd_round = round(rev_usd, 6)
    rev_cny_round = round(rev_cny, 4)
    model = meta["monetization_model"]

    return {
        "metadata": {
            "event_id": str(uuid.uuid4()),
            "event_type": "tencent.video.performance_recorded",
            "resource_id": video_id,
            "occurred_at": occurred_at,
            "cms_id": "TENCENT_VIDEO",
            "offer_type": model,
        },
        "payload": {
            "video_id": video_id,
            "platform": "tencent",
            "geography": "CN",
            "date": date_str,
            "estimated_revenue": rev_usd_round,
            "title": meta["title"],
            "ip_name": meta["ip_name"],
            "series_name": meta["series_name"],
            "extra_metrics": {
                "views": int(views),
                "estimated_minutes_watched": 0.0,
                "revenue_cny": rev_cny_round,
                "exchange_rate": rate,
                "revenue_svod": rev_usd_round if model == "SVOD" else 0.0,
                "revenue_avod": rev_usd_round if model == "AVOD" else 0.0,
                "revenue_tvod": 0.0,
                "monetization_model": model,
                "granularity_level": "series" if model == "SVOD" else "channel",
            },
        },
    }


def _parse_svod_workbook(svod_path: Path, occurred_at: str) -> list[dict[str, Any]]:
    if not svod_path.exists():
        return []

    wb = openpyxl.load_workbook(svod_path, read_only=True, data_only=True)
    events: list[dict[str, Any]] = []
    try:
        for sheet_code, meta in TENCENT_SVOD_SERIES_MAP.items():
            if sheet_code not in wb.sheetnames:
                continue
            ws = wb[sheet_code]
            rows_iter = ws.iter_rows(values_only=True)
            header_row = next(rows_iter, None)
            if not header_row:
                continue

            headers = [str(h).strip().lower() if h is not None else "" for h in header_row]
            rev_indices = [
                i for i, h in enumerate(headers) if "revenue" in h
            ]
            views_idx = next((i for i, h in enumerate(headers) if "view" in h), None)

            daily_agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"cny": 0.0, "views": 0})
            for row in rows_iter:
                if not row or row[0] is None:
                    continue
                date_str = normalize_excel_date(row[0])
                if not date_str:
                    continue

                rev_cny = sum(
                    parse_cny_amount(row[idx]) for idx in rev_indices if idx < len(row)
                )
                views = _safe_int(row[views_idx]) if (views_idx is not None and views_idx < len(row)) else 0

                if rev_cny == 0.0 and views == 0:
                    continue
                daily_agg[date_str]["cny"] += rev_cny
                daily_agg[date_str]["views"] += views

            video_id = f"TENCENT_SVOD_{sheet_code}"
            for date_str in sorted(daily_agg):
                agg = daily_agg[date_str]
                events.append(
                    _build_tencent_event(
                        video_id=video_id,
                        date_str=date_str,
                        rev_cny=agg["cny"],
                        views=agg["views"],
                        meta=meta,
                        occurred_at=occurred_at,
                    )
                )
    finally:
        wb.close()
    return events


def _parse_avod_files(avod_dir: Path, occurred_at: str) -> list[dict[str, Any]]:
    if not avod_dir.exists():
        return []

    daily_agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"cny": 0.0, "views": 0})

    main_file = avod_dir / "TENCENT.xlsx"
    if main_file.exists():
        wb = openpyxl.load_workbook(main_file, read_only=True, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            rows_iter = ws.iter_rows(values_only=True)
            next(rows_iter, None)
            for row in rows_iter:
                if not row or row[0] is None:
                    continue
                date_str = normalize_excel_date(row[0])
                if not date_str:
                    continue
                views = _safe_int(row[1]) if len(row) > 1 else 0
                rev_cny = parse_cny_amount(row[2]) if len(row) > 2 else 0.0
                if rev_cny == 0.0 and views == 0:
                    continue
                daily_agg[date_str]["views"] += views
                daily_agg[date_str]["cny"] += rev_cny
        finally:
            wb.close()

    extra_file = avod_dir / "TENCENT_AVOD_2.xlsx"
    if extra_file.exists():
        wb = openpyxl.load_workbook(extra_file, read_only=True, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            rows_iter = ws.iter_rows(values_only=True)
            next(rows_iter, None)
            for row in rows_iter:
                if not row or row[0] is None:
                    continue
                date_str = normalize_excel_date(row[0])
                if not date_str:
                    continue
                rev_cny = parse_cny_amount(row[2]) if len(row) > 2 else 0.0
                if rev_cny == 0.0:
                    continue
                daily_agg[date_str]["cny"] += rev_cny
        finally:
            wb.close()

    events: list[dict[str, Any]] = []
    for date_str in sorted(daily_agg):
        agg = daily_agg[date_str]
        events.append(
            _build_tencent_event(
                video_id="TENCENT_AVOD_CHANNEL",
                date_str=date_str,
                rev_cny=agg["cny"],
                views=agg["views"],
                meta=TENCENT_AVOD_META,
                occurred_at=occurred_at,
            )
        )
    return events


def parse_tencent_directory(tencent_dir: Path | str) -> list[dict[str, Any]]:
    """Parses Tencent AVOD and SVOD historical workbooks into standardized MongoDB event payloads."""
    base = Path(tencent_dir)
    occurred_at = datetime.now(timezone.utc).isoformat()
    events: list[dict[str, Any]] = []
    events.extend(_parse_svod_workbook(base / "SVOD" / "TENCENT_SVOD_Revenue.xlsx", occurred_at))
    events.extend(_parse_avod_files(base / "AVOD", occurred_at))
    return events


def summarize_tencent_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Computes an audit summary grouped by series/channel and calendar year."""
    by_resource: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "cny": 0.0, "usd": 0.0, "min_date": None, "max_date": None}
    )
    by_year: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "cny": 0.0, "usd": 0.0}
    )

    for ev in events:
        p = ev["payload"]
        ex = p["extra_metrics"]
        rid = p["video_id"]
        d = p["date"]
        yr = d[:4]

        r_entry = by_resource[rid]
        r_entry["events"] += 1
        r_entry["views"] += ex["views"]
        r_entry["cny"] += ex["revenue_cny"]
        r_entry["usd"] += p["estimated_revenue"]
        r_entry["min_date"] = d if (r_entry["min_date"] is None or d < r_entry["min_date"]) else r_entry["min_date"]
        r_entry["max_date"] = d if (r_entry["max_date"] is None or d > r_entry["max_date"]) else r_entry["max_date"]

        y_entry = by_year[yr]
        y_entry["events"] += 1
        y_entry["views"] += ex["views"]
        y_entry["cny"] += ex["revenue_cny"]
        y_entry["usd"] += p["estimated_revenue"]

    return {
        "total_events": len(events),
        "total_views": sum(e["payload"]["extra_metrics"]["views"] for e in events),
        "total_cny": sum(e["payload"]["extra_metrics"]["revenue_cny"] for e in events),
        "total_usd": sum(e["payload"]["estimated_revenue"] for e in events),
        "by_resource": dict(sorted(by_resource.items())),
        "by_year": dict(sorted(by_year.items())),
    }
