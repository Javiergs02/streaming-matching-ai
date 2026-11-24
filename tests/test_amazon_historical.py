"""Unit tests for Historical Amazon Revenue processing and Google Drive sync."""

import csv
import tempfile
from pathlib import Path
import pytest

from core.domain.amazon import AMAZON_EUR_TO_USD, convert_amazon_eur_to_usd
from core.ingestion.amazon_historical import (
    HistoricalAmazonParser,
    convert_currency_to_eur,
    convert_currency_to_usd,
    load_mapping_cache,
    normalize_title,
    parse_numeric_float,
    parse_numeric_int,
    parse_period_month,
    resolve_title_mapping,
)
from core.ingestion.gdrive_sync import GoogleDriveSync


def test_parse_period_month():
    assert parse_period_month("2020-02-01") == "2020-02"
    assert parse_period_month("2020-02") == "2020-02"
    assert parse_period_month("01/01/2017") == "2017-01"
    assert parse_period_month("31/12/2018") == "2018-12"
    assert parse_period_month("1/15/2019") == "2019-01"
    assert parse_period_month("Aug-16-2017") == "2017-08"
    assert parse_period_month("Jun-28-2025") == "2025-06"
    assert parse_period_month(None) is None
    assert parse_period_month("") is None
    assert parse_period_month("invalid-date-string") is None


def test_convert_currency_to_usd():
    assert convert_currency_to_usd(100.0, "USD") == 100.0
    assert convert_currency_to_usd(100.0, None) == 100.0
    assert round(convert_currency_to_usd(100.0, "EUR"), 2) == 108.70
    assert round(convert_currency_to_usd(100.0, "GBP"), 2) == 127.17
    assert round(convert_currency_to_usd(10000.0, "JPY"), 2) == 67.39
    assert convert_currency_to_usd(1000.0, "INR") == pytest.approx(12.065, rel=1e-4)
    assert round(convert_currency_to_usd(100.0, "CAD"), 2) == 73.91
    assert round(convert_currency_to_usd(100.0, "AUD"), 2) == 66.30
    assert round(convert_currency_to_usd(100.0, "BRL"), 2) == 17.39
    assert round(convert_currency_to_usd(100.0, "MXN"), 2) == 5.00
    assert round(convert_currency_to_usd(100.0, "SEK"), 2) == 9.57
    assert round(convert_currency_to_usd(100.0, "PLN"), 2) == 25.00
    assert round(convert_currency_to_usd(100.0, "TRY"), 2) == 2.93
    # Fallback to USD / 1.0 with warning for uncataloged currency
    assert convert_currency_to_usd(100.0, "XYZ") == 100.0


def test_convert_currency_to_eur():
    assert convert_currency_to_eur(100.0, "EUR") == 100.0
    assert convert_currency_to_eur(100.0, "USD") == 92.0
    assert convert_currency_to_eur(100.0, "GBP") == pytest.approx(117.0, rel=1e-3)
    assert convert_currency_to_eur(10000.0, "JPY") == pytest.approx(62.0, rel=1e-3)
    assert convert_currency_to_eur(1000.0, "INR") == pytest.approx(11.1, rel=1e-3)
    assert convert_currency_to_eur(100.0, "CAD") == pytest.approx(68.0, rel=1e-3)
    assert convert_currency_to_eur(100.0, "AUD") == pytest.approx(61.0, rel=1e-3)
    assert convert_currency_to_eur(100.0, "BRL") == pytest.approx(16.0, rel=1e-3)
    assert convert_currency_to_eur(100.0, "MXN") == pytest.approx(4.6, rel=1e-3)
    assert convert_currency_to_eur(100.0, "SEK") == pytest.approx(8.8, rel=1e-3)
    assert convert_currency_to_eur(100.0, "PLN") == pytest.approx(23.0, rel=1e-3)
    assert round(convert_currency_to_eur(100.0, "TRY"), 1) == 2.7
    # Fallback to USD / 1.0 with warning for uncataloged currency
    assert convert_currency_to_eur(100.0, "XYZ") == 92.0
    assert convert_currency_to_eur(100.0, None) == 92.0


