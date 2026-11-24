#!/usr/bin/env python3
"""Unified CLI for Amazon Prime Video Ingestion & Processing.

Applicable to ANY year (historical 2017-2024, current 2025-2026, or future):
  - Detects available data (performance telemetría vs historical revenue settlements).
  - Generates full-fidelity analytics reports.
  - Ingests structured performance events to MongoDB.
  - Rebuilds monthly and yearly summaries.

Usage:
  # Process a specific year (e.g. 2025)
  python scripts/process_amazon.py --year 2025

  # Process a range of months
  python scripts/process_amazon.py --months 2024-09:2025-12

  # Process all available Amazon months
  python scripts/process_amazon.py --all

  # Pull from Google Drive first
  python scripts/process_amazon.py --year 2025 --sync-drive
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.update_service import (
    get_available_amazon_months,
    get_default_update_months,
    run_amazon_update,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("process_amazon")


def parse_month_argument(arg_val: str | None, year_val: int | None) -> list[str]:
    """Resolves target months based on --year, --months, or --all."""
    available = get_available_amazon_months()
    if not available:
        log.error("No se detectaron meses de datos de Amazon en data/amazon/")
        sys.exit(1)

    if year_val:
        y_prefix = f"{year_val:04d}-"
        target = [m for m in available if m.startswith(y_prefix)]
        if not target:
            # Generate all 12 months for that year even if not detected yet
            target = [f"{year_val:04d}-{m:02d}" for m in range(1, 13)]
        return sorted(target)

    if not arg_val or arg_val.strip().lower() == "all":
        return available

    arg_val = arg_val.strip()
    if ":" in arg_val:
        start_m, end_m = [p.strip() for p in arg_val.split(":", 1)]
        s_y, s_m = map(int, start_m.split("-"))
        e_y, e_m = map(int, end_m.split("-"))
        months = []
        cur_y, cur_m = s_y, s_m
        while (cur_y < e_y) or (cur_y == e_y and cur_m <= e_m):
            months.append(f"{cur_y:04d}-{cur_m:02d}")
            cur_m += 1
            if cur_m > 12:
                cur_m = 1
                cur_y += 1
        return months

    # Comma-separated list
    return [m.strip() for m in arg_val.split(",") if m.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Unified Amazon Prime Video Data Processing Pipeline for any year."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--year",
        type=int,
        help="Process all available months for a specific calendar year (e.g. 2025).",
    )
    group.add_argument(
        "--months",
        type=str,
        help="Specific month (YYYY-MM), comma-separated list, or range (YYYY-MM:YYYY-MM).",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Process all available Amazon data across all years.",
    )
    group.add_argument(
        "--recent",
        type=int,
        help="Process the N most recent available Amazon months (e.g. 3).",
    )

    parser.add_argument(
        "--sync-drive",
        action="store_true",
        help="Synchronize with Google Drive before processing.",
    )

    args = parser.parse_args()

    # Sincronizar Google Drive antes de resolver los meses disponibles si se pidió --sync-drive
    sync_drive_in_update = args.sync_drive
    if args.sync_drive:
        log.info("☁️ Sincronizando reportes desde Google Drive antes de seleccionar meses...")
        sync_res = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "sync_amazon_drive.py")], check=False)
        if sync_res.returncode != 0:
            log.warning("⚠️ La sincronización con Google Drive terminó con código %s; se continúa con la caché local.", sync_res.returncode)
        sync_drive_in_update = False

    if args.recent is not None:
        if args.recent <= 0:
            log.error("--recent debe ser mayor que 0.")
            sys.exit(1)
        target_months = get_default_update_months(n_months=args.recent)
    else:
        target_months = parse_month_argument(
            "all" if args.all else args.months, args.year
        )
    log.info(f"Meses seleccionados para procesamiento ({len(target_months)}): {target_months}")

    result = run_amazon_update(
        target_months=target_months,
        sync_drive=sync_drive_in_update,
        log_callback=lambda msg: log.info(msg),
    )

    if result.get("success"):
        log.info("✓ Proceso completado exitosamente para todos los meses solicitados.")
    else:
        log.error("❌ Ocurrió un error durante la ejecución del pipeline.")
        sys.exit(1)


if __name__ == "__main__":
    main()

