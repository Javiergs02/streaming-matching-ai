import pytest
from unittest.mock import MagicMock
import pandas as pd
from datetime import date
from apps.event_manager.src.domain.models import VideoPerformanceEvent
from apps.event_manager.src.infrastructure.adapters.youtube_video_fetcher import YoutubeVideoFetcher


def test_video_performance_event_geography():
    # Default geography
    event_default = VideoPerformanceEvent(
        video_id="vid_123",
        platform="youtube",
        date="2024-01-01",
        estimated_revenue=10.5,
        extra_metrics={"views": 100}
    )
    assert event_default.geography == "Unknown Geo"
    assert event_default.video_id == "vid_123"
    assert event_default.estimated_revenue == 10.5

    # Explicit country geography
    event_country = VideoPerformanceEvent(
        video_id="vid_456",
        platform="youtube",
        date="2024-01-01",
        estimated_revenue=25.0,
        geography="US",
        extra_metrics={"views": 500}
    )
    assert event_country.geography == "US"


def test_get_monthly_intervals():
    intervals = YoutubeVideoFetcher._get_monthly_intervals("2024-01-15", "2024-03-10")
    assert len(intervals) == 3
    
    # Month 1: Jan
    assert intervals[0] == ("2024-01-01", "2024-01-15", "2024-01-31")
    # Month 2: Feb (leap year 2024 -> 29 days)
    assert intervals[1] == ("2024-02-01", "2024-02-01", "2024-02-29")
    # Month 3: Mar
    assert intervals[2] == ("2024-03-01", "2024-03-01", "2024-03-10")


def test_fetch_monthly_analysis_by_country_mock():
    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    cms_id = "TEST_CMS"

    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, cms_id)

    # Setup mock return from YouTube Analytics API
    mock_query = MagicMock()
    mock_analytics_client.reports.return_value.query.return_value = mock_query
    mock_query.execute.return_value = {
        "columnHeaders": [
            {"name": "video"},
            {"name": "country"},
            {"name": "views"},
            {"name": "likes"},
            {"name": "comments"},
            {"name": "estimatedMinutesWatched"},
            {"name": "estimatedRevenue"},
            {"name": "estimatedAdRevenue"},
            {"name": "cpm"},
            {"name": "adImpressions"}
        ],
        "rows": [
            ["vid_1", "US", 1000, 50, 10, 3000, 15.5, 15.0, 2.5, 2000],
            ["vid_1", "MX", 500, 20, 5, 1200, 3.2, 3.0, 1.2, 800]
        ]
    }

    events = fetcher.fetch_monthly_analysis_by_country(["vid_1"], "2024-01-01", "2024-01-31")

    assert len(events) == 2
    ev_us = events[0]
    assert ev_us.video_id == "vid_1"
    assert ev_us.geography == "US"
    assert ev_us.date == "2024-01-01"
    assert ev_us.estimated_revenue == 15.5
    assert ev_us.extra_metrics["views"] == 1000

    ev_mx = events[1]
    assert ev_mx.video_id == "vid_1"
    assert ev_mx.geography == "MX"
    assert ev_mx.date == "2024-01-01"
    assert ev_mx.estimated_revenue == 3.2
    assert ev_mx.extra_metrics["views"] == 500


