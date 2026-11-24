import os
import pytest
import pandas as pd
from apps.dashboard.utils.mapping_stats import (
    load_youtube_mapping_stats,
    load_amazon_mapping_stats,
    get_combined_executive_kpis,
    generate_export_excel_bytes
)


def test_youtube_mapping_stats():
    yt = load_youtube_mapping_stats()
    assert 'recuento' in yt
    assert 'monetizacion_historica' in yt
    assert 'monetizacion_2025' in yt
    assert 'ip_recuento' in yt
    assert 'ip_monetizacion' in yt
    assert 'confianza_resumen' in yt

    df_rec = yt['recuento']
    assert len(df_rec) == 12  # 2014 to 2025
    assert 'BK2 (100%)' in df_rec.columns
    assert 'BK 1 (100%)' in df_rec.columns
    assert 'Match por Título (100%)' in df_rec.columns
    assert 'Modelo Multifase (85%)' in df_rec.columns
    assert 'TOTAL BBDD' in df_rec.columns

    # Verify total sum of active catalogue matches tracker (82,745)
    total_active = df_rec['TOTAL BBDD'].sum()
    assert total_active == 82745

    # Verify historical revenue total
    df_hist = yt['monetizacion_historica']
    tot_rev = df_hist['TOTAL BBDD (€)'].sum()
    assert abs(tot_rev - 12106925.62) < 0.1


def test_amazon_mapping_stats():
    amz = load_amazon_mapping_stats()
    assert 'recuento' in amz
    assert 'monetizacion_historica' in amz
    assert 'monetizacion_2025' in amz
    assert 'ip_recuento' in amz
    assert 'ip_monetizacion' in amz
    assert 'confianza_resumen' in amz

    df_rec = amz['recuento']
    assert len(df_rec) >= 9
    assert 'Exact Title (100%)' in df_rec.columns
    assert 'Semantic AI (>= 80%)' in df_rec.columns
    assert 'TOTAL BBDD' in df_rec.columns

    # Verify total production mappings (12,777)
    total_titles = df_rec['TOTAL BBDD'].sum()
    assert total_titles == 12777

    # Verify IP classification (11,658 Amuse titles, 1,112 Alien series, 7 unmatched)
    df_ip_rec = amz['ip_recuento']
    amuse_titles = df_ip_rec.loc[df_ip_rec['Categoría de Catálogo'].str.contains('AMUSE'), 'Títulos (#)'].values[0]
    assert amuse_titles == 11658


def test_combined_executive_kpis():
    kpis = get_combined_executive_kpis()
    assert 'yt' in kpis
    assert 'amz' in kpis
    assert kpis['yt']['total_items'] == 86686
    assert kpis['amz']['total_items'] == 12769
    assert kpis['yt']['pct_mapped'] > 90
    assert kpis['amz']['pct_mapped'] > 90


def test_generate_export_excel_bytes():
    excel_bytes = generate_export_excel_bytes()
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 5000

