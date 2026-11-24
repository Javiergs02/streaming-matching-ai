# pages/business_reports.py
import sys
import os
from pathlib import Path

# Asegurar que la raíz del proyecto y apps/dashboard estén en el PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DASHBOARD_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

import re
import io
import calendar
import logging
import concurrent.futures
import streamlit as st
import pandas as pd
import numpy as np
import importlib
from datetime import datetime, date, timedelta
from utils.connections import get_postgres_connection, get_mongo_client, get_broadkast_postgres_connection
from utils.styling import apply_portal_style
from core.domain.producers import resolve_producer, KNOWN_PRODUCERS
from core.domain.languages import detect_title_language
import core.domain.china
try:
    if not hasattr(core.domain.china, 'get_iqiyi_series_metadata'):
        importlib.reload(core.domain.china)
except Exception:
    pass
from core.domain.china import (
    get_tencent_series_metadata,
    get_youku_series_metadata,
    get_iqiyi_series_metadata,
)
from core.domain.exchange_rates import (
    get_cny_rate,
    get_eur_rate,
    convert_currency,
    get_rates_dataframe,
    save_rates_dataframe,
    reset_to_defaults,
)
from core.domain.youtube_channels import (
    YouTubeChannelCatalog,
    enrich_youtube_dataframe,
    enrich_youtube_video_metadata,
    get_youtube_channel_info,
    resolve_youtube_channel_ip,
)

logger = logging.getLogger(__name__)

# Asegurar recarga del módulo en Streamlit si el servidor no se ha reiniciado
import core.domain.amazon
try:
    if (not hasattr(core.domain.amazon, 'get_best_english_title') 
        or not hasattr(core.domain.amazon, 'MULTILINGUAL_COGNATES')
        or not hasattr(core.domain.amazon, 'convert_amazon_eur_to_usd')):
        importlib.reload(core.domain.amazon)
except Exception:
    pass

try:
    from core.domain.amazon import (
        load_amazon_match_scores,
        get_title_match_score,
        load_amazon_broadkast_titles,
        load_broadkast_english_titles,
        get_best_english_title,
        load_amazon_to_bkid_map,
        get_broadkast_title,
        convert_amazon_eur_to_usd,
    )
