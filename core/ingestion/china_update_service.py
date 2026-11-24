"""Chinese Platforms (Tencent, Youku, iQIYI) Ingestion & Synchronization Service.

Coordinates Google Drive synchronization, raw event ingestion, and MongoDB
summary rebuilds for Chinese VOD platforms from the Streamlit UI and CLI.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

log = logging.getLogger(__name__)

PLATFORM_MAP = {
    "Todas las plataformas (Tencent, Youku, iQIYI)": ["tencent", "youku", "iqiyi"],
    "Tencent Video": ["tencent"],
    "Youku": ["youku"],
    "iQIYI": ["iqiyi"],
}

SCRIPT_MAP = {
    "tencent": "scripts/ingest_tencent.py",
    "youku": "scripts/ingest_youku.py",
    "iqiyi": "scripts/ingest_iqiyi.py",
}

DATA_DIRS = {
    "tencent": "data/Tencent",
    "youku": "data/Youku",
    "iqiyi": "data/Iqiyi",
}


def get_china_lock_file(data_dir: Optional[Path | str] = None) -> Path:
    """Returns the path to the exclusive lock file for Chinese platform updates."""
    if data_dir is None:
        root = Path(__file__).resolve().parent.parent.parent
        data_dir = root / "data"
    else:
        data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / ".china_update.lock"


def is_china_update_in_progress(
    data_dir: Optional[Path | str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Checks if a Chinese platform update is currently running."""
    lock_file = get_china_lock_file(data_dir)
    if not lock_file.exists():
        return False, None
    try:
        f = open(lock_file, "r+")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        return False, None
    except (BlockingIOError, OSError):
        info = {}
        try:
            with open(lock_file, "r", encoding="utf-8") as rf:
                info = json.load(rf)
        except Exception:
            pass
        return True, info


def get_available_china_platforms() -> List[str]:
    """Returns the list of available platform selection options."""
    return list(PLATFORM_MAP.keys())


def normalize_china_rel_path(rel_path: str) -> str:
    """Normalizes the first directory in rel_path to match exact local folder casing.

    Maps:
      - 'tencent/...' -> 'Tencent/...'
      - 'youku/...' -> 'Youku/...'
      - 'iqiyi/...' or 'iQIYI/...' -> 'Iqiyi/...'
    """
    p = Path(rel_path)
    parts = list(p.parts)
    if not parts:
        return rel_path

    top_dir = parts[0].lower()
    if top_dir == "tencent":
        parts[0] = "Tencent"
    elif top_dir == "youku":
        parts[0] = "Youku"
    elif top_dir in ("iqiyi", "iqy"):
        parts[0] = "Iqiyi"

    return str(Path(*parts))


