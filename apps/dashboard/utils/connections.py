import os
import urllib.parse
import streamlit as st
from psycopg2 import connect
from pymongo import MongoClient
from dotenv import load_dotenv

# Localizar el archivo .env (prioridad: raíz del proyecto, luego carpeta local)
root_env = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))
dashboard_env = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))

if os.path.isfile(root_env):
    load_dotenv(root_env)
elif os.path.isfile(dashboard_env):
    load_dotenv(dashboard_env)
else:
    load_dotenv()

@st.cache_resource
def get_postgres_connection():
    db_host = os.environ.get("DB_HOST")
    db_port = os.environ.get("DB_PORT", "5433")
    db_user = os.environ.get("DB_USER")
    db_passwd = os.environ.get("DB_PASSWD") or os.environ.get("DB_PASSWORD")
    db_name = os.environ.get("DB_NAME")

    if not db_host:
        st.error("[ERROR] Missing Configuration")
        return None

    try:
        conn = connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_passwd,
            database=db_name,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            options="-c statement_timeout=30000"
        )
        conn.autocommit = True
        return conn
    except Exception as e:
        st.error(f"PostgreSQL Connection Error: {e}")
        return None

@st.cache_resource
def get_mongo_client():
    try:
        raw_uri = os.environ.get("MONGODB_URI")
        if not raw_uri:
            st.error("[ERROR] Missing Configuration: MONGODB_URI not set")
            return None
            
        parsed_url = urllib.parse.urlparse(raw_uri)
        
        mongo_user = os.environ.get("MONGODB_READER_USER") or os.environ.get("MONGODB_WRITER_USER")
        mongo_pass = os.environ.get("MONGODB_READER_PASSWD") or os.environ.get("MONGODB_WRITER_PASSWD")
        mongo_db = os.environ.get("MONGODB_DB_NAME", "PlatformEventsDB")
        
        if mongo_user and mongo_pass:
            u_enc = urllib.parse.quote_plus(mongo_user)
            p_enc = urllib.parse.quote_plus(mongo_pass)
            port = parsed_url.port or 27017
            qs = f"?{parsed_url.query}" if parsed_url.query else ""
            uri = f"mongodb://{u_enc}:{p_enc}@{parsed_url.hostname}:{port}/{qs}"
        else:
            uri = raw_uri

        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        return client[mongo_db]
    except Exception as e:
        st.error(f"MongoDB Connection Error: {e}")
        return None

@st.cache_resource
def get_broadkast_postgres_connection():
    db_host = os.environ.get("DB_HOST")
    db_port = os.environ.get("DB_PORT", "5433")
    db_user = os.environ.get("DB_USER")
    db_passwd = os.environ.get("DB_PASSWD") or os.environ.get("DB_PASSWORD")

    try:
        conn = connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_passwd,
            database="broadkast_production",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            options="-c statement_timeout=30000"
        )
        conn.autocommit = True
        return conn
    except Exception as e:
        st.error(f"PostgreSQL Connection Error (Broadkast): {e}")
        return None
