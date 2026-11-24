"""Parser and MongoDB event builder for iQIYI historical datasets (Amuse CC, Amuse LTV/France, Amuse Shanghai)."""

from __future__ import annotations

import calendar
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openpyxl
import xlrd

from core.domain.china import (
    IQIYI_CHANNEL_META,
    convert_cny_to_usd,
    get_iqiyi_series_metadata,
    normalize_excel_date,
    parse_cny_amount,
)

_YEAR_MONTH_RE = re.compile(r"(\d{4})年(\d{2})月")
_IP_FILENAME_SUFFIX_RE = re.compile(r"(?:_儿童收入按日期|收入明细(?:042023)?)$")


def _safe_int(val: Any) -> int:
    if val is None:
        return 0
    s = str(val).replace(",", "").strip()
    if not s or s in ("-", "--", "N/A", "nan", "None", "null"):
        return 0
    try:
        return int(round(float(s)))
    except ValueError:
        return 0


def _safe_float(val: Any) -> float:
    if val is None:
        return 0.0
    s = str(val).replace(",", "").strip()
    if not s or s in ("-", "--", "N/A", "nan", "None", "null"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _read_excel_rows(filepath: Path, sheet_name: str | None = None) -> list[list[Any]]:
    """Reads all non-empty rows from sheet 0 (or named sheet) across .xls and .xlsx workbooks."""
    ext = filepath.suffix.lower()
    if ext == ".xls":
        wb = xlrd.open_workbook(str(filepath))
        sh = wb.sheet_by_name(sheet_name) if (sheet_name and sheet_name in wb.sheet_names()) else wb.sheet_by_index(0)
        rows: list[list[Any]] = []
        for r in range(sh.nrows):
            vals: list[Any] = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                v = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        v = xlrd.xldate_as_datetime(v, wb.datemode).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                vals.append(v)
            if any(x is not None and str(x).strip() != "" for x in vals):
                rows.append(vals)
        return rows

    if ext == ".xlsx":
        # Sparse dimension XML metadata in iQIYI .xlsx exports truncates read_only=True to row 1.
        wb = openpyxl.load_workbook(filepath, read_only=False, data_only=True)
        try:
            ws = wb[sheet_name] if (sheet_name and sheet_name in wb.sheetnames) else wb.worksheets[0]
            rows = []
            for row in ws.iter_rows(values_only=True):
                vals = list(row)
                if any(x is not None and str(x).strip() != "" for x in vals):
                    rows.append(vals)
            return rows
        finally:
            wb.close()

    return []


def _find_header_idx(rows: list[list[Any]], first_col_candidates: tuple[str, ...]) -> int | None:
    for idx, row in enumerate(rows[:6]):
        c0 = str(row[0] or "").strip() if row else ""
        if c0 in first_col_candidates:
            return idx
    return None


def _build_iqiyi_event(
    meta: dict[str, str],
    date_str: str,
    rev_avod_cny: float,
    rev_svod_cny: float,
    views: int,
    watch_hours: float,
    comments: int,
    followers_gained: int,
    is_monthly_revenue: bool,
    occurred_at: str,
) -> dict[str, Any]:
    total_cny = rev_avod_cny + rev_svod_cny
    rev_total_usd, rate = convert_cny_to_usd(total_cny, date_str)
    rev_avod_usd, _ = convert_cny_to_usd(rev_avod_cny, date_str)
    rev_svod_usd, _ = convert_cny_to_usd(rev_svod_cny, date_str)

    if rev_avod_cny > 0 and rev_svod_cny > 0:
        model = "MIXED"
    elif rev_svod_cny > 0 or watch_hours > 0 or "_SVOD_" in meta["series_name"] or meta["video_id"] == "IQIYI_LTV_CHANNEL":
        model = "SVOD"
    else:
        model = "AVOD"

    vid = meta["video_id"]
    granularity = "channel" if vid in IQIYI_CHANNEL_META else "series"
    subplatform = meta.get("channel_name") or "Amuse CC (2463347304)"

    return {
        "metadata": {
            "event_id": str(uuid.uuid4()),
            "event_type": "iqiyi.video.performance_recorded",
            "resource_id": vid,
            "occurred_at": occurred_at,
            "cms_id": "IQIYI",
            "offer_type": model,
        },
        "payload": {
            "video_id": vid,
            "platform": "iqiyi",
            "geography": "CN",
            "date": date_str,
            "estimated_revenue": round(rev_total_usd, 6),
            "title": meta["title"],
            "ip_name": meta["ip_name"],
            "series_name": meta["series_name"],
            "extra_metrics": {
                "views": int(views),
                "estimated_minutes_watched": round(float(watch_hours) * 60.0, 4),
                "likes": 0,
                "comments": int(comments),
                "followers_gained": int(followers_gained),
                "shares": 0,
                "favorites": 0,
                "revenue_cny": round(total_cny, 4),
                "revenue_avod_cny": round(rev_avod_cny, 4),
                "revenue_svod_cny": round(rev_svod_cny, 4),
                "exchange_rate": rate,
                "revenue_avod": round(rev_avod_usd, 6),
                "revenue_svod": round(rev_svod_usd, 6),
                "revenue_tvod": 0.0,
                "monetization_model": model,
                "subplatform": subplatform,
                "granularity_level": granularity,
                "is_monthly_revenue": bool(is_monthly_revenue),
            },
        },
    }


def _parse_cc_avod(rev_dir: Path) -> dict[str, float]:
    """Parses Account 2463347304 (Amuse CC) daily AVOD revenue with max-dedup across video/total exports."""
    by_date: dict[str, float] = {}
    cc_dir = rev_dir / "Revenue CC"
    if not cc_dir.exists():
        return by_date

    for fp in sorted(cc_dir.iterdir()):
        if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() not in (".xls", ".xlsx"):
            continue
        rows = _read_excel_rows(fp)
        hi = _find_header_idx(rows, ("日期", "Date"))
        if hi is None:
            continue
        headers = [str(h or "").strip() for h in rows[hi]]
        for row in rows[hi + 1:]:
            d = normalize_excel_date(row[0] if row else None)
            if not d:
                continue
            rm = dict(zip(headers, row))
            tot = parse_cny_amount(rm.get("总收入（元）"))
            if "贴片广告分成" in rm or "信息流广告分成" in rm:
                comp = (
                    parse_cny_amount(rm.get("贴片广告分成"))
                    + parse_cny_amount(rm.get("信息流广告分成"))
                    + parse_cny_amount(rm.get("小视频广告分成"))
                )
            else:
                comp = (
                    parse_cny_amount(rm.get("视频广告收入", rm.get("视频广告收入（元）")))
                    + parse_cny_amount(rm.get("打赏收入", rm.get("打赏收入（元）")))
                    + parse_cny_amount(rm.get("带货佣金收入", rm.get("带货佣金收入（元）")))
                )
            val = max(tot, comp)
            if val > by_date.get(d, 0.0):
                by_date[d] = val
    return by_date


def _parse_ltv_avod(base: Path) -> dict[str, float]:
    """Parses Account 2484062153 (Amuse LTV) daily AVOD revenue (excluding 儿童会员收入 SVOD), plus 2017-Q1 Old fallback."""
    by_date: dict[str, float] = {}
    ltv_dir = base / "Revenue" / "Revenue LTV"
    if ltv_dir.exists():
        for fp in sorted(ltv_dir.iterdir()):
            if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() not in (".xls", ".xlsx"):
                continue
            rows = _read_excel_rows(fp)
            hi = _find_header_idx(rows, ("日期", "Date"))
            if hi is None:
                continue
            headers = [str(h or "").strip() for h in rows[hi]]
            for row in rows[hi + 1:]:
                d = normalize_excel_date(row[0] if row else None)
                if not d:
                    continue
                rm = dict(zip(headers, row))
                avod = (
                    parse_cny_amount(rm.get("视频广告收入", rm.get("视频广告收入（元）")))
                    + parse_cny_amount(rm.get("打赏收入", rm.get("打赏收入（元）")))
                    + parse_cny_amount(rm.get("带货佣金收入", rm.get("带货佣金收入（元）")))
                )
                if avod > by_date.get(d, 0.0):
                    by_date[d] = avod

    # Fill pre-2017-04-01 launch period (e.g. March 2017) from Old/Revenu LTV/Old Format if missing
    old_ltv_dir = base / "Old" / "Revenu LTV" / "Old Format"
    if old_ltv_dir.exists():
        for fp in sorted(old_ltv_dir.iterdir()):
            if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() not in (".xls", ".xlsx"):
                continue
            rows = _read_excel_rows(fp)
            hi = _find_header_idx(rows, ("日期", "Date"))
            if hi is None:
                continue
            headers = [str(h or "").strip() for h in rows[hi]]
            for row in rows[hi + 1:]:
                d = normalize_excel_date(row[0] if row else None)
                if not d or d >= "2017-04-01":
                    continue
                rm = dict(zip(headers, row))
                tot = parse_cny_amount(rm.get("总收入（元）"))
                if tot > by_date.get(d, 0.0):
                    by_date[d] = tot

    return by_date


def _parse_shanghai_account(rev_dir: Path) -> tuple[dict[str, float], dict[str, float]]:
    """Parses Account 4318775981759616 (Amuse Shanghai) daily AVOD and SVOD revenues."""
    avod_by_date: dict[str, float] = {}
    svod_by_date: dict[str, float] = {}

    avod_dir = rev_dir / "Revenue AVOD"
    if avod_dir.exists():
        for fp in sorted(avod_dir.iterdir()):
            if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() not in (".xls", ".xlsx"):
                continue
            rows = _read_excel_rows(fp)
            hi = _find_header_idx(rows, ("日期", "Date"))
            if hi is None:
                continue
            headers = [str(h or "").strip() for h in rows[hi]]
            for row in rows[hi + 1:]:
                d = normalize_excel_date(row[0] if row else None)
                if not d:
                    continue
                rm = dict(zip(headers, row))
                val = max(
                    parse_cny_amount(rm.get("总收入（元）")),
                    parse_cny_amount(rm.get("信息流广告分成（元）")) + parse_cny_amount(rm.get("贴片广告分成（元）")),
                )
                if val > avod_by_date.get(d, 0.0):
                    avod_by_date[d] = val

    svod_sources: list[Path] = []
    svod2_dir = rev_dir / "Revenue SVOD_2"
    if svod2_dir.exists():
        svod_sources.extend(sorted(p for p in svod2_dir.iterdir() if p.is_file() and not p.name.startswith("~$")))
    sh_file = rev_dir / "iQIYI_Amuse Shanghai_2025.05 to 2026.01.xls"
    if sh_file.exists():
        svod_sources.append(sh_file)

    for fp in svod_sources:
        if fp.suffix.lower() not in (".xls", ".xlsx"):
            continue
        rows = _read_excel_rows(fp)
        hi = _find_header_idx(rows, ("日期", "Date"))
        if hi is None:
            continue
        headers = [str(h or "").strip() for h in rows[hi]]
        for row in rows[hi + 1:]:
            d = normalize_excel_date(row[0] if row else None)
            if not d:
                continue
            rm = dict(zip(headers, row))
            val = parse_cny_amount(rm.get("总计（元）", rm.get("总计")))
            if val > svod_by_date.get(d, 0.0):
                svod_by_date[d] = val

    return avod_by_date, svod_by_date


def _parse_ltv_svod_reconciled(
    base: Path,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, str]]]:
    """Reconciles Account 2484062153 (Amuse LTV/France) SVOD revenue & watch hours across 4 eras with zero overlap."""
    rev_dir = base / "Revenue"
    meta_by_vid: dict[str, dict[str, str]] = {"IQIYI_LTV_CHANNEL": dict(IQIYI_CHANNEL_META["2484062153"])}

    # 1. Read daily per-IP files (normalized album prefixes, ignoring channel summary files)
    per_ip: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)  # vid -> date -> {cny, hrs}
    ip_dir = rev_dir / "Revenue SVOD per IP"
    if ip_dir.exists():
        for fp in sorted(ip_dir.iterdir()):
            if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() not in (".xls", ".xlsx"):
                continue
            raw_prefix = fp.stem.split("_2484062153_")[0].split("_4318775981759616_")[0]
            if "儿童收入按日期查看明细" in raw_prefix:
                continue
            alb_title = _IP_FILENAME_SUFFIX_RE.sub("", raw_prefix.replace("\u3000", "").replace("+", " ")).strip()
            meta = get_iqiyi_series_metadata(alb_title)
            vid = meta["video_id"]
            meta_by_vid[vid] = meta

            rows = _read_excel_rows(fp)
            hi = _find_header_idx(rows, ("日期", "Date"))
            if hi is None:
                continue
            headers = [str(h or "").strip() for h in rows[hi]]
            for row in rows[hi + 1:]:
                d = normalize_excel_date(row[0] if row else None)
                if not d:
                    continue
                rm = dict(zip(headers, row))
                if "总计（元）" in rm or "总计" in rm:
                    cny = parse_cny_amount(rm.get("总计（元）", rm.get("总计")))
                else:
                    cny = parse_cny_amount(rm.get("付费分成收入")) + parse_cny_amount(rm.get("广告分成收入"))
                hrs = _safe_float(rm.get("有效付费时长（时）"))

                cur = per_ip[vid].get(d)
                if cur is None:
                    per_ip[vid][d] = {"cny": cny, "hrs": hrs}
                else:
                    cur["cny"] = max(cur["cny"], cny)
                    cur["hrs"] = max(cur["hrs"], hrs)

    # 2. Read authoritative Monthly Revenue files (2019-01 .. 2023-03)
    mr_by_ym: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)  # ym -> vid -> {cny, hrs}
    mr_dir = base / "Albums" / "Album Perf SVOD" / "Monthly Revenue"
    if mr_dir.exists():
        for fp in sorted(mr_dir.iterdir()):
            if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() not in (".xls", ".xlsx"):
                continue
            rows = _read_excel_rows(fp)
            if len(rows) < 2:
                continue
            m = _YEAR_MONTH_RE.search(str(rows[0][0] or ""))
            if not m:
                continue
            ym = f"{m.group(1)}-{m.group(2)}"
            hi = _find_header_idx(rows, ("剧集",))
            if hi is None:
                continue
            headers = [str(h or "").strip() for h in rows[hi]]
            for row in rows[hi + 1:]:
                alb = str(row[0] or "").strip() if row else ""
                if not alb or alb in ("合计", "总计"):
                    continue
                rm = dict(zip(headers, row))
                meta = get_iqiyi_series_metadata(alb)
                vid = meta["video_id"]
                meta_by_vid[vid] = meta
                cny = parse_cny_amount(rm.get("总计", rm.get("总计（元）")))
                hrs = _safe_float(rm.get("有效付费时长（时）"))
                prev = mr_by_ym[ym].get(vid)
                if prev is None:
                    mr_by_ym[ym][vid] = {"cny": cny, "hrs": hrs}
                else:
                    prev["cny"] += cny
                    prev["hrs"] += hrs

    # 3. Read channel-level SVOD (Revenue/Revenue SVOD + iQIYI_Amuse France_2024.11 to 2026.01.xls)
    ch_svod: dict[str, float] = {}
    svod_sources: list[Path] = []
    svod_dir = rev_dir / "Revenue SVOD"
    if svod_dir.exists():
        svod_sources.extend(sorted(p for p in svod_dir.iterdir() if p.is_file() and not p.name.startswith("~$")))
    fr_file = rev_dir / "iQIYI_Amuse France_2024.11 to 2026.01.xls"
    if fr_file.exists():
        svod_sources.append(fr_file)

    for fp in svod_sources:
        if fp.suffix.lower() not in (".xls", ".xlsx"):
            continue
        rows = _read_excel_rows(fp)
        hi = _find_header_idx(rows, ("日期", "Date"))
        if hi is None:
            continue
        headers = [str(h or "").strip() for h in rows[hi]]
        for row in rows[hi + 1:]:
            d = normalize_excel_date(row[0] if row else None)
            if not d:
                continue
            rm = dict(zip(headers, row))
            if "儿童会员收入" in rm and "总计" not in rm and "总计（元）" not in rm:
                val = parse_cny_amount(rm.get("儿童会员收入"))
            else:
                val = parse_cny_amount(rm.get("总计（元）", rm.get("总计")))
            if val > ch_svod.get(d, 0.0):
                ch_svod[d] = val

    # 4. Assemble exact timeline across all 4 eras
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"cny": 0.0, "hrs": 0.0, "is_monthly": False}
    )

    covered_months_by_ip: set[str] = set()

    # Era 1 (< 2019-01-01) and Era 3 (2022-02-01 .. 2024-06-30): per_ip daily is complete & exact
    for vid, dmap in per_ip.items():
        for d, vals in dmap.items():
            if d < "2019-01-01" or ("2022-02-01" <= d <= "2024-06-30"):
                covered_months_by_ip.add(d[:7])
                b = buckets[(vid, d)]
                b["cny"] += vals["cny"]
                b["hrs"] += vals["hrs"]

    # Era 2 (2019-01 .. 2022-01): use Monthly Revenue exact totals allocated to days
    for ym, vid_map in sorted(mr_by_ym.items()):
        if not ("2019-01" <= ym <= "2022-01"):
            continue
        covered_months_by_ip.add(ym)
        year_i, mon_i = int(ym[:4]), int(ym[5:7])
        days_in_month = calendar.monthrange(year_i, mon_i)[1]
        for vid, mvals in vid_map.items():
            mr_cny = mvals["cny"]
            if mr_cny <= 0.0:
                continue
            ip_month_days = {
                d: v["cny"]
                for d, v in per_ip.get(vid, {}).items()
                if d.startswith(ym) and v["cny"] > 0.0
            }
            ip_sum = sum(ip_month_days.values())
            if ip_sum > 0.0:
                scale = mr_cny / ip_sum
                for d, d_val in ip_month_days.items():
                    b = buckets[(vid, d)]
                    b["cny"] += d_val * scale
            else:
                daily_flat = mr_cny / days_in_month
                for day_num in range(1, days_in_month + 1):
                    d = f"{ym}-{day_num:02d}"
                    b = buckets[(vid, d)]
                    b["cny"] += daily_flat
                    b["is_monthly"] = True

    # Fallback inside Era 2 when Monthly Revenue is absent in synthetic subsets -> use per_ip
    for vid, dmap in per_ip.items():
        for d, vals in dmap.items():
            if "2019-01-01" <= d <= "2022-01-31" and d[:7] not in mr_by_ym:
                covered_months_by_ip.add(d[:7])
                b = buckets[(vid, d)]
                b["cny"] += vals["cny"]
                b["hrs"] += vals["hrs"]

    # Era 4 (>= 2024-07-01) and fallback channel dates where no per-IP exists
    for d, val in ch_svod.items():
        if val <= 0.0:
            continue
        if d >= "2024-07-01" or d[:7] not in covered_months_by_ip:
            buckets[("IQIYI_LTV_CHANNEL", d)]["cny"] += val

    return buckets, meta_by_vid


