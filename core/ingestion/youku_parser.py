"""Parser and MongoDB event builder for Youku historical datasets (DaYu + Open Platform)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl

from core.domain.china import (
    YOUKU_DAYU_META,
    convert_cny_to_usd,
    get_youku_series_metadata,
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


def _safe_float(val: Any) -> float:
    if val is None or str(val).strip() == "":
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except ValueError:
        return 0.0


def _build_youku_event(
    meta: dict[str, str],
    date_str: str,
    rev_avod_cny: float,
    rev_svod_cny: float,
    views: int,
    watch_hours: float,
    likes: int,
    comments: int,
    shares: int,
    favorites: int,
    is_monthly_revenue: bool,
    occurred_at: str,
) -> dict[str, Any]:
    rev_avod_usd, rate = convert_cny_to_usd(rev_avod_cny, date_str)
    rev_svod_usd, _ = convert_cny_to_usd(rev_svod_cny, date_str)
    rev_cny_total = round(rev_avod_cny + rev_svod_cny, 4)
    rev_usd_total = round(rev_avod_usd + rev_svod_usd, 6)

    subplatform = meta["subplatform"]
    if subplatform == "DaYu Platform" and rev_svod_cny == 0:
        model = "AVOD"
    elif rev_avod_cny > 0 and rev_svod_cny > 0:
        model = "AVOD+SVOD"
    elif rev_svod_cny > 0 or (watch_hours > 0 and rev_avod_cny == 0):
        model = "SVOD"
    else:
        model = "AVOD"
    cms_id = "YOUKU_DAYU" if subplatform == "DaYu Platform" else "YOUKU_OPEN_PLATFORM"

    return {
        "metadata": {
            "event_id": str(uuid.uuid4()),
            "event_type": "youku.video.performance_recorded",
            "resource_id": meta["video_id"],
            "occurred_at": occurred_at,
            "cms_id": cms_id,
            "offer_type": model,
        },
        "payload": {
            "video_id": meta["video_id"],
            "platform": "youku",
            "geography": "CN",
            "date": date_str,
            "estimated_revenue": rev_usd_total,
            "title": meta["title"],
            "ip_name": meta["ip_name"],
            "series_name": meta["series_name"],
            "extra_metrics": {
                "views": int(views),
                "estimated_minutes_watched": round(watch_hours * 60.0, 2),
                "likes": int(likes),
                "comments": int(comments),
                "shares": int(shares),
                "favorites": int(favorites),
                "revenue_cny": rev_cny_total,
                "exchange_rate": rate,
                "revenue_avod": round(rev_avod_usd, 6),
                "revenue_svod": round(rev_svod_usd, 6),
                "revenue_tvod": 0.0,
                "monetization_model": model,
                "subplatform": subplatform,
                "is_monthly_revenue": bool(is_monthly_revenue),
                "granularity_level": "channel" if subplatform == "DaYu Platform" else "series",
            },
        },
    }


def _parse_dayu_platform(dayu_dir: Path, occurred_at: str) -> list[dict[str, Any]]:
    if not dayu_dir.exists():
        return []

    events: list[dict[str, Any]] = []
    for channel_code, meta in YOUKU_DAYU_META.items():
        daily: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "rev_cny": 0.0,
                "views": 0,
                "watch_mins": 0.0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "favorites": 0,
            }
        )

        rev_file = dayu_dir / "Revenus" / f"YOUKU revenus {channel_code}.xlsx"
        if rev_file.exists():
            wb = openpyxl.load_workbook(rev_file, read_only=True, data_only=True)
            try:
                sheet_name = "Feuil1" if "Feuil1" in wb.sheetnames else wb.sheetnames[0]
                ws = wb[sheet_name]
                rows_iter = ws.iter_rows(values_only=True)
                next(rows_iter, None)  # header
                for row in rows_iter:
                    if not row or row[0] is None:
                        continue
                    date_str = normalize_excel_date(row[0])
                    if not date_str:
                        continue
                    day_cny = sum(parse_cny_amount(val) for val in row[1:] if val is not None)
                    if day_cny > 0:
                        daily[date_str]["rev_cny"] += day_cny
            finally:
                wb.close()

        vues_dir = dayu_dir / "Vues WT" / channel_code
        if vues_dir.exists():
            for xlsx_path in sorted(vues_dir.glob("*.xlsx")):
                if xlsx_path.name.startswith("~$"):
                    continue
                wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
                try:
                    ws = wb[wb.sheetnames[0]]
                    rows_iter = ws.iter_rows(values_only=True)
                    header_row = next(rows_iter, None)
                    if not header_row:
                        continue
                    col_idx = {
                        str(col).strip(): i
                        for i, col in enumerate(header_row)
                        if col is not None and str(col).strip()
                    }
                    if "日期" not in col_idx or "播放" not in col_idx:
                        continue

                    i_dt = col_idx["日期"]
                    i_v = col_idx["播放"]
                    i_lk = col_idx.get("点赞")
                    i_cm = col_idx.get("评论")
                    i_sh = col_idx.get("分享")
                    i_fv = col_idx.get("收藏")

                    for row in rows_iter:
                        if not row or i_dt >= len(row) or row[i_dt] is None:
                            continue
                        date_str = normalize_excel_date(row[i_dt])
                        if not date_str:
                            continue
                        v = _safe_int(row[i_v]) if i_v < len(row) else 0
                        raw_lk = row[i_lk] if (i_lk is not None and i_lk < len(row)) else None
                        raw_cm = row[i_cm] if (i_cm is not None and i_cm < len(row)) else None
                        raw_sh = row[i_sh] if (i_sh is not None and i_sh < len(row)) else None
                        raw_fv = row[i_fv] if (i_fv is not None and i_fv < len(row)) else None

                        # Hasta el 2019-04-16 las tablas legacy de DaYu exportaron Watch Time (min) en la
                        # columna etiquetada '评论', UV en '点赞' y ratio decimal en '分享'.
                        is_legacy_wt = (
                            date_str <= "2019-04-16"
                            or (isinstance(raw_cm, float) and raw_cm != int(raw_cm))
                            or (isinstance(raw_sh, float) and raw_sh != int(raw_sh))
                        )

                        entry = daily[date_str]
                        if is_legacy_wt:
                            wt_mins = _safe_float(raw_cm)
                            if v == 0 and wt_mins == 0.0:
                                continue
                            entry["views"] = max(entry["views"], v)
                            entry["watch_mins"] = max(entry["watch_mins"], wt_mins)
                        else:
                            lk = _safe_int(raw_lk)
                            cm = _safe_int(raw_cm)
                            sh = _safe_int(raw_sh)
                            fv = _safe_int(raw_fv)
                            if v == 0 and lk == 0 and cm == 0 and sh == 0 and fv == 0:
                                continue
                            # Boundary cutoff exports contain partial/zero days; take max per date
                            entry["views"] = max(entry["views"], v)
                            entry["likes"] = max(entry["likes"], lk)
                            entry["comments"] = max(entry["comments"], cm)
                            entry["shares"] = max(entry["shares"], sh)
                            entry["favorites"] = max(entry["favorites"], fv)
                finally:
                    wb.close()

        for date_str in sorted(daily):
            d = daily[date_str]
            if d["rev_cny"] == 0.0 and d["views"] == 0 and d["watch_mins"] == 0.0 and d["likes"] == 0 and d["comments"] == 0:
                continue
            events.append(
                _build_youku_event(
                    meta=meta,
                    date_str=date_str,
                    rev_avod_cny=d["rev_cny"],
                    rev_svod_cny=0.0,
                    views=d["views"],
                    watch_hours=d["watch_mins"] / 60.0,
                    likes=d["likes"],
                    comments=d["comments"],
                    shares=d["shares"],
                    favorites=d["favorites"],
                    is_monthly_revenue=False,
                    occurred_at=occurred_at,
                )
            )

    return events


def _parse_open_platform(open_dir: Path, occurred_at: str) -> list[dict[str, Any]]:
    if not open_dir.exists():
        return []

    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"avod_cny": 0.0, "svod_cny": 0.0, "views": 0, "watch_hours": 0.0, "is_monthly": False}
    )
    meta_by_vid: dict[str, dict[str, str]] = {}

    rev_file = open_dir / "Youku_Monthly_Revenue.xlsx"
    if rev_file.exists():
        wb = openpyxl.load_workbook(rev_file, read_only=True, data_only=True)
        try:
            for sh_name, rev_key in [
                ("Monthly_AVOD_revenue_album", "avod_cny"),
                ("Monthly_SVOD_revenue_album", "svod_cny"),
            ]:
                if sh_name not in wb.sheetnames:
                    continue
                ws = wb[sh_name]
                rows_iter = ws.iter_rows(values_only=True)
                _contract_row = next(rows_iter, None)
                title_row = next(rows_iter, None)
                ip_row = next(rows_iter, None)
                if not title_row or not ip_row:
                    continue

                # Determine valid album columns (explicitly exclude Total Monthly revenue column)
                album_cols: list[tuple[int, dict[str, str]]] = []
                max_cols = min(len(title_row), len(ip_row))
                for c_idx in range(1, max_cols):
                    ip_label = str(ip_row[c_idx] or "").strip()
                    title_label = str(title_row[c_idx] or "").strip()
                    if "total" in ip_label.lower() or not title_label:
                        if "total" in ip_label.lower():
                            break
                        continue
                    meta = get_youku_series_metadata(title_label)
                    meta_by_vid[meta["video_id"]] = meta
                    album_cols.append((c_idx, meta))

                for row in rows_iter:
                    if not row or row[0] is None:
                        continue
                    date_str = normalize_excel_date(row[0])
                    if not date_str:
                        continue
                    month_day = f"{date_str[:7]}-01"
                    for c_idx, meta in album_cols:
                        if c_idx >= len(row):
                            continue
                        val_cny = parse_cny_amount(row[c_idx])
                        if val_cny <= 0.0:
                            continue
                        b = buckets[(meta["video_id"], month_day)]
                        b[rev_key] += val_cny
                        b["is_monthly"] = True
        finally:
            wb.close()

    views_dir = open_dir / "Views per Series"
    if views_dir.exists():
        for xlsx_path in sorted(views_dir.glob("*.xlsx")):
            if xlsx_path.name.startswith("~$"):
                continue
            wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
            try:
                ws = wb[wb.sheetnames[0]]
                rows_iter = ws.iter_rows(values_only=True)
                header_row = next(rows_iter, None)
                if not header_row or len(header_row) < 3:
                    continue
                metric_col = str(header_row[2] or "").strip()
                is_watch_time = "时长" in metric_col

                for row in rows_iter:
                    if not row or len(row) < 3 or row[0] is None or row[1] is None:
                        continue
                    title_label = str(row[0]).strip()
                    date_str = normalize_excel_date(row[1])
                    if not title_label or not date_str:
                        continue
                    meta = get_youku_series_metadata(title_label)
                    vid = meta["video_id"]
                    meta_by_vid[vid] = meta

                    b = buckets[(vid, date_str)]
                    if is_watch_time:
                        wh = _safe_float(row[2])
                        if wh > 0:
                            b["watch_hours"] = max(b["watch_hours"], wh)
                    else:
                        vw = _safe_int(row[2])
                        if vw > 0:
                            b["views"] = max(b["views"], vw)
            finally:
                wb.close()

    events: list[dict[str, Any]] = []
    for (vid, date_str) in sorted(buckets):
        b = buckets[(vid, date_str)]
        if b["avod_cny"] == 0.0 and b["svod_cny"] == 0.0 and b["views"] == 0 and b["watch_hours"] == 0.0:
            continue
        meta = meta_by_vid.get(vid) or get_youku_series_metadata(vid)
        events.append(
            _build_youku_event(
                meta=meta,
                date_str=date_str,
                rev_avod_cny=b["avod_cny"],
                rev_svod_cny=b["svod_cny"],
                views=b["views"],
                watch_hours=b["watch_hours"],
                likes=0,
                comments=0,
                shares=0,
                favorites=0,
                is_monthly_revenue=b["is_monthly"],
                occurred_at=occurred_at,
            )
        )

    return events


def parse_youku_directory(youku_dir: Path | str) -> list[dict[str, Any]]:
    """Parses Youku historical workbooks (DaYu + Open Platform) into standardized MongoDB events."""
    base = Path(youku_dir)
    occurred_at = datetime.now(timezone.utc).isoformat()
    events: list[dict[str, Any]] = []
    events.extend(_parse_dayu_platform(base / "DaYu Platform", occurred_at))
    events.extend(_parse_open_platform(base / "Open Platform", occurred_at))
    return events


def summarize_youku_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Computes an audit summary grouped by series/channel, subplatform, and calendar year."""
    by_resource: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "watch_hours": 0.0, "cny": 0.0, "usd": 0.0, "min_date": None, "max_date": None}
    )
    by_year: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "watch_hours": 0.0, "cny": 0.0, "usd": 0.0}
    )
    by_subplatform: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "watch_hours": 0.0, "cny": 0.0, "usd": 0.0}
    )

    for ev in events:
        p = ev["payload"]
        ex = p["extra_metrics"]
        rid = p["video_id"]
        d = p["date"]
        yr = d[:4]
        sub = ex.get("subplatform", "Open Platform")
        wt_hrs = ex.get("estimated_minutes_watched", 0.0) / 60.0

        for target in (by_resource[rid], by_year[yr], by_subplatform[sub]):
            target["events"] += 1
            target["views"] += ex["views"]
            target["watch_hours"] += wt_hrs
            target["cny"] += ex["revenue_cny"]
            target["usd"] += p["estimated_revenue"]

        r_entry = by_resource[rid]
        r_entry["min_date"] = d if (r_entry["min_date"] is None or d < r_entry["min_date"]) else r_entry["min_date"]
        r_entry["max_date"] = d if (r_entry["max_date"] is None or d > r_entry["max_date"]) else r_entry["max_date"]

    return {
        "total_events": len(events),
        "total_views": sum(e["payload"]["extra_metrics"]["views"] for e in events),
        "total_watch_hours": sum(e["payload"]["extra_metrics"]["estimated_minutes_watched"] for e in events) / 60.0,
        "total_cny": sum(e["payload"]["extra_metrics"]["revenue_cny"] for e in events),
        "total_usd": sum(e["payload"]["estimated_revenue"] for e in events),
        "by_subplatform": dict(sorted(by_subplatform.items())),
        "by_resource": dict(sorted(by_resource.items())),
        "by_year": dict(sorted(by_year.items())),
    }
