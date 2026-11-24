"""High-performance parser for Amazon Streaming Reports (Content-Performance).

Reads 109 monthly streaming CSV files (2016-09 to 2025-09) with 33.2M rows
using PyArrow and Pandas to aggregate daily streaming telemetry by month,
episode, territory, and offer type.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import pyarrow.csv as pv

from core.ingestion.amazon_historical import resolve_title_mapping

log = logging.getLogger(__name__)

STREAMING_FILENAME_REGEX = re.compile(r"KLQ49[-_](\d{4}-\d{2})", re.IGNORECASE)


class AmazonStreamingParser:
    """Parses and aggregates raw Amazon daily streaming reports into monthly performance records."""

    def __init__(
        self,
        streaming_dir: Path | str,
        mapping_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.streaming_dir = Path(streaming_dir)
        self.mapping_cache = mapping_cache or {}
        self._memo: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}

    def extract_month_from_path(self, path: Path) -> Optional[str]:
        """Extracts 'YYYY-MM' from the file name, or returns None."""
        m = STREAMING_FILENAME_REGEX.search(path.name)
        if m:
            return m.group(1)
        m2 = re.search(r"(\d{4}-\d{2})", path.stem)
        return m2.group(1) if m2 else None

    def get_available_months(self) -> List[Tuple[str, Path]]:
        """Returns sorted list of (month, file_path) available in the streaming and performance directories."""
        found: Dict[str, Path] = {}
        dirs_to_check = [self.streaming_dir]
        if self.streaming_dir.parent.exists():
            perf_dir = self.streaming_dir.parent / "performance"
            if perf_dir.exists() and perf_dir != self.streaming_dir:
                dirs_to_check.append(perf_dir)

        for d in dirs_to_check:
            if not d.exists():
                continue
            for f in sorted(d.rglob("*.csv")):
                month = self.extract_month_from_path(f)
                if month and month not in found:
                    found[month] = f

        return sorted(found.items(), key=lambda x: x[0])

    def process_file(
        self,
        csv_path: Path,
        monthly_data: Dict[str, Dict[Tuple, List[float]]],
        target_month: Optional[str] = None,
    ) -> int:
        """Parses a single streaming report file and accumulates metrics in monthly_data.

        Returns number of unique aggregated records added for the month.
        """
        month = target_month or self.extract_month_from_path(csv_path)
        if not month:
            log.warning("Could not determine month for streaming report: %s", csv_path.name)
            return 0

        try:
            arrow_table = pv.read_csv(str(csv_path))
            df = arrow_table.to_pandas()
        except Exception as e:
            log.error("Failed to read streaming report %s: %s", csv_path.name, e)
            return 0

        if df.empty:
            return 0

        # Normalize column names: strip and title-case
        df.columns = [c.strip().title() for c in df.columns]

        req_cols = ["Title Id", "Title Name", "Minutes Streamed", "Unique Streams"]
        for rc in req_cols:
            if rc not in df.columns:
                log.error("Missing column '%s' in %s", rc, csv_path.name)
                return 0

        for opt in ["Season Id", "Season Name", "Series Id", "Series Name", "Offer Type", "Region", "Territory"]:
            if opt not in df.columns:
                df[opt] = ""

        # Normalize strings
        df["Title Id"] = df["Title Id"].fillna("").astype(str).str.strip()
        df["Title Name"] = df["Title Name"].fillna("").astype(str).str.strip()
        df["Season Id"] = df["Season Id"].fillna("").astype(str).str.strip()
        df["Season Name"] = df["Season Name"].fillna("").astype(str).str.strip()
        df["Series Id"] = df["Series Id"].fillna("").astype(str).str.strip()
        df["Series Name"] = df["Series Name"].fillna("").astype(str).str.strip()
        df["Offer Type"] = df["Offer Type"].fillna("PRIME").astype(str).str.strip().str.upper()
        df["Region"] = df["Region"].fillna("").astype(str).str.strip().str.upper()
        df["Territory"] = df["Territory"].fillna("").astype(str).str.strip().str.upper()

        # Coerce numeric columns safely
        df["Minutes Streamed"] = pd.to_numeric(
            df["Minutes Streamed"].astype(str).str.replace(",", ""), errors="coerce"
        ).fillna(0.0)
        df["Unique Streams"] = pd.to_numeric(
            df["Unique Streams"].astype(str).str.replace(",", ""), errors="coerce"
        ).fillna(0).astype(int)

        # Drop rows with empty title
        df = df[df["Title Name"] != ""]
        if df.empty:
            return 0

        # Group by composite key
        group_cols = [
            "Title Id",
            "Title Name",
            "Season Id",
            "Season Name",
            "Series Id",
            "Series Name",
            "Offer Type",
            "Region",
            "Territory",
        ]
        agg_df = df.groupby(group_cols, as_index=False).agg({
            "Minutes Streamed": "sum",
            "Unique Streams": "sum",
        })

        records_added = 0
        month_dict = monthly_data[month]

        for _, row in agg_df.iterrows():
            title_id = row["Title Id"]
            title_name = row["Title Name"]
            season_name = row["Season Name"]
            series_name = row["Series Name"]
            offer_type = row["Offer Type"]
            territory = row["Territory"] or row["Region"] or "UNKNOWN GEO"
            minutes = float(row["Minutes Streamed"])
            views = int(row["Unique Streams"])

            if offer_type in ("PRIME", "SVOD"):
                c_offer = "PRIME"
            elif offer_type in ("PURCHASE", "TVOD", "RENT"):
                c_offer = "PURCHASE"
            elif offer_type == "AVOD":
                c_offer = "AVOD"
            else:
                c_offer = offer_type

            memo_key = (title_name, series_name, season_name, title_id)
            if memo_key in self._memo:
                mapping = self._memo[memo_key]
            else:
                mapping = resolve_title_mapping(
                    title=title_name,
                    mapping_cache=self.mapping_cache,
                    fallback_series=series_name,
                    fallback_season=season_name,
                    sku=title_id,
                )
                self._memo[memo_key] = mapping

            key = (
                mapping["id"],
                mapping["id_episode"],
                mapping["id_project"],
                mapping["id_serie"],
                mapping["id_season"],
                mapping["project_name_broadkast"],
                mapping["serie_name_broadkast"],
                series_name or mapping["serie_name_amazon"],
                season_name or mapping["season_name_amazon"],
                mapping["episode_name_broadkast"],
                title_name,
                mapping["no_dialog"],
                mapping["performance_score"],
                mapping["youtube_url"],
                c_offer,
                "Amazon",
                territory,
            )

            entry = month_dict[key]
            entry[0] += views
            entry[1] += minutes
            records_added += 1

        log.info(
            "Processed streaming report %s (%s): %d aggregated records",
            csv_path.name,
            month,
            records_added,
        )
        return records_added
