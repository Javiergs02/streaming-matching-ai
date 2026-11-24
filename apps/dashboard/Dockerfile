FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema requeridas para psycopg2 y healthcheck
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias ligeras del dashboard
COPY apps/dashboard/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiar lógica de dominio de negocio, scripts de soporte y el dashboard
COPY core/ /app/core/
COPY scripts/ /app/scripts/
RUN mkdir -p /app/infrastructure/credentials
COPY apps/dashboard/ /app/apps/dashboard/

# Copiar archivos esenciales de referencia y caché para auditoría de mapeo
COPY data/reference/ /app/data/reference/
COPY data/cache/amazon_mapping_stats.json /app/data/cache/amazon_mapping_stats.json
COPY data/cache/broadkast_canonical_english_titles.json /app/data/cache/broadkast_canonical_english_titles.json
COPY data/output/production_mappings.csv /app/data/output/production_mappings.csv

# Configurar PYTHONPATH para resolución unificada de módulos
ENV PYTHONPATH="/app:/app/apps/dashboard"
ENV PYTHONUNBUFFERED=1

WORKDIR /app/apps/dashboard

EXPOSE 8501

# Healthcheck para verificar el estado de Streamlit (soporta ruta base raiz o /bi/)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || curl -f http://localhost:8501/bi/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
