#!/usr/bin/env python3
"""CLI utility to synchronize Amazon Prime Video reports from Google Drive.

Usage:
    python scripts/sync_amazon_drive.py
    python scripts/sync_amazon_drive.py --target-dir data/amazon
    python scripts/sync_amazon_drive.py --folder-id <FOLDER_ID> --dry-run
"""

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure matching_AI root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.ingestion.gdrive_sync import GoogleDriveSync


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Synchronize Amazon Prime Video reports from Google Drive into data/amazon."
    )
    parser.add_argument(
        "--folder-id",
        type=str,
        default=None,
        help="Google Drive Folder ID (defaults to AMAZON_DRIVE_FOLDER_ID from .env)"
    )
    parser.add_argument(
        "--creds",
        type=str,
        default=None,
        help="Path to credentials JSON (defaults to GDRIVE_CREDS_FILE or CREDS_FILE from .env)"
    )
    parser.add_argument(
        "--target-dir",
        type=str,
        default="data/amazon",
        help="Local target directory (defaults to data/amazon)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the sync without writing files to disk."
    )
    args = parser.parse_args()

    print("==================================================")
    print("☁️  SINCRONIZADOR DE GOOGLE DRIVE -> AMAZON DATA")
    print("==================================================")

    syncer = GoogleDriveSync(creds_path=args.creds, folder_id=args.folder_id)

    if not syncer.is_configured():
        print("\n⚠️  [Aviso] Google Drive no está configurado en este entorno:")
        if not syncer.creds_path:
            print("   - Falta la ruta de credenciales (GDRIVE_CREDS_FILE / CREDS_FILE en .env)")
        elif not syncer.creds_path.exists():
            print(f"   - El archivo de credenciales no existe: {syncer.creds_path}")
        if not syncer.folder_id:
            print("   - Falta el ID de la carpeta de Drive (AMAZON_DRIVE_FOLDER_ID en .env)")
            
        print("\n💡 El sistema continuará trabajando con los datos locales en:", args.target_dir)
        print("   Cuando dispongas del ID de la carpeta y credenciales, añádelos a tu .env.")
        sys.exit(0)

    print(f"📁 Carpeta de Drive ID: {syncer.folder_id}")
    print(f"💾 Directorio destino:  {args.target_dir}")
    if args.dry_run:
        print("🔍 Modo: DRY-RUN (simulación sin descarga física)")

    print("\n▶ Consultando archivos en Google Drive...")
    result = syncer.sync_to_local(local_destination_dir=args.target_dir, dry_run=args.dry_run)

    status = result.get("status")
    if status == "success":
        total = result.get("total_drive_files", 0)
        downloaded = result.get("downloaded", [])
        skipped = result.get("skipped", [])
        errors = result.get("errors", [])

        print(f"\n✅ Sincronización completada exitosamente:")
        print(f"   - Total de archivos en Drive:    {total}")
        print(f"   - Archivos nuevos descargados:   {len(downloaded)}")
        print(f"   - Archivos omitidos (al día):    {len(skipped)}")

        if downloaded:
            print("\n📥 Archivos descargados:")
            for item in downloaded[:10]:
                print(f"   ✓ {item}")
            if len(downloaded) > 10:
                print(f"   ... y {len(downloaded) - 10} archivos más.")

        if errors:
            print("\n❌ Errores detectados durante la descarga:")
            for err in errors:
                print(f"   ! {err}")
    else:
        print(f"\n❌ Error durante la sincronización: {result.get('error', 'Desconocido')}")
        sys.exit(1)


if __name__ == "__main__":
    main()