def test_normalize_title():
    assert normalize_title("Hello, World!") == "hello world"
    assert normalize_title("  Dino el Dinosaurio: Los Cubos / La Mochila  ") == "dino el dinosaurio los cubos"
    assert normalize_title("") == ""
    assert normalize_title(None) == ""


def test_resolve_title_mapping_exact_and_normalized():
    with tempfile.TemporaryDirectory() as tmp_dir:
        mapping_file = Path(tmp_dir) / "mappings.csv"
        with mapping_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Amazon Original Title", "Truncated/Normalized Target", "Match Status",
                "Amazon Series", "Amazon Season", "Broadkast Assigned Title", "Broadkast ID",
                "Broadkast Episode Number", "Broadkast Series", "Broadkast Season",
                "Performance Score", "No Dialog", "Broadkast Project ID",
                "Broadkast Project Name", "Broadkast Series ID", "Broadkast Season ID",
                "YouTube ID", "Match Method", "Score"
            ])
            writer.writerow([
                "Mouk en Paris", "Mouk", "MATCH",
                "Mouk", "Mouk S1", "Mouk Goes to Paris", "EP_100",
                "1", "MOUK", "1", "1.5", "False", "2", "CARCITY", "5", "1",
                "yt_12345", "exact", "1.0"
            ])

        cache = load_mapping_cache(mapping_file)

        # 1. Exact match
        res_exact = resolve_title_mapping("Mouk en Paris", cache)
        assert res_exact["status"] == "MATCH"
        assert res_exact["id"] == "EP_100"
        assert res_exact["episode_name_broadkast"] == "Mouk Goes to Paris"
        assert res_exact["youtube_url"] == "https://youtube.com/watch?v=yt_12345"

        # 2. Normalized match (different spacing / punctuation / case)
        res_norm = resolve_title_mapping("mouk en paris!", cache)
        assert res_norm["status"] == "MATCH"
        assert res_norm["id"] == "EP_100"

        # 3. Truncated match
        res_trunc = resolve_title_mapping("Mouk / Second Part / Bonus", cache)
        assert res_trunc["status"] == "MATCH"
        assert res_trunc["id"] == "EP_100"

        # 4. Unknown title
        res_unknown = resolve_title_mapping("Completely Unknown Show", cache, "Fallback Series", "Fallback Season")
        assert res_unknown["status"] == "UNMATCHED"
        assert res_unknown["id"] == "UNMATCHED"
        assert res_unknown["serie_name_amazon"] == "Fallback Series"


