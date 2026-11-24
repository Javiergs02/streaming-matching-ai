# pages/mongodb_explorer.py
import re
import streamlit as st
import pandas as pd
from utils.connections import get_mongo_client
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="MongoDB Event Store Explorer", layout="wide", page_icon="🍃")

st.title("MongoDB Event Store Explorer")
st.markdown("---")

EVENTOS_POR_COLECCION = {
    "channel_events": [
        "youtube.channel.metadata_updated",
        "youtube.channel.removed"
    ],
    "diffusion_events": [
        "diffusion.succeeded",
        "diffusion.failed",
        "diffusion.planned"
    ],
    "video_events": [
        "youtube.video.metadata_updated",
        "youtube.video.linked",
        "youtube.video.removed"
    ],
    "video_performance_events": [
        "youtube.video.performance_recorded",
        "amazon.video.performance_svod",
        "amazon.video.performance_tvod"
    ]
}

with st.expander("📖 Ver Documentación y Arquitectura del Esquema de Eventos", expanded=False):
    st.image("images/MongoDB_collections.png", caption="Estructura de PlatformEventsDB y colecciones de eventos inmutables", use_column_width=True)

    st.markdown("""
    ### Arquitectura del Event Store
    El almacén de datos transaccional opera bajo un patrón de **Event Sourcing**, registrando cada cambio de estado o sincronización externa como un documento inmutable. 

    Esta capa de persistencia actúa como la fuente de verdad primaria para estudios exhaustivos de tendencias y auditorías, capturando el volumen masivo de trazas que posteriormente son procesadas por la capa relacional en PostgreSQL.
    """)

    st.subheader("Catálogo de Eventos por Colección")

    tabs_doc = st.tabs(["Channel Events", "Diffusion Events", "Video Events", "Video Performance Events"])

    with tabs_doc[0]:
        st.markdown("**Colección:** `channel_events` | Ciclo de vida y metadatos de canales.")
        st.markdown("#### 🔹 `youtube.channel.metadata_updated` [382 eventos]")
        st.json({
          "metadata": { "event_type": "youtube.channel.metadata_updated", "resource_id": "UC8oFc4QAqmGK_ErROMB-RqQ" },
          "payload": { "changes": { "description": { "before": "...", "after": "..." } } }
        })
        st.markdown("#### 🔹 `youtube.channel.removed` [43 eventos]")
        st.json({ "payload": { "status": "unlinked", "reason": "Not found in YouTube API fetch" } })

    with tabs_doc[1]:
        st.markdown("**Colección:** `diffusion_events` | Tareas operacionales de distribución asíncrona.")
        st.markdown("#### 🔹 `diffusion.succeeded` [1.706.976 eventos]")
        st.json({ "metadata": { "event_type": "diffusion.succeeded" }, "payload": { "status": "completed" } })
        st.markdown("#### 🔹 `diffusion.failed` [316.638 eventos]")
        st.json({ "payload": { "diffusion_id": "39189", "error_reason": "Timeout" } })
        st.markdown("#### 🔹 `diffusion.planned` [3.087 eventos]")
        st.json({ "payload": { "diffusion_id": "42931", "episodes": [{"series_code": "SPSH"}] } })

    with tabs_doc[2]:
        st.markdown("**Colección:** `video_events` | Mapeo estructural de elementos de vídeo.")
        st.markdown("#### 🔹 `youtube.video.metadata_updated` [179.629 eventos]")
        st.json({ "payload": { "title": "Der Kipplaster (Updated Version)" } })
        st.markdown("#### 🔹 `youtube.video.linked` [9.981 eventos]")
        st.json({ "payload": { "video_id": "EzB2S_QQny0", "title": "Der Kipplaster" } })
        st.markdown("#### 🔹 `youtube.video.removed` [5.877 eventos]")
        st.json({ "payload": { "status": "unlinked" } })

    with tabs_doc[3]:
        st.markdown("**Colección:** `video_performance_events` | Alta volumetría analítica.")
        st.markdown("#### 🔹 `youtube.video.performance_recorded` [116.771.225 eventos]")
        st.json({ "payload": { "video_id": "-0CqA-LbBAY", "estimated_revenue": 3.374, "extra_metrics": { "views": 2264 } } })
        st.markdown("#### 🔹 `amazon.video.performance_svod` [3.232 eventos]")
        st.json({ "payload": { "estimated_revenue": 0.11, "extra_metrics": { "amazon_stream_type": "SVOD" } } })
        st.markdown("#### 🔹 `amazon.video.performance_tvod` [363 eventos]")
        st.json({ "payload": { "estimated_revenue": 0.42, "extra_metrics": { "amazon_stream_type": "TVOD" } } })