def test_dashboard_youtube_geography_merge_precedence():
    # Simulated Mongo performance data from monthly territory ingestion
    df_perf = pd.DataFrame([
        {"video_id": "vid_1", "month": "2024-01", "geography": "US", "revenue": 10.0, "views": 100},
        {"video_id": "vid_1", "month": "2024-01", "geography": "MX", "revenue": 5.0, "views": 50},
        {"video_id": "vid_2", "month": "2024-01", "geography": "Unknown Geo", "revenue": 2.0, "views": 20},
    ])

    # Simulated PostgreSQL metadata (channel geography)
    df_meta = pd.DataFrame([
        {"video_id": "vid_1", "geography": "ES", "series_name": "Series A"},
        {"video_id": "vid_2", "geography": "FR", "series_name": "Series B"},
    ])

    # Replicate merge logic from business_reports.py: direct consumption territory from MongoDB
    df_meta_clean = df_meta.drop(columns=['geography', 'meta_geography'], errors='ignore')
    df_master = pd.merge(df_perf, df_meta_clean, on=['video_id'], how='left')
    df_master['geography'] = df_master['geography'].fillna('Unknown Geo')

    # vid_1: Real viewer territories preserved without being overwritten by channel country ES
    v1_us = df_master[(df_master['video_id'] == 'vid_1') & (df_master['geography'] == 'US')].iloc[0]
    v1_mx = df_master[(df_master['video_id'] == 'vid_1') & (df_master['geography'] == 'MX')].iloc[0]
    assert v1_us['geography'] == "US"
    assert v1_mx['geography'] == "MX"

    # vid_2: Unknown Geo stays Unknown Geo
    v2 = df_master[df_master['video_id'] == 'vid_2'].iloc[0]
    assert v2['geography'] == "Unknown Geo"


def test_dashboard_youtube_daily_mode_geography_global():
    df_perf = pd.DataFrame([
        {"video_id": "vid_1", "month": "2024-01-15", "geography": "Global", "revenue": 10.0, "views": 100},
        {"video_id": "vid_2", "month": "2024-01-15", "geography": "Unknown Geo", "revenue": 5.0, "views": 50},
    ])
    df_meta = pd.DataFrame([
        {"video_id": "vid_1", "geography": "ES", "series_name": "Series A"},
        {"video_id": "vid_2", "geography": "FR", "series_name": "Series B"},
    ])

    temp_mode = "daily"
    df_meta_clean = df_meta.rename(columns={'geography': 'meta_geography'})
    df_master = pd.merge(df_perf, df_meta_clean, on=['video_id'], how='left')

    if temp_mode == "daily":
        df_master['geography'] = "Global (Mundial)"
    else:
        df_master['geography'] = df_master['geography'].replace(['Unknown Geo', 'Global'], None).fillna(df_master['meta_geography']).fillna('Unknown Geo')

    df_master.drop(columns=['meta_geography'], errors='ignore', inplace=True)

    assert (df_master['geography'] == "Global (Mundial)").all()


def test_fetch_historical_analysis_default_daily():
    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, "CMS_123")

    mock_query = MagicMock()
    mock_analytics_client.reports.return_value.query.return_value = mock_query
    mock_query.execute.return_value = {
        "columnHeaders": [{"name": "video"}, {"name": "day"}, {"name": "views"}],
        "rows": [["vid_daily", "2024-01-15", 300]]
    }

    events = fetcher.fetch_historical_analysis(["vid_daily"], "2024-01-15", "2024-01-15")

    # Verify query was called with dimensions='day,video'
    mock_analytics_client.reports.return_value.query.assert_called_with(
        ids="contentOwner==CMS_123",
        startDate="2024-01-15",
        endDate="2024-01-15",
        metrics="views,likes,comments,estimatedMinutesWatched,estimatedRevenue,estimatedAdRevenue,cpm,adImpressions",
        dimensions="day,video",
        filters="video==vid_daily"
    )
    assert len(events) == 1
    assert events[0].geography == "Global"
    assert events[0].date == "2024-01-15"


def test_load_yt_credentials_oauth(tmp_path):
    from apps.event_manager.src.infrastructure.google_setup import load_yt_credentials, YT_Credentials
    oauth_file = tmp_path / "oauth_creds.json"
    oauth_file.write_text('{"token": "tok123", "refresh_token": "ref456", "client_id": "cid", "client_secret": "csec"}')

    creds = load_yt_credentials(str(oauth_file))
    assert isinstance(creds, YT_Credentials)
    assert creds.token == "tok123"
    assert creds.refresh_token == "ref456"
    assert creds.client_id == "cid"


def test_load_yt_credentials_service_account(tmp_path):
    from apps.event_manager.src.infrastructure.google_setup import load_yt_credentials
    from google.oauth2 import service_account
    from unittest.mock import patch

    sa_file = tmp_path / "sa_creds.json"
    sa_file.write_text('{"type": "service_account", "client_email": "sa@test.iam.gserviceaccount.com", "private_key": "dummy"}')

    with patch.object(service_account.Credentials, "from_service_account_info") as mock_from_info:
        mock_from_info.return_value = "mock_sa_credentials"
        creds = load_yt_credentials(str(sa_file))
        assert creds == "mock_sa_credentials"
        assert mock_from_info.called


