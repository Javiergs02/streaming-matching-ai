#!/usr/bin/env bash
# ==============================================================================
# SCRIPT DE SINCRONIZACIÓN Y PROCESAMIENTO AUTOMÁTICO DE AMAZON (CRON MENSUAL)
# Frecuencia recomendada: Días 5 y 16 de cada mes a las 06:00 UTC
# Propósito: Sincronizar Google Drive y reprocesar últimos 3 meses (desfase 60-90d)
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

LOG_DIR="${LOG_DIR:-${PROJECT_ROOT}/logs/cron}"
mkdir -p "${LOG_DIR}"

DATE_TAG="$(date +'%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/amazon_sync_${DATE_TAG}.log"
LOCK_FILE="/tmp/matching_ai_amazon_sync.lock"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "=============================================================================="
echo ">>> INICIO DE SINCRONIZACIÓN AMAZON PRIME VIDEO: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo "=============================================================================="

# Control de concurrencia: Evitar solapamientos
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo "[AVISO] Ya hay una sincronización de Amazon ejecutándose. Abortando instancia duplicada."
    exit 0
fi

VENV_PATH="${PROJECT_ROOT}/venv/bin/python"
if [ ! -x "${VENV_PATH}" ]; then
    echo "[ERROR] No se encontró Python en ${VENV_PATH}. Crea el virtualenv antes de ejecutar."
    exit 1
fi

# 1. Descargar de Google Drive y procesar últimos 3 meses disponibles
echo ""
echo "--- Paso 1/2: Descarga desde Google Drive y Pipeline Amazon (--recent 3) ---"
PYTHONPATH="${PROJECT_ROOT}" "${VENV_PATH}" scripts/process_amazon.py --recent 3 --sync-drive

# 2. Refrescar caché de Streamlit si el contenedor está en ejecución
echo ""
echo "--- Paso 2/2: Refresco de Caché del Dashboard (amuse_bi_dashboard) ---"
if command -v docker >/dev/null 2>&1 && docker ps -q -f "name=^amuse_bi_dashboard$" | grep -q .; then
    docker restart amuse_bi_dashboard >/dev/null && echo "✓ Contenedor amuse_bi_dashboard reiniciado para refrescar caché."
else
    echo "ℹ️ Contenedor amuse_bi_dashboard no detectado en este host; sin reinicio."
fi

echo ""
echo "=============================================================================="
echo ">>> SINCRONIZACIÓN AMAZON COMPLETADA CON ÉXITO: $(date '+%Y-%m-%d %H:%M:%S %Z') <<<"
echo "=============================================================================="

find "${LOG_DIR}" -name "amazon_sync_*.log" -type f -mtime +90 -delete 2>/dev/null || true
