# pages/postgres_sql.py
import io
import streamlit as st
import pandas as pd
from psycopg2 import sql
from utils.connections import get_postgres_connection

ALLOWED_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "ILIKE"}

st.set_page_config(page_title="PostgreSQL Explorer", layout="wide", page_icon="🐘")

st.title("PostgreSQL Relational State Explorer")
st.markdown("---")

with st.expander("Ver Diagrama de Entidad-Relación (ER) y Reglas de Integridad"):
    st.markdown("### Topología de Datos de Contenido (amuseplatforms_db)")
    try:
        st.image("images/PSQL_DB.png", use_column_width=True)
    except Exception as e:
        st.warning(f"No se pudo renderizar el diagrama estático database_schema.png: {e}")

@st.cache_data
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    return output.getvalue()

TABLAS_CORE = [
    "amuseplatforms_db.projects",
    "amuseplatforms_db.series",
    "amuseplatforms_db.episodes",
    "amuseplatforms_db.countries",
    "amuseplatforms_db.youtube_channels",
    "amuseplatforms_db.youtube_videos",
    "amuseplatforms_db.episode_youtube_video"
]

CAMPOS_CON_DESPLEGABLE = [
    "project_code", "series_code", "language_code", "country_code", 
    "region_code", "channel_id", "language", "privacy_status", "category_id",
    "default_audio_language"
]

if "filtros_activos" not in st.session_state:
    st.session_state.filtros_activos = []

@st.cache_data(ttl=300)
def obtener_valores_unicos(table, column):
    conn = get_postgres_connection()
    # Si la conexión de la caché está rota o cerrada internamente, forzamos refresco
    if not conn or conn.closed != 0:
        st.cache_resource.clear()
        conn = get_postgres_connection()
    if not conn:
        return []
    with conn.cursor() as cur:
        try:
            # SQL Identifier escaping to prevent injection (Fix C12)
            query = sql.SQL("SELECT DISTINCT {col} FROM {tbl} WHERE {col} IS NOT NULL ORDER BY {col};").format(
                col=sql.Identifier(column),
                tbl=sql.SQL(table) if "." in table else sql.Identifier(table)
            )
            cur.execute(query)
            return [str(row[0]) for row in cur.fetchall()]
        except:
            conn.rollback()
            return []

# --- CONTROL DE CONEXIÓN ROBUSTA DE PRODUCCIÓN ---
db_psql = get_postgres_connection()

# Si la conexión extraída está muerta (closed != 0), limpiamos la caché del recurso para levantar un socket nuevo
if db_psql is not None and db_psql.closed != 0:
    st.cache_resource.clear()
    db_psql = get_postgres_connection()

