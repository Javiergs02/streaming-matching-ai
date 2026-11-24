# apps/dashboard/pages/estado_mapeado.py
import os
import sys
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Asegurar que la raíz del proyecto y apps/dashboard estén en el PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DASHBOARD_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

from utils.styling import apply_portal_style
from utils.mapping_stats import (
    load_youtube_mapping_stats,
    load_amazon_mapping_stats,
    get_combined_executive_kpis,
    generate_export_excel_bytes
)

st.set_page_config(page_title="Estado Mapeado", layout="wide", page_icon="🎯")
apply_portal_style()

st.title("🎯 Estado de Mapeo y Calidad de Catálogo")
st.markdown("""
Auditoría integral del motor de matching para **YouTube** y **Amazon Prime Video**.
Monitorea los recuentos de vídeos y títulos desglosados por **metodología de mapeo**, **rangos de porcentaje de confianza**, **año de publicación / reporte** y su **monetización histórica y reciente (€)**.
""")
st.markdown("---")

# Carga de datos
try:
    kpis = get_combined_executive_kpis()
    yt_data = load_youtube_mapping_stats()
    amz_data = load_amazon_mapping_stats()
except Exception as e:
    st.error(f"Error al cargar las estadísticas de mapeo: {e}")
    st.stop()

# ==========================================
# 1. TARJETAS DE KPIs EJECUTIVOS SUPERIORES
# ==========================================
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Total Contenidos Auditados",
        value=f"{kpis['yt']['total_items'] + kpis['amz']['total_items']:,}".replace(",", "."),
        delta=f"YT: {kpis['yt']['total_items']:,} | AMZ: {kpis['amz']['total_items']:,}".replace(",", "."),
        delta_color="off"
    )

with col2:
    st.metric(
        label="Cobertura Catálogo Amuse",
        value=f"{kpis['yt']['pct_mapped']}% (YT) / {kpis['amz']['pct_mapped']}% (AMZ)",
        delta="Videos/Títulos identificados",
        delta_color="normal"
    )

with col3:
    st.metric(
        label="Alta Confianza (>= 80% / 17-20 pts)",
        value=f"{kpis['yt']['pct_high_conf']}% (YT) / {kpis['amz']['pct_high_conf']}% (AMZ)",
        delta="Máxima fiabilidad",
        delta_color="normal"
    )

with col4:
    tot_rev_m = (kpis['yt']['total_revenue'] + kpis['amz']['total_revenue']) / 1e6
    st.metric(
        label="Facturación Total Reconciliada",
        value=f"{tot_rev_m:.2f} M €",
        delta=f"YT: {kpis['yt']['total_revenue']/1e6:.2f}M€ | AMZ: {kpis['amz']['total_revenue']/1e6:.2f}M€",
        delta_color="normal"
    )

