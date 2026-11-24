#!/usr/bin/env python3
"""Backfill script to enrich existing YouTube summaries in MongoDB with PostgreSQL catalog metadata.

Populates 'ip_name', 'series_name', and 'title' for all historical YouTube documents in:
  1. yearly_performance_summaries
  2. monthly_performance_summaries
"""

import os
import sys
import time
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.normalization.youtube_catalog_enrichment import (
    fetch_youtube_catalog_map,
    enrich_youtube_collection,
)

def build_mongo_client():
    load_dotenv(_ROOT / ".env")
    raw_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    parsed = urllib.parse.urlparse(raw_uri)
    user = urllib.parse.quote_plus(os.getenv("MONGODB_WRITER_USER") or "")
    pwd = urllib.parse.quote_plus(os.getenv("MONGODB_WRITER_PASSWD") or "")
    uri = f"mongodb://{user}:{pwd}@{parsed.hostname}:{parsed.port}/?authSource=admin"
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    db_name = os.getenv("MONGODB_DB_NAME", "PlatformEventsDB")
    return client[db_name]

def main():
    print("=" * 75)
    print("BACKFILL: ENRIQUECIMIENTO DE METADATOS DE YOUTUBE EN MONGODB")
    print("=" * 75)

    db = build_mongo_client()
    print("✓ Conectado a MongoDB PlatformEventsDB.")

    # 1. Fetch catalog map from PostgreSQL
    print("\n▶ Paso 1: Consultando catálogo de vídeos en PostgreSQL...")
    t0 = time.time()
    catalog_map = fetch_youtube_catalog_map()
    print(f"✓ {len(catalog_map):,} vídeos cargados en memoria en {time.time() - t0:.2f}s.")

    def make_progress(coll_name):
        last_t = [time.time()]
        def cb(curr, total, mod):
            # Print every ~10,000 or at 100%
            if curr % 10000 == 0 or curr == total:
                elapsed = time.time() - last_t[0]
                pct = (curr / total) * 100
                print(f"  [{coll_name}] {curr:>6,}/{total:>6,} vídeos ({pct:>5.1f}%) | Docs modificados: {mod:>8,} | ({elapsed:.1f}s)")
                last_t[0] = time.time()
        return cb

    # 2. Enrich yearly_performance_summaries
    print("\n▶ Paso 2: Enriqueciendo 'yearly_performance_summaries'...")
    t0 = time.time()
    res_yearly = enrich_youtube_collection(
        db=db,
        collection_name="yearly_performance_summaries",
        catalog_map=catalog_map,
        batch_size=2500,
        progress_callback=make_progress("yearly_summaries"),
    )
    print(f"✓ Resúmenes anuales completados: {res_yearly['matched']:,} docs coincidentes, {res_yearly['modified']:,} actualizados en {time.time() - t0:.2f}s.")

    # 3. Enrich monthly_performance_summaries
    print("\n▶ Paso 3: Enriqueciendo 'monthly_performance_summaries'...")
    t0 = time.time()
    res_monthly = enrich_youtube_collection(
        db=db,
        collection_name="monthly_performance_summaries",
        catalog_map=catalog_map,
        batch_size=2500,
        progress_callback=make_progress("monthly_summaries"),
    )
    print(f"✓ Resúmenes mensuales completados: {res_monthly['matched']:,} docs coincidentes, {res_monthly['modified']:,} actualizados en {time.time() - t0:.2f}s.")

    print("\n" + "=" * 75)
    print("✅ ENRIQUECIMIENTO COMPLETADO CON ÉXITO")
    print("=" * 75)

if __name__ == "__main__":
    main()