def test_resolve_title_mapping_franchise_isolation():
    """Verifies that shared common episode titles never leak across distinct franchises."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mapping_file = Path(tmp_dir) / "mappings.csv"
        with mapping_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Amazon Original Title", "Truncated/Normalized Target", "Match Status",
                "Amazon Series", "Amazon Season", "Broadkast Assigned Title", "Broadkast ID",
                "Broadkast Episode Number", "Broadkast Series", "Broadkast Season",
                "Performance Score", "No Dialog", "Broadkast Project ID",
                "Broadkast Project Name", "Broadkast Series ID", "Broadkast Season ID",
                "YouTube ID", "Match Method", "Score"
            ])
            # Shark Academy has Bingo
            writer.writerow([
                "Bingo", "Bingo", "MATCH",
                "Shark Academy - Canções para crianças", "Shark Academy S1", "Bingo Shark", "EP_2847",
                "1", "SHARKS_NURSERY_RHYMES", "1", "10.0", "False", "13", "SHARK_ACADEMY", "39", "1",
                "yt_shark", "exact", "1.0"
            ])
            # Cam & Sam (Babies) has Bingo
            writer.writerow([
                "Bingo", "Bingo", "MATCH",
                "Cam & Sam", "Cam & Sam S1", "Bingo Puppy", "EP_3490",
                "2", "BABIES", "1", "5.0", "False", "15", "BABIES", "45", "1",
                "yt_babies", "exact", "1.0"
            ])

        cache = load_mapping_cache(mapping_file)

        # Querying with Shark Academy series gets Shark Academy match
        res_shark = resolve_title_mapping("Bingo", cache, fallback_series="Shark Academy - Nursery Rhymes")
        assert res_shark["status"] == "MATCH"
        assert res_shark["project_name_broadkast"] == "SHARK_ACADEMY"
        assert res_shark["id"] == "EP_2847"

        # Querying with Cam & Sam gets Babies match
        res_babies = resolve_title_mapping("Bingo", cache, fallback_series="Cam & Sam")
        assert res_babies["status"] == "MATCH"
        assert res_babies["project_name_broadkast"] == "BABIES"
        assert res_babies["id"] == "EP_3490"

        # Querying with Car City (which has no Bingo) strictly REJECTS leaking into Shark or Babies
        res_carcity = resolve_title_mapping("Bingo", cache, fallback_series="Car City Songs")
        assert res_carcity["status"] == "UNMATCHED"
        assert res_carcity["project_name_broadkast"] == "UNMATCHED"
        assert res_carcity["id"] == "UNMATCHED"


def test_resolve_title_mapping_reference_catalog_fallback():
    """Verifies that titles not in production_mappings.csv resolve deterministically via AmazonReferenceCatalog."""
    empty_cache = {
        "exact_pair": {},
        "exact": {},
        "norm_pair": {},
        "norm": {},
        "trunc": {},
    }

    # 1. Unknown title, but known Amazon SKU/ASIN
    res_sku = resolve_title_mapping(
        "Random Translated Episode",
        empty_cache,
        fallback_series="CC2 Super Truck",
        sku="0018DM0YX4J",
    )
    assert res_sku["status"] == "CATALOG_MATCH"
    assert res_sku["project_name_broadkast"] == "CARCITY"
    assert res_sku["performance_score"] == "100.0"

    # 2. Unknown title, but known localized series name
    res_series = resolve_title_mapping(
        "Der Welpe / Der unterirdische Spaziergang",
        empty_cache,
        fallback_series="MOLANG",
    )
    assert res_series["status"] == "CATALOG_MATCH"
    assert res_series["project_name_broadkast"] == "MILLIMAGES"
    assert res_series["performance_score"] == "100.0"

    # 3. Gold Standard precedence: when title is in cache, cache ALWAYS takes precedence
    cache_with_item = {
        "exact_pair": {
            ("CC2 Super Truck", "Gold Standard Title"): {
                "Broadkast ID": "EP_GOLD_999",
                "Broadkast Episode Number": "999",
                "Broadkast Project ID": "1",
                "Broadkast Project Name": "CARCITY",
                "Broadkast Series ID": "10",
                "Broadkast Series": "SUPER_TRUCK",
                "Broadkast Season ID": "100",
                "Broadkast Season": "1",
                "Broadkast Assigned Title": "Gold Standard Title",
                "Performance Score": "98.5",
                "No Dialog": "False",
                "YouTube ID": "yt_123",
                "Match Method": "exact",
                "Score": "100.0",
            }
        },
        "exact": {},
        "norm_pair": {},
        "norm": {},
        "trunc": {},
    }
    res_gold = resolve_title_mapping(
        "Gold Standard Title",
        cache_with_item,
        fallback_series="CC2 Super Truck",
        sku="0018DM0YX4J",
    )
    assert res_gold["status"] == "MATCH"
    assert res_gold["id"] == "EP_GOLD_999"
    assert res_gold["performance_score"] == "98.5"


def test_historical_parser_e2e():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        amazon_dir = tmp_path / "amazon"
        batches_dir = amazon_dir / "historical_revenue" / "batches"
        batches_dir.mkdir(parents=True)
        reports_dir = tmp_path / "output" / "analytics_reports"
        reports_dir.mkdir(parents=True)

        # Create dummy batch CSV
        batch_csv = batches_dir / "Batch_1.csv"
        with batch_csv.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Title/Season ID", "ASIN", "Title Name", "Series Name", "Season Name",
                "Consumption Type", "Quality", "Unit Price", "Quantity", "Is Refund",
                "Duration Streamed", "Paid Ad Impressions", "Ad Revenue", "Royalty Rate",
                "Royalty Amount", "Royalty Currency", "Region", "Territory",
                "Period Start", "Period End", "Type", "CER Percentile"
            ])
            # Row 1: Prime
            writer.writerow([
                "T1", "B01", "Dino Adventures", "Dino Show", "Dino S1",
                "Prime", "", "", "", "",
                "2.5", "", "", "0.10",
                "10.0", "USD", "US", "US",
                "01/01/2017", "31/01/2017", "", ""
            ])
            # Row 2: Purchase
            writer.writerow([
                "T2", "B02", "Dino The Movie", "Dino Show", "Dino S1",
                "Purchase", "HD", "4.99", "3", "",
                "", "", "", "0.50",
                "6.0", "EUR", "US", "US",
                "01/01/2017", "31/01/2017", "", ""
            ])

        mappings_csv = tmp_path / "mappings.csv"
        mappings_csv.touch()

        parser = HistoricalAmazonParser(
            amazon_data_dir=amazon_dir,
            mappings_file=mappings_csv,
            output_reports_dir=reports_dir,
        )

        res = parser.process_all_historical_files(target_months={"2017-01"}, overwrite=True)
        assert "2017-01" in res
        assert res["2017-01"] > 0

        # Verify output CSV
        out_csv = reports_dir / "analytics_reports_01_2017.csv"
        assert out_csv.exists()

        with out_csv.open("r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            assert len(reader) >= 2
            # Check presence of region US and Global
            regions = {r["region"] for r in reader}
            assert "US" in regions
            assert "Global" in regions


def test_historical_parser_future_month_scaling():
    """Verifies that future months process seamlessly and scale with full schema compliance."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        amazon_dir = tmp_path / "amazon"
        monthly_dir = amazon_dir / "historical_revenue" / "monthly_reports" / "2027"
        monthly_dir.mkdir(parents=True)
        reports_dir = tmp_path / "output" / "analytics_reports"
        reports_dir.mkdir(parents=True)

        # Create dummy future monthly CSV (e.g. Jan 2027)
        future_csv = monthly_dir / "Amazon_Video_Direct_Performance_Metrics_Jan_2027.csv"
        with future_csv.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Title/Season ID", "ASIN", "Title Name", "Series Name", "Season Name",
                "Consumption Type", "Quality", "Unit Price", "Quantity", "Is Refund",
                "Duration Streamed", "Paid Ad Impressions", "Ad Revenue", "Royalty Rate",
                "Royalty Amount", "Royalty Currency", "Region", "Territory",
                "Period Start", "Period End", "Type", "CER Percentile"
            ])
            writer.writerow([
                "T100", "B099", "Mud Trap", "AnimaCars", "AnimaCars S1",
                "Prime", "HD", "", "", "",
                "15.5", "", "", "0.10",
                "25.0", "EUR", "DE", "DE",
                "2027-01-01", "2027-01-31", "", ""
            ])

        mappings_csv = tmp_path / "mappings.csv"
        with mappings_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Amazon Original Title", "Truncated/Normalized Target", "Match Status",
                "Amazon Series", "Amazon Season", "Broadkast Assigned Title", "Broadkast ID",
                "Broadkast Episode Number", "Broadkast Series", "Broadkast Season",
                "Performance Score", "No Dialog", "Broadkast Project ID",
                "Broadkast Project Name", "Broadkast Series ID", "Broadkast Season ID",
                "YouTube ID", "Match Method", "Score"
            ])
            writer.writerow([
                "Mud Trap", "Mud Trap", "MATCH",
                "AnimaCars", "AnimaCars S1", "The Mud Trap", "EP_2606",
                "2", "ANIMACARS_DAILY_LIFE", "1", "81.0", "False", "5", "ANIMACARS", "22", "1",
                "yt_mud", "exact", "1.0"
            ])

        parser = HistoricalAmazonParser(
            amazon_data_dir=amazon_dir,
            mappings_file=mappings_csv,
            output_reports_dir=reports_dir,
        )

        res = parser.process_all_historical_files(target_months={"2027-01"}, overwrite=True)
        assert "2027-01" in res
        assert res["2027-01"] > 0

        out_csv = reports_dir / "analytics_reports_01_2027.csv"
        assert out_csv.exists()

        with out_csv.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            assert len(rows) >= 1
            matched_row = rows[0]
            assert matched_row["id_episode"] == "EP_2"
            assert matched_row["serie_name_broadkast"] == "ANIMACARS_DAILY_LIFE"
            assert matched_row["project_name_broadkast"] == "ANIMACARS"
            assert matched_row["platform"] == "Amazon"


