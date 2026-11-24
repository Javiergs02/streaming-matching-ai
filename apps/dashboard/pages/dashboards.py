import os
import sys
from datetime import datetime

# Asegurar que la raíz del proyecto y apps/dashboard estén en el PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DASHBOARD_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

import streamlit as st
import pandas as pd
import plotly.express as px

from utils.connections import get_postgres_connection, get_broadkast_postgres_connection, get_mongo_client
from utils.styling import apply_portal_style
from core.domain.amazon import convert_amazon_eur_to_usd

st.set_page_config(page_title="Dashboards Dinámicos", layout="wide", page_icon="📈")
apply_portal_style()

@st.cache_data(ttl=3600)
def fetch_metadata():
    db_psql = get_postgres_connection()
    db_psql_amz = get_broadkast_postgres_connection()
    
    # YouTube metadata
    sql_yt = '''
    SELECT 
        yv.video_id,
        yc.country_code AS geography,
        s.series_name,
        COALESCE(NULLIF(e_en.title, ''), NULLIF(e.title, ''), s.series_name || ' - Ep ' || COALESCE(e.episode_number, e_en.episode_number)::varchar, 'Unknown Episode') AS episode_name
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
    '''
    df_yt = pd.read_sql(sql_yt, db_psql) if db_psql else pd.DataFrame(columns=['video_id', 'geography', 'series_name', 'episode_name'])
    
    # Amazon metadata
    sql_amz = '''
    SELECT 
        'EP_' || e.id::varchar AS video_id,
        s.name AS series_name,
        s_season.number AS season,
        e.number AS episode_number,
        COALESCE(NULLIF(e.name, ''), s.name || ' - Ep ' || e.number::varchar, 'Unknown Episode') AS episode_name
    FROM public.episodes e
    LEFT JOIN public.seasons s_season ON e.season_id = s_season.id
    LEFT JOIN public.series s ON e.series_id = s.id
    '''
    df_amz = pd.read_sql(sql_amz, db_psql_amz) if db_psql_amz else pd.DataFrame(columns=['video_id', 'series_name', 'season', 'episode_number', 'episode_name'])

    if db_psql and not df_amz.empty:
        sql_en = '''
        SELECT s.series_name, e.season, e.episode_number, e.title as english_name
        FROM amuseplatforms_db.episodes e
        JOIN amuseplatforms_db.series s ON e.series_code = s.series_code
        WHERE e.language_code = 'en'
        '''
        try:
            df_en = pd.read_sql(sql_en, db_psql)
            df_en = df_en.drop_duplicates(subset=['series_name', 'season', 'episode_number'])
            df_amz = df_amz.merge(df_en, on=['series_name', 'season', 'episode_number'], how='left')
            df_amz['episode_name'] = df_amz['english_name'].combine_first(df_amz['episode_name'])
            df_amz.drop(columns=['english_name', 'season', 'episode_number'], inplace=True, errors='ignore')
        except Exception as e:
            pass
            
    return df_yt, df_amz

@st.cache_data(ttl=600)
def fetch_mongo_data(start_month, end_month):
    db_mongo = get_mongo_client()
    if db_mongo is None:
        return pd.DataFrame()
        
    coll = db_mongo['monthly_performance_summaries']
    
    pipeline = [
        {"$match": {
            "_id.month": {
                "$gte": start_month,
                "$lte": end_month
            }
        }},
        {"$group": {
            "_id": {
                "video_id": "$_id.video_id",
                "month": "$_id.month",
                "platform": "$_id.platform",
                "geography": "$_id.geography",
                "event_type": "$_id.event_type"
            },
            "views": {"$sum": "$monthly_views"},
            "watch_time": {"$sum": "$monthly_watch_time"},
            "currency": {"$first": "$currency"},
            "revenue": {"$sum": "$monthly_revenue"},
            "likes": {"$sum": "$monthly_likes"},
            "comments": {"$sum": "$monthly_comments"},
            "ad_impressions": {"$sum": "$monthly_ad_impressions"},
            "ad_revenue": {"$sum": "$monthly_ad_revenue"}
        }}
    ]
    
    data = list(coll.aggregate(pipeline, allowDiskUse=True))
    if not data:
        return pd.DataFrame()
        
    df = pd.DataFrame([{
        'video_id': d['_id']['video_id'],
        'month': d['_id']['month'],
        'platform': d['_id']['platform'],
        'geography': d['_id']['geography'],
        'event_type': d['_id']['event_type'],
        'views': d['views'],
        'watch_time': d['watch_time'],
        'currency': d.get('currency', 'USD'),
        'revenue': d['revenue'],
        'likes': d.get('likes', 0),
        'comments': d.get('comments', 0),
        'ad_impressions': d.get('ad_impressions', 0),
        'ad_revenue': d.get('ad_revenue', 0),
    } for d in data])
    
    return df

