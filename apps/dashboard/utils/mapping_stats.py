import os
import json
import io
import openpyxl
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
EXCEL_TRACKER_PATH = os.path.join(PROJECT_ROOT, 'data', 'reference', 'Tracker_mapeo_Youtube_IDs.xlsx')
AMAZON_CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'cache', 'amazon_mapping_stats.json')


def load_youtube_mapping_stats():
    """
    Carga y estructura las tablas de auditoría de mapeo de YouTube desde el tracker oficial.
    Retorna un diccionario con DataFrames para:
    - recuento: Recuento de IDs según forma (#) por año
    - monetizacion_historica: Monetización histórica (€) por año
    - monetizacion_2025: Monetización 2025 (€) por año
    - ip_recuento: Auditoría de IPs Amuse vs No Amuse (#) por año
    - ip_monetizacion: Auditoría de IPs monetización histórica (€) por año
    - confianza_resumen: Resumen de niveles de confianza y porcentajes
    """
    if not os.path.exists(EXCEL_TRACKER_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de tracker de YouTube en {EXCEL_TRACKER_PATH}")

    wb = openpyxl.load_workbook(EXCEL_TRACKER_PATH, data_only=True)
    ws = wb.active

    # 1. Recuento según forma (#)
    rows_rec = []
    for r in range(75, 87):
        yr = int(ws.cell(r, 1).value)
        rows_rec.append({
            'Año': str(yr),
            'BK2 (100%)': int(ws.cell(r, 2).value or 0),
            'BK 1 (100%)': int(ws.cell(r, 3).value or 0),
            'Match por Título (100%)': int(ws.cell(r, 4).value or 0),
            'Modelo Multifase (85%)': int(ws.cell(r, 5).value or 0),
            'Sin Mapear y NO AMUSE (0%)': int(ws.cell(r, 6).value or 0),
            'TOTAL BBDD': int(ws.cell(r, 7).value or 0)
        })
    df_rec = pd.DataFrame(rows_rec)

    # 2. Monetización histórica (€)
    rows_hist = []
    for r in range(76, 88):
        yr = int(ws.cell(r, 9).value)
        rows_hist.append({
            'Año': str(yr),
            'BK2 (€)': float(ws.cell(r, 10).value or 0.0),
            'BK 1 (€)': float(ws.cell(r, 11).value or 0.0),
            'Match por Título (€)': float(ws.cell(r, 12).value or 0.0),
            'Modelo Multifase (€)': float(ws.cell(r, 13).value or 0.0),
            'Sin Mapear (€)': float(ws.cell(r, 14).value or 0.0),
            'TOTAL BBDD (€)': float(ws.cell(r, 15).value or 0.0)
        })
    df_hist = pd.DataFrame(rows_hist)

    # 3. Monetización 2025 (€)
    rows_2025 = []
    for r in range(76, 88):
        yr = int(ws.cell(r, 17).value)
        rows_2025.append({
            'Año': str(yr),
            'BK2 (€)': float(ws.cell(r, 18).value or 0.0),
            'BK 1 (€)': float(ws.cell(r, 19).value or 0.0),
            'Match por Título (€)': float(ws.cell(r, 20).value or 0.0),
            'Modelo Multifase (€)': float(ws.cell(r, 21).value or 0.0),
            'Sin Mapear (€)': float(ws.cell(r, 22).value or 0.0),
            'TOTAL BBDD (€)': float(ws.cell(r, 23).value or 0.0)
        })
    df_2025 = pd.DataFrame(rows_2025)

    # 4. Descarte e IPs Recuento (#)
    rows_ip_rec = []
    for r in range(93, 105):
        yr = int(ws.cell(r, 1).value)
        rows_ip_rec.append({
            'Año': str(yr),
            'Videos IP AMUSE': int(ws.cell(r, 2).value or 0),
            'Videos IP no AMUSE': int(ws.cell(r, 3).value or 0),
            'Videos eliminados y lives': int(ws.cell(r, 4).value or 0),
            'Videos sin mapear': int(ws.cell(r, 5).value or 0),
            'TOTAL BBDD': int(ws.cell(r, 6).value or 0)
        })
    df_ip_rec = pd.DataFrame(rows_ip_rec)

    # 5. Descarte e IPs Monetización (€)
    rows_ip_mon = []
    for r in range(93, 105):
        yr = int(ws.cell(r, 9).value)
        rows_ip_mon.append({
            'Año': str(yr),
            'Videos IP AMUSE (€)': float(ws.cell(r, 10).value or 0.0),
            'Videos IP no AMUSE (€)': float(ws.cell(r, 11).value or 0.0),
            'Videos eliminados y lives (€)': float(ws.cell(r, 12).value or 0.0),
            'Videos sin mapear (€)': float(ws.cell(r, 13).value or 0.0),
            'TOTAL BBDD (€)': float(ws.cell(r, 14).value or 0.0)
        })
    df_ip_mon = pd.DataFrame(rows_ip_mon)

    # 6. Tabla Resumen de Confianza y Totales
    confianza_summary = pd.DataFrame([
        {'Método / Rango': 'BK 1 (Exacto Broadkast)', 'Confianza (%)': '100%', 'Puntuación': '20 / 20 pts', 'Vídeos (#)': 49582, '% Catálogo': 59.92, 'Ingresos Históricos (€)': 3965769.66, '% Ingresos': 32.76},
        {'Método / Rango': 'Match por Título (Exacto)', 'Confianza (%)': '100%', 'Puntuación': '20 / 20 pts', 'Vídeos (#)': 12948, '% Catálogo': 15.65, 'Ingresos Históricos (€)': 4406286.45, '% Ingresos': 36.39},
        {'Método / Rango': 'BK 2 (Embeddings / ID)', 'Confianza (%)': '100%', 'Puntuación': '20 / 20 pts', 'Vídeos (#)': 10127, '% Catálogo': 12.24, 'Ingresos Históricos (€)': 214296.49, '% Ingresos': 1.77},
        {'Método / Rango': 'Modelo Multifase (Clasificación NLP)', 'Confianza (%)': '85%', 'Puntuación': '17 / 20 pts', 'Vídeos (#)': 7089, '% Catálogo': 8.57, 'Ingresos Históricos (€)': 2859651.34, '% Ingresos': 23.62},
        {'Método / Rango': 'Sin Mapear y NO AMUSE', 'Confianza (%)': '0%', 'Puntuación': '0 / 20 pts', 'Vídeos (#)': 2999, '% Catálogo': 3.62, 'Ingresos Históricos (€)': 660921.68, '% Ingresos': 5.46},
    ])

    return {
        'recuento': df_rec,
        'monetizacion_historica': df_hist,
        'monetizacion_2025': df_2025,
        'ip_recuento': df_ip_rec,
        'ip_monetizacion': df_ip_mon,
        'confianza_resumen': confianza_summary
    }


def load_amazon_mapping_stats():
    """
    Carga y estructura las tablas de auditoría de mapeo de Amazon Prime Video.
    Utiliza el archivo de caché precalculado o genera los datos al vuelo si es necesario.
    """
    if not os.path.exists(AMAZON_CACHE_PATH):
        from scripts.generate_amazon_mapping_cache import generate_cache
        generate_cache()

    with open(AMAZON_CACHE_PATH, 'r') as f:
        cache = json.load(f)

    recuento_dict = cache['recuento_by_year']
    rev_dict = cache['revenue_by_year']
    ip_counts = cache['ip_classification_counts']
    ip_rev_dict = cache.get('ip_revenue_by_year', {})

    # 1. Recuento (#)
    rows_rec = []
    years = sorted(recuento_dict.keys(), key=lambda x: int(x))
    for yr in years:
        d = recuento_dict[yr]
        exact = d.get('Exact Title (100%)', 0)
        ai_high = d.get('Semantic AI >= 80%', 0)
        ai_mid = d.get('Semantic AI 60-79%', 0)
        ai_low = d.get('Semantic AI < 60%', 0)
        descarte_ip = d.get('Descartes IP (No Amuse)', 0)
        descarte_formato = d.get('Descartes Formato/Especial', 0)
        sin_map = d.get('Sin mapear', 0)
        tot = exact + ai_high + ai_mid + ai_low + descarte_ip + descarte_formato + sin_map
        rows_rec.append({
            'Año': yr,
            'Exact Title (100%)': exact,
            'Semantic AI (>= 80%)': ai_high,
            'Semantic AI (60-79%)': ai_mid,
            'Semantic AI (< 60%)': ai_low,
            'Descartes IP (No Amuse)': descarte_ip,
            'Descartes Formato / Películas': descarte_formato,
            'Sin Mapear': sin_map,
            'TOTAL BBDD': tot
        })
    df_rec = pd.DataFrame(rows_rec)

    # 2. Monetización histórica (€)
    rows_hist = []
    rev_years = sorted(rev_dict.keys(), key=lambda x: int(x))
    for yr in rev_years:
        d = rev_dict[yr]
        exact = d.get('Exact Title (100%)', 0.0)
        ai_high = d.get('Semantic AI >= 80%', 0.0)
        ai_mid = d.get('Semantic AI 60-79%', 0.0)
        ai_low = d.get('Semantic AI < 60%', 0.0)
        descarte_ip = d.get('Descartes IP (No Amuse)', 0.0)
        descarte_formato = d.get('Descartes Formato/Especial', 0.0)
        sin_map = d.get('Sin mapear', 0.0)
        legacy = d.get('Múltiple Global (Legacy)', 0.0)
        tot = exact + ai_high + ai_mid + ai_low + descarte_ip + descarte_formato + sin_map + legacy
        rows_hist.append({
            'Año': yr,
            'Exact Title (€)': round(exact, 2),
            'Semantic AI (>= 80%) (€)': round(ai_high, 2),
            'Semantic AI (60-79%) (€)': round(ai_mid, 2),
            'Semantic AI (< 60%) (€)': round(ai_low, 2),
            'Descartes IP No Amuse (€)': round(descarte_ip, 2),
            'Descartes Formato (€)': round(descarte_formato, 2),
            'Sin Mapear (€)': round(sin_map, 2),
            'Múltiple Global Legacy (€)': round(legacy, 2),
            'TOTAL BBDD (€)': round(tot, 2)
        })
    df_hist = pd.DataFrame(rows_hist)

    # 3. Monetización 2025 (€)
    d_2025 = rev_dict.get('2025', {})
    exact_25 = d_2025.get('Exact Title (100%)', 0.0)
    ai_high_25 = d_2025.get('Semantic AI >= 80%', 0.0)
    ai_mid_25 = d_2025.get('Semantic AI 60-79%', 0.0)
    ai_low_25 = d_2025.get('Semantic AI < 60%', 0.0)
    descarte_ip_25 = d_2025.get('Descartes IP (No Amuse)', 0.0)
    descarte_formato_25 = d_2025.get('Descartes Formato/Especial', 0.0)
    sin_map_25 = d_2025.get('Sin mapear', 0.0)
    legacy_25 = d_2025.get('Múltiple Global (Legacy)', 0.0)
    tot_25 = exact_25 + ai_high_25 + ai_mid_25 + ai_low_25 + descarte_ip_25 + descarte_formato_25 + sin_map_25 + legacy_25

    df_2025 = pd.DataFrame([{
        'Año': '2025',
        'Exact Title (€)': round(exact_25, 2),
        'Semantic AI (>= 80%) (€)': round(ai_high_25, 2),
        'Semantic AI (60-79%) (€)': round(ai_mid_25, 2),
        'Semantic AI (< 60%) (€)': round(ai_low_25, 2),
        'Descartes IP No Amuse (€)': round(descarte_ip_25, 2),
        'Descartes Formato (€)': round(descarte_formato_25, 2),
        'Sin Mapear (€)': round(sin_map_25, 2),
        'Múltiple Global Legacy (€)': round(legacy_25, 2),
        'TOTAL 2025 (€)': round(tot_25, 2)
    }])

    # 4. Descarte e IPs Recuento (#)
    df_ip_rec = pd.DataFrame([
        {'Categoría de Catálogo': 'Títulos IP AMUSE (Mapeados Directos / IA)', 'Títulos (#)': ip_counts.get('Títulos IP AMUSE', 11574), '% Catálogo': round(ip_counts.get('Títulos IP AMUSE', 11574) / ip_counts['TOTAL BBDD'] * 100, 2)},
        {'Categoría de Catálogo': 'Títulos IP no AMUSE (Blacklist / Alien Series: Molang, Mouk, etc.)', 'Títulos (#)': ip_counts.get('Títulos IP no AMUSE', 1113), '% Catálogo': round(ip_counts.get('Títulos IP no AMUSE', 1113) / ip_counts['TOTAL BBDD'] * 100, 2)},
        {'Categoría de Catálogo': 'Títulos Formato Película / Especiales descartados', 'Títulos (#)': ip_counts.get('Títulos películas / formato especial', 80), '% Catálogo': round(ip_counts.get('Títulos películas / formato especial', 80) / ip_counts['TOTAL BBDD'] * 100, 2)},
        {'Categoría de Catálogo': 'Títulos Sin Mapear', 'Títulos (#)': ip_counts.get('Títulos sin mapear', 2), '% Catálogo': round(ip_counts.get('Títulos sin mapear', 2) / ip_counts['TOTAL BBDD'] * 100, 2)},
        {'Categoría de Catálogo': 'TOTAL BBDD AMAZON', 'Títulos (#)': ip_counts['TOTAL BBDD'], '% Catálogo': 100.0}
    ])

    # 5. Descarte e IPs Monetización (€) por año
    rows_ip_mon = []
    for yr in sorted(ip_rev_dict.keys(), key=lambda x: int(x)):
        row = {'Año': yr}
        row.update(ip_rev_dict[yr])
        rows_ip_mon.append(row)
    df_ip_mon = pd.DataFrame(rows_ip_mon)

    # 6. Tabla Resumen de Confianza y Totales
    confianza_summary = pd.DataFrame([
        {'Método / Rango': 'Exact Title (Coincidencia Exacta)', 'Confianza (%)': '100%', 'Puntuación': '20 / 20 pts', 'Títulos (#)': 4168, '% Catálogo': 32.64, 'Ingresos Granulares (€)': 134233.78, '% Ingresos Granulares': 3.11},
        {'Método / Rango': 'Semantic AI Alta Confianza (>= 80%)', 'Confianza (%)': '80% - 99%', 'Puntuación': '18-20 pts', 'Títulos (#)': 3656, '% Catálogo': 28.63, 'Ingresos Granulares (€)': 2106632.06, '% Ingresos Granulares': 48.75},
        {'Método / Rango': 'Semantic AI Media Confianza (60-79%)', 'Confianza (%)': '60% - 79%', 'Puntuación': '14-17 pts', 'Títulos (#)': 2810, '% Catálogo': 22.01, 'Ingresos Granulares (€)': 1375530.21, '% Ingresos Granulares': 31.83},
        {'Método / Rango': 'Semantic AI Baja Confianza (< 60%)', 'Confianza (%)': '< 60%', 'Puntuación': '< 14 pts', 'Títulos (#)': 940, '% Catálogo': 7.36, 'Ingresos Granulares (€)': 204183.55, '% Ingresos Granulares': 4.73},
        {'Método / Rango': 'Descartes IP Ajenas (Blacklist / Alien)', 'Confianza (%)': 'Descarte IP', 'Puntuación': '0 / 20 pts', 'Títulos (#)': 1113, '% Catálogo': 8.72, 'Ingresos Granulares (€)': 456738.48, '% Ingresos Granulares': 10.57},
        {'Método / Rango': 'Descartes Formato (Películas / Especiales)', 'Confianza (%)': 'Descarte Formato', 'Puntuación': '0 / 20 pts', 'Títulos (#)': 80, '% Catálogo': 0.63, 'Ingresos Granulares (€)': 43557.26, '% Ingresos Granulares': 1.01},
        {'Método / Rango': 'Sin Mapear', 'Confianza (%)': '0%', 'Puntuación': '0 / 20 pts', 'Títulos (#)': 2, '% Catálogo': 0.02, 'Ingresos Granulares (€)': 14.90, '% Ingresos Granulares': 0.00},
    ])

    return {
        'recuento': df_rec,
        'monetizacion_historica': df_hist,
        'monetizacion_2025': df_2025,
        'ip_recuento': df_ip_rec,
        'ip_monetizacion': df_ip_mon,
        'confianza_resumen': confianza_summary
    }


def get_combined_executive_kpis():
    """
    Retorna métricas ejecutivas consolidadas para las tarjetas superiores de la UI.
    """
    yt = load_youtube_mapping_stats()
    amz = load_amazon_mapping_stats()

    # YouTube Totals
    yt_rec = yt['recuento']
    yt_total_videos = 86686
    yt_amuse_mapped = 10127 + 49582 + 12948 + 7089  # 79,746 (92.0%)
    yt_high_conf = 10127 + 49582 + 12948  # 72,657 (83.8% total, 91.1% de mapeados)
    yt_total_rev = 12106925.62
    yt_rev_2025 = 696376.95

    # Amazon Totals
    amz_total_titles = 12769
    amz_amuse_mapped = 11574  # 90.6%
    amz_high_conf = 4168 + 3656  # 7,824 (61.3% total, 67.6% de mapeados)
    amz_total_rev = 8640727.48
    amz_rev_2025 = 341779.70

    return {
        'yt': {
            'total_items': yt_total_videos,
            'mapped_amuse': yt_amuse_mapped,
            'pct_mapped': round(yt_amuse_mapped / yt_total_videos * 100, 1),
            'high_conf_items': yt_high_conf,
            'pct_high_conf': round(yt_high_conf / yt_total_videos * 100, 1),
            'total_revenue': yt_total_rev,
            'rev_2025': yt_rev_2025
        },
        'amz': {
            'total_items': amz_total_titles,
            'mapped_amuse': amz_amuse_mapped,
            'pct_mapped': round(amz_amuse_mapped / amz_total_titles * 100, 1),
            'high_conf_items': amz_high_conf,
            'pct_high_conf': round(amz_high_conf / amz_total_titles * 100, 1),
            'total_revenue': amz_total_rev,
            'rev_2025': amz_rev_2025
        }
    }


def generate_export_excel_bytes():
    """
    Genera un archivo Excel en memoria con todas las pestañas de auditoría de YouTube y Amazon.
    """
    yt = load_youtube_mapping_stats()
    amz = load_amazon_mapping_stats()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        yt['recuento'].to_excel(writer, sheet_name='YT_Recuento_Por_Año', index=False)
        yt['monetizacion_historica'].to_excel(writer, sheet_name='YT_Monetizacion_Historica', index=False)
        yt['monetizacion_2025'].to_excel(writer, sheet_name='YT_Monetizacion_2025', index=False)
        yt['ip_recuento'].to_excel(writer, sheet_name='YT_Descartes_IP_Recuento', index=False)
        yt['ip_monetizacion'].to_excel(writer, sheet_name='YT_Descartes_IP_Monetizacion', index=False)
        yt['confianza_resumen'].to_excel(writer, sheet_name='YT_Resumen_Confianza', index=False)

        amz['recuento'].to_excel(writer, sheet_name='AMZ_Recuento_Por_Año', index=False)
        amz['monetizacion_historica'].to_excel(writer, sheet_name='AMZ_Monetizacion_Historica', index=False)
        amz['monetizacion_2025'].to_excel(writer, sheet_name='AMZ_Monetizacion_2025', index=False)
        amz['ip_recuento'].to_excel(writer, sheet_name='AMZ_Descartes_IP_Recuento', index=False)
        amz['ip_monetizacion'].to_excel(writer, sheet_name='AMZ_Descartes_IP_Monetizacion', index=False)
        amz['confianza_resumen'].to_excel(writer, sheet_name='AMZ_Resumen_Confianza', index=False)

    output.seek(0)
    return output.getvalue()