def test_gdrive_sync_configuration():
    # Not configured when env/files are absent
    syncer = GoogleDriveSync(creds_path="/nonexistent/creds.json", folder_id=None)
    assert not syncer.is_configured()


def test_parse_numeric_helpers_handle_thousands_commas():
    assert parse_numeric_float("1,436.15") == pytest.approx(1436.15)
    assert parse_numeric_float(" 12,345 ") == pytest.approx(12345.0)
    assert parse_numeric_float("") == 0.0
    assert parse_numeric_float(None) == 0.0
    assert parse_numeric_float("bad", default=5.0) == 5.0

    assert parse_numeric_int("7,813") == 7813
    assert parse_numeric_int("1,220.0") == 1220
    assert parse_numeric_int("", default=0) == 0


def test_historical_amazon_parser_handles_comma_formatted_numbers(tmp_path):
    amazon_dir = tmp_path / "amazon"
    batch_dir = amazon_dir / "historical_revenue" / "batches"
    batch_dir.mkdir(parents=True)
    reports_dir = tmp_path / "analytics_reports"
    reports_dir.mkdir(parents=True)

    batch_csv = batch_dir / "Batch_2_test.csv"
    with batch_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Title/Season ID", "ASIN", "Title Name", "Series Name", "Season Name",
            "Consumption Type", "Quality", "Unit Price", "Quantity", "Is Refund",
            "Duration Streamed", "Paid Ad Impressions", "Ad Revenue", "Royalty Rate",
            "Royalty Amount", "Royalty Currency", "Region", "Territory",
            "Period Start", "Period End", "Type", "CER Percentile"
        ])
        writer.writerow([
            "S1", "B01", "Car Patrol of Car City", "Car Patrol", "Car Patrol S1",
            "Prime", "HD", "", "1,250", "",
            "1,220.85", "", "", "0.10",
            "1,436.15", "USD", "US", "US",
            "01/03/2018", "01/04/2018", "Season", ""
        ])

    mappings_csv = tmp_path / "mappings.csv"
    with mappings_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Amazon Original Title", "Truncated/Normalized Target", "Match Status",
            "Amazon Series", "Amazon Season", "Broadkast Assigned Title", "Broadkast ID",
            "Broadkast Episode Number", "Broadkast Series", "Broadkast Season",
            "Performance Score", "No Dialog", "Broadkast Project ID",
            "Broadkast Project Name", "Broadkast Series ID", "Broadkast Season ID",
            "YouTube ID", "Match Method", "Score"
        ])
        writer.writerow([
            "Car Patrol of Car City", "Car Patrol of Car City", "MATCH",
            "Car Patrol", "Car Patrol S1", "Car Patrol Ep 1", "EP_99",
            "1", "CAR_PATROL", "1", "99.0", "False", "1", "CARCITY", "10", "1",
            "yt_cp", "exact", "1.0"
        ])

    parser = HistoricalAmazonParser(
        amazon_data_dir=amazon_dir,
        mappings_file=mappings_csv,
        output_reports_dir=reports_dir,
    )
    res = parser.process_all_historical_files(target_months={"2018-03"}, overwrite=True)
    assert res["2018-03"] >= 1

    out_csv = reports_dir / "analytics_reports_03_2018.csv"
    with out_csv.open("r", encoding="utf-8") as f:
        terr_rows = [r for r in csv.DictReader(f) if r["region"] == "US"]
    assert len(terr_rows) == 1
    assert int(terr_rows[0]["views"]) == 1250
    assert float(terr_rows[0]["minutes_streamed"]) == pytest.approx(1220.85 * 60.0, rel=1e-4)
    assert float(terr_rows[0]["revenue"]) == pytest.approx(1436.15, rel=1e-4)
    assert terr_rows[0]["currency"] == "USD"


