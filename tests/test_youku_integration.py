"""Tests for Youku parsing, currency conversion, Mongo fetch, and 4-platform dashboard reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from apps.dashboard.pages.business_reports import (
    consolidate_multiplatform_reports,
    consolidate_reports,
    fetch_youku_reports,
    generate_export_filename,
)
from core.domain.china import get_youku_series_metadata
from core.ingestion.youku_parser import parse_youku_directory, summarize_youku_events


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.pipelines: list = []

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
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
    likes: int = 0,
    comments: int = 0,
    subplatform: str | None = None,
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
        "likes": likes,
        "comments": comments,
        "ad_impressions": 500 if platform == "youtube" else 0,
        "ad_revenue": revenue * 0.9 if platform == "youtube" else 0.0,
    }
    if subplatform is not None:
        fin["subplatform"] = subplatform
        op["subplatform"] = subplatform
    if monetization_model is not None:
        fin["monetization_model"] = monetization_model
        op["monetization_model"] = monetization_model
    return fin, op


def test_youku_domain_mappings():
    cc = get_youku_series_metadata("YOUKU_DAYU_CC")
    assert cc["ip_name"] == "CARCITY"
    assert cc["series_name"] == "CARCITY_DAYU_CHANNEL"
    assert cc["subplatform"] == "DaYu Platform"

    ltv = get_youku_series_metadata("LTV")
    assert ltv["ip_name"] == "LEARN_TV"
    assert ltv["series_name"] == "LEARN_TV_DAYU_CHANNEL"

    # Spelling variations across Youku revenue & views exports map identically
    cp1 = get_youku_series_metadata("汽车之城警车和消防车")
    cp2 = get_youku_series_metadata("汽车城之警车和消防车")
    assert cp1["video_id"] == cp2["video_id"] == "YOUKU_OP_CP"
    assert cp1["ip_name"] == "CARCITY"
    assert cp1["series_name"] == "CAR_PATROL"

    mlk = get_youku_series_metadata(" Miliki超级宝贝米利奇 英文版")
    assert mlk["ip_name"] == "MILIKI"
    assert mlk["series_name"] == "MILIKI_SONGS_S1"

    mts2 = get_youku_series_metadata("大脚卡车镇 第二季")
    assert mts2["video_id"] == "YOUKU_OP_MTS2"
    assert mts2["ip_name"] == "CARCITY"
    assert mts2["series_name"] == "MONSTER_TOWN"


def test_youku_parser_synthetic_dedup_header_swap_and_no_total_double_count(tmp_path: Path):
    dayu_rev = tmp_path / "DaYu Platform" / "Revenus"
    dayu_cc = tmp_path / "DaYu Platform" / "Vues WT" / "CC"
    dayu_ltv = tmp_path / "DaYu Platform" / "Vues WT" / "LTV"
    op_dir = tmp_path / "Open Platform"
    op_views = op_dir / "Views per Series"
    for d in (dayu_rev, dayu_cc, dayu_ltv, op_dir, op_views):
        d.mkdir(parents=True)

    # 1. DaYu CC & LTV revenues (including extra Sheet1 on LTV that must be ignored)
    wb_cc = openpyxl.Workbook()
    ws_cc = wb_cc.active
    ws_cc.title = "Feuil1"
    ws_cc.append(["时间", "广告分成结算收益", "优酷粉丝激励", "边看边买估算收益", "视频认领结算收益", "频道会员结算收益"])
    ws_cc.append([datetime(2022, 5, 1), 673.0, 0.0, 0.0, 0.0, 0.0])
    wb_cc.save(dayu_rev / "YOUKU revenus CC.xlsx")

    wb_ltv = openpyxl.Workbook()
    ws_ltv = wb_ltv.active
    ws_ltv.title = "Feuil1"
    ws_ltv.append(["时间", "广告分成结算收益", "优酷粉丝激励", "边看边买估算收益", "视频认领结算收益", "频道会员结算收益"])
    ws_ltv.append(["2022-05-01", 336.5, 0.0, 0.0, 0.0, 0.0])
    ws_dup = wb_ltv.create_sheet("Sheet1")
    ws_dup.append([datetime(2022, 5, 1), 9999.0])  # must be ignored
    wb_ltv.save(dayu_rev / "YOUKU revenus LTV.xlsx")

    # 2. DaYu CC Vues WT with swapped headers & boundary cutoff 0 vs max views
    wb_v1 = openpyxl.Workbook()
    ws_v1 = wb_v1.active
    ws_v1.append(["日期", "播放", "评论", "点赞", "分享"])
    ws_v1.append(["2022-05-01", 0, 0, 0, 0])  # cutoff zero
    wb_v1.save(dayu_cc / "file1.xlsx")

    wb_v2 = openpyxl.Workbook()
    ws_v2 = wb_v2.active
    ws_v2.append(["日期", "播放", "点赞", "评论", "分享"])  # swapped likes & comments
    ws_v2.append(["2022-05-01", 120000, 15, 3, 2])
    wb_v2.save(dayu_cc / "file2.xlsx")

    # 2b. Legacy pre-2019-04-17 DaYu file where '评论' is Watch Time (min) and '点赞' is UV
    wb_v_leg = openpyxl.Workbook()
    ws_v_leg = wb_v_leg.active
    ws_v_leg.append(["日期", "播放", "点赞", "评论", "分享"])
    ws_v_leg.append(["2018-04-30", 100000, 8000, 6000.0, 0.85])
    wb_v_leg.save(dayu_cc / "file_legacy_2018.xlsx")

    # 3. Open Platform monthly revenue (with Total Monthly revenue column that must NOT be summed)
    wb_rev = openpyxl.Workbook()
    ws_avod = wb_rev.active
    ws_avod.title = "Monthly_AVOD_revenue_album"
    ws_avod.append(["Contract ID", "C1", "C2", None])
    ws_avod.append(["Album title in Chinese", "汽车城之拖车汤姆", "和迷你卡车学习", None])
    ws_avod.append(["IP", "TOM", "TINY", "Total Monthly revenue"])
    ws_avod.append([datetime(2021, 5, 1), 645.0, 0.0, 645.0])

    ws_svod = wb_rev.create_sheet("Monthly_SVOD_revenue_album")
    ws_svod.append(["Contract ID", "BQ1"])
    ws_svod.append(["Album title in Chinese", "大脚卡车镇第二季"])
    ws_svod.append(["IP", "MTS2"])
    ws_svod.append([datetime(2021, 5, 1), 322.5])
    wb_rev.save(op_dir / "Youku_Monthly_Revenue.xlsx")

    # 4. Open Platform Views per Series (AVOD views + SVOD watch hours, overlapping file dedup)
    wb_opv1 = openpyxl.Workbook()
    ws_opv1 = wb_opv1.active
    ws_opv1.append(["节目名称", "日期", "有效播放量"])
    ws_opv1.append(["汽车城之拖车汤姆", "20210501", 50000])
    wb_opv1.save(op_views / "tom1.xlsx")

    wb_opv2 = openpyxl.Workbook()
    ws_opv2 = wb_opv2.active
    ws_opv2.append(["节目名称", "日期", "有效播放量"])
    ws_opv2.append(["汽车城之拖车汤姆", "20210501", 50000])
    wb_opv2.save(op_views / "tom2.xlsx")

    wb_wt = openpyxl.Workbook()
    ws_wt = wb_wt.active
    ws_wt.append(["节目名称", "日期", "会员有效观影时长"])
    ws_wt.append(["大脚卡车镇 第二季", "20210501", 10.5])  # hours
    wb_wt.save(op_views / "mts2_wt.xlsx")

    events = parse_youku_directory(tmp_path)
    summary = summarize_youku_events(events)

    assert len(events) == 5  # DAYU_CC (2 dates), DAYU_LTV, OP_TOM, OP_MTS2
    assert summary["total_views"] == 270000  # 120000 + 100000 + 50000
    assert summary["total_watch_hours"] == pytest.approx(110.5)  # 10.5h SVOD + 100.0h DaYu legacy
    # CNY: DaYu CC 673 + DaYu LTV 336.5 + OP AVOD 645 (not 1290) + OP SVOD 322.5 = 1977.0
    assert summary["total_cny"] == pytest.approx(1977.0)
    # USD: 673/6.73 (100) + 336.5/6.73 (50) + 645/6.45 (100) + 322.5/6.45 (50) = 300.0
    assert summary["total_usd"] == pytest.approx(300.0)

    ev_cc = next(e for e in events if e["payload"]["video_id"] == "YOUKU_DAYU_CC" and e["payload"]["date"] == "2022-05-01")
    assert ev_cc["payload"]["extra_metrics"]["likes"] == 15
    assert ev_cc["payload"]["extra_metrics"]["comments"] == 3
    assert ev_cc["payload"]["ip_name"] == "CARCITY"

    ev_cc_leg = next(e for e in events if e["payload"]["video_id"] == "YOUKU_DAYU_CC" and e["payload"]["date"] == "2018-04-30")
    assert ev_cc_leg["metadata"]["offer_type"] == "AVOD"
    assert ev_cc_leg["payload"]["extra_metrics"]["estimated_minutes_watched"] == pytest.approx(6000.0)
    assert ev_cc_leg["payload"]["extra_metrics"]["likes"] == 0
    assert ev_cc_leg["payload"]["extra_metrics"]["comments"] == 0


def test_youku_parser_real_directory_totals():
    real_dir = Path("/home/jgarcia/matching_AI/data/Youku")
    if not real_dir.exists():
        pytest.skip("data/Youku directory not present")
    events = parse_youku_directory(real_dir)
    summary = summarize_youku_events(events)
    assert summary["total_events"] == 25769
    assert summary["total_views"] == 3303197211
    assert summary["total_watch_hours"] == pytest.approx(60931520.50, abs=1.0)
    assert summary["total_cny"] == pytest.approx(4173238.33, abs=0.2)
    assert summary["total_usd"] == pytest.approx(617527.55, abs=0.5)
    # Pre-2019-04-17 legacy DaYu files must have zero polluted likes/comments
    ev_2018 = [e for e in events if e["payload"]["date"].startswith("2018-")]
    assert sum(e["payload"]["extra_metrics"]["likes"] for e in ev_2018) == 0
    assert sum(e["payload"]["extra_metrics"]["comments"] for e in ev_2018) == 0


def test_consolidate_four_platforms_series_ip_and_episode_modes():
    rows = [
        _make_row_pair("2021", "youtube", "CARCITY", "MONSTER_TOWN", revenue=500.0, views=100000, watch_time=5000.0),
        _make_row_pair("2021", "amazon", "CARCITY", "MONSTER_TOWN", revenue=300.0, views=10000, watch_time=2000.0, video_id="EP_1"),
        _make_row_pair(
            "2021", "tencent", "SHARK_ACADEMY", "SHARK_ACADEMY",
            revenue=200.0, views=4000, watch_time=0.0, season=0, episode_number=0,
            episode_name="Shark Academy (Tencent SVOD)", video_id="TENCENT_SVOD_SHK",
            channel_id="TENCENT_SVOD", geography="CN", language_code="zh",
            revenue_cny=1290.0, revenue_svod=200.0, monetization_model="SVOD",
        ),
        _make_row_pair(
            "2021", "youku", "CARCITY", "MONSTER_TOWN",
            revenue=150.0, views=250000, watch_time=1200.0, season=0, episode_number=0,
            episode_name="Monster Town S2 (Youku Open)", video_id="YOUKU_OP_MTS2",
            channel_id="YOUKU_OPEN_PLATFORM", geography="CN", language_code="zh",
            revenue_cny=967.5, revenue_avod=50.0, revenue_svod=100.0,
            subplatform="Open Platform", monetization_model="AVOD+SVOD",
        ),
        _make_row_pair(
            "2021", "youku", "CARCITY", "CARCITY_DAYU_CHANNEL",
            revenue=80.0, views=400000, watch_time=0.0, season=0, episode_number=0,
            episode_name="Car City (Youku DaYu)", video_id="YOUKU_DAYU_CC",
            channel_id="YOUKU_DAYU_CC", geography="CN", language_code="zh",
            revenue_cny=516.0, revenue_avod=80.0, likes=300, comments=45,
            subplatform="DaYu Platform", monetization_model="AVOD",
        ),
    ]
    report_fin = pd.DataFrame([r[0] for r in rows])
    report_op = pd.DataFrame([r[1] for r in rows])

    # 1. Series / IP Mode across all 4 platforms
    res_sip = consolidate_multiplatform_reports(
        report_fin,
        report_op,
        agg_level="Por Serie / IP (Comparativa Multiplataforma)",
        use_youtube=True,
        use_amazon=True,
        use_tencent=True,
        use_youku=True,
    )
    rep_piv, df_totals = res_sip["comparative"]
    df_yku, df_totals_yku = res_sip["youku"]

    mt_row = rep_piv[rep_piv["series_name"] == "MONSTER_TOWN"].iloc[0]
    assert mt_row["revenue_youtube"] == pytest.approx(500.0)
    assert mt_row["revenue_amazon"] == pytest.approx(300.0)
    assert mt_row["revenue_tencent"] == pytest.approx(0.0)
    assert mt_row["revenue_youku"] == pytest.approx(150.0)
    assert mt_row["total_revenue"] == pytest.approx(950.0)
    assert mt_row["watch_time_youku"] == pytest.approx(1200.0)
    assert mt_row["total_watch_time"] == pytest.approx(8200.0)

    tot0 = df_totals.iloc[0]
    assert tot0["revenue_youku"] == pytest.approx(230.0)
    assert tot0["views_youku"] == 650000
    assert tot0["watch_time_youku"] == pytest.approx(1200.0)
    assert tot0["total_revenue"] == pytest.approx(1230.0)

    assert len(df_yku) == 2
    assert df_totals_yku.iloc[0]["revenue"] == pytest.approx(230.0)
    assert df_totals_yku.iloc[0]["likes"] == 300
    assert df_totals_yku.iloc[0]["comments"] == 45
    assert df_totals_yku.iloc[0]["watch_time"] == pytest.approx(1200.0)

    # 2. Episode Mode excludes China rows from report_piv while retaining in df_totals
    res_ep = consolidate_multiplatform_reports(
        report_fin,
        report_op,
        agg_level="Episodio Canónico (Todas las versiones)",
        use_youtube=True,
        use_amazon=True,
        use_tencent=True,
        use_youku=True,
    )
    rep_piv_ep, df_tot_ep = res_ep["comparative"]
    assert "revenue_youku" not in rep_piv_ep.columns
    assert "CARCITY_DAYU_CHANNEL" not in set(rep_piv_ep["series_name"])
    assert df_tot_ep.iloc[0]["revenue_youku"] == pytest.approx(230.0)
    assert df_tot_ep.iloc[0]["total_revenue"] == pytest.approx(1230.0)

    # 3. Legacy 6-tuple compatibility preserved
    legacy = consolidate_reports(
        report_fin[report_fin["platform"].isin(["youtube", "amazon"])],
        report_op[report_op["platform"].isin(["youtube", "amazon"])],
        "Episodio Canónico (Todas las versiones)",
    )
    assert len(legacy) == 6


def test_fetch_youku_reports_daily_proration_and_filters():
    fake_db = _FakeMongoDB({
        "video_performance_events": [
            {
                "_id": {
                    "video_id": "YOUKU_DAYU_CC",
                    "month": "2021-05-10",
                    "platform": "youku",
                    "geography": "CN",
                },
                "mongo_title": "Car City (Youku DaYu)",
                "mongo_ip": "CARCITY",
                "mongo_series": "CARCITY_DAYU_CHANNEL",
                "revenue": 100.0,
                "revenue_cny": 645.0,
                "revenue_avod": 100.0,
                "revenue_svod": 0.0,
                "views": 100000,
                "watch_time": 0.0,
                "likes": 50,
                "comments": 5,
            },
            {
                "_id": {
                    "video_id": "YOUKU_OP_CARL",
                    "month": "2021-05-10",
                    "platform": "youku",
                    "geography": "CN",
                },
                "mongo_title": "Super Truck (Youku Open)",
                "mongo_ip": "CARCITY",
                "mongo_series": "SUPER_TRUCK",
                "revenue": 0.0,
                "revenue_cny": 0.0,
                "revenue_avod": 0.0,
                "revenue_svod": 0.0,
                "views": 25000,
                "watch_time": 0.0,
                "likes": 0,
                "comments": 0,
            },
        ],
        "monthly_performance_summaries": [
            {
                "_id": {
                    "video_id": "YOUKU_OP_CARL",
                    "month": "2021-05",
                    "geography": "CN",
                },
                "mongo_title": "Super Truck (Youku Open)",
                "mongo_ip": "CARCITY",
                "mongo_series": "SUPER_TRUCK",
                "revenue": 310.0,
                "revenue_cny": 1999.5,
                "revenue_avod": 310.0,
                "revenue_svod": 0.0,
            }
        ],
    })

    # Mid-month daily range [2021-05-10..2021-05-11]: DaYu keeps 100.0 native + OP gets 2/31 of 310.0 = 20.0
    fin, op = fetch_youku_reports(
        fake_db,
        temp_mode="daily",
        fecha_inicio=datetime(2021, 5, 10),
        fecha_fin=datetime(2021, 5, 11),
    )
    assert fin["revenue"].sum() == pytest.approx(120.0)
    assert op["views"].sum() == 125000

    # Channel sub-filter: Open Platform only
    fin_op, _ = fetch_youku_reports(
        fake_db,
        temp_mode="daily",
        fecha_inicio=datetime(2021, 5, 10),
        fecha_fin=datetime(2021, 5, 11),
        global_channels=["Youku (Open Platform)"],
    )
    assert (fin_op["subplatform"] == "Open Platform").all()
    assert fin_op["revenue"].sum() == pytest.approx(20.0)

    # Filename convention with all 4 platforms
    fn = generate_export_filename(
        {
            "fecha_inicio": datetime(2020, 1, 1),
            "fecha_fin": datetime(2024, 12, 31),
            "temp_mode": "yearly",
            "agg_level": "Por Serie / IP (Comparativa Multiplataforma)",
            "use_youtube": True,
            "use_amazon": True,
            "use_tencent": True,
            "use_youku": True,
        },
        table_type="comparative",
        platform_override=None,
        ext="xlsx",
    )
    assert fn == "2020__2024_Youtube_Amazon_Tencent_Youku_yearly_comparative_by_series_ip.xlsx"
