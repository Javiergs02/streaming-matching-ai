"""Historical Amazon Prime Video Revenue Parser and Transformer.

Processes Amazon historical revenue reports (Batches 2017-2019, Monthly Reports 2020-2025,
and detailed earnings TVOD/SVOD files) into canonical analytics reports matching
the schema of data/output/analytics_reports/analytics_reports_MM_YYYY.csv.
"""

from __future__ import annotations

import csv
import logging
import re
import string
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.normalization.series_alias import resolve_franchise_project

log = logging.getLogger(__name__)

# Standard FX rates to convert non-USD royalties to USD ($)
FX_RATES: Dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.0870,
    "GBP": 1.2717,
    "JPY": 0.006739,
    "INR": 0.012065,
    "CAD": 0.7391,
    "AUD": 0.6630,
    "BRL": 0.1739,
    "MXN": 0.0500,
    "SEK": 0.0957,
    "PLN": 0.2500,
    "TRY": 0.0293,
}

# Delimiters commonly used in compilation / merged titles
TITLE_SPLIT_DELIMITERS = ["/", "|", " - ", "&", " + ", " そして", " ＆", ":"]

# Canonical mapping from Amazon / SERIE ID universes and IPs to Broadkast project names
CANONICAL_BROADKAST_PROJECTS: Dict[str, str] = {
    "CARCITY": "CARCITY",
    "CARCITY2": "CARCITY",
    "CARL": "CARCITY",
    "CC2CARL": "CARCITY",
    "CC2TOM": "CARCITY",
    "TOM": "CARCITY",
    "TCW": "CARCITY",
    "TPS": "CARCITY",
    "TROY": "CARCITY",
    "TROY1": "CARCITY",
    "TROY2": "CARCITY",
    "CP": "CARCITY",
    "MT": "CARCITY",
    "LUCAS": "CARCITY",
    "TENTPOLE": "CARCITY",
    "XMAS": "CARCITY",
    "MILLIMAGES": "MILLIMAGES",
    "MOLANG": "MILLIMAGES",
    "DIDOU": "MILLIMAGES",
    "64": "MILLIMAGES",
    "ANIMACARS": "ANIMACARS",
    "AC": "ANIMACARS",
    "ACACL": "ANIMACARS",
    "ACDSC": "ANIMACARS",
    "SHK": "SHARK_ACADEMY",
    "SHKNA": "SHARK_ACADEMY",
    "SHKNR": "SHARK_ACADEMY",
    "SHARKS": "SHARK_ACADEMY",
    "SHARK ACADEMY": "SHARK_ACADEMY",
    "TINYWORLD": "TINY_WORLD",
    "TT": "TINY_WORLD",
    "TINY": "TINY_WORLD",
    "D&Z": "D_AND_Z",
    "LEARNTV": "LEARN_TV",
    "INC": "INCREDITALES",
    "INCSKT": "INCREDITALES",
    "SPSH": "SUPERS",
    "SUPERS": "SUPERS",
    "AL": "ALLADIN",
    "ALADDIN": "ALLADIN",
}


from core.normalization.title import normalize_title


def parse_period_month(date_str: str | None) -> Optional[str]:
    """Parses various date formats from Amazon reports into a 'YYYY-MM' string.

    Supports:
        - ISO format: 'YYYY-MM-DD' or 'YYYY-MM'
        - US format: 'MM/DD/YYYY' or 'M/D/YYYY'
        - European format: 'DD/MM/YYYY' (disambiguated when day > 12)
        - Textual dates: 'Aug-16-2017', 'Jun-28-2025'
    """
    if not date_str:
        return None
    cleaned = str(date_str).strip().split(" ")[0]
    if not cleaned:
        return None

    # Fast path if already YYYY-MM
    if re.fullmatch(r"^\d{4}-\d{2}$", cleaned):
        return cleaned

    # Handle slash-separated dates with ambiguity resolution (Amazon batch reports start on 01/MM/YYYY)
    if "/" in cleaned:
        parts = cleaned.split("/")
        if len(parts) == 3:
            try:
                p1, p2, p3 = int(parts[0]), int(parts[1]), int(parts[2])
                if len(parts[2]) == 4:
                    if p1 > 12:
                        return f"{p3:04d}-{p2:02d}"
                    elif p2 > 12:
                        return f"{p3:04d}-{p1:02d}"
                    else:
                        # Batch reports format start of period as 01/MM/YYYY (DD/MM/YYYY)
                        return f"{p3:04d}-{p2:02d}"
                elif len(parts[0]) == 4:
                    return f"{p1:04d}-{p2:02d}"
            except (ValueError, IndexError):
                pass

    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%b-%d-%Y",
        "%B-%d-%Y",
        "%Y-%m",
    ):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m")
        except ValueError:
            continue

    return None


