"""Regression tests for cron scripts, aggregation platform filters, and monthly closure dates."""

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

from core.domain.aggregation_filters import (
    build_events_match_query,
    build_summary_cleanup_filter,
)
from core.ingestion.update_service import run_amazon_update

_EM_SRC = str(Path(__file__).resolve().parent.parent / "apps" / "event_manager" / "src")
if _EM_SRC not in sys.path:
    sys.path.insert(0, _EM_SRC)

from application.yt_analytics_events_service import YtAnalyticsEventsService  # noqa: E402


def test_events_match_query_youtube_uses_real_event_type():
    q = build_events_match_query(platform="youtube", run_all=True)
    assert q == {"metadata.event_type": "youtube.video.performance_recorded"}


def test_events_match_query_amazon_includes_all_variants():
    q = build_events_match_query(platform="amazon", year=2021)
    assert q["metadata.event_type"] == {
        "$in": [
            "amazon.video.performance_recorded",
            "amazon.video.performance_svod",
            "amazon.video.performance_tvod",
        ]
    }
    assert q["payload.date"] == {"$gte": "2021-01-01", "$lte": "2021-12-31"}


def test_events_match_query_china_and_incremental_windows():
    ref = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)

    for plat in ("tencent", "youku", "iqiyi"):
        q = build_events_match_query(platform=plat, run_all=True)
        assert q == {"metadata.event_type": f"{plat}.video.performance_recorded"}

    q_60d = build_events_match_query(platform="youtube", incremental_window="60d", now_utc=ref)
    assert q_60d["payload.date"] == {"$gte": "2026-09-13"}

    q_2y = build_events_match_query(platform="youtube", incremental_window="2y", now_utc=ref)
    assert q_2y["payload.date"] == {"$gte": "2025-01-01"}


def test_summary_cleanup_filter_only_triggers_for_complete_amazon_rebuilds():
    # Incremental or non-Amazon rebuilds must NEVER purge existing summaries
    assert build_summary_cleanup_filter(platform="amazon", year=None, run_all=False) is None
    assert build_summary_cleanup_filter(platform="youtube", year=2025, run_all=False) is None
    assert build_summary_cleanup_filter(platform="youtube", year=None, run_all=True) is None
    assert build_summary_cleanup_filter(platform=None, year=None, run_all=True) is None

    assert build_summary_cleanup_filter(platform="amazon", year=2024, time_field="_id.month") == {
        "_id.platform": "amazon",
        "_id.month": {"$regex": "^2024"},
    }
    assert build_summary_cleanup_filter(platform="amazon", year=2024, time_field="_id.year") == {
        "_id.platform": "amazon",
        "_id.year": "2024",
    }
    assert build_summary_cleanup_filter(platform="amazon", run_all=True) == {
        "_id.platform": "amazon",
    }


def test_monthly_territory_end_date_caps_at_closed_previous_month():
    # Cron running on Dec 2 must stop at Nov 30, never include Dec 1
    end = YtAnalyticsEventsService.resolve_target_end_date(
        by_country=True,
        today_utc=date(2026, 12, 2),
    )
    assert end == date(2026, 11, 30)

    # Year boundary: running on Jan 2 must stop at Dec 31 of previous year
    end_jan = YtAnalyticsEventsService.resolve_target_end_date(
        by_country=True,
        today_utc=date(2027, 1, 2),
    )
    assert end_jan == date(2026, 12, 31)

    # Full-year backfill for current year must still cap at last closed month
    end_override_current = YtAnalyticsEventsService.resolve_target_end_date(
        by_country=True,
        end_date_override="2026-12-31",
        today_utc=date(2026, 11, 12),
    )
    assert end_override_current == date(2026, 10, 31)

    # Full-year backfill for past year preserves Dec 31
    end_override_past = YtAnalyticsEventsService.resolve_target_end_date(
        by_country=True,
        end_date_override="2025-12-31",
        today_utc=date(2026, 11, 12),
    )
    assert end_override_past == date(2025, 12, 31)


def test_daily_global_end_date_uses_yesterday():
    end = YtAnalyticsEventsService.resolve_target_end_date(
        by_country=False,
        today_utc=date(2026, 12, 2),
    )
    assert end == date(2026, 12, 1)


def test_cron_scripts_syntax_and_youtube_platform_isolation():
    root = Path(__file__).resolve().parent.parent
    for script_name in ("cron_daily_sync.sh", "cron_monthly_sync.sh", "cron_amazon_sync.sh"):
        script_path = root / "scripts" / script_name
        res = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr

    daily_txt = (root / "scripts" / "cron_daily_sync.sh").read_text(encoding="utf-8")
    monthly_txt = (root / "scripts" / "cron_monthly_sync.sh").read_text(encoding="utf-8")
    for txt in (daily_txt, monthly_txt):
        assert "scripts/build_monthly_aggregations.py --platform youtube" in txt
        assert "scripts/build_yearly_aggregations.py --platform youtube" in txt


def test_amazon_update_does_not_fallthrough_to_historical_when_incremental_fails(tmp_path, monkeypatch):
    perf_dir = tmp_path / "data" / "amazon" / "performance" / "KLQ49_2026-08_VOD"
    perf_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "core.ingestion.update_service.get_update_lock_file",
        lambda _data_dir=None: tmp_path / ".amazon_update.lock",
    )

    calls = []

    def fake_run(cmd, **kwargs):
        cmd_strs = [str(c) for c in cmd]
        calls.append(cmd_strs)
        if any("run_incremental.py" in c for c in cmd_strs):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom incremental")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("core.ingestion.update_service.subprocess.run", fake_run)

    import core.ingestion.update_service as us
    monkeypatch.setattr(us, "__file__", str(tmp_path / "core" / "ingestion" / "update_service.py"))
    sample_month = "2026-08"

    result = run_amazon_update(target_months=[sample_month], sync_drive=False)

    assert result["success"] is False
    assert result["failed_months"] == [sample_month]
    assert result["processed_months"] == []
    assert any("run_incremental.py" in " ".join(c) for c in calls)
    assert not any("process_historical_amazon.py" in " ".join(c) for c in calls)
    assert any(
        "build_yearly_aggregations.py" in " ".join(c) and "--platform" in c and "amazon" in c
        for c in calls
    )