def test_convert_amazon_eur_to_usd_is_exact_inverse():
    # Legacy EUR amount converted to USD
    assert convert_amazon_eur_to_usd(92.0, "EUR") == pytest.approx(100.0)
    assert convert_amazon_eur_to_usd(92.0) == pytest.approx(100.0)
    # Native USD amount passed as-is
    assert convert_amazon_eur_to_usd(100.0, "USD") == pytest.approx(100.0)
    assert convert_amazon_eur_to_usd(None) == 0.0
    assert AMAZON_EUR_TO_USD == pytest.approx(1.0 / 0.92)


def test_historical_parser_merges_streaming_and_revenue_reports(tmp_path):
    amazon_dir = tmp_path / "amazon"
    streaming_dir = amazon_dir / "streaming_reports"
    batches_dir = amazon_dir / "historical_revenue" / "batches"
    reports_dir = tmp_path / "reports"

    streaming_dir.mkdir(parents=True, exist_ok=True)
    batches_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create Streaming Report for 2018-03
    s_csv = streaming_dir / "KLQ49-2018-03-StreamingReport-abc.csv"
    with s_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date", "Title Id", "Title Name", "Season Id", "Season Name",
            "Series Id", "Series Name", "Offer type", "Region", "Territory",
            "Minutes Streamed", "Unique Streams"
        ])
        writer.writerow([
            "2018-03-01", "SKU_TEST", "Car Patrol Ep 1", "S1", "Car Patrol",
            "SER1", "Car Patrol", "PRIME", "US", "US", "500.0", "50"
        ])
        writer.writerow([
            "2018-03-02", "SKU_TEST", "Car Patrol Ep 1", "S1", "Car Patrol",
            "SER1", "Car Patrol", "PRIME", "US", "US", "300.0", "30"
        ])

    # 2. Create Revenue Batch file for 2018-03
    r_csv = batches_dir / "Batch_1.csv"
    with r_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Title/Season ID", "ASIN", "Title Name", "Series Name", "Season Name",
            "Consumption Type", "Quality", "Unit Price", "Quantity", "Is Refund",
            "Duration Streamed", "Paid Ad Impressions", "Ad Revenue", "Royalty Rate",
            "Royalty Amount", "Royalty Currency", "Region", "Territory", "Period Start",
            "Period End", "Type", "CER Percentile"
        ])
        writer.writerow([
            "SKU_TEST", "B01TEST", "Car Patrol Ep 1", "Car Patrol", "Car Patrol",
            "Prime", "", "", "99", "", "10.0", "", "", "", "250.0", "USD", "US", "US",
            "01/03/2018", "01/04/2018", "Season", ""
        ])

    mappings_csv = tmp_path / "mappings.csv"
    with mappings_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Amazon Original Title", "Truncated/Normalized Target", "Match Status",
            "Amazon Series", "Amazon Season", "Broadkast Assigned Title", "Broadkast ID",
            "Broadkast Episode Number", "Broadkast Series", "Broadkast Season",
            "Performance Score", "No Dialog", "Broadkast Project ID",
            "Broadkast Project Name", "Broadkast Series ID", "Broadkast Season ID",
            "YouTube ID", "Match Method", "Score"
        ])
        writer.writerow([
            "Car Patrol Ep 1", "Car Patrol Ep 1", "MATCH",
            "Car Patrol", "Car Patrol S1", "Car Patrol Ep 1", "EP_100",
            "1", "CAR_PATROL", "1", "99.0", "False", "1", "CARCITY", "10", "1",
            "yt_cp1", "exact", "1.0"
        ])

    parser = HistoricalAmazonParser(
        amazon_data_dir=amazon_dir,
        mappings_file=mappings_csv,
        output_reports_dir=reports_dir,
    )
    res = parser.process_all_historical_files(target_months={"2018-03"}, overwrite=True)
    assert res["2018-03"] >= 1

    out_csv = reports_dir / "analytics_reports_03_2018.csv"
    with out_csv.open("r", encoding="utf-8") as f:
        terr_rows = [r for r in csv.DictReader(f) if r["region"] == "US"]
    assert len(terr_rows) == 1
    # Streaming minutes: 500 + 300 = 800.0 (duration from revenue report 10.0h = 600m is NOT added)
    assert float(terr_rows[0]["minutes_streamed"]) == pytest.approx(800.0)
    # Unique streams: 50 + 30 = 80
    assert int(terr_rows[0]["views"]) == 80
    # Revenue from batch: 250.0 USD
    assert float(terr_rows[0]["revenue"]) == pytest.approx(250.0)
    assert terr_rows[0]["currency"] == "USD"
    # CPH: 250 / (800 / 60) = 18.75
    assert float(terr_rows[0]["cph_rate"]) == pytest.approx(18.75)


