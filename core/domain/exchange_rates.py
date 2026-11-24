"""Centralized Exchange Rates (FX) engine for multi-currency conversion.

Manages monthly and annual conversion rates between:
  - CNY (RMB ¥) and USD ($) [for Chinese platforms: Tencent, Youku, iQIYI]
  - USD ($) and EUR (€) [for global dashboard viewing in EUR or USD]

Supports user editing and persistence via config/exchange_rates.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "exchange_rates.json"

# Official IRS / Federal Reserve / ECB historical annual benchmarks
ANNUAL_DEFAULTS: Dict[str, Dict[str, float]] = {
    "2016": {"cny_per_usd": 6.73, "eur_per_usd": 0.903, "usd_per_eur": 1.107},
    "2017": {"cny_per_usd": 6.73, "eur_per_usd": 0.885, "usd_per_eur": 1.130},
    "2018": {"cny_per_usd": 6.62, "eur_per_usd": 0.847, "usd_per_eur": 1.181},
    "2019": {"cny_per_usd": 6.91, "eur_per_usd": 0.893, "usd_per_eur": 1.120},
    "2020": {"cny_per_usd": 6.90, "eur_per_usd": 0.876, "usd_per_eur": 1.142},
    "2021": {"cny_per_usd": 6.45, "eur_per_usd": 0.845, "usd_per_eur": 1.183},
    "2022": {"cny_per_usd": 6.73, "eur_per_usd": 0.950, "usd_per_eur": 1.053},
    "2023": {"cny_per_usd": 7.08, "eur_per_usd": 0.925, "usd_per_eur": 1.081},
    "2024": {"cny_per_usd": 7.19, "eur_per_usd": 0.924, "usd_per_eur": 1.082},
    "2025": {"cny_per_usd": 7.19, "eur_per_usd": 0.926, "usd_per_eur": 1.080},
    "2026": {"cny_per_usd": 7.19, "eur_per_usd": 0.926, "usd_per_eur": 1.080},
}

FALLBACK_CNY_PER_USD = 7.19
FALLBACK_EUR_PER_USD = 0.925


def _generate_default_monthly_rates() -> Dict[str, Dict[str, float]]:
    """Generates default monthly exchange rates for 2016-01 to 2026-12."""
    monthly: Dict[str, Dict[str, float]] = {}
    for year_str, ann in sorted(ANNUAL_DEFAULTS.items()):
        y = int(year_str)
        cny_base = ann["cny_per_usd"]
        eur_base = ann["eur_per_usd"]
        for m in range(1, 13):
            period = f"{y:04d}-{m:02d}"
            monthly[period] = {
                "cny_per_usd": round(cny_base, 4),
                "eur_per_usd": round(eur_base, 4),
                "usd_per_eur": round(1.0 / eur_base, 4) if eur_base > 0 else 1.08,
            }
    return monthly


def load_raw_rates() -> Dict[str, Any]:
    """Loads exchange rates JSON dictionary from disk or initializes defaults."""
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "monthly" in data and "annual" in data:
                    return data
        except Exception as e:
            log.warning("Could not read %s, reverting to defaults: %s", CONFIG_FILE, e)

    # Initialize default structure
    data = {
        "monthly": _generate_default_monthly_rates(),
        "annual": dict(ANNUAL_DEFAULTS),
    }
    save_raw_rates(data)
    return data


def save_raw_rates(data: Dict[str, Any]) -> None:
    """Saves exchange rates JSON dictionary to config/exchange_rates.json."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("Saved exchange rates to %s", CONFIG_FILE)
    except Exception as e:
        log.error("Failed to save exchange rates to %s: %s", CONFIG_FILE, e)


def get_rates_dataframe(mode: str = "monthly") -> pd.DataFrame:
    """Returns exchange rates as a pandas DataFrame for Streamlit st.data_editor.
    
    mode: 'monthly' returns YYYY-MM rows; 'annual' returns YYYY rows.
    """
    data = load_raw_rates()
    rows: List[Dict[str, Any]] = []

    if mode == "annual":
        ann = data.get("annual", ANNUAL_DEFAULTS)
        for year in sorted(ann.keys()):
            val = ann[year]
            cny = float(val.get("cny_per_usd", FALLBACK_CNY_PER_USD))
            eur = float(val.get("eur_per_usd", FALLBACK_EUR_PER_USD))
            usd_eur = round(1.0 / eur, 4) if eur > 0 else 1.08
            rows.append({
                "period": year,
                "cny_per_usd": cny,
                "eur_per_usd": eur,
                "usd_per_eur": usd_eur,
            })
    else:  # monthly
        mon = data.get("monthly", {})
        if not mon:
            mon = _generate_default_monthly_rates()
        for p in sorted(mon.keys()):
            val = mon[p]
            cny = float(val.get("cny_per_usd", FALLBACK_CNY_PER_USD))
            eur = float(val.get("eur_per_usd", FALLBACK_EUR_PER_USD))
            usd_eur = round(1.0 / eur, 4) if eur > 0 else 1.08
            rows.append({
                "period": p,
                "cny_per_usd": cny,
                "eur_per_usd": eur,
                "usd_per_eur": usd_eur,
            })

    df = pd.DataFrame(rows)
    return df


