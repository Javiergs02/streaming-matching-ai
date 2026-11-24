#!/usr/bin/env python3
"""
scripts/generate_amazon_mapping_cache.py

Genera y actualiza el archivo de caché precalculado data/cache/amazon_mapping_stats.json
a partir de data/output/production_mappings.csv y data/output/analytics_reports/*.csv.
"""

import os
import glob
import re
import json
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROD_MAPPINGS_PATH = os.path.join(PROJECT_ROOT, 'data', 'output', 'production_mappings.csv')
REPORTS_DIR = os.path.join(PROJECT_ROOT, 'data', 'output', 'analytics_reports')
CACHE_PATH = os.path.join(PROJECT_ROOT, 'data', 'cache', 'amazon_mapping_stats.json')


def generate_cache():
    print("Iniciando generación de caché de estadísticas de mapeo de Amazon...")
    if not os.path.exists(PROD_MAPPINGS_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de producción en {PROD_MAPPINGS_PATH}")

    prod = pd.read_csv(PROD_MAPPINGS_PATH)
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'analytics_reports_*.csv')))

    title_first_year = {}
    for f in files:
        m = re.search(r'analytics_reports_\d{2}_(\d{4})\.csv', f)
        if not m:
            continue
        yr = int(m.group(1))
        df = pd.read_csv(f, usecols=['episode_name_amazon'])
        for t in df['episode_name_amazon'].dropna().unique():
            if t not in title_first_year:
                title_first_year[t] = yr
            else:
                title_first_year[t] = min(title_first_year[t], yr)

    # Si algún título de production_mappings no registra reproducciones en ningún reporte,
    # se asigna a 2024 (año base de despliegue del catálogo completo de episodios)
    prod['First_Report_Year'] = prod['Amazon Original Title'].map(title_first_year).fillna(2024).astype(int)

    def categorize_amazon(row):
        method = str(row['Match Method']).lower()
        status = str(row['Match Status']).upper()
        try:
            score = float(row['Score'])
        except (ValueError, TypeError):
            score = 0.0

        if status == 'MATCH':
            if method == 'exact_title' or score >= 99.0:
                return 'Exact Title (100%)'
            elif score >= 80:
                return 'Semantic AI >= 80%'
            elif score >= 60:
                return 'Semantic AI 60-79%'
            else:
                return 'Semantic AI < 60%'
        elif any(k in method for k in ('blacklist', 'alien')):
            return 'Descartes IP (No Amuse)'
        elif any(k in method for k in ('movie', 'special')):
            return 'Descartes Formato/Especial'
        else:
            return 'Sin mapear'

    prod['Category'] = prod.apply(categorize_amazon, axis=1)
    mapping_dict = dict(zip(prod['Amazon Original Title'], prod['Category']))

    # Recuento por año
    ct = pd.crosstab(prod['First_Report_Year'], prod['Category'])
    recuento_dict = ct.to_dict(orient='index')

    # Facturación por año
    rev_hist = {}
    for f in files:
        m = re.search(r'analytics_reports_\d{2}_(\d{4})\.csv', f)
        if not m:
            continue
        yr = int(m.group(1))
        df = pd.read_csv(f, usecols=['episode_name_amazon', 'revenue'])
        df['Category'] = df['episode_name_amazon'].map(mapping_dict).fillna('Múltiple Global (Legacy)')
        if yr not in rev_hist:
            rev_hist[yr] = {}
        for cat, grp in df.groupby('Category'):
            rev_hist[yr][cat] = rev_hist[yr].get(cat, 0.0) + float(grp['revenue'].sum())

    # Auditoría IP
    is_alien = prod['Match Method'].str.contains('blacklist|alien', case=False, na=False)
    is_special = prod['Match Method'].str.contains('movie|special', case=False, na=False)
    ip_counts = {
        'Títulos IP AMUSE': int((prod['Match Status'] == 'MATCH').sum()),
        'Títulos IP no AMUSE': int(is_alien.sum()),
        'Títulos películas / formato especial': int(is_special.sum()),
        'Títulos sin mapear': int(((prod['Match Status'] == 'UNMATCHED') & ~is_alien & ~is_special).sum()),
        'TOTAL BBDD': len(prod)
    }

    # Auditoría IP Monetización
    ip_rev_by_year = {}
    for yr, cats in rev_hist.items():
        amuse_rev = cats.get('Exact Title (100%)', 0) + cats.get('Semantic AI >= 80%', 0) + cats.get('Semantic AI 60-79%', 0) + cats.get('Semantic AI < 60%', 0)
        no_amuse_rev = cats.get('Descartes IP (No Amuse)', 0)
        formato_rev = cats.get('Descartes Formato/Especial', 0)
        sin_mapear_rev = cats.get('Sin mapear', 0)
        legacy_rev = cats.get('Múltiple Global (Legacy)', 0)
        tot = amuse_rev + no_amuse_rev + formato_rev + sin_mapear_rev + legacy_rev
        ip_rev_by_year[yr] = {
            'Títulos IP AMUSE (€)': round(amuse_rev, 2),
            'Títulos IP no AMUSE (€)': round(no_amuse_rev, 2),
            'Películas / Especiales (€)': round(formato_rev, 2),
            'Títulos sin mapear (€)': round(sin_mapear_rev, 2),
            'Múltiple Global Legacy (€)': round(legacy_rev, 2),
            'TOTAL BBDD (€)': round(tot, 2)
        }

    cache_data = {
        'recuento_by_year': {str(k): {str(subk): int(subv) for subk, subv in v.items()} for k, v in recuento_dict.items()},
        'revenue_by_year': {str(k): {str(subk): round(float(subv), 2) for subk, subv in v.items()} for k, v in rev_hist.items()},
        'ip_classification_counts': ip_counts,
        'ip_revenue_by_year': ip_rev_by_year
    }

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w') as f:
        json.dump(cache_data, f, indent=2)

    print(f"Caché generada con éxito en {CACHE_PATH}")
    return cache_data


if __name__ == '__main__':
    generate_cache()