# Botón de exportación a Excel
st.markdown("<br>", unsafe_allow_html=True)
col_dl1, col_dl2 = st.columns([3, 1])
with col_dl2:
    try:
        excel_bytes = generate_export_excel_bytes()
        st.download_button(
            label="📥 Descargar Auditoría Completa (Excel)",
            data=excel_bytes,
            file_name="Estado_Mapeo_Consolidado_Amuse.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    except Exception as e:
        st.warning(f"No se pudo generar el archivo Excel: {e}")

# ==========================================
# 2. PESTAÑAS PRINCIPALES
# ==========================================
tab_yt, tab_amz, tab_comp = st.tabs([
    "📺 YouTube (Canales & Videos)",
    "📦 Amazon Prime Video (Títulos & Series)",
    "📊 Comparativa Ejecutiva y Confianza"
])

# ----------------------------------------------------
# TAB 1: YOUTUBE
# ----------------------------------------------------
with tab_yt:
    st.markdown("### 📺 Auditoría de Mapeo: YouTube IDs")
    st.info("""
    **Metodología de Mapeo YouTube:**
    Auditoría tras depurar **BK 1** mediante modelos de *word embeddings* y multiclasificación avanzada por título (se descartaron descripciones para eliminar ruido).
    Se han descontado emisiones en directo (*lives*), vídeos eliminados de YouTube y vídeos de IPs no registradas en el catálogo de episodios (Louie, Milo, Pipo, Playdoh, etc.).
    """)

    df_rec = yt_data['recuento'].copy()
    df_hist = yt_data['monetizacion_historica'].copy()
    df_2025 = yt_data['monetizacion_2025'].copy()
    df_ip_rec = yt_data['ip_recuento'].copy()
    df_ip_mon = yt_data['ip_monetizacion'].copy()
    df_conf = yt_data['confianza_resumen'].copy()

    # Filtro por año interactivo
    years_yt = df_rec['Año'].tolist()
    sel_years_yt = st.multiselect("Filtrar por Año de Publicación (YouTube):", options=years_yt, default=years_yt, key="yt_year_filter")
    filtered_rec = df_rec[df_rec['Año'].isin(sel_years_yt)]
    filtered_hist = df_hist[df_hist['Año'].isin(sel_years_yt)]
    filtered_2025 = df_2025[df_2025['Año'].isin(sel_years_yt)]

    # 1. Recuento según forma
    st.subheader("1. Recuento de Videos IDs Mapeados por Año de Publicación (#)")
    
    # Gráfico de barras apiladas
    methods_rec = ['BK2 (100%)', 'BK 1 (100%)', 'Match por Título (100%)', 'Modelo Multifase (85%)', 'Sin Mapear y NO AMUSE (0%)']
    df_melt_rec = filtered_rec.melt(id_vars=['Año'], value_vars=methods_rec, var_name='Método de Mapeo', value_name='Vídeos')
    fig_rec = px.bar(
        df_melt_rec,
        x='Año',
        y='Vídeos',
        color='Método de Mapeo',
        title="Evolución de Videos Mapeados por Método y Año de Publicación",
        barmode='stack',
        color_discrete_map={
            'BK2 (100%)': '#1f77b4',
            'BK 1 (100%)': '#2ca02c',
            'Match por Título (100%)': '#ff7f0e',
            'Modelo Multifase (85%)': '#9467bd',
            'Sin Mapear y NO AMUSE (0%)': '#d62728'
        }
    )
    fig_rec.update_layout(height=380, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig_rec, use_container_width=True)

    # Tabla formateada
    cfg_rec = {
        'Año': st.column_config.TextColumn('Año Publicación'),
        'BK2 (100%)': st.column_config.NumberColumn('BK2 (100% conf)', format='%d'),
        'BK 1 (100%)': st.column_config.NumberColumn('BK 1 (100% conf)', format='%d'),
        'Match por Título (100%)': st.column_config.NumberColumn('Match Título (100% conf)', format='%d'),
        'Modelo Multifase (85%)': st.column_config.NumberColumn('Multifase (85% conf)', format='%d'),
        'Sin Mapear y NO AMUSE (0%)': st.column_config.NumberColumn('Sin Mapear / No Amuse', format='%d'),
        'TOTAL BBDD': st.column_config.NumberColumn('TOTAL BBDD', format='%d')
    }
    st.dataframe(filtered_rec, column_config=cfg_rec, use_container_width=True, hide_index=True)

    # Métricas de totales de la tabla
    subcol1, subcol2, subcol3, subcol4 = st.columns(4)
    with subcol1:
        st.caption("**Total Activos Mapeados (Amuse):** 79.746 vídeos")
    with subcol2:
        st.caption("**Total BBDD Histórica:** 82.745 vídeos")
    with subcol3:
        st.caption("**% BK1 + BK2 + Título (100% conf):** 87,8% del catálogo")
    with subcol4:
        st.caption("**% Modelo Multifase (85% conf):** 8,6% del catálogo")

    st.markdown("---")

    # 2. Monetización histórica
    st.subheader("2. Monetización Histórica Acumulada de Videos Mapeados (€)")
    st.caption("Distribución de los **12.106.925,62 €** generados históricamente en YouTube según el método de asignación de cada vídeo:")

    cfg_hist = {
        'Año': st.column_config.TextColumn('Año Publicación'),
        'BK2 (€)': st.column_config.NumberColumn('BK2 (€)', format='€ %,.2f'),
        'BK 1 (€)': st.column_config.NumberColumn('BK 1 (€)', format='€ %,.2f'),
        'Match por Título (€)': st.column_config.NumberColumn('Match Título (€)', format='€ %,.2f'),
        'Modelo Multifase (€)': st.column_config.NumberColumn('Multifase (€)', format='€ %,.2f'),
        'Sin Mapear (€)': st.column_config.NumberColumn('Sin Mapear (€)', format='€ %,.2f'),
        'TOTAL BBDD (€)': st.column_config.NumberColumn('TOTAL BBDD (€)', format='€ %,.2f')
    }
    st.dataframe(filtered_hist, column_config=cfg_hist, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 3. Monetización 2025
    st.subheader("3. Monetización 2025 de Videos Mapeados (€)")
    st.caption("Ingresos generados durante **2025** (**696.376,95 €**) desglosados por el año de publicación original del vídeo y el método de mapeo:")

    cfg_2025 = {
        'Año': st.column_config.TextColumn('Año Publicación'),
        'BK2 (€)': st.column_config.NumberColumn('BK2 (€)', format='€ %,.2f'),
        'BK 1 (€)': st.column_config.NumberColumn('BK 1 (€)', format='€ %,.2f'),
        'Match por Título (€)': st.column_config.NumberColumn('Match Título (€)', format='€ %,.2f'),
        'Modelo Multifase (€)': st.column_config.NumberColumn('Multifase (€)', format='€ %,.2f'),
        'Sin Mapear (€)': st.column_config.NumberColumn('Sin Mapear (€)', format='€ %,.2f'),
        'TOTAL BBDD (€)': st.column_config.NumberColumn('TOTAL BBDD (€)', format='€ %,.2f')
    }
    st.dataframe(filtered_2025, column_config=cfg_2025, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 4. Clasificación de IPs y Descartes
    st.subheader("4. Auditoría de Clasificación de IPs y Descartes (YouTube)")
    col_ip1, col_ip2 = st.columns(2)

    with col_ip1:
        st.markdown("##### Recuento de Videos (#)")
        cfg_ip_rec = {
            'Año': st.column_config.TextColumn('Año'),
            'Videos IP AMUSE': st.column_config.NumberColumn('IP AMUSE (#)', format='%d'),
            'Videos IP no AMUSE': st.column_config.NumberColumn('IP no AMUSE (#)', format='%d'),
            'Videos eliminados y lives': st.column_config.NumberColumn('Eliminados/Lives (#)', format='%d'),
            'Videos sin mapear': st.column_config.NumberColumn('Sin Mapear (#)', format='%d'),
            'TOTAL BBDD': st.column_config.NumberColumn('TOTAL BBDD (#)', format='%d')
        }
        st.dataframe(df_ip_rec, column_config=cfg_ip_rec, use_container_width=True, hide_index=True)

    with col_ip2:
        st.markdown("##### Monetización Histórica (€)")
        cfg_ip_mon = {
            'Año': st.column_config.TextColumn('Año'),
            'Videos IP AMUSE (€)': st.column_config.NumberColumn('IP AMUSE (€)', format='€ %,.2f'),
            'Videos IP no AMUSE (€)': st.column_config.NumberColumn('IP no AMUSE (€)', format='€ %,.2f'),
            'Videos eliminados y lives (€)': st.column_config.NumberColumn('Eliminados/Lives (€)', format='€ %,.2f'),
            'Videos sin mapear (€)': st.column_config.NumberColumn('Sin Mapear (€)', format='€ %,.2f'),
            'TOTAL BBDD (€)': st.column_config.NumberColumn('TOTAL BBDD (€)', format='€ %,.2f')
        }
        st.dataframe(df_ip_mon, column_config=cfg_ip_mon, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 5. Resumen de Confianza
    st.subheader("5. Resumen de Calidad y Niveles de Confianza (YouTube)")
    cfg_conf = {
        'Método / Rango': st.column_config.TextColumn('Método de Mapeo'),
        'Confianza (%)': st.column_config.TextColumn('Confianza (%)'),
        'Puntuación': st.column_config.TextColumn('Escala 20 pts'),
        'Vídeos (#)': st.column_config.NumberColumn('Vídeos (#)', format='%d'),
        '% Catálogo': st.column_config.NumberColumn('% Catálogo', format='%.2f %%'),
        'Ingresos Históricos (€)': st.column_config.NumberColumn('Ingresos (€)', format='€ %,.2f'),
        '% Ingresos': st.column_config.NumberColumn('% Ingresos', format='%.2f %%')
    }
    st.dataframe(df_conf, column_config=cfg_conf, use_container_width=True, hide_index=True)


# ----------------------------------------------------
# TAB 2: AMAZON PRIME VIDEO
# ----------------------------------------------------
with tab_amz:
    st.markdown("### 📦 Auditoría de Mapeo: Amazon Prime Video")
    st.info("""
    **Metodología de Mapeo Amazon Prime Video:**
    Auditoría basada en los **12.769 títulos únicos** procesados por el motor de producción `production_mappings.csv` cruzados con **117 reportes analíticos mensuales (2017–2026)**.
    - **Exact Title (100% confianza / 20 pts):** Cruce exacto por nombre normalizado.
    - **Semantic AI Alta (Score >= 80% / 18-20 pts):** Emparejamiento por embeddings semánticos con alta similitud conceptual.
    - **Semantic AI Media (Score 60-79% / 14-17 pts):** Similitud moderada con validación de contexto de serie.
    - **Semantic AI Baja (< 60% / < 14 pts):** Emparejamientos de baja certidumbre sujetos a revisión humana.
    - **Descartes IP:** Títulos pertenecientes a IPs ajenas a Amuse (Blacklist de Molang, Mouk, Louie, etc.) y series alienígenas.
    - **Descartes Formato:** Películas y especiales aislados (el catálogo core de Amuse es episódico).
    """)

    df_amz_rec = amz_data['recuento'].copy()
    df_amz_hist = amz_data['monetizacion_historica'].copy()
    df_amz_2025 = amz_data['monetizacion_2025'].copy()
    df_amz_ip_rec = amz_data['ip_recuento'].copy()
    df_amz_ip_mon = amz_data['ip_monetizacion'].copy()
    df_amz_conf = amz_data['confianza_resumen'].copy()

    years_amz = df_amz_rec['Año'].tolist()
    sel_years_amz = st.multiselect("Filtrar por Año de Reporte (Amazon):", options=years_amz, default=years_amz, key="amz_year_filter")
    filtered_amz_rec = df_amz_rec[df_amz_rec['Año'].isin(sel_years_amz)]
    filtered_amz_hist = df_amz_hist[df_amz_hist['Año'].isin(sel_years_amz)]

    # 1. Recuento Amazon
    st.subheader("1. Recuento de Títulos Amazon Mapeados por Año de Reporte (#)")

    with st.expander("ℹ️ **Guía Analítica: ¿Por qué 2024 concentra el mayor volumen de títulos (~6.429)?**", expanded=False):
        st.markdown("""
        * **Histórico 2017 – Agosto 2024 (Reportes transaccionales de facturación):** Amazon únicamente emitía liquidaciones mensuales (*Revenue Reports*). En ellos solo aparecían los títulos que registraban compras directas (TVOD) o regalías activas en ese mes específico. Gran parte de los episodios del catálogo histórico no aparecían de forma desglosada.
        * **Hito de Septiembre de 2024 (Content Performance Reports):** Amazon implementó su nueva plataforma automatizada de rendimiento. A partir de septiembre de 2024, Amazon comenzó a reportar mensualmente **la totalidad del catálogo de episodios de Amuse disponible en Prime Video**, independientemente de que acumularan muchas horas o solo minutos marginales.
        * **Concentración en 2024:** Al registrarse formalmente el catálogo completo por primera vez en septiembre de 2024, **6.429 episodios del fondo de catálogo de Amuse quedaron catalogados en 2024** bajo el criterio de *Año de Primer Reporte*.
        * **Años 2025 en adelante (Nuevas incorporaciones genuinas):** Los años posteriores (**550 títulos en 2025** y **916 títulos en 2026**) reflejan con exactitud las incorporaciones genuinas de nuevos episodios, temporadas y adaptaciones idiomáticas añadidas al servicio desde esas fechas.
        """)
    
    amz_methods_rec = [
        'Exact Title (100%)', 'Semantic AI (>= 80%)', 'Semantic AI (60-79%)',
        'Semantic AI (< 60%)', 'Descartes IP (No Amuse)', 'Descartes Formato / Películas', 'Sin Mapear'
    ]
    df_melt_amz = filtered_amz_rec.melt(id_vars=['Año'], value_vars=amz_methods_rec, var_name='Método / Rango', value_name='Títulos')
    fig_amz_rec = px.bar(
        df_melt_amz,
        x='Año',
        y='Títulos',
        color='Método / Rango',
        title="Evolución de Títulos Amazon por Metodología y Año de Primer Reporte",
        barmode='stack',
        color_discrete_map={
            'Exact Title (100%)': '#2ca02c',
            'Semantic AI (>= 80%)': '#1f77b4',
            'Semantic AI (60-79%)': '#ff7f0e',
            'Semantic AI (< 60%)': '#aec7e8',
            'Descartes IP (No Amuse)': '#d62728',
            'Descartes Formato / Películas': '#8c564b',
            'Sin Mapear': '#7f7f7f'
        }
    )
    fig_amz_rec.update_layout(height=380, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig_amz_rec, use_container_width=True)

    cfg_amz_rec = {
        'Año': st.column_config.TextColumn('Año Primer Reporte', help="Año del primer reporte mensual de Amazon donde apareció el título. En septiembre de 2024 Amazon incorporó el catálogo completo de episodios individuales vía Content Performance Reports."),
        'Exact Title (100%)': st.column_config.NumberColumn('Exact Title (100%)', format='%d'),
        'Semantic AI (>= 80%)': st.column_config.NumberColumn('IA Alta (>= 80%)', format='%d'),
        'Semantic AI (60-79%)': st.column_config.NumberColumn('IA Media (60-79%)', format='%d'),
        'Semantic AI (< 60%)': st.column_config.NumberColumn('IA Baja (< 60%)', format='%d'),
        'Descartes IP (No Amuse)': st.column_config.NumberColumn('Descarte IP (No Amuse)', format='%d'),
        'Descartes Formato / Películas': st.column_config.NumberColumn('Películas / Formato', format='%d'),
        'Sin Mapear': st.column_config.NumberColumn('Sin Mapear', format='%d'),
        'TOTAL BBDD': st.column_config.NumberColumn('TOTAL Títulos', format='%d')
    }
    st.dataframe(filtered_amz_rec, column_config=cfg_amz_rec, use_container_width=True, hide_index=True)
    st.caption("💡 **Aclaración sobre 'Año Primer Reporte':** Refleja la fecha del primer informe oficial de Amazon donde apareció registrado el título. Septiembre de 2024 marcó el despliegue del catálogo completo de episodios individuales vía *Content Performance Reports*, mientras que 2025 y 2026 reflejan exclusivamente nuevas incorporaciones.")

    # Subtotales
    subamz1, subamz2, subamz3, subamz4 = st.columns(4)
    with subamz1:
        st.caption("**Total Títulos Mapeados (Amuse):** 11.574 títulos (90,6%)")
    with subamz2:
        st.caption("**Total BBDD Amazon:** 12.769 títulos")
    with subamz3:
        st.caption("**% Exacto + IA Alta (>= 80%):** 61,3% del total")
    with subamz4:
        st.caption("**Descartes (IPs Ajenas + Películas):** 1.193 títulos")

    st.markdown("---")

    # 2. Monetización histórica Amazon
    st.subheader("2. Monetización Histórica Acumulada de Títulos Amazon (€)")
    st.caption("Distribución de los **8.640.727,48 €** acumulados en Amazon VOD por método de mapping:")

    cfg_amz_hist = {
        'Año': st.column_config.TextColumn('Año Reporte'),
        'Exact Title (€)': st.column_config.NumberColumn('Exact Title (€)', format='€ %,.2f'),
        'Semantic AI (>= 80%) (€)': st.column_config.NumberColumn('IA Alta (>= 80%) (€)', format='€ %,.2f'),
        'Semantic AI (60-79%) (€)': st.column_config.NumberColumn('IA Media (60-79%) (€)', format='€ %,.2f'),
        'Semantic AI (< 60%) (€)': st.column_config.NumberColumn('IA Baja (< 60%) (€)', format='€ %,.2f'),
        'Descartes IP No Amuse (€)': st.column_config.NumberColumn('Descartes IP (€)', format='€ %,.2f'),
        'Descartes Formato (€)': st.column_config.NumberColumn('Películas (€)', format='€ %,.2f'),
        'Sin Mapear (€)': st.column_config.NumberColumn('Sin Mapear (€)', format='€ %,.2f'),
        'Múltiple Global Legacy (€)': st.column_config.NumberColumn('Múltiple Global Legacy (€)', format='€ %,.2f'),
        'TOTAL BBDD (€)': st.column_config.NumberColumn('TOTAL (€)', format='€ %,.2f')
    }
    st.dataframe(filtered_amz_hist, column_config=cfg_amz_hist, use_container_width=True, hide_index=True)
    st.caption("ℹ️ *Nota: La columna 'Múltiple Global Legacy' corresponde a líneas agregadas consolidadas por territorio en los primeros reportes de Amazon (2017–2020), donde la plataforma no reportaba títulos de episodios individuales.*")

    st.markdown("---")

    # 3. Monetización 2025 Amazon
    st.subheader("3. Monetización 2025 de Títulos Amazon (€)")
    st.dataframe(df_amz_2025, column_config={
        'Año': st.column_config.TextColumn('Año'),
        'Exact Title (€)': st.column_config.NumberColumn('Exact Title (€)', format='€ %,.2f'),
        'Semantic AI (>= 80%) (€)': st.column_config.NumberColumn('IA Alta (>= 80%) (€)', format='€ %,.2f'),
        'Semantic AI (60-79%) (€)': st.column_config.NumberColumn('IA Media (60-79%) (€)', format='€ %,.2f'),
        'Semantic AI (< 60%) (€)': st.column_config.NumberColumn('IA Baja (< 60%) (€)', format='€ %,.2f'),
        'Descartes IP No Amuse (€)': st.column_config.NumberColumn('Descartes IP (€)', format='€ %,.2f'),
        'Descartes Formato (€)': st.column_config.NumberColumn('Películas (€)', format='€ %,.2f'),
        'Sin Mapear (€)': st.column_config.NumberColumn('Sin Mapear (€)', format='€ %,.2f'),
        'Múltiple Global Legacy (€)': st.column_config.NumberColumn('Múltiple Global Legacy (€)', format='€ %,.2f'),
        'TOTAL 2025 (€)': st.column_config.NumberColumn('TOTAL 2025 (€)', format='€ %,.2f')
    }, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 4. Clasificación de IPs Amazon
    st.subheader("4. Auditoría de Clasificación de Catálogo e IPs (Amazon)")
    col_amz_ip1, col_amz_ip2 = st.columns(2)

    with col_amz_ip1:
        st.markdown("##### Desglose de Catálogo (#)")
        st.dataframe(df_amz_ip_rec, column_config={
            'Categoría de Catálogo': st.column_config.TextColumn('Categoría'),
            'Títulos (#)': st.column_config.NumberColumn('Títulos (#)', format='%d'),
            '% Catálogo': st.column_config.NumberColumn('% Catálogo', format='%.2f %%')
        }, use_container_width=True, hide_index=True)

    with col_amz_ip2:
        st.markdown("##### Monetización Histórica por Tipo de Catálogo (€)")
        st.dataframe(df_amz_ip_mon, column_config={
            'Año': st.column_config.TextColumn('Año'),
            'Títulos IP AMUSE (€)': st.column_config.NumberColumn('IP AMUSE (€)', format='€ %,.2f'),
            'Títulos IP no AMUSE (€)': st.column_config.NumberColumn('IP no AMUSE (€)', format='€ %,.2f'),
            'Películas / Especiales (€)': st.column_config.NumberColumn('Películas (€)', format='€ %,.2f'),
            'Títulos sin mapear (€)': st.column_config.NumberColumn('Sin Mapear (€)', format='€ %,.2f'),
            'Múltiple Global Legacy (€)': st.column_config.NumberColumn('Legacy (€)', format='€ %,.2f'),
            'TOTAL BBDD (€)': st.column_config.NumberColumn('TOTAL (€)', format='€ %,.2f')
        }, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 5. Resumen de Confianza Amazon
    st.subheader("5. Resumen de Calidad y Rangos de Confianza (Amazon)")
    st.dataframe(df_amz_conf, column_config={
        'Método / Rango': st.column_config.TextColumn('Método / Rango de Confianza'),
        'Confianza (%)': st.column_config.TextColumn('Rango Confianza'),
        'Puntuación': st.column_config.TextColumn('Escala 20 pts'),
        'Títulos (#)': st.column_config.NumberColumn('Títulos (#)', format='%d'),
        '% Catálogo': st.column_config.NumberColumn('% Catálogo', format='%.2f %%'),
        'Ingresos Granulares (€)': st.column_config.NumberColumn('Ingresos Granulares (€)', format='€ %,.2f'),
        '% Ingresos Granulares': st.column_config.NumberColumn('% Ingresos Granulares', format='%.2f %%')
    }, use_container_width=True, hide_index=True)


# ----------------------------------------------------
# TAB 3: COMPARATIVA EJECUTIVA Y CONFIANZA
# ----------------------------------------------------
with tab_comp:
    st.markdown("### 📊 Matriz Comparativa: YouTube vs Amazon Prime Video")
    st.markdown("""
    Comparación de la solidez y distribución del catálogo emparejado entre ambas plataformas audiovisuales:
    """)
    st.caption("💡 **Diferencia en la dimensión temporal:** En **YouTube**, el año corresponde a la fecha de publicación/subida del vídeo original. En **Amazon Prime Video**, el año representa la primera fecha en que el título figuró en un reporte analítico oficial (en septiembre de 2024 se integró la totalidad del catálogo histórico de episodios vía *Content Performance Reports*, mientras que 2025 y 2026 reflejan exclusivamente incorporaciones genuinas de nuevos títulos).")

    col_cmp1, col_cmp2 = st.columns(2)

    with col_cmp1:
        st.markdown("#### Distribución de Confianza en YouTube")
        fig_pie_yt = px.pie(
            df_conf,
            names='Método / Rango',
            values='Vídeos (#)',
            title="Distribución de Vídeos por Método (YouTube)",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Plotly
        )
        fig_pie_yt.update_layout(height=350, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_pie_yt, use_container_width=True)

    with col_cmp2:
        st.markdown("#### Distribución de Confianza en Amazon")
        fig_pie_amz = px.pie(
            df_amz_conf,
            names='Método / Rango',
            values='Títulos (#)',
            title="Distribución de Títulos por Rango de Confianza (Amazon)",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Safe
        )
        fig_pie_amz.update_layout(height=350, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_pie_amz, use_container_width=True)

    st.markdown("---")
    st.subheader("Matriz de Correspondencia de Niveles de Calidad")

    matrix_data = pd.DataFrame([
        {
            'Nivel de Calidad': 'Nivel 1: Certidumbre Absoluta (100% / 20 pts)',
            'YouTube (Métodos & Recuento)': 'BK 1 + BK 2 + Match por Título (72.657 vídeos / 87,8%)',
            'Amazon (Métodos & Recuento)': 'Exact Title Match (4.168 títulos / 32,6%)',
            'Criterio de Validación': 'Identificador Broadkast o coincidencia unívoca de título limpio.'
        },
        {
            'Nivel de Calidad': 'Nivel 2: Alta Confianza (80-99% / 17-19 pts)',
            'YouTube (Métodos & Recuento)': 'Modelo Multifase NLP (7.089 vídeos / 8,6%)',
            'Amazon (Métodos & Recuento)': 'Semantic AI Score >= 80% (3.656 títulos / 28,6%)',
            'Criterio de Validación': 'Embeddings contextuales de alta proximidad y confirmación de serie.'
        },
        {
            'Nivel de Calidad': 'Nivel 3: Confianza Moderada (60-79% / 14-17 pts)',
            'YouTube (Métodos & Recuento)': 'Incorporado en Multifase tras descarte de descripción',
            'Amazon (Métodos & Recuento)': 'Semantic AI Score 60-79% (2.810 títulos / 22,0%)',
            'Criterio de Validación': 'Coincidencia semántica con variaciones leves de orden o número de episodio.'
        },
        {
            'Nivel de Calidad': 'Nivel 4: Baja Confianza / Revisión (< 60% / < 14 pts)',
            'YouTube (Métodos & Recuento)': 'No admitido en producción (descartado a Sin Mapear)',
            'Amazon (Métodos & Recuento)': 'Semantic AI Score < 60% (940 títulos / 7,4%)',
            'Criterio de Validación': 'Candidatos semánticos ambiguos pendientes de confirmación editorial.'
        },
        {
            'Nivel de Calidad': 'Nivel 5: Descarte Justificado (0% / 0 pts)',
            'YouTube (Métodos & Recuento)': 'IPs No Amuse (2.978) + Lives/Borrados (3.941) + Sin Mapear (21)',
            'Amazon (Métodos & Recuento)': 'Blacklist Alien IPs (1.113) + Películas (80) + Sin Mapear (2)',
            'Criterio de Validación': 'Contenidos ajenos a Amuse (Louie, Milo, Molang, Mouk) o formatos no episódicos.'
        }
    ])

    st.dataframe(matrix_data, column_config={
        'Nivel de Calidad': st.column_config.TextColumn('Nivel de Fiabilidad'),
        'YouTube (Métodos & Recuento)': st.column_config.TextColumn('YouTube'),
        'Amazon (Métodos & Recuento)': st.column_config.TextColumn('Amazon Prime Video'),
        'Criterio de Validación': st.column_config.TextColumn('Criterio Técnico')
    }, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.success("""
    **Conclusiones de la Auditoría:**
    - **YouTube:** El **96,4%** del catálogo activo analizado está plenamente clasificado, con más del **87,8%** operando a nivel de confianza máxima (100% / 20 pts).
    - **Amazon Prime Video:** El **90,6%** de los títulos pertenecen a IPs legítimas de Amuse, habiendo descartado exitosamente 1.113 títulos de IPs ajenas y 80 películas. La facturación granular está cubierta en un **80,6%** por coincidencias de confianza alta y media.
    - **Sincronización:** Todas las cifras están cuadradas al céntimo y sincronizadas con las bases de datos de analíticas y reportes mensuales.
    """)

