"""YouTube Data Ingestion & Territorial Reconcilation Service.

Coordinates territorial analytics ingestion, CPM-weighted reconciliation,
and MongoDB summary aggregations for YouTube from the Streamlit UI.
"""

import os
import sys
import json
import fcntl
import subprocess
from pathlib import Path
from datetime import datetime, date
from typing import Callable, Optional, List, Tuple, Dict, Any


def get_youtube_lock_file(data_dir: Optional[Path | str] = None) -> Path:
    """Returns the path to the exclusive lock file for YouTube updates."""
    if data_dir is None:
        root = Path(__file__).resolve().parent.parent.parent
        data_dir = root / "data"
    else:
        data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / ".youtube_update.lock"


def is_youtube_update_in_progress(data_dir: Optional[Path | str] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Checks if a YouTube update is currently running and locked by another process."""
    lock_file = get_youtube_lock_file(data_dir)
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


def get_available_youtube_years() -> List[str]:
    """Returns the list of valid analytical years for YouTube."""
    current_year = datetime.now().year
    return [str(y) for y in range(2016, current_year + 1)]


def get_default_youtube_months(n_months: int = 3) -> List[str]:
    """Returns the last N closed calendar months (YYYY-MM)."""
    now = datetime.now()
    # If we are in November 2026, the last closed month is 2026-10
    cur_y = now.year
    cur_m = now.month - 1
    if cur_m == 0:
        cur_m = 12
        cur_y -= 1

    res = []
    for _ in range(n_months):
        res.append(f"{cur_y:04d}-{cur_m:02d}")
        cur_m -= 1
        if cur_m == 0:
            cur_m = 12
            cur_y -= 1
    return sorted(res)


def run_youtube_update(
    period_option: str,
    target_year: Optional[str] = None,
    custom_months: Optional[List[str]] = None,
    custom_years: Optional[List[str]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """Executes the YouTube territorial ingestion, CPM reconciliation, and aggregation pipeline.

    Supported period_option:
    - 'Último mes cerrado'
    - 'Últimos 3 meses (Por defecto)'
    - 'Últimos 6 meses'
    - 'Último año (12 meses)'
    - 'Año específico (Completo)'
    - 'Personalizado (Seleccionar años/meses)'
    - 'Histórico completo (--full-history)'
    """
    root = Path(__file__).resolve().parent.parent.parent
    py = sys.executable
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}:{root / 'apps' / 'event_manager' / 'src'}:{env.get('PYTHONPATH', '')}"

    def _log(msg: str):
        if log_callback:
            log_callback(msg)
        print(f"[YouTubeUpdateService] {msg}")

    # Control de concurrencia: Adquirir bloqueo exclusivo
    lock_file = get_youtube_lock_file(root / "data")
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
        p_desc = running_info.get("period_option", "En proceso")
        busy_msg = f"Ya hay una actualización de YouTube en curso iniciada a las {started_at} ({p_desc}). Por favor espera a que finalice para no sobrecargar la cuota de la API de YouTube."
        _log(f"⚠️ [Concurrencia] {busy_msg}")
        return {
            "success": False,
            "busy": True,
            "message": busy_msg,
            "processed_years": [],
        }

    try:
        meta = {
            "pid": os.getpid(),
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "period_option": period_option,
            "target_year": target_year,
            "custom_months": custom_months,
        }
        lock_fd.seek(0)
        lock_fd.truncate()
        json.dump(meta, lock_fd)
        lock_fd.flush()

        _log(f"🚀 Iniciando proceso de actualización de YouTube: {period_option}")

        # Helper para ejecutar subprocesos con verificación estricta de salida
        def _run_step(cmd: List[str], step_name: str, allow_failure: bool = False) -> subprocess.CompletedProcess:
            res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or f"Código de salida: {res.returncode}"
                if allow_failure:
                    _log(f"  ⚠️ Aviso en {step_name}: {err_msg[:300]}")
                else:
                    _log(f"  ❌ Error crítico en {step_name}: {err_msg[:300]}")
                    raise RuntimeError(f"Fallo en {step_name}: {err_msg[:300]}")
            return res

        # Resolver periodo y comandos
        years_to_reconcile: List[str] = []

        try:
            if period_option == "Último mes cerrado":
                months = get_default_youtube_months(1)
                target_m = months[0]
                y, m = target_m.split("-")
                years_to_reconcile = [y]
                # Determinar fecha de inicio y fin del mes
                import calendar
                _, last_day = calendar.monthrange(int(y), int(m))
                s_date = f"{y}-{m}-01"
                e_date = f"{y}-{m}-{last_day:02d}"

                _log(f"📅 [Paso 1/4] Descargando audiencia por país para {target_m} ({s_date} a {e_date})...")
                cmd_yt = [
                    py,
                    str(root / "apps" / "event_manager" / "src" / "run_yt_monthly_territory_events.py"),
                    "--start-date", s_date,
                    "--end-date", e_date,
                ]
                _run_step(cmd_yt, f"descarga territorial {target_m}")
                _log(f"  ✓ Audiencia territorial descargada con éxito para {target_m}.")

                _log(f"⚖️ [Paso 2/4] Reconciliando facturación contable territorial de {y}...")
                cmd_rec = [
                    py,
                    str(root / "scripts" / "reconcile_youtube_territorial_revenue.py"),
                    "--year", y,
                    "--month", m,
                ]
                _run_step(cmd_rec, f"reconciliación contable {target_m}")
                _log(f"  ✓ Reconciliación territorial completada para {target_m}.")

            elif period_option in ("Últimos 3 meses (Por defecto)", "Últimos 6 meses", "Último año (12 meses)"):
                n_m = 3 if "3" in period_option else (6 if "6" in period_option else 12)
                months = get_default_youtube_months(n_m)
                _log(f"📅 Meses a procesar: {', '.join(months)}")
                affected_years = sorted(list(set(m.split("-")[0] for m in months)))
                years_to_reconcile = affected_years

                for ym in months:
                    y, m = ym.split("-")
                    import calendar
                    _, last_day = calendar.monthrange(int(y), int(m))
                    s_date = f"{y}-{m}-01"
                    e_date = f"{y}-{m}-{last_day:02d}"

                    _log(f"▶ [1/4] Descargando territorial {ym}...")
                    cmd_yt = [
                        py,
                        str(root / "apps" / "event_manager" / "src" / "run_yt_monthly_territory_events.py"),
                        "--start-date", s_date,
                        "--end-date", e_date,
                    ]
                    _run_step(cmd_yt, f"descarga territorial {ym}")

                for y in affected_years:
                    _log(f"⚖️ [2/4] Reconciliando ingresos territoriales de {y}...")
                    _run_step(
                        [py, str(root / "scripts" / "reconcile_youtube_territorial_revenue.py"), "--year", str(y)],
                        f"reconciliación contable {y}"
                    )

            elif period_option == "Año específico (Completo)":
                if not target_year:
                    raise ValueError("Debes especificar un año objetivo para procesar.")
                y = str(target_year).strip()
                years_to_reconcile = [y]

                _log(f"📅 [Paso 1/4] Descargando año completo {y} desde YouTube API...")
                cmd_yt = [
                    py,
                    str(root / "apps" / "event_manager" / "src" / "run_yt_monthly_territory_events.py"),
                    "--year", y,
                ]
                _run_step(cmd_yt, f"descarga territorial año {y}")
                _log(f"  ✓ Ingesta territorial del año {y} completada.")

                _log(f"⚖️ [Paso 2/4] Reconciliando facturación territorial de {y} con CPM real...")
                cmd_rec = [
                    py,
                    str(root / "scripts" / "reconcile_youtube_territorial_revenue.py"),
                    "--year", y,
                ]
                _run_step(cmd_rec, f"reconciliación contable año {y}")
                _log(f"  ✓ Reconciliación contable sellada para {y}.")

            elif period_option == "Histórico completo (--full-history)":
                _log("🔄 [Paso 1/4] Iniciando ingesta territorial completa (2016 hasta hoy)...")
                cmd_yt = [
                    py,
                    str(root / "apps" / "event_manager" / "src" / "run_yt_monthly_territory_events.py"),
                    "--full-history",
                ]
                _run_step(cmd_yt, "descarga territorial histórico completo")
                _log("  ✓ Ingesta territorial histórica descargada.")

                _log("⚖️ [Paso 2/4] Reconciliando histórico completo en MongoDB...")
                _run_step(
                    [py, str(root / "scripts" / "reconcile_youtube_territorial_revenue.py")],
                    "reconciliación contable histórico completo"
                )
                _log("  ✓ Reconciliación histórica completada.")
                years_to_reconcile = get_available_youtube_years()

            else:
                # Personalizado
                selected_years = custom_years or ([target_year] if target_year else ["2025"])
                years_to_reconcile = selected_years
                for y in selected_years:
                    _log(f"▶ Procesando año {y}...")
                    _run_step(
                        [py, str(root / "apps" / "event_manager" / "src" / "run_yt_monthly_territory_events.py"), "--year", str(y)],
                        f"descarga territorial año {y}"
                    )
                    _run_step(
                        [py, str(root / "scripts" / "reconcile_youtube_territorial_revenue.py"), "--year", str(y)],
                        f"reconciliación contable año {y}"
                    )
                    _log(f"  ✓ Año {y} procesado y reconciliado con éxito.")

            # Paso 3: Reconstruir resúmenes mensuales
            _log("📊 [Paso 3/4] Reconstruyendo resúmenes mensuales (monthly_performance_summaries)...")
            if period_option == "Histórico completo (--full-history)":
                cmd_m_list = [[py, str(root / "scripts" / "build_monthly_aggregations.py"), "--all", "--platform", "youtube"]]
            elif years_to_reconcile:
                cmd_m_list = [
                    [py, str(root / "scripts" / "build_monthly_aggregations.py"), "--year", str(y), "--platform", "youtube"]
                    for y in years_to_reconcile
                ]
            else:
                cmd_m_list = [[py, str(root / "scripts" / "build_monthly_aggregations.py"), "--platform", "youtube"]]

            for cmd_m in cmd_m_list:
                _run_step(cmd_m, "resúmenes mensuales")
                _log("  ✓ Resúmenes mensuales actualizados exitosamente.")

            # Paso 4: Reconstruir resúmenes anuales
            _log("📈 [Paso 4/4] Reconstruyendo resúmenes anuales (yearly_performance_summaries)...")
            if period_option == "Histórico completo (--full-history)":
                cmd_y = [py, str(root / "scripts" / "build_yearly_aggregations.py"), "--all", "--platform", "youtube"]
                _run_step(cmd_y, "resúmenes anuales histórico")
            else:
                for y in years_to_reconcile:
                    cmd_y = [py, str(root / "scripts" / "build_yearly_aggregations.py"), "--year", str(y), "--platform", "youtube"]
                    _run_step(cmd_y, f"resúmenes anuales año {y}")
            _log("  ✓ Resúmenes anuales actualizados exitosamente.")

            _log("🎉 ¡Actualización territorial y reconciliación de YouTube completadas con éxito!")
            return {
                "success": True,
                "period_option": period_option,
                "processed_years": years_to_reconcile,
            }

        except Exception as e:
            _log(f"💥 Error durante el proceso de actualización: {e}")
            return {
                "success": False,
                "error": str(e),
                "period_option": period_option,
                "processed_years": years_to_reconcile,
            }

    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass

