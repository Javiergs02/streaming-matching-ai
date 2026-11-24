# apps/dashboard/pages/operaciones.py
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import streamlit as st

# Asegurar que la raíz del proyecto y apps/dashboard estén en el PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DASHBOARD_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

from utils.styling import apply_portal_style
from core.ingestion.update_service import (
    get_available_amazon_months,
    get_default_update_months,
    is_update_in_progress,
    run_amazon_update
)
from core.ingestion.youtube_update_service import (
    get_available_youtube_years,
    get_default_youtube_months,
    is_youtube_update_in_progress,
    run_youtube_update
)
from core.ingestion.china_update_service import (
    get_available_china_platforms,
    is_china_update_in_progress,
    run_china_update
)

st.set_page_config(page_title="Centro de Operaciones", layout="wide", page_icon="🛠️")
apply_portal_style()

st.title("🛠️ Centro de Control y Operaciones de Datos")
st.markdown("""
Panel interactivo para la ejecución y mantenimiento de los pipelines de datos de **Amazon Prime Video**, **YouTube Analytics** y **Plataformas Chinas (Tencent, Youku, iQIYI)**.
Permite a cualquier miembro del equipo sincronizar reportes desde Google Drive o APIs oficiales, reconciliar ingresos territoriales y reconstruir resúmenes analíticos en MongoDB con un solo clic.
""")
st.markdown("---")

tab_amz, tab_yt, tab_china, tab_maint = st.tabs([
    "📦 Amazon Prime Video (Pipeline E2E)",
    "📺 YouTube Analytics (Territorial & CPM)",
    "🇨🇳 Plataformas Chinas (Tencent, Youku, iQIYI)",
    "📊 Mantenimiento de Agregaciones y Caché"
])

