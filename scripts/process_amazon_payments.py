#!/usr/bin/env python3
"""CLI Script to parse Amazon Payment Reports, export ledger, and reconcile against Analytics Reports.

Usage:
    venv/bin/python scripts/process_amazon_payments.py
    venv/bin/python scripts/process_amazon_payments.py --ledger-out data/output/amazon_payments_ledger.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.amazon_payments import AmazonPaymentParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Amazon Payment Reports, generate ledger and accounting reconciliation."
    )
    parser.add_argument(
        "--payments-dir",
        type=str,
        default="data/amazon/payment_reports",
        help="Directory containing monthly payment CSV files (default: data/amazon/payment_reports)",
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        default="data/output/analytics_reports",
        help="Directory containing generated analytics reports (default: data/output/analytics_reports)",
    )
    parser.add_argument(
        "--ledger-out",
        type=str,
        default="data/output/amazon_payments_ledger.csv",
        help="Output CSV for consolidated payments ledger",
    )
    parser.add_argument(
        "--reconciliation-out",
        type=str,
        default="data/output/amazon_accounting_reconciliation.csv",
        help="Output CSV for accounting reconciliation",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    payments_dir = Path(args.payments_dir)
    reports_dir = Path(args.reports_dir)
    ledger_out = Path(args.ledger_out)
    rec_out = Path(args.reconciliation_out)

    if not payments_dir.exists():
        log.error("Payments directory not found: %s", payments_dir)
        return 1

    print("=" * 70)
    print("🏦 RECONCILIADOR Y LIQUIDADOR DE PAGOS DE AMAZON (2016-2024)")
    print("=" * 70)

    payment_parser = AmazonPaymentParser(payments_dir=payments_dir)

    # 1. Parse and export payments ledger
    log.info("Procesando reportes de pago desde %s...", payments_dir)
    payment_parser.export_payments_ledger_csv(ledger_out)
    df_ledger = payment_parser.generate_payments_ledger_df()

    # 2. Reconcile against analytics reports
    log.info("Reconciliando pagos contra reportes analíticos en %s...", reports_dir)
    df_rec = payment_parser.reconcile_with_analytics_reports(reports_dir)
    payment_parser.export_reconciliation_csv(reports_dir, rec_out)

    # 3. Print accounting audit summary
    total_records = len(df_ledger)
    paid_records = df_ledger[df_ledger["status"].str.lower().isin(["paid", "pagado"])]
    
    total_cash_eur = paid_records[paid_records["payment_currency"] == "EUR"]["payment_amount"].sum()
    total_cash_usd = paid_records[paid_records["payment_currency"] == "USD"]["payment_amount"].sum()
    total_tax_usd = df_rec["tax_withheld_usd"].sum()
    total_payments_accrued_usd = df_rec["payments_accrued_usd"].sum()
    total_reported_rev_usd = df_rec["reported_revenue_usd"].sum()
    total_views = df_rec["reported_views"].sum()
    total_hours = df_rec["reported_minutes"].sum() / 60.0

    cat_counts = df_rec["reconciliation_category"].value_counts().to_dict()

    print("\n" + "=" * 70)
    print("📊 RESUMEN EJECUTIVO DE AUDITORÍA CONTABLE")
    print("=" * 70)
    print(f"📁 Transacciones de pago procesadas:  {total_records} registros")
    print(f"💰 Cobrado efectivo en Banco (EUR):    €{total_cash_eur:,.2f}")
    print(f"💵 Cobrado efectivo en Banco (USD):    ${total_cash_usd:,.2f}")
    print(f"🏛️ Retención fiscal IRS (EE.UU.):      ${total_tax_usd:,.2f} USD")
    print("-" * 70)
    print(f"📈 Total Regalías Devengadas (Pagos):  ${total_payments_accrued_usd:,.2f} USD")
    print(f"🎬 Total Ingresos en Analytics:        ${total_reported_rev_usd:,.2f} USD")
    print(f"👁️ Total Consumo:                      {total_views:,.0f} vistas ({total_hours:,.1f} horas)")
    print("-" * 70)
    print("🔍 Desglose de Reconciliación Mensual:")
    for cat, count in sorted(cat_counts.items()):
        print(f"   • {cat:<22}: {count:>3} meses")
    print("=" * 70)
    print(f"\n✅ Libro de pagos exportado en:       {ledger_out}")
    print(f"✅ Informe de reconciliación en:      {rec_out}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
