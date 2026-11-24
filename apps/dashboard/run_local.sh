#!/usr/bin/env bash
# ==============================================================================
# Script de ejecución local para Matching AI Dashboard (Streamlit)
# Permite lanzarlo desde cualquier directorio sin romper rutas relativas
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Cargar variables de entorno (.env de la raíz o de apps/dashboard)
if [ -f "${PROJECT_ROOT}/.env" ]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
elif [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

# Configurar PYTHONPATH para resolución unificada de core/ y dashboard
export PYTHONPATH="${PROJECT_ROOT}:${SCRIPT_DIR}:${PYTHONPATH:-}"

echo "=============================================================================="
echo "Iniciando Matching AI Dashboard en modo local..."
echo "Directorio base: ${SCRIPT_DIR}"
echo "=============================================================================="

if [ -f "${PROJECT_ROOT}/venv/bin/streamlit" ]; then
    exec "${PROJECT_ROOT}/venv/bin/streamlit" run "${SCRIPT_DIR}/app.py" "$@"
else
    exec streamlit run "${SCRIPT_DIR}/app.py" "$@"
fi