# ==============================================================================
# PESTAÑA 1: AMAZON PRIME VIDEO
# ==============================================================================
with tab_amz:
    st.subheader("📦 Pipeline de Ingesta y Reconciliación de Amazon")
    st.markdown("""
    **Operativa Mensual:**
    Conecta con la carpeta oficial de **Google Drive** corporativa, descarga los nuevos reportes de rendimiento y regalías, ejecuta el motor de IA de títulos contra Broadkast y actualiza MongoDB.
    """)

    available_amz_months = get_available_amazon_months()
    default_3_months = get_default_update_months(3)

    col_amz_left, col_amz_right = st.columns([1, 1])

    with col_amz_left:
        opcion_periodo_amz = st.selectbox(
            "Periodo de Amazon a procesar:",
            [
                "Últimos 3 meses (Por defecto)",
                "Último mes cerrado",
                "Últimos 6 meses",
                "Último año (12 meses)",
                "Personalizado (Seleccionar meses)",
                "Histórico completo (--all)"
            ],
            index=0,
            key="ops_amz_period_option"
        )

        if opcion_periodo_amz == "Últimos 3 meses (Por defecto)":
            meses_amz_final = default_3_months
        elif opcion_periodo_amz == "Último mes cerrado":
            meses_amz_final = default_3_months[-1:] if default_3_months else []
        elif opcion_periodo_amz == "Últimos 6 meses":
            meses_amz_final = get_default_update_months(6)
        elif opcion_periodo_amz == "Último año (12 meses)":
            meses_amz_final = get_default_update_months(12)
        elif opcion_periodo_amz == "Histórico completo (--all)":
            meses_amz_final = available_amz_months
        else:
            meses_amz_final = st.multiselect(
                "Selecciona los meses específicos de Amazon:",
                options=available_amz_months,
                default=default_3_months,
                key="ops_amz_custom_months"
            )

        st.info(f"📅 **Meses seleccionados:** `{', '.join(meses_amz_final) if meses_amz_final else 'Ninguno'}`")

    with col_amz_right:
        st.markdown("##### Opciones de Ejecución")
        sync_drive_amz = st.checkbox(
            "Sincronizar automáticamente desde Google Drive",
            value=True,
            help="Descarga archivos nuevos de la carpeta oficial de Google Drive antes de procesar.",
            key="ops_amz_sync_drive"
        )
        offline_amz = st.checkbox(
            "Modo sin conexión (utilizar únicamente caché local)",
            value=not sync_drive_amz,
            key="ops_amz_offline"
        )

        # Control de concurrencia
        amz_busy, amz_info = is_update_in_progress()
        if amz_busy:
            st.warning(f"⏳ **Hay una actualización de Amazon en curso** iniciada a las {(amz_info or {}).get('started_at', 'hace un momento')}. El botón permanecerá bloqueado hasta que finalice.")
            btn_run_amz = st.button("🚀 Iniciar Pipeline de Amazon", type="primary", use_container_width=True, disabled=True, key="btn_amz_busy")
        else:
            btn_run_amz = st.button("🚀 Iniciar Pipeline de Amazon", type="primary", use_container_width=True, key="btn_amz_run")

    if btn_run_amz:
        if not meses_amz_final:
            st.warning("⚠️ Debes seleccionar al menos un mes para procesar.")
        else:
            with st.status(f"Ejecutando pipeline de Amazon para {len(meses_amz_final)} mes(es)...", expanded=True) as status_box:
                log_placeholder = st.empty()
                log_lines = []

                def amz_ui_logger(msg):
                    log_lines.append(f"• {msg}")
                    log_placeholder.markdown("\n".join(log_lines[-10:]))

                res = run_amazon_update(
                    target_months=meses_amz_final,
                    sync_drive=(not offline_amz),
                    log_callback=amz_ui_logger
                )

                if res.get("success"):
                    status_box.update(label="✅ ¡Pipeline de Amazon finalizado con éxito!", state="complete", expanded=False)
                    st.success(f"🎉 Se han procesado e inyectado en MongoDB las métricas de Amazon para los meses: **{', '.join(meses_amz_final)}**.")
                    st.cache_data.clear()
                elif res.get("busy"):
                    status_box.update(label="⚠️ Operación concurrente bloqueada", state="error", expanded=True)
                    st.warning(res.get("message"))
                else:
                    status_box.update(label="❌ Error durante la ejecución del pipeline", state="error", expanded=True)
                    st.error("Ocurrió un error. Revisa los registros detallados arriba.")


