"""
tests/unit/test_amazon_catalog.py

Unit tests for AmazonReferenceCatalog and metadata resolution.
"""

import pytest
from core.domain.amazon_catalog import AmazonReferenceCatalog, normalize_series_key


@pytest.fixture(scope="module")
def catalog():
    cat = AmazonReferenceCatalog.get_instance()
    assert cat.is_loaded, "AmazonReferenceCatalog should be loaded from data/reference/"
    return cat


def test_catalog_is_loaded(catalog):
    assert len(catalog._ids) >= 11000
    assert len(catalog._series) >= 550


def test_lookup_by_title_id(catalog):
    # Known Title ID from SERIE ID.xlsx
    entry = catalog.get_id("0018DM0YX4J")
    assert entry is not None
    assert entry["id"] == "0018DM0YX4J"
    assert entry["id_type"] == "title"
    assert entry["ip"] == "CC2CARL"
    assert entry["universe"] == "CARCITY2"
    assert entry["season_id"] == "M0JY6XC5HJ8"
    assert entry["series_id"] == "WHJ0HXHF7T7"
    assert entry["season_number"] == 2
    assert entry["language_code"] == "ES"


def test_lookup_by_season_id(catalog):
    # Known Season ID
    entry = catalog.get_id("M0JY6XC5HJ8")
    assert entry is not None
    assert entry["id_type"] in ("season", "title")
    assert entry["ip"] == "CC2CARL"
    assert entry["universe"] == "CARCITY2"


def test_lookup_by_series_id(catalog):
    # Known Series ID
    entry = catalog.get_id("WHJ0HXHF7T7")
    assert entry is not None
    assert entry["id_type"] in ("series", "title", "season")
    assert entry["ip"] == "CC2CARL"


def test_lookup_by_series_name_exact(catalog):
    # Exact Series Name
    series = catalog.get_series("A lavagem de Carros de Tom")
    assert series is not None
    assert series["ip"] == "TCW"
    assert series["global_ip"] == "Tom Car Wash"
    assert series["universe"] == "CARCITY"
    assert series["global_universe"] == "CARCITY"


def test_lookup_by_series_name_normalized(catalog):
    # Case insensitive and punctuation stripped
    series = catalog.get_series("a lavagem de carros de tom")
    assert series is not None
    assert series["ip"] == "TCW"

    # With accents variation
    series2 = catalog.get_series("À lavagem de Carros de Tom!")
    assert series2 is not None
    assert series2["ip"] == "TCW"


def test_resolve_cascade_title_id_priority(catalog):
    # When title_id is present, it takes highest precedence
    res = catalog.resolve(
        amazon_id="0018DM0YX4J",
        season_id="DIFFERENT_SEASON",
        series_name="Different Series",
    )
    assert res is not None
    assert res["id"] == "0018DM0YX4J"
    assert res["ip"] == "CC2CARL"
    assert res["match_level"] == "id_title"


def test_resolve_cascade_season_id_fallback(catalog):
    # When amazon_id is unknown or None, fallback to season_id
    res = catalog.resolve(
        amazon_id="NONEXISTENT_ASIN_123",
        season_id="M0JY6XC5HJ8",
        series_name="Different Series",
    )
    assert res is not None
    assert res["ip"] == "CC2CARL"
    assert res["match_level"] == "season_id"


def test_resolve_cascade_series_name_fallback(catalog):
    # When all IDs are unknown or None, fallback to series_name
    res = catalog.resolve(
        amazon_id="NONEXISTENT_1",
        season_id="NONEXISTENT_2",
        series_id="NONEXISTENT_3",
        series_name="A lavagem de Carros de Tom",
    )
    assert res is not None
    assert res["ip"] == "TCW"
    assert res["universe"] == "CARCITY"
    assert res["match_level"] == "series_name"


def test_resolve_unknown(catalog):
    res = catalog.resolve(
        amazon_id="TOTALLY_UNKNOWN_XYZ",
        series_name="Nonexistent alien show 12345",
    )
    assert res is None


def test_empty_and_none_inputs(catalog):
    assert catalog.get_id(None) is None
    assert catalog.get_id("") is None
    assert catalog.get_series(None) is None
    assert catalog.get_series("") is None
    assert catalog.resolve() is None