def test_build_video_batches_date_bucketing():
    from datetime import date, timedelta
    from apps.event_manager.src.application.yt_analytics_events_service import YtAnalyticsEventsService

    yesterday = date(2026, 10, 25)
    
    # 500 recent videos (needing only last 3 days)
    recent = [(f"recent_{i}", date(2026, 10, 23)) for i in range(500)]
    # 2 old videos (from 2020 and 2022)
    old = [("old_1", date(2020, 1, 1)), ("old_2", date(2022, 6, 15))]
    
    # Combined list: old videos mixed in
    videos = recent[:250] + old + recent[250:]
    
    batches = YtAnalyticsEventsService._build_video_batches(videos, yesterday)
    
    # Must produce 2 batches: 1 for recent videos (500 videos), 1 for old videos (2 videos)
    assert len(batches) == 2
    
    # Batch 1: recent videos only
    recent_batch = batches[0]
    assert len(recent_batch) == 500
    assert min(v[1] for v in recent_batch) == date(2026, 10, 23)
    assert all("recent" in v[0] for v in recent_batch)
    
    # Batch 2: historical videos only, sorted by date
    hist_batch = batches[1]
    assert len(hist_batch) == 2
    assert hist_batch[0] == ("old_1", date(2020, 1, 1))
    assert hist_batch[1] == ("old_2", date(2022, 6, 15))


def test_yt_monthly_service_year_parameter_boundaries():
    from apps.event_manager.src.application.yt_analytics_events_service import YtAnalyticsEventsService
    from apps.event_manager.src.domain.models import Video

    mock_fetcher = MagicMock()
    mock_repo = MagicMock()
    mock_pub = MagicMock()

    service = YtAnalyticsEventsService(mock_fetcher, mock_repo, mock_pub, "CMS_TEST")

    # Videos:
    # 1. vid_future: published in 2026 -> should be skipped for year 2025
    # 2. vid_completed: published in 2024, synced up to 2025-12-01 in Mongo -> should be skipped
    # 3. vid_partial: published in 2023, synced up to 2025-06-01 -> should sync 2025-07-01 to 2025-12-31
    # 4. vid_new_in_year: published on 2025-05-15, no data -> should sync 2025-05-15 to 2025-12-31
    v_future = Video(video_id="vid_future", channel_id="ch_1", platform="youtube", title="Future", published_at="2026-03-01T10:00:00Z")
    v_completed = Video(video_id="vid_completed", channel_id="ch_1", platform="youtube", title="Completed", published_at="2024-01-01T10:00:00Z")
    v_partial = Video(video_id="vid_partial", channel_id="ch_1", platform="youtube", title="Partial", published_at="2023-01-01T10:00:00Z")
    v_new = Video(video_id="vid_new", channel_id="ch_1", platform="youtube", title="New", published_at="2025-05-15T10:00:00Z")

    mock_repo.get_all_by_channel.return_value = [v_future, v_completed, v_partial, v_new]

    # In Mongo:
    # vid_completed has last_date = 2025-12-01
    # vid_partial has last_date = 2025-06-01
    mock_pub.get_last_stats_date.return_value = {
        "vid_completed": date(2025, 12, 1),
        "vid_partial": date(2025, 6, 1)
    }

    mock_fetcher.fetch_monthly_analysis_by_country.return_value = []

    service.execute(
        channel_id="ch_1",
        mongo_collection="test_collection",
        by_country=True,
        start_date_override="2025-01-01",
        end_date_override="2025-12-31"
    )

    # Verify get_last_stats_date was called with max_date=date(2025, 12, 31)
    mock_pub.get_last_stats_date.assert_called_once()
    _, kwargs = mock_pub.get_last_stats_date.call_args
    assert kwargs.get("max_date") == date(2025, 12, 31)
    assert kwargs.get("by_country") is True

    # Verify fetcher calls: vid_future and vid_completed must NOT be in any batch
    assert mock_fetcher.fetch_monthly_analysis_by_country.called
    for call in mock_fetcher.fetch_monthly_analysis_by_country.call_args_list:
        v_ids = call.kwargs.get("video_ids") or call.args[0]
        assert "vid_future" not in v_ids
        assert "vid_completed" not in v_ids
        assert call.kwargs.get("end_date") == "2025-12-31"