# ==============================================================================
# PESTAÑA 2: YOUTUBE ANALYTICS
# ==============================================================================
with tab_yt:
    st.subheader("📺 Ingesta Territorial y Reconciliación de YouTube")
    st.markdown("""
    **Operativa Territorial:**
    Descarga la audiencia por país desde la API de YouTube Analytics, aplica el reparto de facturación ponderado por **CPM real de cada territorio** y concilia los ingresos al céntimo exacto en MongoDB.
    """)

    available_yt_years = get_available_youtube_years()
    default_3_yt_months = get_default_youtube_months(3)

    col_yt_left, col_yt_right = st.columns([1, 1])

    with col_yt_left:
        # Selector de periodo homologado con el de Amazon
        opcion_periodo_yt = st.selectbox(
            "Periodo de YouTube a procesar:",
            [
                "Últimos 3 meses (Por defecto)",
                "Último mes cerrado",
                "Últimos 6 meses",
                "Último año (12 meses)",
                "Año específico (Completo)",
                "Personalizado (Seleccionar años/meses)",
                "Histórico completo (--full-history)"
            ],
            index=0,
            key="ops_yt_period_option"
        )

        target_year_yt = None
        custom_years_yt = None
        custom_months_yt = None

        if opcion_periodo_yt == "Año específico (Completo)":
            target_year_yt = st.selectbox(
                "Selecciona el año completo a procesar y reconciliar:",
                options=list(reversed(available_yt_years)),
                index=1 if len(available_yt_years) > 1 else 0,
                key="ops_yt_single_year"
            )
            st.info(f"📅 **Año objetivo:** `{target_year_yt}` (12 meses de enero a diciembre)")

        elif opcion_periodo_yt == "Personalizado (Seleccionar años/meses)":
            custom_years_yt = st.multiselect(
                "Selecciona los años a procesar:",
                options=list(reversed(available_yt_years)),
                default=[available_yt_years[-2]] if len(available_yt_years) > 1 else [available_yt_years[-1]],
                key="ops_yt_custom_years"
            )
            st.info(f"📅 **Años seleccionados:** `{', '.join(custom_years_yt) if custom_years_yt else 'Ninguno'}`")

        elif opcion_periodo_yt == "Histórico completo (--full-history)":
            st.warning("⚠️ **Atención:** El modo histórico completo descargará todos los meses desde 2016 hasta hoy. Esta operación puede demorarse entre 1 y 2 horas debido a los límites de cuota de la API de Google.")

        else:
            # Opciones de meses relativos
            if opcion_periodo_yt == "Último mes cerrado":
                months_yt_disp = default_3_yt_months[-1:]
            elif opcion_periodo_yt == "Últimos 6 meses":
                months_yt_disp = get_default_youtube_months(6)
            elif opcion_periodo_yt == "Último año (12 meses)":
                months_yt_disp = get_default_youtube_months(12)
            else:
                months_yt_disp = default_3_yt_months

            st.info(f"📅 **Meses a procesar:** `{', '.join(months_yt_disp)}`")

    with col_yt_right:
        st.markdown("##### Pasos que se Ejecutarán Secuencialmente")
        st.caption("""
        1. **Descarga Territorial:** Consulta `dimensions='video,country'` en YouTube API.
        2. **Perfil de CPM:** Consulta `dimensions='country'` y pondera $\\text{Views} \\times \\text{CPM}$.
        3. **Reconciliación Contable:** Sella ingresos en `monthly_performance_summaries`.
        4. **Agregaciones:** Reconstruye colecciones mensuales y anuales en MongoDB.
        """)

        # Control de concurrencia de YouTube
        yt_busy, yt_info = is_youtube_update_in_progress()
        if yt_busy:
            st.warning(f"⏳ **Hay una actualización de YouTube en curso** iniciada a las {(yt_info or {}).get('started_at', 'hace un momento')}. El botón permanecerá bloqueado hasta que finalice.")
            btn_run_yt = st.button("🚀 Iniciar Ingesta y Reconciliación de YouTube", type="primary", use_container_width=True, disabled=True, key="btn_yt_busy")
        else:
            btn_run_yt = st.button("🚀 Iniciar Ingesta y Reconciliación de YouTube", type="primary", use_container_width=True, key="btn_yt_run")

    if btn_run_yt:
        with st.status("Ejecutando proceso de YouTube (Ingesta territorial + Reconciliación contable)...", expanded=True) as status_yt:
            log_yt_placeholder = st.empty()
            log_yt_lines = []

            def yt_ui_logger(msg):
                log_yt_lines.append(f"• {msg}")
                log_yt_placeholder.markdown("\n".join(log_yt_lines[-10:]))

            res_yt = run_youtube_update(
                period_option=opcion_periodo_yt,
                target_year=target_year_yt,
                custom_years=custom_years_yt,
                log_callback=yt_ui_logger
            )

            if res_yt.get("success"):
                status_yt.update(label="✅ ¡Ingesta y reconciliación de YouTube finalizadas con éxito!", state="complete", expanded=False)
                st.success(f"🎉 Se han procesado, reconciliado y agregado las métricas territoriales de YouTube para el periodo: **{opcion_periodo_yt}**.")
                st.cache_data.clear()
            elif res_yt.get("busy"):
                status_yt.update(label="⚠️ Operación concurrente bloqueada", state="error", expanded=True)
                st.warning(res_yt.get("message"))
            else:
                status_yt.update(label="❌ Error durante el proceso de YouTube", state="error", expanded=True)
                st.error("Ocurrió un error. Revisa los registros detallados arriba.")