def _parse_wide_old_detail_views(
    detail_dir: Path,
    cutoff_date: str = "2018-04-01",
) -> tuple[dict[tuple[str, str], dict[str, int]], dict[str, dict[str, str]]]:
    """Parses Old/Détail CC or Old/Détail LTV wide-format workbooks (< cutoff_date) ignoring Version BI duplicates."""
    out: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"views": 0, "followers": 0})
    meta_by_vid: dict[str, dict[str, str]] = {}
    if not detail_dir.exists():
        return out, meta_by_vid

    for fp in sorted(detail_dir.iterdir()):
        if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() not in (".xls", ".xlsx"):
            continue
        if "detail" not in fp.name.lower():
            continue

        for sheet_name, metric_key in (("剧集播放量", "views"), ("专辑涨粉量", "followers")):
            rows = _read_excel_rows(fp, sheet_name=sheet_name)
            if len(rows) < 2:
                continue
            date_cols = [normalize_excel_date(c) for c in rows[0][1:]]
            for row in rows[1:]:
                alb = str(row[0] or "").strip() if row else ""
                if not alb or alb in ("合计", "总计"):
                    continue
                meta = get_iqiyi_series_metadata(alb)
                vid = meta["video_id"]
                meta_by_vid[vid] = meta
                for col_idx, d in enumerate(date_cols, start=1):
                    if not d or d >= cutoff_date or col_idx >= len(row):
                        continue
                    val = _safe_int(row[col_idx])
                    if val > out[(vid, d)][metric_key]:
                        out[(vid, d)][metric_key] = val

    return out, meta_by_vid


