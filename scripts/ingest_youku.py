#!/usr/bin/env python3
"""Ingests Youku historical datasets (DaYu + Open Platform) into MongoDB and rebuilds summaries.

Usage:
    python scripts/ingest_youku.py --dry-run
    python scripts/ingest_youku.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.youku_parser import parse_youku_directory, summarize_youku_events
from scripts.build_monthly_aggregations import build_monthly_aggregations
from scripts.build_yearly_aggregations import build_yearly_aggregations
from scripts.ingest_tencent import build_mongo_uri


def print_summary(summary: dict) -> None:
    print("\n=====================================================================")
    print("  RESUMEN DE AUDITORÍA - YOUKU (DAYU + OPEN PLATFORM)")
    print("=====================================================================")
    print(f"  Eventos diarios totales:  {summary['total_events']:,}")
    print(f"  Visualizaciones totales:  {summary['total_views']:,}")
    print(f"  Watch Time total (hrs):   {summary['total_watch_hours']:,.2f}")
    print(f"  Ingresos totales (RMB):   ¥{summary['total_cny']:,.2f}")
    print(f"  Ingresos totales (USD):   ${summary['total_usd']:,.2f}")
    print("\n--- Por Subplataforma ---")
    for sub, info in summary["by_subplatform"].items():
        print(
            f"  {sub:<16} | events={info['events']:>6,} | views={info['views']:>13,} | "
            f"WT={info['watch_hours']:>10,.2f}h | CNY=¥{info['cny']:>12,.2f} | USD=${info['usd']:>10,.2f}"
        )
    print("\n--- Por Serie / Canal ---")
    for rid, info in summary["by_resource"].items():
        print(
            f"  {rid:<20} | {info['min_date']}..{info['max_date']} | "
            f"views={info['views']:>13,} | WT={info['watch_hours']:>9,.2f}h | "
            f"CNY=¥{info['cny']:>11,.2f} | USD=${info['usd']:>9,.2f}"
        )
    print("\n--- Por Año ---")
    for yr, info in summary["by_year"].items():
        print(
            f"  {yr} | events={info['events']:>5,} | "
            f"views={info['views']:>13,} | WT={info['watch_hours']:>9,.2f}h | "
            f"CNY=¥{info['cny']:>12,.2f} | USD=${info['usd']:>10,.2f}"
        )
    print("=====================================================================\n")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Ingest Youku historical DaYu/Open Platform Excel files into MongoDB."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "Youku",
        help="Path to Youku data directory (defaults to data/Youku).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print summary without writing to MongoDB.",
    )
    args = parser.parse_args()

    print(f"📖 Leyendo archivos históricos de Youku desde: {args.data_dir}")
    events = parse_youku_directory(args.data_dir)
    if not events:
        print("⚠️ No se encontraron eventos válidos de Youku para ingestar.")
        sys.exit(1)

    summary = summarize_youku_events(events)
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

        print("🧹 Limpiando registros previos de Youku para evitar duplicados...")
        del_res = collection.delete_many({
            "metadata.event_type": "youku.video.performance_recorded",
            "payload.platform": "youku",
        })
        if del_res.deleted_count:
            print(f"   -> Eliminados {del_res.deleted_count:,} eventos previos de Youku.")

        batch_size = 2000
        inserted = 0
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            collection.insert_many(batch)
            inserted += len(batch)
        print(f"🚀 Insertados {inserted:,} eventos de Youku en '{coll_name}'.")
    finally:
        client.close()

    print("\n🔄 Actualizando resúmenes mensuales de Youku (monthly_performance_summaries)...")
    build_monthly_aggregations(run_all=True, platform="youku")

    print("🔄 Actualizando resúmenes anuales de Youku (yearly_performance_summaries)...")
    build_yearly_aggregations(run_all=True, platform="youku")

    print("\n✅ Ingesta histórica de Youku completada con éxito.")


if __name__ == "__main__":
    main()
