"""Tests for iQIYI parsing, reconciliation, Mongo fetch, and 5-platform dashboard consolidation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from apps.dashboard.pages.business_reports import (
    consolidate_multiplatform_reports,
    consolidate_reports,
    fetch_iqiyi_reports,
    generate_export_filename,
)
from core.domain.china import get_iqiyi_series_metadata
from core.ingestion.iqiyi_parser import parse_iqiyi_directory, summarize_iqiyi_events

REAL_IQIYI_DIR = Path(__file__).resolve().parent.parent / "data" / "Iqiyi"


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
        "ad_revenue": revenue if platform == "youtube" else 0.0,
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
        "ad_impressions": 1000 if platform == "youtube" else 0,
        "likes": 0,
        "comments": comments,
    }
    if subplatform is not None:
        fin["subplatform"] = subplatform
        op["subplatform"] = subplatform
    if monetization_model is not None:
        fin["monetization_model"] = monetization_model
        op["monetization_model"] = monetization_model
    return fin, op


def _write_xlsx(path: Path, rows: list[list], sheet_name: str = "sheet1", extra_sheets: dict[str, list[list]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for r in rows:
        ws.append(r)
    if extra_sheets:
        for name, srows in extra_sheets.items():
            ews = wb.create_sheet(title=name)
            for r in srows:
                ews.append(r)
    wb.save(path)


def _write_minimal_xls_via_xml_or_xlwt_fallback(path: Path, rows: list[list]) -> None:
    """Writes a tiny binary BIFF8 .xls workbook without external xlwt dependency? Not needed if .xlsx is supported,
    EXCEPT parser checks .xls/.xlsx — we can test .xlsx across Revenue subdirs AND test real .xls on data/Iqiyi!"""
    _write_xlsx(path, rows)


def test_iqiyi_domain_metadata_mappings():
    cc_ch = get_iqiyi_series_metadata("2463347304")
    assert cc_ch["ip_name"] == "CARCITY"
    assert cc_ch["series_name"] == "CARCITY_IQIYI_CHANNEL"

    ltv_ch = get_iqiyi_series_metadata("2484062153")
    assert ltv_ch["ip_name"] == "CHANNEL_LEVEL"
    assert ltv_ch["series_name"] == "IQIYI_LTV_CHANNEL"

    sh_ch = get_iqiyi_series_metadata("4318775981759616")
    assert sh_ch["ip_name"] == "CHANNEL_LEVEL"
    assert sh_ch["series_name"] == "IQIYI_SHANGHAI_CHANNEL"

    assert get_iqiyi_series_metadata("One ZeeZ 萌宝儿歌")["ip_name"] == "ONE_ZEES"
    assert get_iqiyi_series_metadata("OneZeeZ 萌宝儿歌")["series_name"] == "ONE_ZEES_S1"
    assert get_iqiyi_series_metadata("汽车城之警车和消防车+英文版")["series_name"] == "CAR_PATROL"
    assert get_iqiyi_series_metadata("动物汽车岛之乔尼特工队 第2季")["series_name"] == "ANIMACARS_DAILY_LIFE"
    assert get_iqiyi_series_metadata("和恐龙戴诺学习 第3季")["ip_name"] == "LEARN_TV"
    assert get_iqiyi_series_metadata("恐龙戴诺之趣味学常识")["series_name"] == "DINO_SVOD_FUN_KNOWLEDGE"
    assert get_iqiyi_series_metadata("迷你卡车之趣味想象力篇")["ip_name"] == "TINY_WORLD"


def test_iqiyi_synthetic_reconciliation_and_dedup(tmp_path: Path):
    base = tmp_path / "Iqiyi"

    # 1. CC AVOD overlap: settled 收入概览_视频 overrides unsettled ~¥30/day in 2021-01
    _write_xlsx(
        base / "Revenue" / "Revenue CC" / "收入概览_2463347304_20210201.xlsx",
        [
            ["2021年01月01日至2021年01月02日 总收入", "60.00"],
            ["日期", "视频广告收入", "打赏收入", "总收入（元）"],
            ["2021-01-01", "30.00", "0.00", "30.00"],
            ["2021-01-02", "30.00", "0.00", "30.00"],
        ],
    )
    _write_xlsx(
        base / "Revenue" / "Revenue CC" / "收入概览_视频_NOV20_MAY17_21.xlsx",
        [
            ["2020年11月01日至2021年05月17日 视频-累计收入", "2000.00"],
            ["日期", "贴片广告分成", "信息流广告分成", "小视频广告分成", "总收入（元）"],
            ["2021-01-01", "990.00", "10.00", "0.00", "1000.00"],
            ["2021-01-02", "-", "-", "-", "-"],  # Falls back cleanly to 30.00 from 总收入
        ],
    )

    # 2. LTV AVOD must ignore 儿童会员收入 (SVOD) to avoid double counting SVOD
    _write_xlsx(
        base / "Revenue" / "Revenue LTV" / "收入概览_2484062153_20220503.xlsx",
        [
            ["2022年04月01日至2022年04月01日", "1050.00"],
            ["日期", "视频广告收入", "儿童会员收入", "打赏收入", "总收入（元）"],
            ["2022-04-01", "50.00", "1000.00", "0.00", "1050.00"],
        ],
    )

    # 3. SVOD Era 2 (2021-10): Monthly Revenue says 趣味学常识 = 0, while mislabeled perIP falsely says 500
    _write_xlsx(
        base / "Albums" / "Album Perf SVOD" / "Monthly Revenue" / "儿童收入按内容查看明细_2484062153_20230301.xlsx",
        [
            ["2021年10月01日至2021年10月31日累计收入金额（元）", "3100.00"],
            ["剧集", "总计", "有效付费点播量", "有效付费时长（时）"],
            ["汽车城之友爱互助篇", "3100.00", "10000", "0"],
            ["迷你卡车之趣味学常识", "0.00", "0", "0"],
        ],
    )
    _write_xlsx(
        base / "Revenue" / "Revenue SVOD per IP" / "迷你卡车之趣味学常识_2484062153_20211104.xlsx",
        [
            ["2021年10月01日至2021年10月31日", "500.00"],
            ["日期", "有效付费点播量", "付费分成收入", "广告播放量", "广告分成收入"],
            ["2021-10-15", "2000", "500.00", "0", "0.00"],
        ],
    )
    # Also Era 3 (2022-04): Watch hours per IP
    _write_xlsx(
        base / "Revenue" / "Revenue SVOD per IP" / "汽车城之友爱互助篇收入明细_2484062153_20240724.xlsx",
        [
            ["2022年04月01日至2022年04月01日", "1000.00"],
            ["日期", "总计（元）", "有效付费点播分成（元）", "有效付费时长分成（元）", "有效付费时长（时）", "广告分成（元）"],
            ["2022-04-01", "1000.00", "0.00", "900.00", "3000", "100.00"],
        ],
    )

    # 4. Views: Per Series (ignoring Total_Adjust) + duplicate Vues affichées ignored + Old/Détail CC only < 2018-04-01
    _write_xlsx(
        base / "Views" / "Per Series" / "Total_Adjust_2017-2018.xlsx",
        [["日期", "播放量", "涨粉量", "评论量"], ["2018-03-01", 99999999, 0, 0]],
    )
    _write_xlsx(
        base / "Views" / "Per Series" / "汽车城之友爱互助篇_专辑详情数据_2463347304_20240614.xlsx",
        [["日期", "播放量", "涨粉量", "评论量"], ["2018-04-01", 5000, 1, 2]],
    )
    _write_xlsx(
        base / "Albums" / "Album Perf SVOD" / "Vues affichées" / "汽车城之友爱互助篇_2484062153_2020.xlsx",
        [["日期", "播放量", "涨粉量", "评论量"], ["2018-04-01", 5000, 1, 2]],
    )
    _write_xlsx(
        base / "Old" / "Détail CC" / "CC detail 02.04.2018.xlsx",
        [["日期", "2018-03-31", "2018-04-01"], ["汽车城之友爱互助篇", 4000, 5000]],
        sheet_name="剧集播放量",
    )

    events = parse_iqiyi_directory(base)
    summary = summarize_iqiyi_events(events)

    # Total revenue: CC AVOD (1000 + 30) + LTV AVOD (50) + SVOD 2021-10 (3100, NOT +500!) + SVOD 2022-04 (1000) = 5180.00
    assert summary["total_cny"] == pytest.approx(5180.00, rel=1e-5)
    assert summary["total_avod_cny"] == pytest.approx(1080.00, rel=1e-5)
    assert summary["total_svod_cny"] == pytest.approx(4100.00, rel=1e-5)
    # Total views: 2018-03-31 (4000) + 2018-04-01 (5000, NOT doubled by Vues affichees or Old 04-01 or Total_Adjust) = 9000
    assert summary["total_views"] == 9000
    assert summary["total_watch_hours"] == pytest.approx(3000.0, rel=1e-5)
    assert summary["total_comments"] == 2
    assert summary["unmatched"] == []


@pytest.mark.skipif(not REAL_IQIYI_DIR.exists(), reason="Real data/Iqiyi directory not present")
def test_iqiyi_real_directory_reconciliation():
    events = parse_iqiyi_directory(REAL_IQIYI_DIR)
    summary = summarize_iqiyi_events(events)

    assert summary["total_events"] == 141645
    assert summary["unmatched"] == []
    assert summary["total_views"] == 12312348182
    assert summary["total_watch_hours"] == pytest.approx(3369434.0, abs=0.5)
    assert summary["total_comments"] == 76254
    assert summary["total_avod_cny"] == pytest.approx(4808579.08, abs=0.5)
    assert summary["total_svod_cny"] == pytest.approx(14604707.12, abs=0.5)
    assert summary["total_cny"] == pytest.approx(19413286.20, abs=0.5)
    assert summary["total_usd"] == pytest.approx(2861337.88, abs=1.0)


def test_fetch_iqiyi_reports_and_filters():
    fake_db = _FakeMongoDB(
        {
            "yearly_performance_summaries": [
                {
                    "_id": {"video_id": "IQIYI_CC_CHANNEL", "month": "2023", "platform": "iqiyi", "geography": "CN"},
                    "mongo_title": "Amuse CC Channel (iQIYI)",
                    "mongo_ip": "CARCITY",
                    "mongo_series": "CARCITY_IQIYI_CHANNEL",
                    "revenue": 1000.0,
                    "revenue_cny": 7080.0,
                    "revenue_avod": 1000.0,
                    "revenue_svod": 0.0,
                    "views": 5000000,
                    "watch_time": 0.0,
                    "comments": 0,
                },
                {
                    "_id": {"video_id": "IQIYI_SERIES_DINO_LUDIQUE", "month": "2023", "platform": "iqiyi", "geography": "CN"},
                    "mongo_title": "Dino: Fun Knowledge (iQIYI)",
                    "mongo_ip": "LEARN_TV",
                    "mongo_series": "DINO_SVOD_FUN_KNOWLEDGE",
                    "revenue": 500.0,
                    "revenue_cny": 3540.0,
                    "revenue_avod": 0.0,
                    "revenue_svod": 500.0,
                    "views": 200000,
                    "watch_time": 60000.0,  # 1,000 hours in minutes
                    "comments": 45,
                },
                {
                    "_id": {"video_id": "IQIYI_SHANGHAI_CHANNEL", "month": "2025", "platform": "iqiyi", "geography": "CN"},
                    "mongo_title": "Amuse Shanghai Channel (iQIYI)",
                    "mongo_ip": "CHANNEL_LEVEL",
                    "mongo_series": "IQIYI_SHANGHAI_CHANNEL",
                    "revenue": 250.0,
                    "revenue_cny": 1800.0,
                    "revenue_avod": 50.0,
                    "revenue_svod": 200.0,
                    "views": 0,
                    "watch_time": 0.0,
                    "comments": 0,
                },
            ]
        }
    )

    fin_all, op_all = fetch_iqiyi_reports(
        db_mongo=fake_db,
        temp_mode="yearly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2025, 12, 31),
        global_ips=[],
        global_series=[],
        global_channels=[],
        global_producers=[],
        selected_geo_codes=[],
        selected_lang_codes=[],
    )
    assert len(fin_all) == 3
    assert fin_all["revenue"].sum() == pytest.approx(1750.0, abs=0.01)
    assert op_all.loc[op_all["video_id"] == "IQIYI_SERIES_DINO_LUDIQUE", "watch_time"].iloc[0] == pytest.approx(1000.0)

    # Channel filter for Amuse Shanghai only
    fin_sh, _ = fetch_iqiyi_reports(
        db_mongo=fake_db,
        temp_mode="yearly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2025, 12, 31),
        global_ips=[],
        global_series=[],
        global_channels=["iQIYI (Amuse Shanghai)"],
        global_producers=[],
        selected_geo_codes=[],
        selected_lang_codes=[],
    )
    assert len(fin_sh) == 1
    assert fin_sh["video_id"].iloc[0] == "IQIYI_SHANGHAI_CHANNEL"

    # Geo filter excluding CN returns empty
    fin_us, _ = fetch_iqiyi_reports(
        db_mongo=fake_db,
        temp_mode="yearly",
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2025, 12, 31),
        global_ips=[],
        global_series=[],
        global_channels=[],
        global_producers=[],
        selected_geo_codes=["US"],
        selected_lang_codes=[],
    )
    assert fin_us.empty


def test_five_platform_consolidation_episode_and_series_modes():
    rows = [
        _make_row_pair("2023", "youtube", "CARCITY", "TOM_THE_TOW_TRUCK", 100.0, 1000, watch_time=50.0, video_id="yt1"),
        _make_row_pair("2023", "amazon", "CARCITY", "TOM_THE_TOW_TRUCK", 40.0, 200, watch_time=20.0, video_id="amz1"),
        _make_row_pair("2023", "tencent", "CARCITY", "CHANNEL_LEVEL", 30.0, 300, watch_time=0.0, video_id="TCN_AVOD", geography="CN", language_code="zh", revenue_cny=212.0, revenue_avod=30.0),
        _make_row_pair("2023", "youku", "CARCITY", "TOM_THE_TOW_TRUCK", 25.0, 400, watch_time=10.0, video_id="YOUKU_OP_TOM", geography="CN", language_code="zh", revenue_cny=177.0, revenue_avod=25.0, subplatform="Open Platform", monetization_model="AVOD"),
        _make_row_pair("2023", "iqiyi", "CARCITY", "TOM_THE_TOW_TRUCK", 80.0, 900, watch_time=30.0, video_id="IQIYI_SERIES_TOM_S1", geography="CN", language_code="zh", revenue_cny=566.4, revenue_svod=80.0, comments=12, subplatform="Amuse CC (2463347304)", monetization_model="SVOD"),
    ]
    df_fin = pd.DataFrame([r[0] for r in rows])
    df_op = pd.DataFrame([r[1] for r in rows])

    # 1. Episode mode: China excluded from report_piv, ALL 5 included in df_totals!
    res_ep = consolidate_multiplatform_reports(
        df_fin, df_op, "Episodio Canónico (Todas las versiones)",
        use_youtube=True, use_amazon=True, use_tencent=True, use_youku=True, use_iqiyi=True,
    )
    piv_ep, tot_ep = res_ep["comparative"]
    assert set(piv_ep["platform"].unique()) == {"YouTube & Amazon"} if "platform" in piv_ep.columns else True
    assert "revenue_iqiyi" not in piv_ep.columns
    assert tot_ep["total_revenue"].iloc[0] == pytest.approx(275.0)
    assert tot_ep["revenue_iqiyi"].iloc[0] == pytest.approx(80.0)
    assert tot_ep["total_views"].iloc[0] == 2800
    assert tot_ep["views_iqiyi"].iloc[0] == 900
    assert tot_ep["watch_time_iqiyi"].iloc[0] == pytest.approx(30.0)
    assert tot_ep["total_watch_time"].iloc[0] == pytest.approx(110.0)  # yt(50)+amz(20)+yku(10)+iqy(30)

    df_iqy, df_tot_iqy = res_ep["iqiyi"]
    assert not df_iqy.empty
    assert df_tot_iqy["revenue"].iloc[0] == pytest.approx(80.0)
    assert df_tot_iqy["comments"].iloc[0] == 12

    # 2. Series/IP comparative mode: TOM_THE_TOW_TRUCK aligns YouTube + Amazon + Youku + iQIYI on the same row!
    res_ip = consolidate_multiplatform_reports(
        df_fin, df_op, "Por Serie / IP (Comparativa Multiplataforma)",
        use_youtube=True, use_amazon=True, use_tencent=True, use_youku=True, use_iqiyi=True,
    )
    piv_ip, tot_ip = res_ip["comparative"]
    tom_row = piv_ip[piv_ip["series_name"] == "TOM_THE_TOW_TRUCK"].iloc[0]
    assert tom_row["revenue_youtube"] == pytest.approx(100.0)
    assert tom_row["revenue_amazon"] == pytest.approx(40.0)
    assert tom_row["revenue_youku"] == pytest.approx(25.0)
    assert tom_row["revenue_iqiyi"] == pytest.approx(80.0)
    assert tom_row["views_iqiyi"] == 900
    assert tom_row["watch_time_iqiyi"] == pytest.approx(30.0)
    assert tot_ip["total_revenue"].iloc[0] == pytest.approx(275.0)

    # 3. Export filename & backward compatible 6-tuple consolidate_reports
    fn = generate_export_filename(
        {"temp_mode": "yearly", "fecha_inicio": datetime(2023, 1, 1), "fecha_fin": datetime(2023, 12, 31)},
        table_type="detailed",
        platform_override="Iqiyi",
        ext="xlsx",
    )
    assert "Iqiyi" in fn
    six_tuple = consolidate_reports(df_fin, df_op, "Episodio Canónico (Todas las versiones)")
    assert len(six_tuple) == 6