def test_historical_parser_ingests_modern_svod_and_tvod(tmp_path):
    """Verifies that modern SVOD and TVOD earnings are ingested and merged with performance telemetry."""
    amazon_dir = tmp_path / "amazon"
    perf_dir = amazon_dir / "performance" / "KLQ49_2025-10_VOD_PV-Content-Performance-Report"
    perf_dir.mkdir(parents=True)
    earnings_dir = amazon_dir / "earnings"
    earnings_dir.mkdir(parents=True)
    reports_dir = tmp_path / "output"

    # 1. Performance telemetry for 2025-10
    perf_csv = perf_dir / "KLQ49_2025-10_VOD_PV-Content-Performance-Report.csv"
    with perf_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date", "Title Id", "Title Name", "Season Id", "Season Name",
            "Series Id", "Series Name", "Offer Type", "Region", "Territory",
            "Minutes Streamed", "Unique Streams"
        ])
        writer.writerow([
            "2025-10-01", "T01", "Car Patrol Ep 1", "S01", "Car Patrol S1",
            "SER01", "Car Patrol", "PRIME", "US", "US", "1200.0", "150"
        ])

    # 2. Modern SVOD earnings for 2025-10
    svod_csv = earnings_dir / "SVOD_2024_09_2026_09.csv"
    with svod_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Statement period", "Contract ID", "Territory", "Duration streamed hours",
            "CPH rate", "Term type", "Total accrued royalty", "Royalty currency",
            "ASIN", "Vendor SKU", "Vendor name", "Season/movie SKU", "Title name",
            "Season title", "Series title", "Title category"
        ])
        writer.writerow([
            "2025-10", "KLQ49", "US", 20.0, 0.05, "", 300.0, "USD",
            "B01ASIN", "SKU1", "Vendor", "", "Car Patrol Ep 1",
            "Car Patrol S1", "Car Patrol", "TV Episode"
        ])

    # 3. Modern TVOD earnings for 2025-10
    tvod_csv = earnings_dir / "TVOD_2025_01_2026_10.csv"
    with tvod_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Statement period", "Aggregation period", "Royalty earned period",
            "Calculation period", "Contract ID", "Territory", "Vendor SKU",
            "Amazon ID", "ASIN ID", "Offer ID", "Titles included", "Title name",
            "Episode title", "Season title", "Series title", "Title category",
            "Transaction category", "Media format", "Theatrical release date",
            "Customer transaction date", "List price", "List price currency",
            "Transaction type", "Transaction count", "Total revenue", "Rev share %",
            "Unit cost", "Unit cost currency", "CYS cost discount", "CYS episode count ",
            "Version type", "License fee", "License fee currency"
        ])
        writer.writerow([
            "2025-10", "", "2025-10", "2025-10", "KLQ49", "US", "SKU1",
            "B01ASIN", "B01ASIN", "offer1", "", "Car Patrol Ep 1",
            "Car Patrol Ep 1", "Car Patrol S1", "Car Patrol", "TV Episode",
            "PURCHASE", "HD", "", "", 1.99, "USD",
            "CHARGE", 10, 19.9, 0.5, 1.0, "USD", 0, 0,
            "ORIGINAL", 50.0, "USD"
        ])

    mappings_csv = tmp_path / "mappings.csv"
    with mappings_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Amazon Original Title", "Truncated/Normalized Target", "Match Status",
            "Amazon Series", "Amazon Season", "Broadkast Assigned Title", "Broadkast ID",
            "Broadkast Episode Number", "Broadkast Series", "Broadkast Season",
            "Performance Score", "No Dialog", "Broadkast Project ID",
            "Broadkast Project Name", "Broadkast Series ID", "Broadkast Season ID",
            "YouTube ID", "Match Method", "Score"
        ])
        writer.writerow([
            "Car Patrol Ep 1", "Car Patrol Ep 1", "MATCH",
            "Car Patrol", "Car Patrol S1", "Car Patrol Ep 1", "EP_100",
            "1", "CAR_PATROL", "1", "99.0", "False", "1", "CARCITY", "10", "1",
            "yt_cp1", "exact", "1.0"
        ])

    parser = HistoricalAmazonParser(
        amazon_data_dir=amazon_dir,
        mappings_file=mappings_csv,
        output_reports_dir=reports_dir,
    )
    res = parser.process_all_historical_files(target_months={"2025-10"}, overwrite=True)
    assert res["2025-10"] >= 1

    out_csv = reports_dir / "analytics_reports_10_2025.csv"
    assert out_csv.exists()
    with out_csv.open("r", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["region"] == "US"]

    prime_rows = [r for r in rows if r["offer_type"] == "PRIME"]
    purchase_rows = [r for r in rows if r["offer_type"] == "PURCHASE"]

    assert len(prime_rows) == 1
    # Minutes streamed from performance: 1200.0 (SVOD 20h = 1200m not duplicated)
    assert float(prime_rows[0]["minutes_streamed"]) == pytest.approx(1200.0)
    assert int(prime_rows[0]["views"]) == 150
    assert float(prime_rows[0]["revenue"]) == pytest.approx(300.0)
    assert float(prime_rows[0]["revenue_svod"]) == pytest.approx(300.0)
    assert prime_rows[0]["currency"] == "USD"

    assert len(purchase_rows) == 1
    assert int(purchase_rows[0]["views"]) == 10
    assert float(purchase_rows[0]["revenue"]) == pytest.approx(50.0)
    assert float(purchase_rows[0]["revenue_tvod"]) == pytest.approx(50.0)
    assert purchase_rows[0]["currency"] == "USD"


