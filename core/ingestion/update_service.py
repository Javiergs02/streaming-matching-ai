"""Amazon Data Ingestion & MongoDB Update Service.

Coordinates updating MongoDB performance events and summary aggregations
when new Amazon CSV files (performance reports, historical batches, detailed earnings)
are added to data/amazon/.
"""

import os
import sys
import re
import json
import fcntl
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, List, Set, Tuple, Dict, Any


def get_update_lock_file(data_dir: Optional[Path | str] = None) -> Path:
    """Returns the path to the exclusive lock file for Amazon updates."""
    if data_dir is None:
        root = Path(__file__).resolve().parent.parent.parent
        data_dir = root / "data"
    else:
        data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / ".amazon_update.lock"


def is_update_in_progress(data_dir: Optional[Path | str] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Checks if an Amazon update is currently running and locked by another user/process."""
    lock_file = get_update_lock_file(data_dir)
    if not lock_file.exists():
        return False, None
    try:
        f = open(lock_file, "r+")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Lock acquired successfully: no other process is holding it
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        return False, None
    except (BlockingIOError, OSError):
        # File is actively locked by another process
        info = {}
        try:
            with open(lock_file, "r", encoding="utf-8") as rf:
                info = json.load(rf)
        except Exception:
            pass
        return True, info


def get_available_amazon_months(data_dir: Optional[Path | str] = None) -> List[str]:
    """Detects all available months (YYYY-MM) in data/amazon/ (performance and historical_revenue)."""
    if data_dir is None:
        root = Path(__file__).resolve().parent.parent.parent
        data_dir = root / "data" / "amazon"
    else:
        data_dir = Path(data_dir)

    months_set: Set[str] = set()

    # 1. Streaming reports and performance folders (files or directories with YYYY-MM)
    for s_dir in [data_dir / "streaming_reports", data_dir / "performance"]:
        if s_dir.exists():
            for p in s_dir.iterdir():
                m = re.search(r"(\d{4}-\d{2})", p.name)
                if m:
                    months_set.add(m.group(1))
            for p in s_dir.rglob("*.csv"):
                m = re.search(r"(\d{4}-\d{2})", p.name)
                if m:
                    months_set.add(m.group(1))

    # 2. Historical monthly reports (e.g. 2024-05.csv)
    hist_monthly_dir = data_dir / "historical_revenue" / "monthly_reports"
    if hist_monthly_dir.exists():
        for f in hist_monthly_dir.glob("*.csv"):
            m = re.search(r"(\d{4}-\d{2})", f.name)
            if m:
                months_set.add(m.group(1))

    # 3. Analytics reports already generated (e.g. analytics_reports_03_2026.csv)
    analytics_dir = data_dir.parent / "output" / "analytics_reports"
    if analytics_dir.exists():
        for f in analytics_dir.glob("analytics_reports_*.csv"):
            m = re.search(r"analytics_reports_(\d{2})_(\d{4})", f.name)
            if m:
                mon, year = m.groups()
                months_set.add(f"{year}-{mon}")

    return sorted(list(months_set))


def get_default_update_months(n_months: int = 3, data_dir: Optional[Path | str] = None) -> List[str]:
    """Returns the default list of N months to update (most recent available or current calendar)."""
    avail = get_available_amazon_months(data_dir)
    if avail:
        return avail[-n_months:]

    # Fallback to current calendar months
    now = datetime.now()
    res = []
    for i in range(n_months - 1, -1, -1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        res.append(f"{y:04d}-{m:02d}")
    return res


def run_amazon_update(
    target_months: List[str],
    sync_drive: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """Runs the Amazon update workflow for the given list of target months.

    1. Sincroniza desde la fuente oficial de datos (Google Drive corporativo).
    2. Procesa los reportes de rendimiento y liquidaciones para cada mes.
    3. Ingesta los eventos estructurados en MongoDB (PlatformEventsDB.video_performance_events).
    4. Reconstruye los resúmenes y colecciones agregadas mensuales y anuales en MongoDB.
    """
    root = Path(__file__).resolve().parent.parent.parent
    py = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}:{env.get('PYTHONPATH', '')}"

    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        print(f"[UpdateService] {msg}")

    # Control de concurrencia: Adquirir bloqueo exclusivo no bloqueante
    lock_file = get_update_lock_file(root / "data")
    try:
        lock_fd = open(lock_file, "w+")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        # Otra sincronización/actualización está ejecutándose simultáneamente
        running_info = {}
        try:
            with open(lock_file, "r", encoding="utf-8") as rf:
                running_info = json.load(rf)
        except Exception:
            pass
        started_at = running_info.get("started_at", "hace un momento")
        m_list = ", ".join(running_info.get("target_months", []))
        busy_msg = f"Ya hay una actualización de Amazon en curso iniciada a las {started_at} ({m_list or 'En proceso'}). Por favor espera a que finalice para evitar conflictos de concurrencia."
        _log(f"⚠️ [Concurrencia] {busy_msg}")
        return {
            "success": False,
            "busy": True,
            "message": busy_msg,
            "target_months": target_months,
            "processed_months": [],
            "years_affected": [],
        }

    try:
        meta = {
            "pid": os.getpid(),
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_months": target_months
        }
        lock_fd.seek(0)
        lock_fd.truncate()
        json.dump(meta, lock_fd)
        lock_fd.flush()

        _log(f"Iniciando actualización de Amazon para {len(target_months)} mes(es): {', '.join(target_months)}")

        # Step 0: Sincronización oficial desde Google Drive
        if sync_drive:
            _log("☁️ [Paso 1/4] Conectando con Google Drive (Fuente Oficial de Amazon)...")
            try:
                res = subprocess.run(
                    [py, str(root / "scripts" / "sync_amazon_drive.py")],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0:
                    _log("  ✓ Sincronización con Google Drive completada exitosamente.")
                    for line in res.stdout.splitlines():
                        if any(k in line for k in ["Total de archivos", "Archivos nuevos descargados", "Archivos omitidos"]):
                            _log(f"    {line.strip()}")
                else:
                    _log(f"  ⚠️ Aviso en sincronización de Google Drive: {res.stderr[:200] or res.stdout[:200]}")
            except Exception as e:
                _log(f"  ⚠️ Error de conexión a Google Drive: {e}. Continuando con datos disponibles en caché local.")
        else:
            _log("ℹ️ Sincronización con Google Drive omitida (modo sin conexión / caché local).")

        # Step 1: Process each target month
        perf_base = root / "data" / "amazon" / "performance"
        hist_base = root / "data" / "amazon" / "historical_revenue"

        processed = []
        failed_months = []
        for month in sorted(target_months):
            _log(f"▶ Procesando mes {month}...")
            has_perf = False
            for base_dir in [root / "data" / "amazon" / "streaming_reports", root / "data" / "amazon" / "performance"]:
                if base_dir.exists():
                    # Coincidencia con archivo o directorio que contenga el mes (Fix BUG-02)
                    match_item = next(
                        (p for p in base_dir.rglob("*") if month in p.name or month in str(p.parent)),
                        None
                    )
                    if not match_item:
                        match_item = next((p for p in base_dir.iterdir() if month in p.name), None)
                    if match_item:
                        has_perf = True
                        break

            if has_perf:
                _log(f"  • Ejecutando pipeline incremental (limpieza, IA de títulos y carga a MongoDB) para {month}...")
                cmd = [py, str(root / "scripts" / "run_incremental.py"), month]
                res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
                if res.returncode != 0:
                    _log(f"  ❌ Error en incremental {month} (no se sobrescribe con histórico): {res.stderr[:300] or res.stdout[:300]}")
                    failed_months.append(month)
                else:
                    _log(f"  ✓ Pipeline incremental completado para {month}.")
                    processed.append(month)
                continue

            # If not handled by performance folder, check historical revenue processor
            _log(f"  • Ejecutando procesador histórico para {month}...")
            cmd_hist = [
                py,
                str(root / "scripts" / "process_historical_amazon.py"),
                "--months",
                month,
                "--force",
                "--publish-mongo",
            ]
            res_hist = subprocess.run(cmd_hist, env=env, capture_output=True, text=True, check=False)
            if res_hist.returncode == 0:
                _log(f"  ✓ Procesamiento histórico y publicación en MongoDB finalizada para {month}.")
                processed.append(month)
            else:
                _log(f"  ❌ Error en procesamiento histórico {month}: {res_hist.stderr[:300] or res_hist.stdout[:300]}")
                failed_months.append(month)

        # Step 2: Rebuild MongoDB monthly aggregations
        years_affected = sorted(list(set(m.split("-")[0] for m in target_months)))
        for y in years_affected:
            _log(f"🔄 Reconstruyendo resúmenes mensuales para {y} en MongoDB (monthly_performance_summaries)...")
            res_m = subprocess.run(
                [py, str(root / "scripts" / "build_monthly_aggregations.py"), "--year", str(y), "--platform", "amazon"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if res_m.returncode == 0:
                _log(f"  ✓ Agregaciones mensuales de {y} actualizadas.")
            else:
                _log(f"  ⚠️ Aviso en agregaciones mensuales de {y}: {res_m.stderr[:200]}")

        # Step 3: Rebuild MongoDB yearly aggregations
        for y in years_affected:
            _log(f"🔄 Reconstruyendo resúmenes anuales para {y} (yearly_performance_summaries)...")
            res_y = subprocess.run(
                [py, str(root / "scripts" / "build_yearly_aggregations.py"), "--year", str(y), "--platform", "amazon"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if res_y.returncode == 0:
                _log(f"✓ Agregaciones anuales de {y} actualizadas.")
            else:
                _log(f"⚠️ Aviso en agregaciones anuales {y}: {res_y.stderr[:200]}")

        # Step 4: Update mapping audit cache for Streamlit
        _log("🎯 Actualizando caché de auditoría de mapeo (amazon_mapping_stats.json)...")
        subprocess.run(
            [py, str(root / "scripts" / "generate_amazon_mapping_cache.py")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        success = len(failed_months) == 0
        if success:
            _log("🎉 ¡Actualización de base de datos finalizada con éxito!")
        else:
            _log(f"⚠️ Actualización finalizada con errores en {len(failed_months)} mes(es): {', '.join(failed_months)}")
        return {
            "success": success,
            "target_months": target_months,
            "processed_months": processed,
            "failed_months": failed_months,
            "years_affected": years_affected,
        }
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass

