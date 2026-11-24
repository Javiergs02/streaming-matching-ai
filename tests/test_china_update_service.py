"""Unit tests for China update service (Tencent, Youku, iQIYI)."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.ingestion.china_update_service import (
    get_available_china_platforms,
    get_china_lock_file,
    is_china_update_in_progress,
    run_china_update,
    sync_china_drive_folders,
    PLATFORM_MAP
)


def test_get_available_china_platforms():
    platforms = get_available_china_platforms()
    assert isinstance(platforms, list)
    assert len(platforms) == 4
    assert "Todas las plataformas (Tencent, Youku, iQIYI)" in platforms
    assert "Tencent Video" in platforms
    assert "Youku" in platforms
    assert "iQIYI" in platforms


def test_is_china_update_in_progress(tmp_path):
    busy, info = is_china_update_in_progress(tmp_path)
    assert busy is False
    assert info is None

    lock_file = get_china_lock_file(tmp_path)
    assert lock_file.name == ".china_update.lock"


def test_sync_china_drive_folders_unconfigured(monkeypatch):
    # Ensure env vars are not set
    monkeypatch.delenv("CHINA_DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("TENCENT_DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("YOUKU_DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("IQIYI_DRIVE_FOLDER_ID", raising=False)

    logs = []
    res = sync_china_drive_folders(["tencent"], log_callback=logs.append)
    assert res["tencent"]["configured"] is False
    assert any("Google Drive no configurado" in log for log in logs)


@patch("subprocess.Popen")
def test_run_china_update_mocked(mock_popen, tmp_path, monkeypatch):
    monkeypatch.setattr("core.ingestion.china_update_service.get_china_lock_file", lambda d=None: tmp_path / ".china_update.lock")

    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = ["• Insertados 100 eventos\n", ""]
    mock_proc.wait.return_value = None
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    logs = []
    res = run_china_update(
        platform_choice="Tencent Video",
        sync_drive=False,
        dry_run=True,
        log_callback=logs.append
    )

    assert res["success"] is True
    assert "tencent" in res["processed_platforms"]
    assert any("TENCENT" in l for l in logs)
