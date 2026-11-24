#!/usr/bin/env bash
# ==============================================================================
# SCRIPT DE CONSOLIDACIÓN MENSUAL DE YOUTUBE (CRON MENSUAL)
# Frecuencia recomendada: Día 2 de cada mes a las 04:30 UTC
# Propósito: Cerrar el mes anterior con desglose territorial (CPM) y consolidar
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs/cron}"
mkdir -p "${LOG_DIR}"

DATE_TAG="$(date +'%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/monthly_close_sync_${DATE_TAG}.log"
LOCK_FILE="/tmp/matching_ai_monthly_sync.lock"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "=============================================================================="
echo ">>> INICIO DE CIERRE MENSUAL Y CONSOLIDACIÓN TERRITORIAL: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo "=============================================================================="

# Control de concurrencia: Evitar solapamientos
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo "[AVISO] Ya hay una sincronización mensual ejecutándose. Abortando instancia duplicada."
    exit 0
fi

VENV_PATH="${PROJECT_ROOT}/venv/bin/python"
if [ ! -x "${VENV_PATH}" ]; then
    echo "[ERROR] No se encontró Python en ${VENV_PATH}. Crea el virtualenv antes de ejecutar."
    exit 1
fi

EM_PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/apps/event_manager/src"

# 1. Ingesta Mensual Territorial (cierra el mes anterior con desglose por país + CPM)
echo ""
echo "--- Paso 1/4: Descarga Territorial de YouTube por País (Mes Cerrado) ---"
PYTHONPATH="${EM_PYTHONPATH}" "${VENV_PATH}" apps/event_manager/src/run_yt_monthly_territory_events.py

# 2. Reconciliación contable territorial con facturación oficial de CMS (año actual)
CUR_YEAR="$(date +'%Y')"
echo ""
echo "--- Paso 2/4: Reconciliación Contable Territorial YouTube (${CUR_YEAR}) ---"
PYTHONPATH="${PROJECT_ROOT}" "${VENV_PATH}" scripts/reconcile_youtube_territorial_revenue.py --year "${CUR_YEAR}"

# 3. Actualización incremental de resúmenes mensuales (últimos 60 días: protege históricos ya reconciliados, solo YouTube)
echo ""
echo "--- Paso 3/4: Actualización de Agregaciones Mensuales YouTube (Últimos 60 días) ---"
PYTHONPATH="${PROJECT_ROOT}" "${VENV_PATH}" scripts/build_monthly_aggregations.py --platform youtube

# 4. Actualización incremental de resúmenes anuales (año actual y anterior, solo YouTube)
echo ""
echo "--- Paso 4/4: Actualización de Agregaciones Anuales YouTube ---"
PYTHONPATH="${PROJECT_ROOT}" "${VENV_PATH}" scripts/build_yearly_aggregations.py --platform youtube

# 4. Refrescar caché de Streamlit si el contenedor está en ejecución
echo ""
echo "--- Refresco de Caché del Dashboard (amuse_bi_dashboard) ---"
if command -v docker >/dev/null 2>&1 && docker ps -q -f "name=^amuse_bi_dashboard$" | grep -q .; then
    docker restart amuse_bi_dashboard >/dev/null && echo "✓ Contenedor amuse_bi_dashboard reiniciado para refrescar caché."
else
    echo "ℹ️ Contenedor amuse_bi_dashboard no detectado en este host; sin reinicio."
fi

echo ""
echo "=============================================================================="
echo ">>> CIERRE MENSUAL COMPLETADO CON ÉXITO: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo "=============================================================================="

find "${LOG_DIR}" -name "monthly_close_sync_*.log" -type f -mtime +90 -delete 2>/dev/null || true

