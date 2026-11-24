#!/usr/bin/env python3
"""Ingests iQIYI historical datasets into MongoDB and rebuilds monthly/yearly summaries.

Usage:
    python scripts/ingest_iqiyi.py --dry-run
    python scripts/ingest_iqiyi.py
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

from core.ingestion.iqiyi_parser import parse_iqiyi_directory, summarize_iqiyi_events
from scripts.build_monthly_aggregations import build_monthly_aggregations
from scripts.build_yearly_aggregations import build_yearly_aggregations
from scripts.ingest_tencent import build_mongo_uri


def print_summary(summary: dict) -> None:
    print("\n===============================================================================")
    print("  RESUMEN DE AUDITORÍA - iQIYI (AMUSE CC + LTV/FRANCE + SHANGHAI)")
    print("===============================================================================")
    print(f"  Eventos diarios totales:  {summary['total_events']:,}")
    print(f"  Visualizaciones totales:  {summary['total_views']:,}")
    print(f"  Watch Time VIP (hrs):     {summary['total_watch_hours']:,.2f}")
    print(f"  Comentarios totales:      {summary['total_comments']:,}")
    print(f"  Ingresos AVOD (RMB):      ¥{summary['total_avod_cny']:,.2f}")
    print(f"  Ingresos SVOD (RMB):      ¥{summary['total_svod_cny']:,.2f}")
    print(f"  Ingresos totales (RMB):   ¥{summary['total_cny']:,.2f}")
    print(f"  Ingresos totales (USD):   ${summary['total_usd']:,.2f}")
    print(f"  Unmatched resources:      {summary['unmatched']}")
    print("\n--- Por Canal / Subplataforma ---")
    for sub, info in summary["by_subplatform"].items():
        print(
            f"  {sub:<34} | events={info['events']:>6,} | views={info['views']:>14,} | "
            f"WT={info['watch_hours']:>10,.1f}h | AVOD=¥{info['avod_cny']:>10,.2f} | "
            f"SVOD=¥{info['svod_cny']:>11,.2f} | USD=${info['usd']:>11,.2f}"
        )
    print("\n--- Por Año ---")
    for yr, info in summary["by_year"].items():
        print(
            f"  {yr} | events={info['events']:>5,} | views={info['views']:>14,} | "
            f"WT={info['watch_hours']:>10,.1f}h | AVOD=¥{info['avod_cny']:>10,.2f} | "
            f"SVOD=¥{info['svod_cny']:>11,.2f} | TOT=¥{info['cny']:>11,.2f} | USD=${info['usd']:>10,.2f}"
        )
    print("===============================================================================\n")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Ingest iQIYI historical Excel datasets into MongoDB."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "Iqiyi",
        help="Path to iQIYI data directory (defaults to data/Iqiyi).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print summary without writing to MongoDB.",
    )
    args = parser.parse_args()

    print(f"📖 Leyendo archivos históricos de iQIYI desde: {args.data_dir}")
    events = parse_iqiyi_directory(args.data_dir)
    if not events:
        print("⚠️ No se encontraron eventos válidos de iQIYI para ingestar.")
        sys.exit(1)

    summary = summarize_iqiyi_events(events)
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

        print("🧹 Limpiando registros previos de iQIYI para evitar duplicados...")
        del_res = collection.delete_many({
            "metadata.event_type": "iqiyi.video.performance_recorded",
            "payload.platform": "iqiyi",
        })
        if del_res.deleted_count:
            print(f"   -> Eliminados {del_res.deleted_count:,} eventos previos de iQIYI.")

        batch_size = 2000
        inserted = 0
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            collection.insert_many(batch)
            inserted += len(batch)
        print(f"🚀 Insertados {inserted:,} eventos de iQIYI en '{coll_name}'.")
    finally:
        client.close()

    print("\n🔄 Actualizando resúmenes mensuales de iQIYI (monthly_performance_summaries)...")
    build_monthly_aggregations(run_all=True, platform="iqiyi")

    print("🔄 Actualizando resúmenes anuales de iQIYI (yearly_performance_summaries)...")
    build_yearly_aggregations(run_all=True, platform="iqiyi")

    print("\n✅ Ingesta histórica de iQIYI completada con éxito.")


if __name__ == "__main__":
    main()
