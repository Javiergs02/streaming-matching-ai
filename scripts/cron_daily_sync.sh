#!/usr/bin/env bash
# ==============================================================================
# SCRIPT DE SINCRONIZACIÓN DIARIA COMPLETA (ESTRUCTURAL + ANALÍTICAS YOUTUBE)
# Frecuencia recomendada: Todas las noches a las 02:30 UTC
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs/cron}"
mkdir -p "${LOG_DIR}"

DATE_TAG="$(date +'%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/daily_sync_${DATE_TAG}.log"
LOCK_FILE="/tmp/matching_ai_daily_sync.lock"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "=============================================================================="
echo ">>> INICIO DE SINCRONIZACIÓN DIARIA: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo "=============================================================================="

# Control de concurrencia: Evitar solapamientos
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo "[AVISO] Ya hay una sincronización diaria ejecutándose. Abortando instancia duplicada."
    exit 0
fi

VENV_PATH="${PROJECT_ROOT}/venv/bin/python"
if [ ! -x "${VENV_PATH}" ]; then
    echo "[ERROR] No se encontró Python en ${VENV_PATH}. Crea el virtualenv antes de ejecutar."
    exit 1
fi

EM_PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/apps/event_manager/src"
EC_PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/apps/event_consumer/src"

# 1-3. Sincronización Estructural (Canales + Vídeos -> Mongo -> PostgreSQL)
# Se aísla el PYTHONPATH por módulo para evitar colisión entre paquetes 'infrastructure'.
# Si falla por cuota temporal de Data API v3, se registra aviso pero continúa la analítica.
echo ""
echo "--- Paso 1/6: Sincronización Estructural de Canales YouTube ---"
if PYTHONPATH="${EM_PYTHONPATH}" "${VENV_PATH}" apps/event_manager/src/run_yt_channel_events.py; then
    echo "--- Paso 2/6: Sincronización Estructural de Vídeos YouTube ---"
    if PYTHONPATH="${EM_PYTHONPATH}" "${VENV_PATH}" apps/event_manager/src/run_yt_video_events.py; then
        echo "--- Paso 3/6: Consumidor Estructural hacia PostgreSQL ---"
        PYTHONPATH="${EC_PYTHONPATH}" "${VENV_PATH}" apps/event_consumer/src/run_youtube_structural_consumer.py || \
            echo "[AVISO] Fallo en consumidor estructural PostgreSQL; se continúa con analíticas."
    else
        echo "[AVISO] Fallo en extracción estructural de vídeos; se continúa con analíticas."
    fi
else
    echo "[AVISO] Fallo en extracción estructural de canales; se continúa con analíticas."
fi

# 4. Ingesta Diaria Global (descarga delta hasta ayer para todos los canales)
echo ""
echo "--- Paso 4/6: Descarga Diaria Global de Analíticas YouTube (Ayer) ---"
PYTHONPATH="${EM_PYTHONPATH}" "${VENV_PATH}" apps/event_manager/src/run_yt_analytics_events.py

# 5. Actualización incremental rápida de MongoDB (últimos 60 días para el mes en curso, solo YouTube)
echo ""
echo "--- Paso 5/6: Actualización Incremental de Resúmenes Mensuales YouTube (60 días) ---"
PYTHONPATH="${PROJECT_ROOT}" "${VENV_PATH}" scripts/build_monthly_aggregations.py --platform youtube

# 6. Actualización incremental anual (año actual y anterior, solo YouTube)
echo ""
echo "--- Paso 6/6: Actualización Incremental de Resúmenes Anuales YouTube ---"
PYTHONPATH="${PROJECT_ROOT}" "${VENV_PATH}" scripts/build_yearly_aggregations.py --platform youtube

# 7. Refrescar caché de Streamlit si el contenedor está en ejecución
echo ""
echo "--- Refresco de Caché del Dashboard (amuse_bi_dashboard) ---"
if command -v docker >/dev/null 2>&1 && docker ps -q -f "name=^amuse_bi_dashboard$" | grep -q .; then
    docker restart amuse_bi_dashboard >/dev/null && echo "✓ Contenedor amuse_bi_dashboard reiniciado para refrescar caché."
else
    echo "ℹ️ Contenedor amuse_bi_dashboard no detectado en este host; sin reinicio."
fi

echo ""
echo "=============================================================================="
echo ">>> SINCRONIZACIÓN DIARIA COMPLETADA: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo "=============================================================================="

find "${LOG_DIR}" -name "daily_sync_*.log" -type f -mtime +30 -delete 2>/dev/null || true