def _match_svod_views_files(base: Path) -> list[tuple[Path, str]]:
    """Matches unnamed Views/SVOD Views/*.xlsx files 1-to-1 to LTV Accumulated Views album names."""
    svod_views_dir = base / "Views" / "SVOD Views"
    if not svod_views_dir.exists():
        return []
    files = sorted(
        p for p in svod_views_dir.iterdir()
        if p.is_file() and not p.name.startswith("~$") and p.suffix.lower() == ".xlsx"
    )
    if not files:
        return []

    acc_file = base / "Views" / "Accumulated Views" / "专辑列表数据_2484062153_20240828174923376.xlsx"
    acc_albums: list[tuple[str, int, int, int]] = []
    if acc_file.exists():
        rows = _read_excel_rows(acc_file)
        for row in rows[2:]:
            alb = str(row[0] or "").strip() if row else ""
            if alb and alb not in ("合计", "总计"):
                acc_albums.append((
                    alb,
                    _safe_int(row[1] if len(row) > 1 else 0),
                    _safe_int(row[2] if len(row) > 2 else 0),
                    _safe_int(row[3] if len(row) > 3 else 0),
                ))

    # Always use signature matching to match daily series files to accumulated albums
    matched: list[tuple[Path, str]] = []
    used: set[str] = set()
    for fp in files:
        rows = _read_excel_rows(fp)
        hi = _find_header_idx(rows, ("日期", "Date")) or 0
        v_s = sum(_safe_int(r[1] if len(r) > 1 else 0) for r in rows[hi + 1:])
        f_s = sum(_safe_int(r[2] if len(r) > 2 else 0) for r in rows[hi + 1:])
        c_s = sum(_safe_int(r[3] if len(r) > 3 else 0) for r in rows[hi + 1:])
        best_alb = fp.stem
        best_score = float("inf")
        for alb, av, af, ac in acc_albums:
            if alb in used:
                continue
            score = abs(f_s - af) * 10000 + abs(c_s - ac) * 1000 + abs(v_s - av) / 1e6
            if score < best_score:
                best_score = score
                best_alb = alb
        used.add(best_alb)
        matched.append((fp, best_alb))
    return matched


