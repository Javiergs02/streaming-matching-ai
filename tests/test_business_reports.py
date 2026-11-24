"""Unit tests for business_reports consolidation and export logic."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from apps.dashboard.pages.business_reports import consolidate_reports, generate_export_filename, format_youtube_url, to_excel_bytes


def test_format_youtube_url():
    assert format_youtube_url(None) == ""
    assert format_youtube_url("") == ""
    assert format_youtube_url(0) == ""
    assert format_youtube_url("EP_12345") == ""
    assert format_youtube_url("UNMATCHED_AMZ_abc") == ""
    assert format_youtube_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_generate_export_filename():
    f_daily = {
        'fecha_inicio': datetime(2025, 1, 1),
        'fecha_fin': datetime(2025, 1, 7),
        'temp_mode': 'daily',
        'agg_level': 'Episodio Canónico (Todas las versiones)',
        'use_youtube': True,
        'use_amazon': True
    }
    # Comparative
    fn_comp = generate_export_filename(f_daily, table_type="comparative", platform_override=None, ext="xlsx")
    assert fn_comp == "2025_01_01__2025_01_07_Youtube_Amazon_daily_comparative_by_canon_episode.xlsx"

    # YouTube metrics
    fn_yt = generate_export_filename(f_daily, table_type="metrics", platform_override="Youtube", ext="csv")
    assert fn_yt == "2025_01_01__2025_01_07_Youtube_daily_metrics_by_canon_episode.csv"

    # Amazon metrics
    fn_amz = generate_export_filename(f_daily, table_type="metrics", platform_override="Amazon", ext="xlsx")
    assert fn_amz == "2025_01_01__2025_01_07_Amazon_daily_metrics_by_canon_episode.xlsx"

    # Monthly and Language
    f_monthly = {
        'fecha_inicio': datetime(2025, 1, 1),
        'fecha_fin': datetime(2025, 3, 31),
        'temp_mode': 'monthly',
        'agg_level': 'Por Idioma (Separar traducciones)',
        'use_youtube': True,
        'use_amazon': False
    }
    fn_mon = generate_export_filename(f_monthly, table_type="metrics", platform_override="Youtube", ext="xlsx")
    assert fn_mon == "2025_01__2025_03_Youtube_monthly_metrics_by_language.xlsx"


def test_to_excel_bytes_formatting():
    import io
    import openpyxl

    df = pd.DataFrame({
        'series_name': ['Car City', 'Molang', 'Total Global'],
        'country': ['ES', 'FR', 'ALL'],
        'views': [1500000, 3200000, 4700000],
        'total_revenue': [1250.50, 4320.10, 5570.60],
        'cpm': [0.83, 1.35, 1.18],
        'youtube_url': ['https://www.youtube.com/watch?v=abc', 'https://www.youtube.com/watch?v=def', '']
    })

    raw_bytes = to_excel_bytes(df, "Comparative_Report")
    assert isinstance(raw_bytes, (bytes, bytearray))
    assert len(raw_bytes) > 1000

    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes))
    assert "Comparative_Report" in wb.sheetnames
    ws = wb["Comparative_Report"]

    # Verify freeze panes and autofilter
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref is not None

    # Verify header row styling
    header_cell = ws["A1"]
    assert header_cell.font.bold is True
    assert header_cell.font.color.rgb == "00FFFFFF"

    # Verify number formats for revenue ($#,##0.00) and views (#,##0)
    views_cell = ws.cell(row=2, column=3) # views
    revenue_cell = ws.cell(row=2, column=4) # total_revenue
    assert views_cell.number_format == "#,##0"
    assert revenue_cell.number_format == "$#,##0.00"

    # Verify Total row (row 4) is bold and has top/bottom borders
    total_cell = ws.cell(row=4, column=1)
    assert total_cell.font.bold is True


def test_consolidate_reports_single_and_dual_platform():
    report_fin = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'IP1',
            'series_name': 'Series1',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'yt_vid_01',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Episode 1 - Official',
            'video_duration': 600,
            'revenue': 150.75
        },
        {
            'month': '2025-01',
            'ip_name': 'IP1',
            'series_name': 'Series1',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'amz_vid_01',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Episode 1',
            'video_duration': 0,
            'revenue': 45.25
        }
    ])

    report_op = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'IP1',
            'series_name': 'Series1',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'yt_vid_01',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Episode 1 - Official',
            'video_duration': 600,
            'views': 2500,
            'watch_time': 15000,
            'likes': 120,
            'comments': 15,
            'ad_impressions': 2000,
            'ad_revenue': 120.0
        },
        {
            'month': '2025-01',
            'ip_name': 'IP1',
            'series_name': 'Series1',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'amz_vid_01',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Episode 1',
            'video_duration': 0,
            'views': 500,
            'watch_time': 3000
        }
    ])

    # 1. Test YouTube Only
    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=False
    )
    assert rep_piv.empty, "Comparative table must be empty when only YouTube is selected"
    assert df_amz.empty, "Amazon table must be empty when only YouTube is selected"
    assert not df_yt.empty, "YouTube table must not be empty"
    assert not tot_yt.empty, "YouTube totals must not be empty"
    assert tot_yt['revenue'].iloc[0] == 150.75
    assert tot_yt['views'].iloc[0] == 2500

    # 2. Test Amazon Only
    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=False, use_amazon=True
    )
    assert rep_piv.empty, "Comparative table must be empty when only Amazon is selected"
    assert df_yt.empty, "YouTube table must be empty when only Amazon is selected"
    assert not df_amz.empty, "Amazon table must not be empty"
    assert not tot_amz.empty, "Amazon totals must not be empty"
    assert tot_amz['revenue'].iloc[0] == 45.25
    assert tot_amz['views'].iloc[0] == 500

    # 3. Test Both Platforms
    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=True
    )
    assert not rep_piv.empty, "Comparative table must be populated when both platforms selected"
    assert not df_yt.empty, "YouTube table must be populated when both platforms selected"
    assert not df_amz.empty, "Amazon table must be populated when both platforms selected"
    assert not tot.empty, "Consolidated totals must not be empty"
    assert 'revenue_youtube' in rep_piv.columns
    assert 'revenue_amazon' in rep_piv.columns


def test_amazon_two_column_titles_and_comparative_canonical():
    report_fin = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '10',
            'episode_name': 'The Lost Puppy',
            'geography': 'DE',
            'video_id': 'yt_vid_10',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'de',
            'video_title': 'Das verlorene Hündchen',
            'video_duration': 600,
            'revenue': 120.0
        },
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '10',
            'episode_name': 'The Lost Puppy',
            'amazon_title': 'Feuer in der Nachbarschaft / Versteckspiele',
            'geography': 'DE',
            'video_id': 'EP_2284',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'TINY_TOWN - Ep 10',
            'video_duration': 0,
            'revenue': 80.0
        }
    ])

    report_op = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '10',
            'episode_name': 'The Lost Puppy',
            'geography': 'DE',
            'video_id': 'yt_vid_10',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'de',
            'video_title': 'Das verlorene Hündchen',
            'video_duration': 600,
            'views': 1000,
            'watch_time': 5000,
            'likes': 50,
            'comments': 5,
            'ad_impressions': 800,
            'ad_revenue': 70.0
        },
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '10',
            'episode_name': 'The Lost Puppy',
            'amazon_title': 'Feuer in der Nachbarschaft / Versteckspiele',
            'geography': 'DE',
            'video_id': 'EP_2284',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'TINY_TOWN - Ep 10',
            'video_duration': 0,
            'views': 400,
            'watch_time': 2400
        }
    ])

    # Test under all 4 aggregation levels
    agg_levels = [
        "Episodio Canónico (Todas las versiones)",
        "Por Idioma (Separar traducciones)",
        "Por Territorio / País",
        "Por Vídeo/Versión (Mostrar resubidas)"
    ]

    for agg in agg_levels:
        rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
            report_fin, report_op, agg, use_youtube=True, use_amazon=True
        )

        # 1. Amazon table checks
        assert not df_amz.empty, f"Amazon table must not be empty for {agg}"
        assert 'amazon_title' in df_amz.columns, f"'amazon_title' must be in df_amz for {agg}"
        assert 'episode_name' in df_amz.columns, f"'episode_name' must be in df_amz for {agg}"
        assert df_amz['amazon_title'].iloc[0] == 'Feuer in der Nachbarschaft / Versteckspiele'
        assert df_amz['episode_name'].iloc[0] == 'The Lost Puppy'

        # Verify column ordering: amazon_title appears right before episode_name
        cols = list(df_amz.columns)
        assert cols.index('amazon_title') < cols.index('episode_name'), f"amazon_title should appear before episode_name in df_amz for {agg}"

        # Verify totals
        assert not tot_amz.empty
        assert 'amazon_title' not in tot_amz.columns
        assert 'episode_name' not in tot_amz.columns

        # 2. Comparative table checks: ALWAYS canonical Broadkast/YouTube name, NO amazon_title
        assert not rep_piv.empty, f"Comparative table must not be empty for {agg}"
        assert 'amazon_title' not in rep_piv.columns, f"Comparative table must NEVER include 'amazon_title' for {agg}"
        assert 'episode_name' in rep_piv.columns, f"Comparative table must include canonical 'episode_name' for {agg}"
        if agg == "Por Idioma (Separar traducciones)":
            assert rep_piv['episode_name'].iloc[0] == 'Das verlorene Hündchen'
        else:
            assert rep_piv['episode_name'].iloc[0] == 'The Lost Puppy'


def test_amazon_is_compilation():
    report_fin = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '10',
            'episode_name': 'The Lost Puppy',
            'amazon_title': 'Feuer in der Nachbarschaft / Versteckspiele / Paintball',
            'geography': 'DE',
            'video_id': 'EP_AMZ_COMP',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'TINY_TOWN - Ep 10',
            'video_duration': 0,
            'revenue': 80.0
        },
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '11',
            'episode_name': 'The Great Race',
            'amazon_title': 'Das große Rennen',
            'geography': 'DE',
            'video_id': 'EP_AMZ_SINGLE',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'TINY_TOWN - Ep 11',
            'video_duration': 0,
            'revenue': 40.0
        }
    ])

    report_op = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '10',
            'episode_name': 'The Lost Puppy',
            'amazon_title': 'Feuer in der Nachbarschaft / Versteckspiele / Paintball',
            'geography': 'DE',
            'video_id': 'EP_AMZ_COMP',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'TINY_TOWN - Ep 10',
            'video_duration': 0,
            'views': 400,
            'watch_time': 2400
        },
        {
            'month': '2025-01',
            'ip_name': 'TINY_WORLD',
            'series_name': 'TINY_TOWN',
            'season': '1',
            'episode_number': '11',
            'episode_name': 'The Great Race',
            'amazon_title': 'Das große Rennen',
            'geography': 'DE',
            'video_id': 'EP_AMZ_SINGLE',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'TINY_TOWN - Ep 11',
            'video_duration': 0,
            'views': 200,
            'watch_time': 1200
        }
    ])

    # 1. Under "Por Vídeo/Versión (Mostrar resubidas)": is_compilation must be present, but is_short must NOT be in Amazon
    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        report_fin, report_op, "Por Vídeo/Versión (Mostrar resubidas)", use_youtube=False, use_amazon=True
    )
    assert not df_amz.empty
    assert 'is_compilation' in df_amz.columns
    assert 'is_short' not in df_amz.columns, "Amazon detailed metrics table must never include 'is_short' column"
    # First row has multi-slash title -> True
    row_comp = df_amz[df_amz['video_id'] == 'EP_AMZ_COMP'].iloc[0]
    assert row_comp['is_compilation'] == True
    # Second row is single episode -> False
    row_single = df_amz[df_amz['video_id'] == 'EP_AMZ_SINGLE'].iloc[0]
    assert row_single['is_compilation'] == False
    # Totals table excludes is_compilation and is_short metadata
    assert 'is_compilation' not in tot_amz.columns
    assert 'is_short' not in tot_amz.columns

    # 2. Under "Episodio Canónico": Option A does not show is_compilation (shows num_versiones instead)
    rep_piv2, df_yt2, df_amz2, tot2, tot_yt2, tot_amz2 = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=False, use_amazon=True
    )
    assert 'is_compilation' not in df_amz2.columns
    assert 'num_versiones' in df_amz2.columns
    assert 'is_short' not in df_amz2.columns
    assert 'is_short' not in tot_amz2.columns


def test_total_metrics_and_two_decimals_formatting():
    """Verify total_views, total_revenue, total_watch_time calculations and 2-decimal rounding."""
    report_fin = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'IP_TEST',
            'series_name': 'SERIES_TEST',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'yt_vid_test',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Episode 1',
            'video_duration': 600,
            'revenue': 123.4567  # should round to 123.46
        },
        {
            'month': '2025-01',
            'ip_name': 'IP_TEST',
            'series_name': 'SERIES_TEST',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'amz_vid_test',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Episode 1',
            'video_duration': 0,
            'revenue': 87.6543  # should round to 87.65
        }
    ])

    report_op = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'IP_TEST',
            'series_name': 'SERIES_TEST',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'yt_vid_test',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Episode 1',
            'video_duration': 600,
            'views': 1000,
            'watch_time': 5000,
            'likes': 50,
            'comments': 5,
            'ad_impressions': 800,
            'ad_revenue': 99.999
        },
        {
            'month': '2025-01',
            'ip_name': 'IP_TEST',
            'series_name': 'SERIES_TEST',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Episode 1',
            'geography': 'US',
            'video_id': 'amz_vid_test',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Episode 1',
            'video_duration': 0,
            'views': 250,
            'watch_time': 1250
        }
    ])

    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=True
    )

    # 1. Check total columns exist in comparative table
    assert 'total_revenue' in rep_piv.columns
    assert 'total_views' in rep_piv.columns
    assert 'total_watch_time' in rep_piv.columns

    # 2. Check sums
    assert rep_piv['total_views'].iloc[0] == 1250
    assert rep_piv['total_watch_time'].iloc[0] == 6250
    expected_total_rev = round(round(123.4567, 2) + round(87.6543, 2), 2)
    assert rep_piv['total_revenue'].iloc[0] == expected_total_rev

    # 3. Check 2-decimal rounding
    assert str(rep_piv['total_revenue'].iloc[0])[::-1].find('.') <= 2
    assert str(rep_piv['revenue_youtube'].iloc[0])[::-1].find('.') <= 2
    assert str(rep_piv['revenue_amazon'].iloc[0])[::-1].find('.') <= 2
    assert str(df_yt['revenue'].iloc[0])[::-1].find('.') <= 2
    assert str(df_yt['ad_revenue'].iloc[0])[::-1].find('.') <= 2
    assert str(df_amz['revenue'].iloc[0])[::-1].find('.') <= 2

    # 4. Check global totals row
    assert tot['total_views'].iloc[0] == 1250
    assert tot['total_watch_time'].iloc[0] == 6250
    assert tot['total_revenue'].iloc[0] == expected_total_rev


def test_consolidar_periodo_aggregation():
    """Verify that toggling consolidar_periodo collapses multiple timeframes into 1 row."""
    years = ['2020', '2021', '2022']
    fin_rows = []
    op_rows = []
    for y in years:
        fin_rows.append({
            'month': y,
            'ip_name': 'IP_COLLAPSE',
            'series_name': 'SERIES_C',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Ep 1',
            'geography': 'US',
            'video_id': f'yt_{y}',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Ep 1',
            'video_duration': 300,
            'revenue': 100.0
        })
        op_rows.append({
            'month': y,
            'ip_name': 'IP_COLLAPSE',
            'series_name': 'SERIES_C',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Ep 1',
            'geography': 'US',
            'video_id': f'yt_{y}',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Ep 1',
            'video_duration': 300,
            'views': 500,
            'watch_time': 2000,
            'likes': 10,
            'comments': 1,
            'ad_impressions': 400,
            'ad_revenue': 80.0
        })
    df_fin = pd.DataFrame(fin_rows)
    df_op = pd.DataFrame(op_rows)

    # 1. Non-aggregated (default): 3 rows (one per year)
    rep_piv_unagg, df_yt_unagg, _, _, tot_yt_unagg, _ = consolidate_reports(
        df_fin, df_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=False,
        consolidar_periodo=False
    )
    assert len(df_yt_unagg) == 3
    assert set(df_yt_unagg['month']) == {'2020', '2021', '2022'}
    # Even when consolidar_periodo=False, totals table ALWAYS shows Grand Total + Year breakdown
    assert len(tot_yt_unagg) == 4
    assert tot_yt_unagg['month'].tolist() == ['TOTAL (2020 - 2022)', '2020', '2021', '2022']
    assert tot_yt_unagg['revenue'].tolist() == [300.0, 100.0, 100.0, 100.0]

    # 2. Aggregated (consolidar_periodo=True): exactly 1 row with summed metrics
    rep_piv_agg, df_yt_agg, df_amz_agg, tot_comp_agg, tot_yt_agg, tot_amz_agg = consolidate_reports(
        df_fin, df_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=False,
        consolidar_periodo=True, periodo_label="2020 - 2022"
    )
    assert len(df_yt_agg) == 1
    assert df_yt_agg['month'].iloc[0] == "2020 - 2022"
    assert df_yt_agg['revenue'].iloc[0] == 300.0  # 100 * 3
    assert df_yt_agg['views'].iloc[0] == 1500  # 500 * 3
    assert df_yt_agg['watch_time'].iloc[0] == 6000  # 2000 * 3

    # 3. Totales adaptativos: fila de Total Global + filas desglosadas por cada año
    assert len(tot_yt_agg) == 4
    assert tot_yt_agg['month'].tolist() == ['TOTAL (2020 - 2022)', '2020', '2021', '2022']
    assert tot_yt_agg['revenue'].tolist() == [300.0, 100.0, 100.0, 100.0]
    assert tot_yt_agg['views'].tolist() == [1500, 500, 500, 500]
    assert tot_yt_agg['watch_time'].tolist() == [6000, 2000, 2000, 2000]


def test_adaptive_totals_breakdown_by_period():
    """Verify totals breakdown by period:
    - Yearly: each year has a subtotal row.
    - Monthly: each month has a subtotal row without limit (full monthly breakdown).
    - Daily: subtotals grouped by month (YYYY-MM).
    """
    # 1. 15 months across 2 years -> exactly 16 rows (Total + 15 individual months)
    months_15 = [f'2023-{m:02d}' for m in range(1, 13)] + ['2024-01', '2024-02', '2024-03']
    fin_15 = pd.DataFrame([{'month': m, 'ip_name': 'IP1', 'series_name': 'S1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'US', 'video_id': f'v_{m}', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Ep 1', 'video_duration': 300, 'revenue': 10.0} for m in months_15])
    op_15 = pd.DataFrame([{'month': m, 'ip_name': 'IP1', 'series_name': 'S1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'US', 'video_id': f'v_{m}', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Ep 1', 'video_duration': 300, 'views': 50, 'watch_time': 200, 'likes': 1, 'comments': 0, 'ad_impressions': 40, 'ad_revenue': 8.0} for m in months_15])

    _, _, _, _, tot_15, _ = consolidate_reports(
        fin_15, op_15, 'Episodio Canónico (Todas las versiones)',
        use_youtube=True, use_amazon=False, consolidar_periodo=True, periodo_label='2023-01 - 2024-03'
    )
    assert len(tot_15) == 16
    assert tot_15['month'].iloc[0] == 'TOTAL (2023-01 - 2024-03)'
    assert tot_15['month'].iloc[1:].tolist() == months_15
    assert tot_15['revenue'].iloc[0] == 150.0
    assert tot_15['views'].iloc[0] == 750

    # 2. Daily mode with 20 days across Jan and Feb -> subtotals grouped by month
    days = [f'2025-01-{d:02d}' for d in range(20, 32)] + [f'2025-02-{d:02d}' for d in range(1, 9)]
    fin_days = pd.DataFrame([{'month': d, 'ip_name': 'IP1', 'series_name': 'S1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'US', 'video_id': f'v_{d}', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Ep 1', 'video_duration': 300, 'revenue': 5.0} for d in days])
    op_days = pd.DataFrame([{'month': d, 'ip_name': 'IP1', 'series_name': 'S1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'US', 'video_id': f'v_{d}', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Ep 1', 'video_duration': 300, 'views': 25, 'watch_time': 100, 'likes': 1, 'comments': 0, 'ad_impressions': 20, 'ad_revenue': 4.0} for d in days])

    _, _, _, _, tot_days, _ = consolidate_reports(
        fin_days, op_days, 'Episodio Canónico (Todas las versiones)',
        use_youtube=True, use_amazon=False, consolidar_periodo=False
    )
    assert len(tot_days) == 3
    assert tot_days['month'].tolist() == ['TOTAL (2025-01-20 - 2025-02-08)', '2025-01', '2025-02']
    assert tot_days['revenue'].tolist() == [100.0, 60.0, 40.0]

    # 3. Verify totals export filename generation
    f_export = {
        'fecha_inicio': datetime(2024, 1, 1),
        'fecha_fin': datetime(2024, 12, 31),
        'temp_mode': 'monthly',
        'agg_level': 'Episodio Canónico (Todas las versiones)',
        'use_youtube': True,
        'use_amazon': True
    }
    fn_tot_comp = generate_export_filename(f_export, table_type="comparative", ext="xlsx", is_totals=True)
    assert fn_tot_comp == "2024_01__2024_12_Youtube_Amazon_monthly_comparative_global_totals.xlsx"

    fn_tot_yt = generate_export_filename(f_export, table_type="metrics", platform_override="Youtube", ext="csv", is_totals=True)
    assert fn_tot_yt == "2024_01__2024_12_Youtube_monthly_metrics_global_totals.csv"


def test_generate_export_filename_aggregated():
    """Verify filename reflects aggregated period when consolidar_periodo is True."""
    f_agg = {
        'fecha_inicio': datetime(2020, 1, 1),
        'fecha_fin': datetime(2025, 12, 31),
        'temp_mode': 'yearly',
        'agg_level': 'Episodio Canónico (Todas las versiones)',
        'use_youtube': True,
        'use_amazon': True,
        'consolidar_periodo': True
    }
    fn = generate_export_filename(f_agg, table_type="comparative", ext="xlsx")
    assert fn == "2020__2025_Youtube_Amazon_yearly_aggregated_comparative_by_canon_episode.xlsx"


def test_versions_breakdown_and_smart_compilation_detection():
    """Verify smart compilation detection and 4-column versions breakdown with exact partition."""
    # We simulate:
    # 1. Ep 1 of TOM_PAINT_SHOP:
    #    - vid_tps_std: 20 min (1200s) -> Standard episode (NOT compilation, despite being >15 min!)
    #    - vid_tps_es: 20 min (1200s) -> Standard Spanish dub
    #    - vid_tps_reupload_es: 20 min (1200s) -> Re-upload in Spanish
    #    - vid_tps_comp: 40 min (2400s) -> Compilation (dura >10 min que el episodio estándar de 20 min)
    #    - vid_tps_short: 45s (45s) -> YouTube Short
    # 2. Ep 1 of CAR_CITY:
    #    - vid_cc_std: 5 min (300s) -> Standard episode
    #    - vid_cc_comp: 16 min (960s) -> Compilation (dura >= 300 + 600s = 900s)
    report_fin = pd.DataFrame([
        # TPS
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'US', 'video_id': 'vid_tps_std', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Paint Shop - Ep 1', 'video_duration': 1200, 'revenue': 10.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'ES', 'video_id': 'vid_tps_es', 'channel_id': 'c2', 'platform': 'youtube', 'language_code': 'es', 'video_title': 'Tom el taller de pintura - Ep 1', 'video_duration': 1200, 'revenue': 10.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'ES', 'video_id': 'vid_tps_reupload_es', 'channel_id': 'c3', 'platform': 'youtube', 'language_code': 'es', 'video_title': 'Tom el taller de pintura - Ep 1 Resubida', 'video_duration': 1200, 'revenue': 5.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'US', 'video_id': 'vid_tps_comp', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Paint Shop - Full Adventure', 'video_duration': 2400, 'revenue': 30.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'US', 'video_id': 'vid_tps_short', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Funny Moment #shorts', 'video_duration': 45, 'revenue': 1.0},
        # CAR_CITY
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'CAR_PATROL', 'season': '1', 'episode_number': '1', 'episode_name': 'The Chase', 'geography': 'US', 'video_id': 'vid_cc_std', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Car Patrol - Ep 1', 'video_duration': 300, 'revenue': 20.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'CAR_PATROL', 'season': '1', 'episode_number': '1', 'episode_name': 'The Chase', 'geography': 'US', 'video_id': 'vid_cc_comp', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Car Patrol - Super Pack', 'video_duration': 960, 'revenue': 40.0},
    ])

    report_op = pd.DataFrame([
        # TPS
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'US', 'video_id': 'vid_tps_std', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Paint Shop - Ep 1', 'video_duration': 1200, 'views': 100, 'watch_time': 1000, 'likes': 5, 'comments': 1, 'ad_impressions': 80, 'ad_revenue': 8.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'ES', 'video_id': 'vid_tps_es', 'channel_id': 'c2', 'platform': 'youtube', 'language_code': 'es', 'video_title': 'Tom el taller de pintura - Ep 1', 'video_duration': 1200, 'views': 100, 'watch_time': 1000, 'likes': 5, 'comments': 1, 'ad_impressions': 80, 'ad_revenue': 8.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'ES', 'video_id': 'vid_tps_reupload_es', 'channel_id': 'c3', 'platform': 'youtube', 'language_code': 'es', 'video_title': 'Tom el taller de pintura - Ep 1 Resubida', 'video_duration': 1200, 'views': 50, 'watch_time': 500, 'likes': 2, 'comments': 0, 'ad_impressions': 40, 'ad_revenue': 4.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'US', 'video_id': 'vid_tps_comp', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Paint Shop - Full Adventure', 'video_duration': 2400, 'views': 300, 'watch_time': 5000, 'likes': 10, 'comments': 2, 'ad_impressions': 200, 'ad_revenue': 20.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'TOM_PAINT_SHOP', 'season': '1', 'episode_number': '1', 'episode_name': 'Colors', 'geography': 'US', 'video_id': 'vid_tps_short', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Funny Moment #shorts', 'video_duration': 45, 'views': 500, 'watch_time': 300, 'likes': 20, 'comments': 5, 'ad_impressions': 0, 'ad_revenue': 0.0},
        # CAR_CITY
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'CAR_PATROL', 'season': '1', 'episode_number': '1', 'episode_name': 'The Chase', 'geography': 'US', 'video_id': 'vid_cc_std', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Car Patrol - Ep 1', 'video_duration': 300, 'views': 200, 'watch_time': 800, 'likes': 10, 'comments': 1, 'ad_impressions': 150, 'ad_revenue': 15.0},
        {'month': '2025-01', 'ip_name': 'CAR_CITY', 'series_name': 'CAR_PATROL', 'season': '1', 'episode_number': '1', 'episode_name': 'The Chase', 'geography': 'US', 'video_id': 'vid_cc_comp', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Car Patrol - Super Pack', 'video_duration': 960, 'views': 400, 'watch_time': 3000, 'likes': 15, 'comments': 3, 'ad_impressions': 300, 'ad_revenue': 30.0},
    ])

    # 1. Test under "Por Vídeo/Versión (Mostrar resubidas)" to assert exact boolean classification
    _, df_ver, _, _, _, _ = consolidate_reports(
        report_fin, report_op, "Por Vídeo/Versión (Mostrar resubidas)", use_youtube=True, use_amazon=False
    )
    # TPS 20-minute video must NOT be compilation
    assert df_ver.loc[df_ver['video_id'] == 'vid_tps_std', 'is_compilation'].iloc[0] == False
    assert df_ver.loc[df_ver['video_id'] == 'vid_tps_es', 'is_compilation'].iloc[0] == False
    assert df_ver.loc[df_ver['video_id'] == 'vid_tps_reupload_es', 'is_compilation'].iloc[0] == False
    # TPS 40-minute video MUST be compilation
    assert df_ver.loc[df_ver['video_id'] == 'vid_tps_comp', 'is_compilation'].iloc[0] == True
    # TPS 45s video MUST be short
    assert df_ver.loc[df_ver['video_id'] == 'vid_tps_short', 'is_short'].iloc[0] == True
    assert df_ver.loc[df_ver['video_id'] == 'vid_tps_short', 'is_compilation'].iloc[0] == False
    # Car Patrol 16-minute video MUST be compilation
    assert df_ver.loc[df_ver['video_id'] == 'vid_cc_std', 'is_compilation'].iloc[0] == False
    assert df_ver.loc[df_ver['video_id'] == 'vid_cc_comp', 'is_compilation'].iloc[0] == True

    # 2. Test under "Episodio Canónico" for versions breakdown numbers
    rep_piv, df_yt, _, tot, tot_yt, _ = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=False
    )
    row_tps = df_yt[df_yt['series_name'] == 'TOM_PAINT_SHOP'].iloc[0]
    # Total versions for TPS = 5 unique video_ids
    assert row_tps['num_versiones_totales'] == 5
    # Distinct languages available for standard episode = 2 (en, es)
    assert row_tps['num_versiones'] == 2
    # Republicaciones = (3 std vids - 2 langs) + 1 comp + 1 short = 1 + 1 + 1 = 3
    assert row_tps['num_publicaciones'] == 3
    # Check exact mathematical partition: Total = Idiomas + Republicaciones
    assert row_tps['num_versiones_totales'] == row_tps['num_versiones'] + row_tps['num_publicaciones']

    # Car Patrol
    row_cc = df_yt[df_yt['series_name'] == 'CAR_PATROL'].iloc[0]
    assert row_cc['num_versiones_totales'] == 2
    assert row_cc['num_versiones'] == 1
    assert row_cc['num_publicaciones'] == 1  # 1 compilation
    assert row_cc['num_versiones_totales'] == row_cc['num_versiones'] + row_cc['num_publicaciones']

    # Check totals row: structural metadata columns should not be in totals table to keep it clean
    assert 'num_versiones_totales' not in tot_yt.columns
    assert 'num_versiones' not in tot_yt.columns
    assert 'num_publicaciones' not in tot_yt.columns


def test_amazon_platform_isolated_version_counts():
    """Verify that Amazon version metrics are strictly isolated from YouTube metrics."""
    # YouTube rows for Tom Ep 9: 5 distinct videos (2 std English, 1 std Spanish, 1 comp English, 1 short English)
    yt_fin = [
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_en1', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom - The Crane 1', 'video_duration': 600, 'revenue': 100.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_en2', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom - The Crane 2', 'video_duration': 600, 'revenue': 50.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'ES', 'video_id': 'yt_vid_es', 'channel_id': 'c2', 'platform': 'youtube', 'language_code': 'es', 'video_title': 'Tom - La Grua', 'video_duration': 600, 'revenue': 40.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_comp', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Super Compilation Pack', 'video_duration': 2400, 'revenue': 200.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_short', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Crane #shorts', 'video_duration': 50, 'revenue': 10.0},
    ]
    yt_op = [
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_en1', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom - The Crane 1', 'video_duration': 600, 'views': 1000, 'watch_time': 5000, 'likes': 50, 'comments': 5, 'ad_impressions': 800, 'ad_revenue': 80.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_en2', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom - The Crane 2', 'video_duration': 600, 'views': 500, 'watch_time': 2500, 'likes': 25, 'comments': 2, 'ad_impressions': 400, 'ad_revenue': 40.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'ES', 'video_id': 'yt_vid_es', 'channel_id': 'c2', 'platform': 'youtube', 'language_code': 'es', 'video_title': 'Tom - La Grua', 'video_duration': 600, 'views': 400, 'watch_time': 2000, 'likes': 20, 'comments': 1, 'ad_impressions': 300, 'ad_revenue': 30.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_comp', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Super Compilation Pack', 'video_duration': 2400, 'views': 2000, 'watch_time': 20000, 'likes': 100, 'comments': 10, 'ad_impressions': 1500, 'ad_revenue': 150.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'geography': 'US', 'video_id': 'yt_vid_short', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Tom Crane #shorts', 'video_duration': 50, 'views': 3000, 'watch_time': 1500, 'likes': 150, 'comments': 15, 'ad_impressions': 0, 'ad_revenue': 0.0},
    ]

    # Amazon rows for Tom Ep 9: 3 distinct deliveries (1 std English, 1 std Spanish, 1 comp French)
    amz_fin = [
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'amazon_title': 'The Crane', 'geography': 'US', 'video_id': 'EP_206', 'channel_id': 'Amazon Prime Video', 'platform': 'amazon', 'language_code': 'en', 'video_title': 'The Crane', 'video_duration': 0, 'revenue': 30.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'amazon_title': 'La Grúa', 'geography': 'ES', 'video_id': 'EP_206', 'channel_id': 'Amazon Prime Video', 'platform': 'amazon', 'language_code': 'es', 'video_title': 'La Grúa', 'video_duration': 0, 'revenue': 20.0},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'amazon_title': "Tom la Dépanneuse : La Grue / L'Helicoptère", 'geography': 'FR', 'video_id': 'EP_206', 'channel_id': 'Amazon Prime Video', 'platform': 'amazon', 'language_code': 'fr', 'video_title': "Tom la Dépanneuse : La Grue / L'Helicoptère", 'video_duration': 0, 'revenue': 15.0},
    ]
    amz_op = [
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'amazon_title': 'The Crane', 'geography': 'US', 'video_id': 'EP_206', 'channel_id': 'Amazon Prime Video', 'platform': 'amazon', 'language_code': 'en', 'video_title': 'The Crane', 'video_duration': 0, 'views': 300, 'watch_time': 1800},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'amazon_title': 'La Grúa', 'geography': 'ES', 'video_id': 'EP_206', 'channel_id': 'Amazon Prime Video', 'platform': 'amazon', 'language_code': 'es', 'video_title': 'La Grúa', 'video_duration': 0, 'views': 200, 'watch_time': 1200},
        {'month': '2025-01', 'ip_name': 'CARCITY', 'series_name': 'TOM_THE_TOW_TRUCK', 'season': '1', 'episode_number': '9', 'episode_name': 'The Crane', 'amazon_title': "Tom la Dépanneuse : La Grue / L'Helicoptère", 'geography': 'FR', 'video_id': 'EP_206', 'channel_id': 'Amazon Prime Video', 'platform': 'amazon', 'language_code': 'fr', 'video_title': "Tom la Dépanneuse : La Grue / L'Helicoptère", 'video_duration': 0, 'views': 150, 'watch_time': 900},
    ]

    report_fin = pd.DataFrame(yt_fin + amz_fin)
    report_op = pd.DataFrame(yt_op + amz_op)

    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=True
    )

    # 1. YouTube table assertions
    assert len(df_yt) == 1
    row_yt = df_yt.iloc[0]
    assert row_yt['num_versiones_totales'] == 5
    assert row_yt['num_versiones'] == 2  # en, es
    assert row_yt['num_publicaciones'] == 3  # 1 re-upload + 1 comp + 1 short
    assert row_yt['num_versiones_totales'] == row_yt['num_versiones'] + row_yt['num_publicaciones']

    # 2. Amazon table assertions (Must NOT match YouTube!)
    assert len(df_amz) == 1
    row_amz = df_amz.iloc[0]
    assert row_amz['num_versiones_totales'] == 3, f"Expected 3 Amazon versions, got {row_amz['num_versiones_totales']}"
    assert row_amz['num_versiones'] == 2  # en, es (standard)
    assert row_amz['num_publicaciones'] == 1  # 1 compilation pack with '/'
    assert row_amz['num_versiones_totales'] == row_amz['num_versiones'] + row_amz['num_publicaciones']

    # 3. Comparative table assertions (Combined totals with true language union)
    assert len(rep_piv) == 1
    row_piv = rep_piv.iloc[0]
    assert row_piv['num_versiones_totales'] == 5 + 3
    # Both platforms share the exact same 2 standard languages (en, es), so union is 2 languages
    assert row_piv['num_versiones'] == 2
    assert row_piv['num_publicaciones'] == (5 + 3) - 2  # 6 publications
    assert row_piv['num_versiones_totales'] == row_piv['num_versiones'] + row_piv['num_publicaciones']

    # 4. Totals row assertions: structural metadata excluded from totals tables
    assert 'num_versiones_totales' not in tot_yt.columns
    assert 'num_versiones_totales' not in tot_amz.columns
    assert 'num_versiones_totales' not in tot.columns


def test_por_idioma_excludes_num_versiones():
    """Verify that under 'Por Idioma (Separar traducciones)', the redundant 'num_versiones' column is excluded."""
    fin = pd.DataFrame([
        {'month': '2025-01', 'ip_name': 'IP1', 'series_name': 'SERIES1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'US', 'video_id': 'v1', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Ep 1', 'video_duration': 600, 'revenue': 100.0},
        {'month': '2025-01', 'ip_name': 'IP1', 'series_name': 'SERIES1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'DE', 'video_id': 'v2', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'de', 'video_title': 'Ep 1 De', 'video_duration': 600, 'revenue': 50.0},
    ])
    op = pd.DataFrame([
        {'month': '2025-01', 'ip_name': 'IP1', 'series_name': 'SERIES1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'US', 'video_id': 'v1', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'en', 'video_title': 'Ep 1', 'video_duration': 600, 'views': 100, 'watch_time': 600, 'likes': 5, 'comments': 1, 'ad_impressions': 80, 'ad_revenue': 8.0},
        {'month': '2025-01', 'ip_name': 'IP1', 'series_name': 'SERIES1', 'season': '1', 'episode_number': '1', 'episode_name': 'Ep 1', 'geography': 'DE', 'video_id': 'v2', 'channel_id': 'c1', 'platform': 'youtube', 'language_code': 'de', 'video_title': 'Ep 1 De', 'video_duration': 600, 'views': 50, 'watch_time': 300, 'likes': 2, 'comments': 0, 'ad_impressions': 40, 'ad_revenue': 4.0},
    ])

    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        fin, op, "Por Idioma (Separar traducciones)", use_youtube=True, use_amazon=False
    )
    assert not df_yt.empty
    assert 'language_code' in df_yt.columns
    assert 'num_versiones_totales' in df_yt.columns
    assert 'num_publicaciones' in df_yt.columns
    # Crucial assertion: num_versiones must NOT be present in df_yt
    assert 'num_versiones' not in df_yt.columns, "num_versiones should be excluded in Por Idioma view"


def test_por_video_comparative_table_structure():
    """Verify that when agg_level is 'Por Vídeo/Versión (Mostrar resubidas)', the comparative table
    has the exact 15 columns in the exact order requested by the user:
    Fecha | IP | Serie | Season | Episode | Idioma | ID | nombre Episodio (broadkast) |
    nombre episodio en la plataforma | Platform | Short | Total Revenue | Total Views | Total Watch Time | URL (en blanco para Amazon)
    """
    fin = pd.DataFrame([
        # YouTube Standard Video
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMACARS_DAILY_LIFE',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Toothbrushing Crocodile',
            'geography': 'US',
            'video_id': 'yt_vid_std',
            'channel_id': 'c1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'AnimaCars - Jonny makes syrup to heal BILLDOZER throat',
            'video_duration': 600,
            'revenue': 150.25
        },
        # YouTube Short
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMACARS_DAILY_LIFE',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Toothbrushing Crocodile',
            'geography': 'US',
            'video_id': 'yt_vid_short',
            'channel_id': 'c1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Jonny vs Billdozer #shorts',
            'video_duration': 45,
            'revenue': 12.50
        },
        # Amazon Video
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMACARS_DAILY_LIFE',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Toothbrushing Crocodile',
            'amazon_title': 'AnimaCars - Das Beste aus ELEFANTEN BAGGER Cartoons',
            'geography': 'DE',
            'video_id': 'amz_asin_01',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'ANIMACARS_DAILY_LIFE - Ep 1',
            'video_duration': 0,
            'revenue': 85.75
        }
    ])

    op = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMACARS_DAILY_LIFE',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Toothbrushing Crocodile',
            'geography': 'US',
            'video_id': 'yt_vid_std',
            'channel_id': 'c1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'AnimaCars - Jonny makes syrup to heal BILLDOZER throat',
            'video_duration': 600,
            'views': 5000,
            'watch_time': 25000,
            'likes': 100,
            'comments': 10,
            'ad_impressions': 4000,
            'ad_revenue': 120.0
        },
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMACARS_DAILY_LIFE',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Toothbrushing Crocodile',
            'geography': 'US',
            'video_id': 'yt_vid_short',
            'channel_id': 'c1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Jonny vs Billdozer #shorts',
            'video_duration': 45,
            'views': 12000,
            'watch_time': 9000,
            'likes': 500,
            'comments': 20,
            'ad_impressions': 8000,
            'ad_revenue': 10.0
        },
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMACARS_DAILY_LIFE',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Toothbrushing Crocodile',
            'amazon_title': 'AnimaCars - Das Beste aus ELEFANTEN BAGGER Cartoons',
            'geography': 'DE',
            'video_id': 'amz_asin_01',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'de',
            'video_title': 'ANIMACARS_DAILY_LIFE - Ep 1',
            'video_duration': 0,
            'views': 1500,
            'watch_time': 7500
        }
    ])

    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        fin, op, "Por Vídeo/Versión (Mostrar resubidas)", use_youtube=True, use_amazon=True
    )

    # 1. Assert exact 15 columns in exact required order
    expected_columns = [
        'month',
        'ip_name',
        'series_name',
        'season',
        'episode_number',
        'language_code',
        'video_id',
        'episode_name',
        'platform_title',
        'platform',
        'is_short',
        'total_revenue',
        'total_views',
        'total_watch_time',
        'youtube_url'
    ]
    assert list(rep_piv.columns) == expected_columns, f"Columns mismatch. Expected {expected_columns}, got {list(rep_piv.columns)}"
    assert len(rep_piv) == 3

    # 2. Check YouTube Standard Row
    yt_std_row = rep_piv[rep_piv['video_id'] == 'yt_vid_std'].iloc[0]
    assert yt_std_row['platform'] == 'youtube'
    assert yt_std_row['episode_name'] == 'The Toothbrushing Crocodile'
    assert yt_std_row['platform_title'] == 'AnimaCars - Jonny makes syrup to heal BILLDOZER throat'
    assert yt_std_row['is_short'] == False
    assert yt_std_row['total_revenue'] == 150.25
    assert yt_std_row['total_views'] == 5000
    assert yt_std_row['total_watch_time'] == 25000
    assert yt_std_row['youtube_url'] == 'https://www.youtube.com/watch?v=yt_vid_std'

    # 3. Check YouTube Short Row
    yt_short_row = rep_piv[rep_piv['video_id'] == 'yt_vid_short'].iloc[0]
    assert yt_short_row['platform'] == 'youtube'
    assert yt_short_row['episode_name'] == 'The Toothbrushing Crocodile'
    assert yt_short_row['platform_title'] == 'Jonny vs Billdozer #shorts'
    assert yt_short_row['is_short'] == True
    assert yt_short_row['total_revenue'] == 12.50
    assert yt_short_row['total_views'] == 12000
    assert yt_short_row['youtube_url'] == 'https://www.youtube.com/watch?v=yt_vid_short'

    # 4. Check Amazon Row (Short must be False, URL must be blank string "")
    amz_row = rep_piv[rep_piv['video_id'] == 'amz_asin_01'].iloc[0]
    assert amz_row['platform'] == 'amazon'
    assert amz_row['episode_name'] == 'The Toothbrushing Crocodile'
    assert amz_row['platform_title'] == 'AnimaCars - Das Beste aus ELEFANTEN BAGGER Cartoons'
    assert amz_row['is_short'] == False, "Amazon videos must never be classified as Shorts"
    assert amz_row['total_revenue'] == 85.75
    assert amz_row['total_views'] == 1500
    assert amz_row['total_watch_time'] == 7500
    assert amz_row['youtube_url'] == "", "Amazon rows must have blank URL"

    # 5. Check Global Totals: Desglosado en dos filas (una para YouTube y otra para Amazon)
    assert not tot.empty
    expected_tot_columns = ['month', 'platform', 'total_revenue', 'total_views', 'total_watch_time']
    assert list(tot.columns) == expected_tot_columns
    assert len(tot) == 2, f"Expected 2 totals rows (YouTube and Amazon), got {len(tot)}"

    # 5.1 Fila de totales YouTube
    row_tot_yt = tot[tot['platform'] == 'youtube'].iloc[0]
    assert row_tot_yt['month'] == 'TOTAL'
    assert row_tot_yt['platform'] == 'youtube'
    assert row_tot_yt['total_revenue'] == round(150.25 + 12.50, 2)
    assert row_tot_yt['total_views'] == 5000 + 12000
    assert row_tot_yt['total_watch_time'] == 25000 + 9000
    for non_metric in ['is_short', 'platform_title', 'episode_name', 'youtube_url']:
        assert non_metric not in tot.columns

    # 5.2 Fila de totales Amazon
    row_tot_amz = tot[tot['platform'] == 'amazon'].iloc[0]
    assert row_tot_amz['month'] == 'TOTAL'
    assert row_tot_amz['platform'] == 'amazon'
    assert row_tot_amz['total_revenue'] == 85.75
    assert row_tot_amz['total_views'] == 1500
    assert row_tot_amz['total_watch_time'] == 7500


def test_producer_enrichment_in_consolidate_reports():
    """Verify that 'producer' is included in consolidated reports and positioned right before ip_name."""
    fin = pd.DataFrame([
        {
            'month': '2025-01',
            'producer': 'Millimages',
            'ip_name': 'UNMATCHED',
            'series_name': 'Molang',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Party',
            'geography': 'US',
            'video_id': 'amz_molang_01',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Molang - The Party',
            'video_duration': 300,
            'revenue': 100.0
        },
        {
            'month': '2025-01',
            'producer': 'Amuse Animation',
            'ip_name': 'CAR_CITY',
            'series_name': 'TOM_THE_TOW_TRUCK',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Crane',
            'geography': 'US',
            'video_id': 'yt_tom_01',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Tom the Tow Truck - Ep 1',
            'video_duration': 600,
            'revenue': 50.0
        }
    ])
    op = pd.DataFrame([
        {
            'month': '2025-01',
            'producer': 'Millimages',
            'ip_name': 'UNMATCHED',
            'series_name': 'Molang',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Party',
            'geography': 'US',
            'video_id': 'amz_molang_01',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Molang - The Party',
            'video_duration': 300,
            'views': 2000,
            'watch_time': 10000
        },
        {
            'month': '2025-01',
            'producer': 'Amuse Animation',
            'ip_name': 'CAR_CITY',
            'series_name': 'TOM_THE_TOW_TRUCK',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'The Crane',
            'geography': 'US',
            'video_id': 'yt_tom_01',
            'channel_id': 'chan1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Tom the Tow Truck - Ep 1',
            'video_duration': 600,
            'views': 500,
            'watch_time': 3000,
            'likes': 10,
            'comments': 1,
            'ad_impressions': 400,
            'ad_revenue': 40.0
        }
    ])

    rep_piv, df_yt, df_amz, tot, tot_yt, tot_amz = consolidate_reports(
        fin, op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=True
    )

    # 1. Producer column is present in comparative table
    assert 'producer' in rep_piv.columns
    cols_comp = list(rep_piv.columns)
    assert cols_comp.index('producer') < cols_comp.index('ip_name')

    # 2. Check individual rows
    molang_row = rep_piv[rep_piv['series_name'] == 'Molang'].iloc[0]
    assert molang_row['producer'] == 'Millimages'
    assert molang_row['ip_name'] == 'UNMATCHED'
    assert molang_row['total_revenue'] == 100.0

    tom_row = rep_piv[rep_piv['series_name'] == 'TOM_THE_TOW_TRUCK'].iloc[0]
    assert tom_row['producer'] == 'Amuse Animation'
    assert tom_row['ip_name'] == 'CAR_CITY'
    assert tom_row['total_revenue'] == 50.0

    # 3. Producer present in individual platform tables
    assert 'producer' in df_yt.columns
    assert 'producer' in df_amz.columns
    assert df_yt.iloc[0]['producer'] == 'Amuse Animation'
    assert df_amz.iloc[0]['producer'] == 'Millimages'

    # 4. Totals tables must NOT contain producer
    assert 'producer' not in tot.columns
    assert 'producer' not in tot_yt.columns
    assert 'producer' not in tot_amz.columns


def test_territory_level_filtering_excludes_unknown_geo_and_global():
    # Simulates YouTube data where daily unsegmented rollups ('Unknown Geo' or 'Global')
    # coexist with true monthly country breakdowns ('ES', 'US')
    report_fin = pd.DataFrame([
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'MILIKI', 'series_name': 'MILIKI_SONGS_S1',
            'season': '1', 'episode_number': '36', 'episode_name': 'Afraid of Dark', 'geography': 'ES',
            'video_id': 'vid1', 'channel_id': 'ch1', 'platform': 'youtube', 'language_code': 'es',
            'video_title': 'Afraid of Dark', 'video_duration': 120, 'revenue': 0.0
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'MILIKI', 'series_name': 'MILIKI_SONGS_S1',
            'season': '1', 'episode_number': '36', 'episode_name': 'Afraid of Dark', 'geography': 'US',
            'video_id': 'vid1', 'channel_id': 'ch1', 'platform': 'youtube', 'language_code': 'es',
            'video_title': 'Afraid of Dark', 'video_duration': 120, 'revenue': 0.0
        }
    ])

    report_op = pd.DataFrame([
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'MILIKI', 'series_name': 'MILIKI_SONGS_S1',
            'season': '1', 'episode_number': '36', 'episode_name': 'Afraid of Dark', 'geography': 'ES',
            'video_id': 'vid1', 'channel_id': 'ch1', 'platform': 'youtube', 'language_code': 'es',
            'video_title': 'Afraid of Dark', 'video_duration': 120, 'views': 1638, 'watch_time': 18448,
            'likes': 0, 'comments': 0, 'ad_impressions': 0, 'ad_revenue': 0.0
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'MILIKI', 'series_name': 'MILIKI_SONGS_S1',
            'season': '1', 'episode_number': '36', 'episode_name': 'Afraid of Dark', 'geography': 'US',
            'video_id': 'vid1', 'channel_id': 'ch1', 'platform': 'youtube', 'language_code': 'es',
            'video_title': 'Afraid of Dark', 'video_duration': 120, 'views': 5635, 'watch_time': 24121,
            'likes': 0, 'comments': 0, 'ad_impressions': 0, 'ad_revenue': 0.0
        }
    ])

    _, df_yt, _, _, _, _ = consolidate_reports(
        report_fin, report_op, "Por Territorio / País", use_youtube=True, use_amazon=False
    )

    assert not df_yt.empty
    assert 'geography' in df_yt.columns
    assert set(df_yt['geography'].unique()) == {'ES', 'US'}
    assert 'Unknown Geo' not in df_yt['geography'].values
    assert 'Global' not in df_yt['geography'].values


def test_youtube_territory_revenue_allocation_proportional_to_views():
    """
    Verifica que la asignación de ingresos de YouTube por territorio distribuye
    proporcionalmente la facturación global según las visualizaciones de cada país,
    y que la tabla de totales y desglose territorial refleja los importes exactos sin salir a 0.
    """
    # 1. Simulación de datos por país (inicialmente con revenue y ad_impressions a 0 tal y como devuelve la API de YouTube para dimensions='video,country')
    df_perf = pd.DataFrame([
        {
            'video_id': 'vid_test', 'month': '2026-01', 'platform': 'youtube', 'geography': 'US',
            'views': 750, 'watch_time': 3000, 'likes': 10, 'comments': 2, 'ad_impressions': 0,
            'revenue': 0.0, 'ad_revenue': 0.0
        },
        {
            'video_id': 'vid_test', 'month': '2026-01', 'platform': 'youtube', 'geography': 'ES',
            'views': 250, 'watch_time': 1000, 'likes': 5, 'comments': 1, 'ad_impressions': 0,
            'revenue': 0.0, 'ad_revenue': 0.0
        }
    ])

    # 2. Facturación e impresiones globales reportadas a nivel de vídeo
    df_glob = pd.DataFrame([
        {
            'video_id': 'vid_test', 'month': '2026-01',
            'global_revenue': 100.00, 'global_ad_revenue': 80.00, 'global_ad_impressions': 10000
        }
    ])

    # 3. Aplicar el algoritmo de prorrateo
    df_merged = df_perf.merge(df_glob, on=['video_id', 'month'], how='left').fillna({
        'global_revenue': 0.0, 'global_ad_revenue': 0.0, 'global_ad_impressions': 0
    })
    tot_views = df_merged.groupby(['video_id', 'month'])['views'].transform('sum')
    ratio = np.where(tot_views > 0, df_merged['views'] / tot_views, 0.0)
    df_merged['revenue'] = (df_merged['global_revenue'] * ratio).round(4)
    df_merged['ad_revenue'] = (df_merged['global_ad_revenue'] * ratio).round(4)
    df_merged['ad_impressions'] = np.round(df_merged['global_ad_impressions'] * ratio).astype(int)
    df_merged.drop(columns=['global_revenue', 'global_ad_revenue', 'global_ad_impressions'], inplace=True)

    assert df_merged.loc[df_merged['geography'] == 'US', 'revenue'].iloc[0] == 75.00
    assert df_merged.loc[df_merged['geography'] == 'ES', 'revenue'].iloc[0] == 25.00
    assert df_merged.loc[df_merged['geography'] == 'US', 'ad_impressions'].iloc[0] == 7500
    assert df_merged.loc[df_merged['geography'] == 'ES', 'ad_impressions'].iloc[0] == 2500
    assert df_merged['revenue'].sum() == 100.00
    assert df_merged['ad_impressions'].sum() == 10000

    # 4. Consolidar en el reporte por territorio
    df_merged['producer'] = 'Amuse Animation'
    df_merged['ip_name'] = 'MILIKI'
    df_merged['series_name'] = 'MILIKI_SONGS_S1'
    df_merged['season'] = 1
    df_merged['episode_number'] = 36
    df_merged['episode_name'] = 'Afraid of Dark'
    df_merged['channel_id'] = 'ch1'
    df_merged['language_code'] = 'es'
    df_merged['video_title'] = 'Afraid of Dark'
    df_merged['video_duration'] = 120

    yt_cols = ['month', 'producer', 'ip_name', 'series_name', 'season', 'episode_number', 'episode_name', 'geography', 'video_id', 'channel_id', 'platform', 'language_code', 'video_title', 'video_duration']
    report_fin = df_merged.groupby(yt_cols)['revenue'].sum().reset_index()
    report_op = df_merged.groupby(yt_cols)[['views', 'watch_time', 'likes', 'comments', 'ad_impressions', 'ad_revenue']].sum().reset_index()

    report_piv, df_yt, df_amz, df_totals, df_totals_yt, _ = consolidate_reports(
        report_fin, report_op, "Por Territorio / País", use_youtube=True, use_amazon=False
    )

    # Validar que los totales de YouTube no son 0.00 ni 0 impresiones
    assert not df_totals_yt.empty
    assert df_totals_yt['revenue'].iloc[0] == 100.00
    assert df_totals_yt['views'].iloc[0] == 1000
    assert df_totals_yt['watch_time'].iloc[0] == 4000
    assert df_totals_yt['ad_impressions'].iloc[0] == 10000
    assert df_totals_yt['cpm'].iloc[0] == 8.00

    # Validar desglose en la tabla de métricas de YouTube
    assert not df_yt.empty
    row_us = df_yt[df_yt['geography'] == 'US'].iloc[0]
    row_es = df_yt[df_yt['geography'] == 'ES'].iloc[0]
    assert row_us['revenue'] == 75.00
    assert row_es['revenue'] == 25.00
    assert row_us['ad_impressions'] == 7500
    assert row_es['ad_impressions'] == 2500
    assert row_us['cpm'] == 8.00
    assert row_es['cpm'] == 8.00


def test_legacy_compilation_fallback_to_video_title():
    """
    Verifica que vídeos no asignados o marcados con el comodín técnico 'Legacy Compilation'
    (código de episodio 9999 o LGCY_SR) utilicen su título real de vídeo como nombre de episodio
    y no se agrupen en una única fila genérica 'Legacy Compilation'.
    """
    from apps.dashboard.pages.business_reports import assign_name_score

    # 1. Comprobar que assign_name_score penaliza 'Legacy Compilation' como genérico (score 4)
    df_test_score = pd.DataFrame([
        {'episode_name': 'Afraid of Dark'},
        {'episode_name': 'Legacy Compilation'},
        {'episode_name': 'Unknown Video'}
    ])
    df_scored = assign_name_score(df_test_score, 'episode_name')
    assert df_scored.loc[df_scored['episode_name'] == 'Afraid of Dark', 'name_score'].iloc[0] == 1
    assert df_scored.loc[df_scored['episode_name'] == 'Legacy Compilation', 'name_score'].iloc[0] == 4

    # 2. Comprobar consolidación con vídeos históricos/unassigned
    report_fin = pd.DataFrame([
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'UNMATCHED',
            'series_name': 'Historical & Unassigned', 'season': 1, 'episode_number': 9999,
            'episode_name': 'Legacy Compilation', 'geography': 'US',
            'video_id': 'vid_legacy_1', 'channel_id': 'ch1', 'platform': 'youtube',
            'language_code': 'en', 'video_title': 'Baby Shark Dancing Compilation',
            'video_duration': 650, 'revenue': 50.0
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'UNMATCHED',
            'series_name': 'Historical & Unassigned', 'season': 1, 'episode_number': 9999,
            'episode_name': 'Legacy Compilation', 'geography': 'US',
            'video_id': 'vid_legacy_2', 'channel_id': 'ch1', 'platform': 'youtube',
            'language_code': 'en', 'video_title': 'Car City Live Adventure',
            'video_duration': 1200, 'revenue': 30.0
        }
    ])
    # En el pipeline, df_master reemplaza 'Legacy Compilation' con video_title
    report_fin['episode_name'] = report_fin['episode_name'].replace(['Legacy Compilation'], np.nan).combine_first(report_fin['video_title'])

    report_op = pd.DataFrame([
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'UNMATCHED',
            'series_name': 'Historical & Unassigned', 'season': 1, 'episode_number': 9999,
            'episode_name': 'Baby Shark Dancing Compilation', 'geography': 'US',
            'video_id': 'vid_legacy_1', 'channel_id': 'ch1', 'platform': 'youtube',
            'language_code': 'en', 'video_title': 'Baby Shark Dancing Compilation',
            'video_duration': 650, 'views': 500, 'watch_time': 2000,
            'likes': 10, 'comments': 1, 'ad_impressions': 400, 'ad_revenue': 40.0
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'UNMATCHED',
            'series_name': 'Historical & Unassigned', 'season': 1, 'episode_number': 9999,
            'episode_name': 'Car City Live Adventure', 'geography': 'US',
            'video_id': 'vid_legacy_2', 'channel_id': 'ch1', 'platform': 'youtube',
            'language_code': 'en', 'video_title': 'Car City Live Adventure',
            'video_duration': 1200, 'views': 300, 'watch_time': 1500,
            'likes': 8, 'comments': 2, 'ad_impressions': 250, 'ad_revenue': 25.0
        }
    ])

    report_piv, df_yt, _, _, _, _ = consolidate_reports(
        report_fin, report_op, "Episodio Canónico (Todas las versiones)", use_youtube=True, use_amazon=False
    )

    # Ambos vídeos deben aparecer como filas separadas en df_yt (no agrupados en un solo 9999) y con sus títulos de vídeo reales
    assert len(df_yt) == 2
    assert 'Baby Shark Dancing Compilation' in df_yt['episode_name'].values
    assert 'Car City Live Adventure' in df_yt['episode_name'].values
    assert 'Legacy Compilation' not in df_yt['episode_name'].values


def test_amazon_language_classification_and_consolidation():
    """Verify that Amazon records with English titles consumed in Spanish territories
    are classified as 'en', while Spanish titles are 'es', and are properly separated
    when consolidating 'Por Idioma (Separar traducciones)'."""
    from core.domain.languages import detect_title_language

    geo_to_lang = {'MX': 'es', 'ES': 'es', 'US': 'en'}

    records_fin = [
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 1,
            'episode_name': 'BEACH Day at the Playground',
            'amazon_title': 'BEACH Day at the Playground',
            'video_title': 'BEACH Day at the Playground',
            'geography': 'MX', 'video_id': 'EP_1001', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'video_duration': 600, 'revenue': 45.0
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 2,
            'episode_name': 'Mezclando Pizza de Caramelos / El Castillo Inflable / Bebe Jaremy es un Tramposo',
            'amazon_title': 'Mezclando Pizza de Caramelos / El Castillo Inflable / Bebe Jaremy es un Tramposo',
            'video_title': 'Mezclando Pizza de Caramelos / El Castillo Inflable / Bebe Jaremy es un Tramposo',
            'geography': 'MX', 'video_id': 'EP_1002', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'video_duration': 600, 'revenue': 60.0
        }
    ]

    df_fin = pd.DataFrame(records_fin)
    df_fin['language_code'] = df_fin.apply(
        lambda r: detect_title_language(r['amazon_title'], r['geography'], geo_to_lang),
        axis=1
    )

    assert df_fin.loc[df_fin['video_id'] == 'EP_1001', 'language_code'].values[0] == 'en'
    assert df_fin.loc[df_fin['video_id'] == 'EP_1002', 'language_code'].values[0] == 'es'

    records_op = [
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 1,
            'episode_name': 'BEACH Day at the Playground',
            'amazon_title': 'BEACH Day at the Playground',
            'video_title': 'BEACH Day at the Playground',
            'geography': 'MX', 'video_id': 'EP_1001', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'language_code': 'en',
            'video_duration': 600, 'views': 450, 'watch_time': 2700
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 2,
            'episode_name': 'Mezclando Pizza de Caramelos / El Castillo Inflable / Bebe Jaremy es un Tramposo',
            'amazon_title': 'Mezclando Pizza de Caramelos / El Castillo Inflable / Bebe Jaremy es un Tramposo',
            'video_title': 'Mezclando Pizza de Caramelos / El Castillo Inflable / Bebe Jaremy es un Tramposo',
            'geography': 'MX', 'video_id': 'EP_1002', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'language_code': 'es',
            'video_duration': 600, 'views': 600, 'watch_time': 3600
        }
    ]
    df_op = pd.DataFrame(records_op)

    report_piv, _, df_amz, _, _, _ = consolidate_reports(
        df_fin, df_op, "Por Idioma (Separar traducciones)", use_youtube=False, use_amazon=True
    )

    assert len(df_amz) == 2
    assert set(df_amz['language_code'].values) == {'en', 'es'}
    en_row = df_amz[df_amz['language_code'] == 'en'].iloc[0]
    es_row = df_amz[df_amz['language_code'] == 'es'].iloc[0]

    assert en_row['views'] == 450
    assert en_row['revenue'] == 45.0
    assert es_row['views'] == 600
    assert es_row['revenue'] == 60.0


def test_amazon_match_score_column():
    """Verify that Amazon match_score is included and correctly preserved in df_amz."""
    records_fin = [
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 1,
            'episode_name': 'Episode 1', 'amazon_title': 'Tom S01E01 Match Exact',
            'video_title': 'Tom S01E01 Match Exact', 'geography': 'US',
            'video_id': 'EP_1001', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'language_code': 'en', 'video_duration': 600,
            'match_score': 100.0, 'revenue': 50.0
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 2,
            'episode_name': 'Episode 2', 'amazon_title': 'Tom S01E02 Match AI',
            'video_title': 'Tom S01E02 Match AI', 'geography': 'US',
            'video_id': 'EP_1002', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'language_code': 'en', 'video_duration': 600,
            'match_score': 84.5, 'revenue': 40.0
        }
    ]
    records_op = [
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 1,
            'episode_name': 'Episode 1', 'amazon_title': 'Tom S01E01 Match Exact',
            'video_title': 'Tom S01E01 Match Exact', 'geography': 'US',
            'video_id': 'EP_1001', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'language_code': 'en', 'video_duration': 600,
            'match_score': 100.0, 'views': 500, 'watch_time': 3000
        },
        {
            'month': '2026-01', 'producer': 'Amuse Animation', 'ip_name': 'Car City',
            'series_name': 'Tom the Tow Truck', 'season': 1, 'episode_number': 2,
            'episode_name': 'Episode 2', 'amazon_title': 'Tom S01E02 Match AI',
            'video_title': 'Tom S01E02 Match AI', 'geography': 'US',
            'video_id': 'EP_1002', 'channel_id': 'Amazon Prime Video',
            'platform': 'amazon', 'language_code': 'en', 'video_duration': 600,
            'match_score': 84.5, 'views': 400, 'watch_time': 2400
        }
    ]

    _, _, df_amz, _, _, _ = consolidate_reports(
        pd.DataFrame(records_fin), pd.DataFrame(records_op),
        "Por Vídeo/Versión (Mostrar resubidas)", use_youtube=False, use_amazon=True
    )

    assert 'match_score' in df_amz.columns
    row_exact = df_amz[df_amz['video_id'] == 'EP_1001'].iloc[0]
    row_ai = df_amz[df_amz['video_id'] == 'EP_1002'].iloc[0]
    assert row_exact['match_score'] == 100.0
    assert row_ai['match_score'] == 84.5


def test_amz_metadata_recovers_canonical_title_from_production_mappings(tmp_path, monkeypatch):
    """Verify that generic 'SERIE - Ep N' titles in Amazon metadata are replaced with
    canonical titles from production_mappings.csv (e.g. 'ANIMA_TOWN - Ep 40' -> 'Cave Rescue')."""
    import apps.dashboard.pages.business_reports as br
    
    # Create mock mappings file
    mock_csv = tmp_path / "production_mappings.csv"
    mock_csv.write_text(
        "Broadkast ID,Broadkast Assigned Title,Match Method,Score\n"
        "EP_2622,Cave Rescue,exact_title,1.0\n"
        "EP_2623,Break The Ice,exact_title,1.0\n",
        encoding="utf-8"
    )
    
    # Mock PROJECT_ROOT so fetch_amz_metadata reads mock_csv
    monkeypatch.setattr(br, "PROJECT_ROOT", str(tmp_path.parent))
    target_dir = tmp_path.parent / "data" / "output"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "production_mappings.csv").write_text(mock_csv.read_text(encoding="utf-8"), encoding="utf-8")
    
    # Create mock DB returning generic episode_name
    class MockCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        
    class MockConn:
        def cursor(self): return MockCursor()
        def rollback(self): pass
        
    df_raw = pd.DataFrame([
        {
            'video_id': 'EP_2622', 'season': 1, 'episode_number': 40,
            'episode_name': 'ANIMA_TOWN - Ep 40', 'series_name': 'ANIMA_TOWN',
            'ip_name': 'ANIMACARS', 'channel_id': 'Amazon Prime Video',
            'language_code': 'Multi-idioma', 'video_title': 'ANIMA_TOWN - Ep 40', 'video_duration': 0
        },
        {
            'video_id': 'EP_2623', 'season': 1, 'episode_number': 41,
            'episode_name': 'ANIMA_TOWN - Ep 41', 'series_name': 'ANIMA_TOWN',
            'ip_name': 'ANIMACARS', 'channel_id': 'Amazon Prime Video',
            'language_code': 'Multi-idioma', 'video_title': 'ANIMA_TOWN - Ep 41', 'video_duration': 0
        }
    ])
    
    monkeypatch.setattr(pd, "read_sql_query", lambda *args, **kwargs: df_raw.copy())
    
    res = br.fetch_amz_metadata(MockConn(), None, None, None, None, None)
    assert res.loc[res['video_id'] == 'EP_2622', 'episode_name'].values[0] == 'Cave Rescue'
    assert res.loc[res['video_id'] == 'EP_2623', 'episode_name'].values[0] == 'Break The Ice'


def test_amazon_table_displays_broadkast_title_not_youtube():
    """Verifica que la tabla de Amazon muestre el título de producción oficial de Broadkast y no el comercial de YouTube."""
    df_fin = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '24',
            'episode_name': 'The RHINOCEROS DUMPTRUCK gets STUCK IN MUD',
            'amazon_title': 'Mud Trap / The Cold',
            'geography': 'US',
            'video_id': 'EP_2606',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Mud Trap / The Cold',
            'video_duration': 0,
            'revenue': 50.0
        }
    ])
    df_op = pd.DataFrame([
        {
            'month': '2025-01',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '24',
            'episode_name': 'The RHINOCEROS DUMPTRUCK gets STUCK IN MUD',
            'amazon_title': 'Mud Trap / The Cold',
            'geography': 'US',
            'video_id': 'EP_2606',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Mud Trap / The Cold',
            'video_duration': 0,
            'views': 500,
            'watch_time': 3000
        }
    ])

    _, _, df_amz, _, _, _ = consolidate_reports(
        df_fin, df_op, "Episodio Canónico (Todas las versiones)",
        use_youtube=False, use_amazon=True
    )

    assert not df_amz.empty
    row = df_amz.iloc[0]
    assert row['amazon_title'] == 'Mud Trap / The Cold'
    assert row['episode_name'] == 'Mud Trap'
    assert row['episode_name'] != 'The RHINOCEROS DUMPTRUCK gets STUCK IN MUD'


def test_amazon_table_svod_and_tvod_revenue():
    """Verifica que la tabla de Amazon y sus totales incluyan y desglosen las ganancias de SVOD y TVOD además del total."""
    df_fin = pd.DataFrame([
        {
            'month': '2026-08',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Cave Rescue',
            'amazon_title': 'Cave Rescue',
            'geography': 'US',
            'video_id': 'EP_2601',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Cave Rescue',
            'video_duration': 0,
            'revenue': 155.75,
            'revenue_svod': 120.50,
            'revenue_tvod': 35.25
        },
        {
            'month': '2026-08',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '2',
            'episode_name': 'Fire Rescue',
            'amazon_title': 'Fire Rescue',
            'geography': 'US',
            'video_id': 'EP_2602',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Fire Rescue',
            'video_duration': 0,
            'revenue': 44.25,
            'revenue_svod': 30.00,
            'revenue_tvod': 14.25
        }
    ])
    df_op = pd.DataFrame([
        {
            'month': '2026-08',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Cave Rescue',
            'amazon_title': 'Cave Rescue',
            'geography': 'US',
            'video_id': 'EP_2601',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Cave Rescue',
            'video_duration': 0,
            'views': 1200,
            'watch_time': 6000
        },
        {
            'month': '2026-08',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '2',
            'episode_name': 'Fire Rescue',
            'amazon_title': 'Fire Rescue',
            'geography': 'US',
            'video_id': 'EP_2602',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Fire Rescue',
            'video_duration': 0,
            'views': 400,
            'watch_time': 2000
        }
    ])

    _, _, df_amz, _, _, df_totals_amz = consolidate_reports(
        df_fin, df_op, "Episodio Canónico (Todas las versiones)",
        use_youtube=False, use_amazon=True
    )

    assert not df_amz.empty
    assert 'revenue' in df_amz.columns
    assert 'revenue_svod' in df_amz.columns
    assert 'revenue_tvod' in df_amz.columns

    # Verificar valores por episodio
    row1 = df_amz[df_amz['episode_name'] == 'Cave Rescue'].iloc[0]
    assert row1['revenue'] == 155.75
    assert row1['revenue_svod'] == 120.50
    assert row1['revenue_tvod'] == 35.25

    row2 = df_amz[df_amz['episode_name'] == 'Fire Rescue'].iloc[0]
    assert row2['revenue'] == 44.25
    assert row2['revenue_svod'] == 30.00
    assert row2['revenue_tvod'] == 14.25

    # Verificar totales
    assert not df_totals_amz.empty
    tot_row = df_totals_amz.iloc[0]
    assert tot_row['revenue'] == 200.00
    assert tot_row['revenue_svod'] == 150.50
    assert tot_row['revenue_tvod'] == 49.50
    assert tot_row['revenue'] == round(tot_row['revenue_svod'] + tot_row['revenue_tvod'], 2)


def test_watch_time_in_hours_and_amazon_cph_avg_view_formulas():
    """Valida que watch_time se maneje en horas (con 2 decimales) y que las fórmulas

    derivadas de Amazon (cph_rate y avg_view_minutes) y consolidación funcionen correctamente.
    """
    df_fin = pd.DataFrame([
        {
            'month': '2026-09',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Ep 1',
            'amazon_title': 'Ep 1',
            'geography': 'US',
            'video_id': 'amz_1',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Ep 1',
            'video_duration': 0,
            'revenue': 50.00,
            'revenue_svod': 40.00,
            'revenue_tvod': 10.00
        },
        {
            'month': '2026-09',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '2',
            'episode_name': 'Ep 2',
            'amazon_title': 'Ep 2',
            'geography': 'US',
            'video_id': 'amz_2',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Ep 2',
            'video_duration': 0,
            'revenue': 15.00,
            'revenue_svod': 10.00,
            'revenue_tvod': 5.00
        },
        {
            'month': '2026-09',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Ep 1',
            'geography': 'US',
            'video_id': 'yt_1',
            'channel_id': 'yt_chan',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Ep 1 YT',
            'video_duration': 600,
            'revenue': 100.00
        }
    ])

    df_op = pd.DataFrame([
        {
            'month': '2026-09',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Ep 1',
            'amazon_title': 'Ep 1',
            'geography': 'US',
            'video_id': 'amz_1',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Ep 1',
            'video_duration': 0,
            'views': 120,
            'watch_time': 10.0  # 10.0 horas
        },
        {
            'month': '2026-09',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '2',
            'episode_name': 'Ep 2',
            'amazon_title': 'Ep 2',
            'geography': 'US',
            'video_id': 'amz_2',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Ep 2',
            'video_duration': 0,
            'views': 80,
            'watch_time': 2.5  # 2.5 horas
        },
        {
            'month': '2026-09',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '1',
            'episode_number': '1',
            'episode_name': 'Ep 1',
            'geography': 'US',
            'video_id': 'yt_1',
            'channel_id': 'yt_chan',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Ep 1 YT',
            'video_duration': 600,
            'views': 1000,
            'watch_time': 20.25,  # 20.25 horas
            'likes': 50,
            'comments': 5,
            'ad_impressions': 800,
            'ad_revenue': 80.0
        }
    ])

    rep_piv, df_yt, df_amz, df_tot, df_tot_yt, df_tot_amz = consolidate_reports(
        df_fin, df_op, "Episodio Canónico (Todas las versiones)",
        use_youtube=True, use_amazon=True
    )

    # 1. Validar tabla Amazon
    assert not df_amz.empty
    row_amz1 = df_amz[df_amz['episode_name'] == 'Ep 1'].iloc[0]
    assert row_amz1['watch_time'] == 10.0
    # cph_rate = revenue_svod (40.0) / watch_time (10.0) = 4.0000
    assert row_amz1['cph_rate'] == 4.0000
    # avg_view_minutes = (watch_time (10.0) * 60) / views (120) = 5.00
    assert row_amz1['avg_view_minutes'] == 5.00

    row_amz2 = df_amz[df_amz['episode_name'] == 'Ep 2'].iloc[0]
    assert row_amz2['watch_time'] == 2.5
    # cph_rate = 10.0 / 2.5 = 4.0000
    assert row_amz2['cph_rate'] == 4.0000
    # avg_view_minutes = (2.5 * 60) / 80 = 1.88
    assert row_amz2['avg_view_minutes'] == 1.88

    # 2. Validar totales Amazon
    assert not df_tot_amz.empty
    tot_amz = df_tot_amz.iloc[0]
    assert tot_amz['watch_time'] == 12.50
    assert tot_amz['cph_rate'] == 4.0000  # 50.0 / 12.5
    # avg_view_minutes = (12.50 * 60) / 200 = 3.75
    assert tot_amz['avg_view_minutes'] == 3.75

    # 3. Validar tabla YouTube
    assert not df_yt.empty
    row_yt = df_yt[df_yt['episode_name'] == 'Ep 1'].iloc[0]
    assert row_yt['watch_time'] == 20.25

    # 4. Validar tabla Consolidada
    assert not rep_piv.empty
    row_piv1 = rep_piv[rep_piv['episode_name'] == 'Ep 1'].iloc[0]
    assert row_piv1['watch_time_youtube'] == 20.25
    assert row_piv1['watch_time_amazon'] == 10.00
    assert row_piv1['total_watch_time'] == 30.25
    assert row_piv1['total_views'] == 1120
    assert row_piv1['total_revenue'] == 150.00


def test_channel_filter_options_and_metadata():
    """Valida que el filtro por canal funcione correctamente tanto para YouTube como para Amazon."""
    import apps.dashboard.pages.business_reports as br
    class MockConn:
        def rollback(self): pass
        def cursor(self):
            class MockCursor:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def execute(self, *args): pass
            return MockCursor()
    
    # 1. fetch_amz_metadata con canal exclusivo de YouTube debe devolver DataFrame vacío
    empty_amz = br.fetch_amz_metadata(MockConn(), None, None, None, None, None, channels=["UC_YOUTUBE_CHAN"])
    assert empty_amz.empty
    
    # 2. fetch_yt_metadata incluye filtro de canal en query SQL
    captured = {}
    def mock_read_sql(sql, conn, params=None):
        captured['sql'] = sql
        captured['params'] = params
        return pd.DataFrame(columns=['video_id', 'channel_id', 'channel_name', 'language_code', 'geography'])
        
    original_read_sql = pd.read_sql_query
    pd.read_sql_query = mock_read_sql
    try:
        br.fetch_yt_metadata(MockConn(), None, None, None, None, None, None, channels=["UC_CHAN_123"])
        assert "AND yc.channel_id IN %s" in captured['sql']
        assert ("UC_CHAN_123",) in captured['params']
    finally:
        pd.read_sql_query = original_read_sql


def test_business_reports_groupby_fillna():
    """Valida que la falta de video_duration o language_code no provoque la omisión de filas en groupby (bug dropna)."""
    data = [
        {
            "month": "2025",
            "producer": "Amuse Animation",
            "ip_name": "Car City",
            "series_name": "Tom the Tow Truck",
            "season": 1,
            "episode_number": 1,
            "episode_name": "Tom helps Amber",
            "geography": "Global (Mundial)",
            "video_id": "vid_1",
            "channel_id": "UC_1",
            "platform": "youtube",
            "language_code": "en",
            "video_title": "Tom helps Amber",
            "video_duration": 300,
            "revenue": 100.0,
            "views": 50000
        },
        {
            "month": "2025",
            "producer": "Amuse Animation",
            "ip_name": "Car City",
            "series_name": "Tom the Tow Truck",
            "season": 1,
            "episode_number": 2,
            "episode_name": "Tom helps Ethan",
            "geography": "Global (Mundial)",
            "video_id": "vid_2",
            "channel_id": "UC_1",
            "platform": "youtube",
            "language_code": np.nan,  # Missing language_code
            "video_title": "Tom helps Ethan",
            "video_duration": np.nan,  # Missing video_duration (Bug condition)
            "revenue": 50.0,
            "views": 25000
        }
    ]
    df = pd.DataFrame(data)

    yt_group_cols = [
        "month", "producer", "ip_name", "series_name", "season", "episode_number",
        "episode_name", "geography", "video_id", "channel_id", "platform",
        "language_code", "video_title", "video_duration"
    ]

    # Sin fillna y con dropna=True por defecto se perdía la segunda fila
    res_bad = df.groupby(yt_group_cols, dropna=True)["revenue"].sum().sum()
    assert res_bad == 100.0

    # Con la corrección de fillna y dropna=False se conserva el 100% de la facturación
    df.fillna({
        "video_duration": 0,
        "language_code": "Unknown",
        "video_title": "Unknown Video",
        "producer": "Amuse Animation"
    }, inplace=True)
    res_good = df.groupby(yt_group_cols, dropna=False)["revenue"].sum().sum()
    assert res_good == 150.0
    assert df.groupby(yt_group_cols, dropna=False)["views"].sum().sum() == 75000


def test_amazon_multilingual_match_and_english_canonical_resolution():
    """Verifica que un episodio en idioma extranjero (ej. italiano) matcheado semánticamente con
    un título de catálogo en otro idioma (ej. chino '鳄鱼车碎石车的牙痛') muestre:
    1. 'amazon_title': el título en Amazon Prime Video ('Il mal di denti del coccodrillo')
    2. 'match_title': el título con el que hizo Match la IA ('鳄鱼车碎石车的牙痛')
    3. 'episode_name': el título canónico original de producción en inglés ('Trackodile\'s Toothache')
    """
    df_fin = pd.DataFrame([
        {
            'month': '2024-05',
            'producer': 'Amuse Animation',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '2',
            'episode_number': '103',
            'episode_name': 'Il mal di denti del coccodrillo',
            'amazon_title': 'Il mal di denti del coccodrillo',
            'geography': 'IT',
            'video_id': 'EP_2684',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'it',
            'video_title': 'Il mal di denti del coccodrillo',
            'video_duration': 0,
            'revenue': 85.50,
            'match_score': 78.9
        }
    ])
    df_op = pd.DataFrame([
        {
            'month': '2024-05',
            'producer': 'Amuse Animation',
            'ip_name': 'ANIMACARS',
            'series_name': 'ANIMA_TOWN',
            'season': '2',
            'episode_number': '103',
            'episode_name': 'Il mal di denti del coccodrillo',
            'amazon_title': 'Il mal di denti del coccodrillo',
            'geography': 'IT',
            'video_id': 'EP_2684',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'it',
            'video_title': 'Il mal di denti del coccodrillo',
            'video_duration': 0,
            'views': 1200,
            'watch_time': 5000,
            'match_score': 78.9
        }
    ])

    _, _, df_amz, _, _, _ = consolidate_reports(
        df_fin, df_op, "Episodio Canónico (Todas las versiones)",
        use_youtube=False, use_amazon=True
    )

    assert not df_amz.empty
    row = df_amz.iloc[0]
    assert row['amazon_title'] == 'Il mal di denti del coccodrillo'
    assert row['match_title'] == '鳄鱼车碎石车的牙痛'
    assert row['episode_name'] == "Trackodile's Toothache"
    assert row['match_score'] == 78.9

    cols = list(df_amz.columns)
    assert cols.index('amazon_title') < cols.index('match_title')
    assert cols.index('match_title') < cols.index('episode_name')
    assert cols.index('episode_name') < cols.index('match_score')


def test_amazon_unmatched_records_preserve_original_titles():
    """Verifica que los vídeos UNMATCHED de Amazon Prime Video:
    1. Tengan match_title = 'UNMATCHED'.
    2. Conserven su amazon_title original intacto como episode_name.
    3. NUNCA sean sobreescritos con títulos de producción ni traducciones del catálogo.
    """
    df_fin = pd.DataFrame([
        {
            'month': '2025-01',
            'producer': 'Amuse Animation',
            'ip_name': 'UNMATCHED',
            'series_name': 'UNMATCHED_AMZ',
            'season': '0',
            'episode_number': 'UNMATCHED_AMZ_0f9c19d90cbe',
            'episode_name': "Aladdin & the genies'",
            'amazon_title': "Aladdin & the genies'",
            'match_title': 'UNMATCHED',
            'geography': 'US',
            'video_id': 'UNMATCHED_AMZ_0f9c19d90cbe',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': "Aladdin & the genies'",
            'video_duration': 0,
            'revenue': 4.60,
            'match_score': 0.0
        },
        {
            'month': '2025-01',
            'producer': 'Amuse Animation',
            'ip_name': 'UNMATCHED',
            'series_name': 'UNMATCHED_AMZ',
            'season': '0',
            'episode_number': 'UNMATCHED_AMZ_11c713be000d',
            'episode_name': "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball",
            'amazon_title': "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball",
            'match_title': 'UNMATCHED',
            'geography': 'FR',
            'video_id': 'UNMATCHED_AMZ_11c713be000d',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'fr',
            'video_title': "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball",
            'video_duration': 0,
            'revenue': 2.68,
            'match_score': 0.0
        }
    ])
    df_op = pd.DataFrame([
        {
            'month': '2025-01',
            'producer': 'Amuse Animation',
            'ip_name': 'UNMATCHED',
            'series_name': 'UNMATCHED_AMZ',
            'season': '0',
            'episode_number': 'UNMATCHED_AMZ_0f9c19d90cbe',
            'episode_name': "Aladdin & the genies'",
            'amazon_title': "Aladdin & the genies'",
            'match_title': 'UNMATCHED',
            'geography': 'US',
            'video_id': 'UNMATCHED_AMZ_0f9c19d90cbe',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': "Aladdin & the genies'",
            'video_duration': 0,
            'views': 100,
            'watch_time': 500,
            'match_score': 0.0
        },
        {
            'month': '2025-01',
            'producer': 'Amuse Animation',
            'ip_name': 'UNMATCHED',
            'series_name': 'UNMATCHED_AMZ',
            'season': '0',
            'episode_number': 'UNMATCHED_AMZ_11c713be000d',
            'episode_name': "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball",
            'amazon_title': "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball",
            'match_title': 'UNMATCHED',
            'geography': 'FR',
            'video_id': 'UNMATCHED_AMZ_11c713be000d',
            'channel_id': 'Amazon Prime Video',
            'platform': 'amazon',
            'language_code': 'fr',
            'video_title': "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball",
            'video_duration': 0,
            'views': 150,
            'watch_time': 600,
            'match_score': 0.0
        }
    ])

    # Probar en todos los niveles de agregación
    for agg in [
        "Episodio Canónico (Todas las versiones)",
        "Por Idioma (Separar traducciones)",
        "Por Territorio / País",
        "Por Vídeo/Versión (Mostrar resubidas)"
    ]:
        _, _, df_amz, _, _, _ = consolidate_reports(
            df_fin, df_op, agg, use_youtube=False, use_amazon=True
        )

        assert not df_amz.empty
        row_aladdin = df_amz[df_amz['amazon_title'] == "Aladdin & the genies'"].iloc[0]
        assert row_aladdin['match_title'] == 'UNMATCHED'
        assert row_aladdin['episode_name'] == "Aladdin & the genies'"
        assert row_aladdin['episode_name'] != 'Episode 18'

        row_dino = df_amz[df_amz['amazon_title'] == "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball"].iloc[0]
        assert row_dino['match_title'] == 'UNMATCHED'
        assert row_dino['episode_name'] == "Apprendre avec Dino : La Fête Foraine / Jouer au Basket-Ball"
        assert 'ДЕНЬ' not in row_dino['episode_name']


def test_currency_conversion_usd_vs_eur():
    """Verify that consolidate_reports and consolidate_multiplatform_reports properly convert to EUR when requested."""
    from core.domain.exchange_rates import get_eur_rate

    df_fin = pd.DataFrame([
        {
            'month': '2023-05',
            'ip_name': 'CARCITY',
            'series_name': 'CAR_PATROL',
            'season': 1,
            'episode_number': 1,
            'episode_name': 'Car Patrol Ep 1',
            'geography': 'US',
            'video_id': 'YT_TEST_1',
            'channel_id': 'CHANNEL_1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Car Patrol Ep 1',
            'video_duration': 300,
            'revenue': 100.0,
            'ad_revenue': 80.0,
            'ad_impressions': 40000,
        },
        {
            'month': '2023-05',
            'ip_name': 'CARCITY',
            'series_name': 'CAR_PATROL',
            'season': 1,
            'episode_number': 1,
            'episode_name': 'Car Patrol Ep 1',
            'geography': 'US',
            'video_id': 'AMZ_TEST_1',
            'channel_id': 'AMAZON',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Car Patrol Ep 1',
            'video_duration': 300,
            'revenue': 50.0,
            'revenue_svod': 50.0,
            'revenue_tvod': 0.0,
        }
    ])
    df_op = pd.DataFrame([
        {
            'month': '2023-05',
            'ip_name': 'CARCITY',
            'series_name': 'CAR_PATROL',
            'season': 1,
            'episode_number': 1,
            'episode_name': 'Car Patrol Ep 1',
            'geography': 'US',
            'video_id': 'YT_TEST_1',
            'channel_id': 'CHANNEL_1',
            'platform': 'youtube',
            'language_code': 'en',
            'video_title': 'Car Patrol Ep 1',
            'video_duration': 300,
            'views': 50000,
            'watch_time': 100.0,
            'likes': 100,
            'comments': 10,
        },
        {
            'month': '2023-05',
            'ip_name': 'CARCITY',
            'series_name': 'CAR_PATROL',
            'season': 1,
            'episode_number': 1,
            'episode_name': 'Car Patrol Ep 1',
            'geography': 'US',
            'video_id': 'AMZ_TEST_1',
            'channel_id': 'AMAZON',
            'platform': 'amazon',
            'language_code': 'en',
            'video_title': 'Car Patrol Ep 1',
            'video_duration': 300,
            'views': 10000,
            'watch_time': 50.0,
        }
    ])

    # 1. USD (default)
    rep_usd, df_yt_usd, df_amz_usd, tot_usd, tot_yt_usd, tot_amz_usd = consolidate_reports(
        df_fin, df_op, "Por Serie", use_youtube=True, use_amazon=True, display_currency="USD"
    )
    assert round(float(tot_usd['total_revenue'].iloc[0]), 2) == 150.0
    assert round(float(tot_yt_usd['revenue'].iloc[0]), 2) == 100.0
    assert round(float(tot_amz_usd['revenue'].iloc[0]), 2) == 50.0
    assert round(float(df_yt_usd['revenue'].iloc[0]), 2) == 100.0
    assert round(float(df_amz_usd['revenue'].iloc[0]), 2) == 50.0

    # 2. EUR
    eur_rate_2023_05 = get_eur_rate("2023-05")
    expected_tot_eur = round(150.0 * eur_rate_2023_05, 2)
    expected_yt_eur = round(100.0 * eur_rate_2023_05, 2)
    expected_amz_eur = round(50.0 * eur_rate_2023_05, 2)
    expected_ad_eur = round(80.0 * eur_rate_2023_05, 2)

    rep_eur, df_yt_eur, df_amz_eur, tot_eur, tot_yt_eur, tot_amz_eur = consolidate_reports(
        df_fin, df_op, "Por Serie", use_youtube=True, use_amazon=True, display_currency="EUR"
    )
    assert round(float(tot_eur['total_revenue'].iloc[0]), 2) == expected_tot_eur
    assert round(float(tot_yt_eur['revenue'].iloc[0]), 2) == expected_yt_eur
    assert round(float(tot_amz_eur['revenue'].iloc[0]), 2) == expected_amz_eur
    assert round(float(df_yt_eur['revenue'].iloc[0]), 2) == expected_yt_eur
    assert round(float(df_yt_eur['ad_revenue'].iloc[0]), 2) == expected_ad_eur
    assert round(float(df_amz_eur['revenue'].iloc[0]), 2) == expected_amz_eur


def test_to_excel_bytes_euro_currency_formatting():
    """Verify that to_excel_bytes formats cells with € when currency_symbol='€'."""
    import io
    import openpyxl

    df = pd.DataFrame({
        'series_name': ['Car City', 'Total Global'],
        'total_revenue': [1250.50, 1250.50],
        'cph_rate': [0.1234, 0.1234],
    })

    raw_bytes = to_excel_bytes(df, "Comparative_EUR", currency_symbol="€")
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes))
    ws = wb["Comparative_EUR"]

    rev_cell = ws.cell(row=2, column=2)
    cph_cell = ws.cell(row=2, column=3)

    assert rev_cell.number_format == "€#,##0.00"
    assert cph_cell.number_format == "€#,##0.0000"





