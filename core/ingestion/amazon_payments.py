"""Parser and reconciliation engine for Amazon Payment Reports (Liquidaciones Bancarias).

Parses the 108 official monthly payment reports (2016 to 2024), extracting
exact accrued royalties, bank settlement amounts, withholding taxes, and effective
FX rates applied by Amazon's banking partners.
"""

from __future__ import annotations

import csv
import glob
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from core.ingestion.amazon_historical import (
    FX_RATES,
    convert_currency_to_usd,
    parse_numeric_float,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AmazonPaymentRecord:
    payment_date: Optional[date]
    status: str
    sales_period_start: Optional[date]
    sales_period_end: Optional[date]
    sales_month: str
    accrued_royalty: float
    accrued_currency: str
    tax_withholding: float
    adjustments: float
    net_earnings: float
    fx_rate: Optional[float]
    payment_amount: float
    payment_currency: str
    source_file: str
    accrued_usd: float


def parse_payment_date_str(val: Optional[str]) -> Optional[date]:
    """Parses date string formatted as '%B %d, %Y' (e.g. 'August 29, 2016')."""
    if not val:
        return None
    cleaned = str(val).strip()
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%B %d, %Y").date()
    except ValueError:
        try:
            return datetime.fromisoformat(cleaned).date()
        except ValueError:
            return None


def derive_sales_month(start_date: date, end_date: date) -> str:
    """Derives the canonical sales month (YYYY-MM) from start and end dates using midpoint."""
    midpoint = start_date + (end_date - start_date) // 2
    return midpoint.strftime("%Y-%m")


class AmazonPaymentParser:
    """Parses Amazon Payment Reports into structured accounting records."""

    def __init__(self, payments_dir: Path | str) -> None:
        self.payments_dir = Path(payments_dir)

    def parse_file(self, csv_path: Path) -> List[AmazonPaymentRecord]:
        """Parses a single payment report CSV file (bilingual English / Spanish)."""
        records: List[AmazonPaymentRecord] = []
        if not csv_path.exists():
            return records

        with csv_path.open("r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_date_str = (row.get("Payment date") or row.get("Fecha de pago") or "").strip()
                s_start_str = (
                    row.get("Sales period start date")
                    or row.get("Fecha de inicio del período de ventas")
                    or ""
                ).strip()
                s_end_str = (
                    row.get("Sales period end date")
                    or row.get("Fecha límite del período de ventas")
                    or ""
                ).strip()

                status = (row.get("Status") or row.get("Estado") or "").strip()
                acc_curr = (
                    row.get("Accrued Royalty Currency")
                    or row.get("Divisa de las regalías devengadas")
                    or row.get("Monedas acumuladas por derecho de autor")
                    or "USD"
                ).strip().upper()

                p_date = parse_payment_date_str(p_date_str)
                s_start = parse_payment_date_str(s_start_str)
                s_end = parse_payment_date_str(s_end_str)

                if s_start and s_end:
                    sales_month = derive_sales_month(s_start, s_end)
                elif p_date:
                    # Fallback Net-60: payment date minus ~2 months
                    fallback_dt = p_date - timedelta(days=60)
                    sales_month = fallback_dt.strftime("%Y-%m")
                else:
                    continue

                acc_royalty = parse_numeric_float(
                    row.get("Accrued Royalty")
                    or row.get("Regalías devengadas")
                    or row.get("Regalías acumuladas"),
                    0.0,
                )
                tax = parse_numeric_float(
                    row.get("Tax Withholding") or row.get("Retención de impuestos"), 0.0
                )
                adj = parse_numeric_float(
                    row.get("Adjustments") or row.get("Ajustes"), 0.0
                )
                net = parse_numeric_float(
                    row.get("Net Earnings") or row.get("Ganancias netas"), acc_royalty
                )

                fx_val = row.get("FX Rate") or row.get("Tipo de cambio") or row.get("Tasa FX")
                fx_rate = parse_numeric_float(fx_val, 0.0) if fx_val else None

                payment = parse_numeric_float(
                    row.get("Payment") or row.get("Pago"), 0.0
                )
                pay_curr = (
                    row.get("Payment Currency")
                    or row.get("Divisa de pago")
                    or row.get("Monedas de pagos")
                    or "EUR"
                ).strip().upper()

                acc_usd = convert_currency_to_usd(acc_royalty, acc_curr)

                records.append(
                    AmazonPaymentRecord(
                        payment_date=p_date,
                        status=status,
                        sales_period_start=s_start,
                        sales_period_end=s_end,
                        sales_month=sales_month,
                        accrued_royalty=acc_royalty,
                        accrued_currency=acc_curr,
                        tax_withholding=tax,
                        adjustments=adj,
                        net_earnings=net,
                        fx_rate=fx_rate,
                        payment_amount=payment,
                        payment_currency=pay_curr,
                        source_file=csv_path.name,
                        accrued_usd=round(acc_usd, 4),
                    )
                )

        return records

    def parse_all_payment_reports(self) -> List[AmazonPaymentRecord]:
        """Parses all CSV files in the payment reports directory."""
        all_records: List[AmazonPaymentRecord] = []
        if not self.payments_dir.exists():
            log.warning("Payments directory %s does not exist", self.payments_dir)
            return all_records

        for csv_file in sorted(self.payments_dir.glob("*.csv")):
            recs = self.parse_file(csv_file)
            all_records.extend(recs)

        log.info(
            "Parsed %d payment records from %d files in %s",
            len(all_records),
            len(list(self.payments_dir.glob("*.csv"))),
            self.payments_dir,
        )
        return all_records

    def generate_payments_ledger_df(self) -> pd.DataFrame:
        """Converts all payment records into a consolidated DataFrame."""
        records = self.parse_all_payment_reports()
        if not records:
            return pd.DataFrame()

        rows = []
        for r in records:
            rows.append(
                {
                    "sales_month": r.sales_month,
                    "payment_date": r.payment_date.isoformat() if r.payment_date else "",
                    "status": r.status,
                    "accrued_royalty": r.accrued_royalty,
                    "accrued_currency": r.accrued_currency,
                    "tax_withholding": r.tax_withholding,
                    "adjustments": r.adjustments,
                    "net_earnings": r.net_earnings,
                    "fx_rate": r.fx_rate if r.fx_rate is not None else "",
                    "payment_amount": r.payment_amount,
                    "payment_currency": r.payment_currency,
                    "accrued_usd": r.accrued_usd,
                    "sales_period_start": r.sales_period_start.isoformat() if r.sales_period_start else "",
                    "sales_period_end": r.sales_period_end.isoformat() if r.sales_period_end else "",
                    "source_file": r.source_file,
                }
            )

        df = pd.DataFrame(rows)
        # Sort chronologically by sales_month and payment_date
        df.sort_values(by=["sales_month", "payment_date", "accrued_currency"], inplace=True)
        return df

    def export_payments_ledger_csv(self, output_path: Path | str) -> Path:
        """Exports the consolidated payment records to CSV."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df = self.generate_payments_ledger_df()
        df.to_csv(str(out), index=False, encoding="utf-8")
        log.info("Saved Amazon payments ledger to %s (%d rows)", out.name, len(df))
        return out

    def reconcile_with_analytics_reports(
        self, analytics_reports_dir: Path | str
    ) -> pd.DataFrame:
        """Reconciles analytics revenue against official bank payment reports month by month.

        Filters out 'Global' region rows in analytics reports to avoid double-counting.
        """
        rep_dir = Path(analytics_reports_dir)
        df_payments = self.generate_payments_ledger_df()

        # Group payments by sales_month
        pay_summary: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "accrued_usd": 0.0,
                "bank_cash_eur": 0.0,
                "bank_cash_usd": 0.0,
                "tax_withheld_usd": 0.0,
                "statuses": set(),
                "currencies": set(),
            }
        )

        if not df_payments.empty:
            for _, r in df_payments.iterrows():
                sm = str(r["sales_month"]).strip()
                if not sm:
                    continue
                acc_usd = float(r.get("accrued_usd") or 0.0)
                status = str(r.get("status") or "").strip()
                pay_amt = float(r.get("payment_amount") or 0.0)
                pay_curr = str(r.get("payment_currency") or "").strip().upper()
                acc_curr = str(r.get("accrued_currency") or "").strip().upper()
                tax_amt = float(r.get("tax_withholding") or 0.0)
                tax_usd = convert_currency_to_usd(tax_amt, acc_curr)

                entry = pay_summary[sm]
                entry["accrued_usd"] += acc_usd
                entry["tax_withheld_usd"] += tax_usd
                entry["statuses"].add(status)
                entry["currencies"].add(acc_curr)

                # Only count bank cash if paid / pagado
                if status.lower() in ("paid", "pagado"):
                    if pay_curr == "EUR":
                        entry["bank_cash_eur"] += pay_amt
                    elif pay_curr == "USD":
                        entry["bank_cash_usd"] += pay_amt

        # Scan all analytics reports in directory
        all_months: Set[str] = set(pay_summary.keys())
        rep_files: Dict[str, Path] = {}
        month_regex = re.compile(r"analytics_reports_(\d{2})_(\d{4})\.csv")

        if rep_dir.exists():
            for p in sorted(rep_dir.glob("analytics_reports_*.csv")):
                match = month_regex.match(p.name)
                if match:
                    mm, yyyy = match.group(1), match.group(2)
                    sm = f"{yyyy}-{mm}"
                    rep_files[sm] = p
                    all_months.add(sm)

        rows: List[Dict[str, Any]] = []
        for sm in sorted(all_months):
            p_file = rep_files.get(sm)
            rep_views = 0
            rep_minutes = 0.0
            rep_rev = 0.0
            rep_svod = 0.0
            rep_tvod = 0.0

            if p_file and p_file.exists():
                try:
                    df_rep = pd.read_csv(p_file, dtype=str)
                    # Filter out Global region summary to avoid 2x duplication
                    df_terr = df_rep[df_rep["region"] != "Global"]
                    if not df_terr.empty:
                        rep_views = int(pd.to_numeric(df_terr["views"], errors="coerce").fillna(0).sum())
                        rep_minutes = float(pd.to_numeric(df_terr["minutes_streamed"], errors="coerce").fillna(0.0).sum())
                        rep_rev = float(pd.to_numeric(df_terr["revenue"], errors="coerce").fillna(0.0).sum())
                        rep_svod = float(pd.to_numeric(df_terr.get("revenue_svod", 0.0), errors="coerce").fillna(0.0).sum())
                        rep_tvod = float(pd.to_numeric(df_terr.get("revenue_tvod", 0.0), errors="coerce").fillna(0.0).sum())
                except Exception as exc:
                    log.warning("Failed parsing analytics report for %s: %s", sm, exc)

            p_data = pay_summary.get(sm, {
                "accrued_usd": 0.0,
                "bank_cash_eur": 0.0,
                "bank_cash_usd": 0.0,
                "tax_withheld_usd": 0.0,
                "statuses": set(),
                "currencies": set(),
            })

            pay_accrued = p_data["accrued_usd"]
            cash_eur = p_data["bank_cash_eur"]
            cash_usd = p_data["bank_cash_usd"]
            tax_usd = p_data["tax_withheld_usd"]
            statuses = p_data["statuses"]

            if not statuses:
                p_status = "NO_PAYMENT_RECORD"
            elif any(s.lower() in ("paid", "pagado") for s in statuses) and any(s.lower() in ("failed", "falló", "in progress") for s in statuses):
                p_status = "PARTIAL"
            elif all(s.lower() in ("paid", "pagado") for s in statuses):
                p_status = "PAID"
            else:
                p_status = "FAILED/PENDING"

            variance = pay_accrued - rep_rev
            variance_pct = (variance / rep_rev * 100.0) if rep_rev > 0 else 0.0

            # Classification
            if rep_rev > 0 and (abs(variance) <= 1.0 or abs(variance_pct) <= 0.1):
                category = "EXACT_MATCH"
            elif rep_rev > 0 and abs(variance_pct) <= 5.0:
                category = "CLOSE_MATCH"
            elif rep_views > 0 and rep_rev == 0 and pay_accrued > 0:
                category = "TELEMETRY_ONLY"
            elif pay_accrued == 0 and rep_rev > 0:
                category = "PENDING_SETTLEMENT"
            elif rep_rev == 0 and rep_views == 0 and pay_accrued == 0:
                category = "NO_ACTIVITY"
            else:
                category = "DISCREPANCY"

            rows.append(
                {
                    "sales_month": sm,
                    "reported_views": rep_views,
                    "reported_minutes": round(rep_minutes, 2),
                    "reported_revenue_usd": round(rep_rev, 4),
                    "reported_svod_usd": round(rep_svod, 4),
                    "reported_tvod_usd": round(rep_tvod, 4),
                    "payments_accrued_usd": round(pay_accrued, 4),
                    "bank_cash_eur_paid": round(cash_eur, 2),
                    "bank_cash_usd_paid": round(cash_usd, 2),
                    "tax_withheld_usd": round(tax_usd, 4),
                    "variance_usd": round(variance, 4),
                    "variance_pct": round(variance_pct, 4),
                    "payment_status": p_status,
                    "reconciliation_category": category,
                }
            )

        df = pd.DataFrame(rows)
        df.sort_values(by="sales_month", inplace=True)
        return df

    def export_reconciliation_csv(
        self, analytics_reports_dir: Path | str, output_path: Path | str
    ) -> Path:
        """Exports the accounting reconciliation report to CSV."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df = self.reconcile_with_analytics_reports(analytics_reports_dir)
        df.to_csv(str(out), index=False, encoding="utf-8")
        log.info("Saved Amazon accounting reconciliation to %s (%d rows)", out.name, len(df))
        return out
