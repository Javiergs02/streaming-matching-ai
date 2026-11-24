"""Parser for Amazon Content Performance CSV files.

Transforms raw CSV rows into AmazonPerformanceRecord domain entities.
No normalization, matching, or database access — parsing only.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from core.domain.amazon import AmazonPerformanceRecord

log = logging.getLogger(__name__)

REQUIRED_COLUMNS: list[str] = [
    "Date",
    "Title Id",
    "Title Name",
    "Season Id",
    "Season Name",
    "Series Id",
    "Series Name",
    "Offer Type",
    "Region",
    "Territory",
    "Minutes Streamed",
    "Unique Streams",
]


class MissingColumnsError(ValueError):
    """Raised when the CSV is missing one or more required columns."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            f"Missing required column(s): {', '.join(missing)}"
        )


class InvalidNumericValueError(ValueError):
    """Raised when a numeric field cannot be parsed."""

    def __init__(self, field: str, value: str, row_num: int) -> None:
        self.field = field
        self.value = value
        self.row_num = row_num
        super().__init__(
            f"Row {row_num}: cannot parse '{value}' as {field}"
        )


def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def parse_float(value: str) -> float:
    try:
        return float(value.strip().replace(",", ""))
    except (ValueError, TypeError) as exc:
        raise InvalidNumericValueError("Minutes Streamed", value, 0) from exc


def parse_int(value: str) -> int:
    try:
        return int(float(value.strip().replace(",", "")))
    except (ValueError, TypeError) as exc:
        raise InvalidNumericValueError("Unique Streams", value, 0) from exc


def _detect_movie(row: dict[str, str]) -> bool:
    """Detect standalone movies in Amazon performance data.

    A movie is identified when Title Id == Series Id (both non-empty),
    meaning the title references itself as its own series.

    This was verified against the Amazon earnings 'Title Category'
    column: 100% of titles matching this pattern are categorised as
    'Movie'.

    Note: some movies have an empty Series Id instead, but the
    empty-ID heuristic produces false positives (e.g. Italian
    TV Season compilations). Those cases are caught downstream by
    the hardened voting thresholds in hybrid.py (>= 82 single or
    >= 120 total).
    """
    title_id = row["Title Id"].strip()
    series_id = row["Series Id"].strip()

    return bool(series_id and title_id == series_id)


def row_to_record(row: dict[str, str], row_num: int) -> AmazonPerformanceRecord:
    return AmazonPerformanceRecord(
        date=parse_date(row["Date"]),
        title_id=row["Title Id"].strip(),
        title_name=row["Title Name"].strip(),
        season_id=row["Season Id"].strip(),
        season_name=row["Season Name"].strip(),
        series_id=row["Series Id"].strip(),
        series_name=row["Series Name"].strip(),
        offer_type=row["Offer Type"].strip(),
        region=row["Region"].strip(),
        territory=row["Territory"].strip(),
        minutes_streamed=parse_float(row["Minutes Streamed"]),
        unique_streams=parse_int(row["Unique Streams"]),
        is_movie=_detect_movie(row),
    )


def validate_columns(headers: list[str]) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise MissingColumnsError(missing)


def find_csv_file(data_dir: str | Path) -> Path:
    """Locate a single CSV in the given directory.

    Raises if zero or more-than-one CSV exists.
    """
    data_dir = Path(data_dir)
    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")
    if len(csv_files) > 1:
        names = ", ".join(f.name for f in csv_files)
        raise ValueError(
            f"Multiple CSV files found in {data_dir}: {names}. "
            f"Please specify which file to parse."
        )
    return csv_files[0]


class AmazonPerformanceCsvParser:
    """Parses Amazon Content Performance CSVs into domain records."""

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path)

    def parse(self) -> list[AmazonPerformanceRecord]:
        if not self.csv_path.exists():
            raise FileNotFoundError(
                f"CSV file not found: {self.csv_path}"
            )

        records: list[AmazonPerformanceRecord] = []

        with self.csv_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError(f"CSV file is empty: {self.csv_path}")

            validate_columns(list(reader.fieldnames))

            for row_num, row in enumerate(reader, start=2):
                if row is None:
                    continue
                record = row_to_record(row, row_num)
                records.append(record)

        log.info(
            "Parsed %d record(s) from %s", len(records), self.csv_path.name
        )
        return records