def convert_currency_to_usd(amount: float, currency_code: str | None) -> float:
    """Converts a monetary amount to USD using standard rates."""
    if not currency_code:
        curr = "USD"
    else:
        curr = currency_code.strip().upper()
    if curr not in FX_RATES:
        log.warning(f"Uncataloged currency code '{curr}' encountered. Defaulting FX rate to 1.0 (USD parity).")
        rate = 1.0
    else:
        rate = FX_RATES[curr]
    return amount * rate


def convert_currency_to_eur(amount: float, currency_code: str | None) -> float:
    """Legacy helper: converts a monetary amount to EUR using 0.92 USD/EUR parity."""
    curr = (currency_code or "USD").strip().upper()
    if curr == "EUR":
        return amount
    return convert_currency_to_usd(amount, currency_code) * 0.92


def parse_numeric_float(raw_value: Any, default: float = 0.0) -> float:
    """Parses a numeric float string safely, stripping US/Amazon thousands commas."""
    if raw_value is None:
        return default
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    cleaned = str(raw_value).strip().replace(",", "")
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def parse_numeric_int(raw_value: Any, default: int = 0) -> int:
    """Parses a numeric integer string safely, stripping thousands commas."""
    if raw_value is None:
        return default
    if isinstance(raw_value, (int, float)):
        return int(raw_value)
    cleaned = str(raw_value).strip().replace(",", "")
    if not cleaned:
        return default
    try:
        return int(float(cleaned))
    except ValueError:
        return default


def load_mapping_cache(mappings_csv_path: Path) -> Dict[str, Any]:
    """Loads production_mappings.csv into multi-level index caches for matching."""
    exact_pair_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    exact_title_map: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    norm_pair_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    norm_title_map: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    trunc_title_map: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    if not mappings_csv_path.exists():
        log.warning("Mappings file not found: %s", mappings_csv_path)
        return {
            "exact_pair": exact_pair_map,
            "exact": exact_title_map,
            "norm_pair": norm_pair_map,
            "norm": norm_title_map,
            "trunc": trunc_title_map,
        }

    with mappings_csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            orig = (row.get("Amazon Original Title") or "").strip()
            amz_s = (row.get("Amazon Series") or "").strip()
            if not orig:
                continue

            exact_pair_map[(amz_s, orig)] = row
            exact_title_map[orig].append(row)

            norm_key = normalize_title(orig)
            norm_pair_map[(amz_s, norm_key)] = row
            norm_title_map[norm_key].append(row)

            trunc = (row.get("Truncated/Normalized Target") or "").strip()
            if trunc:
                trunc_norm = normalize_title(trunc)
                trunc_title_map[trunc_norm].append(row)

    return {
        "exact_pair": exact_pair_map,
        "exact": exact_title_map,
        "norm_pair": norm_pair_map,
        "norm": norm_title_map,
        "trunc": trunc_title_map,
    }


def _pick_franchise_compliant_candidate(
    candidates: List[Dict[str, str]], fallback_series: str
) -> Optional[Dict[str, str]]:
    """Picks candidate that strictly matches the franchise of fallback_series, preventing cross-franchise leaks."""
    if not candidates:
        return None
    amz_proj = resolve_franchise_project(fallback_series)
    if not amz_proj:
        return candidates[0]

    for cand in candidates:
        cand_proj = cand.get("Broadkast Project Name")
        if not cand_proj or cand_proj == "UNMATCHED":
            continue
        if amz_proj in ("CARCITY", "CARCITY_SUPER") and cand_proj in ("CARCITY", "CARCITY_SUPER"):
            return cand
        if cand_proj == amz_proj:
            return cand

    return None


def _resolve_via_reference_catalog(
    sku: Optional[str],
    fallback_series: str,
    fallback_season: str,
    clean_title: str,
) -> Optional[Dict[str, str]]:
    """Tries resolving metadata from the deterministic Amazon Reference Catalog."""
    try:
        from core.domain.amazon_catalog import AmazonReferenceCatalog

        cat = AmazonReferenceCatalog.get_instance()
        if not cat.is_loaded:
            return None

        res = cat.resolve(
            amazon_id=sku,
            season_id=fallback_season if fallback_season != "UNMATCHED" else None,
            series_name=fallback_series if fallback_series != "UNMATCHED" else None,
            title_name=clean_title,
        )
        if not res:
            return None

        raw_univ = (res.get("universe") or res.get("global_universe") or "").strip().upper()
        raw_ip = (res.get("ip") or "").strip().upper()

        proj_name = CANONICAL_BROADKAST_PROJECTS.get(raw_univ) or CANONICAL_BROADKAST_PROJECTS.get(raw_ip)
        if not proj_name:
            proj_name = raw_univ if raw_univ else "UNMATCHED"

        serie_name = res.get("canonical_series") or res.get("global_ip") or fallback_series or "UNMATCHED"
        ep_name = res.get("title_name") or clean_title

        return {
            "id": f"REF_{sku}" if sku else "CATALOG_MATCH",
            "id_episode": "CATALOG_MATCH",
            "id_project": "N/A",
            "id_serie": "N/A",
            "id_season": "N/A",
            "project_name_broadkast": proj_name,
            "serie_name_broadkast": serie_name,
            "serie_name_amazon": fallback_series or "UNMATCHED",
            "season_name_amazon": fallback_season or "UNMATCHED",
            "episode_name_broadkast": ep_name,
            "episode_name_amazon": clean_title,
            "no_dialog": "N/A",
            "performance_score": "100.0",
            "youtube_url": "",
            "status": "CATALOG_MATCH",
        }
    except Exception as e:
        log.debug("Reference catalog resolution exception: %s", e)
        return None


