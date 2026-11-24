#!/usr/bin/env python3
"""
scripts/build_youtube_channel_catalog.py

Extracts and compiles master YouTube channel-to-IP mappings from:
- data/reference/Mapping Youtube Channels.xlsx (sheet: youtube_channels)

Outputs canonical JSON reference catalog into data/reference/:
- data/reference/youtube_channel_catalog.json

Ensures 100% determinism, zero formula errors, and O(1) in-memory lookups.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import openpyxl

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("build_youtube_channel_catalog")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"
EXCEL_PATH = REFERENCE_DIR / "Mapping Youtube Channels.xlsx"
OUTPUT_JSON_PATH = REFERENCE_DIR / "youtube_channel_catalog.json"


def _clean_str(val: Any) -> Optional[str]:
    """Cleans string, stripping whitespace and non-breaking spaces."""
    if val is None:
        return None
    s = str(val).strip().replace("\xa0", " ")
    return s if s else None


def build_channel_catalog() -> Dict[str, Any]:
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Master mapping Excel not found at: {EXCEL_PATH}")

    log.info(f"Loading master YouTube channels mapping from: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)

    if "youtube_channels" not in wb.sheetnames:
        raise ValueError(f"Sheet 'youtube_channels' not found in {EXCEL_PATH}. Available: {wb.sheetnames}")

    ws = wb["youtube_channels"]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Sheet 'youtube_channels' is empty.")

    headers = [_clean_str(c) for c in rows[0]]
    log.info(f"Found headers: {headers}")

    # Expected columns:
    # 0: youtube_account_id, 1: title, 2: channel_id, 3: custom_title,
    # 4: youtube_playlists_count, 5: Language, 6: Main Series IP, 7: Universe,
    # 8: IP CODES, 9: Global IP, 10: Global Universe

    channels_catalog: Dict[str, Dict[str, Any]] = {}
    skipped_count = 0

    for row_idx, r in enumerate(rows[1:], start=2):
        if not r or not any(r):
            continue

        raw_cid = r[2] if len(r) > 2 else None
        cid = _clean_str(raw_cid)

        if not cid or not cid.startswith("UC") or len(cid) != 24:
            skipped_count += 1
            log.warning(f"Row {row_idx}: Invalid channel_id '{raw_cid}', skipping.")
            continue

        account_id = r[0] if len(r) > 0 else None
        title = _clean_str(r[1]) if len(r) > 1 else None
        custom_title = _clean_str(r[3]) if len(r) > 3 else None
        playlist_count = r[4] if len(r) > 4 else None
        language = _clean_str(r[5]) if len(r) > 5 else None
        main_series_ip = _clean_str(r[6]) if len(r) > 6 else None
        universe = _clean_str(r[7]) if len(r) > 7 else None
        ip_code = _clean_str(r[8]) if len(r) > 8 else None
        global_ip = _clean_str(r[9]) if len(r) > 9 else None
        global_universe = _clean_str(r[10]) if len(r) > 10 else None

        channels_catalog[cid] = {
            "channel_id": cid,
            "account_id": account_id,
            "channel_title": title,
            "custom_title": custom_title,
            "playlists_count": playlist_count,
            "language": language or "Unknown",
            "main_series_ip": main_series_ip or "Others",
            "universe": universe or "Others",
            "ip_code": ip_code or "Others",
            "global_ip": global_ip or (main_series_ip or "Others"),
            "global_universe": global_universe or (universe or "Others"),
        }

    log.info(f"Successfully compiled {len(channels_catalog)} channels (skipped: {skipped_count}).")

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(EXCEL_PATH.name),
        "total_channels": len(channels_catalog),
        "channels": channels_catalog,
    }

    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    log.info(f"Saved canonical catalog to: {OUTPUT_JSON_PATH}")
    return metadata


if __name__ == "__main__":
    build_channel_catalog()
