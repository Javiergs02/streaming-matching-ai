#!/usr/bin/env python3
"""Ingests Tencent Video historical datasets (AVOD + SVOD) into MongoDB and rebuilds summaries.

Usage:
    python scripts/ingest_tencent.py --dry-run
    python scripts/ingest_tencent.py
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.tencent_parser import parse_tencent_directory, summarize_tencent_events
from scripts.build_monthly_aggregations import build_monthly_aggregations
from scripts.build_yearly_aggregations import build_yearly_aggregations


def build_mongo_uri(base_uri: str, user: str | None, password: str | None) -> str:
    if not base_uri:
        raise ValueError("MONGODB_URI no está definido en el .env")
    if user and password:
        parsed = urllib.parse.urlparse(base_uri)
        return f"mongodb://{user}:{password}@{parsed.hostname}:{parsed.port}/"
    return base_uri


def print_summary(summary: dict) -> None:
    print("\n============================================================")
    print("  RESUMEN DE AUDITORÍA - TENCENT VIDEO (AVOD + SVOD)")
    print("============================================================")
    print(f"  Eventos diarios totales:  {summary['total_events']:,}")
    print(f"  Visualizaciones totales:  {summary['total_views']:,}")
    print(f"  Ingresos totales (RMB):   ¥{summary['total_cny']:,.2f}")
    print(f"  Ingresos totales (USD):   ${summary['total_usd']:,.2f}")
    print("\n--- Por Serie / Canal ---")
    for rid, info in summary["by_resource"].items():
        print(
            f"  {rid:<24} | {info['min_date']}..{info['max_date']} | "
            f"views={info['views']:>13,} | CNY=¥{info['cny']:>12,.2f} | USD=${info['usd']:>10,.2f}"
        )
    print("\n--- Por Año ---")
    for yr, info in summary["by_year"].items():
        print(
            f"  {yr} | events={info['events']:>5,} | "
            f"views={info['views']:>13,} | CNY=¥{info['cny']:>12,.2f} | USD=${info['usd']:>10,.2f}"
        )
    print("============================================================\n")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Ingest Tencent Video historical AVOD/SVOD Excel files into MongoDB."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "Tencent",
        help="Path to Tencent data directory (defaults to data/Tencent).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print summary without writing to MongoDB.",
    )
    args = parser.parse_args()

    print(f"📖 Leyendo archivos históricos de Tencent desde: {args.data_dir}")
    events = parse_tencent_directory(args.data_dir)
    if not events:
        print("⚠️ No se encontraron eventos válidos de Tencent para ingestar.")
        sys.exit(1)

    summary = summarize_tencent_events(events)
    print_summary(summary)

    if args.dry_run:
        print("🔍 Modo DRY-RUN activo: no se realizaron cambios en MongoDB.")
        return

    base_uri = os.getenv("MONGODB_URI")
    user = os.getenv("MONGODB_WRITER_USER")
    password = os.getenv("MONGODB_WRITER_PASSWD")
    db_name = os.getenv("MONGODB_DB_NAME", "PlatformEventsDB")
    coll_name = os.getenv("MONGODB_ANALYTICS_COLLECTION", "video_performance_events")

    uri = build_mongo_uri(base_uri, user, password)
    print(f"🔌 Conectando a MongoDB ({db_name}.{coll_name})...")
    client = MongoClient(uri)
    try:
        db = client[db_name]
        collection = db[coll_name]

        print("🧹 Limpiando registros previos de Tencent para evitar duplicados...")
        del_res = collection.delete_many({
            "metadata.event_type": "tencent.video.performance_recorded",
            "payload.platform": "tencent",
        })
        if del_res.deleted_count:
            print(f"   -> Eliminados {del_res.deleted_count:,} eventos previos de Tencent.")

        batch_size = 2000
        inserted = 0
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            collection.insert_many(batch)
            inserted += len(batch)
        print(f"🚀 Insertados {inserted:,} eventos de Tencent en '{coll_name}'.")
    finally:
        client.close()

    print("\n🔄 Actualizando resúmenes mensuales de Tencent (monthly_performance_summaries)...")
    build_monthly_aggregations(run_all=True, platform="tencent")

    print("🔄 Actualizando resúmenes anuales de Tencent (yearly_performance_summaries)...")
    build_yearly_aggregations(run_all=True, platform="tencent")

    print("\n✅ Ingesta histórica de Tencent completada con éxito.")


if __name__ == "__main__":
    main()