def resolve_title_mapping(
    title: str,
    mapping_cache: Dict[str, Any],
    fallback_series: str = "UNMATCHED",
    fallback_season: str = "UNMATCHED",
    sku: Optional[str] = None,
) -> Dict[str, str]:
    """Resolves an Amazon title to Broadkast metadata using exact pair, normalized,
    compliant truncated matching, or deterministic AmazonReferenceCatalog fallback."""
    clean_title = (title or "").strip()
    if not clean_title:
        return _build_unmatched_record("", fallback_series, fallback_season)

    # 1. Tier 1: Gold Standard production_mappings.csv Exact (Series, Title) match
    exact_pair = mapping_cache.get("exact_pair", {})
    if (fallback_series, clean_title) in exact_pair:
        return _format_matched_record(clean_title, exact_pair[(fallback_series, clean_title)])

    # 2. Tier 1: Exact Title match with franchise validation
    exact_map = mapping_cache.get("exact", {})
    if clean_title in exact_map:
        cand_list = exact_map[clean_title]
        cand = _pick_franchise_compliant_candidate(cand_list, fallback_series) if isinstance(cand_list, list) else cand_list
        if cand:
            return _format_matched_record(clean_title, cand)

    # 3. Tier 1: Normalized (Series, NormTitle) match
    norm_key = normalize_title(clean_title)
    norm_pair = mapping_cache.get("norm_pair", {})
    if (fallback_series, norm_key) in norm_pair:
        return _format_matched_record(clean_title, norm_pair[(fallback_series, norm_key)])

    # 4. Tier 1: Normalized Title match with franchise validation
    norm_map = mapping_cache.get("norm", {})
    if norm_key in norm_map:
        cand_list = norm_map[norm_key]
        cand = _pick_franchise_compliant_candidate(cand_list, fallback_series) if isinstance(cand_list, list) else cand_list
        if cand:
            return _format_matched_record(clean_title, cand)

    # 5. Tier 1: Truncated match with franchise validation
    trunc_map = mapping_cache.get("trunc", {})
    trunc_title = clean_title
    for marker in TITLE_SPLIT_DELIMITERS:
        if marker in trunc_title:
            trunc_title = trunc_title.split(marker, 1)[0].strip()
            break

    trunc_norm = normalize_title(trunc_title)
    if trunc_norm in trunc_map:
        cand_list = trunc_map[trunc_norm]
        cand = _pick_franchise_compliant_candidate(cand_list, fallback_series) if isinstance(cand_list, list) else cand_list
        if cand:
            return _format_matched_record(clean_title, cand)

    # 6. Tier 2: Deterministic AmazonReferenceCatalog Fallback
    catalog_res = _resolve_via_reference_catalog(
        sku=sku,
        fallback_series=fallback_series,
        fallback_season=fallback_season,
        clean_title=clean_title,
    )
    if catalog_res:
        return catalog_res

    # 7. Fallback unmatched
    return _build_unmatched_record(clean_title, fallback_series, fallback_season)


def _format_matched_record(
    orig_title: str, mapping_row: Dict[str, str]
) -> Dict[str, str]:
    bk_id = mapping_row.get("Broadkast ID", "UNMATCHED")
    bk_ep_num = mapping_row.get("Broadkast Episode Number", "N/A")
    id_episode = "N/A"
    if bk_ep_num and bk_ep_num != "N/A":
        id_episode = bk_ep_num if bk_ep_num == "UNMATCHED" else f"EP_{bk_ep_num}"

    yt_id = mapping_row.get("YouTube ID", "N/A")
    yt_url = (
        f"https://youtube.com/watch?v={yt_id}"
        if yt_id and yt_id not in ("N/A", "UNMATCHED")
        else ""
    )

    return {
        "id": bk_id if bk_id != "N/A" else "UNMATCHED",
        "id_episode": id_episode,
        "id_project": mapping_row.get("Broadkast Project ID", "N/A"),
        "id_serie": mapping_row.get("Broadkast Series ID", "N/A"),
        "id_season": mapping_row.get("Broadkast Season ID", "N/A"),
        "project_name_broadkast": mapping_row.get(
            "Broadkast Project Name", "N/A"
        ),
        "serie_name_broadkast": mapping_row.get("Broadkast Series", "N/A"),
        "serie_name_amazon": mapping_row.get("Amazon Series", "N/A"),
        "season_name_amazon": mapping_row.get("Amazon Season", "N/A"),
        "episode_name_broadkast": mapping_row.get(
            "Broadkast Assigned Title", orig_title
        ),
        "episode_name_amazon": orig_title,
        "no_dialog": mapping_row.get("No Dialog", "N/A"),
        "performance_score": mapping_row.get("Performance Score", "N/A"),
        "youtube_url": yt_url,
        "status": mapping_row.get("Match Status", "MATCH"),
    }


