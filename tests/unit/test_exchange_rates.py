"""Unit tests for the centralized exchange rates (FX) system."""

import pytest
import pandas as pd
from core.domain.exchange_rates import (
    load_raw_rates,
    save_raw_rates,
    get_rates_dataframe,
    save_rates_dataframe,
    get_cny_rate,
    get_eur_rate,
    convert_cny_to_usd,
    convert_usd_to_eur,
    convert_currency,
    ANNUAL_DEFAULTS,
)


def test_defaults_loaded():
    data = load_raw_rates()
    assert "monthly" in data
    assert "annual" in data
    assert "2021" in data["annual"]
    assert data["annual"]["2021"]["cny_per_usd"] == 6.45


def test_get_cny_rate():
    # Annual lookup
    assert get_cny_rate("2021") == 6.45
    assert get_cny_rate("2024") == 7.19
    # Monthly lookup
    assert get_cny_rate("2021-05") == 6.45
    assert get_cny_rate("2024-03-15") == 7.19


def test_get_eur_rate():
    assert get_eur_rate("2021") == 0.845
    assert get_eur_rate("2024-01") == 0.924


def test_convert_cny_to_usd():
    usd, rate = convert_cny_to_usd(645.0, "2021-05")
    assert rate == 6.45
    assert round(usd, 2) == 100.0


def test_convert_usd_to_eur():
    eur, rate = convert_usd_to_eur(100.0, "2024-01")
    assert rate == 0.924
    assert round(eur, 2) == 92.40


def test_convert_currency_cross():
    # CNY to EUR
    eur = convert_currency(645.0, "CNY", "EUR", "2021")
    # 645 CNY = 100 USD. 100 USD * 0.845 = 84.5 EUR
    assert round(eur, 2) == 84.50

    # Same currency
    assert convert_currency(123.45, "USD", "USD", "2024") == 123.45


def test_rates_dataframe_roundtrip():
    df_mon = get_rates_dataframe(mode="monthly")
    assert not df_mon.empty
    assert "period" in df_mon.columns
    assert "cny_per_usd" in df_mon.columns
    assert "eur_per_usd" in df_mon.columns

    df_ann = get_rates_dataframe(mode="annual")
    assert not df_ann.empty
    assert len(df_ann) >= 10