def _parse_all_views(
    base: Path,
) -> tuple[dict[tuple[str, str], dict[str, int]], dict[str, dict[str, str]]]:
    """Parses daily Views, Comments, and Followers across CC & LTV with strict non-overlapping windows."""
    out: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"views": 0, "comments": 0, "followers": 0}
    )
    meta_by_vid: dict[str, dict[str, str]] = {
        "IQIYI_CC_CHANNEL": dict(IQIYI_CHANNEL_META["2463347304"]),
        "IQIYI_LTV_CHANNEL": dict(IQIYI_CHANNEL_META["2484062153"]),
    }

    # 1. Views/Per Series (CC, 2018-04-01 onwards; excludes manual placeholder Total_Adjust_2017-2018.xlsx)
    per_series_dir = base / "Views" / "Per Series"
    if per_series_dir.exists():
        for fp in sorted(per_series_dir.iterdir()):
            if not fp.is_file() or fp.name.startswith("~$") or fp.suffix.lower() != ".xlsx":
                continue
            if "total_adjust" in fp.name.lower():
                continue
            alb_title = fp.stem.split("_专辑详情数据_")[0].strip()
            meta = get_iqiyi_series_metadata(alb_title)
            vid = meta["video_id"]
            meta_by_vid[vid] = meta

            rows = _read_excel_rows(fp)
            hi = _find_header_idx(rows, ("日期", "Date"))
            if hi is None:
                continue
            for row in rows[hi + 1:]:
                d = normalize_excel_date(row[0] if row else None)
                if not d:
                    continue
                cur = out[(vid, d)]
                cur["views"] = max(cur["views"], _safe_int(row[1] if len(row) > 1 else 0))
                cur["followers"] = max(cur["followers"], _safe_int(row[2] if len(row) > 2 else 0))
                cur["comments"] = max(cur["comments"], _safe_int(row[3] if len(row) > 3 else 0))

    # 2. Views/SVOD Views (LTV, 2018-04-01 .. 2024-07-31, 32 series; excludes duplicate Vues affichées)
    for fp, alb_title in _match_svod_views_files(base):
        meta = get_iqiyi_series_metadata(alb_title)
        vid = meta["video_id"]
        meta_by_vid[vid] = meta

        rows = _read_excel_rows(fp)
        hi = _find_header_idx(rows, ("日期", "Date"))
        if hi is None:
            continue
        for row in rows[hi + 1:]:
            d = normalize_excel_date(row[0] if row else None)
            if not d:
                continue
            cur = out[(vid, d)]
            cur["views"] = max(cur["views"], _safe_int(row[1] if len(row) > 1 else 0))
            cur["followers"] = max(cur["followers"], _safe_int(row[2] if len(row) > 2 else 0))
            cur["comments"] = max(cur["comments"], _safe_int(row[3] if len(row) > 3 else 0))

    # 3. Old/Détail CC & Old/Détail LTV (2017-10-25 .. 2018-03-31 only, exact per-series views & followers)
    for sub in ("Détail CC", "Détail LTV"):
        old_data, old_meta = _parse_wide_old_detail_views(base / "Old" / sub, cutoff_date="2018-04-01")
        meta_by_vid.update(old_meta)
        for (vid, d), vals in old_data.items():
            cur = out[(vid, d)]
            cur["views"] = max(cur["views"], vals["views"])
            cur["followers"] = max(cur["followers"], vals["followers"])

    # 4. Pre-2017-10-25 daily channel views: Views/Views Iqiyi CC 2017-2020.xlsx & Old/IQIYI_LTV_12.03.2018.xlsx
    cc_early = base / "Views" / "Views Iqiyi CC 2017-2020.xlsx"
    if cc_early.exists():
        rows = _read_excel_rows(cc_early)
        hi = _find_header_idx(rows, ("Date", "日期")) or 0
        for row in rows[hi + 1:]:
            d = normalize_excel_date(row[0] if row else None)
            if d and d < "2017-10-25":
                vw = _safe_int(row[1] if len(row) > 1 else 0)
                if vw > out[("IQIYI_CC_CHANNEL", d)]["views"]:
                    out[("IQIYI_CC_CHANNEL", d)]["views"] = vw

    ltv_early = base / "Old" / "IQIYI_LTV_12.03.2018.xlsx"
    if ltv_early.exists():
        rows = _read_excel_rows(ltv_early)
        hi = _find_header_idx(rows, ("Date", "日期")) or 0
        for row in rows[hi + 1:]:
            d = normalize_excel_date(row[0] if row else None)
            if d and d < "2017-10-25":
                vw = _safe_int(row[1] if len(row) > 1 else 0)
                if vw > out[("IQIYI_LTV_CHANNEL", d)]["views"]:
                    out[("IQIYI_LTV_CHANNEL", d)]["views"] = vw

    return out, meta_by_vid