def _build_unmatched_record(
    orig_title: str, series_name: str, season_name: str
) -> Dict[str, str]:
    return {
        "id": "UNMATCHED",
        "id_episode": "UNMATCHED",
        "id_project": "UNMATCHED",
        "id_serie": "UNMATCHED",
        "id_season": "UNMATCHED",
        "project_name_broadkast": "UNMATCHED",
        "serie_name_broadkast": "UNMATCHED",
        "serie_name_amazon": series_name or "UNMATCHED",
        "season_name_amazon": season_name or "UNMATCHED",
        "episode_name_broadkast": orig_title or "Unknown Title",
        "episode_name_amazon": orig_title or "Unknown Title",
        "no_dialog": "N/A",
        "performance_score": "N/A",
        "youtube_url": "",
        "status": "UNMATCHED",
    }


class HistoricalAmazonParser:
    """Parser and aggregator for Amazon Historical Revenue Reports."""

    def __init__(
        self,
        amazon_data_dir: Path | str,
        mappings_file: Path | str,
        output_reports_dir: Path | str,
    ) -> None:
        self.amazon_data_dir = Path(amazon_data_dir)
        self.mappings_file = Path(mappings_file)
        self.output_reports_dir = Path(output_reports_dir)
        self.output_reports_dir.mkdir(parents=True, exist_ok=True)
        self.mapping_cache = load_mapping_cache(self.mappings_file)

        from core.ingestion.amazon_streaming import AmazonStreamingParser
        self.streaming_parser = AmazonStreamingParser(
            streaming_dir=self.amazon_data_dir / "streaming_reports",
            mapping_cache=self.mapping_cache,
        )

    def process_all_historical_files(
        self,
        target_months: Optional[Set[str]] = None,
        overwrite: bool = False,
    ) -> Dict[str, int]:
        """Processes all streaming reports, batches, monthly reports, and detailed TVOD/SVOD files.

        Returns a dictionary mapping month ('YYYY-MM') to the number of records produced.
        """
        # monthly_data[month][key] -> [views, minutes_streamed, revenue_usd]
        monthly_data: Dict[str, Dict[Tuple, List[float]]] = defaultdict(
            lambda: defaultdict(lambda: [0, 0.0, 0.0])
        )

        # 0. Process Streaming Reports (2016-09 to 2026-09)
        streaming_months_processed: Set[str] = set()
        for month, s_path in self.streaming_parser.get_available_months():
            if target_months and month not in target_months:
                continue
            log.info("Processing Streaming Report: %s (%s)", s_path.name, month)
            cnt = self.streaming_parser.process_file(s_path, monthly_data, target_month=month)
            if cnt > 0:
                streaming_months_processed.add(month)

        # 1. Process Batches (2017 - 2019)
        batches_dir = self.amazon_data_dir / "historical_revenue" / "batches"
        if batches_dir.exists():
            for batch_file in sorted(batches_dir.glob("*.csv")):
                log.info("Processing Batch: %s", batch_file.name)
                self._process_csv_revenue_file(
                    batch_file,
                    monthly_data,
                    target_months,
                    streaming_months_processed=streaming_months_processed,
                )

        # 2. Process Monthly Reports (2020 - 2025)
        monthly_dir = (
            self.amazon_data_dir / "historical_revenue" / "monthly_reports"
        )
        monthly_reports_processed: Set[str] = set()
        if monthly_dir.exists():
            for report_file in sorted(monthly_dir.rglob("*.csv")):
                log.info("Processing Monthly Report: %s", report_file.name)
                processed = self._process_csv_revenue_file(
                    report_file,
                    monthly_data,
                    target_months,
                    streaming_months_processed=streaming_months_processed,
                )
                if processed:
                    monthly_reports_processed.update(processed)

            # Process Excel TVOD reports if present
            for xlsx_file in sorted(monthly_dir.rglob("*.xlsx")):
                log.info("Processing Excel TVOD Report: %s", xlsx_file.name)
                self._process_xlsx_tvod_file(xlsx_file, monthly_data, target_months)

        # 3. Process Modern Detailed Earnings (SVOD & TVOD 2024-2026)
        earnings_dirs = [
            self.amazon_data_dir / "earnings",
            self.amazon_data_dir / "detailed_earnings",
        ]
        svod_processed_months: Set[str] = set()
        for e_dir in earnings_dirs:
            if not e_dir.exists():
                continue
            for svod_file in sorted(e_dir.glob("*SVOD*.csv")):
                log.info("Processing Modern SVOD Earnings: %s", svod_file.name)
                svod_m = self._process_detailed_svod_csv(
                    svod_file,
                    monthly_data,
                    target_months=target_months,
                    streaming_months_processed=streaming_months_processed,
                    skip_months=monthly_reports_processed | svod_processed_months,
                )
                svod_processed_months.update(svod_m)

        tvod_processed_months: Set[str] = set()
        for e_dir in earnings_dirs:
            if not e_dir.exists():
                continue
            for tvod_file in sorted(e_dir.glob("*TVOD*.csv")):
                log.info("Processing Modern TVOD Earnings: %s", tvod_file.name)
                tvod_m = self._process_detailed_tvod_csv(
                    tvod_file,
                    monthly_data,
                    target_months=target_months,
                    skip_months=monthly_reports_processed | tvod_processed_months,
                )
                tvod_processed_months.update(tvod_m)

        # 4. Export consolidated reports per month
        exported_counts = self._export_monthly_reports(monthly_data, overwrite=overwrite)
        return exported_counts

    def _process_csv_revenue_file(
        self,
        csv_path: Path,
        monthly_data: Dict[str, Dict[Tuple, List[float]]],
        target_months: Optional[Set[str]] = None,
        streaming_months_processed: Optional[Set[str]] = None,
    ) -> Set[str]:
        """Parses a 22-column Amazon Revenue Report CSV (Batches & Monthly)."""
        months_found: Set[str] = set()
        with csv_path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                period_str = row.get("Period Start")
                month = parse_period_month(period_str)
                if not month:
                    continue
                if target_months and month not in target_months:
                    continue

                title = (row.get("Title Name") or "").strip()
                if not title:
                    continue

                months_found.add(month)
                series = (row.get("Series Name") or "").strip()
                season = (row.get("Season Name") or "").strip()
                territory = (
                    (row.get("Territory") or row.get("Region") or "Unknown Geo")
                    .strip()
                    .upper()
                )

                consumption_type = (row.get("Consumption Type") or "Prime").strip()
                if consumption_type.lower() in ("prime", "svod"):
                    offer_type = "PRIME"
                elif consumption_type.lower() in ("purchase", "tvod"):
                    offer_type = "PURCHASE"
                elif consumption_type.lower() == "avod":
                    offer_type = "AVOD"
                else:
                    offer_type = consumption_type.upper()

                # Streamed minutes
                duration_hours = parse_numeric_float(row.get("Duration Streamed"), 0.0)
                minutes = duration_hours * 60.0

                # Views / Transactions
                raw_qty = (row.get("Quantity") or "").strip()
                raw_ad_imp = (row.get("Paid Ad Impressions") or "").strip()
                if raw_qty:
                    views = parse_numeric_int(raw_qty, 0)
                elif raw_ad_imp:
                    views = parse_numeric_int(raw_ad_imp, 0)
                else:
                    views = 0

                # Royalties in USD
                royalty_amount = parse_numeric_float(row.get("Royalty Amount"), 0.0)

                currency = (row.get("Royalty Currency") or "USD").strip()
                revenue_usd = convert_currency_to_usd(royalty_amount, currency)

                # Match metadata
                sku = (row.get("Title/Season ID") or row.get("Title/Season ID (SKU)") or row.get("ASIN") or "").strip()
                mapping = resolve_title_mapping(
                    title, self.mapping_cache, series, season, sku=sku
                )

                key = (
                    mapping["id"],
                    mapping["id_episode"],
                    mapping["id_project"],
                    mapping["id_serie"],
                    mapping["id_season"],
                    mapping["project_name_broadkast"],
                    mapping["serie_name_broadkast"],
                    series or mapping["serie_name_amazon"],
                    season or mapping["season_name_amazon"],
                    mapping["episode_name_broadkast"],
                    title,
                    mapping["no_dialog"],
                    mapping["performance_score"],
                    mapping["youtube_url"],
                    offer_type,
                    "Amazon",
                    territory,
                )

                entry = monthly_data[month][key]
                if streaming_months_processed and month in streaming_months_processed:
                    entry[2] += revenue_usd
                else:
                    entry[0] += views
                    entry[1] += minutes
                    entry[2] += revenue_usd

        return months_found

    def _process_xlsx_tvod_file(
        self,
        xlsx_path: Path,
        monthly_data: Dict[str, Dict[Tuple, List[float]]],
        target_months: Optional[Set[str]] = None,
    ) -> None:
        """Parses an Excel TVOD Detailed Earnings report."""
        try:
            import openpyxl
        except ImportError:
            log.error("openpyxl is required to parse Excel TVOD files.")
            return

        wb = openpyxl.load_workbook(str(xlsx_path), read_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if not header_row:
            return

        headers = [str(h).strip() if h else "" for h in header_row]
        header_idx = {h: i for i, h in enumerate(headers) if h}

        stmt_idx = header_idx.get("Statement period")
        title_idx = header_idx.get("Title name")
        series_idx = header_idx.get("Series title")
        season_idx = header_idx.get("Season title")
        terr_idx = header_idx.get("Territory")
        tx_count_idx = header_idx.get("Transaction count")
        fee_idx = header_idx.get("License fee")
        fee_curr_idx = header_idx.get("License fee currency")
        asin_idx = header_idx.get("ASIN ID") or header_idx.get("Vendor SKU") or header_idx.get("Amazon ID") or header_idx.get("Title/Season ID")

        for r in rows_iter:
            if not r:
                continue
            period_val = r[stmt_idx] if stmt_idx is not None and stmt_idx < len(r) else None
            month = parse_period_month(period_val)
            if not month:
                continue
            if target_months and month not in target_months:
                continue

            title_val = r[title_idx] if title_idx is not None and title_idx < len(r) else None
            title = str(title_val).strip() if title_val else ""
            if not title:
                continue

            series = (
                str(r[series_idx]).strip()
                if series_idx is not None and series_idx < len(r) and r[series_idx]
                else "UNMATCHED"
            )
            season = (
                str(r[season_idx]).strip()
                if season_idx is not None and season_idx < len(r) and r[season_idx]
                else "UNMATCHED"
            )
            territory = (
                str(r[terr_idx]).strip().upper()
                if terr_idx is not None and terr_idx < len(r) and r[terr_idx]
                else "UNKNOWN GEO"
            )

            views = (
                parse_numeric_int(r[tx_count_idx], 0)
                if tx_count_idx is not None and tx_count_idx < len(r)
                else 0
            )
            fee_amount = (
                parse_numeric_float(r[fee_idx], 0.0)
                if fee_idx is not None and fee_idx < len(r)
                else 0.0
            )

            curr = (
                str(r[fee_curr_idx]).strip()
                if fee_curr_idx is not None and fee_curr_idx < len(r) and r[fee_curr_idx]
                else "JPY"
            )
            revenue_usd = convert_currency_to_usd(fee_amount, curr)

            sku = str(r[asin_idx]).strip() if asin_idx is not None and asin_idx < len(r) and r[asin_idx] else None
            mapping = resolve_title_mapping(title, self.mapping_cache, series, season, sku=sku)

            key = (
                mapping["id"],
                mapping["id_episode"],
                mapping["id_project"],
                mapping["id_serie"],
                mapping["id_season"],
                mapping["project_name_broadkast"],
                mapping["serie_name_broadkast"],
                series or mapping["serie_name_amazon"],
                season or mapping["season_name_amazon"],
                mapping["episode_name_broadkast"],
                title,
                mapping["no_dialog"],
                mapping["performance_score"],
                mapping["youtube_url"],
                "PURCHASE",
                "Amazon",
                territory,
            )

            entry = monthly_data[month][key]
            entry[0] += views
            entry[1] += 0.0  # TVOD purchase
            entry[2] += revenue_usd

    def _process_detailed_svod_csv(
        self,
        csv_path: Path,
        monthly_data: Dict[str, Dict[Tuple, List[float]]],
        target_months: Optional[Set[str]] = None,
        streaming_months_processed: Optional[Set[str]] = None,
        skip_months: Optional[Set[str]] = None,
    ) -> Set[str]:
        """Parses a Detailed SVOD Earnings report (e.g. SVOD_2024_09_2026_09.csv)."""
        months_found: Set[str] = set()
        with csv_path.open("r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stmt = row.get("Statement period")
                month = parse_period_month(stmt)
                if not month:
                    continue
                if target_months and month not in target_months:
                    continue
                if skip_months and month in skip_months:
                    continue

                title = (row.get("Title name") or "").strip()
                if not title:
                    continue

                months_found.add(month)
                series = (row.get("Series title") or "").strip()
                season = (row.get("Season title") or "").strip()
                territory = (row.get("Territory") or "Unknown Geo").strip().upper()

                duration_hours = parse_numeric_float(row.get("Duration streamed hours"), 0.0)
                minutes = duration_hours * 60.0

                royalty = parse_numeric_float(row.get("Total accrued royalty"), 0.0)
                curr = (row.get("Royalty currency") or "USD").strip().upper()
                revenue_usd = convert_currency_to_usd(royalty, curr)

                sku = (row.get("ASIN") or row.get("Vendor SKU") or row.get("Season/movie SKU") or "").strip()
                mapping = resolve_title_mapping(title, self.mapping_cache, series, season, sku=sku)

                key = (
                    mapping["id"],
                    mapping["id_episode"],
                    mapping["id_project"],
                    mapping["id_serie"],
                    mapping["id_season"],
                    mapping["project_name_broadkast"],
                    mapping["serie_name_broadkast"],
                    series or mapping["serie_name_amazon"],
                    season or mapping["season_name_amazon"],
                    mapping["episode_name_broadkast"],
                    title,
                    mapping["no_dialog"],
                    mapping["performance_score"],
                    mapping["youtube_url"],
                    "PRIME",
                    "Amazon",
                    territory,
                )

                entry = monthly_data[month][key]
                if not streaming_months_processed or month not in streaming_months_processed:
                    entry[1] += minutes
                entry[2] += revenue_usd

        return months_found

    def _process_detailed_tvod_csv(
        self,
        csv_path: Path,
        monthly_data: Dict[str, Dict[Tuple, List[float]]],
        target_months: Optional[Set[str]] = None,
        skip_months: Optional[Set[str]] = None,
    ) -> Set[str]:
        """Parses a Detailed TVOD Earnings report (e.g. TVOD_2025_01_2026_10.csv)."""
        months_found: Set[str] = set()
        with csv_path.open("r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stmt = row.get("Statement period")
                month = parse_period_month(stmt)
                if not month:
                    continue
                if target_months and month not in target_months:
                    continue
                if skip_months and month in skip_months:
                    continue

                title = (row.get("Title name") or "").strip()
                if not title:
                    continue

                months_found.add(month)
                series = (row.get("Series title") or "").strip()
                season = (row.get("Season title") or "").strip()
                territory = (row.get("Territory") or "Unknown Geo").strip().upper()

                views = parse_numeric_int(row.get("Transaction count"), 0)
                fee_val = row.get("License fee") or row.get("Gross license fee")
                fee_amount = parse_numeric_float(fee_val, 0.0)

                curr = (row.get("License fee currency") or "USD").strip().upper()
                revenue_usd = convert_currency_to_usd(fee_amount, curr)

                sku = (row.get("ASIN ID") or row.get("Amazon ID") or row.get("Vendor SKU") or row.get("Title/Season ID") or "").strip()
                mapping = resolve_title_mapping(title, self.mapping_cache, series, season, sku=sku)

                key = (
                    mapping["id"],
                    mapping["id_episode"],
                    mapping["id_project"],
                    mapping["id_serie"],
                    mapping["id_season"],
                    mapping["project_name_broadkast"],
                    mapping["serie_name_broadkast"],
                    series or mapping["serie_name_amazon"],
                    season or mapping["season_name_amazon"],
                    mapping["episode_name_broadkast"],
                    title,
                    mapping["no_dialog"],
                    mapping["performance_score"],
                    mapping["youtube_url"],
                    "PURCHASE",
                    "Amazon",
                    territory,
                )

                entry = monthly_data[month][key]
                entry[0] += views
                entry[1] += 0.0
                entry[2] += revenue_usd

        return months_found

    def _export_monthly_reports(
        self,
        monthly_data: Dict[str, Dict[Tuple, List[float]]],
        overwrite: bool = False,
    ) -> Dict[str, int]:
        """Writes consolidated monthly analytics CSV reports."""
        fieldnames = [
            "id",
            "id_episode",
            "id_project",
            "id_serie",
            "id_season",
            "project_name_broadkast",
            "serie_name_broadkast",
            "serie_name_amazon",
            "season_name_amazon",
            "episode_name_broadkast",
            "episode_name_amazon",
            "no_dialog",
            "performance_score",
            "youtube_url",
            "offer_type",
            "platform",
            "region",
            "views",
            "minutes_streamed",
            "avg_view_minutes",
            "revenue",
            "revenue_svod",
            "revenue_tvod",
            "cph_rate",
            "currency",
        ]

        result_counts: Dict[str, int] = {}

        for month in sorted(monthly_data.keys()):
            items = monthly_data[month]
            if not items:
                continue

            year_str, month_str = month.split("-")
            out_file = (
                self.output_reports_dir
                / f"analytics_reports_{month_str}_{year_str}.csv"
            )

            # If the file already exists and overwrite is False:
            if out_file.exists() and not overwrite:
                log.info(
                    "Skipping existing analytics report: %s (use overwrite=True to replace)",
                    out_file.name,
                )
                continue

            # Global aggregation accumulator
            # global_key: (id, id_episode, ..., offer_type, platform) -> [views, minutes, revenue, svod, tvod]
            global_acc: Dict[Tuple, List[float]] = defaultdict(
                lambda: [0, 0.0, 0.0, 0.0, 0.0]
            )

            rows_to_write: List[Dict[str, Any]] = []

            for key, (views, minutes, revenue_usd) in items.items():
                (
                    b_id,
                    b_ep_id,
                    b_proj_id,
                    b_ser_id,
                    b_seas_id,
                    b_proj_name,
                    b_ser_name,
                    amz_series,
                    amz_season,
                    b_ep_title,
                    amz_title,
                    no_dialog,
                    perf_score,
                    yt_url,
                    offer_type,
                    platform,
                    territory,
                ) = key

                hours = minutes / 60.0
                cph = (revenue_usd / hours) if hours > 0 else 0.0
                avg_view = (minutes / views) if views > 0 else 0.0

                svod_usd = revenue_usd if offer_type == "PRIME" else 0.0
                tvod_usd = revenue_usd if offer_type == "PURCHASE" else 0.0

                rows_to_write.append(
                    {
                        "id": b_id,
                        "id_episode": b_ep_id,
                        "id_project": b_proj_id,
                        "id_serie": b_ser_id,
                        "id_season": b_seas_id,
                        "project_name_broadkast": b_proj_name,
                        "serie_name_broadkast": b_ser_name,
                        "serie_name_amazon": amz_series,
                        "season_name_amazon": amz_season,
                        "episode_name_broadkast": b_ep_title,
                        "episode_name_amazon": amz_title,
                        "no_dialog": no_dialog,
                        "performance_score": perf_score,
                        "youtube_url": yt_url,
                        "offer_type": offer_type,
                        "platform": platform,
                        "region": territory,
                        "views": int(views),
                        "minutes_streamed": f"{minutes:.2f}",
                        "avg_view_minutes": f"{avg_view:.2f}",
                        "revenue": f"{revenue_usd:.4f}",
                        "revenue_svod": f"{svod_usd:.4f}",
                        "revenue_tvod": f"{tvod_usd:.4f}",
                        "cph_rate": f"{cph:.4f}",
                        "currency": "USD",
                    }
                )

                # Accumulate for Global row
                g_key = (
                    b_id,
                    b_ep_id,
                    b_proj_id,
                    b_ser_id,
                    b_seas_id,
                    b_proj_name,
                    b_ser_name,
                    b_ep_title,
                    amz_title,
                    no_dialog,
                    perf_score,
                    yt_url,
                    offer_type,
                    platform,
                )
                g_entry = global_acc[g_key]
                g_entry[0] += views
                g_entry[1] += minutes
                g_entry[2] += revenue_usd
                g_entry[3] += svod_usd
                g_entry[4] += tvod_usd

            # Append Global summary rows
            for g_key, (g_views, g_minutes, g_rev, g_svod, g_tvod) in global_acc.items():
                (
                    b_id,
                    b_ep_id,
                    b_proj_id,
                    b_ser_id,
                    b_seas_id,
                    b_proj_name,
                    b_ser_name,
                    b_ep_title,
                    amz_title,
                    no_dialog,
                    perf_score,
                    yt_url,
                    offer_type,
                    platform,
                ) = g_key

                g_hours = g_minutes / 60.0
                g_cph = (g_rev / g_hours) if g_hours > 0 else 0.0
                g_avg_view = (g_minutes / g_views) if g_views > 0 else 0.0

                rows_to_write.append(
                    {
                        "id": b_id,
                        "id_episode": b_ep_id,
                        "id_project": b_proj_id,
                        "id_serie": b_ser_id,
                        "id_season": b_seas_id,
                        "project_name_broadkast": b_proj_name,
                        "serie_name_broadkast": b_ser_name,
                        "serie_name_amazon": "Múltiple (Global)",
                        "season_name_amazon": "Múltiple (Global)",
                        "episode_name_broadkast": f"{b_ep_title} (Global)",
                        "episode_name_amazon": "Múltiple (Global)",
                        "no_dialog": no_dialog,
                        "performance_score": perf_score,
                        "youtube_url": yt_url,
                        "offer_type": offer_type,
                        "platform": platform,
                        "region": "Global",
                        "views": int(g_views),
                        "minutes_streamed": f"{g_minutes:.2f}",
                        "avg_view_minutes": f"{g_avg_view:.2f}",
                        "revenue": f"{g_rev:.4f}",
                        "revenue_svod": f"{g_svod:.4f}",
                        "revenue_tvod": f"{g_tvod:.4f}",
                        "cph_rate": f"{g_cph:.4f}",
                        "currency": "USD",
                    }
                )

            with out_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows_to_write)

            result_counts[month] = len(rows_to_write)
            log.info("Saved %s (%d rows)", out_file.name, len(rows_to_write))

        return result_counts