# ==============================================================================
# PESTAÑA 3: PLATAFORMAS CHINAS (TENCENT, YOUKU, iQIYI)
# ==============================================================================
with tab_china:
    st.subheader("🇨🇳 Pipeline de Ingesta y Sincronización de Plataformas Chinas")
    st.markdown("""
    **Operativa Periódica:**
    Sincroniza los datasets de liquidación y rendimiento desde **Google Drive** (carpetas de Tencent, Youku e iQIYI), procesa los libros Excel (AVOD y SVOD), convierte y unifica ingresos en RMB (CNY) y USD, e impacta directamente en las colecciones analíticas de MongoDB.
    """)

    col_cn_left, col_cn_right = st.columns([1, 1])

    with col_cn_left:
        opcion_plataforma_cn = st.selectbox(
            "Plataformas a procesar:",
            get_available_china_platforms(),
            index=0,
            key="ops_cn_platform_choice"
        )
        st.info(f"🇨🇳 **Plataforma seleccionada:** `{opcion_plataforma_cn}`")

    with col_cn_right:
        st.markdown("##### Opciones de Ejecución")
        sync_drive_cn = st.checkbox(
            "Sincronizar automáticamente desde Google Drive",
            value=True,
            help="Descarga archivos nuevos de las carpetas de Google Drive configuradas en .env antes de procesar.",
            key="ops_cn_sync_drive"
        )
        dry_run_cn = st.checkbox(
            "Modo Dry-Run (Solo auditoría y resumen, sin escribir en MongoDB)",
            value=False,
            help="Parsea los archivos y muestra el resumen de ingresos y views sin modificar MongoDB.",
            key="ops_cn_dry_run"
        )

        cn_busy, cn_info = is_china_update_in_progress()
        if cn_busy:
            st.warning(f"⏳ **Hay una actualización de plataformas chinas en curso** iniciada a las {(cn_info or {}).get('started_at', 'hace un momento')}.")
            btn_run_cn = st.button("🚀 Iniciar Pipeline de Plataformas Chinas", type="primary", use_container_width=True, disabled=True, key="btn_cn_busy")
        else:
            btn_run_cn = st.button("🚀 Iniciar Pipeline de Plataformas Chinas", type="primary", use_container_width=True, key="btn_cn_run")

    if btn_run_cn:
        with st.status("Ejecutando pipeline de plataformas chinas...", expanded=True) as status_cn:
            log_cn_placeholder = st.empty()
            log_cn_lines = []

            def cn_ui_logger(msg):
                log_cn_lines.append(f"• {msg}")
                log_cn_placeholder.markdown("\n".join(log_cn_lines[-35:]))

            res_cn = run_china_update(
                platform_choice=opcion_plataforma_cn,
                sync_drive=sync_drive_cn,
                dry_run=dry_run_cn,
                log_callback=cn_ui_logger
            )

            if res_cn.get("success"):
                status_cn.update(label="✅ ¡Pipeline de plataformas chinas finalizado con éxito!", state="complete", expanded=False)
                st.success(f"🎉 Se han procesado y consolidado los datos en MongoDB para: **{opcion_plataforma_cn}**.")
                st.cache_data.clear()
            elif res_cn.get("busy"):
                status_cn.update(label="⚠️ Operación concurrente bloqueada", state="error", expanded=True)
                st.warning(res_cn.get("message"))
            else:
                status_cn.update(label="❌ Error durante el proceso de plataformas chinas", state="error", expanded=True)
                st.error("Ocurrió un error. Revisa los registros detallados arriba.")


