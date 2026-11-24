import os
import pytest
from pathlib import Path
from core.ingestion.youtube_update_service import (
    get_available_youtube_years,
    get_default_youtube_months,
    get_youtube_lock_file,
    is_youtube_update_in_progress
)


def test_get_available_youtube_years():
    years = get_available_youtube_years()
    assert isinstance(years, list)
    assert len(years) >= 9
    assert "2016" in years
    assert "2024" in years
    assert "2025" in years


def test_get_default_youtube_months():
    months = get_default_youtube_months(3)
    assert isinstance(months, list)
    assert len(months) == 3
    for m in months:
        assert len(m) == 7
        assert "-" in m
        y, mon = m.split("-")
        assert len(y) == 4 and y.isdigit()
        assert len(mon) == 2 and mon.isdigit()
        assert 1 <= int(mon) <= 12


def test_is_youtube_update_in_progress(tmp_path):
    # Testing with clean tmp_path
    busy, info = is_youtube_update_in_progress(tmp_path)
    assert busy is False
    assert info is None

    # Testing lock file creation
    lock_file = get_youtube_lock_file(tmp_path)
    assert lock_file.name == ".youtube_update.lock"

