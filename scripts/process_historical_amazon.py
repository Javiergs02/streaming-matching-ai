#!/usr/bin/env python3
"""CLI utility to process historical Amazon revenue data into monthly analytics reports.

Usage:
    # Process all historical months (2016-09 to 2025-09)
    python scripts/process_historical_amazon.py

    # Process specific months or range
    python scripts/process_historical_amazon.py --months 2017-01:2018-12

    # Process and publish to MongoDB directly
    python scripts/process_historical_amazon.py --publish-mongo

    # Pull latest files from Google Drive before processing
    python scripts/process_historical_amazon.py --sync-drive --publish-mongo
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Ensure matching_AI root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.ingestion.amazon_historical import HistoricalAmazonParser
from core.ingestion.gdrive_sync import GoogleDriveSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("process_historical_amazon")


def parse_month_argument(arg_val: str | None) -> set[str] | None:
    """Parses a month argument which can be a single month, a comma-separated list, or a range."""
    if not arg_val or arg_val.strip().lower() == "all":
        return None

    arg_val = arg_val.strip()
    # Check for range: YYYY-MM:YYYY-MM
    if ":" in arg_val:
        start_m, end_m = [p.strip() for p in arg_val.split(":", 1)]
        s_y, s_m = map(int, start_m.split("-"))
        e_y, e_m = map(int, end_m.split("-"))
        months = set()
        cur_y, cur_m = s_y, s_m
        while (cur_y < e_y) or (cur_y == e_y and cur_m <= e_m):
            months.add(f"{cur_y:04d}-{cur_m:02d}")
            cur_m += 1
            if cur_m > 12:
                cur_m = 1
                cur_y += 1
        return months

    # Comma-separated list
    return {m.strip() for m in arg_val.split(",") if m.strip()}


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Process Amazon Historical Revenue into monthly analytics reports."
    )
    parser.add_argument(
        "--sync-drive",
        action="store_true",
        help="Synchronize latest files from Google Drive before processing.",
    )
    parser.add_argument(
        "--months",
        type=str,
        default=None,
        help="Target month(s) to process, e.g. '2017-01', '2017-01:2024-08', or 'all' (default: all missing).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing analytics reports.",
    )
    parser.add_argument(
        "--publish-mongo",
        action="store_true",
        help="Publish newly generated reports directly to MongoDB.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/amazon",
        help="Directory where Amazon data is located (default: data/amazon).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/output/analytics_reports",
        help="Directory to save generated analytics reports.",
    )
    args = parser.parse_args()

    print("==================================================")
    print("🎬 PROCESADOR HISTÓRICO DE INGRESOS DE AMAZON")
    print("==================================================")

    data_dir = project_root / args.data_dir
    output_dir = project_root / args.output_dir
    mappings_file = project_root / "data" / "output" / "production_mappings.csv"

    # Step 0: Google Drive Sync (optional)
    if args.sync_drive:
        print("\n☁️ [Paso 0] Verificando sincronización con Google Drive...")
        syncer = GoogleDriveSync()
        if syncer.is_configured():
            try:
                sync_res = syncer.sync_to_local(local_destination_dir=str(data_dir))
                downloaded = sync_res.get("downloaded", [])
                print(f"   -> Sincronización exitosa: {len(downloaded)} archivo(s) nuevo(s) descargados.")
            except Exception as e:
                print(f"   ⚠️ Error durante la sincronización de Drive: {e}")
                print("   Continuando con los archivos locales...")
        else:
            print("   ℹ️ Google Drive no configurado en .env (se usarán datos locales).")

    # Step 1: Processing Historical Revenue
    target_months = parse_month_argument(args.months)
    if target_months:
        print(f"\n🎯 Meses objetivo: {len(target_months)} mes(es) seleccionados.")
    else:
        print("\n🎯 Modo: Procesando todos los meses disponibles (septiembre 2016 en adelante).")

    start_time = time.time()
    historical_parser = HistoricalAmazonParser(
        amazon_data_dir=data_dir,
        mappings_file=mappings_file,
        output_reports_dir=output_dir,
    )

    print("\n▶ Procesando lotes y reportes mensuales de Amazon...")
    exported_counts = historical_parser.process_all_historical_files(
        target_months=target_months,
        overwrite=args.force,
    )

    elapsed = time.time() - start_time
    print(f"\n✅ Procesamiento completado en {elapsed:.2f}s:")
    print(f"   - Total de meses generados/actualizados: {len(exported_counts)}")
    total_rows = sum(exported_counts.values())
    print(f"   - Total de filas generadas:             {total_rows}")

    for m in sorted(exported_counts.keys()):
        print(f"     ✓ {m}: {exported_counts[m]} filas")

    # Step 2: Publish to MongoDB (optional)
    if args.publish_mongo and exported_counts:
        print("\n🚀 [Paso 2] Publicando eventos históricos en MongoDB...")
        from scripts.publish_to_mongo import build_mongo_uri, process_csv_file
        from pymongo import MongoClient

        base_uri = os.getenv("MONGODB_URI")
        user = os.getenv("MONGODB_WRITER_USER")
        password = os.getenv("MONGODB_WRITER_PASSWD")
        db_name = os.getenv("MONGODB_DB_NAME", "PlatformEventsDB")
        coll_name = os.getenv("MONGODB_ANALYTICS_COLLECTION", "video_performance_events")

        try:
            uri = build_mongo_uri(base_uri, user, password)
            client = MongoClient(uri)
            coll = client[db_name][coll_name]

            for m in sorted(exported_counts.keys()):
                y, mon = m.split("-")
                csv_path = output_dir / f"analytics_reports_{mon}_{y}.csv"
                if csv_path.exists():
                    process_csv_file(csv_path, y, mon, coll)
            print("\n🎉 ¡Publicación en MongoDB finalizada con éxito!")
        except Exception as e:
            print(f"⚠️ Error conectando o publicando en MongoDB: {e}")
            print("Los reportes CSV permanecen guardados en data/output/analytics_reports/.")


if __name__ == "__main__":
    main()

