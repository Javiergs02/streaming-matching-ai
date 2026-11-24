"""Unit tests for AmazonPaymentParser and payment reconciliation."""

import csv
from datetime import date
from pathlib import Path
import pytest

from core.ingestion.amazon_payments import (
    AmazonPaymentParser,
    AmazonPaymentRecord,
    derive_sales_month,
    parse_payment_date_str,
)


def test_parse_payment_date_str():
    assert parse_payment_date_str("August 29, 2016") == date(2016, 8, 29)
    assert parse_payment_date_str("January 31, 2024") == date(2024, 1, 31)
    assert parse_payment_date_str("2024-05-01") == date(2024, 5, 1)
    assert parse_payment_date_str("") is None
    assert parse_payment_date_str(None) is None
    assert parse_payment_date_str("invalid date") is None


def test_derive_sales_month():
    assert derive_sales_month(date(2016, 4, 30), date(2016, 5, 31)) == "2016-05"
    assert derive_sales_month(date(2017, 1, 1), date(2017, 2, 1)) == "2017-01"
    assert derive_sales_month(date(2016, 12, 1), date(2017, 1, 1)) == "2016-12"
    assert derive_sales_month(date(2016, 11, 30), date(2017, 1, 1)) == "2016-12"


def test_parse_file_english(tmp_path):
    csv_file = tmp_path / "2016-08-All-PaymentsReport.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Payment date", "Status", "Sales period start date", "Sales period end date",
            "Accrued Royalty", "Accrued Royalty Currency", "Tax Withholding",
            "Tax Withholding Currency", "Adjustments", "Adjustments Currency",
            "Net Earnings", "Net Earnings Currency", "FX Rate", "Payment", "Payment Currency"
        ])
        writer.writerow([
            "August 29, 2016", "Paid", "April 30, 2016", "May 31, 2016",
            "100.0", "USD", "0", "USD", "", "", "100.0", "USD", "0.92", "92.0", "EUR"
        ])

    parser = AmazonPaymentParser(payments_dir=tmp_path)
    records = parser.parse_file(csv_file)
    assert len(records) == 1
    r = records[0]
    assert r.status == "Paid"
    assert r.sales_month == "2016-05"
    assert r.accrued_royalty == 100.0
    assert r.accrued_currency == "USD"
    assert r.accrued_usd == 100.0
    assert r.payment_amount == 92.0
    assert r.payment_currency == "EUR"
    assert r.fx_rate == 0.92


def test_parse_file_spanish(tmp_path):
    csv_file = tmp_path / "2017-05-All-PaymentsReport.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Fecha de pago", "Estado", "Fecha de inicio del período de ventas",
            "Fecha límite del período de ventas", "Regalías devengadas",
            "Divisa de las regalías devengadas", "Retención de impuestos",
            "Divisa de retención de impuestos", "Ajustes", "Divisa de ajustes",
            "Ganancias netas", "Divisa de ganancias netas", "Tipo de cambio", "Pago", "Divisa de pago"
        ])
        writer.writerow([
            "May 29, 2017", "Pagado", "February 28, 2017", "April 1, 2017",
            "10000", "JPY", "0", "JPY", "", "", "10000", "JPY", "0.008", "80.0", "EUR"
        ])

    parser = AmazonPaymentParser(payments_dir=tmp_path)
    records = parser.parse_file(csv_file)
    assert len(records) == 1
    r = records[0]
    assert r.status == "Pagado"
    assert r.sales_month == "2017-03"
    assert r.accrued_royalty == 10000.0
    assert r.accrued_currency == "JPY"
    assert r.payment_amount == 80.0
    assert r.payment_currency == "EUR"
    assert r.accrued_usd == pytest.approx(67.39, rel=1e-3)


def test_export_payments_ledger_csv(tmp_path):
    pay_dir = tmp_path / "payments"
    pay_dir.mkdir()
    f1 = pay_dir / "pay1.csv"
    with f1.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Payment date", "Status", "Sales period start date", "Sales period end date",
            "Accrued Royalty", "Accrued Royalty Currency", "Tax Withholding",
            "Tax Withholding Currency", "Adjustments", "Adjustments Currency",
            "Net Earnings", "Net Earnings Currency", "FX Rate", "Payment", "Payment Currency"
        ])
        writer.writerow([
            "August 29, 2016", "Paid", "April 30, 2016", "May 31, 2016",
            "50.0", "EUR", "0", "EUR", "", "", "50.0", "EUR", "", "50.0", "EUR"
        ])

    parser = AmazonPaymentParser(payments_dir=pay_dir)
    out_csv = tmp_path / "out" / "ledger.csv"
    res = parser.export_payments_ledger_csv(out_csv)
    assert res.exists()
    assert out_csv.exists()


def test_reconcile_with_analytics_reports(tmp_path):
    pay_dir = tmp_path / "payments"
    pay_dir.mkdir()
    f1 = pay_dir / "2020-04-All-PaymentsReport.csv"
    with f1.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Payment date", "Status", "Sales period start date", "Sales period end date",
            "Accrued Royalty", "Accrued Royalty Currency", "Tax Withholding",
            "Tax Withholding Currency", "Adjustments", "Adjustments Currency",
            "Net Earnings", "Net Earnings Currency", "FX Rate", "Payment", "Payment Currency"
        ])
        writer.writerow([
            "April 29, 2020", "Paid", "January 01, 2020", "February 01, 2020",
            "1000.0", "USD", "0", "USD", "", "", "1000.0", "USD", "", "1000.0", "USD"
        ])

    rep_dir = tmp_path / "analytics"
    rep_dir.mkdir()
    rep_file = rep_dir / "analytics_reports_01_2020.csv"
    with rep_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "id_episode", "id_project", "id_serie", "id_season",
            "project_name_broadkast", "serie_name_broadkast", "serie_name_amazon",
            "season_name_amazon", "episode_name_broadkast", "episode_name_amazon",
            "no_dialog", "performance_score", "youtube_url", "offer_type",
            "platform", "region", "views", "minutes_streamed", "avg_view_minutes",
            "revenue", "revenue_svod", "revenue_tvod", "cph_rate", "currency"
        ])
        # Territory row
        writer.writerow([
            "EP_1", "EP_1", "1", "1", "1", "P", "S", "S", "S", "E", "E",
            "False", "", "", "PRIME", "Amazon", "US", "500", "2500.0", "5.0",
            "1000.0000", "1000.0000", "0.0000", "24.0", "USD"
        ])
        # Global row (must NOT be double counted!)
        writer.writerow([
            "EP_1", "EP_1", "1", "1", "1", "P", "S", "S", "S", "E", "E",
            "False", "", "", "PRIME", "Amazon", "Global", "500", "2500.0", "5.0",
            "1000.0000", "1000.0000", "0.0000", "24.0", "USD"
        ])

    parser = AmazonPaymentParser(payments_dir=pay_dir)
    df_rec = parser.reconcile_with_analytics_reports(analytics_reports_dir=rep_dir)

    assert len(df_rec) == 1
    row = df_rec.iloc[0]
    assert row["sales_month"] == "2020-01"
    assert row["reported_revenue_usd"] == 1000.0
    assert row["payments_accrued_usd"] == 1000.0
    assert row["variance_usd"] == 0.0
    assert row["payment_status"] == "PAID"
    assert row["reconciliation_category"] == "EXACT_MATCH"
