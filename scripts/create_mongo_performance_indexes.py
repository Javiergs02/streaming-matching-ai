#!/usr/bin/env python3
"""Script para auditar, crear y verificar los índices compuestos de rendimiento en MongoDB.

Optimiza las consultas por plataforma en las colecciones:
  - monthly_performance_summaries (~11M documentos): index {"_id.platform": 1, "_id.month": 1}
  - yearly_performance_summaries (~2.1M documentos): index {"_id.platform": 1, "_id.year": 1}
"""

import os
import sys
import time
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

def get_mongo_db():
    load_dotenv(_ROOT / ".env")
    raw_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    parsed = urllib.parse.urlparse(raw_uri)
    user = urllib.parse.quote_plus(os.getenv("MONGODB_WRITER_USER", ""))
    pwd = urllib.parse.quote_plus(os.getenv("MONGODB_WRITER_PASSWD", ""))
    auth_source = os.getenv("MONGODB_AUTH_SOURCE", "admin")
    
    if user and pwd:
        uri = f"mongodb://{user}:{pwd}@{parsed.hostname}:{parsed.port}/?authSource={auth_source}"
    else:
        uri = raw_uri
        
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db_name = os.getenv("MONGODB_DB_NAME", "PlatformEventsDB")
    return client[db_name]

def main():
    print("=" * 75)
    print("🚀 AUDITORÍA E INDEXACIÓN DE RENDIMIENTO EN MONGODB (PlatformEventsDB)")
    print("=" * 75)

    try:
        db = get_mongo_db()
        # Verificar conexión
        db.command("ping")
        print("✓ Conexión establecida con MongoDB exitosamente.\n")
    except Exception as e:
        print(f"❌ Error al conectar a MongoDB: {e}")
        print("\nSi estás ejecutando desde un entorno con red restringida, ejecuta este script")
        print("directamente en tu terminal o en el servidor:")
        print("  venv/bin/python scripts/create_mongo_performance_indexes.py")
        sys.exit(1)

    targets = [
        {
            "coll": "monthly_performance_summaries",
            "keys": [("_id.platform", ASCENDING), ("_id.month", ASCENDING)],
            "name": "idx_platform_month",
            "test_filter": {"_id.platform": "tencent"},
        },
        {
            "coll": "yearly_performance_summaries",
            "keys": [("_id.platform", ASCENDING), ("_id.year", ASCENDING)],
            "name": "idx_platform_year",
            "test_filter": {"_id.platform": "tencent"},
        },
    ]

    for target in targets:
        coll_name = target["coll"]
        keys = target["keys"]
        index_name = target["name"]
        test_filter = target["test_filter"]

        print(f"--- Colección: {coll_name} ---")
        collection = db[coll_name]

        # 1. Contar documentos
        doc_count = collection.estimated_document_count()
        print(f"  Volumen de documentos: {doc_count:,}")

        # 2. Listar índices actuales
        existing_indexes = collection.index_information()
        print(f"  Índices existentes ({len(existing_indexes)}):")
        for idx_k, idx_v in existing_indexes.items():
            print(f"    - {idx_k}: {idx_v.get('key')}")

        # 3. Comprobar o crear el índice
        if index_name in existing_indexes:
            print(f"  ✓ El índice '{index_name}' ya existe previamente.")
        else:
            print(f"  ⚡ Creando índice '{index_name}' {keys} en segundo plano...")
            t0 = time.time()
            created_name = collection.create_index(keys, name=index_name, background=True)
            t_elapsed = time.time() - t0
            print(f"  ✓ Índice '{created_name}' creado con éxito en {t_elapsed:.2f}s.")

        # 4. Prueba de rendimiento / Explain
        print(f"  🔍 Verificando plan de ejecución para {test_filter}...")
        try:
            explain = collection.find(test_filter).limit(10).explain()
            stage = explain.get("queryPlanner", {}).get("winningPlan", {}).get("stage", "UNKNOWN")
            input_stage = explain.get("queryPlanner", {}).get("winningPlan", {}).get("inputStage", {}).get("stage", "")
            effective_stage = input_stage if input_stage else stage
            
            if "IXSCAN" in (stage, input_stage):
                print(f"  ✅ Plan de ejecución: IXSCAN (Usa índice, ultra-rápido). Stage: {effective_stage}")
            else:
                print(f"  ℹ️ Plan de ejecución: {stage} / {input_stage}")
        except Exception as ex:
            print(f"  ℹ️ No se pudo ejecutar explain detallado: {ex}")

        print()

    print("=" * 75)
    print("✅ PROCESO DE INDEXACIÓN COMPLETADO CON ÉXITO")
    print("=" * 75)

if __name__ == "__main__":
    main()
