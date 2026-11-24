"""
scripts/build_amazon_reference_catalog.py

Extracts, normalizes, and compiles the master metadata from:
- data/amazon/metadata/SERIE ID.xlsx
- data/amazon/metadata/Amazon_SeriesMapping_v2.csv

Outputs canonical, fast-lookup JSON reference catalogs into data/reference/:
1. data/reference/amazon_id_catalog.json (Lookup by Title ID, Season ID, Series ID in O(1))
2. data/reference/amazon_series_catalog.json (Lookup by Localized Series Name in O(1))

Ensures 100% determinism, zero duplicate IDs, and zero null critical fields.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import openpyxl
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("build_amazon_catalog")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
METADATA_DIR = PROJECT_ROOT / "data" / "amazon" / "metadata"
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"

SERIE_ID_XLSX = METADATA_DIR / "SERIE ID.xlsx"
SERIES_MAPPING_CSV = METADATA_DIR / "Amazon_SeriesMapping_v2.csv"

OUT_ID_CATALOG = REFERENCE_DIR / "amazon_id_catalog.json"
OUT_SERIES_CATALOG = REFERENCE_DIR / "amazon_series_catalog.json"


def _clean_str(val: Any) -> Optional[str]:
    """Cleans string, stripping whitespace and non-breaking spaces."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().replace("\xa0", " ")
    return s if s else None