def test_mongo_publisher_get_last_stats_date_with_max_date():
    from apps.event_manager.src.infrastructure.adapters.mongo_publisher import MongoRepository

    mock_client = MagicMock()
    repo = MongoRepository("mongodb://dummy:27017", "dummy_db")
    repo.client = mock_client
    repo.db = mock_client["dummy_db"]
    mock_coll = MagicMock()
    repo.db.__getitem__.return_value = mock_coll
    mock_coll.aggregate.return_value = [{"_id": "vid_1", "max_date": "2025-06-01"}]

    res = repo.get_last_stats_date(["vid_1"], "test_coll", by_country=True, max_date="2025-12-31")

    assert res == {"vid_1": date(2025, 6, 1)}
    pipeline = mock_coll.aggregate.call_args[0][0]
    match_stage = pipeline[0]["$match"]
    assert match_stage["payload.date"] == {"$lte": "2025-12-31"}
    assert match_stage["payload.geography"] == {"$nin": ["Global", "Unknown Geo", None]}


def test_query_retry_on_http_500_transient():
    from googleapiclient.errors import HttpError
    from unittest.mock import Mock

    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, "CMS_123")

    mock_resp_500 = Mock()
    mock_resp_500.status = 500
    err_500 = HttpError(resp=mock_resp_500, content=b'{"message": "backendError"}')

    success_result = {
        "columnHeaders": [{"name": "video"}, {"name": "country"}, {"name": "views"}],
        "rows": [["vid_retry", "ES", 100]]
    }

    mock_query = MagicMock()
    mock_analytics_client.reports.return_value.query.return_value = mock_query
    mock_query.execute.side_effect = [err_500, success_result]

    rows = fetcher._query_reports_with_retry_and_split(
        start_date="2025-05-01",
        end_date="2025-05-31",
        metrics="views",
        dimensions="video,country",
        video_batch=["vid_retry"],
        max_retries=3,
        base_delay=0.01  # fast test
    )

    assert len(rows) == 1
    assert rows[0]["video"] == "vid_retry"
    assert rows[0]["views"] == 100
    assert mock_query.execute.call_count == 2


def test_query_batch_splitting_on_persistent_500():
    from googleapiclient.errors import HttpError
    from unittest.mock import Mock

    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, "CMS_123")

    mock_resp_500 = Mock()
    mock_resp_500.status = 500
    err_500 = HttpError(resp=mock_resp_500, content=b'{"message": "backendError"}')

    def side_effect_query(*args, **kwargs):
        filters = kwargs.get("filters", "")
        # If batch contains all 4 videos, fail with 500
        if "vid_1,vid_2,vid_3,vid_4" in filters:
            mock_call = MagicMock()
            mock_call.execute.side_effect = err_500
            return mock_call
        elif "vid_1,vid_2" in filters:
            mock_call = MagicMock()
            mock_call.execute.return_value = {
                "columnHeaders": [{"name": "video"}, {"name": "country"}, {"name": "views"}],
                "rows": [["vid_1", "ES", 50], ["vid_2", "US", 60]]
            }
            return mock_call
        elif "vid_3,vid_4" in filters:
            mock_call = MagicMock()
            mock_call.execute.return_value = {
                "columnHeaders": [{"name": "video"}, {"name": "country"}, {"name": "views"}],
                "rows": [["vid_3", "MX", 70], ["vid_4", "AR", 80]]
            }
            return mock_call
        mock_call = MagicMock()
        mock_call.execute.return_value = {"columnHeaders": [], "rows": []}
        return mock_call

    mock_analytics_client.reports.return_value.query.side_effect = side_effect_query

    rows = fetcher._query_reports_with_retry_and_split(
        start_date="2025-05-01",
        end_date="2025-05-31",
        metrics="views",
        dimensions="video,country",
        video_batch=["vid_1", "vid_2", "vid_3", "vid_4"],
        max_retries=2,
        base_delay=0.01
    )

    assert len(rows) == 4
    vids = {r["video"] for r in rows}
    assert vids == {"vid_1", "vid_2", "vid_3", "vid_4"}
    assert len(fetcher.failed_queries) == 0