except ImportError:
    import csv
    import json
    import re
    from difflib import SequenceMatcher
    from pathlib import Path
    from core.normalization.title import normalize_title

    def load_broadkast_english_titles(cache_path=None):
        cp = Path(PROJECT_ROOT) / "data" / "cache" / "broadkast_canonical_english_titles.json" if cache_path is None else Path(cache_path)
        if cp.exists():
            try:
                with open(cp, mode="r", encoding="utf-8") as f:
                    data = json.load(f)
                    res = {}
                    for k, v in data.items():
                        res[k] = v if isinstance(v, list) else [v]
                    return res
            except Exception:
                pass
        return {}

    def get_best_english_title(bkid, match_title=None, amazon_title=None, en_map=None, default=None):
        try:
            import core.domain.amazon as _cda
            return _cda.get_best_english_title(bkid, match_title=match_title, amazon_title=amazon_title, en_map=en_map, default=default)
        except Exception:
            return default or (match_title or (amazon_title or ""))

    def load_amazon_to_bkid_map(mappings_path=None):
        mp = Path(PROJECT_ROOT) / "data" / "output" / "production_mappings.csv" if mappings_path is None else Path(mappings_path)
        if not mp.exists():
            return {}
        b_map = {}
        with open(mp, mode="r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                bkid = (row.get("Broadkast ID") or "").strip()
                orig = (row.get("Amazon Original Title") or "").strip()
                status = (row.get("Match Status") or "").strip().upper()
                if not bkid or bkid == "UNMATCHED" or status == "UNMATCHED":
                    continue
                if orig and orig not in b_map:
                    b_map[orig] = bkid
                norm = normalize_title(orig)
                if norm and norm not in b_map:
                    b_map[norm] = bkid
        return b_map

    def load_amazon_broadkast_titles(mappings_path=None):
        mp = Path(PROJECT_ROOT) / "data" / "output" / "production_mappings.csv" if mappings_path is None else Path(mappings_path)
        if not mp.exists():
            return {}
        t_map = {}
        with open(mp, mode="r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                bkid = (row.get("Broadkast ID") or "").strip()
                btitle = (row.get("Broadkast Assigned Title") or "").strip()
                orig = (row.get("Amazon Original Title") or "").strip()
                status = (row.get("Match Status") or "").strip().upper()
                if not btitle or bkid == "UNMATCHED" or status == "UNMATCHED" or re.search(r" - Ep \d+$", btitle):
                    continue
                if bkid and bkid not in t_map:
                    t_map[bkid] = btitle
                if orig and orig not in t_map:
                    t_map[orig] = btitle
                norm = normalize_title(orig)
                if norm and norm not in t_map:
                    t_map[norm] = btitle
        return t_map

    def get_broadkast_title(bkid=None, amazon_title=None, default=None, title_map=None):
        if not title_map:
            return default or (amazon_title or "")
        if bkid and str(bkid).strip() in title_map:
            return title_map[str(bkid).strip()]
        if amazon_title:
            t = str(amazon_title).strip()
            if t in title_map:
                return title_map[t]
            norm = normalize_title(t)
            if norm in title_map:
                return title_map[norm]
        return default or (amazon_title or "")

    def convert_amazon_eur_to_usd(amount_eur, currency=None):
        if amount_eur is None:
            return 0.0
        val = float(amount_eur)
        if currency and str(currency).strip().upper() == "USD":
            return round(val, 6)
        return round(val * (1.0 / 0.92), 6)

st.set_page_config(page_title="Business Intelligence", layout="wide", page_icon="📊")
apply_portal_style()

st.title("Business Intelligence & Reports", anchor=False)
st.markdown("---")

st.subheader("Consola de Consolidación de Negocio", anchor=False)
st.markdown("""
Esta interfaz unifica la capa relacional y el almacén de eventos para generar los reportes oficiales de rendimiento financiero y KPIs operacionales. 
""")

with st.expander("💱 Configuración y Edición de Tipos de Cambio (FX: CNY / USD / EUR)", expanded=False):
    st.markdown("""
    **Tabla de Correspondencia y Conversión Monetaria Oficial:**
    - **Plataformas Chinas (Tencent, Youku, iQIYI):** Sus ingresos se liquidan en Yuanes (RMB ¥) y se convierten a USD ($) dividiendo entre la tasa `CNY / 1 USD`.
    - **Visualización en Euros (EUR €):** Si seleccionas EUR (€) en el selector de divisa, todos los ingresos en USD se convierten a EUR multiplicando por la tasa `EUR / 1 USD`.
    - **Edición en vivo:** Puedes modificar directamente cualquier celda y pulsar **Guardar Tipos de Cambio**. Se guardará en `config/exchange_rates.json` y se aplicará de inmediato a todos los cálculos.
    """)
    col_fx_mode, col_fx_year, col_fx_space = st.columns([2, 2, 4])
    fx_mode = col_fx_mode.radio("Granularidad de visualización / edición:", ["Mensual", "Anual"], index=0, horizontal=True, key="fx_mode_selector")
    mode_str = "monthly" if fx_mode == "Mensual" else "annual"
    df_fx_full = get_rates_dataframe(mode=mode_str)
    
    if mode_str == "monthly":
        fx_years = ["Todos"] + sorted(list(set(df_fx_full["period"].str[:4])), reverse=True)
        selected_fx_year = col_fx_year.selectbox("Filtrar meses por año:", fx_years, index=0, key="fx_year_filter")
        df_fx_display = df_fx_full[df_fx_full["period"].str.startswith(selected_fx_year)] if selected_fx_year != "Todos" else df_fx_full
    else:
        df_fx_display = df_fx_full

    edited_fx = st.data_editor(
        df_fx_display,
        key=f"fx_editor_{mode_str}_{st.session_state.get('fx_reset_counter', 0)}",
        disabled=["period"],
        column_config={
            "period": st.column_config.TextColumn("Periodo (Mes/Año)" if mode_str == "monthly" else "Año", help="Periodo temporal de aplicación"),
            "cny_per_usd": st.column_config.NumberColumn("CNY / 1 USD (¥/$)", min_value=1.0, max_value=25.0, step=0.01, format="%.4f", help="Yuanes chinos necesarios por 1 USD"),
            "eur_per_usd": st.column_config.NumberColumn("EUR / 1 USD (€/$)", min_value=0.1, max_value=5.0, step=0.001, format="%.4f", help="Euros por 1 USD (ej. 0.925)"),
            "usd_per_eur": st.column_config.NumberColumn("USD / 1 EUR ($/€)", min_value=0.1, max_value=5.0, step=0.001, format="%.4f", help="Dólares por 1 EUR (Inversa: 1 / EUR_per_USD)"),
        },
        use_container_width=True,
        hide_index=True,
    )

    col_btn1, col_btn2, _ = st.columns([2, 2, 4])
    if col_btn1.button("💾 Guardar Tipos de Cambio", key="save_fx_btn", type="primary"):
        if mode_str == "monthly" and selected_fx_year != "Todos":
            df_to_save = df_fx_full.copy()
            df_to_save.set_index("period", inplace=True)
            edited_indexed = edited_fx.set_index("period")
            df_to_save.update(edited_indexed)
            df_to_save.reset_index(inplace=True)
        else:
            df_to_save = edited_fx
        save_rates_dataframe(df_to_save, mode=mode_str)
        st.cache_data.clear()
        st.success("✅ Tipos de cambio guardados correctamente en `config/exchange_rates.json`.")
        st.rerun()

    if col_btn2.button("🔄 Restaurar Valores Oficiales por Defecto", key="reset_fx_btn"):
        reset_to_defaults()
        st.cache_data.clear()
        st.session_state["fx_reset_counter"] = st.session_state.get("fx_reset_counter", 0) + 1
        st.success("✅ Tipos de cambio restaurados a los benchmarks oficiales por defecto.")
        st.rerun()



db_psql = get_postgres_connection()
if db_psql is not None and db_psql.closed != 0:
    st.cache_resource.clear()
    db_psql = get_postgres_connection()

db_mongo = get_mongo_client()

@st.cache_data(show_spinner=False)
def to_excel_bytes(df: pd.DataFrame, sheet_name_val: str, currency_symbol: str = "$") -> bytes:
    """
    Exporta un DataFrame a Excel (.xlsx) con formato y estilizado corporativo Amuse:
    - Cabeceras en azul marino (#1E3A8A) con texto en blanco negrita y ajuste de texto.
    - Cuadrícula visible, inmovilización de paneles (Freeze Panes A2) y autofiltros activos.
    - Detección automática y formateo numérico: Moneda ($#,##0.00), Métricas (#,##0) y % (0.0%).
    - Ajuste dinámico de ancho de columnas y filas de totales resaltadas con doble borde inferior.
    """
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    output = io.BytesIO()
    clean_sheet_name = str(sheet_name_val)[:31] if sheet_name_val else "Report"

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=clean_sheet_name)
        ws = writer.sheets[clean_sheet_name]

        # 1. Asegurar visualización de líneas de cuadrícula
        if ws.views.sheetView:
            ws.views.sheetView[0].showGridLines = True

        # 2. Inmovilizar cabecera y activar autofiltros
        ws.freeze_panes = "A2"
        if ws.max_row > 1 and ws.max_column > 0:
            ws.auto_filter.ref = ws.dimensions

        # 3. Paleta de estilos corporativos
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

        border_side = Side(style="thin", color="CBD5E1")
        cell_border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)

        total_font = Font(name="Calibri", size=10, bold=True)
        total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        total_border = Border(
            left=border_side,
            right=border_side,
            top=Side(style="thin", color="1E3A8A"),
            bottom=Side(style="double", color="1E3A8A")
        )

        # 4. Estilizar fila de cabecera
        ws.row_dimensions[1].height = 28
        for col_idx, col_name in enumerate(df.columns, start=1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_align
            cell.border = cell_border

        # 5. Formatear celdas de datos según su tipo
        is_totals_sheet = "total" in clean_sheet_name.lower()

        for row_idx in range(2, ws.max_row + 1):
            ws.row_dimensions[row_idx].height = 20
            first_val = str(ws.cell(row=row_idx, column=1).value or "").lower()
            second_val = str(ws.cell(row=row_idx, column=2).value or "").lower() if ws.max_column >= 2 else ""
            is_total_row = is_totals_sheet or "total" in first_val or "total" in second_val

            for col_idx, col_name in enumerate(df.columns, start=1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = total_font if is_total_row else Font(name="Calibri", size=10)
                cell.border = total_border if is_total_row else cell_border
                if is_total_row:
                    cell.fill = total_fill

                c_name = str(col_name).lower()

                # Formatos numéricos inteligentes
                if 'cph_rate' in c_name:
                    cell.number_format = f'{currency_symbol}#,##0.0000'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif any(k in c_name for k in ['revenue_cny', 'cny', 'rmb', '¥']):
                    cell.number_format = '¥#,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif any(k in c_name for k in ['revenue', 'cpm', 'ingreso', 'ad_revenue', 'usd', 'eur', 'divisa', '$', '€', 'tarifa']):
                    cell.number_format = f'{currency_symbol}#,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif any(k in c_name for k in ['watch_time', 'hours', 'horas', 'avg_view_minutes']):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif any(k in c_name for k in ['views', 'visualiz', 'likes', 'comments', 'impressions', 'impresion', 'minuto', 'versione', 'publicacion', 'republicacion', 'reproduccion', 'video']):
                    cell.number_format = '#,##0'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif any(k in c_name for k in ['%', 'ratio', 'ctr', 'share', 'tasa', 'porcentaje', 'acierto', 'match_score']):
                    if isinstance(cell.value, (int, float)) and cell.value > 1.0:
                        cell.value = cell.value / 100.0
                    cell.number_format = '0.0%'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif any(k in c_name for k in ['country', 'geography', 'plataforma', 'platform', 'month', 'mes', 'season', 'temporada', 'episode_number', 'código', 'code', 'date', 'fecha']):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        # 6. Ajuste inteligente de ancho de columnas
        for col_idx, col_name in enumerate(df.columns, start=1):
            max_len = len(str(col_name))
            for r in range(2, min(ws.max_row + 1, 150)):
                val = ws.cell(row=r, column=col_idx).value
                if val is not None:
                    val_str = str(val)
                    if "http" in val_str:
                        max_len = max(max_len, 35)
                    else:
                        max_len = max(max_len, len(val_str))
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 50)

    return output.getvalue()

@st.cache_data(show_spinner=False)
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode('utf-8')


def generate_export_filename(f: dict, table_type: str, platform_override: str | None = None, ext: str = "xlsx", is_totals: bool = False) -> str:
    """
    Formato estandarizado en inglés:
    - Tablas de contenido: {search_period}_{Platform}_{granularity}_{table_type}_by_{aggregation_level}.{ext}
    - Tablas de totales:    {search_period}_{Platform}_{granularity}_{table_type}_global_totals.{ext}
    Ejemplo: 2025_01_01__2025_01_07_Youtube_Amazon_daily_comparative_by_canon_episode.xlsx
    """
    fecha_ini = f.get('fecha_inicio', datetime.now())
    fecha_fin = f.get('fecha_fin', datetime.now())
    temp_mode = f.get('temp_mode', 'monthly')

    if temp_mode == 'yearly':
        period_str = f"{fecha_ini.strftime('%Y')}__{fecha_fin.strftime('%Y')}"
    elif temp_mode == 'monthly':
        period_str = f"{fecha_ini.strftime('%Y_%m')}__{fecha_fin.strftime('%Y_%m')}"
    else:  # daily
        period_str = f"{fecha_ini.strftime('%Y_%m_%d')}__{fecha_fin.strftime('%Y_%m_%d')}"

    if platform_override:
        plat_str = platform_override
    else:
        plat_parts = []
        if f.get('use_youtube', True):
            plat_parts.append("Youtube")
        if f.get('use_amazon', False):
            plat_parts.append("Amazon")
        if f.get('use_tencent', False):
            plat_parts.append("Tencent")
        if f.get('use_youku', False):
            plat_parts.append("Youku")
        if f.get('use_iqiyi', False):
            plat_parts.append("iQIYI")
        plat_str = "_".join(plat_parts) if plat_parts else "Consolidated"

    granularity_str = temp_mode.lower()
    if f.get('consolidar_periodo'):
        granularity_str = f"{granularity_str}_aggregated"

    if is_totals:
        return f"{period_str}_{plat_str}_{granularity_str}_{table_type}_global_totals.{ext}"

    agg_mapping = {
        "Por Propiedad Intelectual (IP)": "ip",
        "Por Serie": "series",
        "Episodio Canónico (Todas las versiones)": "canon_episode",
        "Por Serie / IP (Comparativa Multiplataforma)": "series_ip",
        "Por Idioma (Separar traducciones)": "language",
        "Por Territorio / País": "territory",
        "Por Vídeo/Versión (Mostrar resubidas)": "video_version"
    }
    agg_str = agg_mapping.get(f.get('agg_level', ''), 'canon_episode')

    return f"{period_str}_{plat_str}_{granularity_str}_{table_type}_by_{agg_str}.{ext}"


@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options(_db_psql):
    if _db_psql is None:
        return [], [], [], [], [], [], {}, [], {}
    try:
        _db_psql.rollback()
        with _db_psql.cursor() as cursor:
            cursor.execute("SELECT DISTINCT project_name FROM amuseplatforms_db.projects WHERE project_name IS NOT NULL ORDER BY project_name;")
            lista_ips = [row[0] for row in cursor.fetchall()]
            for extra_ip in ('UNMATCHED', 'CHANNEL_LEVEL'):
                if extra_ip not in lista_ips:
                    lista_ips.append(extra_ip)
            yt_catalog = YouTubeChannelCatalog.get_instance()
            for yt_ip in yt_catalog._ip_to_channels.keys():
                if yt_ip and yt_ip not in lista_ips:
                    lista_ips.append(yt_ip)
            lista_ips.sort()
            
            cursor.execute("SELECT DISTINCT series_name FROM amuseplatforms_db.series WHERE series_name IS NOT NULL ORDER BY series_name;")
            lista_series = [row[0] for row in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT season FROM amuseplatforms_db.episodes WHERE season IS NOT NULL ORDER BY season;")
            lista_seasons = [int(row[0]) for row in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT episode_number FROM amuseplatforms_db.episodes WHERE episode_number IS NOT NULL ORDER BY episode_number;")
            lista_episodios = [int(row[0]) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT DISTINCT country_code, country_name, language_code, language_name 
                FROM amuseplatforms_db.countries 
                WHERE country_code IS NOT NULL 
                ORDER BY country_name;
            """)
            raw_countries = cursor.fetchall()
            df_countries_info = pd.DataFrame(raw_countries, columns=['country_code', 'country_name', 'language_code', 'language_name'])
            
            lista_territorios_display = [f"{r['country_code']} - {r['country_name']}" for _, r in df_countries_info.iterrows()]
            geo_to_lang = dict(zip(df_countries_info['country_code'], df_countries_info['language_code']))
            
            df_langs = df_countries_info.dropna(subset=['language_code', 'language_name']).drop_duplicates(subset=['language_code']).sort_values('language_name')
            lista_idiomas_display = [f"{r['language_name']} ({r['language_code']})" for _, r in df_langs.iterrows()]

            cursor.execute("""
                SELECT DISTINCT channel_id, serie_name 
                FROM amuseplatforms_db.youtube_channels 
                WHERE serie_name IS NOT NULL AND TRIM(serie_name) != ''
                ORDER BY serie_name;
            """)
            raw_channels = cursor.fetchall()
            lista_canales_display = [f"{r[1]} ({r[0]})" for r in raw_channels]
            channel_display_to_id = {f"{r[1]} ({r[0]})": r[0] for r in raw_channels}
            lista_canales_display.append("Amazon Prime Video")
            channel_display_to_id["Amazon Prime Video"] = "Amazon Prime Video"
            for extra_ch in (
                "Tencent Video", "Tencent Video (SVOD)", "Tencent Video (AVOD)",
                "Youku", "Youku (Open Platform)", "Youku (DaYu CC / LTV)",
                "iQIYI", "iQIYI (Amuse CC)", "iQIYI (Amuse LTV / France)", "iQIYI (Amuse Shanghai)",
            ):
                lista_canales_display.append(extra_ch)
                channel_display_to_id[extra_ch] = extra_ch
            lista_canales_display.sort()

            _db_psql.rollback()
            return lista_ips, lista_series, lista_seasons, lista_episodios, lista_territorios_display, lista_idiomas_display, geo_to_lang, lista_canales_display, channel_display_to_id
    except Exception as e:
        if _db_psql:
            try:
                _db_psql.rollback()
            except:
                pass
        return [], [], [], [], [], [], {}, [], {}


@st.cache_data(ttl=3600)
def fetch_yt_metadata(_db_psql, ips, series, seasons, episodes, languages, geos, channels=None):
    sql_base = '''
    SELECT 
        yv.video_id,
        yc.channel_id,
        COALESCE(
            yc.country_code, 
            c_lang.country_code,
            c_eyv.country_code,
            'Unknown Geo'
        ) AS geography,
        COALESCE(e.season, e_en.season, 0) AS season,
        COALESCE(e.episode_number, e_en.episode_number, 0) AS episode_number,
        CASE 
            WHEN p.project_name = 'UNMATCHED' 
                 OR eyv.series_code = 'LGCY_SR' 
                 OR COALESCE(e.episode_number, e_en.episode_number, 0) IN (1111, 9999)
                 OR COALESCE(NULLIF(e_en.title, ''), NULLIF(e.title, '')) = 'Legacy Compilation'
            THEN COALESCE(NULLIF(yv.title, ''), 'Unknown Video')
            ELSE COALESCE(
                NULLIF(NULLIF(e_en.title, 'Legacy Compilation'), ''), 
                NULLIF(NULLIF(e.title, 'Legacy Compilation'), ''), 
                NULLIF(s.series_name || ' - Ep ' || COALESCE(e.episode_number, e_en.episode_number)::varchar, ''),
                NULLIF(yv.title, ''), 
                'Unknown Video'
            ) 
        END AS episode_name,
        COALESCE(NULLIF(s.series_name, ''), NULLIF(yc.serie_name, ''), 'UNMATCHED_YT') AS series_name,
        COALESCE(NULLIF(p.project_name, ''), 'UNMATCHED') AS ip_name,
        COALESCE(eyv.language_code, NULLIF(yc.language, ''), 'Unknown') AS language_code,
        COALESCE(NULLIF(yv.title, ''), 'Unknown Video') AS video_title,
        yv.duration AS video_duration,
        COALESCE(NULLIF(yc.serie_name, ''), yc.channel_id, 'Unknown Channel') AS channel_name
    FROM amuseplatforms_db.youtube_videos yv
    LEFT JOIN amuseplatforms_db.youtube_channels yc ON yv.channel_id = yc.channel_id
    LEFT JOIN amuseplatforms_db.episode_youtube_video eyv ON yv.video_id = eyv.video_id
    LEFT JOIN amuseplatforms_db.episodes e_en ON eyv.episode_number = e_en.episode_number 
        AND e_en.language_code = 'en' 
        AND eyv.series_code = e_en.series_code
    LEFT JOIN amuseplatforms_db.episodes e ON eyv.episode_number = e.episode_number 
        AND eyv.language_code = e.language_code 
        AND eyv.series_code = e.series_code
    LEFT JOIN amuseplatforms_db.series s ON eyv.series_code = s.series_code
    LEFT JOIN amuseplatforms_db.projects p ON s.project_code = p.project_code
    LEFT JOIN (
        SELECT DISTINCT ON (LOWER(language_name)) LOWER(language_name) as lang_lower, country_code
        FROM amuseplatforms_db.countries
        ORDER BY LOWER(language_name), country_code
    ) c_lang ON LOWER(yc.language) = c_lang.lang_lower
    LEFT JOIN (
        SELECT DISTINCT ON (LOWER(language_code)) LOWER(language_code) as code_lower, country_code
        FROM amuseplatforms_db.countries
        ORDER BY LOWER(language_code), country_code
    ) c_eyv ON LOWER(SPLIT_PART(eyv.language_code, '-', 1)) = c_eyv.code_lower
    WHERE 1=1
    '''
    params = []
    if ips:
        catalog = YouTubeChannelCatalog.get_instance()
        extra_cids = []
        for ip_item in ips:
            extra_cids.extend(catalog.get_channels_for_ip(ip_item))
            extra_cids.extend(catalog.get_channels_for_universe(ip_item))
        extra_cids = list(set(extra_cids))
        if extra_cids:
            sql_base += " AND (p.project_name IN %s OR yc.channel_id IN %s)"
            params.append(tuple(ips))
            params.append(tuple(extra_cids))
        else:
            sql_base += " AND p.project_name IN %s"
            params.append(tuple(ips))
    if series:
        sql_base += " AND s.series_name IN %s"
        params.append(tuple(series))
    if channels:
        sql_base += " AND yc.channel_id IN %s"
        params.append(tuple(channels))
    if seasons:
        sql_base += " AND e.season IN %s"
        params.append(tuple(seasons))
    if episodes:
        sql_base += " AND e.episode_number IN %s"
        params.append(tuple(episodes))
    
    try:
        _db_psql.rollback()
        with _db_psql.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY;")
        df_meta = pd.read_sql_query(sql_base, _db_psql, params=params if params else None)
        _db_psql.rollback()  # Release transaction

        if not df_meta.empty:
            df_meta = enrich_youtube_dataframe(df_meta, channel_col='channel_id', ip_col='ip_name', series_col='series_name')
            if ips:
                df_meta = df_meta[df_meta['ip_name'].isin(ips) | df_meta.get('universe', pd.Series(dtype=str)).isin(ips)]

        if languages and not df_meta.empty:
            mask_lang = df_meta['language_code'].apply(
                lambda x: any(str(x).lower().startswith(l.lower()) for l in languages)
            )
            df_meta = df_meta[mask_lang]
            
        if geos and not df_meta.empty:
            df_meta = df_meta[df_meta['geography'].isin(geos)]

        return df_meta
    except Exception as e:
        if _db_psql:
            try:
                _db_psql.rollback()
            except:
                pass
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_amz_metadata(_db_psql_amz, _db_psql, ips, series, seasons, episodes, channels=None):
    if channels and "Amazon Prime Video" not in channels:
        return pd.DataFrame()
    sql_amz = '''
    SELECT 
        'EP_' || e.id::varchar AS video_id,
        s_season.number AS season,
        e.number AS episode_number,
        COALESCE(
            NULLIF((
                SELECT mt.title 
                FROM public.episode_versions ev 
                JOIN public.metadata_titles mt ON mt.episode_version_id = ev.id 
                WHERE ev.episode_id = e.id 
                  AND mt.title IS NOT NULL AND TRIM(mt.title) != ''
                  AND UPPER(TRIM(mt.title)) NOT IN ('INTRO', 'OUTRO')
                ORDER BY 
                    CASE WHEN ev.language_code = 'en' THEN 1
                         WHEN ev.language_code LIKE 'en%' THEN 2
                         WHEN ev.language_code IN ('es', 'es-las') THEN 3
                         ELSE 4 END,
                    LENGTH(mt.title) ASC
                LIMIT 1
            ), ''),
            NULLIF(e.name, ''),
            s.name || ' - Ep ' || e.number::varchar,
            'Unknown Episode'
        ) AS episode_name,
        s.name AS series_name,
        p.name AS ip_name,
        'Amazon Prime Video' AS channel_id,
        'Multi-idioma' AS language_code,
        COALESCE(NULLIF(e.name, ''), s.name || ' - Ep ' || e.number::varchar, 'Unknown Episode') AS video_title,
        0 AS video_duration,
        'Amazon Prime Video' AS channel_name
    FROM public.episodes e
    LEFT JOIN public.seasons s_season ON e.season_id = s_season.id
    LEFT JOIN public.series s ON e.series_id = s.id
    LEFT JOIN public.projects p ON s.project_id = p.id
    WHERE 1=1
      AND e.number NOT IN (1111, 9999)
    '''
    params_amz = []
    if ips:
        sql_amz += " AND p.name IN %s"
        params_amz.append(tuple(ips))
    if series:
        sql_amz += " AND s.name IN %s"
        params_amz.append(tuple(series))
    if seasons:
        sql_amz += " AND s_season.number IN %s"
        params_amz.append(tuple(seasons))
    if episodes:
        sql_amz += " AND e.number IN %s"
        params_amz.append(tuple(episodes))
        
    try:
        _db_psql_amz.rollback()
        with _db_psql_amz.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY;")
        df_meta_amz = pd.read_sql_query(sql_amz, _db_psql_amz, params=params_amz if params_amz else None)
        _db_psql_amz.rollback()  # Release transaction

        # 1. Recuperar el título canónico en inglés de Broadkast desde caché o production_mappings.csv si era genérico
        en_title_map = load_broadkast_english_titles()
        bk_title_map = load_amazon_broadkast_titles()
        if not df_meta_amz.empty:
            mask_generic = (
                df_meta_amz['episode_name'].str.contains(r' - Ep \d+$', regex=True) |
                df_meta_amz['episode_name'].isin(['Unknown Episode', 'Unknown Video', ''])
            )
            if mask_generic.any():
                s_en_meta = df_meta_amz['video_id'].apply(lambda x: get_best_english_title(x, en_map=en_title_map) if en_title_map else np.nan)
                s_bk_meta = df_meta_amz['video_id'].map(bk_title_map) if bk_title_map else pd.Series(np.nan, index=df_meta_amz.index)
                s_target_meta = np.where(s_en_meta.notna() & (s_en_meta != ''), s_en_meta, s_bk_meta)
                has_target = pd.Series(s_target_meta, index=df_meta_amz.index).notna() & (pd.Series(s_target_meta, index=df_meta_amz.index) != '')
                df_meta_amz['episode_name'] = np.where(
                    mask_generic & has_target,
                    s_target_meta,
                    df_meta_amz['episode_name']
                )

        # 2. Si todavía tiene formato genérico de fallback ('... - Ep ...' o 'Unknown Episode'), buscar en amuseplatforms_db
        mask_generic = df_meta_amz['episode_name'].str.contains(r' - Ep \d+$', regex=True) | df_meta_amz['episode_name'].isin(['Unknown Episode', 'Unknown Video', ''])
        if mask_generic.any() and _db_psql and not df_meta_amz.empty:
            sql_en = '''
            SELECT s.series_name, e.season, e.episode_number, e.title as english_name
            FROM amuseplatforms_db.episodes e
            JOIN amuseplatforms_db.series s ON e.series_code = s.series_code
            WHERE e.language_code = 'en'
            '''
            _db_psql.rollback()
            with _db_psql.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY;")
            df_en = pd.read_sql_query(sql_en, _db_psql)
            df_en = df_en.drop_duplicates(subset=['series_name', 'season', 'episode_number'])
            _db_psql.rollback()

            df_meta_amz = df_meta_amz.merge(df_en, on=['series_name', 'season', 'episode_number'], how='left')
            df_meta_amz['episode_name'] = np.where(
                mask_generic & df_meta_amz['english_name'].notna() & (df_meta_amz['english_name'] != ''),
                df_meta_amz['english_name'],
                df_meta_amz['episode_name']
            )
            df_meta_amz.drop(columns=['english_name'], inplace=True, errors='ignore')

        return df_meta_amz
    except Exception as e:
        if _db_psql_amz:
            try:
                _db_psql_amz.rollback()
            except:
                pass
        return pd.DataFrame()


def assign_name_score(df, col='episode_name'):
    if 'name_score' in df.columns:
        df = df.drop(columns=['name_score'])
    def get_score(title):
        if pd.isna(title):
            return 0
        t = str(title)
        if t in ['Unknown Episode', 'Unknown Video', 'Legacy Compilation']:
            return 4
        if ' - Ep ' in t or re.search(r' - Ep \d+', t):
            return 3
        if re.search(r'[^\x00-\x7F]', t):
            return 2
        return 1
    df['name_score'] = df[col].apply(get_score)
    return df


def format_youtube_url(val):
    if pd.isna(val) or not val:
        return ""
    s_val = str(val).strip()
    if s_val == "0" or s_val.startswith(("EP_", "UNMATCHED_AMZ_")):
        return ""
    return f"https://www.youtube.com/watch?v={s_val}"


def _passes_china_common_filters(
    global_seasons: list | None,
    global_episodes: list | None,
    selected_geo_codes: list | None,
    selected_lang_codes: list | None,
) -> bool:
    """Comprueba filtros de temporada, episodio, geografía ('CN') e idioma ('zh') para plataformas chinas."""
    if global_seasons and 0 not in global_seasons and "0" not in [str(s).strip() for s in global_seasons]:
        return False
    if global_episodes and 0 not in global_episodes and "0" not in [str(e).strip() for e in global_episodes]:
        return False
    if selected_geo_codes and "CN" not in [str(g).strip().upper() for g in selected_geo_codes]:
        return False
    if selected_lang_codes:
        lang_match = any(
            str(l).strip().lower().startswith("zh") or "zh".startswith(str(l).strip().lower())
            for l in selected_lang_codes
        )
        if not lang_match:
            return False
    return True


def fetch_tencent_reports(
    db_mongo,
    temp_mode: str,
    fecha_inicio,
    fecha_fin,
    global_ips: list | None = None,
    global_series: list | None = None,
    global_channels: list | None = None,
    global_producers: list | None = None,
    selected_geo_codes: list | None = None,
    selected_lang_codes: list | None = None,
    global_seasons: list | None = None,
    global_episodes: list | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Consulta en MongoDB los datos históricos de Tencent Video (SVOD + AVOD) y aplica los filtros globales."""
    if db_mongo is None:
        return pd.DataFrame(), pd.DataFrame()

    # Filtro de canales específico para Tencent
    allow_svod, allow_avod = True, True
    if global_channels:
        has_all_tcn = "Tencent Video" in global_channels
        has_svod = "Tencent Video (SVOD)" in global_channels
        has_avod = "Tencent Video (AVOD)" in global_channels
        if not (has_all_tcn or has_svod or has_avod):
            return pd.DataFrame(), pd.DataFrame()
        if not has_all_tcn:
            allow_svod = has_svod
            allow_avod = has_avod

    if not _passes_china_common_filters(global_seasons, global_episodes, selected_geo_codes, selected_lang_codes):
        return pd.DataFrame(), pd.DataFrame()

    if temp_mode == "yearly":
        coll_mongo = db_mongo["yearly_performance_summaries"]
        match_stage = {
            "_id.platform": "tencent",
            "_id.event_type": "tencent.video.performance_recorded",
            "_id.year": {
                "$gte": fecha_inicio.strftime("%Y"),
                "$lte": fecha_fin.strftime("%Y"),
            },
        }
        pipeline = [
            {"$match": match_stage},
            {
                "$group": {
                    "_id": {
                        "video_id": "$_id.video_id",
                        "month": "$_id.year",
                        "platform": "$_id.platform",
                        "geography": "$_id.geography",
                    },
                    "mongo_title": {"$first": "$title"},
                    "mongo_ip": {"$first": "$ip_name"},
                    "mongo_series": {"$first": "$series_name"},
                    "revenue": {"$sum": "$yearly_revenue"},
                    "revenue_cny": {"$sum": {"$ifNull": ["$yearly_revenue_cny", 0]}},
                    "revenue_svod": {"$sum": {"$ifNull": ["$yearly_revenue_svod", 0]}},
                    "revenue_avod": {"$sum": {"$ifNull": ["$yearly_revenue_avod", 0]}},
                    "views": {"$sum": "$yearly_views"},
                    "watch_time": {"$sum": {"$ifNull": ["$yearly_watch_time", 0]}},
                }
            },
        ]
    elif temp_mode == "daily":
        coll_mongo = db_mongo[os.getenv("MONGODB_ANALYTICS_COLLECTION", "video_performance_events")]
        match_stage = {
            "metadata.event_type": "tencent.video.performance_recorded",
            "payload.date": {
                "$gte": fecha_inicio.strftime("%Y-%m-%d"),
                "$lte": fecha_fin.strftime("%Y-%m-%d"),
            },
        }
        pipeline = [
            {"$match": match_stage},
            {
                "$group": {
                    "_id": {
                        "video_id": "$payload.video_id",
                        "month": "$payload.date",
                        "platform": "$payload.platform",
                        "geography": {"$ifNull": ["$payload.geography", "CN"]},
                    },
                    "mongo_title": {"$first": "$payload.title"},
                    "mongo_ip": {"$first": "$payload.ip_name"},
                    "mongo_series": {"$first": "$payload.series_name"},
                    "monetization_model": {
                        "$first": {"$ifNull": ["$payload.extra_metrics.monetization_model", "$metadata.offer_type"]}
                    },
                    "revenue": {"$sum": {"$ifNull": ["$payload.estimated_revenue", 0]}},
                    "revenue_cny": {"$sum": {"$ifNull": ["$payload.extra_metrics.revenue_cny", 0]}},
                    "revenue_svod": {"$sum": {"$ifNull": ["$payload.extra_metrics.revenue_svod", 0]}},
                    "revenue_avod": {"$sum": {"$ifNull": ["$payload.extra_metrics.revenue_avod", 0]}},
                    "views": {"$sum": {"$ifNull": ["$payload.extra_metrics.views", 0]}},
                    "watch_time": {"$sum": {"$ifNull": ["$payload.extra_metrics.estimated_minutes_watched", 0]}},
                }
            },
        ]
    else:  # monthly
        coll_mongo = db_mongo["monthly_performance_summaries"]
        match_stage = {
            "_id.platform": "tencent",
            "_id.event_type": "tencent.video.performance_recorded",
            "_id.month": {
                "$gte": fecha_inicio.strftime("%Y-%m"),
                "$lte": fecha_fin.strftime("%Y-%m"),
            },
        }
        pipeline = [
            {"$match": match_stage},
            {
                "$group": {
                    "_id": {
                        "video_id": "$_id.video_id",
                        "month": "$_id.month",
                        "platform": "$_id.platform",
                        "geography": "$_id.geography",
                    },
                    "mongo_title": {"$first": "$title"},
                    "mongo_ip": {"$first": "$ip_name"},
                    "mongo_series": {"$first": "$series_name"},
                    "revenue": {"$sum": "$monthly_revenue"},
                    "revenue_cny": {"$sum": {"$ifNull": ["$monthly_revenue_cny", 0]}},
                    "revenue_svod": {"$sum": {"$ifNull": ["$monthly_revenue_svod", 0]}},
                    "revenue_avod": {"$sum": {"$ifNull": ["$monthly_revenue_avod", 0]}},
                    "views": {"$sum": "$monthly_views"},
                    "watch_time": {"$sum": {"$ifNull": ["$monthly_watch_time", 0]}},
                }
            },
        ]

    docs = list(coll_mongo.aggregate(pipeline))
    if not docs:
        return pd.DataFrame(), pd.DataFrame()

    rows = []
    for doc in docs:
        doc_id = doc.get("_id", {})
        video_id = str(doc_id.get("video_id") or "")
        meta = get_tencent_series_metadata(video_id)
        ip_name = doc.get("mongo_ip") or meta["ip_name"]
        series_name = doc.get("mongo_series") or meta["series_name"]
        title = doc.get("mongo_title") or meta["title"]
        model = str(doc.get("monetization_model") or meta["monetization_model"]).upper()
        channel_id = "TENCENT_SVOD" if model == "SVOD" else "TENCENT_AVOD_CHANNEL"

        period_str = str(doc_id.get("month") or "")
        rev_cny = float(doc.get("revenue_cny") or 0.0)
        cny_rate = get_cny_rate(period_str)
        if rev_cny > 0 and cny_rate > 0:
            rev = rev_cny / cny_rate
            if model == "SVOD":
                rev_svod = rev
                rev_avod = 0.0
            elif model == "AVOD":
                rev_avod = rev
                rev_svod = 0.0
            else:
                s_orig = float(doc.get("revenue_svod") or 0.0)
                a_orig = float(doc.get("revenue_avod") or 0.0)
                tot_orig = s_orig + a_orig
                if tot_orig > 0:
                    rev_svod = (s_orig / tot_orig) * rev
                    rev_avod = (a_orig / tot_orig) * rev
                else:
                    rev_svod = rev if model == "SVOD" else 0.0
                    rev_avod = rev if model == "AVOD" else 0.0
        else:
            rev = float(doc.get("revenue") or 0.0)
            rev_svod = float(doc.get("revenue_svod") or (rev if model == "SVOD" else 0.0))
            rev_avod = float(doc.get("revenue_avod") or (rev if model == "AVOD" else 0.0))

        rows.append({
            "month": period_str,
            "ip_name": ip_name,
            "series_name": series_name,
            "season": 0,
            "episode_number": 0,
            "episode_name": title,
            "geography": doc_id.get("geography") or "CN",
            "video_id": video_id,
            "channel_id": channel_id,
            "platform": doc_id.get("platform") or "tencent",
            "language_code": "zh",
            "video_title": title,
            "video_duration": 0,
            "monetization_model": model,
            "revenue": rev,
            "revenue_cny": float(doc.get("revenue_cny") or 0.0),
            "revenue_svod": rev_svod,
            "revenue_avod": rev_avod,
            "views": int(doc.get("views") or 0),
            "watch_time": round(float(doc.get("watch_time") or 0.0) / 60.0, 2),
        })

    df_tcn = pd.DataFrame(rows)
    if df_tcn.empty:
        return pd.DataFrame(), pd.DataFrame()

    allowed_models = []
    if allow_svod:
        allowed_models.append("SVOD")
    if allow_avod:
        allowed_models.append("AVOD")
    df_tcn = df_tcn[df_tcn["monetization_model"].isin(allowed_models)]

    if global_ips:
        df_tcn = df_tcn[df_tcn["ip_name"].isin(global_ips)]
    if global_series:
        df_tcn = df_tcn[df_tcn["series_name"].isin(global_series)]
    if df_tcn.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_tcn["producer"] = df_tcn.apply(
        lambda r: resolve_producer(r.get("video_title"), r.get("series_name"), r.get("ip_name"), platform="tencent"),
        axis=1,
    ).fillna("Amuse Animation")
    if global_producers:
        df_tcn = df_tcn[df_tcn["producer"].isin(global_producers)]
    if df_tcn.empty:
        return pd.DataFrame(), pd.DataFrame()

    tcn_group_cols = [
        "month", "producer", "ip_name", "series_name", "season", "episode_number",
        "episode_name", "geography", "video_id", "channel_id", "platform",
        "language_code", "video_title", "video_duration", "monetization_model",
    ]
    report_fin_tcn = (
        df_tcn.groupby(tcn_group_cols, dropna=False)[["revenue", "revenue_cny", "revenue_svod", "revenue_avod"]]
        .sum()
        .reset_index()
        .sort_values(by=["month", "ip_name", "series_name"])
    )
    report_op_tcn = (
        df_tcn.groupby(tcn_group_cols, dropna=False)[["views", "watch_time"]]
        .sum()
        .reset_index()
        .sort_values(by=["month", "ip_name"])
    )
    return report_fin_tcn, report_op_tcn


def fetch_youku_reports(
    db_mongo,
    temp_mode: str,
    fecha_inicio,
    fecha_fin,
    global_ips: list | None = None,
    global_series: list | None = None,
    global_channels: list | None = None,
    global_producers: list | None = None,
    selected_geo_codes: list | None = None,
    selected_lang_codes: list | None = None,
    global_seasons: list | None = None,
    global_episodes: list | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Consulta en MongoDB los datos históricos de Youku (DaYu + Open Platform) y aplica los filtros globales."""
    if db_mongo is None:
        return pd.DataFrame(), pd.DataFrame()

    allow_open, allow_dayu = True, True
    if global_channels:
        has_all_yku = "Youku" in global_channels
        has_open = "Youku (Open Platform)" in global_channels
        has_dayu = "Youku (DaYu CC / LTV)" in global_channels
        if not (has_all_yku or has_open or has_dayu):
            return pd.DataFrame(), pd.DataFrame()
        if not has_all_yku:
            allow_open = has_open
            allow_dayu = has_dayu

    if not _passes_china_common_filters(global_seasons, global_episodes, selected_geo_codes, selected_lang_codes):
        return pd.DataFrame(), pd.DataFrame()

    def _yku_base_row(video_id: str, period_str: str, geo: str, mongo_title, mongo_ip, mongo_series, rev, rev_cny, rev_avod, rev_svod, views, watch_mins, likes, comments):
        meta = get_youku_series_metadata(video_id)
        subplat = "DaYu Platform" if video_id.startswith("YOUKU_DAYU_") else meta.get("subplatform", "Open Platform")
        ip_name = mongo_ip or meta["ip_name"]
        series_name = mongo_series or meta["series_name"]
        title = mongo_title or meta["title"]
        wt_hrs = round(float(watch_mins or 0.0) / 60.0, 2)
        rev_a = float(rev_avod or 0.0)
        rev_s = float(rev_svod or 0.0)
        rev_val = float(rev or 0.0)
        rev_cny_val = float(rev_cny or 0.0)

        if subplat == "DaYu Platform" and rev_s == 0:
            model = "AVOD"
        elif rev_a > 0 and rev_s > 0:
            model = "AVOD+SVOD"
        elif rev_s > 0 or (wt_hrs > 0 and rev_a == 0):
            model = "SVOD"
        else:
            model = "AVOD"

        # Respetar prioritariamente el revenue en USD ya consolidado en MongoDB (Fix BUG-03)
        if (rev_a + rev_s) <= 0.0:
            cny_rate = get_cny_rate(period_str)
            if rev_cny_val > 0 and cny_rate > 0:
                rev_val = rev_cny_val / cny_rate
                if model == "SVOD":
                    rev_s = rev_val
                elif model == "AVOD":
                    rev_a = rev_val

        ch_id = video_id if subplat == "DaYu Platform" else "YOUKU_OPEN_PLATFORM"
        return {
            "month": period_str,
            "ip_name": ip_name,
            "series_name": series_name,
            "season": 0,
            "episode_number": 0,
            "episode_name": title,
            "geography": geo or "CN",
            "video_id": video_id,
            "channel_id": ch_id,
            "platform": "youku",
            "language_code": "zh",
            "video_title": title,
            "video_duration": 0,
            "subplatform": subplat,
            "monetization_model": model,
            "revenue": rev_val,
            "revenue_cny": rev_cny_val,
            "revenue_avod": rev_a,
            "revenue_svod": rev_s,
            "views": int(views or 0),
            "watch_time": wt_hrs,
            "likes": int(likes or 0),
            "comments": int(comments or 0),
        }

    rows = []
    if temp_mode == "yearly":
        coll_mongo = db_mongo["yearly_performance_summaries"]
        pipeline = [
            {
                "$match": {
                    "_id.platform": "youku",
                    "_id.event_type": "youku.video.performance_recorded",
                    "_id.year": {"$gte": fecha_inicio.strftime("%Y"), "$lte": fecha_fin.strftime("%Y")},
                }
            },
            {
                "$group": {
                    "_id": {"video_id": "$_id.video_id", "month": "$_id.year", "platform": "$_id.platform", "geography": "$_id.geography"},
                    "mongo_title": {"$first": "$title"},
                    "mongo_ip": {"$first": "$ip_name"},
                    "mongo_series": {"$first": "$series_name"},
                    "revenue": {"$sum": "$yearly_revenue"},
                    "revenue_cny": {"$sum": {"$ifNull": ["$yearly_revenue_cny", 0]}},
                    "revenue_avod": {"$sum": {"$ifNull": ["$yearly_revenue_avod", 0]}},
                    "revenue_svod": {"$sum": {"$ifNull": ["$yearly_revenue_svod", 0]}},
                    "views": {"$sum": "$yearly_views"},
                    "watch_time": {"$sum": {"$ifNull": ["$yearly_watch_time", 0]}},
                    "likes": {"$sum": {"$ifNull": ["$yearly_likes", 0]}},
                    "comments": {"$sum": {"$ifNull": ["$yearly_comments", 0]}},
                }
            },
        ]
        for doc in coll_mongo.aggregate(pipeline):
            did = doc.get("_id", {})
            rows.append(_yku_base_row(
                str(did.get("video_id") or ""), str(did.get("month") or ""), did.get("geography") or "CN",
                doc.get("mongo_title"), doc.get("mongo_ip"), doc.get("mongo_series"),
                doc.get("revenue"), doc.get("revenue_cny"), doc.get("revenue_avod"), doc.get("revenue_svod"),
                doc.get("views"), doc.get("watch_time"), doc.get("likes"), doc.get("comments"),
            ))
    elif temp_mode == "daily":
        coll_ev = db_mongo[os.getenv("MONGODB_ANALYTICS_COLLECTION", "video_performance_events")]
        is_op_monthly = {
            "$and": [
                {"$eq": ["$payload.extra_metrics.subplatform", "Open Platform"]},
                {"$eq": ["$payload.extra_metrics.is_monthly_revenue", True]},
            ]
        }
        pipe_daily = [
            {
                "$match": {
                    "metadata.event_type": "youku.video.performance_recorded",
                    "payload.date": {"$gte": fecha_inicio.strftime("%Y-%m-%d"), "$lte": fecha_fin.strftime("%Y-%m-%d")},
                }
            },
            {
                "$group": {
                    "_id": {
                        "video_id": "$payload.video_id",
                        "month": "$payload.date",
                        "platform": "$payload.platform",
                        "geography": {"$ifNull": ["$payload.geography", "CN"]},
                    },
                    "mongo_title": {"$first": "$payload.title"},
                    "mongo_ip": {"$first": "$payload.ip_name"},
                    "mongo_series": {"$first": "$payload.series_name"},
                    "revenue": {"$sum": {"$cond": [is_op_monthly, 0, {"$ifNull": ["$payload.estimated_revenue", 0]}]}},
                    "revenue_cny": {"$sum": {"$cond": [is_op_monthly, 0, {"$ifNull": ["$payload.extra_metrics.revenue_cny", 0]}]}},
                    "revenue_avod": {"$sum": {"$cond": [is_op_monthly, 0, {"$ifNull": ["$payload.extra_metrics.revenue_avod", 0]}]}},
                    "revenue_svod": {"$sum": {"$cond": [is_op_monthly, 0, {"$ifNull": ["$payload.extra_metrics.revenue_svod", 0]}]}},
                    "views": {"$sum": {"$ifNull": ["$payload.extra_metrics.views", 0]}},
                    "watch_time": {"$sum": {"$ifNull": ["$payload.extra_metrics.estimated_minutes_watched", 0]}},
                    "likes": {"$sum": {"$ifNull": ["$payload.extra_metrics.likes", 0]}},
                    "comments": {"$sum": {"$ifNull": ["$payload.extra_metrics.comments", 0]}},
                }
            },
        ]
        for doc in coll_ev.aggregate(pipe_daily):
            did = doc.get("_id", {})
            rows.append(_yku_base_row(
                str(did.get("video_id") or ""), str(did.get("month") or ""), did.get("geography") or "CN",
                doc.get("mongo_title"), doc.get("mongo_ip"), doc.get("mongo_series"),
                doc.get("revenue"), doc.get("revenue_cny"), doc.get("revenue_avod"), doc.get("revenue_svod"),
                doc.get("views"), doc.get("watch_time"), doc.get("likes"), doc.get("comments"),
            ))

        # Prorratear equitativamente los ingresos mensuales de Open Platform entre los días del rango solicitado
        if allow_open:
            coll_mo = db_mongo["monthly_performance_summaries"]
            pipe_op_mo = [
                {
                    "$match": {
                        "_id.event_type": "youku.video.performance_recorded",
                        "_id.video_id": {"$regex": "^YOUKU_OP_"},
                        "_id.month": {"$gte": fecha_inicio.strftime("%Y-%m"), "$lte": fecha_fin.strftime("%Y-%m")},
                    }
                },
                {
                    "$group": {
                        "_id": {"video_id": "$_id.video_id", "month": "$_id.month", "geography": "$_id.geography"},
                        "mongo_title": {"$first": "$title"},
                        "mongo_ip": {"$first": "$ip_name"},
                        "mongo_series": {"$first": "$series_name"},
                        "revenue": {"$sum": "$monthly_revenue"},
                        "revenue_cny": {"$sum": {"$ifNull": ["$monthly_revenue_cny", 0]}},
                        "revenue_avod": {"$sum": {"$ifNull": ["$monthly_revenue_avod", 0]}},
                        "revenue_svod": {"$sum": {"$ifNull": ["$monthly_revenue_svod", 0]}},
                    }
                },
            ]
            op_mo_docs = list(coll_mo.aggregate(pipe_op_mo))
            if op_mo_docs:
                days_by_ym = {}
                cur_d = fecha_inicio
                while cur_d <= fecha_fin:
                    ym = cur_d.strftime("%Y-%m")
                    days_by_ym.setdefault(ym, []).append((cur_d.strftime("%Y-%m-%d"), calendar.monthrange(cur_d.year, cur_d.month)[1]))
                    cur_d += timedelta(days=1)
                for doc in op_mo_docs:
                    rev_tot = float(doc.get("revenue") or 0.0)
                    if rev_tot <= 0.0:
                        continue
                    did = doc.get("_id", {})
                    ym = str(did.get("month") or "")
                    vid = str(did.get("video_id") or "")
                    geo = did.get("geography") or "CN"
                    for day_str, days_in_m in days_by_ym.get(ym, []):
                        rows.append(_yku_base_row(
                            vid, day_str, geo,
                            doc.get("mongo_title"), doc.get("mongo_ip"), doc.get("mongo_series"),
                            rev_tot / days_in_m,
                            float(doc.get("revenue_cny") or 0.0) / days_in_m,
                            float(doc.get("revenue_avod") or 0.0) / days_in_m,
                            float(doc.get("revenue_svod") or 0.0) / days_in_m,
                            0, 0.0, 0, 0,
                        ))
    else:  # monthly
        coll_mongo = db_mongo["monthly_performance_summaries"]
        pipeline = [
            {
                "$match": {
                    "_id.platform": "youku",
                    "_id.event_type": "youku.video.performance_recorded",
                    "_id.month": {"$gte": fecha_inicio.strftime("%Y-%m"), "$lte": fecha_fin.strftime("%Y-%m")},
                }
            },
            {
                "$group": {
                    "_id": {"video_id": "$_id.video_id", "month": "$_id.month", "platform": "$_id.platform", "geography": "$_id.geography"},
                    "mongo_title": {"$first": "$title"},
                    "mongo_ip": {"$first": "$ip_name"},
                    "mongo_series": {"$first": "$series_name"},
                    "revenue": {"$sum": "$monthly_revenue"},
                    "revenue_cny": {"$sum": {"$ifNull": ["$monthly_revenue_cny", 0]}},
                    "revenue_avod": {"$sum": {"$ifNull": ["$monthly_revenue_avod", 0]}},
                    "revenue_svod": {"$sum": {"$ifNull": ["$monthly_revenue_svod", 0]}},
                    "views": {"$sum": "$monthly_views"},
                    "watch_time": {"$sum": {"$ifNull": ["$monthly_watch_time", 0]}},
                    "likes": {"$sum": {"$ifNull": ["$monthly_likes", 0]}},
                    "comments": {"$sum": {"$ifNull": ["$monthly_comments", 0]}},
                }
            },
        ]
        for doc in coll_mongo.aggregate(pipeline):
            did = doc.get("_id", {})
            rows.append(_yku_base_row(
                str(did.get("video_id") or ""), str(did.get("month") or ""), did.get("geography") or "CN",
                doc.get("mongo_title"), doc.get("mongo_ip"), doc.get("mongo_series"),
                doc.get("revenue"), doc.get("revenue_cny"), doc.get("revenue_avod"), doc.get("revenue_svod"),
                doc.get("views"), doc.get("watch_time"), doc.get("likes"), doc.get("comments"),
            ))

    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    df_yku = pd.DataFrame(rows)
    allowed_subs = []
    if allow_open:
        allowed_subs.append("Open Platform")
    if allow_dayu:
        allowed_subs.append("DaYu Platform")
    df_yku = df_yku[df_yku["subplatform"].isin(allowed_subs)]

    if global_ips:
        df_yku = df_yku[df_yku["ip_name"].isin(global_ips)]
    if global_series:
        df_yku = df_yku[df_yku["series_name"].isin(global_series)]
    if df_yku.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_yku["producer"] = df_yku.apply(
        lambda r: resolve_producer(r.get("video_title"), r.get("series_name"), r.get("ip_name"), platform="youku"),
        axis=1,
    ).fillna("Amuse Animation")
    if global_producers:
        df_yku = df_yku[df_yku["producer"].isin(global_producers)]
    if df_yku.empty:
        return pd.DataFrame(), pd.DataFrame()

    yku_group_cols = [
        "month", "producer", "ip_name", "series_name", "season", "episode_number",
        "episode_name", "geography", "video_id", "channel_id", "platform",
        "language_code", "video_title", "video_duration", "subplatform", "monetization_model",
    ]
    report_fin_yku = (
        df_yku.groupby(yku_group_cols, dropna=False)[["revenue", "revenue_cny", "revenue_avod", "revenue_svod"]]
        .sum()
        .reset_index()
        .sort_values(by=["month", "ip_name", "series_name"])
    )
    report_op_yku = (
        df_yku.groupby(yku_group_cols, dropna=False)[["views", "watch_time", "likes", "comments"]]
        .sum()
        .reset_index()
        .sort_values(by=["month", "ip_name"])
    )
    return report_fin_yku, report_op_yku


def fetch_iqiyi_reports(
    db_mongo,
    temp_mode: str,
    fecha_inicio,
    fecha_fin,
    global_ips: list,
    global_series: list,
    global_channels: list,
    global_producers: list,
    selected_geo_codes: list,
    selected_lang_codes: list,
    global_seasons: list = None,
    global_episodes: list = None,
):
    """Consulta en MongoDB los datos históricos de iQIYI (Amuse CC, Amuse LTV/France, Amuse Shanghai) y aplica los filtros globales."""
    if not _passes_china_common_filters(global_seasons, global_episodes, selected_geo_codes, selected_lang_codes):
        return pd.DataFrame(), pd.DataFrame()

    allowed_subs = {
        "Amuse CC (2463347304)",
        "Amuse LTV / France (2484062153)",
        "Amuse Shanghai (4318775981759616)",
    }
    if global_channels:
        has_all = "iQIYI" in global_channels
        has_cc = "iQIYI (Amuse CC)" in global_channels
        has_ltv = "iQIYI (Amuse LTV / France)" in global_channels
        has_sh = "iQIYI (Amuse Shanghai)" in global_channels
        if not (has_all or has_cc or has_ltv or has_sh):
            return pd.DataFrame(), pd.DataFrame()
        if not has_all:
            allowed_subs = set()
            if has_cc:
                allowed_subs.add("Amuse CC (2463347304)")
            if has_ltv:
                allowed_subs.add("Amuse LTV / France (2484062153)")
            if has_sh:
                allowed_subs.add("Amuse Shanghai (4318775981759616)")

    def _iqy_base_row(
        video_id: str,
        period_str: str,
        geo: str,
        mongo_title,
        mongo_ip,
        mongo_series,
        rev,
        rev_cny,
        rev_avod,
        rev_svod,
        views,
        watch_mins,
        comments,
    ):
        meta = get_iqiyi_series_metadata(video_id)
        ip_name = mongo_ip or meta["ip_name"]
        series_name = mongo_series or meta["series_name"]
        title = mongo_title or meta["title"]
        subplat = meta.get("channel_name", "Amuse CC (2463347304)")
        if "SHANGHAI" in video_id:
            ch_id = "IQIYI_4318775981759616"
        elif "2484062153" in subplat:
            ch_id = "IQIYI_2484062153"
        else:
            ch_id = "IQIYI_2463347304"

        rev_a = float(rev_avod or 0.0)
        rev_s = float(rev_svod or 0.0)
        rev_val = float(rev or 0.0)
        rev_cny_val = float(rev_cny or 0.0)
        wt_hrs = float(watch_mins or 0.0) / 60.0
        if rev_a > 0 and rev_s > 0:
            model = "MIXED"
        elif rev_s > 0 or wt_hrs > 0 or "_SVOD_" in series_name or video_id == "IQIYI_LTV_CHANNEL":
            model = "SVOD"
        else:
            model = "AVOD"

        # Respetar prioritariamente el revenue en USD ya consolidado en MongoDB (Fix BUG-03)
        if (rev_a + rev_s) <= 0.0:
            cny_rate = get_cny_rate(period_str)
            if rev_cny_val > 0 and cny_rate > 0:
                rev_val = rev_cny_val / cny_rate
                if model == "SVOD":
                    rev_s = rev_val
                elif model == "AVOD":
                    rev_a = rev_val

        return {
            "month": period_str,
            "ip_name": ip_name,
            "series_name": series_name,
            "season": 0,
            "episode_number": 0,
            "episode_name": title,
            "geography": geo or "CN",
            "video_id": video_id,
            "channel_id": ch_id,
            "platform": "iqiyi",
            "language_code": "zh",
            "video_title": title,
            "video_duration": 0,
            "subplatform": subplat,
            "monetization_model": model,
            "revenue": rev_val,
            "revenue_cny": rev_cny_val,
            "revenue_avod": rev_a,
            "revenue_svod": rev_s,
            "views": int(views or 0),
            "watch_time": wt_hrs,
            "comments": int(comments or 0),
        }

    if temp_mode == "yearly":
        coll_name = "yearly_performance_summaries"
        id_period_field = "$_id.year"
        match_period_field = "_id.year"
        start_val, end_val = fecha_inicio.strftime("%Y"), fecha_fin.strftime("%Y")
        prefix = "yearly_"
    elif temp_mode == "daily":
        coll_name = os.getenv("MONGODB_ANALYTICS_COLLECTION", "video_performance_events")
        match_period_field = "payload.date"
        start_val, end_val = fecha_inicio.strftime("%Y-%m-%d"), fecha_fin.strftime("%Y-%m-%d")
        prefix = None
    else:
        coll_name = "monthly_performance_summaries"
        id_period_field = "$_id.month"
        match_period_field = "_id.month"
        start_val, end_val = fecha_inicio.strftime("%Y-%m"), fecha_fin.strftime("%Y-%m")
        prefix = "monthly_"

    coll_mongo = db_mongo[coll_name]
    if temp_mode == "daily":
        pipeline = [
            {
                "$match": {
                    "metadata.event_type": "iqiyi.video.performance_recorded",
                    match_period_field: {"$gte": start_val, "$lte": end_val},
                }
            },
            {
                "$group": {
                    "_id": {
                        "video_id": "$payload.video_id",
                        "month": "$payload.date",
                        "platform": "$payload.platform",
                        "geography": {"$ifNull": ["$payload.geography", "CN"]},
                    },
                    "mongo_title": {"$first": "$payload.title"},
                    "mongo_ip": {"$first": "$payload.ip_name"},
                    "mongo_series": {"$first": "$payload.series_name"},
                    "revenue": {"$sum": {"$ifNull": ["$payload.estimated_revenue", 0]}},
                    "revenue_cny": {"$sum": {"$ifNull": ["$payload.extra_metrics.revenue_cny", 0]}},
                    "revenue_avod": {"$sum": {"$ifNull": ["$payload.extra_metrics.revenue_avod", 0]}},
                    "revenue_svod": {"$sum": {"$ifNull": ["$payload.extra_metrics.revenue_svod", 0]}},
                    "views": {"$sum": {"$ifNull": ["$payload.extra_metrics.views", 0]}},
                    "watch_time": {"$sum": {"$ifNull": ["$payload.extra_metrics.estimated_minutes_watched", 0]}},
                    "comments": {"$sum": {"$ifNull": ["$payload.extra_metrics.comments", 0]}},
                }
            },
        ]
    else:
        pipeline = [
            {
                "$match": {
                    "_id.platform": "iqiyi",
                    "_id.event_type": "iqiyi.video.performance_recorded",
                    match_period_field: {"$gte": start_val, "$lte": end_val},
                }
            },
            {
                "$group": {
                    "_id": {
                        "video_id": "$_id.video_id",
                        "month": id_period_field,
                        "platform": "$_id.platform",
                        "geography": "$_id.geography",
                    },
                    "mongo_title": {"$first": "$title"},
                    "mongo_ip": {"$first": "$ip_name"},
                    "mongo_series": {"$first": "$series_name"},
                    "revenue": {"$sum": f"${prefix}revenue"},
                    "revenue_cny": {"$sum": {"$ifNull": [f"${prefix}revenue_cny", 0]}},
                    "revenue_avod": {"$sum": {"$ifNull": [f"${prefix}revenue_avod", 0]}},
                    "revenue_svod": {"$sum": {"$ifNull": [f"${prefix}revenue_svod", 0]}},
                    "views": {"$sum": f"${prefix}views"},
                    "watch_time": {"$sum": {"$ifNull": [f"${prefix}watch_time", 0]}},
                    "comments": {"$sum": {"$ifNull": [f"${prefix}comments", 0]}},
                }
            },
        ]

    rows = []
    for doc in coll_mongo.aggregate(pipeline):
        did = doc.get("_id", {})
        rows.append(
            _iqy_base_row(
                str(did.get("video_id") or ""),
                str(did.get("month") or ""),
                did.get("geography") or "CN",
                doc.get("mongo_title"),
                doc.get("mongo_ip"),
                doc.get("mongo_series"),
                doc.get("revenue"),
                doc.get("revenue_cny"),
                doc.get("revenue_avod"),
                doc.get("revenue_svod"),
                doc.get("views"),
                doc.get("watch_time"),
                doc.get("comments"),
            )
        )

    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    df_iqy = pd.DataFrame(rows)
    df_iqy = df_iqy[df_iqy["subplatform"].isin(allowed_subs)]
    if df_iqy.empty:
        return pd.DataFrame(), pd.DataFrame()
    if global_ips:
        df_iqy = df_iqy[df_iqy["ip_name"].isin(global_ips)]
    if global_series:
        df_iqy = df_iqy[df_iqy["series_name"].isin(global_series)]
    if df_iqy.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_iqy["producer"] = df_iqy.apply(
        lambda r: resolve_producer(r.get("video_title"), r.get("series_name"), r.get("ip_name"), platform="iqiyi"),
        axis=1,
    )
    if global_producers:
        df_iqy = df_iqy[df_iqy["producer"].isin(global_producers)]
    if df_iqy.empty:
        return pd.DataFrame(), pd.DataFrame()

    iqy_group_cols = [
        "month", "producer", "ip_name", "series_name", "season", "episode_number",
        "episode_name", "geography", "video_id", "channel_id", "platform",
        "language_code", "video_title", "video_duration", "subplatform", "monetization_model",
    ]
    report_fin_iqy = (
        df_iqy.groupby(iqy_group_cols, dropna=False)[["revenue", "revenue_cny", "revenue_avod", "revenue_svod"]]
        .sum()
        .reset_index()
    )
    report_op_iqy = (
        df_iqy.groupby(iqy_group_cols, dropna=False)[["views", "watch_time", "comments"]]
        .sum()
        .reset_index()
    )
    return report_fin_iqy, report_op_iqy


def consolidate_multiplatform_reports(
    report_fin: pd.DataFrame,
    report_op: pd.DataFrame,
    agg_level: str,
    use_youtube: bool = True,
    use_amazon: bool = True,
    use_tencent: bool = False,
    use_youku: bool = False,
    use_iqiyi: bool = False,
    consolidar_periodo: bool = False,
    periodo_label: str = "",
    display_currency: str = "USD",
) -> dict:
    # Combinar para métricas específicas
    merge_cols = ['month', 'ip_name', 'series_name', 'season', 'episode_number', 'episode_name', 'geography', 'video_id', 'channel_id', 'platform', 'language_code', 'video_title', 'video_duration']
    if 'producer' in report_fin.columns and 'producer' in report_op.columns:
        merge_cols.insert(1, 'producer')
    for opt_col in ['amazon_title', 'match_title', 'match_score', 'monetization_model', 'subplatform']:
        if opt_col in report_fin.columns and opt_col in report_op.columns:
            merge_cols.append(opt_col)
    report_combined = pd.merge(report_fin, report_op, on=merge_cols, how='outer')

    platform_flags = {
        'youtube': bool(use_youtube),
        'amazon': bool(use_amazon),
        'tencent': bool(use_tencent),
        'youku': bool(use_youku),
        'iqiyi': bool(use_iqiyi),
    }
    active_platforms = [p for p in ['youtube', 'amazon', 'tencent', 'youku', 'iqiyi'] if platform_flags[p]]
    is_ip_mode = (agg_level == "Por Propiedad Intelectual (IP)")
    is_series_mode = (agg_level in ["Por Serie", "Por Serie / IP (Comparativa Multiplataforma)"])
    is_series_ip_mode = is_ip_mode or is_series_mode
    active_piv_platforms = active_platforms if is_series_ip_mode else [p for p in ['youtube', 'amazon'] if platform_flags[p]]

    if report_combined.empty:
        report_combined['raw_period'] = pd.Series(dtype=object)
        report_combined['subtotal_period'] = pd.Series(dtype=object)
        unique_subtotals = []
    else:
        report_combined['raw_period'] = report_combined['month'].astype(str)
        raw_periods = [p for p in report_combined['raw_period'].dropna().unique() if str(p).strip() not in ['', 'nan', 'None']]
        raw_periods_sorted = sorted(raw_periods)

        is_daily = any(len(str(p)) == 10 and str(p).count('-') == 2 for p in raw_periods_sorted)
        is_monthly = any(len(str(p)) == 7 and str(p).count('-') == 1 for p in raw_periods_sorted)

        if is_daily:
            # En vista diaria, agrupar subtotales por Mes (YYYY-MM) para evitar decenas de filas diarias
            report_combined['subtotal_period'] = report_combined['raw_period'].apply(lambda x: str(x)[:7] if len(str(x)) >= 7 else str(x))
        elif is_monthly:
            # En vista mensual, desglosar siempre mes a mes sin límite
            report_combined['subtotal_period'] = report_combined['raw_period']
        else:
            # En vista anual u otros, desglosar año a año
            report_combined['subtotal_period'] = report_combined['raw_period']

        unique_subtotals = sorted([p for p in report_combined['subtotal_period'].dropna().unique() if str(p).strip() not in ['', 'nan', 'None']])

        num_cols_to_fill = ['revenue', 'revenue_svod', 'revenue_tvod', 'revenue_avod', 'revenue_cny', 'views', 'watch_time', 'likes', 'comments', 'ad_impressions', 'ad_revenue']
        for nc in num_cols_to_fill:
            if nc in report_combined.columns:
                report_combined[nc] = report_combined[nc].fillna(0)

        # Conversión de divisa a EUR si el usuario seleccionó EUR (€)
        if display_currency.upper() == "EUR" and not report_combined.empty:
            unique_raw = report_combined['raw_period'].dropna().unique()
            period_to_rate = {p: get_eur_rate(p) for p in unique_raw}
            eur_rates = report_combined['raw_period'].map(period_to_rate).fillna(get_eur_rate(None))
            for mon_col in ['revenue', 'revenue_svod', 'revenue_tvod', 'revenue_avod', 'ad_revenue']:
                if mon_col in report_combined.columns:
                    report_combined[mon_col] = (report_combined[mon_col] * eur_rates).round(6)

    if not periodo_label:
        all_months = report_combined['raw_period'].dropna().astype(str).unique() if not report_combined.empty else []
        if len(all_months) > 1:
            periodo_label = f"{min(all_months)} - {max(all_months)}"
        elif len(all_months) == 1:
            periodo_label = str(all_months[0])
        else:
            periodo_label = "Periodo Consolidado"

    if consolidar_periodo:
        report_combined['month'] = periodo_label
    
    # Prevenir que Excel interprete títulos como fórmulas (#VALUE!)
    report_combined['episode_name'] = report_combined['episode_name'].apply(lambda x: f"'{x}" if str(x).strip().startswith(('=', '+', '-', '@')) else x)
    if 'amazon_title' in report_combined.columns:
        report_combined['amazon_title'] = report_combined['amazon_title'].apply(lambda x: f"'{x}" if str(x).strip().startswith(('=', '+', '-', '@')) else x)
    if 'match_title' in report_combined.columns:
        report_combined['match_title'] = report_combined['match_title'].apply(lambda x: f"'{x}" if str(x).strip().startswith(('=', '+', '-', '@')) else x)
    
    # Separar los vídeos UNMATCHED para que no se agrupen en una sola fila
    mask_unmatched = (
        (report_combined['ip_name'] == 'UNMATCHED') | 
        (report_combined['series_name'] == 'Historical & Unassigned') | 
        (report_combined['episode_number'].isin([9999, '9999']))
    )
    report_combined['episode_number'] = report_combined['episode_number'].astype(object)
    report_combined.loc[mask_unmatched, 'episode_number'] = report_combined.loc[mask_unmatched, 'video_id']
    
    for col in ['season', 'episode_number']:
        if col in report_combined.columns:
            # Solo convertir si es realmente numérico (ignorar video_ids de UNMATCHED)
            report_combined[col] = report_combined[col].apply(lambda x: str(int(float(x))) if str(x).replace('.','',1).isdigit() else str(x))

    # 1. Identificar Shorts (estándar estricto YouTube: duración <= 60s o tag #shorts)
    dur = report_combined['video_duration'].fillna(0)
    title_str = report_combined['video_title'].astype(str).str.lower()
    is_short = (report_combined['platform'] == 'youtube') & (
        ((dur > 0) & (dur <= 60)) |
        title_str.str.contains(r'#shorts?\b|\bshorts?\b', regex=True, na=False)
    )
    report_combined['is_short'] = is_short

    # 2. Identificar compilaciones y clips
    comp_regex = r'compilat|recopila|marath|marat[oó]n|colecci[oó]n|collection|pack|temporada completa|full season|kompilation|sammlung|folgen'
    is_comp_title = title_str.str.contains(comp_regex, regex=True, na=False)
    
    if 'amazon_title' in report_combined.columns:
        s_amz_title = report_combined['amazon_title'].astype(str)
        is_comp_amz = s_amz_title.str.lower().str.contains(comp_regex, regex=True, na=False) | s_amz_title.str.contains(r' / ', regex=False, na=False) | (s_amz_title.str.count('/') >= 2)
        is_comp_title = is_comp_title | is_comp_amz
        
    # Duración base del episodio estándar (mínima duración no-clip >= 90s para el episodio)
    ep_keys = ['ip_name', 'series_name', 'season', 'episode_number']
    mask_std_cand = (~is_short) & (dur >= 90)
    df_std_cand = report_combined[mask_std_cand]
    if not df_std_cand.empty:
        base_dur_map = df_std_cand.groupby(ep_keys)['video_duration'].min().rename('_base_dur')
        report_combined = report_combined.merge(base_dur_map, on=ep_keys, how='left')
    else:
        report_combined['_base_dur'] = np.nan

    # Un vídeo es compilación si:
    # a) Título explícito de recopilación / maratón
    # b) Dura más de 30 minutos (1800s) -> ninguna animación unitaria en Amuse supera los 25 minutos
    # c) O dura al menos 10 minutos (600s) más que el episodio base del mismo episodio
    is_comp_dur = (dur > 1800) | (
        report_combined['_base_dur'].notna() & 
        (dur >= report_combined['_base_dur'] + 600) & 
        (dur > 900)
    )
    report_combined['is_compilation'] = (is_comp_title | is_comp_dur) & (~is_short)
    report_combined.drop(columns=['_base_dur'], errors='ignore', inplace=True)
    report_combined['is_standard'] = (~report_combined['is_short']) & (~report_combined['is_compilation'])
    
    has_producer = 'producer' in report_combined.columns
    producer_key = ['producer'] if has_producer else []
    df_ep_src = report_combined[report_combined['platform'].isin(['youtube', 'amazon'])].copy() if not report_combined.empty else report_combined.copy()

    if is_ip_mode:
        idx_comp = ['month'] + producer_key + ['ip_name']
        cols_base = ['month'] + producer_key + ['ip_name']
        ep_name_map = pd.DataFrame(columns=idx_comp)

    elif is_series_mode:
        idx_comp = ['month'] + producer_key + ['ip_name', 'series_name']
        cols_base = ['month'] + producer_key + ['ip_name', 'series_name']
        ep_name_map = pd.DataFrame(columns=idx_comp)

    elif agg_level == "Episodio Canónico (Todas las versiones)":
        idx_comp = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number']
        cols_base = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'episode_name', 'num_versiones_totales', 'num_versiones', 'num_publicaciones']
        
        if df_ep_src.empty:
            ep_name_map = pd.DataFrame(columns=idx_comp + ['episode_name'])
        else:
            df_ep_src = assign_name_score(df_ep_src, 'episode_name')
            ep_name_map = df_ep_src.sort_values(by=['name_score', 'episode_name'], ascending=[True, True]).groupby(idx_comp)['episode_name'].first().reset_index()

    elif agg_level == "Por Idioma (Separar traducciones)":
        idx_comp = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'language_code']
        cols_base = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'language_code', 'episode_name', 'num_versiones_totales', 'num_publicaciones']
        
        if df_ep_src.empty:
            ep_name_map = pd.DataFrame(columns=idx_comp + ['episode_name'])
        else:
            df_ep_src = assign_name_score(df_ep_src, 'video_title')
            ep_name_map = df_ep_src.sort_values(by=['name_score', 'video_title'], ascending=[True, True]).groupby(idx_comp)['video_title'].first().reset_index()
            ep_name_map.rename(columns={'video_title': 'episode_name'}, inplace=True)

    elif agg_level == "Por Territorio / País":
        idx_comp = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'geography']
        cols_base = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'geography', 'episode_name', 'num_versiones_totales', 'num_versiones', 'num_publicaciones']
        
        if df_ep_src.empty:
            ep_name_map = pd.DataFrame(columns=idx_comp + ['episode_name'])
        else:
            df_ep_src = assign_name_score(df_ep_src, 'episode_name')
            ep_name_map = df_ep_src.sort_values(by=['name_score', 'episode_name'], ascending=[True, True]).groupby(idx_comp)['episode_name'].first().reset_index()

    else: # "Por Vídeo/Versión (Mostrar resubidas)"
        idx_comp = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'language_code', 'video_id']
        cols_base = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'language_code', 'video_id', 'episode_name', 'is_compilation', 'is_short']
        
        if df_ep_src.empty:
            ep_name_map = pd.DataFrame(columns=idx_comp + ['episode_name'])
        else:
            s_title_ver = np.where(df_ep_src['platform'] == 'amazon', df_ep_src['episode_name'], df_ep_src['video_title'])
            df_ep_src['_ver_title'] = s_title_ver
            ep_name_map = df_ep_src.groupby(idx_comp)['_ver_title'].first().reset_index()
            ep_name_map.rename(columns={'_ver_title': 'episode_name'}, inplace=True)
            df_ep_src = df_ep_src.drop(columns=['_ver_title'], errors='ignore')
        
    # Desglose de versiones: Total, Idiomas distintos y Republicaciones (resubidas + recopilaciones + shorts)
    def _compute_versions_breakdown(df_sub, id_col, idx_keys):
        if df_sub.empty or is_series_ip_mode:
            base_vc_cols = [c for c in ['num_versiones_totales', 'num_versiones', 'num_publicaciones'] if c in cols_base]
            return pd.DataFrame(columns=idx_keys + base_vc_cols)
        
        df_uniq = df_sub.drop_duplicates(subset=idx_keys + [id_col])
        g_tot = df_uniq.groupby(idx_keys)[id_col].count().rename('num_versiones_totales')
        g_shorts = df_uniq[df_uniq['is_short']].groupby(idx_keys)[id_col].count().rename('num_shorts')
        g_comps = df_uniq[df_uniq['is_compilation']].groupby(idx_keys)[id_col].count().rename('num_comps')
        
        df_std = df_uniq[df_uniq['is_standard']]
        g_std_vids = df_std.groupby(idx_keys)[id_col].count().rename('num_std_vids')
        g_std_langs = df_std.groupby(idx_keys)['language_code'].nunique().rename('num_versiones')
        
        vc = pd.concat([g_tot, g_shorts, g_comps, g_std_vids, g_std_langs], axis=1).fillna(0).reset_index()
        for col in ['num_versiones_totales', 'num_shorts', 'num_comps', 'num_std_vids', 'num_versiones']:
            vc[col] = vc[col].astype(int)
            
        vc['num_publicaciones'] = (
            np.maximum(0, vc['num_std_vids'] - vc['num_versiones']) 
            + vc['num_comps'] 
            + vc['num_shorts']
        ).astype(int)
        vc.drop(columns=['num_comps', 'num_std_vids', 'num_shorts'], errors='ignore', inplace=True)
        if 'num_versiones' not in cols_base:
            vc.drop(columns=['num_versiones'], errors='ignore', inplace=True)
        return vc

    ep_group_keys = [c for c in idx_comp if c != 'month']

    if is_series_ip_mode:
        versions_count_yt = pd.DataFrame(columns=idx_comp)
        versions_count_amz = pd.DataFrame(columns=idx_comp)
        versions_count_comb = pd.DataFrame(columns=idx_comp)
        ep_video_map = pd.DataFrame(columns=ep_group_keys + ['parent_video_id'])
    else:
        # Desglose de versiones específico por plataforma:
        # 1. YouTube: basado en los identificadores de vídeo únicos (video_id)
        df_yt_sub = df_ep_src[df_ep_src['platform'] == 'youtube'].copy()
        versions_count_yt = _compute_versions_breakdown(df_yt_sub, 'video_id', idx_comp)

        # 2. Amazon: basado en las entregas/publicaciones únicas (amazon_title + language_code)
        df_amz_sub = df_ep_src[df_ep_src['platform'] == 'amazon'].copy()
        if not df_amz_sub.empty:
            title_col = 'amazon_title' if 'amazon_title' in df_amz_sub.columns else ('video_title' if 'video_title' in df_amz_sub.columns else 'episode_name')
            s_title = df_amz_sub[title_col].fillna('').astype(str).str.strip()
            s_vid = df_amz_sub['video_id'].fillna('').astype(str).str.strip()
            s_title = np.where(s_title != '', s_title, s_vid)
            s_lang = df_amz_sub['language_code'].fillna('multi').astype(str).str.strip()
            df_amz_sub['_amz_pub_id'] = s_title + '_' + s_lang
        versions_count_amz = _compute_versions_breakdown(df_amz_sub, '_amz_pub_id', idx_comp)

        # 3. Consolidado para la tabla comparativa
        if not versions_count_yt.empty and not versions_count_amz.empty:
            vc_comb = pd.merge(
                versions_count_yt, 
                versions_count_amz, 
                on=idx_comp, 
                how='outer', 
                suffixes=('_yt', '_amz')
            ).fillna(0)
            vc_comb['num_versiones_totales'] = (vc_comb['num_versiones_totales_yt'] + vc_comb['num_versiones_totales_amz']).astype(int)
            
            if 'num_versiones' in cols_base:
                # Extraer los idiomas estándar reales disponibles en cada plataforma para hacer la unión exacta
                std_langs_yt = df_yt_sub[df_yt_sub['is_standard']].groupby(idx_comp)['language_code'].apply(lambda s: set(s.dropna())).rename('_std_langs_yt')
                std_langs_amz = df_amz_sub[df_amz_sub['is_standard']].groupby(idx_comp)['language_code'].apply(lambda s: set(s.dropna())).rename('_std_langs_amz')
                vc_comb = vc_comb.merge(std_langs_yt, on=idx_comp, how='left')
                vc_comb = vc_comb.merge(std_langs_amz, on=idx_comp, how='left')
                
                def _get_union_lang_count(row):
                    s1 = row['_std_langs_yt'] if isinstance(row['_std_langs_yt'], set) else set()
                    s2 = row['_std_langs_amz'] if isinstance(row['_std_langs_amz'], set) else set()
                    return len(s1.union(s2))
                    
                vc_comb['num_versiones'] = vc_comb.apply(_get_union_lang_count, axis=1).astype(int)
                vc_comb['num_publicaciones'] = (vc_comb['num_versiones_totales'] - vc_comb['num_versiones']).astype(int)
                final_vc_cols = idx_comp + ['num_versiones_totales', 'num_versiones', 'num_publicaciones']
            else:
                vc_comb['num_publicaciones'] = (vc_comb['num_publicaciones_yt'] + vc_comb['num_publicaciones_amz']).astype(int)
                final_vc_cols = idx_comp + ['num_versiones_totales', 'num_publicaciones']
                
            versions_count_comb = vc_comb[final_vc_cols]
        elif not versions_count_yt.empty:
            versions_count_comb = versions_count_yt.copy()
        else:
            versions_count_comb = versions_count_amz.copy()

        # Seleccionar el vídeo padre/representativo para cada grupo
        df_yt_rep = df_ep_src[df_ep_src['platform'] == 'youtube'].copy()
        if not df_yt_rep.empty:
            yt_dur = df_yt_rep['video_duration'].fillna(0)
            yt_comp = df_yt_rep['is_compilation'].fillna(False)
            yt_clip = df_yt_rep['is_short'].fillna(False) | ((yt_dur > 0) & (yt_dur < 90))
            
            # Prioridad de formato: 0 = Episodio estándar (90s - 900s), 1 = Duración desconocida, 2 = Clip/Teaser (<90s), 3 = Compilación (>900s)
            df_yt_rep['format_prio'] = np.where(yt_comp, 3, np.where(yt_clip, 2, np.where(yt_dur == 0, 1, 0)))
            
            # Prioridad de idioma: inglés original primero (prefijo 'en'), luego español ('es'), luego el resto
            lang_str = df_yt_rep['language_code'].astype(str).str.lower()
            is_en = lang_str.str.startswith('en')
            is_es = lang_str.str.startswith('es')
            df_yt_rep['lang_prio'] = np.where(is_en, 1, np.where(is_es, 2, 3))
            
            # Calidad del título para desempatar títulos genéricos ("Unknown Video")
            df_yt_rep = assign_name_score(df_yt_rep, 'video_title')
            
            # Tráfico acumulado del vídeo en el periodo
            df_yt_rep['total_video_views'] = df_yt_rep.groupby('video_id')['views'].transform('sum')
            
            if agg_level == "Episodio Canónico (Todas las versiones)":
                sort_cols = ['format_prio', 'lang_prio', 'name_score', 'total_video_views']
                asc_order = [True, True, True, False]
            else:
                sort_cols = ['format_prio', 'name_score', 'total_video_views']
                asc_order = [True, True, False]
                
            ep_video_map = df_yt_rep.sort_values(by=sort_cols, ascending=asc_order).groupby(ep_group_keys)['video_id'].first().reset_index(name='parent_video_id')
        else:
            ep_video_map = pd.DataFrame(columns=ep_group_keys + ['parent_video_id'])

    # Generación concurrente y paralela de las tablas analíticas
    def _build_consolidated():
        if agg_level == "Por Vídeo/Versión (Mostrar resubidas)":
            target_order = (
                ['month'] + producer_key + [
                    'ip_name', 'series_name', 'season', 'episode_number', 
                    'language_code', 'video_id', 'episode_name', 'platform_title', 
                    'platform', 'is_short', 'total_revenue', 'total_views', 
                    'total_watch_time', 'youtube_url'
                ]
            )
            df_ep_comb = df_ep_src
            if df_ep_comb.empty:
                report_piv = pd.DataFrame(columns=target_order)
            else:
                idx_ver = ['month'] + producer_key + ['ip_name', 'series_name', 'season', 'episode_number', 'language_code', 'video_id', 'platform']
                
                # 1. Métricas sumadas por vídeo individual y plataforma
                metrics = [m for m in ['revenue', 'views', 'watch_time'] if m in df_ep_comb.columns]
                df_ver = df_ep_comb.groupby(idx_ver, as_index=False)[metrics].sum()
                
                for m in ['revenue', 'views', 'watch_time']:
                    if m not in df_ver.columns:
                        df_ver[m] = 0.0
                        
                df_ver['total_revenue'] = df_ver['revenue'].fillna(0).round(2)
                df_ver['total_views'] = df_ver['views'].fillna(0).round().astype(int)
                df_ver['total_watch_time'] = df_ver['watch_time'].fillna(0).round(2)
                df_ver.drop(columns=['revenue', 'views', 'watch_time'], errors='ignore', inplace=True)
                
                # 2. Nombre Canónico del Episodio (Broadkast)
                df_rep_sorted = assign_name_score(df_ep_comb.copy(), 'episode_name').sort_values(
                    by=['name_score', 'episode_name'], ascending=[True, True]
                )
                ep_canon_map = df_rep_sorted.groupby(idx_ver)['episode_name'].first().reset_index()
                df_ver = df_ver.merge(ep_canon_map, on=idx_ver, how='left')
                
                # Mejorar nombres genéricos si existe nombre canónico no-genérico para el episodio
                mask_gen = df_ver['episode_name'].fillna('').str.contains(r' - Ep \d+$', regex=True) | df_ver['episode_name'].isin(['Unknown Episode', 'Unknown Video', 'Legacy Compilation', ''])
                if mask_gen.any():
                    ep_keys_loc = ['ip_name', 'series_name', 'season', 'episode_number']
                    non_gen = df_ep_comb[
                        ~df_ep_comb['episode_name'].fillna('').str.contains(r' - Ep \d+$', regex=True) & 
                        ~df_ep_comb['episode_name'].isin(['Unknown Episode', 'Unknown Video', 'Legacy Compilation', ''])
                    ]
                    if not non_gen.empty:
                        canon_fallback = non_gen.groupby(ep_keys_loc)['episode_name'].first().reset_index().rename(columns={'episode_name': '_canon_name'})
                        df_ver = df_ver.merge(canon_fallback, on=ep_keys_loc, how='left')
                        df_ver['episode_name'] = np.where(mask_gen & df_ver['_canon_name'].notna(), df_ver['_canon_name'], df_ver['episode_name'])
                        df_ver.drop(columns=['_canon_name'], errors='ignore', inplace=True)
                df_ver['episode_name'] = df_ver['episode_name'].fillna('Unknown Episode')
                
                # 3. Nombre del Episodio en la Plataforma
                df_comb = df_ep_comb.copy()
                if 'amazon_title' in df_comb.columns:
                    amz_t = df_comb['amazon_title'].replace('', np.nan).combine_first(df_comb['episode_name'])
                else:
                    amz_t = df_comb.get('video_title', pd.Series(np.nan, index=df_comb.index)).replace('', np.nan).combine_first(df_comb['episode_name'])
                yt_t = df_comb.get('video_title', pd.Series(np.nan, index=df_comb.index)).replace('', np.nan).combine_first(df_comb['episode_name'])
                
                df_comb['_plat_title'] = np.where(df_comb['platform'] == 'amazon', amz_t, yt_t)
                df_comb['_plat_title'] = df_comb['_plat_title'].fillna('Unknown Title')
                plat_title_map = df_comb.groupby(idx_ver)['_plat_title'].first().reset_index().rename(columns={'_plat_title': 'platform_title'})
                df_ver = df_ver.merge(plat_title_map, on=idx_ver, how='left')
                df_ver['platform_title'] = df_ver['platform_title'].fillna('Unknown Title')
                
                # 4. Short (en Amazon siempre False)
                short_map = df_ep_comb.groupby(idx_ver)['is_short'].any().reset_index()
                df_ver = df_ver.merge(short_map, on=idx_ver, how='left')
                df_ver['is_short'] = df_ver['is_short'].fillna(False).astype(bool)
                
                # 5. URL (en blanco para Amazon)
                df_ver['youtube_url'] = np.where(
                    df_ver['platform'] == 'youtube',
                    df_ver['video_id'].apply(format_youtube_url),
                    ""
                )
                
                # Orden exacto de columnas requerido por el usuario:
                report_piv = df_ver[[c for c in target_order if c in df_ver.columns]].copy()
            
            # Filas de totales desglosadas por plataforma (incluyendo Tencent si está activo)
            totals_rows = []
            if not report_combined.empty:
                present_plats = set(report_combined['platform'].dropna().unique())
                available_platforms = [p for p in active_platforms if p in present_plats]
                for p in report_piv['platform'].unique() if not report_piv.empty else []:
                    if p not in available_platforms:
                        available_platforms.append(p)

                tot_label = f"TOTAL ({periodo_label})" if (len(unique_subtotals) > 1 and periodo_label) else 'TOTAL'
                for plat in available_platforms:
                    df_raw_plat = report_combined[report_combined['platform'] == plat]
                    row_tot = {
                        'month': tot_label,
                        'platform': plat,
                        'total_revenue': round(float(df_raw_plat['revenue'].sum()), 2) if 'revenue' in df_raw_plat.columns else 0.0,
                        'total_views': int(df_raw_plat['views'].sum()) if 'views' in df_raw_plat.columns else 0,
                        'total_watch_time': round(float(df_raw_plat['watch_time'].sum()), 2) if 'watch_time' in df_raw_plat.columns else 0.0,
                    }
                    totals_rows.append(row_tot)

                    if len(unique_subtotals) > 1:
                        for sub_p in unique_subtotals:
                            df_sub_p = df_raw_plat[df_raw_plat['subtotal_period'] == sub_p]
                            row_sub = {
                                'month': str(sub_p),
                                'platform': plat,
                                'total_revenue': round(float(df_sub_p['revenue'].sum()), 2) if 'revenue' in df_sub_p.columns else 0.0,
                                'total_views': int(df_sub_p['views'].sum()) if 'views' in df_sub_p.columns else 0,
                                'total_watch_time': round(float(df_sub_p['watch_time'].sum()), 2) if 'watch_time' in df_sub_p.columns else 0.0,
                            }
                            totals_rows.append(row_sub)

            df_totals = pd.DataFrame(totals_rows) if totals_rows else pd.DataFrame()
            if not df_totals.empty:
                tot_cols_pv = ['month', 'platform', 'total_revenue', 'total_views', 'total_watch_time']
                df_totals = df_totals[[c for c in tot_cols_pv if c in df_totals.columns]]
            return report_piv, df_totals

        # Para "Por Serie / IP" u otros niveles de agregación: tabla pivotada consolidada
        piv_source = (
            report_combined[report_combined['platform'].isin(active_piv_platforms)].copy()
            if not report_combined.empty and active_piv_platforms
            else pd.DataFrame()
        )
        if piv_source.empty:
            report_piv = pd.DataFrame(columns=cols_base)
        else:
            report_piv = pd.pivot_table(
                piv_source,
                values=['revenue', 'views', 'watch_time'],
                index=idx_comp,
                columns=['platform'],
                aggfunc='sum',
            ).reset_index()
            new_cols = []
            for c in report_piv.columns:
                if isinstance(c, tuple):
                    new_cols.append(c[0] if c[1] == "" else f"{c[0]}_{c[1]}")
                else:
                    new_cols.append(c)
            report_piv.columns = new_cols
            report_piv.drop(columns=['watch_time_tencent'], errors='ignore', inplace=True)

            if not is_series_ip_mode:
                report_piv = pd.merge(report_piv, ep_name_map, on=idx_comp, how='left')
                report_piv = pd.merge(report_piv, versions_count_comb, on=idx_comp, how='left')
                if use_youtube and not ep_video_map.empty:
                    report_piv = pd.merge(report_piv, ep_video_map, on=ep_group_keys, how='left')
                    report_piv['youtube_url'] = report_piv['parent_video_id'].apply(format_youtube_url)
                    report_piv = report_piv.drop(columns=['parent_video_id'], errors='ignore')

            for p in active_piv_platforms:
                for m in ['revenue', 'views']:
                    col_pm = f"{m}_{p}"
                    if col_pm not in report_piv.columns:
                        report_piv[col_pm] = 0.0
                if p != 'tencent':
                    col_wt = f"watch_time_{p}"
                    if col_wt not in report_piv.columns:
                        report_piv[col_wt] = 0.0

            rev_sum = sum((report_piv[f"revenue_{p}"].fillna(0) for p in active_piv_platforms), pd.Series(0.0, index=report_piv.index))
            views_sum = sum((report_piv[f"views_{p}"].fillna(0) for p in active_piv_platforms), pd.Series(0.0, index=report_piv.index))
            wt_plats = [p for p in active_piv_platforms if p != 'tencent']
            wt_sum = sum((report_piv[f"watch_time_{p}"].fillna(0) for p in wt_plats), pd.Series(0.0, index=report_piv.index)) if wt_plats else pd.Series(0.0, index=report_piv.index)

            report_piv['total_revenue'] = rev_sum.round(2)
            report_piv['total_views'] = views_sum.round().astype(int)
            report_piv['total_watch_time'] = wt_sum.round(2)

            ordered_metrics = (
                ['total_revenue']
                + [f'revenue_{p}' for p in active_piv_platforms]
                + ['total_views']
                + [f'views_{p}' for p in active_piv_platforms]
                + ['total_watch_time']
                + [f'watch_time_{p}' for p in wt_plats]
            )
            cols_piv = [c for c in cols_base if c != 'youtube_url']
            for m in ordered_metrics:
                if m in report_piv.columns and m not in cols_piv:
                    cols_piv.append(m)
            cols_piv.extend([c for c in report_piv.columns if c not in cols_piv and c != 'youtube_url'])
            if 'youtube_url' in report_piv.columns:
                cols_piv.append('youtube_url')
            report_piv = report_piv[[c for c in cols_piv if c in report_piv.columns]].fillna(0)
            if 'youtube_url' in report_piv.columns:
                report_piv['youtube_url'] = report_piv['youtube_url'].replace(0, "").fillna("")

            for col in ['total_revenue', 'total_watch_time'] + [f'revenue_{p}' for p in active_piv_platforms] + [f'watch_time_{p}' for p in wt_plats]:
                if col in report_piv.columns:
                    report_piv[col] = report_piv[col].round(2)

            for col in ['total_views', 'num_versiones_totales', 'num_versiones', 'num_publicaciones'] + [f'views_{p}' for p in active_piv_platforms]:
                if col in report_piv.columns:
                    report_piv[col] = report_piv[col].round().astype(int)

            sort_cols_piv = [c for c in ['month', 'producer', 'ip_name', 'series_name'] if c in report_piv.columns]
            if sort_cols_piv:
                report_piv = report_piv.sort_values(by=sort_cols_piv).reset_index(drop=True)

        def _build_comp_totals_row(df_slice, month_str):
            row = {'month': month_str}
            tot_rev, tot_views, tot_wt = 0.0, 0, 0.0
            for p in active_platforms:
                df_p = df_slice[df_slice['platform'] == p] if not df_slice.empty else df_slice
                p_rev = round(float(df_p['revenue'].sum()), 2) if (not df_p.empty and 'revenue' in df_p.columns) else 0.0
                p_views = int(df_p['views'].sum()) if (not df_p.empty and 'views' in df_p.columns) else 0
                row[f'revenue_{p}'] = p_rev
                row[f'views_{p}'] = p_views
                tot_rev += p_rev
                tot_views += p_views
                if p != 'tencent':
                    p_wt = round(float(df_p['watch_time'].sum()), 2) if (not df_p.empty and 'watch_time' in df_p.columns) else 0.0
                    row[f'watch_time_{p}'] = p_wt
                    tot_wt += p_wt
            row['total_revenue'] = round(tot_rev, 2)
            row['total_views'] = int(tot_views)
            row['total_watch_time'] = round(tot_wt, 2)
            return row

        totals_rows = []
        if not report_combined.empty and (not report_piv.empty or use_tencent or use_youku or use_iqiyi):
            tot_label = f"TOTAL ({periodo_label})" if (len(unique_subtotals) > 1 and periodo_label) else 'TOTAL'
            totals_rows.append(_build_comp_totals_row(report_combined, tot_label))
            if len(unique_subtotals) > 1:
                for sub_p in unique_subtotals:
                    df_sub_p = report_combined[report_combined['subtotal_period'] == sub_p]
                    totals_rows.append(_build_comp_totals_row(df_sub_p, str(sub_p)))

        df_totals = pd.DataFrame(totals_rows) if totals_rows else pd.DataFrame()
        if not df_totals.empty:
            tot_wt_plats = [p for p in active_platforms if p != 'tencent']
            tot_cols = (
                ['month', 'total_revenue']
                + [f'revenue_{p}' for p in active_platforms]
                + ['total_views']
                + [f'views_{p}' for p in active_platforms]
                + ['total_watch_time']
                + [f'watch_time_{p}' for p in tot_wt_plats]
            )
            df_totals = df_totals[[c for c in tot_cols if c in df_totals.columns]]
        return report_piv, df_totals

    def _build_youtube():
        df_yt = report_combined[report_combined['platform'] == 'youtube'].copy()
        if not df_yt.empty:
            yt_metrics = ['revenue', 'views', 'watch_time', 'likes', 'comments', 'ad_impressions', 'ad_revenue']
            yt_metrics = [m for m in yt_metrics if m in df_yt.columns]
            df_yt = df_yt.groupby(idx_comp)[yt_metrics].sum().reset_index()

            if not is_series_ip_mode:
                df_yt = pd.merge(df_yt, ep_name_map, on=idx_comp, how='left')
                if agg_level != "Por Vídeo/Versión (Mostrar resubidas)":
                    df_yt = pd.merge(df_yt, versions_count_yt, on=idx_comp, how='left')
                    if not ep_video_map.empty:
                        df_yt = pd.merge(df_yt, ep_video_map, on=ep_group_keys, how='left')
                        df_yt['youtube_url'] = df_yt['parent_video_id'].apply(format_youtube_url)
                        df_yt = df_yt.drop(columns=['parent_video_id'], errors='ignore')
                    else:
                        df_yt['youtube_url'] = ""
                else:
                    comp_map = df_ep_src.groupby(idx_comp)['is_compilation'].first().reset_index()
                    df_yt = pd.merge(df_yt, comp_map, on=idx_comp, how='left')
                    short_map = df_ep_src.groupby(idx_comp)['is_short'].first().reset_index()
                    df_yt = pd.merge(df_yt, short_map, on=idx_comp, how='left')
                    if 'video_id' in df_yt.columns:
                        df_yt['youtube_url'] = df_yt['video_id'].apply(format_youtube_url)
                    else:
                        df_yt['youtube_url'] = ""
                
            df_yt['cpm'] = np.where(df_yt['ad_impressions'] > 0, (df_yt['ad_revenue'] / df_yt['ad_impressions'] * 1000), 0)
            df_yt['cpm'] = df_yt['cpm'].round(2)
            df_yt = df_yt.fillna(0)
            if 'youtube_url' in df_yt.columns:
                df_yt['youtube_url'] = df_yt['youtube_url'].replace(0, "").fillna("")
            
            if 'revenue' in df_yt.columns:
                df_yt['revenue'] = df_yt['revenue'].round(2)
            if 'ad_revenue' in df_yt.columns:
                df_yt['ad_revenue'] = df_yt['ad_revenue'].round(2)
            if 'watch_time' in df_yt.columns:
                df_yt['watch_time'] = df_yt['watch_time'].round(2)
            
            int_cols = ['views', 'likes', 'comments', 'ad_impressions', 'num_versiones_totales', 'num_versiones', 'num_publicaciones']
            for c in int_cols:
                if c in df_yt.columns:
                    df_yt[c] = df_yt[c].round().astype(int)
            
            base_cols_yt = [c for c in cols_base if c in df_yt.columns and c != 'youtube_url']
            metrics_yt = ['revenue', 'views', 'watch_time', 'cpm', 'likes', 'comments', 'ad_impressions', 'ad_revenue']
            metrics_yt = [c for c in metrics_yt if c in df_yt.columns]
            other_cols_yt = [c for c in df_yt.columns if c not in base_cols_yt and c not in metrics_yt and c != 'youtube_url']
            final_cols_yt = base_cols_yt + metrics_yt + other_cols_yt
            if 'youtube_url' in df_yt.columns:
                final_cols_yt.append('youtube_url')
            df_yt = df_yt[final_cols_yt]
            yt_sort_cols = [c for c in ['month', 'producer', 'ip_name', 'series_name'] if c in df_yt.columns]
            if yt_sort_cols:
                df_yt = df_yt.sort_values(by=yt_sort_cols).reset_index(drop=True)
            
            totals_yt_rows = []
            tot_label = f"TOTAL ({periodo_label})" if (len(unique_subtotals) > 1 and periodo_label) else 'TOTAL'
            totals_yt = {}
            for col in df_yt.columns:
                if col == 'month':
                    totals_yt[col] = tot_label
                elif col in ['revenue', 'ad_revenue', 'watch_time']:
                    totals_yt[col] = round(float(df_yt[col].sum()), 2)
                elif col in ['views', 'likes', 'comments', 'ad_impressions']:
                    totals_yt[col] = int(df_yt[col].sum())
                elif col == 'cpm':
                    tot_ad_rev = float(df_yt['ad_revenue'].sum()) if 'ad_revenue' in df_yt.columns else 0.0
                    tot_ad_imp = float(df_yt['ad_impressions'].sum()) if 'ad_impressions' in df_yt.columns else 0.0
                    totals_yt[col] = round((tot_ad_rev / tot_ad_imp * 1000), 2) if tot_ad_imp > 0 else 0.0
                else:
                    totals_yt[col] = '-'
            totals_yt_rows.append(totals_yt)

            if len(unique_subtotals) > 1:
                df_raw_yt = report_combined[report_combined['platform'] == 'youtube']
                for sub_p in unique_subtotals:
                    df_sub_p = df_raw_yt[df_raw_yt['subtotal_period'] == sub_p]
                    row_sub = {}
                    for col in df_yt.columns:
                        if col == 'month':
                            row_sub[col] = str(sub_p)
                        elif col in ['revenue', 'ad_revenue', 'watch_time']:
                            row_sub[col] = round(float(df_sub_p[col].sum()), 2) if col in df_sub_p.columns else 0.0
                        elif col in ['views', 'likes', 'comments', 'ad_impressions']:
                            row_sub[col] = int(df_sub_p[col].sum()) if col in df_sub_p.columns else 0
                        elif col == 'cpm':
                            sub_ad_rev = float(df_sub_p['ad_revenue'].sum()) if 'ad_revenue' in df_sub_p.columns else 0.0
                            sub_ad_imp = float(df_sub_p['ad_impressions'].sum()) if 'ad_impressions' in df_sub_p.columns else 0.0
                            row_sub[col] = round((sub_ad_rev / sub_ad_imp * 1000), 2) if sub_ad_imp > 0 else 0.0
                        else:
                            row_sub[col] = '-'
                    totals_yt_rows.append(row_sub)

            df_totals_yt = pd.DataFrame(totals_yt_rows)
            if not df_totals_yt.empty:
                tot_cols_yt = ['month', 'revenue', 'ad_revenue', 'views', 'watch_time', 'cpm', 'likes', 'comments', 'ad_impressions']
                df_totals_yt = df_totals_yt[[c for c in tot_cols_yt if c in df_totals_yt.columns]]
        else:
            df_yt = pd.DataFrame()
            df_totals_yt = pd.DataFrame()
        return df_yt, df_totals_yt

    def _build_amazon():
        df_amz = report_combined[report_combined['platform'] == 'amazon'].copy()
        if not df_amz.empty:
            amz_metrics = ['revenue', 'revenue_svod', 'revenue_tvod', 'views', 'watch_time']
            amz_metrics = [m for m in amz_metrics if m in df_amz.columns]
            df_amz_agg = df_amz.groupby(idx_comp)[amz_metrics].sum().reset_index()

            if not is_series_ip_mode:
                # Nombre de Broadkast asignado/matcheado
                if 'episode_name' in df_amz.columns:
                    df_amz_ep_sorted = assign_name_score(df_amz.copy(), 'episode_name').sort_values(by=['name_score', 'episode_name'], ascending=[True, True])
                    amz_ep_map = df_amz_ep_sorted.groupby(idx_comp)['episode_name'].first().reset_index()
                    df_amz_agg = pd.merge(df_amz_agg, amz_ep_map, on=idx_comp, how='left')
                    
                    # Si el nombre en df_amz es genérico pero ep_name_map tiene un nombre canónico de Broadkast/YouTube, mejorarlo
                    mask_generic = df_amz_agg['episode_name'].str.contains(r' - Ep \d+$', regex=True) | df_amz_agg['episode_name'].isin(['Unknown Episode', 'Unknown Video', 'Legacy Compilation'])
                    if mask_generic.any() and 'episode_name' in ep_name_map.columns:
                        df_amz_agg = pd.merge(df_amz_agg, ep_name_map.rename(columns={'episode_name': '_canon_ep_name'}), on=idx_comp, how='left')
                        canon_mask = df_amz_agg['_canon_ep_name'].notna() & ~df_amz_agg['_canon_ep_name'].str.contains(r' - Ep \d+$', regex=True)
                        df_amz_agg['episode_name'] = np.where(mask_generic & canon_mask, df_amz_agg['_canon_ep_name'], df_amz_agg['episode_name'])
                        df_amz_agg = df_amz_agg.drop(columns=['_canon_ep_name'], errors='ignore')
                else:
                    df_amz_agg = pd.merge(df_amz_agg, ep_name_map, on=idx_comp, how='left')
                    
                # Nombre original en Amazon
                if 'amazon_title' in df_amz.columns:
                    df_amz_sorted = df_amz.assign(
                        _has_title=df_amz['amazon_title'].astype(str).str.strip().ne('') & ~df_amz['amazon_title'].astype(str).isin(['Unknown Title', 'Unknown Amazon Title', '-'])
                    ).sort_values(by=['_has_title'], ascending=[False])
                    amz_title_map = df_amz_sorted.groupby(idx_comp)['amazon_title'].first().reset_index().drop(columns=['_has_title'], errors='ignore')
                    df_amz_agg = pd.merge(df_amz_agg, amz_title_map, on=idx_comp, how='left')
                else:
                    df_amz_agg['amazon_title'] = df_amz_agg.get('episode_name', 'Unknown Amazon Title')

                # Identificar filas UNMATCHED en Amazon (estricto por identificador/serie)
                is_unm_amz = (
                    (df_amz_agg['ip_name'].astype(str).str.upper() == 'UNMATCHED') |
                    (df_amz_agg['series_name'].astype(str).str.upper() == 'UNMATCHED_AMZ') |
                    (df_amz_agg['episode_number'].astype(str).str.startswith('UNMATCHED'))
                )
                if 'video_id' in df_amz_agg.columns:
                    is_unm_amz = is_unm_amz | df_amz_agg['video_id'].astype(str).str.startswith('UNMATCHED')

                # Título específico con el que hizo Match la IA
                bk_title_map = load_amazon_broadkast_titles()
                if 'match_title' in df_amz.columns:
                    df_amz_m_sorted = df_amz.assign(
                        _has_m=df_amz['match_title'].astype(str).str.strip().ne('') & ~df_amz['match_title'].astype(str).isin(['Unknown Title', 'UNMATCHED', '-', 'nan'])
                    ).sort_values(by=['_has_m'], ascending=[False])
                    amz_m_map = df_amz_m_sorted.groupby(idx_comp)['match_title'].first().reset_index().drop(columns=['_has_m'], errors='ignore')
                    df_amz_agg = pd.merge(df_amz_agg, amz_m_map, on=idx_comp, how='left')
                else:
                    if bk_title_map and 'amazon_title' in df_amz_agg.columns:
                        df_amz_agg['match_title'] = np.where(
                            is_unm_amz,
                            'UNMATCHED',
                            df_amz_agg['amazon_title'].map(bk_title_map).fillna(df_amz_agg['episode_name'])
                        )
                    else:
                        df_amz_agg['match_title'] = np.where(is_unm_amz, 'UNMATCHED', df_amz_agg['episode_name'])

                # Registros UNMATCHED: preservar estrictamente su título original de Amazon y match_title = 'UNMATCHED'
                df_amz_agg.loc[is_unm_amz, 'match_title'] = 'UNMATCHED'
                df_amz_agg.loc[is_unm_amz, 'episode_name'] = df_amz_agg.loc[is_unm_amz, 'amazon_title']

                # Registros MATCHED: resolver el título canónico original en inglés (episode_name)
                matched_mask = ~is_unm_amz
                if matched_mask.any():
                    en_title_map = load_broadkast_english_titles()
                    amz_to_bkid = load_amazon_to_bkid_map()

                    sub_amz = df_amz_agg.loc[matched_mask]
                    s_bk_amz = sub_amz['amazon_title'].map(bk_title_map) if (bk_title_map and 'amazon_title' in sub_amz.columns) else pd.Series(np.nan, index=sub_amz.index)
                    s_bkid = sub_amz['amazon_title'].map(amz_to_bkid) if (amz_to_bkid and 'amazon_title' in sub_amz.columns) else pd.Series(np.nan, index=sub_amz.index)

                    cur_m_titles = sub_amz['match_title'] if 'match_title' in sub_amz.columns else s_bk_amz
                    cur_amz_titles = sub_amz['amazon_title'] if 'amazon_title' in sub_amz.columns else pd.Series(np.nan, index=sub_amz.index)
                    cur_ep_names = sub_amz['episode_name']

                    chosen_en = [
                        get_best_english_title(bid, m_t, a_t, en_title_map, default=def_ep)
                        for bid, m_t, a_t, def_ep in zip(s_bkid, cur_m_titles, cur_amz_titles, cur_ep_names)
                    ]
                    df_amz_agg.loc[matched_mask, 'episode_name'] = chosen_en

                    # Fallback de match_title si venía vacío, nulo o idéntico a amazon_title en matched records
                    s_has_bk = pd.Series(s_bk_amz, index=sub_amz.index).notna() & (pd.Series(s_bk_amz, index=sub_amz.index) != '')
                    s_m_current = df_amz_agg.loc[matched_mask, 'match_title']
                    needs_m_fix = s_m_current.isna() | s_m_current.isin(['', 'nan', 'Unknown Title']) | (s_m_current.astype(str).str.strip() == sub_amz['amazon_title'].astype(str).str.strip())
                    df_amz_agg.loc[matched_mask, 'match_title'] = np.where(
                        needs_m_fix & s_has_bk,
                        s_bk_amz,
                        s_m_current
                    )

                if agg_level != "Por Vídeo/Versión (Mostrar resubidas)":
                    df_amz_agg = pd.merge(df_amz_agg, versions_count_amz, on=idx_comp, how='left')
                else:
                    comp_map = df_ep_src.groupby(idx_comp)['is_compilation'].first().reset_index()
                    df_amz_agg = pd.merge(df_amz_agg, comp_map, on=idx_comp, how='left')
                    
                if 'match_score' in df_amz.columns:
                    if agg_level == "Por Vídeo/Versión (Mostrar resubidas)":
                        score_map_amz = df_amz.groupby(idx_comp)['match_score'].first().reset_index()
                    else:
                        def _calc_weighted_score(grp):
                            tot_v = grp['views'].sum()
                            if tot_v > 0:
                                return (grp['match_score'] * grp['views']).sum() / tot_v
                            return grp['match_score'].mean()
                        score_map_amz = df_amz.groupby(idx_comp).apply(_calc_weighted_score).reset_index(name='match_score')
                        score_map_amz['match_score'] = score_map_amz['match_score'].round(1)
                    df_amz_agg = pd.merge(df_amz_agg, score_map_amz, on=idx_comp, how='left')

            s_svod = df_amz_agg['revenue_svod'] if 'revenue_svod' in df_amz_agg.columns else df_amz_agg['revenue']
            df_amz_agg['cph_rate'] = np.where(df_amz_agg['watch_time'] > 0, s_svod / df_amz_agg['watch_time'], 0)
            df_amz_agg['cph_rate'] = df_amz_agg['cph_rate'].round(4)
            
            df_amz_agg['avg_view_minutes'] = np.where(df_amz_agg['views'] > 0, (df_amz_agg['watch_time'] * 60) / df_amz_agg['views'], 0)
            df_amz_agg['avg_view_minutes'] = df_amz_agg['avg_view_minutes'].round(2)
            
            df_amz_agg = df_amz_agg.fillna(0)
            
            # Disposición de columnas: amazon_title, match_title, episode_name y match_score (excluyendo youtube_url e is_short)
            base_cols_amz = []
            for c in cols_base:
                if c == 'episode_name':
                    if 'amazon_title' in df_amz_agg.columns and 'amazon_title' not in base_cols_amz:
                        base_cols_amz.append('amazon_title')
                    if 'match_title' in df_amz_agg.columns and 'match_title' not in base_cols_amz:
                        base_cols_amz.append('match_title')
                    base_cols_amz.append('episode_name')
                    if 'match_score' in df_amz_agg.columns and 'match_score' not in base_cols_amz:
                        base_cols_amz.append('match_score')
                elif c in df_amz_agg.columns and c not in ('youtube_url', 'is_short'):
                    base_cols_amz.append(c)
                    
            if 'amazon_title' in df_amz_agg.columns and 'amazon_title' not in base_cols_amz:
                base_cols_amz.append('amazon_title')
            if 'match_title' in df_amz_agg.columns and 'match_title' not in base_cols_amz:
                base_cols_amz.append('match_title')
            if 'match_score' in df_amz_agg.columns and 'match_score' not in base_cols_amz:
                base_cols_amz.append('match_score')
                
            metrics_amz = ['revenue', 'revenue_svod', 'revenue_tvod', 'views', 'watch_time', 'cph_rate', 'avg_view_minutes']
            metrics_amz = [c for c in metrics_amz if c in df_amz_agg.columns]
            other_cols_amz = [c for c in df_amz_agg.columns if c not in base_cols_amz and c not in metrics_amz and c != 'is_short']
            df_amz = df_amz_agg[base_cols_amz + metrics_amz + other_cols_amz]
            df_amz = df_amz.drop(columns=['is_short'], errors='ignore')
            amz_sort_cols = [c for c in ['month', 'producer', 'ip_name', 'series_name'] if c in df_amz.columns]
            if amz_sort_cols:
                df_amz = df_amz.sort_values(by=amz_sort_cols).reset_index(drop=True)
            
            for r_col in ['revenue', 'revenue_svod', 'revenue_tvod', 'watch_time']:
                if r_col in df_amz.columns:
                    df_amz[r_col] = df_amz[r_col].round(2)
            
            int_cols = ['views', 'num_versiones_totales', 'num_versiones', 'num_publicaciones']
            for c in int_cols:
                if c in df_amz.columns:
                    df_amz[c] = df_amz[c].round().astype(int)

            totals_amz_rows = []
            tot_label = f"TOTAL ({periodo_label})" if (len(unique_subtotals) > 1 and periodo_label) else 'TOTAL'
            totals_amz = {}
            for col in df_amz.columns:
                if col == 'month':
                    totals_amz[col] = tot_label
                elif col in ['revenue', 'revenue_svod', 'revenue_tvod', 'watch_time']:
                    totals_amz[col] = round(float(df_amz[col].sum()), 2)
                elif col in ['views']:
                    totals_amz[col] = int(df_amz[col].sum())
                elif col == 'cph_rate':
                    tot_svod = float(df_amz['revenue_svod'].sum()) if 'revenue_svod' in df_amz.columns else (float(df_amz['revenue'].sum()) if 'revenue' in df_amz.columns else 0.0)
                    tot_wt = float(df_amz['watch_time'].sum()) if 'watch_time' in df_amz.columns else 0.0
                    totals_amz[col] = round(tot_svod / tot_wt, 4) if tot_wt > 0 else 0.0
                elif col == 'avg_view_minutes':
                    tot_views = float(df_amz['views'].sum()) if 'views' in df_amz.columns else 0.0
                    tot_wt = float(df_amz['watch_time'].sum()) if 'watch_time' in df_amz.columns else 0.0
                    totals_amz[col] = round((tot_wt * 60) / tot_views, 2) if tot_views > 0 else 0.0
                else:
                    totals_amz[col] = '-'
            totals_amz_rows.append(totals_amz)

            if len(unique_subtotals) > 1:
                df_raw_amz = report_combined[report_combined['platform'] == 'amazon']
                for sub_p in unique_subtotals:
                    df_sub_p = df_raw_amz[df_raw_amz['subtotal_period'] == sub_p]
                    row_sub = {}
                    for col in df_amz.columns:
                        if col == 'month':
                            row_sub[col] = str(sub_p)
                        elif col in ['revenue', 'revenue_svod', 'revenue_tvod', 'watch_time']:
                            row_sub[col] = round(float(df_sub_p[col].sum()), 2) if col in df_sub_p.columns else 0.0
                        elif col in ['views']:
                            row_sub[col] = int(df_sub_p[col].sum()) if col in df_sub_p.columns else 0
                        elif col == 'cph_rate':
                            sub_svod = float(df_sub_p['revenue_svod'].sum()) if 'revenue_svod' in df_sub_p.columns else (float(df_sub_p['revenue'].sum()) if 'revenue' in df_sub_p.columns else 0.0)
                            sub_wt = float(df_sub_p['watch_time'].sum()) if 'watch_time' in df_sub_p.columns else 0.0
                            row_sub[col] = round(sub_svod / sub_wt, 4) if sub_wt > 0 else 0.0
                        elif col == 'avg_view_minutes':
                            sub_views = float(df_sub_p['views'].sum()) if 'views' in df_sub_p.columns else 0.0
                            sub_wt = float(df_sub_p['watch_time'].sum()) if 'watch_time' in df_sub_p.columns else 0.0
                            row_sub[col] = round((sub_wt * 60) / sub_views, 2) if sub_views > 0 else 0.0
                        else:
                            row_sub[col] = '-'
                    totals_amz_rows.append(row_sub)

            df_totals_amz = pd.DataFrame(totals_amz_rows)
            if not df_totals_amz.empty:
                tot_cols_amz = ['month', 'revenue', 'revenue_svod', 'revenue_tvod', 'views', 'watch_time', 'cph_rate', 'avg_view_minutes']
                df_totals_amz = df_totals_amz[[c for c in tot_cols_amz if c in df_totals_amz.columns]]
        else:
            df_amz = pd.DataFrame()
            df_totals_amz = pd.DataFrame()
        return df_amz, df_totals_amz

    def _build_tencent():
        df_tcn_raw = report_combined[report_combined['platform'] == 'tencent'].copy()
        if df_tcn_raw.empty:
            return pd.DataFrame(), pd.DataFrame()

        if 'revenue' not in df_tcn_raw.columns:
            df_tcn_raw['revenue'] = 0.0
        if 'revenue_cny' not in df_tcn_raw.columns:
            df_tcn_raw['revenue_cny'] = 0.0
        if 'views' not in df_tcn_raw.columns:
            df_tcn_raw['views'] = 0

        if 'monetization_model' not in df_tcn_raw.columns:
            s_svod = df_tcn_raw['revenue_svod'].fillna(0) if 'revenue_svod' in df_tcn_raw.columns else pd.Series(0.0, index=df_tcn_raw.index)
            s_ch = df_tcn_raw['channel_id'].fillna('').astype(str) if 'channel_id' in df_tcn_raw.columns else pd.Series('', index=df_tcn_raw.index)
            df_tcn_raw['monetization_model'] = np.where(
                (s_svod > 0) | s_ch.str.contains('SVOD', case=False) | (df_tcn_raw['ip_name'] != 'CHANNEL_LEVEL'),
                'SVOD',
                'AVOD'
            )
        df_tcn_raw['monetization_model'] = df_tcn_raw['monetization_model'].fillna('SVOD').astype(str).str.upper()

        if 'revenue_svod' not in df_tcn_raw.columns:
            df_tcn_raw['revenue_svod'] = np.where(df_tcn_raw['monetization_model'] == 'SVOD', df_tcn_raw['revenue'], 0.0)
        if 'revenue_avod' not in df_tcn_raw.columns:
            df_tcn_raw['revenue_avod'] = np.where(df_tcn_raw['monetization_model'] == 'AVOD', df_tcn_raw['revenue'], 0.0)
        if 'channel_id' not in df_tcn_raw.columns:
            df_tcn_raw['channel_id'] = np.where(df_tcn_raw['monetization_model'] == 'SVOD', 'TENCENT_SVOD', 'TENCENT_AVOD_CHANNEL')
        else:
            df_tcn_raw['channel_id'] = df_tcn_raw['channel_id'].replace('', np.nan).fillna('TENCENT')
        if 'geography' not in df_tcn_raw.columns:
            df_tcn_raw['geography'] = 'CN'
        else:
            df_tcn_raw['geography'] = df_tcn_raw['geography'].replace('', np.nan).fillna('CN')

        if is_ip_mode:
            idx_tcn = ['month'] + producer_key + ['monetization_model', 'ip_name']
        elif is_series_mode:
            idx_tcn = ['month'] + producer_key + ['monetization_model', 'ip_name', 'series_name']
        else:
            idx_tcn = ['month'] + producer_key + ['monetization_model', 'ip_name', 'series_name', 'channel_id', 'geography']
        tcn_metrics = ['revenue', 'revenue_cny', 'revenue_svod', 'revenue_avod', 'views']
        df_tcn = df_tcn_raw.groupby(idx_tcn, dropna=False)[tcn_metrics].sum().reset_index()
        tcn_sort_cols = [c for c in ['month', 'producer', 'monetization_model', 'ip_name', 'series_name'] if c in df_tcn.columns]
        if tcn_sort_cols:
            df_tcn = df_tcn.sort_values(by=tcn_sort_cols).reset_index(drop=True)

        for r_col in ['revenue', 'revenue_cny', 'revenue_svod', 'revenue_avod']:
            df_tcn[r_col] = df_tcn[r_col].fillna(0.0).round(2)
        df_tcn['views'] = df_tcn['views'].fillna(0).round().astype(int)

        def _build_tcn_tot_row(df_slice, month_str):
            return {
                'month': month_str,
                'revenue': round(float(df_slice['revenue'].sum()), 2) if not df_slice.empty else 0.0,
                'revenue_cny': round(float(df_slice['revenue_cny'].sum()), 2) if not df_slice.empty else 0.0,
                'revenue_svod': round(float(df_slice['revenue_svod'].sum()), 2) if not df_slice.empty else 0.0,
                'revenue_avod': round(float(df_slice['revenue_avod'].sum()), 2) if not df_slice.empty else 0.0,
                'views': int(df_slice['views'].sum()) if not df_slice.empty else 0,
            }

        tot_label = f"TOTAL ({periodo_label})" if (len(unique_subtotals) > 1 and periodo_label) else 'TOTAL'
        totals_tcn_rows = [_build_tcn_tot_row(df_tcn, tot_label)]
        if len(unique_subtotals) > 1:
            for sub_p in unique_subtotals:
                df_sub_p = df_tcn_raw[df_tcn_raw['subtotal_period'] == sub_p]
                totals_tcn_rows.append(_build_tcn_tot_row(df_sub_p, str(sub_p)))

        df_totals_tcn = pd.DataFrame(totals_tcn_rows)
        tot_cols_tcn = ['month', 'revenue', 'revenue_cny', 'revenue_svod', 'revenue_avod', 'views']
        df_totals_tcn = df_totals_tcn[[c for c in tot_cols_tcn if c in df_totals_tcn.columns]]
        return df_tcn, df_totals_tcn

    def _build_china_detailed_df(
        plat_key: str,
        default_subplatform: str,
        default_channel_id: str,
        metric_cols: list,
        use_open_wt_svod_rule: bool = False,
    ):
        df_raw = report_combined[report_combined['platform'] == plat_key].copy()
        if df_raw.empty:
            return pd.DataFrame(), pd.DataFrame()

        for c in ['revenue', 'revenue_cny', 'watch_time']:
            if c not in df_raw.columns:
                df_raw[c] = 0.0
        for c in ['views', 'likes', 'comments']:
            if c not in df_raw.columns:
                df_raw[c] = 0

        if 'subplatform' not in df_raw.columns:
            if plat_key == 'youku':
                s_vid = df_raw['video_id'].fillna('').astype(str) if 'video_id' in df_raw.columns else pd.Series('', index=df_raw.index)
                s_ch = df_raw['channel_id'].fillna('').astype(str) if 'channel_id' in df_raw.columns else pd.Series('', index=df_raw.index)
                df_raw['subplatform'] = np.where(
                    s_vid.str.contains('DAYU', case=False) | s_ch.str.contains('DAYU', case=False),
                    'DaYu Platform',
                    'Open Platform',
                )
            else:
                df_raw['subplatform'] = default_subplatform
        else:
            df_raw['subplatform'] = df_raw['subplatform'].replace('', np.nan).fillna(default_subplatform)

        if 'monetization_model' not in df_raw.columns:
            s_a = df_raw['revenue_avod'].fillna(0) if 'revenue_avod' in df_raw.columns else pd.Series(0.0, index=df_raw.index)
            s_s = df_raw['revenue_svod'].fillna(0) if 'revenue_svod' in df_raw.columns else pd.Series(0.0, index=df_raw.index)
            s_wt = df_raw['watch_time'].fillna(0)
            extra_svod_init = ((df_raw['subplatform'] == 'Open Platform') & (s_wt > 0) & (s_a == 0)) if use_open_wt_svod_rule else ((s_wt > 0) & (s_a == 0))
            df_raw['monetization_model'] = np.where(
                (s_a > 0) & (s_s > 0),
                'AVOD+SVOD' if plat_key == 'youku' else 'MIXED',
                np.where((s_s > 0) | extra_svod_init, 'SVOD', 'AVOD'),
            )
        if 'revenue_avod' not in df_raw.columns:
            df_raw['revenue_avod'] = np.where(df_raw['monetization_model'] == 'SVOD', 0.0, df_raw['revenue'])
        if 'revenue_svod' not in df_raw.columns:
            df_raw['revenue_svod'] = np.where(df_raw['monetization_model'] == 'SVOD', df_raw['revenue'], 0.0)
        if 'channel_id' not in df_raw.columns:
            if plat_key == 'youku':
                df_raw['channel_id'] = np.where(df_raw['subplatform'] == 'DaYu Platform', 'YOUKU_DAYU', 'YOUKU_OPEN_PLATFORM')
            else:
                df_raw['channel_id'] = default_channel_id
        else:
            df_raw['channel_id'] = df_raw['channel_id'].replace('', np.nan).fillna(default_channel_id)
        if 'geography' not in df_raw.columns:
            df_raw['geography'] = 'CN'
        else:
            df_raw['geography'] = df_raw['geography'].replace('', np.nan).fillna('CN')

        if is_ip_mode:
            idx_cols = ['month'] + producer_key + ['subplatform', 'monetization_model', 'ip_name']
        elif is_series_mode:
            idx_cols = ['month'] + producer_key + ['subplatform', 'monetization_model', 'ip_name', 'series_name']
        else:
            idx_cols = ['month'] + producer_key + ['subplatform', 'monetization_model', 'ip_name', 'series_name', 'channel_id', 'geography']
        df_plat = df_raw.groupby(idx_cols, dropna=False)[metric_cols].sum().reset_index()

        # Reevaluar modelo de monetización tras agrupar por mes/año
        if use_open_wt_svod_rule:
            extra_svod_agg = (df_plat['subplatform'] == 'Open Platform') & (df_plat['watch_time'] > 0) & (df_plat['revenue_avod'] == 0)
        else:
            extra_svod_agg = (df_plat['watch_time'] > 0) & (df_plat['revenue_avod'] == 0)
        df_plat['monetization_model'] = np.where(
            (df_plat['revenue_avod'] > 0) & (df_plat['revenue_svod'] > 0),
            'AVOD+SVOD' if plat_key == 'youku' else 'MIXED',
            np.where((df_plat['revenue_svod'] > 0) | extra_svod_agg, 'SVOD', 'AVOD'),
        )
        df_plat = df_plat.groupby(idx_cols, dropna=False)[metric_cols].sum().reset_index()
        plat_sort_cols = [c for c in ['month', 'producer', 'subplatform', 'monetization_model', 'ip_name', 'series_name'] if c in df_plat.columns]
        if plat_sort_cols:
            df_plat = df_plat.sort_values(by=plat_sort_cols).reset_index(drop=True)

        for r_col in ['revenue', 'revenue_cny', 'revenue_avod', 'revenue_svod', 'watch_time']:
            if r_col in df_plat.columns:
                df_plat[r_col] = df_plat[r_col].fillna(0.0).round(2)
        for i_col in ['views', 'likes', 'comments']:
            if i_col in df_plat.columns:
                df_plat[i_col] = df_plat[i_col].fillna(0).round().astype(int)

        def _build_tot_row(df_slice, month_str):
            row = {'month': month_str}
            for r_col in ['revenue', 'revenue_cny', 'revenue_avod', 'revenue_svod', 'watch_time']:
                if r_col in metric_cols:
                    row[r_col] = round(float(df_slice[r_col].sum()), 2) if not df_slice.empty else 0.0
            for i_col in ['views', 'likes', 'comments']:
                if i_col in metric_cols:
                    row[i_col] = int(df_slice[i_col].sum()) if not df_slice.empty else 0
            return row

        tot_label = f"TOTAL ({periodo_label})" if (len(unique_subtotals) > 1 and periodo_label) else 'TOTAL'
        totals_rows = [_build_tot_row(df_plat, tot_label)]
        if len(unique_subtotals) > 1:
            for sub_p in unique_subtotals:
                df_sub_p = df_raw[df_raw['subtotal_period'] == sub_p]
                totals_rows.append(_build_tot_row(df_sub_p, str(sub_p)))

        df_totals_plat = pd.DataFrame(totals_rows)
        tot_cols_plat = ['month'] + metric_cols
        df_totals_plat = df_totals_plat[[c for c in tot_cols_plat if c in df_totals_plat.columns]]
        return df_plat, df_totals_plat

    def _build_youku():
        return _build_china_detailed_df(
            plat_key='youku',
            default_subplatform='Open Platform',
            default_channel_id='YOUKU',
            metric_cols=['revenue', 'revenue_cny', 'revenue_avod', 'revenue_svod', 'views', 'watch_time', 'likes', 'comments'],
            use_open_wt_svod_rule=True,
        )

    def _build_iqiyi():
        return _build_china_detailed_df(
            plat_key='iqiyi',
            default_subplatform='Amuse CC (2463347304)',
            default_channel_id='IQIYI_2463347304',
            metric_cols=['revenue', 'revenue_cny', 'revenue_avod', 'revenue_svod', 'views', 'watch_time', 'comments'],
            use_open_wt_svod_rule=False,
        )

    report_piv, df_totals = pd.DataFrame(), pd.DataFrame()
    df_yt, df_totals_yt = pd.DataFrame(), pd.DataFrame()
    df_amz, df_totals_amz = pd.DataFrame(), pd.DataFrame()
    df_tcn, df_totals_tcn = pd.DataFrame(), pd.DataFrame()
    df_yku, df_totals_yku = pd.DataFrame(), pd.DataFrame()
    df_iqy, df_totals_iqy = pd.DataFrame(), pd.DataFrame()

    tasks = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        if len(active_platforms) >= 2:
            tasks['comparative'] = executor.submit(_build_consolidated)
        if use_youtube:
            tasks['youtube'] = executor.submit(_build_youtube)
        if use_amazon:
            tasks['amazon'] = executor.submit(_build_amazon)
        if use_tencent:
            tasks['tencent'] = executor.submit(_build_tencent)
        if use_youku:
            tasks['youku'] = executor.submit(_build_youku)
        if use_iqiyi:
            tasks['iqiyi'] = executor.submit(_build_iqiyi)

        if 'comparative' in tasks:
            report_piv, df_totals = tasks['comparative'].result()
        if 'youtube' in tasks:
            df_yt, df_totals_yt = tasks['youtube'].result()
        if 'amazon' in tasks:
            df_amz, df_totals_amz = tasks['amazon'].result()
        if 'tencent' in tasks:
            df_tcn, df_totals_tcn = tasks['tencent'].result()
        if 'youku' in tasks:
            df_yku, df_totals_yku = tasks['youku'].result()
        if 'iqiyi' in tasks:
            df_iqy, df_totals_iqy = tasks['iqiyi'].result()

    return {
        "comparative": (report_piv, df_totals),
        "youtube": (df_yt, df_totals_yt),
        "amazon": (df_amz, df_totals_amz),
        "tencent": (df_tcn, df_totals_tcn),
        "youku": (df_yku, df_totals_yku),
        "iqiyi": (df_iqy, df_totals_iqy),
    }


def consolidate_reports(
    report_fin: pd.DataFrame, 
    report_op: pd.DataFrame, 
    agg_level: str, 
    use_youtube: bool = True, 
    use_amazon: bool = True,
    consolidar_periodo: bool = False,
    periodo_label: str = "",
    display_currency: str = "USD",
):
    res = consolidate_multiplatform_reports(
        report_fin=report_fin,
        report_op=report_op,
        agg_level=agg_level,
        use_youtube=use_youtube,
        use_amazon=use_amazon,
        use_tencent=False,
        use_youku=False,
        use_iqiyi=False,
        consolidar_periodo=consolidar_periodo,
        periodo_label=periodo_label,
        display_currency=display_currency,
    )
    rep_piv, df_totals = res["comparative"]
    df_yt, df_totals_yt = res["youtube"]
    df_amz, df_totals_amz = res["amazon"]
    return rep_piv, df_yt, df_amz, df_totals, df_totals_yt, df_totals_amz


if db_psql is not None and db_mongo is not None:
    lista_ips, lista_series, lista_seasons, lista_episodios, lista_territorios_display, lista_idiomas_display, geo_to_lang, lista_canales_display, channel_display_to_id = load_filter_options(db_psql)
    lista_productoras = KNOWN_PRODUCERS

    st.sidebar.header("Configuración de Reporte")
    
    st.sidebar.subheader("Granularidad Temporal")
    temporal_granularity = st.sidebar.selectbox(
        "Colección de Datos (MongoDB):",
        [
            "Por Meses (monthly_performance_summaries)",
            "Por Años (yearly_performance_summaries)",
            "Por Días (video_performance_events - Raw)"
        ],
        index=0,
        help="Permite elegir la colección de MongoDB a consultar. Las colecciones por Meses y Años están pre-agregadas para máxima velocidad. La colección por Días consulta eventos individuales sin resumir."
    )
    if "Por Días" in temporal_granularity:
        st.sidebar.warning("⚠️ **Atención:** La consulta de eventos diarios en bruto procesa un volumen elevado de datos sin resumir.")
        st.sidebar.info("ℹ️ **YouTube (Sin Desglose Territorial en Días):** El análisis por días de YouTube no incluye desglose por territorio/país (las métricas reflejan el total mundial consolidado del vídeo). Para auditar métricas desglosadas por país (audiencia real e ingresos prorrateados), seleccione la granularidad **Por Meses** o **Por Años**.")
        st.sidebar.info("ℹ️ **Amazon Prime Video (Prorrateo Diario de Ingresos):** Amazon emite liquidaciones financieras de regalías a nivel mensual. En la vista por días, los ingresos se **prorratean de forma lineal equitativa entre los días de cada mes (1/N días)** para permitir una comparación justa y homogénea con YouTube.")

    if "Por Años" in temporal_granularity:
        temp_mode = "yearly"
        temp_mode_label = "Por Años"
        temp_coll_name = "yearly_performance_summaries"
    elif "Por Días" in temporal_granularity:
        temp_mode = "daily"
        temp_mode_label = "Por Días"
        temp_coll_name = "video_performance_events"
    else:
        temp_mode = "monthly"
        temp_mode_label = "Por Meses"
        temp_coll_name = "monthly_performance_summaries"

    current_year = datetime.now().year
    available_years = list(range(2016, current_year + 2))
    default_year_start = 2025 if 2025 in available_years else current_year
    default_year_end = 2025 if 2025 in available_years else current_year

    with st.sidebar.form("filtros_reporte_form"):
        if temp_mode == "yearly":
            st.subheader("Periodo de Análisis (Años)", anchor=False)
            col_y1, col_y2 = st.columns(2)
            ano_inicio = col_y1.selectbox("Año Inicio:", available_years, index=available_years.index(default_year_start), key="ano_ini_yearly")
            ano_fin = col_y2.selectbox("Año Fin:", available_years, index=available_years.index(default_year_end), key="ano_fin_yearly")
            fecha_inicio = datetime(ano_inicio, 1, 1)
            fecha_fin = datetime(ano_fin, 12, 31)
        elif temp_mode == "monthly":
            st.subheader("Periodo de Análisis (Meses)", anchor=False)
            meses_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            
            st.markdown("**Desde:**")
            col_m1, col_y1 = st.columns([3, 2])
            mes_inicio = col_m1.selectbox("Mes Inicio:", range(1, 13), format_func=lambda m: f"{m:02d} - {meses_nombres[m-1]}", index=0, key="mes_ini_monthly")
            ano_inicio = col_y1.selectbox("Año Inicio:", available_years, index=available_years.index(default_year_start), key="ano_ini_monthly")
            
            st.markdown("**Hasta:**")
            col_m2, col_y2 = st.columns([3, 2])
            mes_fin = col_m2.selectbox("Mes Fin:", range(1, 13), format_func=lambda m: f"{m:02d} - {meses_nombres[m-1]}", index=11, key="mes_fin_monthly")
            ano_fin = col_y2.selectbox("Año Fin:", available_years, index=available_years.index(default_year_end), key="ano_fin_monthly")
            
            ultimo_dia = calendar.monthrange(ano_fin, mes_fin)[1]
            fecha_inicio = datetime(ano_inicio, mes_inicio, 1)
            fecha_fin = datetime(ano_fin, mes_fin, ultimo_dia)
        else:  # daily
            st.subheader("Periodo de Análisis (Días)", anchor=False)
            col_d1, col_d2 = st.columns(2)
            raw_fecha_inicio = col_d1.date_input(
                "Fecha Inicio:", 
                datetime(2025, 1, 1), 
                min_value=datetime(2016, 1, 1), 
                max_value=datetime(current_year + 1, 12, 31), 
                key="fecha_ini_daily"
            )
            raw_fecha_fin = col_d2.date_input(
                "Fecha Fin:", 
                datetime(2025, 1, 31), 
                min_value=datetime(2016, 1, 1), 
                max_value=datetime(current_year + 1, 12, 31), 
                key="fecha_fin_daily"
            )
            fecha_inicio = datetime(raw_fecha_inicio.year, raw_fecha_inicio.month, raw_fecha_inicio.day)
            fecha_fin = datetime(raw_fecha_fin.year, raw_fecha_fin.month, raw_fecha_fin.day)
            
            dias_diff = (fecha_fin - fecha_inicio).days
            if dias_diff > 90:
                st.info("💡 **Consejo:** Seleccionar rangos diarios superiores a 90 días puede ralentizar la consulta. Para rangos amplios se recomienda usar granularidad mensual o anual.")

        with st.expander("ℹ️ Cobertura Histórica de Datos", expanded=False):
            st.markdown(
                """
                - **YouTube:** Las métricas operacionales e ingresos publicitarios en MongoDB comienzan a recopilarse a partir de **abril de 2016** (los vídeos del catálogo subidos en 2014 y 2015 registran su rendimiento a partir de esa fecha).
                - **Amazon Prime Video:** Cobertura histórica continua desde **septiembre de 2016 hasta octubre de 2026** (122 meses). Integra la telemetría oficial de streaming (*Unique Streams* y minutos reproducidos) y liquidaciones de regalías unificadas al 100% en **USD ($)**.
                - **Tencent Video (China):** Datos históricos oficiales de ingresos y visualizaciones: **AVOD** a nivel de canal (**ene 2018 – dic 2023**) y **SVOD** por serie/IP (**mar 2021 – feb 2025**). Importes convertidos de RMB (¥) a USD con la tasa media anual del ejercicio correspondiente.
                - **Youku (China):** Canales propios **DaYu Platform** (`CARCITY` y `LEARN_TV`, **mar 2017 – may 2023**) y catálogo licenciado **Open Platform** por serie/IP (**ene 2020 – ene 2025** AVOD/SVOD + views y horas SVOD). Importes convertidos de RMB (¥) a USD con la tasa media anual correspondiente.
                - **iQIYI (China):** Cuentas **Amuse CC (2463347304)** (**2017–2025** AVOD + vistas por serie), **Amuse LTV / France (2484062153)** (**2017–2026** AVOD/SVOD + vistas por serie y Watch Time VIP **feb 2022 – jun 2024**) y **Amuse Shanghai (4318775981759616)** (**abr 2024 – ene 2026**). Importes en RMB (¥) convertidos a USD con tasa media anual.
                - **Granularidad Diaria:** En vista diaria, las regalías mensuales de Amazon y los ingresos mensuales de Youku *Open Platform* se prorratean equitativamente (1/N días del mes); Youku *DaYu*, Tencent e iQIYI reflejan reportes diarios nativos (con asignación proporcional dentro de cada mes SVOD 2019–2021 de iQIYI).
                """
            )

        st.markdown("")
        consolidar_periodo = st.checkbox(
            "Consolidar métricas de todo el periodo (Agregado)",
            value=False,
            help="Si está marcado, suma todas las métricas de todo el rango seleccionado (ej. 2020 a 2025) en una sola fila por vídeo o episodio, en lugar de desglosar fila por fila cada año/mes/día."
        )

        st.markdown("---")
        st.subheader("Plataformas a Incluir", anchor=False)
        use_youtube = st.checkbox("YouTube", value=True)
        use_amazon = st.checkbox("Amazon Prime Video", value=True)
        use_tencent = st.checkbox("Tencent Video (China)", value=True)
        use_youku = st.checkbox("Youku (China)", value=True)
        use_iqiyi = st.checkbox("iQIYI (China)", value=True)
        
        st.markdown("---")
        st.subheader("Filtros Globales de Contenido", anchor=False)
        global_producers = st.multiselect("Productora:", lista_productoras, help="Filtrar por productora (Amuse Animation, Millimages, Sunnyside Studios, etc.). Dejar vacío para incluir todas.")
        global_ips = st.multiselect("Propiedad Intelectual (IP):", lista_ips, help="Aplica a todas las plataformas. Dejar vacío para incluir todas.")
        global_series = st.multiselect("Serie:", lista_series, help="Aplica a todas las plataformas. Dejar vacío para incluir todas.")
        global_channels = st.multiselect("Canal (YouTube / Plataforma):", lista_canales_display, help="Filtrar por canal específico de YouTube, Amazon Prime Video, Tencent Video, Youku o iQIYI. Dejar vacío para incluir todos.")
        global_seasons = st.multiselect("Temporada (Season):", lista_seasons, help="Aplica a YouTube y Amazon. Dejar vacío para incluir todas.")
        global_episodes = st.multiselect("Número de Episodio:", lista_episodios, help="Aplica a YouTube y Amazon. Dejar vacío para incluir todos.")
        global_languages = st.multiselect("Idioma:", lista_idiomas_display, help="Filtra por idioma del contenido (audio en YouTube y título/versión lingüística en Amazon; plataformas chinas en chino 'zh'). Dejar vacío para incluir todos.")
        global_geos = st.multiselect("Territorio / País:", lista_territorios_display, help="Aplica tanto a YouTube y Amazon como a Tencent, Youku e iQIYI (CN). Dejar vacío para incluir todos. En vista diaria, YouTube refleja métricas mundiales.")

        st.markdown("---")
        st.subheader("Divisa del Reporte", anchor=False)
        selected_currency = st.radio(
            "Moneda de visualización y exportación:",
            ["USD ($)", "EUR (€)"],
            index=0,
            horizontal=True,
            help="Selecciona si deseas visualizar todos los importes consolidados en Dólares ($ USD) o en Euros (€ EUR). La conversión se realiza dinámicamente según la tabla oficial editable de tipos de cambio."
        )
        display_currency_val = "EUR" if "EUR" in selected_currency else "USD"

        st.markdown("---")
        st.subheader("Nivel de Agregación", anchor=False)
        agg_level = st.radio("Agrupar métricas por:", [
            "Por Propiedad Intelectual (IP)",
            "Por Serie",
            "Episodio Canónico (Todas las versiones)",
            "Por Idioma (Separar traducciones)",
            "Por Territorio / País",
            "Por Vídeo/Versión (Mostrar resubidas)"
        ])
        if agg_level == "Por Propiedad Intelectual (IP)":
            st.caption("🏢 *Vista ejecutiva macro: 1 fila por IP consolidando YouTube, Amazon, Tencent, Youku e iQIYI.*")
        elif agg_level == "Por Serie":
            st.caption("🎬 *Desglose comparativo multiplataforma por show, paquete temático y canal.*")
        elif temp_mode == "daily":
            st.caption("ℹ️ *Nota para Vista Diaria:* YouTube reporta métricas mundiales consolidadas en el análisis diario (sin desglose de país). Si selecciona 'Por Territorio / País', el desglose geográfico detallado se recomienda en granularidad **Por Meses** o **Por Años**.")
        else:
            st.caption("⏱️ *A menor nivel de agregación (mayor detalle por idioma, territorio o resubida individual), mayor es el volumen de datos y el tiempo de ejecución.*")

        submitted = st.form_submit_button("Generar Reportes Consolidados", use_container_width=True)

    placeholder_msg_yt = st.empty()
    placeholder_msg_amz = st.empty()
    placeholder_msg_tcn = st.empty()
    placeholder_msg_yku = st.empty()
    placeholder_msg_iqy = st.empty()
    placeholder_msg_tablas = st.empty()
    results_placeholder = st.empty()

    if submitted:
        placeholder_msg_yt.empty()
        placeholder_msg_amz.empty()
        placeholder_msg_tcn.empty()
        placeholder_msg_yku.empty()
        placeholder_msg_iqy.empty()
        placeholder_msg_tablas.empty()
        results_placeholder.empty()
        for k in [
            "ready_report_piv", "ready_df_yt", "ready_df_amz", "ready_df_tcn", "ready_df_yku", "ready_df_iqy",
            "ready_df_totals", "ready_df_totals_yt", "ready_df_totals_amz", "ready_df_totals_tcn", "ready_df_totals_yku", "ready_df_totals_iqy",
            "ready_report_generated", "use_youtube_executed", 
            "use_amazon_executed", "use_tencent_executed", "use_youku_executed", "use_iqiyi_executed", "use_tablas_executed"
        ]:
            st.session_state.pop(k, None)

        selected_lang_codes = [item.split('(')[-1].replace(')', '').strip().lower() for item in global_languages] if global_languages else []
        selected_geo_codes = [item.split(' - ')[0].strip().upper() for item in global_geos] if global_geos else []

        if temp_mode == "yearly":
            periodo_label = f"{ano_inicio} - {ano_fin}" if ano_inicio != ano_fin else f"{ano_inicio}"
        elif temp_mode == "monthly":
            periodo_label = f"{ano_inicio}-{mes_inicio:02d} a {ano_fin}-{mes_fin:02d}"
        else:  # daily
            periodo_label = f"{fecha_inicio.strftime('%Y-%m-%d')} a {fecha_fin.strftime('%Y-%m-%d')}"

        if fecha_inicio > fecha_fin:
            st.error("Error: La fecha de inicio no puede ser posterior a la fecha de fin.")
        elif not use_youtube and not use_amazon and not use_tencent and not use_youku and not use_iqiyi:
            st.warning("⚠️ Debes seleccionar al menos una plataforma de distribución para generar los reportes.")
        else:
            filtros_dict = {
                'fecha_inicio': fecha_inicio,
                'fecha_fin': fecha_fin,
                'producers': global_producers,
                'ips': global_ips,
                'series': global_series,
                'seasons': global_seasons,
                'episodes': global_episodes,
                'idiomas': global_languages,
                'territorios': global_geos,
                'granularidad': temp_mode_label,
                'coleccion': temp_coll_name,
                'temp_mode': temp_mode,
                'agg_level': agg_level,
                'use_youtube': use_youtube,
                'use_amazon': use_amazon,
                'use_tencent': use_tencent,
                'use_youku': use_youku,
                'use_iqiyi': use_iqiyi,
                'consolidar_periodo': consolidar_periodo,
                'periodo_label': periodo_label,
                'display_currency': display_currency_val,
            }
            
            collected_fin = []
            collected_op = []
            rango_parts = []

            if use_youtube:
                with st.spinner("Procesando pipeline de YouTube... Paso 1/4 (PostgreSQL)"):
                    selected_channel_ids = [channel_display_to_id[c] for c in global_channels if c in channel_display_to_id] if global_channels else None
                    df_meta = fetch_yt_metadata(db_psql, global_ips, global_series, global_seasons, global_episodes, selected_lang_codes, None, channels=selected_channel_ids)

                if df_meta.empty:
                    st.warning("No se encontraron vídeos de YouTube en PostgreSQL que coincidan con los filtros.")
                else:
                    df_meta.fillna({'ip_name': 'Unknown IP', 'series_name': 'Unknown Series', 'geography': 'Unknown Geo', 'channel_id': 'Unknown ID', 'season': 0, 'episode_number': 0}, inplace=True)
                    
                    lista_video_ids = df_meta['video_id'].unique().tolist()
                    is_territory_query = (agg_level == "Por Territorio / País") or bool(selected_geo_codes)

                    with st.spinner(f"Procesando pipeline de YouTube... Paso 2/4 (MongoDB - {temp_mode_label}) con {len(lista_video_ids)} IDs..."):
                        if temp_mode == "yearly":
                            coll_mongo = db_mongo['yearly_performance_summaries']
                            match_stage = {
                                "_id.event_type": "youtube.video.performance_recorded",
                                "_id.year": {
                                    "$gte": fecha_inicio.strftime("%Y"),
                                    "$lte": fecha_fin.strftime("%Y")
                                }
                            }
                            if global_ips or global_series or global_channels or global_seasons or global_episodes or selected_lang_codes or selected_geo_codes:
                                match_stage["_id.video_id"] = {"$in": lista_video_ids}
                            if is_territory_query:
                                match_stage["_id.geography"] = {"$nin": ["Global", "Unknown Geo"]}
                            else:
                                match_stage["_id.geography"] = "Global"

                            pipeline = [
                                {"$match": match_stage},
                                {
                                    "$group": {
                                        "_id": {
                                            "video_id": "$_id.video_id",
                                            "month": "$_id.year",
                                            "platform": "$_id.platform",
                                            "geography": { "$ifNull": ["$_id.geography", "Unknown Geo"] }
                                        },
                                        "revenue": { "$sum": "$yearly_revenue" },
                                        "revenue_svod": { "$sum": { "$ifNull": ["$yearly_revenue_svod", "$yearly_revenue"] } },
                                        "revenue_tvod": { "$sum": { "$ifNull": ["$yearly_revenue_tvod", 0] } },
                                        "views": { "$sum": "$yearly_views" },
                                        "watch_time": { "$sum": "$yearly_watch_time" },
                                        "likes": { "$sum": "$yearly_likes" },
                                        "comments": { "$sum": "$yearly_comments" },
                                        "ad_impressions": { "$sum": "$yearly_ad_impressions" },
                                        "ad_revenue": { "$sum": "$yearly_ad_revenue" }
                                    }
                                }
                            ]
                        elif temp_mode == "daily":
                            coll_mongo = db_mongo[os.getenv("MONGODB_ANALYTICS_COLLECTION", 'video_performance_events')]
                            match_stage = {
                                "metadata.event_type": "youtube.video.performance_recorded",
                                "payload.date": {
                                    "$gte": fecha_inicio.strftime("%Y-%m-%d"),
                                    "$lte": fecha_fin.strftime("%Y-%m-%d")
                                }
                            }
                            if global_ips or global_series or global_channels or global_seasons or global_episodes or selected_lang_codes or selected_geo_codes:
                                match_stage["payload.video_id"] = {"$in": lista_video_ids}
                            if selected_geo_codes:
                                match_stage["$or"] = [
                                    {"payload.geography": {"$in": selected_geo_codes}},
                                    {"payload.geography": "Unknown Geo"},
                                    {"payload.geography": { "$exists": False }}
                                ]
                            else:
                                # En vista diaria global, excluir eventos mensuales de territorio que coinciden en el día 1 (YYYY-MM-01)
                                match_stage["$or"] = [
                                    {"payload.geography": { "$exists": False }},
                                    {"payload.geography": { "$in": ["Global", "Unknown Geo", None] }}
                                ]

                            pipeline = [
                                {"$match": match_stage},
                                {
                                    "$group": {
                                        "_id": {
                                            "video_id": "$payload.video_id",
                                            "month": "$payload.date",
                                            "platform": "$payload.platform",
                                            "geography": { "$ifNull": ["$payload.geography", "Unknown Geo"] }
                                        },
                                        "revenue": { "$sum": { "$ifNull": ["$payload.estimated_revenue", 0] } },
                                        "revenue_svod": { "$sum": { "$ifNull": ["$payload.extra_metrics.revenue_svod", "$payload.estimated_revenue"] } },
                                        "revenue_tvod": { "$sum": { "$ifNull": ["$payload.extra_metrics.revenue_tvod", 0] } },
                                        "views": { "$sum": { "$ifNull": ["$payload.extra_metrics.views", { "$ifNull": ["$payload.views", 0] }] } },
                                        "watch_time": { "$sum": { "$ifNull": ["$payload.extra_metrics.estimated_minutes_watched", { "$ifNull": ["$payload.watch_time", 0] }] } },
                                        "likes": { "$sum": { "$ifNull": ["$payload.extra_metrics.likes", 0] } },
                                        "comments": { "$sum": { "$ifNull": ["$payload.extra_metrics.comments", 0] } },
                                        "ad_impressions": { "$sum": { "$ifNull": ["$payload.extra_metrics.ad_impressions", 0] } },
                                        "ad_revenue": { "$sum": { "$ifNull": ["$payload.extra_metrics.estimated_ad_revenue", 0] } }
                                    }
                                }
                            ]
                        else: # "monthly"
                            coll_mongo = db_mongo['monthly_performance_summaries']
                            match_stage = {
                                "_id.event_type": "youtube.video.performance_recorded",
                                "_id.month": {
                                    "$gte": fecha_inicio.strftime("%Y-%m"),
                                    "$lte": fecha_fin.strftime("%Y-%m")
                                }
                            }
                            if global_ips or global_series or global_channels or global_seasons or global_episodes or selected_lang_codes or selected_geo_codes:
                                match_stage["_id.video_id"] = {"$in": lista_video_ids}
                            if is_territory_query:
                                match_stage["_id.geography"] = {"$nin": ["Global", "Unknown Geo"]}
                            else:
                                match_stage["_id.geography"] = "Global"

                            pipeline = [
                                {"$match": match_stage},
                                {
                                    "$group": {
                                        "_id": {
                                            "video_id": "$_id.video_id",
                                            "month": "$_id.month",
                                            "platform": "$_id.platform",
                                            "geography": { "$ifNull": ["$_id.geography", "Unknown Geo"] }
                                        },
                                        "revenue": { "$sum": "$monthly_revenue" },
                                        "revenue_svod": { "$sum": { "$ifNull": ["$monthly_revenue_svod", "$monthly_revenue"] } },
                                        "revenue_tvod": { "$sum": { "$ifNull": ["$monthly_revenue_tvod", 0] } },
                                        "views": { "$sum": "$monthly_views" },
                                        "watch_time": { "$sum": "$monthly_watch_time" },
                                        "likes": { "$sum": "$monthly_likes" },
                                        "comments": { "$sum": "$monthly_comments" },
                                        "ad_impressions": { "$sum": "$monthly_ad_impressions" },
                                        "ad_revenue": { "$sum": "$monthly_ad_revenue" }
                                    }
                                }
                            ]
                        
                        try:
                            mongo_data = list(coll_mongo.aggregate(pipeline, allowDiskUse=True))
                            
                            flat_mongo_data = []
                            for doc in mongo_data:
                                flat_mongo_data.append({
                                    'video_id': doc['_id']['video_id'],
                                    'month': doc['_id']['month'],
                                    'platform': doc['_id'].get('platform', 'youtube'),
                                    'geography': doc['_id'].get('geography', 'Unknown Geo'),
                                    'revenue': doc.get('revenue', 0.0),
                                    'views': doc.get('views', 0),
                                    'watch_time': round(doc.get('watch_time', 0) / 60.0, 2),
                                    'likes': doc.get('likes', 0),
                                    'comments': doc.get('comments', 0),
                                    'ad_impressions': doc.get('ad_impressions', 0),
                                    'ad_revenue': doc.get('ad_revenue', 0.0)
                                })
                            df_performance = pd.DataFrame(flat_mongo_data)

                            # Si los datos en MongoDB aún no tienen revenue territorial (datos legacy a 0), aplicar asignación ponderada por CPM
                            has_territorial_revenue = (df_performance["revenue"].sum() > 0.0) if not df_performance.empty else False
                            if is_territory_query and not df_performance.empty and temp_mode in ["monthly", "yearly"] and not has_territorial_revenue:
                                time_field = "_id.month" if temp_mode == "monthly" else "_id.year"
                                rev_field = "monthly_revenue" if temp_mode == "monthly" else "yearly_revenue"
                                ad_rev_field = "monthly_ad_revenue" if temp_mode == "monthly" else "yearly_ad_revenue"
                                ad_imp_field = "monthly_ad_impressions" if temp_mode == "monthly" else "yearly_ad_impressions"
                                
                                global_match = {
                                    "_id.event_type": "youtube.video.performance_recorded",
                                    time_field: match_stage[time_field],
                                    "_id.geography": "Global"
                                }
                                if "_id.video_id" in match_stage:
                                    global_match["_id.video_id"] = match_stage["_id.video_id"]
                                    
                                global_pipeline = [
                                    {"$match": global_match},
                                    {
                                        "$group": {
                                            "_id": {
                                                "video_id": "$_id.video_id",
                                                "month": f"${time_field}"
                                            },
                                            "global_revenue": {"$sum": f"${rev_field}"},
                                            "global_ad_revenue": {"$sum": f"${ad_rev_field}"},
                                            "global_ad_impressions": {"$sum": f"${ad_imp_field}"}
                                        }
                                    }
                                ]
                                try:
                                    global_docs = list(coll_mongo.aggregate(global_pipeline, allowDiskUse=True))
                                    if global_docs:
                                        df_glob = pd.DataFrame([{
                                            "video_id": d["_id"]["video_id"],
                                            "month": d["_id"]["month"],
                                            "global_revenue": d.get("global_revenue", 0.0),
                                            "global_ad_revenue": d.get("global_ad_revenue", 0.0),
                                            "global_ad_impressions": d.get("global_ad_impressions", 0)
                                        } for d in global_docs])
                                        
                                        df_performance = df_performance.merge(df_glob, on=["video_id", "month"], how="left").fillna({
                                            "global_revenue": 0.0, 
                                            "global_ad_revenue": 0.0,
                                            "global_ad_impressions": 0
                                        })
                                        # Ponderación económica por CPM de territorio (calibrada para catálogo infantil Amuse Animation)
                                        tier_cpm = {
                                            "US": 18.0, "CA": 14.0, "GB": 14.5, "AU": 18.0, "DE": 13.8, "CH": 46.0, "AT": 18.0,
                                            "FR": 12.5, "ES": 6.8, "IT": 6.2, "NL": 12.0, "BE": 17.0, "SE": 14.0, "NO": 15.0,
                                            "DK": 14.0, "FI": 12.0, "IE": 12.0, "NZ": 13.0, "JP": 9.0, "KR": 8.0,
                                            "MX": 2.2, "BR": 2.1, "AR": 1.5, "CL": 2.5, "CO": 1.6, "PE": 1.4,
                                            "PL": 5.2, "CZ": 4.3, "RO": 2.8, "TR": 1.2, "RU": 1.5,
                                            "IN": 0.6, "PH": 0.8, "ID": 0.65, "VN": 0.7, "TH": 1.6, "MY": 2.0
                                        }
                                        cpm_weights = df_performance["geography"].map(tier_cpm).fillna(2.0)
                                        df_performance["cpm_weight"] = df_performance["views"] * cpm_weights
                                        tot_weights = df_performance.groupby(["video_id", "month"])["cpm_weight"].transform("sum")
                                        ratio = np.where(tot_weights > 0, df_performance["cpm_weight"] / tot_weights, 0.0)
                                        df_performance["revenue"] = (df_performance["global_revenue"] * ratio).round(4)
                                        df_performance["ad_revenue"] = (df_performance["global_ad_revenue"] * ratio).round(4)
                                        df_performance["ad_impressions"] = np.round(df_performance["global_ad_impressions"] * ratio).astype(int)

                                        # Reconciliar residual no clasificado por periodo para asegurar 100% de coincidencia contable sin distorsionar periodos históricos
                                        if not selected_geo_codes and not df_performance.empty and not df_glob.empty:
                                            alloc_by_period = df_performance.groupby("month")["revenue"].transform("sum")
                                            glob_by_period_map = df_glob.groupby("month")["global_revenue"].sum()
                                            glob_by_period = df_performance["month"].map(glob_by_period_map).fillna(0.0)
                                            scale_factor = np.where(
                                                (alloc_by_period > 0) & (glob_by_period > alloc_by_period),
                                                glob_by_period / alloc_by_period,
                                                1.0
                                            )
                                            df_performance["revenue"] = (df_performance["revenue"] * scale_factor).round(4)
                                            df_performance["ad_revenue"] = (df_performance["ad_revenue"] * scale_factor).round(4)

                                        df_performance.drop(columns=["global_revenue", "global_ad_revenue", "global_ad_impressions", "cpm_weight"], inplace=True, errors="ignore")
                                except Exception as e:
                                    logger.error("Error en la asignación de ingresos territoriales de YouTube: %s", e)
                        except Exception as e:
                            st.error(f"Fallo en la agregación distribuida (YouTube): {e}")
                            df_performance = pd.DataFrame()

                    if df_performance.empty:
                        st.warning("No se encontraron registros de rendimiento de YouTube para los parámetros seleccionados.")
                    else:
                        with st.spinner("Consolidando métricas de YouTube..."):
                            df_meta_clean = df_meta.drop(columns=['geography', 'meta_geography'], errors='ignore')
                            df_master = pd.merge(df_performance, df_meta_clean, on=['video_id'], how='left')

                            if temp_mode == "daily" or not is_territory_query:
                                df_master['geography'] = "Global (Mundial)"
                                if temp_mode == "daily" and selected_geo_codes:
                                    st.info("ℹ️ **Aviso sobre Territorio (Vista Diaria):** El desglose por territorio de consumo del espectador se consolida a nivel mensual (igual que en Amazon). En la vista diaria se muestran las métricas mundiales consolidadas de YouTube.")
                            else:
                                # Utilizar la geografía real del espectador de la ingesta mensual territorial de MongoDB
                                df_master['geography'] = df_master['geography'].fillna('Unknown Geo')
                                if selected_geo_codes:
                                    df_master = df_master[df_master['geography'].isin(selected_geo_codes)]
                                elif agg_level == "Por Territorio / País":
                                    df_master = df_master[~df_master['geography'].isin(["Global", "Unknown Geo"])]

                            df_master.fillna({
                                'ip_name': 'UNMATCHED', 
                                'series_name': 'UNMATCHED_YT', 
                                'channel_id': 'Unknown ID', 
                                'geography': 'Unknown Geo', 
                                'season': 0, 
                                'episode_number': 0,
                                'video_duration': 0,
                                'video_title': 'Unknown Video',
                                'language_code': 'Unknown'
                            }, inplace=True)

                            if 'channel_name' in df_master.columns:
                                mask_chan = ~df_master['channel_id'].isin(['Unknown ID', 'Amazon Prime Video', None]) & df_master['channel_name'].notna()
                                df_master.loc[mask_chan, 'channel_id'] = df_master.loc[mask_chan, 'channel_name'] + ' (' + df_master.loc[mask_chan, 'channel_id'] + ')'
                            df_master['episode_name'] = df_master['episode_name'].replace(['Unknown Episode', 'Legacy Compilation', '', None], np.nan).combine_first(df_master['video_title']).fillna('Unknown Video')
                            df_master['series_name'] = df_master['series_name'].replace('Unknown Series', 'UNMATCHED_YT')
                            df_master['ip_name'] = df_master['ip_name'].replace('Unknown IP', 'UNMATCHED')

                            # Enriquecer cualquier vídeo residual que haya quedado en UNMATCHED con el catálogo de canales
                            df_master = enrich_youtube_dataframe(df_master, channel_col='channel_id', ip_col='ip_name', series_col='series_name')

                            # Enriquecer con Productora
                            df_master['producer'] = df_master.apply(
                                lambda r: resolve_producer(r.get('video_title'), r.get('series_name'), r.get('ip_name'), platform='youtube'),
                                axis=1
                            )
                            df_master['producer'] = df_master['producer'].fillna('Amuse Animation')
                            if global_producers:
                                df_master = df_master[df_master['producer'].isin(global_producers)]

                            yt_group_cols = [
                                'month', 'producer', 'ip_name', 'series_name', 'season', 'episode_number', 
                                'episode_name', 'geography', 'video_id', 'channel_id', 'platform', 
                                'language_code', 'video_title', 'video_duration'
                            ]
                            report_financiero = df_master.groupby(yt_group_cols, dropna=False)['revenue'].sum().reset_index()
                            report_financiero = report_financiero.sort_values(by=['month', 'ip_name', 'series_name'])

                            report_operacional = df_master.groupby(yt_group_cols, dropna=False)[['views', 'watch_time', 'likes', 'comments', 'ad_impressions', 'ad_revenue']].sum().reset_index()
                            report_operacional = report_operacional.sort_values(by=['month', 'ip_name'])

                        collected_fin.append(report_financiero)
                        collected_op.append(report_operacional)
                        rango_parts.append("YouTube")

                        placeholder_msg_yt.success("¡Procesamiento de Youtube finalizado con éxito!")
                        st.session_state.use_youtube_executed = True

            if use_amazon:
                with st.spinner("Procesando pipeline de Amazon Prime... Paso 1/4 (PostgreSQL)"):
                    db_psql_amz = get_broadkast_postgres_connection()
                    df_meta_amz = fetch_amz_metadata(db_psql_amz, db_psql, global_ips, global_series, global_seasons, global_episodes, channels=global_channels)
                        
                is_unmatched_selected = ("UNMATCHED" in global_ips) if global_ips else False
                if df_meta_amz.empty and not (is_unmatched_selected or not global_ips):
                    st.warning("No se encontraron vídeos de Amazon en PostgreSQL que coincidan con los filtros.")
                else:
                    if not df_meta_amz.empty:
                        df_meta_amz.fillna({'ip_name': 'Unknown IP', 'series_name': 'Unknown Series', 'episode_name': 'Unknown Episode', 'season': 0, 'episode_number': 0}, inplace=True)
                    
                    with st.spinner(f"Procesando pipeline de Amazon... Paso 2/4 (MongoDB - {temp_mode_label})..."):
                        if temp_mode == "yearly":
                            coll_mongo = db_mongo['yearly_performance_summaries']
                            match_stage_amz = {
                                "_id.event_type": {"$in": ["amazon.video.performance_recorded", "amazon.video.performance_svod", "amazon.video.performance_tvod"]},
                                "_id.platform": "amazon",
                                "_id.year": {
                                    "$gte": fecha_inicio.strftime("%Y"),
                                    "$lte": fecha_fin.strftime("%Y")
                                }
                            }
                            conds_vid_amz = []
                            lista_video_ids_amz = df_meta_amz['video_id'].unique().tolist() if not df_meta_amz.empty else []
                            if lista_video_ids_amz:
                                conds_vid_amz.append({"_id.video_id": {"$in": lista_video_ids_amz}})
                            if not global_series and not global_seasons and not global_episodes:
                                if not global_channels or "Amazon Prime Video" in global_channels:
                                    if not global_ips or "UNMATCHED" in global_ips:
                                        conds_vid_amz.append({"_id.video_id": {"$regex": "^UNMATCHED"}})

                            if len(conds_vid_amz) == 1:
                                match_stage_amz.update(conds_vid_amz[0])
                            elif len(conds_vid_amz) > 1:
                                match_stage_amz["$or"] = conds_vid_amz
                            else:
                                match_stage_amz["_id.video_id"] = {"$in": []}
                            
                            if selected_geo_codes:
                                match_stage_amz["_id.geography"] = {"$in": selected_geo_codes}

                            pipeline_amz = [
                                {"$match": match_stage_amz},
                                {
                                    "$group": {
                                        "_id": {
                                            "video_id": "$_id.video_id",
                                            "month": "$_id.year",
                                            "platform": "$_id.platform",
                                            "geography": "$_id.geography"
                                        },
                                        "mongo_title": { "$first": "$title" },
                                        "mongo_series": { "$first": { "$ifNull": ["$series_name", "UNMATCHED_AMZ"] } },
                                        "currency": { "$first": { "$ifNull": ["$currency", "USD"] } },
                                        "revenue": { "$sum": "$yearly_revenue" },
                                        "revenue_svod": { "$sum": { "$ifNull": ["$yearly_revenue_svod", "$yearly_revenue"] } },
                                        "revenue_tvod": { "$sum": { "$ifNull": ["$yearly_revenue_tvod", 0] } },
                                        "views": { "$sum": "$yearly_views" },
                                        "watch_time": { "$sum": "$yearly_watch_time" }
                                    }
                                }
                            ]
                        elif temp_mode == "daily":
                            coll_mongo = db_mongo[os.getenv("MONGODB_ANALYTICS_COLLECTION", 'video_performance_events')]
                            
                            # Identificar los meses involucrados en [fecha_inicio, fecha_fin]
                            # Los eventos de Amazon en MongoDB se registran el día 1 de cada mes (YYYY-MM-01)
                            cur_m = fecha_inicio.replace(day=1)
                            end_m = fecha_fin.replace(day=1)
                            amz_month_dates = []
                            while cur_m <= end_m:
                                amz_month_dates.append(cur_m.strftime("%Y-%m-01"))
                                next_m = cur_m.month % 12 + 1
                                next_y = cur_m.year + (cur_m.month // 12)
                                cur_m = cur_m.replace(year=next_y, month=next_m, day=1)

                            match_stage_amz = {
                                "metadata.event_type": {"$in": ["amazon.video.performance_recorded", "amazon.video.performance_svod", "amazon.video.performance_tvod"]},
                                "payload.platform": "amazon",
                                "payload.date": {"$in": amz_month_dates}
                            }
                            conds_vid_amz = []
                            lista_video_ids_amz = df_meta_amz['video_id'].unique().tolist() if not df_meta_amz.empty else []
                            if lista_video_ids_amz:
                                conds_vid_amz.append({"payload.video_id": {"$in": lista_video_ids_amz}})
                            if not global_series and not global_seasons and not global_episodes:
                                if not global_channels or "Amazon Prime Video" in global_channels:
                                    if not global_ips or "UNMATCHED" in global_ips:
                                        conds_vid_amz.append({"payload.video_id": {"$regex": "^UNMATCHED"}})

                            if len(conds_vid_amz) == 1:
                                match_stage_amz.update(conds_vid_amz[0])
                            elif len(conds_vid_amz) > 1:
                                match_stage_amz["$or"] = conds_vid_amz
                            else:
                                match_stage_amz["payload.video_id"] = {"$in": []}
                            
                            if selected_geo_codes:
                                match_stage_amz["payload.geography"] = {"$in": selected_geo_codes}

                            pipeline_amz = [
                                {"$match": match_stage_amz},
                                {
                                    "$group": {
                                        "_id": {
                                            "video_id": "$payload.video_id",
                                            "month": "$payload.date",
                                            "platform": "$payload.platform",
                                            "geography": { "$ifNull": ["$payload.geography", "Unknown Geo"] }
                                        },
                                        "mongo_title": { "$first": "$payload.title" },
                                        "mongo_series": { "$first": { "$ifNull": ["$payload.amazon_series", "UNMATCHED_AMZ"] } },
                                        "currency": { "$first": { "$ifNull": ["$payload.currency", "USD"] } },
                                        "revenue": { "$sum": { "$ifNull": ["$payload.estimated_revenue", 0] } },
                                        "revenue_svod": { "$sum": { "$ifNull": ["$payload.extra_metrics.revenue_svod", "$payload.estimated_revenue"] } },
                                        "revenue_tvod": { "$sum": { "$ifNull": ["$payload.extra_metrics.revenue_tvod", 0] } },
                                        "views": { "$sum": { "$ifNull": ["$payload.extra_metrics.views", { "$ifNull": ["$payload.views", 0] }] } },
                                        "watch_time": { "$sum": { "$ifNull": ["$payload.extra_metrics.estimated_minutes_watched", { "$ifNull": ["$payload.watch_time", 0] }] } }
                                    }
                                }
                            ]
                        else: # "monthly"
                            coll_mongo = db_mongo['monthly_performance_summaries']
                            match_stage_amz = {
                                "_id.event_type": {"$in": ["amazon.video.performance_recorded", "amazon.video.performance_svod", "amazon.video.performance_tvod"]},
                                "_id.platform": "amazon",
                                "_id.month": {
                                    "$gte": fecha_inicio.strftime("%Y-%m"),
                                    "$lte": fecha_fin.strftime("%Y-%m")
                                }
                            }
                            conds_vid_amz = []
                            lista_video_ids_amz = df_meta_amz['video_id'].unique().tolist() if not df_meta_amz.empty else []
                            if lista_video_ids_amz:
                                conds_vid_amz.append({"_id.video_id": {"$in": lista_video_ids_amz}})
                            if not global_series and not global_seasons and not global_episodes:
                                if not global_channels or "Amazon Prime Video" in global_channels:
                                    if not global_ips or "UNMATCHED" in global_ips:
                                        conds_vid_amz.append({"_id.video_id": {"$regex": "^UNMATCHED"}})

                            if len(conds_vid_amz) == 1:
                                match_stage_amz.update(conds_vid_amz[0])
                            elif len(conds_vid_amz) > 1:
                                match_stage_amz["$or"] = conds_vid_amz
                            else:
                                match_stage_amz["_id.video_id"] = {"$in": []}
                            
                            if selected_geo_codes:
                                match_stage_amz["_id.geography"] = {"$in": selected_geo_codes}

                            pipeline_amz = [
                                {"$match": match_stage_amz},
                                {
                                    "$group": {
                                        "_id": {
                                            "video_id": "$_id.video_id",
                                            "month": "$_id.month",
                                            "platform": "$_id.platform",
                                            "geography": "$_id.geography"
                                        },
                                        "mongo_title": { "$first": "$title" },
                                        "mongo_series": { "$first": { "$ifNull": ["$series_name", "UNMATCHED_AMZ"] } },
                                        "currency": { "$first": { "$ifNull": ["$currency", "USD"] } },
                                        "revenue": { "$sum": "$monthly_revenue" },
                                        "revenue_svod": { "$sum": { "$ifNull": ["$monthly_revenue_svod", "$monthly_revenue"] } },
                                        "revenue_tvod": { "$sum": { "$ifNull": ["$monthly_revenue_tvod", 0] } },
                                        "views": { "$sum": "$monthly_views" },
                                        "watch_time": { "$sum": "$monthly_watch_time" }
                                    }
                                }
                            ]
                        
                        try:
                            mongo_data_amz = list(coll_mongo.aggregate(pipeline_amz, allowDiskUse=True))
                            flat_mongo_data_amz = []
                            for doc in mongo_data_amz:
                                amz_curr = doc.get('currency', 'USD')
                                flat_mongo_data_amz.append({
                                    'video_id': doc['_id']['video_id'],
                                    'month': doc['_id']['month'],
                                    'platform': doc['_id'].get('platform', 'amazon'),
                                    'geography': doc['_id'].get('geography', 'Unknown Geo'),
                                    'currency': amz_curr,
                                    'revenue': convert_amazon_eur_to_usd(doc.get('revenue', 0.0), currency=amz_curr),
                                    'revenue_svod': convert_amazon_eur_to_usd(doc.get('revenue_svod', 0.0), currency=amz_curr),
                                    'revenue_tvod': convert_amazon_eur_to_usd(doc.get('revenue_tvod', 0.0), currency=amz_curr),
                                    'views': doc.get('views', 0),
                                    'watch_time': round(doc.get('watch_time', 0) / 60.0, 2),
                                    'amazon_title': doc.get('mongo_title', ''),
                                    'mongo_series': doc.get('mongo_series', '')
                                })
                            df_performance_amz = pd.DataFrame(flat_mongo_data_amz)
                            if not df_performance_amz.empty:
                                if 'revenue_svod' not in df_performance_amz.columns:
                                    df_performance_amz['revenue_svod'] = 0.0
                                if 'revenue_tvod' not in df_performance_amz.columns:
                                    df_performance_amz['revenue_tvod'] = 0.0
                                mask_legacy = (
                                    (df_performance_amz['revenue'] > 0) & 
                                    (df_performance_amz['revenue_svod'] == 0) & 
                                    (df_performance_amz['revenue_tvod'] == 0)
                                )
                                if mask_legacy.any():
                                    df_performance_amz.loc[mask_legacy, 'revenue_svod'] = df_performance_amz.loc[mask_legacy, 'revenue']
                            
                            # Si es granularidad diaria, prorratear equitativamente los totales mensuales por día
                            if temp_mode == "daily" and not df_performance_amz.empty:
                                prorated_rows = []
                                cur_day = fecha_inicio
                                while cur_day <= fecha_fin:
                                    m_prefix = cur_day.strftime("%Y-%m")
                                    days_in_m = calendar.monthrange(cur_day.year, cur_day.month)[1]
                                    day_str = cur_day.strftime("%Y-%m-%d")
                                    
                                    mask_m = df_performance_amz['month'].str.startswith(m_prefix)
                                    df_day_slice = df_performance_amz[mask_m].copy()
                                    if not df_day_slice.empty:
                                        df_day_slice['month'] = day_str
                                        df_day_slice['revenue'] = df_day_slice['revenue'] / days_in_m
                                        if 'revenue_svod' in df_day_slice.columns:
                                            df_day_slice['revenue_svod'] = df_day_slice['revenue_svod'] / days_in_m
                                        if 'revenue_tvod' in df_day_slice.columns:
                                            df_day_slice['revenue_tvod'] = df_day_slice['revenue_tvod'] / days_in_m
                                        df_day_slice['views'] = df_day_slice['views'] / days_in_m
                                        df_day_slice['watch_time'] = (df_day_slice['watch_time'] / days_in_m).round(2)
                                        prorated_rows.append(df_day_slice)
                                    cur_day += timedelta(days=1)
                                df_performance_amz = pd.concat(prorated_rows, ignore_index=True) if prorated_rows else pd.DataFrame()
                        except Exception as e:
                            st.error(f"Fallo en la agregación distribuida (Amazon): {e}")
                            df_performance_amz = pd.DataFrame()
                            
                    if df_performance_amz.empty:
                        st.warning("No se encontraron registros de rendimiento de Amazon para los parámetros seleccionados.")
                    else:
                        with st.spinner("Consolidando métricas de Amazon..."):
                            
                            df_meta_amz_clean = df_meta_amz.drop(columns=['geography'], errors='ignore') if not df_meta_amz.empty else pd.DataFrame(columns=['video_id', 'ip_name', 'series_name', 'season', 'episode_number', 'episode_name', 'channel_id', 'video_title', 'video_duration'])
                            df_master_amz = pd.merge(df_performance_amz, df_meta_amz_clean, on=['video_id'], how='left')

                            # Handle UNMATCHED records for Amazon
                            mask_unm = df_master_amz['video_id'].str.startswith('UNMATCHED')
                            if mask_unm.any():
                                for col in ['ip_name', 'series_name', 'episode_name', 'video_title', 'channel_id', 'episode_number', 'amazon_title', 'match_title']:
                                    if col in df_master_amz.columns:
                                        df_master_amz[col] = df_master_amz[col].astype(object)
                                df_master_amz.loc[mask_unm, 'ip_name'] = 'UNMATCHED'
                                s_mongo_series = df_master_amz.loc[mask_unm, 'mongo_series'].fillna('')
                                s_series = np.where(s_mongo_series != '', s_mongo_series, 'UNMATCHED_AMZ')
                                df_master_amz.loc[mask_unm, 'series_name'] = s_series
                                s_mongo_title = df_master_amz.loc[mask_unm, 'amazon_title'].fillna('')
                                s_title = np.where(s_mongo_title != '', s_mongo_title, 'Unknown Title')
                                df_master_amz.loc[mask_unm, 'amazon_title'] = s_title
                                df_master_amz.loc[mask_unm, 'match_title'] = 'UNMATCHED'
                                df_master_amz.loc[mask_unm, 'episode_name'] = s_title
                                df_master_amz.loc[mask_unm, 'video_title'] = s_title
                                df_master_amz.loc[mask_unm, 'season'] = 0
                                df_master_amz.loc[mask_unm, 'episode_number'] = df_master_amz.loc[mask_unm, 'video_id']
                                df_master_amz.loc[mask_unm, 'channel_id'] = 'Amazon Prime Video'
                                df_master_amz.loc[mask_unm, 'video_duration'] = 0

                            df_master_amz.fillna({'ip_name': 'Unknown IP', 'series_name': 'Unknown Series', 'episode_name': 'Unknown Episode', 'channel_id': 'Amazon Prime Video', 'geography': 'Unknown Geo', 'season': 0, 'episode_number': 0, 'video_duration': 0}, inplace=True)
                            
                            # Garantizar que amazon_title tenga valor (usando episode_name como respaldo)
                            if 'amazon_title' not in df_master_amz.columns:
                                df_master_amz['amazon_title'] = df_master_amz['episode_name']
                            else:
                                df_master_amz['amazon_title'] = df_master_amz['amazon_title'].replace('', np.nan).combine_first(df_master_amz['episode_name']).fillna('Unknown Title')
                            
                            df_master_amz['video_title'] = df_master_amz['amazon_title']
                            df_master_amz = df_master_amz.drop(columns=['mongo_series'], errors='ignore')

                            # Cargar el título de la variante con la que hizo Match la IA y asegurar título en inglés
                            is_unm_master = (
                                df_master_amz['video_id'].astype(str).str.startswith('UNMATCHED') |
                                (df_master_amz['ip_name'].astype(str).str.upper() == 'UNMATCHED') |
                                (df_master_amz['series_name'].astype(str).str.upper() == 'UNMATCHED_AMZ')
                            )
                            df_master_amz['match_title'] = 'UNMATCHED'
                            df_master_amz.loc[is_unm_master, 'episode_name'] = df_master_amz.loc[is_unm_master, 'amazon_title']

                            matched_master_mask = ~is_unm_master
                            if matched_master_mask.any():
                                bk_title_map = load_amazon_broadkast_titles()
                                en_title_map = load_broadkast_english_titles()
                                amz_to_bkid = load_amazon_to_bkid_map()

                                sub_master = df_master_amz.loc[matched_master_mask]
                                s_bkid = np.where(
                                    sub_master['video_id'].astype(str).str.startswith('EP_'),
                                    sub_master['video_id'].astype(str),
                                    sub_master['amazon_title'].map(amz_to_bkid) if amz_to_bkid else np.nan
                                )
                                if bk_title_map:
                                    s_bk_by_vid = sub_master['video_id'].map(bk_title_map)
                                    s_bk_by_orig = sub_master['amazon_title'].map(bk_title_map)
                                    s_bk = s_bk_by_vid.combine_first(s_bk_by_orig)
                                    df_master_amz.loc[matched_master_mask, 'match_title'] = s_bk.fillna(sub_master['episode_name'])
                                else:
                                    s_bk = pd.Series(np.nan, index=sub_master.index)
                                    df_master_amz.loc[matched_master_mask, 'match_title'] = sub_master['episode_name']

                                cur_m_titles = df_master_amz.loc[matched_master_mask, 'match_title']
                                cur_amz_titles = sub_master['amazon_title']
                                cur_ep_names = sub_master['episode_name']

                                chosen_ep = [
                                    get_best_english_title(bid, m_t, a_t, en_title_map, default=def_ep)
                                    for bid, m_t, a_t, def_ep in zip(s_bkid, cur_m_titles, cur_amz_titles, cur_ep_names)
                                ]
                                df_master_amz.loc[matched_master_mask, 'episode_name'] = chosen_ep

                            # Cargar porcentaje de acierto del match de IA
                            amz_score_map = load_amazon_match_scores()
                            df_master_amz['match_score'] = df_master_amz.apply(
                                lambda r: get_title_match_score(
                                    r.get('amazon_title') or r.get('video_title'),
                                    is_unmatched=str(r.get('video_id', '')).startswith('UNMATCHED'),
                                    score_map=amz_score_map
                                ),
                                axis=1
                            )

                            # Clasificar idioma por título (con fallback al territorio)
                            df_master_amz['language_code'] = df_master_amz.apply(
                                lambda r: detect_title_language(
                                    title=r.get('amazon_title') or r.get('video_title') or r.get('episode_name'),
                                    territory=r.get('geography'),
                                    geo_to_lang=geo_to_lang
                                ),
                                axis=1
                            )

                            if selected_geo_codes:
                                df_master_amz = df_master_amz[df_master_amz['geography'].isin(selected_geo_codes)]
                            elif agg_level == "Por Territorio / País":
                                df_master_amz = df_master_amz[~df_master_amz['geography'].isin(["Global", "Unknown Geo"])]

                            if selected_lang_codes:
                                df_master_amz = df_master_amz[df_master_amz['language_code'].apply(lambda x: any(str(x).lower().startswith(l.lower()) for l in selected_lang_codes))]

                            if df_master_amz.empty:
                                st.warning("No se encontraron registros de rendimiento de Amazon que coincidan con los filtros de idioma o territorio.")
                            else:
                                # Enriquecer con Productora
                                df_master_amz['producer'] = df_master_amz.apply(
                                    lambda r: resolve_producer(r.get('amazon_title') or r.get('video_title'), r.get('series_name'), r.get('ip_name'), platform='amazon'),
                                    axis=1
                                )
                                df_master_amz['producer'] = df_master_amz['producer'].fillna('Amuse Animation')
                                if global_producers:
                                    df_master_amz = df_master_amz[df_master_amz['producer'].isin(global_producers)]
                                
                                amz_group_cols = [
                                    'month', 'producer', 'ip_name', 'series_name', 'season', 'episode_number', 
                                    'episode_name', 'amazon_title', 'match_title', 'geography', 'video_id', 
                                    'channel_id', 'platform', 'language_code', 'video_title', 'video_duration', 'match_score'
                                ]
                                amz_group_cols = [c for c in amz_group_cols if c in df_master_amz.columns]
                                amz_fin_metrics = ['revenue']
                                if 'revenue_svod' in df_master_amz.columns:
                                    amz_fin_metrics.append('revenue_svod')
                                if 'revenue_tvod' in df_master_amz.columns:
                                    amz_fin_metrics.append('revenue_tvod')
                                report_financiero_amz = df_master_amz.groupby(amz_group_cols, dropna=False)[amz_fin_metrics].sum().reset_index()
                                report_financiero_amz = report_financiero_amz.sort_values(by=['month', 'ip_name', 'series_name'])

                                report_operacional_amz = df_master_amz.groupby(amz_group_cols, dropna=False)[['views', 'watch_time']].sum().reset_index()
                                report_operacional_amz = report_operacional_amz.sort_values(by=['month', 'ip_name'])
                            
                                collected_fin.append(report_financiero_amz)
                                collected_op.append(report_operacional_amz)
                                rango_parts.append("Amazon")
                                
                        placeholder_msg_amz.success("¡Procesamiento de Amazon finalizado con éxito!")
                        st.session_state.use_amazon_executed = True

            if use_tencent:
                with st.spinner(f"Procesando pipeline de Tencent Video (MongoDB - {temp_mode_label})..."):
                    try:
                        report_fin_tcn, report_op_tcn = fetch_tencent_reports(
                            db_mongo=db_mongo,
                            temp_mode=temp_mode,
                            fecha_inicio=fecha_inicio,
                            fecha_fin=fecha_fin,
                            global_ips=global_ips,
                            global_series=global_series,
                            global_channels=global_channels,
                            global_producers=global_producers,
                            selected_geo_codes=selected_geo_codes,
                            selected_lang_codes=selected_lang_codes,
                            global_seasons=global_seasons,
                            global_episodes=global_episodes,
                        )
                        if not report_fin_tcn.empty:
                            collected_fin.append(report_fin_tcn)
                            collected_op.append(report_op_tcn)
                            rango_parts.append("Tencent")
                            placeholder_msg_tcn.success("¡Procesamiento de Tencent Video finalizado con éxito!")
                            st.session_state.use_tencent_executed = True
                        else:
                            st.warning("No se encontraron registros de rendimiento de Tencent Video que coincidan con los filtros.")
                    except Exception as e:
                        st.error(f"Error consultando Tencent Video en MongoDB: {e}")

            if use_youku:
                with st.spinner(f"Procesando pipeline de Youku (MongoDB - {temp_mode_label})..."):
                    try:
                        report_fin_yku, report_op_yku = fetch_youku_reports(
                            db_mongo=db_mongo,
                            temp_mode=temp_mode,
                            fecha_inicio=fecha_inicio,
                            fecha_fin=fecha_fin,
                            global_ips=global_ips,
                            global_series=global_series,
                            global_channels=global_channels,
                            global_producers=global_producers,
                            selected_geo_codes=selected_geo_codes,
                            selected_lang_codes=selected_lang_codes,
                            global_seasons=global_seasons,
                            global_episodes=global_episodes,
                        )
                        if not report_fin_yku.empty:
                            collected_fin.append(report_fin_yku)
                            collected_op.append(report_op_yku)
                            rango_parts.append("Youku")
                            placeholder_msg_yku.success("¡Procesamiento de Youku finalizado con éxito!")
                            st.session_state.use_youku_executed = True
                        else:
                            st.warning("No se encontraron registros de rendimiento de Youku que coincidan con los filtros.")
                    except Exception as e:
                        st.error(f"Error consultando Youku en MongoDB: {e}")

            if use_iqiyi:
                with st.spinner(f"Procesando pipeline de iQIYI (MongoDB - {temp_mode_label})..."):
                    try:
                        report_fin_iqy, report_op_iqy = fetch_iqiyi_reports(
                            db_mongo=db_mongo,
                            temp_mode=temp_mode,
                            fecha_inicio=fecha_inicio,
                            fecha_fin=fecha_fin,
                            global_ips=global_ips,
                            global_series=global_series,
                            global_channels=global_channels,
                            global_producers=global_producers,
                            selected_geo_codes=selected_geo_codes,
                            selected_lang_codes=selected_lang_codes,
                            global_seasons=global_seasons,
                            global_episodes=global_episodes,
                        )
                        if not report_fin_iqy.empty:
                            collected_fin.append(report_fin_iqy)
                            collected_op.append(report_op_iqy)
                            rango_parts.append("iQIYI")
                            placeholder_msg_iqy.success("¡Procesamiento de iQIYI finalizado con éxito!")
                            st.session_state.use_iqiyi_executed = True
                        else:
                            st.warning("No se encontraron registros de rendimiento de iQIYI que coincidan con los filtros.")
                    except Exception as e:
                        st.error(f"Error consultando iQIYI en MongoDB: {e}")

            if not collected_fin:
                st.warning("No se encontraron registros de rendimiento para las plataformas y filtros seleccionados.")
            else:
                report_fin = pd.concat(collected_fin, ignore_index=True)
                report_op = pd.concat(collected_op, ignore_index=True)
                agg_tag = "aggregated_" if consolidar_periodo else ""
                rango_str = f"{'_'.join(rango_parts)}_{temp_mode}_{agg_tag}{fecha_inicio.strftime('%Y%m%d')}_{fecha_fin.strftime('%Y%m%d')}"

                with st.spinner("Consolidando tablas y métricas analíticas..."):
                    res_multi = consolidate_multiplatform_reports(
                        report_fin,
                        report_op,
                        agg_level,
                        use_youtube=use_youtube,
                        use_amazon=use_amazon,
                        use_tencent=use_tencent,
                        use_youku=use_youku,
                        use_iqiyi=use_iqiyi,
                        consolidar_periodo=consolidar_periodo,
                        periodo_label=periodo_label,
                        display_currency=display_currency_val,
                    )
                    report_piv, df_totals = res_multi["comparative"]
                    df_yt, df_totals_yt = res_multi["youtube"]
                    df_amz, df_totals_amz = res_multi["amazon"]
                    df_tcn, df_totals_tcn = res_multi["tencent"]
                    df_yku, df_totals_yku = res_multi["youku"]
                    df_iqy, df_totals_iqy = res_multi["iqiyi"]

                st.session_state.ready_report_piv = report_piv
                st.session_state.ready_df_yt = df_yt
                st.session_state.ready_df_amz = df_amz
                st.session_state.ready_df_tcn = df_tcn
                st.session_state.ready_df_yku = df_yku
                st.session_state.ready_df_iqy = df_iqy
                st.session_state.ready_df_totals = df_totals
                st.session_state.ready_df_totals_yt = df_totals_yt
                st.session_state.ready_df_totals_amz = df_totals_amz
                st.session_state.ready_df_totals_tcn = df_totals_tcn
                st.session_state.ready_df_totals_yku = df_totals_yku
                st.session_state.ready_df_totals_iqy = df_totals_iqy
                st.session_state.rango_ejecutado = rango_str
                st.session_state.filtros_aplicados = filtros_dict
                st.session_state.ready_report_generated = True

    if st.session_state.get("ready_report_generated", False):
        f = st.session_state.filtros_aplicados
        use_yt = f.get('use_youtube', True)
        use_amz = f.get('use_amazon', False)
        use_tcn = f.get('use_tencent', False)
        use_yku = f.get('use_youku', False)
        use_iqy = f.get('use_iqiyi', False)
        num_platforms = sum([bool(use_yt), bool(use_amz), bool(use_tcn), bool(use_yku), bool(use_iqy)])
        has_comparative_tab = num_platforms >= 2
        success_msg = "¡Tablas generadas correctamente!" if has_comparative_tab else "¡Tabla generada correctamente!"

        if not submitted:
            if st.session_state.get("use_youtube_executed", False):
                placeholder_msg_yt.success("¡Procesamiento de Youtube finalizado con éxito!")
            if st.session_state.get("use_amazon_executed", False):
                placeholder_msg_amz.success("¡Procesamiento de Amazon finalizado con éxito!")
            if st.session_state.get("use_tencent_executed", False):
                placeholder_msg_tcn.success("¡Procesamiento de Tencent Video finalizado con éxito!")
            if st.session_state.get("use_youku_executed", False):
                placeholder_msg_yku.success("¡Procesamiento de Youku finalizado con éxito!")
            if st.session_state.get("use_iqiyi_executed", False):
                placeholder_msg_iqy.success("¡Procesamiento de iQIYI finalizado con éxito!")
            if st.session_state.get("use_tablas_executed", False):
                placeholder_msg_tablas.success(success_msg)

        with results_placeholder.container():
            st.markdown("---")
            st.subheader("Visualización y Descarga de Reportes Generados", anchor=False)
            
            disp_curr = f.get('display_currency', 'USD')
            curr_sym = "€" if disp_curr == "EUR" else "$"
            curr_lbl = "EUR (€)" if disp_curr == "EUR" else "USD ($)"
            curr_fmt = f"{curr_sym}%,.2f"
            curr_fmt_cph = f"{curr_sym}%,.4f"

            if f.get('temp_mode') == 'yearly':
                fechas_str = f"{f['fecha_inicio'].strftime('%Y')} a {f['fecha_fin'].strftime('%Y')}" if f['fecha_inicio'].strftime('%Y') != f['fecha_fin'].strftime('%Y') else f"{f['fecha_inicio'].strftime('%Y')}"
            elif f.get('temp_mode') == 'monthly':
                fechas_str = f"{f['fecha_inicio'].strftime('%Y-%m')} a {f['fecha_fin'].strftime('%Y-%m')}"
            else:
                fechas_str = f"{f['fecha_inicio'].strftime('%Y-%m-%d')} a {f['fecha_fin'].strftime('%Y-%m-%d')}"
            filtros_texto = f"**Filtros aplicados a estos datos:** 📅 {fechas_str}"
            filtros_texto += f" | 💱 **Divisa:** {curr_lbl}"
            filtros_texto += f" | 📊 **Granularidad:** {f.get('granularidad', 'Por Meses')} (`{f.get('coleccion', 'monthly_performance_summaries')}`)"
            filtros_texto += f" | 📦 **Modo temporal:** {'Consolidado (Agregado del periodo)' if f.get('consolidar_periodo') else 'Desglosado temporalmente'}"
            if f.get('producers'): filtros_texto += f" | 🏢 **Productora:** {', '.join(f['producers'])}"
            if f.get('ips'): filtros_texto += f" | **IPs:** {', '.join(f['ips'])}"
            if f.get('series'): filtros_texto += f" | **Series:** {', '.join(f['series'])}"
            if f.get('seasons'): filtros_texto += f" | **Temporadas:** {', '.join(map(str, f['seasons']))}"
            if f.get('episodes'): filtros_texto += f" | **Episodios:** {', '.join(map(str, f['episodes']))}"
            if f.get('idiomas'): filtros_texto += f" | **Idiomas:** {', '.join(f['idiomas'])}"
            if f.get('territorios'): filtros_texto += f" | **Territorios:** {', '.join(f['territorios'])}"
            st.info(filtros_texto)
            if f.get('temp_mode') == 'daily' and use_amz:
                st.info("ℹ️ **Aviso sobre Granularidad Diaria y Prorrateo de Amazon:** Los registros de YouTube reflejan métricas diarias reales. Dado que Amazon Prime Video emite liquidaciones financieras de regalías de forma mensual, en la vista por días sus ingresos y métricas agregadas se distribuyen de forma lineal equitativa entre los días de cada mes (1/N días) para permitir una comparación justa, equilibrada y homogénea con YouTube.")
            if f.get('temp_mode') == 'daily' and use_yt and (f.get('agg_level') == "Por Territorio / País" or bool(f.get('territorios'))):
                st.warning("⚠️ **Aviso sobre Territorio en Vista Diaria (YouTube):** El análisis por días de YouTube no incluye desglose por territorio/país (las métricas analíticas diarias de Google se recopilan a nivel mundial consolidado del vídeo: `Global (Mundial)`). Para consultar métricas y facturación con desglose geográfico de consumo por país, seleccione la granularidad **Por Meses** o **Por Años**.")
            if (f.get('agg_level') == "Por Territorio / País" or bool(f.get('territorios'))) and use_yt and f.get('temp_mode') in ['monthly', 'yearly']:
                st.info("ℹ️ **Métricas de YouTube en Vista Territorial:** Los ingresos y la publicidad por país reflejan el desglose territorial ponderado por el CPM real de cada territorio, garantizando total coherencia contable con el total mundial del vídeo y valorando adecuadamente las visualizaciones según el mercado publicitario de cada país.")
            if (f.get('agg_level') == "Por Territorio / País" or bool(f.get('territorios'))) and use_yt and f['fecha_inicio'] < datetime(2023, 1, 1):
                st.warning("⚠️ **Aviso Histórico de Territorios en YouTube (2016–2022):** La recopilación analítica con desglose por país del espectador en YouTube comenzó a registrarse a partir de **enero de 2023**. Para el histórico anterior (2016–2022), las métricas oficiales de YouTube están registradas únicamente a nivel consolidado mundial (`Global`). Por ello, en vistas territoriales YouTube refleja $0 en esos años antiguos. Para auditar la facturación global de 2016–2022, seleccione la vista **Por Propiedad Intelectual (IP)**, **Por Serie** o **Episodio Canónico**.")
            if use_yt and f['fecha_inicio'] < datetime(2016, 4, 1):
                st.caption("ℹ️ **Aviso Histórico YouTube:** Para fechas anteriores a abril de 2016 existen metadatos de vídeos publicados en catálogo, pero la recolección de métricas analíticas e ingresos publicitarios comenzó en abril de 2016.")
            if use_amz and f['fecha_inicio'] < datetime(2016, 9, 1):
                st.caption("ℹ️ **Aviso Histórico Amazon Prime Video:** Las regalías y métricas oficiales de Amazon Prime Video comenzaron a registrarse a partir de **septiembre de 2016**. Los periodos anteriores a dicha fecha no disponen de liquidaciones ni streaming en la plataforma.")
            if use_amz:
                st.info("ℹ️ **Métricas de Amazon Prime Video (Watch Time, Views y CPH):** En Amazon Prime Video los ingresos de Prime (SVOD) se liquidan por **horas reproducidas (Watch Time)** mediante tarifa horaria (CPH), mientras que TVOD liquida por transacciones directas. La base de datos integra la telemetría oficial de streaming (*Unique Streams* y minutos de visualización) y liquidaciones desde **septiembre de 2016** de forma continua, unificadas al 100% en **USD ($)**.")
            if use_tcn:
                st.caption("ℹ️ **Aviso Histórico Tencent Video:** Datos oficiales **AVOD** disponibles de **ene 2018 a dic 2023** (a nivel de canal `CHANNEL_LEVEL`) y **SVOD** por serie de **mar 2021 a feb 2025**. Los importes originales en yuanes (RMB ¥) se convierten a USD utilizando la tasa media anual oficial de cada año.")
            if use_yku:
                st.caption("ℹ️ **Aviso Histórico Youku:** Canales propios **DaYu Platform** (`CARCITY` y `LEARN_TV`, **mar 2017 – may 2023**) con ingresos y consumo diarios nativos, más catálogo **Open Platform** por serie (**ene 2020 – ene 2025** AVOD/SVOD). En granularidad diaria, los ingresos mensuales de *Open Platform* se prorratean equitativamente por día (1/N días).")
            if use_iqy:
                st.caption("ℹ️ **Aviso Histórico iQIYI:** Cuentas **Amuse CC (2463347304)**, **Amuse LTV / France (2484062153)** y **Amuse Shanghai (4318775981759616)** (**2017–ene 2026**). Incluye AVOD diario, SVOD por serie/IP (**2017–jun 2024** con horas VIP de **feb 2022–jun 2024**) y totales de canal recientes (**jul 2024–ene 2026**).")
            macro_aggs = ["Por Propiedad Intelectual (IP)", "Por Serie", "Por Serie / IP (Comparativa Multiplataforma)"]
            if (use_tcn or use_yku or use_iqy) and has_comparative_tab and f.get('agg_level') not in macro_aggs:
                st.info("ℹ️ **Plataformas Chinas en Vistas de Episodio/Vídeo:** Tencent Video, Youku e iQIYI reportan históricamente por serie o canal, sin identificadores de episodio individual. Por ello, sus cifras se contabilizan íntegramente en **Totales Globales Comparativos** y en sus pestañas individuales, mientras que la tabla de detalle por episodio muestra YouTube/Amazon. Para comparar **YouTube vs Amazon vs Tencent vs Youku vs iQIYI** fila a fila, seleccione **\"Por Propiedad Intelectual (IP)\"** o **\"Por Serie\"**.")
            if (use_tcn or use_yku or use_iqy) and f.get('agg_level') in macro_aggs:
                with st.expander("ℹ️ **Guía de Estructura: Series Canónicas vs Paquetes Temáticos y Canales en China**", expanded=False):
                    st.markdown("""
                    **¿Cómo se distribuye y estructura el contenido en China (iQIYI, Tencent, Youku)?**
                    
                    A diferencia de YouTube y Amazon (que reportan episodios individuales estándar), en las plataformas chinas el catálogo se comercializó bajo 3 modalidades:
                    
                    * 🎬 **Series Canónicas (Tencent SVOD y Youku Open):** Coinciden 1:1 con las series tradicionales del estudio (`CAR_PATROL`, `TINY_TRUCKS`, `DINO_THE_DINOSAUR`, `ROBOFUSE`, `ANIMACARS`).
                    * 📦 **Paquetes Temáticos y Educativos (Especialidad iQIYI SVOD):** En iQIYI el catálogo se licenció en álbumes cerrados de educación infantil y valores (*Edutainment*):
                      - *Car City:* `CARCITY_SVOD_SELF_PROTECTION` (*Autoprotección y seguridad*), `CARCITY_SVOD_CONSTRUCTION` (*Construcción e ingeniería*), `CARCITY_SVOD_OLYMPIC` (*Especial deportivo*), `CARCITY_SVOD_TRANSFORMATIONS` (*Transformaciones de Carl*), etc.
                      - *Learn TV / Tiny World:* `TINY_SVOD_SPACE_CREATIVITY` (*Creatividad espacial con Tiny Trucks*), `DINO_SVOD_COGNITION` (*Desarrollo cognitivo con Dino*).
                      - *Nota contable:* Cada uno de estos paquetes tiene asignada internamente su IP correspondiente (`CARCITY`, `TINY_WORLD`, `LEARN_TV`), sumando íntegramente a su franquicia.
                    * 📺 **Emisiones de Canal Abierto (AVOD):**
                      - `CARCITY_IQIYI_CHANNEL` (iQIYI) y `CARCITY_DAYU_CHANNEL` (Youku DaYu): Emisión continua de todo el catálogo de Car City en abierto; los ingresos publicitarios se liquidan a nivel global de canal sin desglose por show individual.
                      - `CHANNEL_LEVEL`: Ingresos publicitarios que aplican a todo el canal corporativo de Tencent (2018–2023) sin desglose por show individual.
                    
                    💡 **Consejo de Análisis:**
                    - Seleccione **"Por Propiedad Intelectual (IP)"** para una vista ejecutiva macro: 1 sola fila por franquicia sumando YouTube + Amazon + todas las modalidades de China.
                    - Seleccione **"Por Serie"** para auditar y comparar show a show (series canónicas, álbumes temáticos SVOD y canales AVOD).
                    """)

            report_piv = st.session_state.ready_report_piv
            df_yt = st.session_state.ready_df_yt
            df_amz = st.session_state.ready_df_amz
            df_tcn = st.session_state.get("ready_df_tcn", pd.DataFrame())
            df_yku = st.session_state.get("ready_df_yku", pd.DataFrame())
            df_iqy = st.session_state.get("ready_df_iqy", pd.DataFrame())
            df_totals = st.session_state.ready_df_totals
            df_totals_yt = st.session_state.ready_df_totals_yt
            df_totals_amz = st.session_state.ready_df_totals_amz
            df_totals_tcn = st.session_state.get("ready_df_totals_tcn", pd.DataFrame())
            df_totals_yku = st.session_state.get("ready_df_totals_yku", pd.DataFrame())
            df_totals_iqy = st.session_state.get("ready_df_totals_iqy", pd.DataFrame())
            
            mode = f.get('temp_mode', 'monthly')
            if f.get('consolidar_periodo'):
                time_header = "Periodo"
                time_help = "Periodo acumulado consolidado"
            elif mode == 'yearly':
                time_header = "Año"
                time_help = "Año del registro (YYYY)"
            elif mode == 'daily':
                time_header = "Fecha / Día"
                time_help = "Fecha diaria del registro (YYYY-MM-DD). Para Amazon los importes e indicadores en vista diaria representan la distribución proporcional de la liquidación mensual."
            else:
                time_header = "Mes"
                time_help = "Mes del registro (YYYY-MM)"

            col_tooltips = {
                "month": st.column_config.Column(time_header, help=time_help),
                "video_id": st.column_config.Column("ID", help="Identificador único del vídeo en la plataforma"),
                "language_code": st.column_config.Column("Idioma", help="Idioma del vídeo o idioma predominante del territorio"),
                "producer": st.column_config.Column("Productora 🧮", help="🧮 Clasificación calculada en código: Productora asignada (Amuse Animation para producciones propias, o el estudio correspondiente para distribución externa)"),
                "ip_name": st.column_config.Column("IP", help="Propiedad Intelectual (IP) del catálogo Broadkast (o `CHANNEL_LEVEL` para AVOD sin desglose)"),
                "series_name": st.column_config.Column("Serie", help="Nombre de la serie canónica en Broadkast (o paquete temático/canal en plataformas chinas, ej: CARCITY_SVOD_... o _CHANNEL)"),
                "season": st.column_config.Column("Season", help="Temporada de la serie"),
                "episode_number": st.column_config.Column("Episode", help="Número de episodio canónico"),
                "episode_name": st.column_config.Column("Episode Name/Title", help="Título del vídeo o episodio canónico"),
                "channel_id": st.column_config.Column("Channel", help="Identificador del canal en la plataforma"),
                "geography": st.column_config.Column("Territorio", help="Región o país donde se consumió el contenido (territorio del espectador reportado por las plataformas)"),
                "revenue": st.column_config.NumberColumn(f"Revenue ({curr_lbl})", help=f"Ingresos totales estimados ({curr_lbl}) reportados por la plataforma", format=curr_fmt),
                "revenue_svod": st.column_config.NumberColumn(f"Revenue SVOD ({curr_lbl}) 🧮", help=f"🧮 Regalías devengadas por consumo bajo suscripción ({curr_lbl}).", format=curr_fmt),
                "revenue_tvod": st.column_config.NumberColumn(f"Revenue TVOD ({curr_lbl}) 🧮", help=f"🧮 Ingresos devengados por compras y alquileres transaccionales a la carta ({curr_lbl}).", format=curr_fmt),
                "revenue_avod": st.column_config.NumberColumn(f"Revenue AVOD ({curr_lbl}) 🧮", help=f"🧮 Ingresos publicitarios bajo modelo AVOD ({curr_lbl}).", format=curr_fmt),
                "revenue_cny": st.column_config.NumberColumn("Revenue Original (RMB ¥)", help="Importe original liquidado en yuanes chinos (RMB / CNY) antes de convertir a USD/EUR.", format="¥%,.2f"),
                "revenue_amazon": st.column_config.NumberColumn(f"Revenue Amazon ({curr_lbl})", help=f"Ingresos totales de regalías de Amazon Prime Video expresados en {curr_lbl}.", format=curr_fmt),
                "revenue_youtube": st.column_config.NumberColumn(f"Revenue YouTube ({curr_lbl}) ℹ️", help=f"Ingresos estimados de partner de YouTube expresados en {curr_lbl}.", format=curr_fmt),
                "revenue_tencent": st.column_config.NumberColumn(f"Revenue Tencent ({curr_lbl}) 🧮", help=f"🧮 Ingresos estimados en {curr_lbl} de Tencent Video (SVOD + AVOD), convertidos desde RMB (¥).", format=curr_fmt),
                "revenue_youku": st.column_config.NumberColumn(f"Revenue Youku ({curr_lbl}) 🧮", help=f"🧮 Ingresos estimados en {curr_lbl} de Youku (DaYu + Open Platform), convertidos desde RMB (¥).", format=curr_fmt),
                "revenue_iqiyi": st.column_config.NumberColumn(f"Revenue iQIYI ({curr_lbl}) 🧮", help=f"🧮 Ingresos estimados en {curr_lbl} de iQIYI (Amuse CC + LTV/France + Shanghai), convertidos desde RMB (¥).", format=curr_fmt),
                "total_revenue": st.column_config.NumberColumn(f"Total Revenue ({curr_lbl})", help=f"Suma combinada de ingresos en {curr_lbl} de las plataformas seleccionadas.", format=curr_fmt),
                "views": st.column_config.NumberColumn("Views", help="Número total de visualizaciones reportadas directamente por la plataforma", format="%,d"),
                "views_amazon": st.column_config.NumberColumn("Views Amazon ℹ️", help="Visualizaciones en Amazon Prime Video. Refleja las reproducciones reales de streaming de suscriptores Prime (Unique Streams) junto con las compras y alquileres transaccionales directos (TVOD) desde septiembre de 2016 de forma continua.", format="%,d"),
                "views_youtube": st.column_config.NumberColumn("Views YouTube ℹ️", help="Visualizaciones reportadas sobre los vídeos activos en catálogo en YouTube. Nota: Los ingresos (Revenue) concilian al 100% con el CMS oficial; las visualizaciones presentan una variación natural mínima (<1% en 2025) debida a vídeos históricos despublicados o eliminados.", format="%,d"),
                "views_tencent": st.column_config.NumberColumn("Views Tencent", help="Visualizaciones totales reportadas en Tencent Video (SVOD por serie + AVOD a nivel canal).", format="%,d"),
                "views_youku": st.column_config.NumberColumn("Views Youku", help="Visualizaciones totales reportadas en Youku (DaYu canales CC/LTV + Open Platform por serie).", format="%,d"),
                "views_iqiyi": st.column_config.NumberColumn("Views iQIYI", help="Visualizaciones totales reportadas en iQIYI (Amuse CC + Amuse LTV por serie y canal).", format="%,d"),
                "total_views": st.column_config.NumberColumn("Total Views ℹ️", help="Suma combinada de visualizaciones de las plataformas seleccionadas.", format="%,d"),
                "watch_time": st.column_config.NumberColumn("Watch Time (hrs)", help="Tiempo total de visualización (en horas) reportado por la plataforma", format="%,.2f"),
                "watch_time_amazon": st.column_config.NumberColumn("Watch Time Amazon (hrs) 🧮", help="Tiempo total de reproducción en Amazon Prime Video (en horas). Ésta es la métrica principal sobre la que Amazon calcula y liquida los ingresos de los creadores (vía tarifa horaria CPH Rate), tanto en el catálogo histórico como actual.", format="%,.2f"),
                "watch_time_youtube": st.column_config.NumberColumn("Watch Time YouTube (hrs) ℹ️", help="Tiempo total de visualización en YouTube (en horas) medido sobre el catálogo activo. Nota: Los ingresos concilian al 100% con la liquidación bancaria del CMS; el tiempo de reproducción refleja el consumo del catálogo activo (variación <1.7% en 2025 debida a vídeos históricos eliminados).", format="%,.2f"),
                "watch_time_youku": st.column_config.NumberColumn("Watch Time Youku (hrs)", help="Tiempo total de visualización reportado en Youku Open Platform SVOD (en horas).", format="%,.2f"),
                "watch_time_iqiyi": st.column_config.NumberColumn("Watch Time iQIYI (hrs)", help="Horas de consumo VIP de pago reportadas en iQIYI SVOD (feb 2022 – jun 2024).", format="%,.2f"),
                "total_watch_time": st.column_config.NumberColumn("Total Watch Time (hrs) 🧮", help="Tiempo de visualización total combinado en horas de las plataformas con medición de tiempo.", format="%,.2f"),
                "cpm": st.column_config.NumberColumn(f"CPM (Neto) ({curr_lbl}) 🧮", help=f"🧮 Métrica calculada en código: CPM Neto del Partner ({curr_lbl}). Ingresos publicitarios netos percibidos por Amuse por cada 1.000 impresiones de anuncios (tras deducir el 45% de YouTube). Fórmula: (Ad Revenue / Ad Impressions) * 1.000.", format=curr_fmt),
                "cph_rate": st.column_config.NumberColumn(f"CPH Rate (SVOD) ({curr_lbl}) 🧮", help=f"🧮 Tasa efectiva por hora de streaming en Amazon Prime Video (SVOD) en {curr_lbl}. Fórmula: Revenue SVOD / Watch Time (hrs). Excluye compras TVOD.", format=curr_fmt_cph),
                "avg_view_minutes": st.column_config.NumberColumn("Avg Min/View 🧮", help="🧮 Métrica calculada en código: Tiempo promedio de visualización por reproducción en minutos en Amazon Prime Video. Fórmula: (Watch Time (hrs) * 60) / Views.", format="%,.2f"),
                "ad_revenue": st.column_config.NumberColumn(f"Ad Revenue ({curr_lbl})", help=f"Ingresos publicitarios netos de partner ({curr_lbl}) reportados por YouTube (tras deducir la comisión del 45% de Google)", format=curr_fmt),
                "ad_impressions": st.column_config.NumberColumn("Ad Impressions", help="Número de impresiones de anuncios mostrados reportadas directamente por YouTube", format="%,d"),
                "likes": st.column_config.NumberColumn("Likes", help="Número de 'Me gusta' reportados por la plataforma", format="%,d"),
                "comments": st.column_config.NumberColumn("Comments", help="Número de comentarios reportados por la plataforma", format="%,d"),
                "num_versiones_totales": st.column_config.NumberColumn("Total Versiones 🧮", help="🧮 Métrica calculada en código: Número total de vídeos y publicaciones únicas vinculadas a este episodio canónico en el catálogo.", format="%,d"),
                "num_versiones": st.column_config.NumberColumn("Nº Idiomas 🧮", help="🧮 Métrica calculada en código: Número de idiomas distintos disponibles con episodio estándar (excluyendo recopilaciones y resubidas).", format="%,d"),
                "num_publicaciones": st.column_config.NumberColumn("Republicaciones 🧮", help="🧮 Métrica calculada en código: Número de publicaciones adicionales para este episodio (republicaciones en el mismo idioma + recopilaciones/maratones + shorts).", format="%,d"),
                "is_compilation": st.column_config.CheckboxColumn("Compilación 🧮", help="🧮 Clasificación calculada en código: Determinado automáticamente mediante análisis de palabras clave en el título y duración (> 30 min o +10 min respecto al episodio estándar)."),
                "is_short": st.column_config.CheckboxColumn("Short 🧮", help="🧮 Clasificación calculada en código: Determinado automáticamente si la duración es ≤ 60 segundos o si el título contiene la etiqueta #shorts."),
                "platform": st.column_config.Column("Platform", help="Plataforma de distribución (YouTube, Amazon Prime Video, Tencent Video, Youku o iQIYI)"),
                "subplatform": st.column_config.Column("Subplataforma", help="Origen o cuenta dentro de la plataforma china (p. ej. DaYu / Open Platform en Youku, o Amuse CC / LTV / Shanghai en iQIYI)"),
                "monetization_model": st.column_config.Column("Modelo", help="Modelo de monetización (SVOD, AVOD, MIXED o AVOD+SVOD)"),
                "platform_title": st.column_config.Column("Nombre Episodio en la Plataforma", help="Título del vídeo o episodio publicado en la plataforma"),
                "youtube_url": st.column_config.LinkColumn("YouTube URL 🧮", help="🧮 Enlace generado en código: Enlace directo al vídeo en YouTube construido a partir de su ID.")
            }

            col_tooltips_comp = dict(col_tooltips)
            if f.get('agg_level') == "Por Vídeo/Versión (Mostrar resubidas)":
                col_tooltips_comp["episode_name"] = st.column_config.Column("Nombre Episodio (Broadkast)", help="Título canónico original del episodio en Broadkast (Inglés)")
                col_tooltips_comp["platform_title"] = st.column_config.Column("Nombre Episodio en la Plataforma", help="Título del vídeo o episodio publicado en la plataforma")
                col_tooltips_comp["youtube_url"] = st.column_config.LinkColumn("URL 🧮", help="🧮 Enlace generado en código: Enlace directo al vídeo en YouTube (en blanco para vídeos de Amazon)")
            else:
                col_tooltips_comp["episode_name"] = st.column_config.Column("Episodio Canónico (Broadkast)", help="Título canónico original del episodio en Broadkast (versión original en inglés)")

            col_tooltips_yt = dict(col_tooltips)
            col_tooltips_yt["episode_name"] = st.column_config.Column("Título del Vídeo / Episodio", help="Título del vídeo o episodio canónico en YouTube")

            col_tooltips_amz = dict(col_tooltips)
            col_tooltips_amz.pop("is_short", None)
            col_tooltips_amz["amazon_title"] = st.column_config.Column("Título en Amazon", help="Título original y localizado registrado en Amazon Prime Video")
            col_tooltips_amz["match_title"] = st.column_config.Column("Título Match 🧮", help="🧮 Título o variante de catálogo con la que la IA encontró la coincidencia semántica")
            col_tooltips_amz["episode_name"] = st.column_config.Column("Episodio Broadkast original 🧮", help="🧮 Título canónico de producción en Broadkast en su versión original (Inglés)")
            col_tooltips_amz["revenue"] = st.column_config.NumberColumn(f"Revenue Total ({curr_lbl})", help=f"Suma combinada de ingresos en {curr_lbl} de Amazon Prime Video (Revenue SVOD + Revenue TVOD).", format=curr_fmt)
            col_tooltips_amz["revenue_svod"] = st.column_config.NumberColumn(f"Revenue SVOD (Prime) ({curr_lbl}) 🧮", help=f"🧮 Regalías devengadas por consumo de suscriptores Prime en {curr_lbl}.", format=curr_fmt)
            col_tooltips_amz["revenue_tvod"] = st.column_config.NumberColumn(f"Revenue TVOD (Ventas) ({curr_lbl}) 🧮", help=f"🧮 Ingresos devengados por compras y alquileres transaccionales a la carta en {curr_lbl}.", format=curr_fmt)
            col_tooltips_amz["is_compilation"] = st.column_config.CheckboxColumn("Compilación 🧮", help="🧮 Clasificación calculada en código: Indica si el vídeo en Amazon es una compilación o maratón multiepisodio.")
            col_tooltips_amz["num_publicaciones"] = st.column_config.NumberColumn("Republicaciones 🧮", help="🧮 Métrica calculada en código: Número de publicaciones adicionales para este episodio (republicaciones en el mismo idioma + recopilaciones/maratones).", format="%,d")
            col_tooltips_amz["match_score"] = st.column_config.NumberColumn("Acierto Match IA 🧮", help="🧮 Métrica de confianza calculada por el motor de reconciliación semántica e IA (Exacto = 100%, IA Semántica = % similitud de embeddings, UNMATCHED = 0%).", format="%.1f%%")

            col_tooltips_tcn = dict(col_tooltips)
            col_tooltips_tcn["revenue"] = st.column_config.NumberColumn(f"Revenue Total ({curr_lbl}) 🧮", help=f"🧮 Ingresos totales estimados en {curr_lbl} convertidos desde RMB (¥) según tipo de cambio.", format=curr_fmt)
            col_tooltips_tcn["revenue_svod"] = st.column_config.NumberColumn(f"Revenue SVOD ({curr_lbl}) 🧮", help=f"🧮 Ingresos por suscripción SVOD en {curr_lbl} (desglosados por IP y Serie).", format=curr_fmt)
            col_tooltips_tcn["revenue_avod"] = st.column_config.NumberColumn(f"Revenue AVOD ({curr_lbl}) 🧮", help=f"🧮 Ingresos publicitarios AVOD en {curr_lbl} (agregados a nivel de canal `CHANNEL_LEVEL`).", format=curr_fmt)

            col_tooltips_yku = dict(col_tooltips_tcn)
            col_tooltips_yku["revenue_avod"] = st.column_config.NumberColumn(f"Revenue AVOD ({curr_lbl}) 🧮", help=f"🧮 Ingresos AVOD en {curr_lbl} (DaYu canales CC/LTV + Open Platform por serie).", format=curr_fmt)

            col_tooltips_iqy = dict(col_tooltips_tcn)
            col_tooltips_iqy["revenue_avod"] = st.column_config.NumberColumn(f"Revenue AVOD ({curr_lbl}) 🧮", help=f"🧮 Ingresos AVOD en {curr_lbl} (Amuse CC, LTV y Shanghai).", format=curr_fmt)
            col_tooltips_iqy["watch_time"] = st.column_config.NumberColumn("Watch Time VIP (hrs)", help="Horas de consumo VIP de pago SVOD (有效付费时长（时）, feb 2022 – jun 2024).", format="%,.2f")

            col_tooltips_comp_totals = dict(col_tooltips_comp)
            col_tooltips_comp_totals["is_short"] = st.column_config.Column("Short 🧮", help="🧮 Clasificación calculada en código")
            col_tooltips_comp_totals["is_compilation"] = st.column_config.Column("Compilación 🧮", help="🧮 Clasificación calculada en código")

            col_tooltips_yt_totals = dict(col_tooltips_yt)
            col_tooltips_yt_totals["is_short"] = st.column_config.Column("Short 🧮", help="🧮 Clasificación calculada en código")
            col_tooltips_yt_totals["is_compilation"] = st.column_config.Column("Compilación 🧮", help="🧮 Clasificación calculada en código")

            col_tooltips_amz_totals = dict(col_tooltips_amz)
            col_tooltips_amz_totals.pop("is_short", None)
            col_tooltips_amz_totals["is_compilation"] = st.column_config.Column("Compilación 🧮", help="🧮 Clasificación calculada en código")

            col_tooltips_tcn_totals = dict(col_tooltips_tcn)
            col_tooltips_yku_totals = dict(col_tooltips_yku)
            col_tooltips_iqy_totals = dict(col_tooltips_iqy)

            def _get_totals_caption(filtros, df_tot):
                if len(df_tot) <= 1:
                    return ""
                mode = filtros.get('temp_mode', 'monthly')
                if mode == 'daily':
                    detail = "Para facilitar el análisis en datos diarios, los subtotales se agrupan por **Mes**"
                elif mode == 'monthly':
                    detail = "Se desglosa el subtotal de cada **Mes**"
                else:
                    detail = "Se desglosa el subtotal de cada **Año**"
                caption = f"💡 **Aclaración sobre los Totales:** La primera fila muestra el **Total Global** consolidado del periodo seleccionado, seguido del desglose de subtotales ({detail}) para permitir un análisis claro de la evolución temporal."
                if filtros.get('use_amazon', False):
                    caption += " | ℹ️ **Nota sobre Amazon:** Ingresos 100% unificados en USD ($). Las visualizaciones integran las reproducciones de streaming (*Unique Streams*) y compras directas (TVOD) desde septiembre de 2016."
                return caption

            def _render_comp():
                fn_comp_xlsx = generate_export_filename(f, table_type="comparative", platform_override=None, ext="xlsx")
                fn_comp_csv = generate_export_filename(f, table_type="comparative", platform_override=None, ext="csv")
                st.markdown("##### Reporte Consolidado (Revenue, Views & Watch Time)", anchors=False)
                st.caption("💡 **Nota:** Las columnas marcadas con el símbolo **🧮** contienen datos calculados o consolidados en código. Pasa el cursor sobre el encabezado de la columna para ver la fórmula y explicación.")
                if not df_totals.empty:
                    with st.expander("ℹ️ **Auditoría de Métricas: Conciliación de Ingresos (CMS) y Consumo de Catálogo (Views / Watch Time)**", expanded=False):
                        st.markdown("""
                        * **Ingresos (Revenue) Conciliados al 100%:** Los ingresos reflejan la facturación contable oficial auditada con las liquidaciones del CMS de YouTube, los informes de Amazon y los reportes oficiales históricos de Tencent Video (RMB ¥ convertidos con tasa media anual a USD).
                        * **CPM Neto vs CPM Bruto (YouTube):** La columna *CPM (Neto)* refleja los ingresos publicitarios reales percibidos por Amuse por cada 1.000 impresiones tras deducir el 45% de YouTube ($0,77 en 2025). El CPM Bruto de YouTube Studio/CMS ($1,38) representa lo que pagan los anunciantes antes de la comisión (CPM Bruto = CPM Neto / 0,55, con una conciliación contable del 98,6%).
                        * **Visualizaciones y Tiempo de Visualización (Views y Watch Time en YouTube):** Representan el consumo real medido sobre los vídeos activos que componen el catálogo actual. Existe una variación natural mínima (apenas un **0,7% en 2025** y ~4,7% en 2024) respecto a los agregados globales del CMS, debida a vídeos históricos que generaron ingresos pero fueron posteriormente despublicados, eliminados o desvinculados del catálogo.
                        * **Amazon Prime Video (Horas Vistas, Unique Streams y CPH Rate):** Cobertura histórica continua desde **septiembre de 2016 hasta octubre de 2026** (122 meses). Los ingresos SVOD se liquidan por **tiempo total reproducido (tarifa horaria CPH)** y TVOD por compras directas, todos unificados en **USD ($)**. Las visualizaciones integran la telemetría oficial de streaming (*Unique Streams*) de suscriptores Prime y compras directas a lo largo de todo el periodo.
                        * **Tencent Video (SVOD por Serie vs AVOD de Canal):** El catálogo SVOD en Tencent incluye métricas por serie/IP (`SHARK_ACADEMY`, `INCREDITALES`, `ANIMACARS`, `CARCITY_SUPER`, `SUPERS`), mientras que AVOD se liquidaba únicamente a nivel agregado de canal (`CHANNEL_LEVEL`). Tencent no incluye métrica de *Watch Time*.
                        * **Youku (DaYu + Open Platform):** Reúne los canales propios **DaYu** (`CARCITY` y `LEARN_TV`, diarios) y las series licenciadas **Open Platform** (AVOD/SVOD por serie/IP, con horas vistas SVOD). Las cifras chinas originales en RMB (¥) se convierten a USD mediante tasa media anual.
                        * **iQIYI (Amuse CC, LTV / France y Shanghai):** Integra ingresos AVOD diarios por canal, SVOD por serie/IP reconciliados sin duplicidades (`2017–jun 2024`, con horas VIP de **feb 2022–jun 2024**), SVOD de canal (`jul 2024–ene 2026`) y visualizaciones por serie (`oct 2017–jul 2024`) + canal inicial (`feb–oct 2017`). Importes en RMB (¥) convertidos a USD con tasa media anual.
                        """)
                    if len(df_totals) > 1:
                        st.markdown("**Totales Globales y Desglose Temporal:**")
                        st.caption(_get_totals_caption(f, df_totals))
                    else:
                        header_tot = "**Totales Globales por Plataforma:**" if len(df_totals) > 1 else "**Fila de Totales Globales:**"
                        st.markdown(header_tot)
                    
                    fn_tot_comp_xlsx = generate_export_filename(f, table_type="comparative", platform_override=None, ext="xlsx", is_totals=True)
                    fn_tot_comp_csv = generate_export_filename(f, table_type="comparative", platform_override=None, ext="csv", is_totals=True)
                    c_tot1, c_tot2 = st.columns(2, width=380, gap="small", wrap=False)
                    with c_tot1:
                        st.download_button(
                            "Descargar Totales (.csv)", 
                            data=lambda: to_csv_bytes(df_totals), 
                            file_name=fn_tot_comp_csv, 
                            mime="text/csv",
                            key="btn_dl_tot_comp_csv",
                            use_container_width=True
                        )
                    with c_tot2:
                        st.download_button(
                            "Descargar Totales (.xlsx)", 
                            data=lambda: to_excel_bytes(df_totals, "Comparative_Totals", currency_symbol=curr_sym), 
                            file_name=fn_tot_comp_xlsx,
                            key="btn_dl_tot_comp_xlsx",
                            use_container_width=True
                        )
                    h_tot = 300 if len(df_totals) > 6 else "content"
                    st.dataframe(df_totals, use_container_width=True, hide_index=True, column_config=col_tooltips_comp_totals, height=h_tot)

                if not report_piv.empty:
                    c_comp1, c_comp2 = st.columns(2, width=380, gap="small", wrap=False)
                    with c_comp1:
                        st.download_button(
                            "Descargar .csv", 
                            data=lambda: to_csv_bytes(report_piv), 
                            file_name=fn_comp_csv, 
                            mime="text/csv",
                            key="btn_dl_comp_csv",
                            use_container_width=True
                        )
                    with c_comp2:
                        st.download_button(
                            "Descargar .xlsx", 
                            data=lambda: to_excel_bytes(report_piv, "Comparative", currency_symbol=curr_sym), 
                            file_name=fn_comp_xlsx,
                            key="btn_dl_comp_xlsx",
                            use_container_width=True
                        )
                        
                    st.dataframe(report_piv, use_container_width=True, hide_index=True, column_config=col_tooltips_comp)
                else:
                    st.info("No hay filas de detalle comparativo para este nivel de agregación y filtros (consulta **Totales Globales** arriba o la pestaña individual de cada plataforma).")

            def _render_yt():
                fn_yt_xlsx = generate_export_filename(f, table_type="metrics", platform_override="Youtube", ext="xlsx")
                fn_yt_csv = generate_export_filename(f, table_type="metrics", platform_override="Youtube", ext="csv")
                st.markdown("##### Métricas Exclusivas de YouTube", anchors=False)
                st.caption("💡 **Nota:** Las columnas marcadas con el símbolo **🧮** contienen datos calculados en código (ej. CPM, clasificaciones de formato o recuento de versiones). Pasa el cursor sobre el encabezado para ver la fórmula.")
                st.caption("ℹ️ **Conciliación Contable:** Los ingresos de YouTube están anclados al 100% con las liquidaciones oficiales del CMS. Las visualizaciones y el tiempo de reproducción reflejan el consumo real medido sobre los episodios activos del catálogo.")
                if not df_yt.empty:
                    if not df_totals_yt.empty:
                        if len(df_totals_yt) > 1:
                            st.markdown("**Totales Globales y Desglose Temporal (YouTube):**")
                            st.caption(_get_totals_caption(f, df_totals_yt))
                        else:
                            st.markdown("**Fila de Totales Globales (YouTube):**")
                        
                        fn_tot_yt_xlsx = generate_export_filename(f, table_type="metrics", platform_override="Youtube", ext="xlsx", is_totals=True)
                        fn_tot_yt_csv = generate_export_filename(f, table_type="metrics", platform_override="Youtube", ext="csv", is_totals=True)
                        c_tot_yt1, c_tot_yt2 = st.columns(2, width=380, gap="small", wrap=False)
                        with c_tot_yt1:
                            st.download_button(
                                "Descargar Totales (.csv)",
                                data=lambda: to_csv_bytes(df_totals_yt),
                                file_name=fn_tot_yt_csv,
                                mime="text/csv",
                                key="btn_dl_tot_yt_csv",
                                use_container_width=True
                            )
                        with c_tot_yt2:
                            st.download_button(
                                "Descargar Totales (.xlsx)",
                                data=lambda: to_excel_bytes(df_totals_yt, "YouTube_Totals", currency_symbol=curr_sym),
                                file_name=fn_tot_yt_xlsx,
                                key="btn_dl_tot_yt_xlsx",
                                use_container_width=True
                            )
                        h_tot_yt = 300 if len(df_totals_yt) > 6 else "content"
                        st.dataframe(df_totals_yt, use_container_width=True, hide_index=True, column_config=col_tooltips_yt_totals, height=h_tot_yt)
                        
                    c_yt1, c_yt2 = st.columns(2, width=380, gap="small", wrap=False)
                    with c_yt1:
                        st.download_button(
                            "Descargar .csv", 
                            data=lambda: to_csv_bytes(df_yt), 
                            file_name=fn_yt_csv, 
                            mime="text/csv",
                            key="btn_dl_yt_csv",
                            use_container_width=True
                        )
                    with c_yt2:
                        st.download_button(
                            "Descargar .xlsx", 
                            data=lambda: to_excel_bytes(df_yt, "YouTube_Metrics", currency_symbol=curr_sym), 
                            file_name=fn_yt_xlsx,
                            key="btn_dl_yt_xlsx",
                            use_container_width=True
                        )
                        
                    st.dataframe(df_yt, use_container_width=True, hide_index=True, column_config=col_tooltips_yt)
                else:
                    st.info("No hay datos de YouTube para mostrar en el periodo seleccionado.")

            def _render_amz():
                fn_amz_xlsx = generate_export_filename(f, table_type="metrics", platform_override="Amazon", ext="xlsx")
                fn_amz_csv = generate_export_filename(f, table_type="metrics", platform_override="Amazon", ext="csv")
                st.markdown("##### Métricas Exclusivas de Amazon Prime Video", anchors=False)
                st.caption("💡 **Nota:** Las columnas marcadas con el símbolo **🧮** contienen datos calculados en código (ej. CPH Rate, Avg Min/View, Match de IA). Pasa el cursor sobre el encabezado para ver la fórmula y detalle.")
                if f.get('temp_mode') == 'daily':
                    st.info("ℹ️ **Valores diarios prorrateados:** En vista diaria, cada registro refleja la cuota proporcional lineal (1/N días del mes) calculada a partir de las liquidaciones y reportes mensuales oficiales de Amazon Prime Video.")
                if not df_amz.empty:
                    with st.expander("ℹ️ **Guía Visual: Relación entre Views, Watch Time y Regalías en Amazon Prime Video (2016–2026)**", expanded=False):
                        st.markdown("""
                        * **Periodo Oficial Auditado (2016–2026):** Serie histórica continua de 122 meses (septiembre de 2016 a octubre de 2026) con ingresos unificados al 100% en **USD ($)**.
                        * **Amazon liquida por Horas Vistas (CPH Rate):** En Prime (SVOD), cada hora completa reproducida devenga una regalía según la tarifa CPH (*Cost Per Hour*) del territorio. En TVOD, los ingresos devienen de la compra o alquiler directo del título.
                        * **Telemetría de Visualizaciones (Unique Streams):** Todos los reportes mensuales incorporan las reproducciones reales (*Unique Streams*) y minutos reproducidos (*Watch Time*) de los Streaming Reports oficiales de Amazon desde septiembre de 2016.
                        """)
                    if not df_totals_amz.empty:
                        if len(df_totals_amz) > 1:
                            st.markdown("**Totales Globales y Desglose Temporal (Amazon Prime Video):**")
                            st.caption(_get_totals_caption(f, df_totals_amz))
                        else:
                            st.markdown("**Fila de Totales Globales (Amazon Prime Video):**")
                        
                        fn_tot_amz_xlsx = generate_export_filename(f, table_type="metrics", platform_override="Amazon", ext="xlsx", is_totals=True)
                        fn_tot_amz_csv = generate_export_filename(f, table_type="metrics", platform_override="Amazon", ext="csv", is_totals=True)
                        c_tot_amz1, c_tot_amz2 = st.columns(2, width=380, gap="small", wrap=False)
                        with c_tot_amz1:
                            st.download_button(
                                "Descargar Totales (.csv)",
                                data=lambda: to_csv_bytes(df_totals_amz),
                                file_name=fn_tot_amz_csv,
                                mime="text/csv",
                                key="btn_dl_tot_amz_csv",
                                use_container_width=True
                            )
                        with c_tot_amz2:
                            st.download_button(
                                "Descargar Totales (.xlsx)",
                                data=lambda: to_excel_bytes(df_totals_amz, "Amazon_Totals", currency_symbol=curr_sym),
                                file_name=fn_tot_amz_xlsx,
                                key="btn_dl_tot_amz_xlsx",
                                use_container_width=True
                            )
                        h_tot_amz = 300 if len(df_totals_amz) > 6 else "content"
                        st.dataframe(df_totals_amz, use_container_width=True, hide_index=True, column_config=col_tooltips_amz_totals, height=h_tot_amz)
                        
                    c_amz1, c_amz2 = st.columns(2, width=380, gap="small", wrap=False)
                    with c_amz1:
                        st.download_button(
                            "Descargar .csv", 
                            data=lambda: to_csv_bytes(df_amz), 
                            file_name=fn_amz_csv, 
                            mime="text/csv",
                            key="btn_dl_amz_csv",
                            use_container_width=True
                        )
                    with c_amz2:
                        st.download_button(
                            "Descargar .xlsx", 
                            data=lambda: to_excel_bytes(df_amz, "Amazon_Metrics", currency_symbol=curr_sym), 
                            file_name=fn_amz_xlsx,
                            key="btn_dl_amz_xlsx",
                            use_container_width=True
                        )
                        
                    st.dataframe(df_amz, use_container_width=True, hide_index=True, column_config=col_tooltips_amz)
                else:
                    st.info("No hay datos de Amazon para mostrar en el periodo seleccionado.")

            def _render_china_platform_tab(
                platform_override: str,
                display_name: str,
                heading: str,
                expander_title: str,
                expander_md: str,
                df_main: pd.DataFrame,
                df_tot: pd.DataFrame,
                tooltips_main: dict,
                tooltips_tot: dict,
                sheet_prefix: str,
                key_prefix: str,
            ):
                fn_xlsx = generate_export_filename(f, table_type="metrics", platform_override=platform_override, ext="xlsx")
                fn_csv = generate_export_filename(f, table_type="metrics", platform_override=platform_override, ext="csv")
                st.markdown(heading, anchors=False)
                st.caption("💡 **Nota:** Las columnas marcadas con el símbolo **🧮** reflejan ingresos en RMB (¥) convertidos a USD mediante la tasa media anual del ejercicio correspondiente.")
                if not df_main.empty:
                    with st.expander(expander_title, expanded=False):
                        st.markdown(expander_md)
                    if not df_tot.empty:
                        if len(df_tot) > 1:
                            st.markdown(f"**Totales Globales y Desglose Temporal ({display_name}):**")
                            st.caption(_get_totals_caption(f, df_tot))
                        else:
                            st.markdown(f"**Fila de Totales Globales ({display_name}):**")

                        fn_tot_xlsx = generate_export_filename(f, table_type="metrics", platform_override=platform_override, ext="xlsx", is_totals=True)
                        fn_tot_csv = generate_export_filename(f, table_type="metrics", platform_override=platform_override, ext="csv", is_totals=True)
                        c_tot1, c_tot2 = st.columns(2, width=380, gap="small", wrap=False)
                        with c_tot1:
                            st.download_button(
                                "Descargar Totales (.csv)",
                                data=lambda: to_csv_bytes(df_tot),
                                file_name=fn_tot_csv,
                                mime="text/csv",
                                key=f"btn_dl_tot_{key_prefix}_csv",
                                use_container_width=True
                            )
                        with c_tot2:
                            st.download_button(
                                "Descargar Totales (.xlsx)",
                                data=lambda: to_excel_bytes(df_tot, f"{sheet_prefix}_Totals", currency_symbol=curr_sym),
                                file_name=fn_tot_xlsx,
                                key=f"btn_dl_tot_{key_prefix}_xlsx",
                                use_container_width=True
                            )
                        h_tot = 300 if len(df_tot) > 6 else "content"
                        st.dataframe(df_tot, use_container_width=True, hide_index=True, column_config=tooltips_tot, height=h_tot)

                    c1, c2 = st.columns(2, width=380, gap="small", wrap=False)
                    with c1:
                        st.download_button(
                            "Descargar .csv",
                            data=lambda: to_csv_bytes(df_main),
                            file_name=fn_csv,
                            mime="text/csv",
                            key=f"btn_dl_{key_prefix}_csv",
                            use_container_width=True
                        )
                    with c2:
                        st.download_button(
                            "Descargar .xlsx",
                            data=lambda: to_excel_bytes(df_main, f"{sheet_prefix}_Metrics", currency_symbol=curr_sym),
                            file_name=fn_xlsx,
                            key=f"btn_dl_{key_prefix}_xlsx",
                            use_container_width=True
                        )

                    st.dataframe(df_main, use_container_width=True, hide_index=True, column_config=tooltips_main)
                else:
                    st.info(f"No hay datos de {display_name} para mostrar en el periodo seleccionado.")

            def _render_tcn():
                _render_china_platform_tab(
                    platform_override="Tencent",
                    display_name="Tencent Video",
                    heading="##### Métricas Exclusivas de Tencent Video (China)",
                    expander_title="ℹ️ **Estructura Histórica Tencent Video (SVOD por Serie vs AVOD de Canal)**",
                    expander_md="""
                        * **SVOD (por Serie / IP, mar 2021 – feb 2025):** Los reportes mensuales/diarios de SVOD incluyen ingresos y visualizaciones desglosadas para las series `Shark Academy` (`SHARK_ACADEMY`), `Increditales` (`INCREDITALES`), `AnimaCars` (`ANIMACARS`), `Baby Trucks` / `InvenTom` / `RoboFuse` (`CARCITY_SUPER`) y `Supers` (`SUPERS`).
                        * **AVOD (a nivel de Canal, ene 2018 – dic 2023):** Los reportes históricos de tráfico publicitario en Tencent no incluyen identificador de serie ni de episodio, por lo que se consolidan bajo la IP `CHANNEL_LEVEL` (`Channel Wide (AVOD)`).
                        * **Conversión Monetaria Auditada:** Se conserva la columna contable original en yuanes (**RMB ¥**) junto al equivalente en **USD ($)** convertido por año (tasas medias IRS/Fed `2017–2026`).
                    """,
                    df_main=df_tcn,
                    df_tot=df_totals_tcn,
                    tooltips_main=col_tooltips_tcn,
                    tooltips_tot=col_tooltips_tcn_totals,
                    sheet_prefix="Tencent",
                    key_prefix="tcn",
                )

            def _render_yku():
                _render_china_platform_tab(
                    platform_override="Youku",
                    display_name="Youku",
                    heading="##### Métricas Exclusivas de Youku (China)",
                    expander_title="ℹ️ **Estructura Histórica Youku (DaYu Platform vs Open Platform)**",
                    expander_md="""
                        * **Open Platform (Licencias por Serie / IP, ene 2020 – ene 2025):** Ingresos mensuales oficiales **AVOD** (24 álbumes mapeados a `CARCITY`, `LEARN_TV`, `TINY_WORLD`, `ANIMACARS`, `ONE_ZEES`, `SUPERS`, `MILIKI`) y **SVOD** (`MONSTER_TOWN`, `CARCITY_MAGIC_CAR_CITY`), combinados con visualizaciones diarias y horas de consumo VIP (`Watch Time`).
                        * **DaYu Platform (Canales Propios CC y LTV, mar 2017 – may 2023):** Ingresos diarios nativos, visualizaciones, likes y comentarios de los canales **Car City (`CARCITY`)** y **Learn TV (`LEARN_TV`)**.
                        * **Granularidad Diaria:** En vista diaria, los ingresos mensuales de *Open Platform* se prorratean equitativamente (1/N días del mes), mientras las visualizaciones y los datos de *DaYu* mantienen su grano diario nativo.
                    """,
                    df_main=df_yku,
                    df_tot=df_totals_yku,
                    tooltips_main=col_tooltips_yku,
                    tooltips_tot=col_tooltips_yku_totals,
                    sheet_prefix="Youku",
                    key_prefix="yku",
                )

            def _render_iqy():
                _render_china_platform_tab(
                    platform_override="Iqiyi",
                    display_name="iQIYI",
                    heading="##### Métricas Exclusivas de iQIYI (China)",
                    expander_title="ℹ️ **Estructura Histórica iQIYI (Amuse CC, LTV / France y Shanghai)**",
                    expander_md="""
                        * **Amuse CC (`2463347304`, ene 2017 – ene 2025):** Canal Car City con ingresos diarios **AVOD** y visualizaciones/comentarios por serie (`Views/Per Series`, más `Old/Détail CC` y `Views Iqiyi CC` en 2017–mar 2018).
                        * **Amuse LTV / France (`2484062153`, mar 2017 – ene 2026):** Canal Learn TV con ingresos diarios **AVOD**, más ingresos **SVOD** conciliados sin duplicidades por serie/IP (`2017–jun 2024`, incluyendo consumo VIP `有效付费时长` en horas de **feb 2022 – jun 2024**) y totales de canal (`jul 2024 – ene 2026`).
                        * **Amuse Shanghai (`4318775981759616`, abr 2024 – ene 2026):** Cuenta corporativa en China con liquidaciones diarias **AVOD** (`2024–ene 2025`) y **SVOD** (`jul 2024 – ene 2026`).
                        * **Conversión Auditada:** Se conserva la columna original en yuanes (**RMB ¥**) junto al equivalente en **USD ($)** convertido por año (tasas medias IRS/Fed `2017–2026`).
                    """,
                    df_main=df_iqy,
                    df_tot=df_totals_iqy,
                    tooltips_main=col_tooltips_iqy,
                    tooltips_tot=col_tooltips_iqy_totals,
                    sheet_prefix="Iqiyi",
                    key_prefix="iqy",
                )

            tab_defs = []
            if has_comparative_tab:
                tab_defs.append(("Comparativa: Consolidada", _render_comp))
            if use_yt:
                tab_defs.append(("Métricas Detalladas: YouTube", _render_yt))
            if use_amz:
                tab_defs.append(("Métricas Detalladas: Amazon", _render_amz))
            if use_tcn:
                tab_defs.append(("Métricas Detalladas: Tencent", _render_tcn))
            if use_yku:
                tab_defs.append(("Métricas Detalladas: Youku", _render_yku))
            if use_iqy:
                tab_defs.append(("Métricas Detalladas: iQIYI", _render_iqy))

            if len(tab_defs) > 1:
                st_tabs = st.tabs([t[0] for t in tab_defs])
                for tab_obj, (_, render_fn) in zip(st_tabs, tab_defs):
                    with tab_obj:
                        render_fn()
            elif len(tab_defs) == 1:
                tab_defs[0][1]()

        if submitted:
            placeholder_msg_tablas.success(success_msg)
            st.session_state.use_tablas_executed = True
else:
    st.error("Error de infraestructura: No se pudo verificar la doble conexión activa a las bases de datos.")