def save_rates_dataframe(df: pd.DataFrame, mode: str = "monthly") -> bool:
    """Saves edited DataFrame from Streamlit back to config/exchange_rates.json."""
    if df.empty:
        return False
    data = load_raw_rates()

    if mode == "annual":
        ann = data.get("annual", {})
        for _, row in df.iterrows():
            p = str(row["period"]).strip()
            cny = float(row.get("cny_per_usd") or FALLBACK_CNY_PER_USD)
            eur = float(row.get("eur_per_usd") or FALLBACK_EUR_PER_USD)
            ann[p] = {
                "cny_per_usd": round(cny, 4),
                "eur_per_usd": round(eur, 4),
                "usd_per_eur": round(1.0 / eur, 4) if eur > 0 else 1.08,
            }
        data["annual"] = ann
    else:
        mon = data.get("monthly", {})
        for _, row in df.iterrows():
            p = str(row["period"]).strip()
            cny = float(row.get("cny_per_usd") or FALLBACK_CNY_PER_USD)
            eur = float(row.get("eur_per_usd") or FALLBACK_EUR_PER_USD)
            mon[p] = {
                "cny_per_usd": round(cny, 4),
                "eur_per_usd": round(eur, 4),
                "usd_per_eur": round(1.0 / eur, 4) if eur > 0 else 1.08,
            }
        data["monthly"] = mon

    save_raw_rates(data)
    return True


def reset_to_defaults() -> None:
    """Resets exchange_rates.json back to initial historical defaults."""
    data = {
        "monthly": _generate_default_monthly_rates(),
        "annual": dict(ANNUAL_DEFAULTS),
    }
    save_raw_rates(data)


def parse_period_key(val: Any) -> Tuple[Optional[str], Optional[str]]:
    """Extracts (year_month, year) strings from date/datetime/string."""
    if val is None:
        return None, None
    if isinstance(val, (datetime, date)):
        ym = val.strftime("%Y-%m")
        y = val.strftime("%Y")
        return ym, y
    s = str(val).strip()
    m_ym = re.match(r"^(\d{4})[-/]?(\d{2})", s)
    if m_ym:
        ym = f"{m_ym.group(1)}-{m_ym.group(2)}"
        y = m_ym.group(1)
        return ym, y
    m_y = re.match(r"^(\d{4})", s)
    if m_y:
        y = m_y.group(1)
        return None, y
    return None, None


def get_cny_rate(period: Any = None) -> float:
    """Returns CNY/RMB per 1 USD for the given month or year."""
    ym, y = parse_period_key(period)
    data = load_raw_rates()

    # 1. Try exact monthly rate
    if ym and ym in data.get("monthly", {}):
        rate = data["monthly"][ym].get("cny_per_usd")
        if rate and float(rate) > 0:
            return float(rate)

    # 2. Try annual rate
    if y and y in data.get("annual", {}):
        rate = data["annual"][y].get("cny_per_usd")
        if rate and float(rate) > 0:
            return float(rate)

    # 3. Fallback to ANNUAL_DEFAULTS or global default
    if y:
        try:
            if int(y) < 2017:
                return ANNUAL_DEFAULTS["2017"]["cny_per_usd"]
        except (ValueError, TypeError):
            pass
        if y in ANNUAL_DEFAULTS:
            return ANNUAL_DEFAULTS[y]["cny_per_usd"]
    return FALLBACK_CNY_PER_USD


def get_eur_rate(period: Any = None) -> float:
    """Returns EUR per 1 USD for the given month or year (e.g. 0.925 -> $1 USD = 0.925 EUR)."""
    ym, y = parse_period_key(period)
    data = load_raw_rates()

    # 1. Try exact monthly rate
    if ym and ym in data.get("monthly", {}):
        rate = data["monthly"][ym].get("eur_per_usd")
        if rate and float(rate) > 0:
            return float(rate)

    # 2. Try annual rate
    if y and y in data.get("annual", {}):
        rate = data["annual"][y].get("eur_per_usd")
        if rate and float(rate) > 0:
            return float(rate)

    # 3. Fallback to ANNUAL_DEFAULTS or global default
    if y and y in ANNUAL_DEFAULTS:
        return ANNUAL_DEFAULTS[y]["eur_per_usd"]
    return FALLBACK_EUR_PER_USD


def convert_cny_to_usd(amount_cny: float, period: Any = None) -> Tuple[float, float]:
    """Converts CNY/RMB amount to USD. Returns (amount_usd, rate_cny_per_usd)."""
    if not amount_cny:
        return 0.0, get_cny_rate(period)
    rate = get_cny_rate(period)
    usd = float(amount_cny) / rate if rate > 0 else 0.0
    return usd, rate


def convert_usd_to_eur(amount_usd: float, period: Any = None) -> Tuple[float, float]:
    """Converts USD amount to EUR. Returns (amount_eur, rate_eur_per_usd)."""
    if not amount_usd:
        return 0.0, get_eur_rate(period)
    rate = get_eur_rate(period)
    eur = float(amount_usd) * rate
    return eur, rate


def convert_currency(
    amount: float,
    from_curr: str,
    to_curr: str,
    period: Any = None
) -> float:
    """Converts an amount between CNY, USD, and EUR for a given period."""
    if not amount:
        return 0.0
    val = float(amount)
    f = from_curr.strip().upper() if from_curr else "USD"
    t = to_curr.strip().upper() if to_curr else "USD"

    if f == t:
        return val

    # Normalise to USD first
    if f in ("CNY", "RMB"):
        usd = val / get_cny_rate(period)
    elif f == "EUR":
        eur_rate = get_eur_rate(period)
        usd = val / eur_rate if eur_rate > 0 else val * 1.08
    else:  # already USD or other treated as USD
        usd = val

    # Convert USD to target
    if t in ("CNY", "RMB"):
        return usd * get_cny_rate(period)
    elif t == "EUR":
        return usd * get_eur_rate(period)
    return usd
