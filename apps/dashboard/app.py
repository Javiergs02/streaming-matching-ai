# app.py
import sys
import os

# Asegurar que la raíz del proyecto y apps/dashboard estén en el PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DASHBOARD_ROOT = os.path.abspath(os.path.dirname(__file__))
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

import streamlit as st
from dotenv import load_dotenv
from utils.custom_dashboards import discover_custom_dashboards, make_html_page_renderer
from utils.styling import apply_portal_style

load_dotenv()


def render_home_page() -> None:
    """Renders the main Matching AI overview page."""
    st.set_page_config(page_title="Matching AI Dashboard", layout="wide", page_icon="🤖")
    apply_portal_style()

    st.title("Matching AI Dashboard - Motor de Mapeo e Inteligencia")
    st.markdown("---")

    st.markdown("""
    ### Ecosistema de Matching AI
    Bienvenido a la consola centralizada de **Matching AI**. Esta interfaz modular te permite auditar y monitorear los resultados de nuestro motor de IA diseñado para reconciliar y mapear catálogos de contenido entre múltiples plataformas (Amazon VOD, YouTube, Broadkast).

    Utiliza el **menú lateral izquierdo** para explorar los dashboards interactivos de rendimiento y los reportes de negocio.
    """)

    st.subheader("Motor de Matching y Procesamiento")
    with st.expander("Ver Arquitectura del Motor de Mapeo", expanded=True):
        st.markdown("""
        El núcleo del sistema de matching opera en tres capas consecutivas para garantizar la máxima precisión en el cruce de entidades (series, episodios, películas):
        
        #### 1. Mapeo Exacto (Exact Matching)
        * Realiza cruces directos mediante identificadores únicos y reglas estrictas.
        * Resolución inmediata de entidades con alta fiabilidad.
          
        #### 2. Mapeo Híbrido (Hybrid Matching)
        * Normaliza textos, elimina caracteres especiales y aplica heurísticas avanzadas.
        * Ideal para cruzar títulos que presentan ligeras variaciones entre plataformas (ej. "Episodio 1" vs "Ep 1").
          
        #### 3. Mapeo Semántico con IA (Semantic Matching)
        * Utiliza modelos de procesamiento de lenguaje natural (NLP) y embeddings para comparar el significado de los títulos.
        * Resuelve casos complejos donde los textos difieren significativamente pero representan el mismo contenido.
        """)

    st.subheader("Capacidades de Consulta del Sistema")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        #### Capa Relacional (PostgreSQL)
        **Propósito:** Catálogos, Metadatos y Mapeos del Ecosistema.
        
        Esta capa actúa como la fuente de la verdad para el catálogo estructurado. Contiene la información unificada de propiedades intelectuales, series, canales de YouTube y el resultado consolidado del motor de matching.
        
        **Casos de uso:**
        * Consultar metadatos de vídeos, países de origen y jerarquías de series.
        * Auditar qué entidades de Amazon han sido emparejadas con éxito a nuestro catálogo interno.
        """)

    with col2:
        st.markdown("""
        #### Almacén de Rendimiento (MongoDB)
        **Propósito:** Métricas, Analíticas y Eventos.
        
        MongoDB almacena las agregaciones de rendimiento mensuales y eventos procesados. Es la base de datos optimizada para las consultas de analíticas y reportes.
        
        **Casos de uso:**
        * Visualizar tendencias de visualizaciones (Views) y tiempo de retención (Watch Time).
        * Análisis financiero (Revenue) desglosado por país y plataforma (YouTube vs Amazon).
        """)

    st.markdown("---")

    st.markdown("""
    #### Módulos de la Plataforma
    * **Centro de Operaciones (Operaciones):** Panel de control interactivo para ejecutar la ingesta y sincronización de Amazon Prime Video (con Google Drive), la ingesta territorial y reconciliación contable de YouTube Analytics, y el mantenimiento de resúmenes en MongoDB.
    * **Estado Mapeado (Mapping Status):** Auditoría integral del catálogo de YouTube y Amazon Prime Video. Recuentos de vídeos y títulos desglosados por método de mapeo, rangos de porcentaje de confianza (100%, 80-99%, 60-79%, <60%), año de publicación y monetización histórica y reciente (€), junto con la clasificación de IPs Amuse vs descartes.
    * **Business Reports:** Consolidación y exportación de datos estratégicos. Combina la estructura del catálogo (PostgreSQL) con el histórico de rendimiento (MongoDB) para análisis financiero y operacional unificado.
    """)

    st.markdown("---")
    st.info("Nota para desarrollo: Los cambios en los archivos fuente se reflejarán automáticamente en esta interfaz interactiva.")


def build_navigation_pages() -> dict:
    """Builds built-in and hot-loaded custom pages for Streamlit `st.navigation`."""
    core_pages = [
        st.Page(render_home_page, title="Inicio", icon="🤖", url_path="inicio", default=True),
        st.Page("pages/business_reports.py", title="Business Reports", icon="📊", url_path="business_reports"),
        st.Page("pages/estado_mapeado.py", title="Estado Mapeado", icon="🎯", url_path="estado_mapeado"),
        st.Page("pages/operaciones.py", title="Operaciones", icon="🛠️", url_path="operaciones"),
    ]

    nav_sections: dict = {"Plataforma": core_pages}
    custom_entries = discover_custom_dashboards()
    if custom_entries:
        custom_pages = []
        for entry in custom_entries:
            if entry["kind"] == "py":
                custom_pages.append(
                    st.Page(
                        str(entry["path"]),
                        title=str(entry["title"]),
                        icon=str(entry["icon"]),
                        url_path=str(entry["url_path"]),
                    )
                )
            else:
                custom_pages.append(
                    st.Page(
                        make_html_page_renderer(entry["path"], str(entry["title"]), str(entry["slug"])),
                        title=str(entry["title"]),
                        icon=str(entry["icon"]),
                        url_path=str(entry["url_path"]),
                    )
                )
        nav_sections["Dashboards Adicionales"] = custom_pages

    return nav_sections


is_embedded = str(st.query_params.get("embed", "")).strip().lower() in ("1", "true", "yes")
pg = st.navigation(
    build_navigation_pages(),
    position="hidden" if is_embedded else "sidebar",
)
pg.run()