def parse_iqiyi_directory(iqiyi_dir: Path | str) -> list[dict[str, Any]]:
    """Parses iQIYI historical workbooks into reconciled, deduplicated daily MongoDB event payloads."""
    base = Path(iqiyi_dir)
    occurred_at = datetime.now(timezone.utc).isoformat()

    rev_dir = base / "Revenue"
    cc_avod = _parse_cc_avod(rev_dir) if rev_dir.exists() else {}
    ltv_avod = _parse_ltv_avod(base)
    sh_avod, sh_svod = _parse_shanghai_account(rev_dir) if rev_dir.exists() else ({}, {})
    svod_buckets, meta_by_vid = _parse_ltv_svod_reconciled(base)
    views_buckets, views_meta = _parse_all_views(base)
    meta_by_vid.update(views_meta)
    for k, v in IQIYI_CHANNEL_META.items():
        meta_by_vid[v["video_id"]] = dict(v)

    combined: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "avod_cny": 0.0,
            "svod_cny": 0.0,
            "views": 0,
            "watch_hours": 0.0,
            "comments": 0,
            "followers": 0,
            "is_monthly": False,
        }
    )

    for d, val in cc_avod.items():
        combined[("IQIYI_CC_CHANNEL", d)]["avod_cny"] += val
    for d, val in ltv_avod.items():
        combined[("IQIYI_LTV_CHANNEL", d)]["avod_cny"] += val
    for d, val in sh_avod.items():
        combined[("IQIYI_SHANGHAI_CHANNEL", d)]["avod_cny"] += val
    for d, val in sh_svod.items():
        combined[("IQIYI_SHANGHAI_CHANNEL", d)]["svod_cny"] += val

    for (vid, d), vals in svod_buckets.items():
        c = combined[(vid, d)]
        c["svod_cny"] += vals["cny"]
        c["watch_hours"] += vals["hrs"]
        if vals["is_monthly"]:
            c["is_monthly"] = True

    for (vid, d), vals in views_buckets.items():
        c = combined[(vid, d)]
        c["views"] += vals["views"]
        c["comments"] += vals["comments"]
        c["followers"] += vals["followers"]

    events: list[dict[str, Any]] = []
    for vid, d in sorted(combined):
        b = combined[(vid, d)]
        if (
            b["avod_cny"] == 0.0
            and b["svod_cny"] == 0.0
            and b["views"] == 0
            and b["watch_hours"] == 0.0
            and b["comments"] == 0
            and b["followers"] == 0
        ):
            continue
        meta = meta_by_vid.get(vid) or get_iqiyi_series_metadata(vid)
        events.append(
            _build_iqiyi_event(
                meta=meta,
                date_str=d,
                rev_avod_cny=b["avod_cny"],
                rev_svod_cny=b["svod_cny"],
                views=b["views"],
                watch_hours=b["watch_hours"],
                comments=b["comments"],
                followers_gained=b["followers"],
                is_monthly_revenue=b["is_monthly"],
                occurred_at=occurred_at,
            )
        )
    return events