def _clean_int(val: Any) -> Optional[int]:
    """Parses integer safely."""
    if val is None or pd.isna(val):
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def build_catalogs() -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Builds ID catalog and Series Name catalog."""
    if not SERIE_ID_XLSX.exists():
        raise FileNotFoundError(f"Missing master metadata file: {SERIE_ID_XLSX}")
    if not SERIES_MAPPING_CSV.exists():
        raise FileNotFoundError(f"Missing series mapping file: {SERIES_MAPPING_CSV}")

    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Loading '%s'...", SERIE_ID_XLSX.name)
    wb = openpyxl.load_workbook(SERIE_ID_XLSX, read_only=True, data_only=True)

    id_catalog: Dict[str, Dict[str, Any]] = {}
    series_catalog: Dict[str, Dict[str, Any]] = {}

    # ----------------------------------------------------
    # 1. Process Sheet 'Title ID' (Master episodic & standalone catalog)
    # ----------------------------------------------------
    log.info("Processing sheet 'Title ID'...")
    ws_title = wb["Title ID"]
    title_rows = list(ws_title.iter_rows(values_only=True))
    if not title_rows:
        raise ValueError("Sheet 'Title ID' is empty!")

    header_title = [_clean_str(c) or f"col_{i}" for i, c in enumerate(title_rows[0])]
    col_idx_title = {name: i for i, name in enumerate(header_title)}

    title_count = 0
    for row in title_rows[1:]:
        title_id = _clean_str(row[col_idx_title.get("Title Id", 0)])
        if not title_id:
            continue

        title_name = _clean_str(row[col_idx_title.get("Title Name", 3)])
        season_id = _clean_str(row[col_idx_title.get("Season Id", 1)])
        series_id = _clean_str(row[col_idx_title.get("Series Id", 2)])
        series_name = _clean_str(row[col_idx_title.get("Series Name", 7)])
        ip = _clean_str(row[col_idx_title.get("IP", 4)])
        global_ip = _clean_str(row[col_idx_title.get("Global IP", 9)])
        universe = _clean_str(row[col_idx_title.get("Universe", 6)])
        global_universe = _clean_str(row[col_idx_title.get("Global Universe", 10)])
        lang_code = _clean_str(row[col_idx_title.get("Language Code", 5)])
        season_num = _clean_int(row[col_idx_title.get("Season Number", 8)])
        ep_num = _clean_int(row[col_idx_title.get("Episode Number", 11)])

        id_catalog[title_id] = {
            "id": title_id,
            "id_type": "title",
            "title_name": title_name,
            "season_id": season_id,
            "series_id": series_id,
            "series_name": series_name,
            "season_number": season_num,
            "episode_number": ep_num,
            "ip": ip,
            "global_ip": global_ip,
            "universe": universe,
            "global_universe": global_universe,
            "language_code": lang_code,
        }
        title_count += 1

    log.info("Loaded %d unique Title IDs.", title_count)

    # ----------------------------------------------------
    # 2. Process Sheet 'Season ID' (Season-level metadata)
    # ----------------------------------------------------
    log.info("Processing sheet 'Season ID'...")
    ws_season = wb["Season ID"]
    season_rows = list(ws_season.iter_rows(values_only=True))
    season_count = 0

    if season_rows:
        header_season = [_clean_str(c) or f"col_{i}" for i, c in enumerate(season_rows[0])]
        col_idx_season = {name: i for i, name in enumerate(header_season)}

        for row in season_rows[1:]:
            season_id = _clean_str(row[col_idx_season.get("Season Id", 0)])
            if not season_id:
                continue

            ip = _clean_str(row[col_idx_season.get("IP", 1)])
            lang_code = _clean_str(row[col_idx_season.get("LANGUAGE CODE", 2)])
            universe = _clean_str(row[col_idx_season.get("UNIVERS", 4)])
            season_num = _clean_int(row[col_idx_season.get("SEASON", 5)])

            # If season_id not in catalog or if catalog has title entry, add or complement season entry
            if season_id not in id_catalog:
                id_catalog[season_id] = {
                    "id": season_id,
                    "id_type": "season",
                    "title_name": None,
                    "season_id": season_id,
                    "series_id": None,
                    "series_name": None,
                    "season_number": season_num,
                    "episode_number": None,
                    "ip": ip,
                    "global_ip": None,
                    "universe": universe,
                    "global_universe": None,
                    "language_code": lang_code,
                }
                season_count += 1

    # Also register any Season Id from Title ID that wasn't registered yet
    for entry in list(id_catalog.values()):
        sid = entry.get("season_id")
        if sid and sid not in id_catalog:
            id_catalog[sid] = {
                "id": sid,
                "id_type": "season",
                "title_name": entry.get("title_name"),
                "season_id": sid,
                "series_id": entry.get("series_id"),
                "series_name": entry.get("series_name"),
                "season_number": entry.get("season_number"),
                "episode_number": None,
                "ip": entry.get("ip"),
                "global_ip": entry.get("global_ip"),
                "universe": entry.get("universe"),
                "global_universe": entry.get("global_universe"),
                "language_code": entry.get("language_code"),
            }
            season_count += 1

    log.info("Total Season IDs indexed in catalog: %d.", season_count)

    # ----------------------------------------------------
    # 3. Process Sheet 'Series ID' (Series-level metadata)
    # ----------------------------------------------------
    log.info("Processing sheet 'Series ID'...")
    ws_series = wb["Series ID"]
    series_rows = list(ws_series.iter_rows(values_only=True))
    series_count = 0

    if series_rows:
        header_series = [_clean_str(c) or f"col_{i}" for i, c in enumerate(series_rows[0])]
        col_idx_series = {name: i for i, name in enumerate(header_series)}

        for row in series_rows[1:]:
            series_id = _clean_str(row[col_idx_series.get("Series Id", 0)])
            if not series_id:
                continue

            s_name = _clean_str(row[col_idx_series.get("Series Name", 1)])
            ip = _clean_str(row[col_idx_series.get("IP", 2)])
            lang_code = _clean_str(row[col_idx_series.get("LANGUAGE CODE", 3)])
            universe = _clean_str(row[col_idx_series.get("UNIVERS", 5)])

            if series_id not in id_catalog:
                id_catalog[series_id] = {
                    "id": series_id,
                    "id_type": "series",
                    "title_name": None,
                    "season_id": None,
                    "series_id": series_id,
                    "series_name": s_name,
                    "season_number": None,
                    "episode_number": None,
                    "ip": ip,
                    "global_ip": None,
                    "universe": universe,
                    "global_universe": None,
                    "language_code": lang_code,
                }
                series_count += 1

    # Also register any Series Id from Title ID that wasn't registered yet
    for entry in list(id_catalog.values()):
        s_id = entry.get("series_id")
        if s_id and s_id not in id_catalog:
            id_catalog[s_id] = {
                "id": s_id,
                "id_type": "series",
                "title_name": None,
                "season_id": None,
                "series_id": s_id,
                "series_name": entry.get("series_name"),
                "season_number": None,
                "episode_number": None,
                "ip": entry.get("ip"),
                "global_ip": entry.get("global_ip"),
                "universe": entry.get("universe"),
                "global_universe": entry.get("global_universe"),
                "language_code": entry.get("language_code"),
            }
            series_count += 1

    log.info("Total Series IDs indexed in catalog: %d.", series_count)

    # ----------------------------------------------------
    # 4. Process Series Name Mappings (SERIE ID.xlsx & Amazon_SeriesMapping_v2.csv)
    # ----------------------------------------------------
    log.info("Processing Series Name mappings...")
    # First from 'Series Name' sheet in SERIE ID.xlsx
    ws_sname = wb["Series Name"]
    for row in list(ws_sname.iter_rows(values_only=True))[1:]:
        s_name = _clean_str(row[0])
        ip = _clean_str(row[1]) if len(row) > 1 else None
        if s_name and ip:
            series_catalog[s_name] = {
                "series_name": s_name,
                "canonical_series": s_name,
                "ip": ip,
                "global_ip": None,
                "universe": None,
                "global_universe": None,
            }

    # Second from Amazon_SeriesMapping_v2.csv (higher detail: IP, Global IP, Universe, Global Universe)
    log.info("Enriching with '%s'...", SERIES_MAPPING_CSV.name)
    df_v2 = pd.read_csv(SERIES_MAPPING_CSV)
    for _, r in df_v2.iterrows():
        s_name = _clean_str(r.get("Series Name"))
        if not s_name:
            continue
        canon_series = _clean_str(r.get("Series")) or s_name
        ip = _clean_str(r.get("IP"))
        global_ip = _clean_str(r.get("Global IP"))
        universe = _clean_str(r.get("Universe"))
        global_universe = _clean_str(r.get("Global Universe"))

        # Known single edge case in CSV: OUTrageous Series is part of ALADDIN
        if not ip and "outrageous" in s_name.lower():
            ip = "AL"
            global_ip = "Aladdin"
            universe = "ALADDIN"
            global_universe = "ALADDIN"

        existing = series_catalog.get(s_name, {})
        final_ip = ip or existing.get("ip")
        if not final_ip:
            log.warning("Skipping series '%s': No IP could be determined.", s_name)
            continue

        series_catalog[s_name] = {
            "series_name": s_name,
            "canonical_series": canon_series,
            "ip": final_ip,
            "global_ip": global_ip or existing.get("global_ip"),
            "universe": universe or existing.get("universe"),
            "global_universe": global_universe or existing.get("global_universe"),
        }

    log.info("Total unique localized series names indexed: %d.", len(series_catalog))
    wb.close()

    # ----------------------------------------------------
    # 5. Write Catalog Files
    # ----------------------------------------------------
    log.info("Writing '%s' (%d IDs)...", OUT_ID_CATALOG, len(id_catalog))
    with open(OUT_ID_CATALOG, "w", encoding="utf-8") as f:
        json.dump(id_catalog, f, ensure_ascii=False, indent=2)

    log.info("Writing '%s' (%d series)...", OUT_SERIES_CATALOG, len(series_catalog))
    with open(OUT_SERIES_CATALOG, "w", encoding="utf-8") as f:
        json.dump(series_catalog, f, ensure_ascii=False, indent=2)

    return id_catalog, series_catalog


def validate_catalogs(id_catalog: Dict[str, Any], series_catalog: Dict[str, Any]) -> None:
    """Runs automated integrity tests against the generated catalogs."""
    log.info("Validating catalog integrity...")

    # 1. Title IDs count
    title_entries = [v for v in id_catalog.values() if v.get("id_type") == "title"]
    assert len(title_entries) == 9967, f"Expected 9,967 Title IDs, got {len(title_entries)}"

    # 2. Critical fields in Title IDs
    for entry in title_entries:
        assert entry.get("id"), "Found entry with missing 'id'"
        assert entry.get("ip"), f"Found Title ID {entry['id']} with missing 'ip'"
        assert entry.get("universe"), f"Found Title ID {entry['id']} with missing 'universe'"
        assert entry.get("title_name"), f"Found Title ID {entry['id']} with missing 'title_name'"

    # 3. Series Catalog entries
    assert len(series_catalog) >= 555, f"Expected at least 555 series names, got {len(series_catalog)}"
    for s_name, data in series_catalog.items():
        assert data.get("ip"), f"Series '{s_name}' is missing 'ip'"

    # 4. Cross-check against real Amazon report (Revenue Report 2024-01)
    sample_report = PROJECT_ROOT / "data" / "amazon" / "historical_revenue" / "monthly_reports" / "KLQ49-2024-01-RevenueReport-8620f81e-fba1-40da-8a51-df97be707a80.csv"
    if sample_report.exists():
        df_rev = pd.read_csv(sample_report, low_memory=False)
        skus = set(df_rev["Title/Season ID"].dropna().astype(str).str.strip())
        matched = skus.intersection(set(id_catalog.keys()))
        match_rate = len(matched) / len(skus) * 100
        log.info("Cross-check KLQ49-2024-01: %d/%d SKUs matched (%.1f%%).", len(matched), len(skus), match_rate)
        assert match_rate == 100.0, f"Expected 100.0% match rate, got {match_rate:.1f}%"

    log.info("✅ All validation tests PASSED successfully!")


def main() -> None:
    try:
        id_catalog, series_catalog = build_catalogs()
        validate_catalogs(id_catalog, series_catalog)
        print("\n✨ Amazon Reference Catalogs generated and verified successfully!")
        print(f"   -> {OUT_ID_CATALOG.relative_to(PROJECT_ROOT)}: {len(id_catalog)} Amazon IDs")
        print(f"   -> {OUT_SERIES_CATALOG.relative_to(PROJECT_ROOT)}: {len(series_catalog)} Series Names")
    except Exception as e:
        log.error("Fatal error generating catalogs: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