def sync_china_drive_folders(
    platforms: List[str],
    log_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Synchronizes files from Google Drive if folder IDs are configured in .env.

    Supported Drive structures:
      1. Single parent folder: CHINA_DRIVE_FOLDER_ID
         (Contains subfolders: 'Tencent', 'Youku', 'Iqiyi')
      2. Individual folder IDs:
         TENCENT_DRIVE_FOLDER_ID, YOUKU_DRIVE_FOLDER_ID, IQIYI_DRIVE_FOLDER_ID
    """
    from core.ingestion.gdrive_sync import GoogleDriveSync

    root = Path(__file__).resolve().parent.parent.parent
    if "PYTEST_CURRENT_TEST" not in os.environ:
        load_dotenv(root / ".env")
        load_dotenv(root / "apps" / "dashboard" / ".env")

    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        log.info(msg)

    sync_results = {}
    china_root_folder_id = os.getenv("CHINA_DRIVE_FOLDER_ID")

    # Caso 1: Se ha configurado una única carpeta raíz para Plataformas Chinas
    if china_root_folder_id:
        try:
            _log(f"  ☁️ Conectando con Google Drive (Carpeta raíz 'Plataformas Chinas': {china_root_folder_id})...")
            syncer = GoogleDriveSync(folder_id=china_root_folder_id)
            all_drive_files = syncer.list_folder_contents()
            _log(f"  ✓ Archivos encontrados en Google Drive: {len(all_drive_files)}")

            service = syncer.get_client()
            from googleapiclient.http import MediaIoBaseDownload

            downloaded_count = 0
            for item in all_drive_files:
                file_id = item["id"]
                norm_rel = normalize_china_rel_path(item["rel_path"])
                local_path = root / "data" / norm_rel
                drive_size = item["size"]

                # Comprobar si pertenece a las plataformas solicitadas
                top_name = norm_rel.split("/")[0].lower()
                if platforms and not any(p == top_name for p in platforms):
                    continue

                if local_path.exists() and drive_size > 0 and local_path.stat().st_size == drive_size:
                    continue

                local_path.parent.mkdir(parents=True, exist_ok=True)
                request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
                with local_path.open("wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 2)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                downloaded_count += 1
                if downloaded_count <= 3 or downloaded_count % 50 == 0:
                    _log(f"    • Descargando archivos de Drive ({downloaded_count}/{len(all_drive_files)}): {norm_rel}")

            _log(f"  ✓ Sincronización raíz finalizada: {downloaded_count} archivos actualizados en local.")
            return {"configured": True, "downloaded": downloaded_count, "total": len(all_drive_files)}
        except Exception as e:
            _log(f"  ⚠️ Error en sincronización de Drive raíz: {e}. Se utilizarán los archivos locales.")
            return {"configured": True, "error": str(e)}

    # Caso 2: Carpetas individuales configuradas por plataforma
    for plat in platforms:
        plat_folder_id = os.getenv(f"{plat.upper()}_DRIVE_FOLDER_ID")
        target_dir = root / DATA_DIRS[plat]
        target_dir.mkdir(parents=True, exist_ok=True)

        if not plat_folder_id:
            _log(
                f"  ℹ️ Google Drive no configurado para {plat.upper()} "
                f"(define CHINA_DRIVE_FOLDER_ID o {plat.upper()}_DRIVE_FOLDER_ID en .env). "
                f"Utilizando archivos locales de {DATA_DIRS[plat]}."
            )
            sync_results[plat] = {"configured": False, "files": 0}
            continue

        try:
            _log(f"  ☁️ Conectando con Google Drive para {plat.upper()} (Folder ID: {plat_folder_id})...")
            syncer = GoogleDriveSync(folder_id=plat_folder_id)
            res = syncer.sync_to_local(target_dir)
            dl_count = len(res.get("downloaded", []))
            _log(f"  ✓ Sincronización de {plat.upper()}: {dl_count} archivos nuevos/actualizados descargados.")
            sync_results[plat] = {"configured": True, "downloaded": dl_count, "total": res.get("total_drive_files", 0)}
        except Exception as e:
            _log(f"  ⚠️ Error sincronizando {plat.upper()} desde Drive: {e}. Se continuará con los archivos locales.")
            sync_results[plat] = {"configured": True, "error": str(e)}

    return sync_results


def run_china_update(
    platform_choice: str = "Todas las plataformas (Tencent, Youku, iQIYI)",
    sync_drive: bool = True,
    dry_run: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """Executes ingestion and aggregation for the selected Chinese platforms."""
    root = Path(__file__).resolve().parent.parent.parent
    if "PYTEST_CURRENT_TEST" not in os.environ:
        load_dotenv(root / ".env")
        load_dotenv(root / "apps" / "dashboard" / ".env")
    py = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}:{env.get('PYTHONPATH', '')}"

    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        print(f"[ChinaUpdateService] {msg}")

    # Control de concurrencia: Adquirir bloqueo exclusivo
    lock_file = get_china_lock_file(root / "data")
    try:
        lock_fd = open(lock_file, "w+")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        running_info = {}
        try:
            with open(lock_file, "r", encoding="utf-8") as rf:
                running_info = json.load(rf)
        except Exception:
            pass
        started_at = running_info.get("started_at", "hace un momento")
        p_desc = running_info.get("platform_choice", "En proceso")
        busy_msg = (
            f"Ya hay una actualización de plataformas chinas en curso iniciada a las {started_at} "
            f"({p_desc}). Por favor espera a que finalice."
        )
        _log(f"⚠️ [Concurrencia] {busy_msg}")
        return {
            "success": False,
            "busy": True,
            "message": busy_msg,
            "processed_platforms": [],
        }

    try:
        meta = {
            "pid": os.getpid(),
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "platform_choice": platform_choice,
            "sync_drive": sync_drive,
            "dry_run": dry_run,
        }
        lock_fd.seek(0)
        lock_fd.truncate()
        json.dump(meta, lock_fd)
        lock_fd.flush()

        platforms_to_run = PLATFORM_MAP.get(platform_choice, ["tencent", "youku", "iqiyi"])
        _log(f"🚀 Iniciando actualización para: {platform_choice} ({', '.join(platforms_to_run)})")

        # Paso 1: Sincronización con Google Drive
        if sync_drive:
            _log("☁️ [Paso 1/2] Sincronizando con Google Drive corporativo...")
            sync_china_drive_folders(platforms_to_run, log_callback=_log)
        else:
            _log("ℹ️ Sincronización con Google Drive omitida (modo sin conexión / caché local).")

        # Paso 2: Ingesta de Datos y Reconstrucción de Resúmenes
        _log("📊 [Paso 2/2] Ejecutando parsers de ingesta y consolidación en MongoDB...")
        processed_successfully = []

        for plat in platforms_to_run:
            script_rel = SCRIPT_MAP.get(plat)
            if not script_rel:
                continue

            script_path = root / script_rel
            cmd = [py, str(script_path)]
            if dry_run:
                cmd.append("--dry-run")

            plat_label = plat.upper()
            _log(f"\n▶ Procesando {plat_label} ({script_rel})...")
            
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines = []
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    clean_line = line.strip()
                    if clean_line:
                        output_lines.append(clean_line)
                        # Show summary and milestone lines
                        if any(k in clean_line for k in ["Insertados", "Eliminados", "Actualizando", "RESUMEN", "Total", "Visualizaciones", "Ingresos", "completada"]):
                            _log(f"  • {clean_line}")

            proc.wait()

            if proc.returncode == 0:
                _log(f"  ✓ {plat_label} procesado e integrado exitosamente.")
                processed_successfully.append(plat)
            else:
                _log(f"  ⚠️ Error o advertencia procesando {plat_label} (código de salida: {proc.returncode}).")
                # Mostrar los últimos mensajes de error para diagnóstico inmediato
                recent_errs = [l for l in output_lines[-5:] if l]
                for err_line in recent_errs:
                    _log(f"    ↳ {err_line}")

        all_ok = len(processed_successfully) == len(platforms_to_run)
        if all_ok:
            _log(f"\n🎉 ¡Actualización de plataformas chinas ({', '.join(platforms_to_run)}) finalizada con éxito!")
        else:
            _log(f"\n⚠️ Finalizado con advertencias ({len(processed_successfully)}/{len(platforms_to_run)} completados).")

        return {
            "success": all_ok,
            "platform_choice": platform_choice,
            "processed_platforms": processed_successfully,
        }

    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass
