"""Tests for Tencent Video parsing, currency conversion, Mongo fetch, and multiplatform dashboard reports."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from apps.dashboard.pages.business_reports import (
    consolidate_multiplatform_reports,
    consolidate_reports,
    fetch_tencent_reports,
    generate_export_filename,
    to_excel_bytes,
)
from core.domain.china import (
    convert_cny_to_usd,
    get_rmb_per_usd_rate,
    get_tencent_series_metadata,
    normalize_excel_date,
    parse_cny_amount,
)
from core.ingestion.tencent_parser import parse_tencent_directory, summarize_tencent_events


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.last_pipeline = None

    def aggregate(self, pipeline):
        self.last_pipeline = pipeline
        return list(self.docs)


class _FakeMongoDB:
    def __init__(self, collections: dict[str, list[dict]]):
        self.collections = {name: _FakeCollection(docs) for name, docs in collections.items()}

    def __getitem__(self, name: str):
        return self.collections.setdefault(name, _FakeCollection([]))


def _make_row_pair(
    month: str,
    platform: str,
    ip_name: str,
    series_name: str,
    revenue: float,
    views: int,
    watch_time: float = 0.0,
    season: int = 1,
    episode_number: int = 1,
    episode_name: str = "Ep 1",
    video_id: str = "vid_1",
    channel_id: str = "ch_1",
    geography: str = "US",
    language_code: str = "en",
    revenue_cny: float = 0.0,
    revenue_svod: float = 0.0,
    revenue_avod: float = 0.0,
    monetization_model: str | None = None,
) -> tuple[dict, dict]:
    fin = {
        "month": month,
        "producer": "Amuse Animation",
        "ip_name": ip_name,
        "series_name": series_name,
        "season": season,
        "episode_number": episode_number,
        "episode_name": episode_name,
        "geography": geography,
        "video_id": video_id,
        "channel_id": channel_id,
        "platform": platform,
        "language_code": language_code,
        "video_title": episode_name,
        "video_duration": 180 if platform == "youtube" else 0,
        "revenue": revenue,
        "revenue_svod": revenue_svod,
        "revenue_tvod": 0.0,
        "revenue_avod": revenue_avod,
        "revenue_cny": revenue_cny,
    }
    op = {
        "month": month,
        "producer": "Amuse Animation",
        "ip_name": ip_name,
        "series_name": series_name,
        "season": season,
        "episode_number": episode_number,
        "episode_name": episode_name,
        "geography": geography,
        "video_id": video_id,
        "channel_id": channel_id,
        "platform": platform,
        "language_code": language_code,
        "video_title": episode_name,
        "video_duration": 180 if platform == "youtube" else 0,
        "views": views,
        "watch_time": watch_time,
        "likes": 10 if platform == "youtube" else 0,
        "comments": 2 if platform == "youtube" else 0,
        "ad_impressions": 500 if platform == "youtube" else 0,
        "ad_revenue": revenue * 0.9 if platform == "youtube" else 0.0,
    }
    if monetization_model is not None:
        fin["monetization_model"] = monetization_model
        op["monetization_model"] = monetization_model
    return fin, op


def test_china_domain_helpers():
    assert parse_cny_amount("￥0.23") == pytest.approx(0.23)
    assert parse_cny_amount("¥1,234.50") == pytest.approx(1234.50)
    assert parse_cny_amount("-") == 0.0
    assert parse_cny_amount(None) == 0.0

    assert normalize_excel_date(datetime(22, 7, 1)) == "2022-07-01"
    assert normalize_excel_date("0022-07-01") == "2022-07-01"
    assert normalize_excel_date("2021-03-18") == "2021-03-18"

    assert get_rmb_per_usd_rate(2021) == 6.45
    assert get_rmb_per_usd_rate(2015) == 6.73  # clamped to earliest year
    assert get_rmb_per_usd_rate(2030) == 7.19  # default fallback

    usd, rate = convert_cny_to_usd(645.0, "2021-05-01")
    assert rate == 6.45
    assert usd == pytest.approx(100.0)

    shk = get_tencent_series_metadata("TENCENT_SVOD_SHK")
    assert shk["ip_name"] == "SHARK_ACADEMY"
    assert shk["monetization_model"] == "SVOD"

    avod = get_tencent_series_metadata("TENCENT_AVOD_CHANNEL")
    assert avod["ip_name"] == "CHANNEL_LEVEL"
    assert avod["monetization_model"] == "AVOD"


def test_tencent_parser_synthetic_avoids_double_counting_and_fixes_typo(tmp_path: Path):
    svod_dir = tmp_path / "SVOD"
    avod_dir = tmp_path / "AVOD"
    svod_dir.mkdir()
    avod_dir.mkdir()

    # SVOD workbook with ALL_Daily (must be ignored) and SHK
    wb_svod = openpyxl.Workbook()
    ws_all = wb_svod.active
    ws_all.title = "ALL_Daily"
    ws_all.append(["Date", "Views", "Revenue"])
    ws_all.append(["2021-03-18", 999999, "￥999999"])
    ws_shk = wb_svod.create_sheet("SHK")
    ws_shk.append(["Date", "Views", "Net Revenue (CNY)"])
    ws_shk.append(["2021-03-18", 1200, "￥645.00"])
    wb_svod.save(svod_dir / "TENCENT_SVOD_Revenue.xlsx")

    # AVOD main + extra file with two-digit typo 0022-07-01 and duplicate date rows
    wb_avod = openpyxl.Workbook()
    ws_a1 = wb_avod.active
    ws_a1.append(["Date", "Views", "Revenue"])
    ws_a1.append(["2022-07-01", 5000, "￥336.50"])
    wb_avod.save(avod_dir / "TENCENT.xlsx")

    wb_avod2 = openpyxl.Workbook()
    ws_a2 = wb_avod2.active
    ws_a2.append(["Date", "Type", "Revenue"])
    ws_a2.append([datetime(22, 7, 1), "流量分成-短视频", "￥336.50"])
    wb_avod2.save(avod_dir / "TENCENT_AVOD_2.xlsx")

    events = parse_tencent_directory(tmp_path)
    assert len(events) == 2

    svod_ev = next(e for e in events if e["payload"]["video_id"] == "TENCENT_SVOD_SHK")
    assert svod_ev["payload"]["date"] == "2021-03-18"
    assert svod_ev["payload"]["estimated_revenue"] == pytest.approx(100.0)
    assert svod_ev["payload"]["extra_metrics"]["views"] == 1200

    avod_ev = next(e for e in events if e["payload"]["video_id"] == "TENCENT_AVOD_CHANNEL")
    assert avod_ev["payload"]["date"] == "2022-07-01"
    assert avod_ev["payload"]["ip_name"] == "CHANNEL_LEVEL"
    assert avod_ev["payload"]["extra_metrics"]["views"] == 5000
    assert avod_ev["payload"]["extra_metrics"]["revenue_cny"] == pytest.approx(673.0)
    assert avod_ev["payload"]["estimated_revenue"] == pytest.approx(100.0)


def test_tencent_parser_real_directory_totals():
    real_dir = Path("/home/jgarcia/matching_AI/data/Tencent")
    if not real_dir.exists():
        pytest.skip("data/Tencent directory not present")
    events = parse_tencent_directory(real_dir)
    summary = summarize_tencent_events(events)
    assert summary["total_events"] == 11161
    assert summary["total_views"] == 4520260252
    assert summary["total_cny"] == pytest.approx(7367363.21, abs=0.1)
    assert summary["total_usd"] == pytest.approx(1098662.51, abs=0.2)


def test_consolidate_multiplatform_series_ip_mode():
    rows = [
        _make_row_pair("2023", "youtube", "SHARK_ACADEMY", "SHARK_ACADEMY", revenue=500.0, views=100000, watch_time=5000.0),
        _make_row_pair("2023", "amazon", "SHARK_ACADEMY", "SHARK_ACADEMY", revenue=300.0, views=10000, watch_time=2000.0, video_id="EP_1"),
        _make_row_pair(
            "2023", "tencent", "SHARK_ACADEMY", "SHARK_ACADEMY",
            revenue=200.0, views=4000, watch_time=0.0, season=0, episode_number=0,
            episode_name="Shark Academy (Tencent SVOD)", video_id="TENCENT_SVOD_SHK",
            channel_id="TENCENT_SVOD", geography="CN", language_code="zh",
            revenue_cny=1416.0, revenue_svod=200.0, monetization_model="SVOD",
        ),
        _make_row_pair(
            "2023", "tencent", "CHANNEL_LEVEL", "Tencent Video AVOD (Channel Level)",
            revenue=150.0, views=500000, watch_time=0.0, season=0, episode_number=0,
            episode_name="Tencent Video AVOD (Channel Level)", video_id="TENCENT_AVOD_CHANNEL",
            channel_id="TENCENT_AVOD_CHANNEL", geography="CN", language_code="zh",
            revenue_cny=1062.0, revenue_avod=150.0, monetization_model="AVOD",
        ),
    ]
    report_fin = pd.DataFrame([r[0] for r in rows])
    report_op = pd.DataFrame([r[1] for r in rows])

    res = consolidate_multiplatform_reports(
        report_fin,
        report_op,
        agg_level="Por Serie / IP (Comparativa Multiplataforma)",
        use_youtube=True,
        use_amazon=True,
        use_tencent=True,
    )

    rep_piv, df_totals = res["comparative"]
    df_yt, df_totals_yt = res["youtube"]
    df_amz, df_totals_amz = res["amazon"]
    df_tcn, df_totals_tcn = res["tencent"]

    assert len(rep_piv) == 2
    assert "watch_time_tencent" not in rep_piv.columns
    assert "episode_name" not in rep_piv.columns
    assert "youtube_url" not in rep_piv.columns

    shark_row = rep_piv[rep_piv["ip_name"] == "SHARK_ACADEMY"].iloc[0]
    assert shark_row["revenue_youtube"] == pytest.approx(500.0)
    assert shark_row["revenue_amazon"] == pytest.approx(300.0)
    assert shark_row["revenue_tencent"] == pytest.approx(200.0)
    assert shark_row["total_revenue"] == pytest.approx(1000.0)
    assert shark_row["total_views"] == 114000

    ch_row = rep_piv[rep_piv["ip_name"] == "CHANNEL_LEVEL"].iloc[0]
    assert ch_row["revenue_tencent"] == pytest.approx(150.0)
    assert ch_row["views_tencent"] == 500000

    assert len(df_totals) == 1
    tot_row = df_totals.iloc[0]
    assert tot_row["revenue_youtube"] == pytest.approx(500.0)
    assert tot_row["revenue_amazon"] == pytest.approx(300.0)
    assert tot_row["revenue_tencent"] == pytest.approx(350.0)
    assert tot_row["total_revenue"] == pytest.approx(1150.0)
    assert tot_row["views_tencent"] == 504000
    assert tot_row["total_views"] == 614000

    # Platform tabs clean checks
    assert "episode_name" not in df_yt.columns
    assert "amazon_title" not in df_amz.columns
    assert set(df_tcn["monetization_model"]) == {"SVOD", "AVOD"}
    assert df_totals_tcn.iloc[0]["revenue"] == pytest.approx(350.0)
    assert df_totals_tcn.iloc[0]["revenue_cny"] == pytest.approx(2478.0)
    assert df_totals_tcn.iloc[0]["revenue_svod"] == pytest.approx(200.0)
    assert df_totals_tcn.iloc[0]["revenue_avod"] == pytest.approx(150.0)


def test_episode_level_excludes_tencent_rows_from_piv_but_keeps_in_totals():
    rows = [
        _make_row_pair("2023-01", "youtube", "SHARK_ACADEMY", "SHARK_ACADEMY", revenue=100.0, views=1000, watch_time=50.0, season=1, episode_number=2, episode_name="Ep 2"),
        _make_row_pair("2023-02", "amazon", "SHARK_ACADEMY", "SHARK_ACADEMY", revenue=80.0, views=500, watch_time=40.0, season=1, episode_number=2, episode_name="Ep 2", video_id="EP_2"),
        _make_row_pair(
            "2023-01", "tencent", "SHARK_ACADEMY", "SHARK_ACADEMY",
            revenue=250.0, views=9000, watch_time=0.0, season=0, episode_number=0,
            episode_name="Shark Academy (Tencent SVOD)", video_id="TENCENT_SVOD_SHK",
            channel_id="TENCENT_SVOD", geography="CN", language_code="zh",
            revenue_cny=1770.0, revenue_svod=250.0, monetization_model="SVOD",
        ),
    ]
    report_fin = pd.DataFrame([r[0] for r in rows])
    report_op = pd.DataFrame([r[1] for r in rows])

    for agg_mode in (
        "Episodio Canónico (Todas las versiones)",
        "Por Vídeo/Versión (Mostrar resubidas)",
    ):
        res = consolidate_multiplatform_reports(
            report_fin,
            report_op,
            agg_level=agg_mode,
            use_youtube=True,
            use_amazon=True,
            use_tencent=True,
        )
        rep_piv, df_totals = res["comparative"]
        df_tcn, df_totals_tcn = res["tencent"]

        assert not rep_piv.empty
        assert all(rep_piv["video_id"] != "TENCENT_SVOD_SHK") if "video_id" in rep_piv.columns else "revenue_tencent" not in rep_piv.columns
        assert (rep_piv["season"].astype(str) != "0").all()

        if agg_mode == "Por Vídeo/Versión (Mostrar resubidas)":
            tcn_tot = df_totals[df_totals["platform"] == "tencent"]
            assert not tcn_tot.empty
            assert tcn_tot.iloc[0]["total_revenue"] == pytest.approx(250.0)
        else:
            assert df_totals.iloc[0]["revenue_tencent"] == pytest.approx(250.0)
            assert df_totals.iloc[0]["total_revenue"] == pytest.approx(430.0)
            assert len(df_totals) == 3  # TOTAL + 2023-01 + 2023-02
        assert df_totals_tcn.iloc[0]["revenue"] == pytest.approx(250.0)

    # Verify legacy 6-tuple wrapper untouched
    out = consolidate_reports(
        report_fin[report_fin["platform"] != "tencent"],
        report_op[report_op["platform"] != "tencent"],
        "Episodio Canónico (Todas las versiones)",
        use_youtube=True,
        use_amazon=True,
    )
    assert len(out) == 6


def test_tencent_only_and_youtube_plus_tencent():
    rows = [
        _make_row_pair("2024", "youtube", "ANIMACARS", "ANIMA_TOWN", revenue=120.0, views=2000, watch_time=60.0),
        _make_row_pair(
            "2024", "tencent", "ANIMACARS", "ANIMA_TOWN",
            revenue=90.0, views=1500, watch_time=0.0, season=0, episode_number=0,
            episode_name="AnimaTown (Tencent SVOD)", video_id="TENCENT_SVOD_ACAT",
            channel_id="TENCENT_SVOD", geography="CN", language_code="zh",
            revenue_cny=647.10, revenue_svod=90.0, monetization_model="SVOD",
        ),
    ]
    report_fin = pd.DataFrame([r[0] for r in rows])
    report_op = pd.DataFrame([r[1] for r in rows])

    # YouTube + Tencent (without Amazon) in Series/IP mode
    res_yt_tcn = consolidate_multiplatform_reports(
        report_fin,
        report_op,
        agg_level="Por Serie / IP (Comparativa Multiplataforma)",
        use_youtube=True,
        use_amazon=False,
        use_tencent=True,
    )
    rep_piv, df_totals = res_yt_tcn["comparative"]
    assert not rep_piv.empty
    assert "revenue_amazon" not in rep_piv.columns
    assert rep_piv.iloc[0]["total_revenue"] == pytest.approx(210.0)
    assert df_totals.iloc[0]["total_revenue"] == pytest.approx(210.0)

    # Tencent only
    tcn_fin = report_fin[report_fin["platform"] == "tencent"]
    tcn_op = report_op[report_op["platform"] == "tencent"]
    res_only = consolidate_multiplatform_reports(
        tcn_fin,
        tcn_op,
        agg_level="Episodio Canónico (Todas las versiones)",
        use_youtube=False,
        use_amazon=False,
        use_tencent=True,
    )
    assert res_only["comparative"][0].empty
    assert res_only["tencent"][0].iloc[0]["revenue"] == pytest.approx(90.0)


def test_export_filename_and_excel_cny_format():
    f = {
        "fecha_inicio": datetime(2021, 1, 1),
        "fecha_fin": datetime(2024, 12, 31),
        "temp_mode": "yearly",
        "agg_level": "Por Serie / IP (Comparativa Multiplataforma)",
        "use_youtube": True,
        "use_amazon": True,
        "use_tencent": True,
    }
    fn = generate_export_filename(f, table_type="comparative", platform_override=None, ext="xlsx")
    assert fn == "2021__2024_Youtube_Amazon_Tencent_yearly_comparative_by_series_ip.xlsx"

    fn_tcn = generate_export_filename(f, table_type="metrics", platform_override="Tencent", ext="xlsx")
    assert fn_tcn == "2021__2024_Tencent_yearly_metrics_by_series_ip.xlsx"

    df_tcn = pd.DataFrame({
        "month": ["2023"],
        "revenue": [100.0],
        "revenue_cny": [708.0],
        "views": [1000],
    })
    wb = openpyxl.load_workbook(io.BytesIO(to_excel_bytes(df_tcn, "Tencent")))
    ws = wb["Tencent"]
    assert ws["C2"].number_format == "¥#,##0.00"
    assert ws["B2"].number_format == "$#,##0.00"


def test_fetch_tencent_reports_mock_mongo_and_filters():
    aggregated_docs = [
        {
            "_id": {
                "video_id": "TENCENT_SVOD_SHK",
                "month": "2023-05",
                "platform": "tencent",
                "geography": "CN",
            },
            "mongo_title": "Shark Academy (Tencent SVOD)",
            "mongo_ip": "SHARK_ACADEMY",
            "mongo_series": "SHARK_ACADEMY",
            "revenue": 100.0,
            "revenue_cny": 708.0,
            "revenue_svod": 100.0,
            "revenue_avod": 0.0,
            "views": 5000,
            "watch_time": 0.0,
        },
        {
            "_id": {
                "video_id": "TENCENT_AVOD_CHANNEL",
                "month": "2023-05",
                "platform": "tencent",
                "geography": "CN",
            },
            "mongo_title": "Tencent Video AVOD (Channel Level)",
            "mongo_ip": "CHANNEL_LEVEL",
            "mongo_series": "Tencent Video AVOD (Channel Level)",
            "revenue": 50.0,
            "revenue_cny": 354.0,
            "revenue_svod": 0.0,
            "revenue_avod": 50.0,
            "views": 250000,
            "watch_time": 0.0,
        },
    ]
    fake_db = _FakeMongoDB({
        "monthly_performance_summaries": aggregated_docs,
        "yearly_performance_summaries": aggregated_docs,
        "video_performance_events": aggregated_docs,
    })

    fin, op = fetch_tencent_reports(
        fake_db,
        temp_mode="monthly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2023, 12, 31),
    )
    assert len(fin) == 2
    assert fin["revenue"].sum() == pytest.approx(150.0)
    assert fin["revenue_cny"].sum() == pytest.approx(1062.0)
    assert op["views"].sum() == 255000
    monthly_pipe = fake_db["monthly_performance_summaries"].last_pipeline
    assert monthly_pipe[0]["$match"]["_id.event_type"] == "tencent.video.performance_recorded"
    assert monthly_pipe[1]["$group"]["revenue_cny"] == {"$sum": {"$ifNull": ["$monthly_revenue_cny", 0]}}

    # Verify yearly & daily pipelines target the right collections/fields
    fetch_tencent_reports(fake_db, temp_mode="yearly", fecha_inicio=datetime(2023, 1, 1), fecha_fin=datetime(2023, 12, 31))
    yearly_pipe = fake_db["yearly_performance_summaries"].last_pipeline
    assert yearly_pipe[1]["$group"]["revenue"] == {"$sum": "$yearly_revenue"}
    assert yearly_pipe[1]["$group"]["revenue_avod"] == {"$sum": {"$ifNull": ["$yearly_revenue_avod", 0]}}

    fetch_tencent_reports(fake_db, temp_mode="daily", fecha_inicio=datetime(2023, 5, 1), fecha_fin=datetime(2023, 5, 31))
    daily_pipe = fake_db["video_performance_events"].last_pipeline
    assert daily_pipe[0]["$match"]["metadata.event_type"] == "tencent.video.performance_recorded"
    assert daily_pipe[1]["$group"]["views"] == {"$sum": {"$ifNull": ["$payload.extra_metrics.views", 0]}}

    # Channel sub-filter: SVOD only
    fin_svod, _ = fetch_tencent_reports(
        fake_db,
        temp_mode="monthly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2023, 12, 31),
        global_channels=["Tencent Video (SVOD)"],
    )
    assert len(fin_svod) == 1
    assert fin_svod.iloc[0]["ip_name"] == "SHARK_ACADEMY"

    # Non-Tencent channel excluded
    fin_none, _ = fetch_tencent_reports(
        fake_db,
        temp_mode="monthly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2023, 12, 31),
        global_channels=["Amazon Prime Video"],
    )
    assert fin_none.empty

    # Season > 0 or non-CN geography returns empty
    fin_season, _ = fetch_tencent_reports(
        fake_db,
        temp_mode="monthly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2023, 12, 31),
        global_seasons=[1],
    )
    assert fin_season.empty

    fin_us, _ = fetch_tencent_reports(
        fake_db,
        temp_mode="monthly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2023, 12, 31),
        selected_geo_codes=["US"],
    )
    assert fin_us.empty


def test_consolidation_ip_vs_series_aggregation_levels():
    rows = [
        # Two different series for CARCITY in YouTube
        _make_row_pair("2023", "youtube", "CARCITY", "CAR_PATROL", revenue=100.0, views=10000, watch_time=50.0),
        _make_row_pair("2023", "youtube", "CARCITY", "TOM_THE_TOW_TRUCK", revenue=50.0, views=5000, watch_time=25.0),
        # A series for CARCITY in Tencent
        _make_row_pair(
            "2023", "tencent", "CARCITY", "CAR_PATROL",
            revenue=80.0, views=8000, watch_time=0.0,
            revenue_cny=566.4, revenue_svod=80.0, monetization_model="SVOD",
        ),
        # Another IP
        _make_row_pair("2023", "youtube", "LEARN_TV", "ROBOFUSE", revenue=200.0, views=20000, watch_time=100.0),
    ]
    report_fin = pd.DataFrame([r[0] for r in rows])
    report_op = pd.DataFrame([r[1] for r in rows])

    # 1. Test Aggregation "Por Propiedad Intelectual (IP)"
    res_ip = consolidate_multiplatform_reports(
        report_fin,
        report_op,
        agg_level="Por Propiedad Intelectual (IP)",
        use_youtube=True,
        use_amazon=False,
        use_tencent=True,
    )
    rep_piv_ip, df_totals_ip = res_ip["comparative"]
    df_yt_ip, _ = res_ip["youtube"]
    df_tcn_ip, _ = res_ip["tencent"]

    # rep_piv_ip must NOT have series_name
    assert "series_name" not in rep_piv_ip.columns
    assert "ip_name" in rep_piv_ip.columns
    # CARCITY should be consolidated into 1 row
    assert len(rep_piv_ip) == 2
    car_row_ip = rep_piv_ip[rep_piv_ip["ip_name"] == "CARCITY"].iloc[0]
    assert car_row_ip["revenue_youtube"] == pytest.approx(150.0)
    assert car_row_ip["revenue_tencent"] == pytest.approx(80.0)
    assert car_row_ip["total_revenue"] == pytest.approx(230.0)
    assert car_row_ip["total_views"] == 23000

    # In df_yt_ip and df_tcn_ip, series_name should also be absent
    assert "series_name" not in df_yt_ip.columns
    assert len(df_yt_ip) == 2
    assert "series_name" not in df_tcn_ip.columns
    assert len(df_tcn_ip) == 1

    # 2. Test Aggregation "Por Serie"
    res_series = consolidate_multiplatform_reports(
        report_fin,
        report_op,
        agg_level="Por Serie",
        use_youtube=True,
        use_amazon=False,
        use_tencent=True,
    )
    rep_piv_s, df_totals_s = res_series["comparative"]
    df_yt_s, _ = res_series["youtube"]
    df_tcn_s, _ = res_series["tencent"]

    # rep_piv_s MUST have series_name
    assert "series_name" in rep_piv_s.columns
    assert "ip_name" in rep_piv_s.columns
    # CAR_PATROL, TOM_THE_TOW_TRUCK and ROBOFUSE should be 3 rows
    assert len(rep_piv_s) == 3
    cp_row = rep_piv_s[(rep_piv_s["ip_name"] == "CARCITY") & (rep_piv_s["series_name"] == "CAR_PATROL")].iloc[0]
    assert cp_row["revenue_youtube"] == pytest.approx(100.0)
    assert cp_row["revenue_tencent"] == pytest.approx(80.0)
    assert cp_row["total_revenue"] == pytest.approx(180.0)

    tom_row = rep_piv_s[(rep_piv_s["ip_name"] == "CARCITY") & (rep_piv_s["series_name"] == "TOM_THE_TOW_TRUCK")].iloc[0]
    assert tom_row["revenue_youtube"] == pytest.approx(50.0)
    assert tom_row["revenue_tencent"] == pytest.approx(0.0)
    assert tom_row["total_revenue"] == pytest.approx(50.0)

    # In df_yt_s, series_name should be present with 3 rows
    assert "series_name" in df_yt_s.columns
    assert len(df_yt_s) == 3
    # In df_tcn_s, series_name should be present
    assert "series_name" in df_tcn_s.columns
    assert len(df_tcn_s) == 1