def test_query_single_video_persistent_failure_tracked():
    from googleapiclient.errors import HttpError
    from unittest.mock import Mock

    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, "CMS_123")

    mock_resp_500 = Mock()
    mock_resp_500.status = 500
    err_500 = HttpError(resp=mock_resp_500, content=b'{"message": "backendError"}')

    mock_query = MagicMock()
    mock_analytics_client.reports.return_value.query.return_value = mock_query
    mock_query.execute.side_effect = err_500

    rows = fetcher._query_reports_with_retry_and_split(
        start_date="2025-05-01",
        end_date="2025-05-31",
        metrics="views",
        dimensions="video,country",
        video_batch=["bad_vid"],
        max_retries=2,
        base_delay=0.01
    )

    assert rows == []
    assert len(fetcher.failed_queries) == 1
    assert fetcher.failed_queries[0]["video_ids"] == ["bad_vid"]


def test_fetch_monthly_country_cpm_profile():
    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, "CMS_123")

    mock_query = MagicMock()
    mock_analytics_client.reports.return_value.query.return_value = mock_query
    mock_query.execute.return_value = {
        "columnHeaders": [{"name": "country"}, {"name": "views"}, {"name": "estimatedRevenue"}, {"name": "cpm"}],
        "rows": [
            ["US", 500000, 9000.0, 18.0],
            ["ES", 200000, 1300.0, 6.5],
            ["IN", 1000000, 900.0, 0.9]
        ]
    }

    cpm_dict, default_cpm = fetcher.fetch_monthly_country_cpm_profile("2024-05-01", "2024-05-31")

    assert cpm_dict["US"] == 18.0
    assert cpm_dict["ES"] == 6.5
    assert cpm_dict["IN"] == 0.9
    assert default_cpm == 6.5  # median of 0.9, 6.5, 18.0

    # Test cache: second call should not trigger reports().query again
    mock_analytics_client.reports.return_value.query.reset_mock()
    cpm_dict_2, _ = fetcher.fetch_monthly_country_cpm_profile("2024-05-01", "2024-05-31")
    assert cpm_dict_2["US"] == 18.0
    assert not mock_analytics_client.reports.return_value.query.called


def test_monthly_analysis_by_country_cpm_weighting_allocation():
    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, "CMS_123")

    # Mock country CPM profile
    fetcher._monthly_cpm_cache["2024-05"] = ({"US": 18.0, "IN": 0.9}, 2.0)

    def side_effect_query(*args, **kwargs):
        dims = kwargs.get("dimensions", "")
        mock_call = MagicMock()
        if dims == "video":
            # Global revenue of $1000 for vid_cpm
            mock_call.execute.return_value = {
                "columnHeaders": [{"name": "video"}, {"name": "estimatedRevenue"}, {"name": "estimatedAdRevenue"}, {"name": "adImpressions"}],
                "rows": [["vid_cpm", 1000.0, 800.0, 50000]]
            }
        elif dims == "video,country":
            # Country views: US 10,000 views, IN 100,000 views (direct revenue is 0 as YouTube returns in production)
            mock_call.execute.return_value = {
                "columnHeaders": [
                    {"name": "video"}, {"name": "country"}, {"name": "views"}, {"name": "likes"},
                    {"name": "comments"}, {"name": "estimatedMinutesWatched"}, {"name": "estimatedRevenue"},
                    {"name": "estimatedAdRevenue"}, {"name": "cpm"}, {"name": "adImpressions"}
                ],
                "rows": [
                    ["vid_cpm", "US", 10000, 50, 10, 30000, 0.0, 0.0, 0.0, 0],
                    ["vid_cpm", "IN", 100000, 500, 100, 300000, 0.0, 0.0, 0.0, 0]
                ]
            }
        else:
            mock_call.execute.return_value = {"columnHeaders": [], "rows": []}
        return mock_call

    mock_analytics_client.reports.return_value.query.side_effect = side_effect_query

    events = fetcher.fetch_monthly_analysis_by_country(["vid_cpm"], "2024-05-01", "2024-05-31")

    assert len(events) == 2
    ev_us = next(e for e in events if e.geography == "US")
    ev_in = next(e for e in events if e.geography == "IN")

    # Weight US = 10,000 * 18.0 = 180,000
    # Weight IN = 100,000 * 0.9 = 90,000
    # Total weight = 270,000
    # US ratio = 180,000 / 270,000 = 2/3 (66.67%)
    # IN ratio = 90,000 / 270,000 = 1/3 (33.33%)

    # Despite US having 10x LESS views than IN (10k vs 100k), US generated DOUBLE the revenue!
    assert ev_us.estimated_revenue > ev_in.estimated_revenue
    assert round(ev_us.estimated_revenue, 1) == 666.7
    assert round(ev_in.estimated_revenue, 1) == 333.3

    # Exact cent conservation check
    assert round(ev_us.estimated_revenue + ev_in.estimated_revenue, 2) == 1000.00
    assert ev_us.extra_metrics["ad_impressions"] + ev_in.extra_metrics["ad_impressions"] == 50000


