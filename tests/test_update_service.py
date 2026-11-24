"""Unit tests for Amazon Ingestion Update Service."""

import pytest
from pathlib import Path
from core.ingestion.update_service import get_available_amazon_months, get_default_update_months


def test_get_available_amazon_months(tmp_path):
    data_dir = tmp_path / "data" / "amazon"
    perf_dir = data_dir / "performance"
    perf_dir.mkdir(parents=True)
    (perf_dir / "KLQ49_2025-01_VOD_PV-Content-Performance-Report").mkdir()
    (perf_dir / "KLQ49_2025-02_VOD_PV-Content-Performance-Report").mkdir()

    hist_dir = data_dir / "historical_revenue" / "monthly_reports"
    hist_dir.mkdir(parents=True)
    (hist_dir / "2024-12.csv").write_text("header\n", encoding="utf-8")

    months = get_available_amazon_months(data_dir)
    assert months == ["2024-12", "2025-01", "2025-02"]


def test_get_default_update_months(tmp_path):
    data_dir = tmp_path / "data" / "amazon"
    perf_dir = data_dir / "performance"
    perf_dir.mkdir(parents=True)
    for m in ["2025-01", "2025-02", "2025-03", "2025-04"]:
        (perf_dir / f"KLQ49_{m}_VOD_PV").mkdir()

    defaults = get_default_update_months(n_months=3, data_dir=data_dir)
    assert defaults == ["2025-02", "2025-03", "2025-04"]

    defaults_1 = get_default_update_months(n_months=1, data_dir=data_dir)
    assert defaults_1 == ["2025-04"]


def test_run_amazon_update_signature():
    """Verify that run_amazon_update has sync_drive=True by default."""
    import inspect
    from core.ingestion.update_service import run_amazon_update
    sig = inspect.signature(run_amazon_update)
    assert sig.parameters["sync_drive"].default is True


def test_update_lock_detection_and_concurrency(tmp_path):
    """Verifica que el bloqueo de archivo impida ejecuciones concurrentes simultáneas."""
    import fcntl
    from core.ingestion.update_service import (
        get_update_lock_file,
        is_update_in_progress,
        run_amazon_update,
    )

    lock_file = get_update_lock_file(tmp_path)
    assert lock_file.name == ".amazon_update.lock"

    # Initially no update is in progress
    in_prog, info = is_update_in_progress(tmp_path)
    assert in_prog is False

    # Simulate an active process holding the lock
    fd = open(lock_file, "w+")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    in_prog_active, info_active = is_update_in_progress(tmp_path)
    assert in_prog_active is True

    # Release lock
    fcntl.flock(fd, fcntl.LOCK_UN)
    fd.close()

    in_prog_after, _ = is_update_in_progress(tmp_path)
    assert in_prog_after is False