def summarize_iqiyi_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Computes an audit summary grouped by series/channel, account channel, model, and calendar year."""
    by_resource: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "watch_hours": 0.0, "cny": 0.0, "avod_cny": 0.0, "svod_cny": 0.0, "usd": 0.0, "min_date": None, "max_date": None}
    )
    by_year: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "watch_hours": 0.0, "cny": 0.0, "avod_cny": 0.0, "svod_cny": 0.0, "usd": 0.0, "comments": 0}
    )
    by_subplatform: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"events": 0, "views": 0, "watch_hours": 0.0, "cny": 0.0, "avod_cny": 0.0, "svod_cny": 0.0, "usd": 0.0}
    )
    unmatched: set[str] = set()

    for ev in events:
        p = ev["payload"]
        ex = p["extra_metrics"]
        rid = p["video_id"]
        d = p["date"]
        yr = d[:4]
        sub = ex.get("subplatform", "Unknown iQIYI Channel")
        wt_hrs = ex.get("estimated_minutes_watched", 0.0) / 60.0
        avod_cny = ex.get("revenue_avod_cny", 0.0)
        svod_cny = ex.get("revenue_svod_cny", 0.0)
        if p["ip_name"] == "CHANNEL_LEVEL" and rid not in ("IQIYI_LTV_CHANNEL", "IQIYI_SHANGHAI_CHANNEL"):
            unmatched.add(rid)

        for target in (by_resource[rid], by_year[yr], by_subplatform[sub]):
            target["events"] += 1
            target["views"] += ex["views"]
            target["watch_hours"] += wt_hrs
            target["cny"] += ex["revenue_cny"]
            target["avod_cny"] += avod_cny
            target["svod_cny"] += svod_cny
            target["usd"] += p["estimated_revenue"]
        by_year[yr]["comments"] += ex.get("comments", 0)

        r_entry = by_resource[rid]
        r_entry["min_date"] = d if (r_entry["min_date"] is None or d < r_entry["min_date"]) else r_entry["min_date"]
        r_entry["max_date"] = d if (r_entry["max_date"] is None or d > r_entry["max_date"]) else r_entry["max_date"]

    return {
        "total_events": len(events),
        "total_views": sum(e["payload"]["extra_metrics"]["views"] for e in events),
        "total_watch_hours": sum(e["payload"]["extra_metrics"]["estimated_minutes_watched"] for e in events) / 60.0,
        "total_comments": sum(e["payload"]["extra_metrics"]["comments"] for e in events),
        "total_cny": sum(e["payload"]["extra_metrics"]["revenue_cny"] for e in events),
        "total_avod_cny": sum(e["payload"]["extra_metrics"]["revenue_avod_cny"] for e in events),
        "total_svod_cny": sum(e["payload"]["extra_metrics"]["revenue_svod_cny"] for e in events),
        "total_usd": sum(e["payload"]["estimated_revenue"] for e in events),
        "by_subplatform": dict(sorted(by_subplatform.items())),
        "by_resource": dict(sorted(by_resource.items())),
        "by_year": dict(sorted(by_year.items())),
        "unmatched": sorted(unmatched),
    }