def test_monthly_analysis_cent_conservation_adjustment():
    from apps.event_manager.src.domain.models import VideoPerformanceEvent
    from apps.event_manager.src.infrastructure.adapters.youtube_video_fetcher import YoutubeVideoFetcher

    mock_data_client = MagicMock()
    mock_analytics_client = MagicMock()
    fetcher = YoutubeVideoFetcher(mock_data_client, mock_analytics_client, "CMS_DIFF")

    def side_effect_query(**kwargs):
        mock_call = MagicMock()
        dims = kwargs.get("dimensions", "")
        if dims == "country":
            mock_call.execute.return_value = {
                "columnHeaders": [{"name": "country"}, {"name": "views"}, {"name": "estimatedRevenue"}, {"name": "cpm"}],
                "rows": [["US", 1000, 10.0, 10.0], ["ES", 1000, 10.0, 10.0]]
            }
        elif dims == "video":
            # Global revenue is 100.01 (creates an odd cent difference when split 50/50)
            mock_call.execute.return_value = {
                "columnHeaders": [{"name": "video"}, {"name": "views"}, {"name": "estimatedRevenue"}, {"name": "estimatedAdRevenue"}, {"name": "adImpressions"}],
                "rows": [["vid_diff", 2000, 100.01, 80.0, 1001]]
            }
        elif "video,country" in dims:
            mock_call.execute.return_value = {
                "columnHeaders": [
                    {"name": "video"}, {"name": "country"}, {"name": "views"}, {"name": "likes"},
                    {"name": "comments"}, {"name": "estimatedMinutesWatched"}, {"name": "estimatedRevenue"},
                    {"name": "estimatedAdRevenue"}, {"name": "cpm"}, {"name": "adImpressions"}
                ],
                "rows": [
                    ["vid_diff", "US", 1000, 10, 5, 2000, 0.0, 0.0, 0.0, 0],
                    ["vid_diff", "ES", 1000, 10, 5, 2000, 0.0, 0.0, 0.0, 0]
                ]
            }
        else:
            mock_call.execute.return_value = {"columnHeaders": [], "rows": []}
        return mock_call

    mock_analytics_client.reports.return_value.query.side_effect = side_effect_query

    events = fetcher.fetch_monthly_analysis_by_country(["vid_diff"], "2024-05-01", "2024-05-31")
    assert len(events) == 2
    # Verify exact cent conservation: sum must be exactly 100.01
    assert round(sum(e.estimated_revenue for e in events), 2) == 100.01


