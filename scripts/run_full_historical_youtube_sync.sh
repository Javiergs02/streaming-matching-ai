#!/usr/bin/env bash
# ==============================================================================
# SCRIPT DE RECONSTRUCCIÓN Y SINCRONIZACIÓN HISTÓRICA TOTAL DE YOUTUBE (2016-2024)
# Ejecución: Manual en segundo plano (nohup / tmux / screen)
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"

DATE_TAG="$(date +'%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/full_historical_sync_${DATE_TAG}.log"
LOCK_FILE="/tmp/matching_ai_historical_sync.lock"

exec > >(tee -a "${LOG_FILE}") 2>&1
export PYTHONUNBUFFERED=1

echo "=============================================================================="
echo ">>> INICIO DE RECONSTRUCCIÓN HISTÓRICA YOUTUBE: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo ">>> Log guardándose en: ${LOG_FILE}"
echo "=============================================================================="

# Control de concurrencia: Evitar ejecuciones simultáneas
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo "[AVISO] Ya hay una sincronización histórica ejecutándose. Abortando instancia duplicada."
    exit 0
fi

VENV_PATH="${PROJECT_ROOT}/venv/bin/python"
if [ ! -x "${VENV_PATH}" ]; then
    echo "[ERROR] No se encontró Python en ${VENV_PATH}."
    exit 1
fi

FROM_STEP=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-step)
            FROM_STEP="$2"
            shift 2
            ;;
        --skip-step1)
            FROM_STEP=2
            shift
            ;;
        *)
            echo "[AVISO] Parámetro desconocido: $1. Continuando con FROM_STEP=${FROM_STEP}."
            shift
            ;;
    esac
done

START_SEC=$(date +%s)
echo ">>> Ejecutando desde el Paso ${FROM_STEP}/5 en adelante <<<"

# Paso 1: Ingesta Global Diaria (2016 - 2024) para todos los canales CMS
# Omite automáticamente cualquier vídeo/periodo que ya exista en MongoDB.
if [ "${FROM_STEP}" -le 1 ]; then
    echo ""
    echo "=============================================================================="
    echo "--- Paso 1/5: Descarga Analítica Global (2016 - 2024) - Todos los canales CMS ---"
    echo "=============================================================================="
    "${VENV_PATH}" scripts/backfill_historical_analytics.py --all-cms --start-year 2016 --end-year 2024 --no-territories
else
    echo ""
    echo "ℹ️ [INFO] Omitiendo Paso 1/5 (configurado --from-step ${FROM_STEP})."
fi

# Paso 2: Ingesta Territorial Mensual (2016 - Actualidad)
# Descarga el desglose por país para los meses que no estén completos.
if [ "${FROM_STEP}" -le 2 ]; then
    echo ""
    echo "=============================================================================="
    echo "--- Paso 2/5: Descarga Territorial por Países (Full History) ---"
    echo "=============================================================================="
    "${VENV_PATH}" apps/event_manager/src/run_yt_monthly_territory_events.py --full-history
else
    echo ""
    echo "ℹ️ [INFO] Omitiendo Paso 2/5 (configurado --from-step ${FROM_STEP})."
fi

# Paso 3: Reconstrucción Total de Agregaciones Mensuales en MongoDB
if [ "${FROM_STEP}" -le 3 ]; then
    echo ""
    echo "=============================================================================="
    echo "--- Paso 3/5: Reconstrucción Total de Resúmenes Mensuales (YouTube) ---"
    echo "=============================================================================="
    "${VENV_PATH}" scripts/build_monthly_aggregations.py --all --platform youtube
else
    echo ""
    echo "ℹ️ [INFO] Omitiendo Paso 3/5 (configurado --from-step ${FROM_STEP})."
fi

# Paso 4: Reconciliación Contable Territorial de Todos los Años
if [ "${FROM_STEP}" -le 4 ]; then
    echo ""
    echo "=============================================================================="
    echo "--- Paso 4/5: Reconciliación Contable Territorial (Todos los años) ---"
    echo "=============================================================================="
    "${VENV_PATH}" scripts/reconcile_youtube_territorial_revenue.py
else
    echo ""
    echo "ℹ️ [INFO] Omitiendo Paso 4/5 (configurado --from-step ${FROM_STEP})."
fi

# Paso 5: Reconstrucción Total de Agregaciones Anuales en MongoDB
if [ "${FROM_STEP}" -le 5 ]; then
    echo ""
    echo "=============================================================================="
    echo "--- Paso 5/5: Reconstrucción Total de Resúmenes Anuales (YouTube) ---"
    echo "=============================================================================="
    "${VENV_PATH}" scripts/build_yearly_aggregations.py --all --platform youtube
else
    echo ""
    echo "ℹ️ [INFO] Omitiendo Paso 5/5 (configurado --from-step ${FROM_STEP})."
fi

END_SEC=$(date +%s)
DURATION=$((END_SEC - START_SEC))
HOURS=$((DURATION / 3600))
MINUTES=$(((DURATION % 3600) / 60))
SECONDS=$((DURATION % 60))

echo ""
echo "=============================================================================="
echo ">>> RECONSTRUCCIÓN HISTÓRICA COMPLETADA CON ÉXITO: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo ">>> Tiempo total transcurrido: ${HOURS}h ${MINUTES}m ${SECONDS}s"
echo "=============================================================================="