st.markdown("---")
db_mongo = get_mongo_client()

if db_mongo is not None:
    st.subheader("Consola de Inspección de Eventos")
    
    available_collections = db_mongo.list_collection_names()
    default_index = available_collections.index("video_performance_events") if "video_performance_events" in available_collections else 0
    collection_name = st.selectbox("Seleccione Colección Principal:", available_collections, index=default_index)
    
    eventos_validos = EVENTOS_POR_COLECCION.get(collection_name, [])
    opciones_filtro = ["Mostrar todos los tipos de evento"] + eventos_validos
    event_filter = st.selectbox("Filtrar por Tipo de Evento (metadata.event_type):", opciones_filtro)
    
    st.markdown("##### Filtros Avanzados de Utilidad Operativa")
    col_id, col_fecha, col_limite = st.columns([2, 2, 1])
    
    with col_id:
        if collection_name == "diffusion_events":
            search_id = st.text_input("Buscar por ID de Difusión (diffusion_id):", placeholder="Ej: 42931").strip()
        else:
            search_id = st.text_input("Buscar por ID de Vídeo (video_id):", placeholder="Ej: -0CqA-LbBAY").strip()
            
    with col_fecha:
        ventana_temporal = st.selectbox(
            "Ventana Temporal Operativa:",
            ["Sin restricción de fecha", "Últimas 24 horas", "Últimos 7 días", "Mes específico (Ingresar en filtro)"]
        )
        
        mes_filtro = ""
        if ventana_temporal == "Mes específico (Ingresar en filtro)":
            mes_filtro = st.text_input("Año y Mes del Payload (YYYY-MM):", placeholder="Ej: 2026-02").strip()

    with col_limite:
        limit_mongo = st.slider("Límite de registros:", 10, 500, 50)
        
    if st.button("Ejecutar Consulta Estratégica"):
        coll = db_mongo[collection_name]
        query = {}
        
        if search_id:
            if collection_name == "diffusion_events":
                query["payload.diffusion_id"] = search_id
            else:
                query["payload.video_id"] = search_id
                
        else:
            if event_filter != "Mostrar todos los tipos de evento":
                query["metadata.event_type"] = event_filter
                
            ahora = datetime.now(timezone.utc)
            
            if ventana_temporal == "Últimas 24 horas":
                limite_tiempo = ahora - timedelta(days=1)
                query["metadata.occurred_at"] = {"$gte": limite_tiempo.isoformat()}
            elif ventana_temporal == "Últimos 7 días":
                limite_tiempo = ahora - timedelta(days=7)
                query["metadata.occurred_at"] = {"$gte": limite_tiempo.isoformat()}
            elif ventana_temporal == "Mes específico (Ingresar en filtro)" and mes_filtro:
                clean_mes = str(mes_filtro).strip()
                if re.match(r"^\d{4}-\d{2}$", clean_mes):
                    query["payload.date"] = {"$regex": f"^{clean_mes}"}
                else:
                    query["payload.date"] = {"$regex": f"^{re.escape(clean_mes)}"}

        try:
            with st.spinner("Buscando en el Event Store de forma indexada..."):
                if collection_name == "video_performance_events" and "payload.date" in query:
                    docs = list(coll.find(query).sort("payload.date", -1).limit(limit_mongo))
                elif "metadata.occurred_at" in query:
                    docs = list(coll.find(query).sort("metadata.occurred_at", -1).limit(limit_mongo))
                else:
                    docs = list(coll.find(query).limit(limit_mongo))
                
            if docs:
                # Normalizar ObjectId para serialización JSON segura (Fix M30)
                for d in docs:
                    if "_id" in d:
                        d["_id"] = str(d["_id"])

                st.success(f"Éxito operacional: {len(docs)} documentos recuperados.")
                mode = st.radio("Formato de salida:", ["Tabla Normalizada (Operaciones)", "JSON Estructural (Sistemas)"], horizontal=True)
                
                if mode == "Tabla Normalizada (Operaciones)":
                    st.dataframe(pd.json_normalize(docs), use_container_width=True)
                else:
                    st.json(docs)
            else:
                st.warning("No se encontraron eventos que coincidan con los parámetros especificados.")
                
        except Exception as e:
            st.error(f"Error crítico en la consulta a la base de datos: {e}")