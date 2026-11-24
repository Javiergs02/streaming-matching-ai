"""Unit tests for AmazonStreamingParser."""

import csv
import tempfile
from pathlib import Path
import pytest

from core.ingestion.amazon_streaming import AmazonStreamingParser


def test_extract_month_from_path():
    parser = AmazonStreamingParser(streaming_dir="data/amazon/streaming_reports")

    p1 = Path("KLQ49-2016-09-StreamingReport-aa5a9524-1117-445f-88e0-13adc2811e99.csv")
    assert parser.extract_month_from_path(p1) == "2016-09"

    p2 = Path("KLQ49_2024-04_VOD_PV-Content-Performance-Report.csv")
    assert parser.extract_month_from_path(p2) == "2024-04"

    p3 = Path("KLQ49-2017-04-StreamingReport-2ea3e6be-b24e-44b3-85a9-03904256b3cd (2).csv")
    assert parser.extract_month_from_path(p3) == "2017-04"

    # UUID contains 2022-4991, must match 2021-10
    p4 = Path("KLQ49-2021-10-StreamingReport-2f9dbe69-2022-4991-a61d-32007b1c9fa6.csv")
    assert parser.extract_month_from_path(p4) == "2021-10"

    p5 = Path("invalid_name.csv")
    assert parser.extract_month_from_path(p5) is None


def test_get_available_months(tmp_path):
    (tmp_path / "KLQ49-2017-01-StreamingReport-abc.csv").write_text("dummy")
    (tmp_path / "KLQ49-2017-02-StreamingReport-def.csv").write_text("dummy")
    (tmp_path / "other_file.txt").write_text("dummy")

    parser = AmazonStreamingParser(streaming_dir=tmp_path)
    months = parser.get_available_months()
    assert len(months) == 2
    assert months[0][0] == "2017-01"
    assert months[1][0] == "2017-02"


def test_process_file_aggregates_properly(tmp_path):
    csv_file = tmp_path / "KLQ49-2018-05-StreamingReport-test.csv"
    headers = [
        "Date", "Title Id", "Title Name", "Season Id", "Season Name",
        "Series Id", "Series Name", "Offer type", "Region", "Territory",
        "Minutes Streamed", "Unique Streams"
    ]
    rows = [
        # Day 1: Episode A in US (PRIME)
        ["2018-05-01", "AMZ_SKU_1", "Car Patrol Ep 1", "S1_ID", "Car Patrol", "SER_ID", "Car Patrol", "PRIME", "US", "US", "120.5", "10"],
        # Day 2: Episode A in US (PRIME) -> Should sum with Day 1
        ["2018-05-02", "AMZ_SKU_1", "Car Patrol Ep 1", "S1_ID", "Car Patrol", "SER_ID", "Car Patrol", "PRIME", "US", "US", "80.5", "5"],
        # Day 1: Episode A in GB (PRIME) -> Separate territory
        ["2018-05-01", "AMZ_SKU_1", "Car Patrol Ep 1", "S1_ID", "Car Patrol", "SER_ID", "Car Patrol", "PRIME", "GB", "GB", "50.0", "3"],
        # Day 1: Episode B in US (PURCHASE) -> Separate offer type
        ["2018-05-01", "AMZ_SKU_2", "Car Patrol Ep 2", "S1_ID", "Car Patrol", "SER_ID", "Car Patrol", "PURCHASE", "US", "US", "30.0", "1"],
    ]

    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    from collections import defaultdict
    monthly_data = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))

    parser = AmazonStreamingParser(streaming_dir=tmp_path)
    added = parser.process_file(csv_file, monthly_data)
    assert added == 3  # (Ep 1 US PRIME), (Ep 1 GB PRIME), (Ep 2 US PURCHASE)

    m_data = monthly_data["2018-05"]
    assert len(m_data) == 3

    # Check that US PRIME has 201.0 mins and 15 views
    us_prime_entries = [v for k, v in m_data.items() if k[10] == "Car Patrol Ep 1" and k[16] == "US" and k[14] == "PRIME"]
    assert len(us_prime_entries) == 1
    assert us_prime_entries[0][0] == 15
    assert us_prime_entries[0][1] == pytest.approx(201.0)
    assert us_prime_entries[0][2] == 0.0  # Revenue starts at 0 for streaming


def test_process_file_missing_required_columns(tmp_path):
    bad_file = tmp_path / "KLQ49-2018-05-StreamingReport-bad.csv"
    bad_file.write_text("Date,Something,Else\n2018-05-01,A,B\n")

    from collections import defaultdict
    monthly_data = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))

    parser = AmazonStreamingParser(streaming_dir=tmp_path)
    added = parser.process_file(bad_file, monthly_data)
    assert added == 0