if db_psql and db_psql.closed == 0:
    st.sidebar.header("Data Controls")
    selected_table = st.sidebar.selectbox("1. Elige una tabla base:", TABLAS_CORE)
    
    if "ultima_tabla" not in st.session_state or st.session_state.ultima_tabla != selected_table:
        st.session_state.filtros_activos = []
        st.session_state.ultima_tabla = selected_table
        st.session_state.df_resultado = None
        st.session_state.excel_data_to_download = None
        st.session_state.last_report_id = None

    st.sidebar.markdown("---")
    st.sidebar.subheader("Volumen de Datos")
    limit_val = st.sidebar.number_input("Límite de filas:", min_value=1, max_value=1000000, value=1000, step=500)
    traer_todo = st.sidebar.checkbox("Desbloquear: Traer todo", help="Ignora el límite numérico superior.")

    st.subheader(f"Configuración de Filtros para: {selected_table}")
    
    columnas_tipos = {}
    if "." in selected_table:
        schema_part, table_part = selected_table.split(".")
    else:
        schema_part, table_part = "amuseplatforms_db", selected_table

    # Bloque protegido para extraer el esquema estructural de la tabla elegida
    try:
        with db_psql.cursor() as cursor:
            cursor.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position;
            """, (schema_part, table_part))
            
            rows = cursor.fetchall()
            for row in rows:
                if len(row) >= 2:
                    columnas_tipos[row[0]] = row[1]
    except Exception as e:
        st.error(f"Error estructural al leer columnas: {e}")
        db_psql.rollback()

    columnas_disponibles = list(columnas_tipos.keys())

    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        if st.button("Añadir Filtro", use_container_width=True):
            if columnas_disponibles:
                st.session_state.filtros_activos.append({"columna": columnas_disponibles[0], "operador": "=", "valor": ""})
    with col_btn2:
        if st.button("Limpiar todos los filtros", use_container_width=False):
            st.session_state.filtros_activos = []
            st.session_state.excel_data_to_download = None
            st.session_state.df_resultado = None
            st.rerun()

    with st.form("form_filtros_postgres"):
        filtros_a_aplicar = []
        
        if not st.session_state.filtros_activos:
            st.info("Presiona 'Añadir Filtro' arriba para segmentar los datos, o ejecuta directamente para ver la tabla completa.")
        
        for i, filtro in enumerate(st.session_state.filtros_activos):
            st.markdown(f"**Condición combinada AND #{i+1}**")
            c1, c2, c3 = st.columns([3, 2, 4])
            
            with c1:
                idx_col = columnas_disponibles.index(filtro["columna"]) if filtro["columna"] in columnas_disponibles else 0
                col_sel = st.selectbox(f"Columna #{i}", columnas_disponibles, index=idx_col, key=f"col_{i}", label_visibility="collapsed")
            
            tipo_real = columnas_tipos.get(col_sel, "text")
            
            if col_sel in CAMPOS_CON_DESPLEGABLE:
                operadores_disponibles = ["=", "!="]
                with c2:
                    op_sel = st.selectbox(f"Op #{i}", operadores_disponibles, key=f"op_{i}", label_visibility="collapsed")
                valores_reales = obtener_valores_unicos(selected_table, col_sel)
                with c3:
                    if valores_reales:
                        val_sel = st.selectbox(f"Val #{i}", valores_reales, key=f"val_{i}", label_visibility="collapsed")
                    else:
                        val_sel = st.text_input(f"Escribe #{i}", key=f"val_{i}", label_visibility="collapsed")

            elif "bool" in tipo_real:
                operadores_disponibles = ["="]
                with c2:
                    op_sel = st.selectbox(f"Op #{i}", operadores_disponibles, key=f"op_{i}", label_visibility="collapsed")
                with c3:
                    val_sel = st.selectbox(f"Val #{i}", ["true", "false"], key=f"val_{i}", label_visibility="collapsed")

            elif "int" in tipo_real or "num" in tipo_real or "doub" in tipo_real:
                operadores_disponibles = ["=", "!=", ">", "<", ">=", "<="]
                with c2:
                    op_sel = st.selectbox(f"Op #{i}", operadores_disponibles, key=f"op_{i}", label_visibility="collapsed")
                with c3:
                    val_sel = st.number_input(f"Val #{i}", step=1, key=f"val_{i}", label_visibility="collapsed")
                    val_sel = str(val_sel)

            else:
                operadores_disponibles = ["=", "LIKE", "!="]
                with c2:
                    op_sel = st.selectbox(f"Op #{i}", operadores_disponibles, key=f"op_{i}", label_visibility="collapsed")
                with c3:
                    val_sel = st.text_input(f"Texto #{i}", placeholder="Buscar texto...", key=f"val_{i}", label_visibility="collapsed")

            st.session_state.filtros_activos[i] = {"columna": col_sel, "operador": op_sel, "valor": val_sel}
            if val_sel.strip():
                filtros_a_aplicar.append({"columna": col_sel, "operador": op_sel, "valor": val_sel.strip()})
        
        st.markdown("---")
        submit_button = st.form_submit_button("Consultar Base de Datos", use_container_width=True)

    if submit_button:
        # Doble verificación de seguridad de socket antes de lanzar transacciones analíticas pesadas
        if db_psql.closed != 0:
            st.cache_resource.clear()
            db_psql = get_postgres_connection()

        try:
            try: db_psql.rollback()
            except: pass
            
            with db_psql.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY;")
                tbl_part = sql.SQL(selected_table) if "." in selected_table else sql.Identifier(selected_table)
                query_parts = [sql.SQL("SELECT * FROM {tbl}").format(tbl=tbl_part)]
                params = []
                
                if filtros_a_aplicar:
                    where_clauses = []
                    for f in filtros_a_aplicar:
                        op = f['operador'] if f['operador'] in ALLOWED_OPERATORS else '='
                        where_clauses.append(sql.SQL("{col} " + op + " %s").format(col=sql.Identifier(f['columna'])))
                        params.append(f['valor'])
                    query_parts.append(sql.SQL("WHERE") + sql.SQL(" AND ").join(where_clauses))
                
                if not traer_todo:
                    query_parts.append(sql.SQL("LIMIT %s"))
                    params.append(int(limit_val))
                else:
                    # Techo de seguridad para evitar crashes por OOM (Fix C15)
                    query_parts.append(sql.SQL("LIMIT 50000"))
                
                final_query = sql.SQL(" ").join(query_parts)
                cursor.execute(final_query, tuple(params))
                
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description if len(desc) > 0]
                    datos = cursor.fetchall()
                    st.session_state.df_resultado = pd.DataFrame(datos, columns=columns)
                else:
                    st.session_state.df_resultado = pd.DataFrame()
                    
                db_psql.commit()
                st.session_state.excel_data_to_download = None
                
        except Exception as e:
            st.error(f"Error relacional: {e}")
            try: db_psql.rollback()
            except: pass

    if "df_resultado" in st.session_state and st.session_state.df_resultado is not None:
        df_display = st.session_state.df_resultado
        
        st.write("---")
        if not df_display.empty:
            col_m1, col_m2 = st.columns(2)
            col_m1.metric(label="Total Registros en Memoria (Para Excel)", value=f"{len(df_display):,}")
            col_m2.metric(label="Columnas de la Entidad", value=len(df_display.columns))
            
            st.sidebar.markdown("---")
            st.sidebar.subheader("Report Generator")
            
            current_report_id = hash(tuple(df_display.index))
            if 'last_report_id' not in st.session_state or st.session_state.last_report_id != current_report_id:
                st.session_state.excel_data_to_download = None
                st.session_state.last_report_id = current_report_id

            if st.sidebar.button("Pack Data to XLSX", use_container_width=True):
                with st.spinner("Baking Excel..."):
                    st.session_state.excel_data_to_download = convert_df_to_excel(df_display)
                    st.sidebar.success("Excel generated successfully!")
            
            if st.session_state.get('excel_data_to_download') is not None:
                st.sidebar.download_button(
                    label="Download Excel Report",
                    data=st.session_state.excel_data_to_download,
                    file_name=f"extract_{selected_table.split('.')[-1]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            
            st.markdown("---")
            UMBRAL_VISUAL = 5000
            if len(df_display) > UMBRAL_VISUAL:
                st.warning(f"Aviso de rendimiento: Mostrando las primeras {UMBRAL_VISUAL:,} filas en pantalla. El reporte de la barra lateral empaquetará los {len(df_display):,} registros completos.")
                st.dataframe(df_display.head(UMBRAL_VISUAL), use_container_width=True)
            else:
                st.dataframe(df_display, use_container_width=True)
        else:
            st.info("La consulta se ejecutó correctamente, pero no existen registros para esta combinación de filtros.")
else:
    st.error("No se pudo establecer una conexión válida con el servidor central de PostgreSQL. Por favor, revisa el estado de la red local o los logs del contenedor Docker.")