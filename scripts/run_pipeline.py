"""Master Pipeline Orchestrator for Matching AI.

Executes the entire end-to-end data processing workflow in a single command.

Usage:
  1. Monthly execution (Standard maintenance):
     python scripts/run_pipeline.py YYYY-MM
     Example: python scripts/run_pipeline.py 2025-05

  2. Full historical rebuild:
     python scripts/run_pipeline.py --all

  Optional flags:
     --sync-drive: Sincroniza primero la carpeta de Amazon desde Google Drive.
"""

import sys
import os
import subprocess
import time
import argparse


def print_banner(text):
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def run_step(description, command, env):
    print(f"\n▶ {description}...")
    start = time.time()
    try:
        subprocess.run(command, env=env, check=True)
        elapsed = time.time() - start
        print(f"  ✓ Completado en {elapsed:.1f}s")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error en el paso: {description}")
        print(f"Comando: {' '.join(command)}")
        print(f"Código de salida: {e.returncode}")
        sys.exit(e.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Master Pipeline Orchestrator for Matching AI."
    )
    parser.add_argument(
        "month",
        nargs="?",
        default=None,
        help="Target month (YYYY-MM), e.g. 2026-10.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Complete historical rebuild for all months (2017 to present).",
    )
    parser.add_argument(
        "--sync-drive",
        dest="sync_drive",
        action="store_true",
        help="Synchronize Amazon reports from official Google Drive folder before processing (default: True).",
    )
    parser.add_argument(
        "--no-sync-drive",
        dest="sync_drive",
        action="store_false",
        help="Skip Google Drive synchronization and use local cached files only.",
    )
    parser.set_defaults(sync_drive=True)
    args = parser.parse_args()

    if not args.all and not args.month:
        parser.print_help()
        print("\n❌ Error: Debes especificar un mes objetivo (ej. '2026-10') o la bandera '--all'.")
        sys.exit(1)

    env = os.environ.copy()
    py = sys.executable
    total_start = time.time()

    # Step 0: Google Drive Sync (if requested)
    if args.sync_drive:
        run_step(
            "Paso 0: Sincronizando reportes desde Google Drive hacia data/amazon",
            [py, "scripts/sync_amazon_drive.py"],
            env,
        )

    if args.all or args.month == "--all":
        print_banner("🔄 EJECUTANDO RECONSTRUCCIÓN HISTÓRICA TOTAL (--all)")

        # Paso 1: Generar reportes históricos faltantes (2017 a 2024-08)
        run_step(
            "Paso 1/4: Procesando histórico de Amazon (2017-2024)",
            [py, "scripts/process_historical_amazon.py"],
            env,
        )

        # Paso 2: Publicar todos los CSVs analíticos en MongoDB
        run_step(
            "Paso 2/4: Publicando todos los CSVs de analíticas en MongoDB (video_performance_events)",
            [py, "scripts/publish_to_mongo.py", "--all"],
            env,
        )

        # Paso 3: Reconstruir colecciones agregadas mensuales
        run_step(
            "Paso 3/4: Reconstruyendo agregaciones mensuales completas (monthly_performance_summaries)",
            [py, "scripts/build_monthly_aggregations.py", "--all"],
            env,
        )

        # Paso 4: Reconstruir colecciones agregadas anuales
        run_step(
            "Paso 4/5: Reconstruyendo agregaciones anuales completas (yearly_performance_summaries)",
            [py, "scripts/build_yearly_aggregations.py", "--all"],
            env,
        )

        # Paso 5: Actualizar caché de auditoría de mapeo para Streamlit
        run_step(
            "Paso 5/5: Actualizando caché de auditoría de mapeo de Amazon (amazon_mapping_stats.json)",
            [py, "scripts/generate_amazon_mapping_cache.py"],
            env,
        )

        total_elapsed = time.time() - total_start
        print_banner(
            f"✅ RECONSTRUCCIÓN HISTÓRICA COMPLETADA EXITOSAMENTE EN {total_elapsed:.1f}s"
        )

    else:
        target_month = args.month.strip()
        print_banner(f"🚀 EJECUTANDO PIPELINE MENSUAL COMPLETO: {target_month}")

        # Paso 1: Pipeline incremental (Limpieza + IA + CSV Analytics + Inyección en Mongo)
        run_step(
            f"Paso 1/3: Procesamiento incremental de Amazon para {target_month}",
            [py, "scripts/run_incremental.py", target_month],
            env,
        )

        # Paso 2: Actualizar agregaciones mensuales
        run_step(
            "Paso 2/3: Actualizando agregaciones mensuales en MongoDB",
            [py, "scripts/build_monthly_aggregations.py"],
            env,
        )

        # Paso 3: Actualizar agregaciones anuales
        run_step(
            "Paso 3/4: Actualizando agregaciones anuales en MongoDB",
            [py, "scripts/build_yearly_aggregations.py"],
            env,
        )

        # Paso 4: Actualizar caché de auditoría de mapeo para Streamlit
        run_step(
            "Paso 4/4: Actualizando caché de auditoría de mapeo de Amazon (amazon_mapping_stats.json)",
            [py, "scripts/generate_amazon_mapping_cache.py"],
            env,
        )

        total_elapsed = time.time() - total_start
        print_banner(
            f"✅ PIPELINE MENSUAL PARA {target_month} FINALIZADO CON ÉXITO EN {total_elapsed:.1f}s"
        )


if __name__ == "__main__":
    main()