st.title("📈 Dashboards Dinámicos")

# --- Filters ---
with st.sidebar.form("filtros_dashboard"):
    st.header("Filtros")
    
    granularity = st.radio("Nivel de Análisis", ["Por Series", "Por Episodios"])
    
    # Use date inputs to derive YYYY-MM
    start_date = st.date_input("Fecha Inicio (Mes)", datetime(2025, 1, 1))
    end_date = st.date_input("Fecha Fin (Mes)", datetime(2025, 12, 31))
    
    top_n = st.slider("Mostrar Top N (Elementos)", min_value=5, max_value=50, value=10, help="Limita las gráficas a los elementos más populares para evitar sobrecarga visual.")
    
    submitted = st.form_submit_button("Generar Dashboard", use_container_width=True)

if submitted:
    st.session_state.generate_dashboard = True
    # Save parameters to session state so they persist across interactions inside the dashboard
    st.session_state.dash_start_month = start_date.strftime("%Y-%m")
    st.session_state.dash_end_month = end_date.strftime("%Y-%m")
    st.session_state.dash_top_n = top_n
    st.session_state.dash_granularity = granularity

if st.session_state.get("generate_dashboard", False):
    start_month_str = st.session_state.dash_start_month
    end_month_str = st.session_state.dash_end_month
    top_n = st.session_state.dash_top_n
    granularity = st.session_state.dash_granularity


    with st.spinner("Cargando datos..."):
        df_mongo = fetch_mongo_data(start_month_str, end_month_str)
        df_meta_yt, df_meta_amz = fetch_metadata()

    if df_mongo.empty:
        st.warning("No se encontraron datos para el rango de fechas seleccionado.")
    else:
        # Separate YT and Amazon Data (incluyendo SVOD y TVOD, Fix BUG-01)
        df_yt_mongo = df_mongo[df_mongo['event_type'] == 'youtube.video.performance_recorded'].copy()
        df_amz_mongo = df_mongo[df_mongo['event_type'].astype(str).str.startswith('amazon.video.performance')].copy()
    
        # Merge with metadata
        if not df_yt_mongo.empty:
            df_yt_mongo = pd.merge(df_yt_mongo, df_meta_yt, on='video_id', how='left', suffixes=('', '_meta'))
            df_yt_mongo['geography'] = df_yt_mongo['geography'].replace('Unknown Geo', None).fillna(df_yt_mongo['geography_meta']).fillna('Unknown Geo')
            df_yt_mongo.fillna({'series_name': 'Unknown Series', 'geography': 'Unknown'}, inplace=True)
            # Drop duplicate rows due to potential many-to-many if episode_youtube_video has multiples, though usually 1:1
            df_yt_mongo = df_yt_mongo.drop_duplicates(subset=['video_id', 'month', 'platform', 'geography'])
        
        if not df_amz_mongo.empty:
            if 'currency' in df_amz_mongo.columns:
                df_amz_mongo['revenue'] = [
                    convert_amazon_eur_to_usd(rev, curr)
                    for rev, curr in zip(df_amz_mongo['revenue'], df_amz_mongo['currency'])
                ]
            else:
                df_amz_mongo['revenue'] = df_amz_mongo['revenue'].map(convert_amazon_eur_to_usd)
            df_amz_mongo = pd.merge(df_amz_mongo, df_meta_amz, on='video_id', how='left')
            df_amz_mongo.fillna({'series_name': 'Unknown Series'}, inplace=True)
        
        # --- Top N Filtering (Independiente por Plataforma) ---
        group_col = 'episode_name' if granularity == 'Por Episodios' else 'series_name'
        
        # Rellenar posibles nulos en la columna de agrupación
        if not df_yt_mongo.empty:
            df_yt_mongo[group_col] = df_yt_mongo[group_col].fillna('Desconocido')
            
        if not df_amz_mongo.empty:
            df_amz_mongo[group_col] = df_amz_mongo[group_col].fillna('Desconocido')
        
        if not df_yt_mongo.empty:
            yt_metric = df_yt_mongo.groupby(group_col)['views'].sum().sort_values(ascending=False)
            top_yt_items = yt_metric.head(top_n).index.tolist()
            df_yt_mongo = df_yt_mongo[df_yt_mongo[group_col].isin(top_yt_items)]
        
        if not df_amz_mongo.empty:
            # En Amazon filtramos el Top por ingresos, ya que las vistas suelen ser nulas o 0 en reportes de SVOD
            amz_metric = df_amz_mongo.groupby(group_col)['revenue'].sum().sort_values(ascending=False)
            top_amz_items = amz_metric.head(top_n).index.tolist()
            df_amz_mongo = df_amz_mongo[df_amz_mongo[group_col].isin(top_amz_items)]
    
        # Create tabs
        tab1, tab2 = st.tabs(["🟥 YouTube", "🟦 Amazon Prime Video"])
    
        with tab1:
            st.subheader(f"Análisis Detallado: YouTube ({granularity})")
            if not df_yt_mongo.empty:
                # Region Filter for YouTube
                all_yt_regions = sorted(df_yt_mongo['geography'].astype(str).unique().tolist())
                selected_yt_regions = st.multiselect("Filtrar por Región (YouTube)", options=all_yt_regions, default=all_yt_regions, key="yt_reg")
            
                yt_filtered = df_yt_mongo[df_yt_mongo['geography'].isin(selected_yt_regions)]
            
                if not yt_filtered.empty:
                    col1, col2 = st.columns(2)
                
                    # Vistas en el tiempo
                    yt_time = yt_filtered.groupby(['month', group_col])['views'].sum().reset_index()
                    fig_yt_time = px.line(yt_time, x='month', y='views', color=group_col, markers=True, title=f"Vistas a lo largo del tiempo ({granularity})")
                    col1.plotly_chart(fig_yt_time, use_container_width=True)
                
                    # Ingresos totales (Pie)
                    yt_pie = yt_filtered.groupby(group_col)['revenue'].sum().reset_index()
                    fig_yt_pie = px.pie(yt_pie, values='revenue', names=group_col, title=f"Distribución de Ingresos ({granularity})", hole=0.3)
                    col2.plotly_chart(fig_yt_pie, use_container_width=True)
                
                    # Métricas adicionales
                    st.markdown("#### Métricas de Interacción")
                    yt_inter = yt_filtered.groupby(group_col)[['likes', 'comments', 'ad_impressions']].sum().reset_index()
                    fig_yt_inter = px.bar(yt_inter, x=group_col, y=['likes', 'comments'], barmode='group', title=f"Likes y Comentarios ({granularity})")
                    st.plotly_chart(fig_yt_inter, use_container_width=True)
                else:
                    st.info("No hay datos de YouTube para la selección actual.")
            else:
                st.info("No hay datos de YouTube disponibles en este rango.")
            
        with tab2:
            st.subheader(f"Análisis Detallado: Amazon Prime Video ({granularity})")
            if not df_amz_mongo.empty:
                # Region Filter for Amazon
                all_amz_regions = sorted(df_amz_mongo['geography'].astype(str).unique().tolist())
                selected_amz_regions = st.multiselect("Filtrar por Región (Amazon)", options=all_amz_regions, default=all_amz_regions, key="amz_reg")
            
                amz_filtered = df_amz_mongo[df_amz_mongo['geography'].isin(selected_amz_regions)]
            
                if not amz_filtered.empty:
                    col1, col2 = st.columns(2)
                
                    # Vistas en el tiempo
                    amz_time = amz_filtered.groupby(['month', group_col])['views'].sum().reset_index()
                    fig_amz_time = px.line(amz_time, x='month', y='views', color=group_col, markers=True, title=f"Vistas a lo largo del tiempo ({granularity})")
                    col1.plotly_chart(fig_amz_time, use_container_width=True)
                
                    # Ingresos totales (Pie)
                    amz_pie = amz_filtered.groupby(group_col)['revenue'].sum().reset_index()
                    fig_amz_pie = px.pie(amz_pie, values='revenue', names=group_col, title=f"Distribución de Ingresos ({granularity})", hole=0.3)
                    col2.plotly_chart(fig_amz_pie, use_container_width=True)
                else:
                    st.info("No hay datos de Amazon para la selección actual.")
            else:
                st.info("No hay datos de Amazon disponibles en este rango.")