# ==============================================================================
# PESTAÑA 4: MANTENIMIENTO DE AGREGACIONES Y CACHÉ
# ==============================================================================
with tab_maint:
    st.subheader("📊 Mantenimiento Rápido de Agregaciones y Caché")
    st.markdown("""
    Esta sección permite forzar la reconstrucción de las colecciones analíticas en MongoDB y actualizar las cachés locales del Dashboard **sin consultar APIs externas ni descargar datos adicionales**.
    """)

    col_m1, col_m2, col_m3 = st.columns(3)

    with col_m1:
        st.markdown("##### Resúmenes de MongoDB")
        st.caption("Reconstruye `monthly_performance_summaries` y `yearly_performance_summaries` a partir de los eventos existentes.")
        btn_rebuild_mongo = st.button("⚡ Reconstruir Todo MongoDB (--all)", use_container_width=True, key="btn_rebuild_mongo")
        if btn_rebuild_mongo:
            with st.status("Reconstruyendo agregaciones en MongoDB...", expanded=True) as st_mb:
                root_path = Path(PROJECT_ROOT)
                py_path = sys.executable
                st.write("• Ejecutando build_monthly_aggregations.py --all...")
                res_m = subprocess.run([py_path, str(root_path / "scripts" / "build_monthly_aggregations.py"), "--all"], capture_output=True, text=True, check=False)
                st.write("• Ejecutando build_yearly_aggregations.py --all...")
                res_y = subprocess.run([py_path, str(root_path / "scripts" / "build_yearly_aggregations.py"), "--all"], capture_output=True, text=True, check=False)
                
                if res_m.returncode == 0 and res_y.returncode == 0:
                    st_mb.update(label="✅ ¡Agregaciones de MongoDB reconstruidas!", state="complete", expanded=False)
                    st.success("Colecciones de resúmenes mensuales y anuales actualizadas al 100%.")
                else:
                    st_mb.update(label="❌ Error al reconstruir agregaciones de MongoDB", state="error", expanded=True)
                    st.error(f"Fallo en la reconstrucción (mensual={res_m.returncode}, anual={res_y.returncode})")
                    if res_m.stderr: st.code(res_m.stderr[-500:], language="bash")
                    if res_y.stderr: st.code(res_y.stderr[-500:], language="bash")
                st.cache_data.clear()

    with col_m2:
        st.markdown("##### Caché de Estado Mapeado")
        st.caption("Regenera `amazon_mapping_stats.json` a partir de `production_mappings.csv` y los reportes analíticos generados.")
        btn_rebuild_cache = st.button("🎯 Regenerar Caché de Mapeo", use_container_width=True, key="btn_rebuild_cache")
        if btn_rebuild_cache:
            with st.status("Regenerando caché de auditoría...", expanded=True) as st_cb:
                root_path = Path(PROJECT_ROOT)
                py_path = sys.executable
                res_c = subprocess.run([py_path, str(root_path / "scripts" / "generate_amazon_mapping_cache.py")], capture_output=True, text=True, check=False)
                if res_c.returncode == 0:
                    st_cb.update(label="✅ ¡Caché de mapeo actualizada!", state="complete", expanded=False)
                    st.success("Archivo `data/cache/amazon_mapping_stats.json` actualizado.")
                else:
                    st_cb.update(label="❌ Error al regenerar caché de mapeo", state="error", expanded=True)
                    st.error(f"Fallo en la regeneración de caché (código: {res_c.returncode})")
                    if res_c.stderr: st.code(res_c.stderr[-500:], language="bash")
                st.cache_data.clear()

    with col_m3:
        st.markdown("##### Caché de Navegador / Sesión")
        st.caption("Limpia la memoria caché en memoria (`@st.cache_data`) del dashboard para forzar la recarga de consultas SQL y MongoDB.")
        btn_clear_st = st.button("🧹 Limpiar Caché de Streamlit", use_container_width=True, key="btn_clear_st")
        if btn_clear_st:
            st.cache_data.clear()
            st.success("¡Memoria caché de Streamlit limpiada con éxito!")