def test_mongo_publisher_in_place_overwrite():
    from apps.event_manager.src.infrastructure.adapters.mongo_publisher import MongoRepository
    from pymongo import UpdateOne

    mock_client = MagicMock()
    repo = MongoRepository("mongodb://dummy:27017", "dummy_db")
    repo.client = mock_client
    repo.db = mock_client["dummy_db"]
    mock_coll = MagicMock()
    repo.db.__getitem__.return_value = mock_coll
    repo.db.list_collection_names.return_value = ["video_performance_events"]

    mock_result = MagicMock()
    mock_result.upserted_count = 0
    mock_result.modified_count = 1
    mock_result.matched_count = 1
    mock_coll.bulk_write.return_value = mock_result

    event = {
        "metadata": {
            "event_type": "youtube.video.performance_recorded",
            "resource_id": "vid_overwrite_1"
        },
        "payload": {
            "video_id": "vid_overwrite_1",
            "platform": "youtube",
            "date": "2026-08-01",
            "geography": "US",
            "estimated_revenue": 150.25,
            "extra_metrics": {"views": 5000}
        }
    }

    res = repo.publish([event], "video_performance_events")
    assert res["published_news"] == 1
    assert res["ignored_duplicates"] == 0

    assert mock_coll.bulk_write.called
    ops = mock_coll.bulk_write.call_args[0][0]
    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, UpdateOne)
    assert op._filter["metadata.event_type"] == "youtube.video.performance_recorded"
    assert op._filter["payload.video_id"] == "vid_overwrite_1"
    assert op._filter["payload.date"] == "2026-08-01"
    assert op._filter["payload.geography"] == "US"
    assert "$set" in op._doc
    assert op._doc["$set"]["payload"]["estimated_revenue"] == 150.25


def test_dashboard_territorial_period_scale_reconciliation():
    import pandas as pd
    import numpy as np

    # Multi-year dataset where 2017-2022 only exist globally (no territorial rows)
    # and 2023 has territorial rows.
    df_performance = pd.DataFrame([
        {"month": "2023", "video_id": "v1", "geography": "US", "views": 1000, "revenue": 100.0, "ad_revenue": 80.0},
        {"month": "2023", "video_id": "v1", "geography": "ES", "views": 500, "revenue": 50.0, "ad_revenue": 40.0},
    ])
    df_glob = pd.DataFrame([
        {"month": "2017", "video_id": "v1", "global_revenue": 1000.0, "global_ad_revenue": 800.0},
        {"month": "2018", "video_id": "v1", "global_revenue": 1000.0, "global_ad_revenue": 800.0},
        {"month": "2023", "video_id": "v1", "global_revenue": 150.0, "global_ad_revenue": 120.0},
    ])

    # Reconciliar residual no clasificado por periodo
    alloc_by_period = df_performance.groupby("month")["revenue"].transform("sum")
    glob_by_period_map = df_glob.groupby("month")["global_revenue"].sum()
    glob_by_period = df_performance["month"].map(glob_by_period_map).fillna(0.0)
    scale_factor = np.where(
        (alloc_by_period > 0) & (glob_by_period > alloc_by_period),
        glob_by_period / alloc_by_period,
        1.0
    )
    df_performance["revenue"] = (df_performance["revenue"] * scale_factor).round(4)

    # 2023 total must equal 2023 global revenue (150.0), NOT inflated by 2017-2018 (which would have been 2150.0)
    tot_2023 = df_performance[df_performance["month"] == "2023"]["revenue"].sum()
    assert tot_2023 == pytest.approx(150.0)


def test_mongo_publisher_get_existing_combinations_exclude_zero_revenue():
    from apps.event_manager.src.infrastructure.adapters.mongo_publisher import MongoRepository

    mock_client = MagicMock()
    repo = MongoRepository("mongodb://dummy:27017", "dummy_db")
    repo.client = mock_client
    repo.db = mock_client["dummy_db"]
    mock_coll = MagicMock()
    repo.db.__getitem__.return_value = mock_coll

    repo.get_existing_combinations(
        platform="youtube",
        dates=["2026-08-01"],
        collection_name="video_performance_events",
        video_ids=["vid_1"],
        exclude_zero_revenue=True
    )

    query = mock_coll.find.call_args[0][0]
    assert "$or" in query
    assert {"payload.estimated_revenue": {"$gt": 0}} in query["$or"]









