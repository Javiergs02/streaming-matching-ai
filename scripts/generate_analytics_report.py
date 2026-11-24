"""Generates an analytics report by joining mappings with raw performance and earnings data.

Cross-references Amazon performance records, Broadkast metadata (from mappings), and 
Amazon earnings reports to produce a consolidated analytics CSV with revenue and CPH metrics.
"""

import sys
import csv
import time
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from pathlib import Path
from collections import defaultdict
import string

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.ingestion.amazon_historical import parse_numeric_float, parse_numeric_int
from core.normalization.title import normalize_title

def main():
    start_time = time.time()
    
    project_root = Path(__file__).resolve().parent.parent
    amazon_dir = project_root / "data" / "amazon"
    output_dir = project_root / "data" / "output"
    
    mappings_file = Path(sys.argv[1]) if len(sys.argv) > 1 else output_dir / "production_mappings.csv"
    raw_csv_path = Path(sys.argv[2]) if len(sys.argv) > 2 else amazon_dir / "KLQ49_2026-08_VOD_PV-Content-Performance-Report.csv"
    analytics_output = Path(sys.argv[3]) if len(sys.argv) > 3 else output_dir / "analytics_report.csv"
    target_month = sys.argv[4] if len(sys.argv) > 4 else "2026-08"
    
    earnings_dir = amazon_dir / "earnings"
    detailed_dir = amazon_dir / "detailed_earnings"
    
    # Derivar sufijos mensuales (soporta tanto YYYY_MM como MM_YYYY y variantes con guión)
    month_parts = target_month.split('-')
    if len(month_parts) == 2:
        year, month = month_parts[0], month_parts[1]
    else:
        year, month = "2026", "08"
        
    # --- 1. Detección de archivos SVOD ---
    candidate_svod = [
        earnings_dir / f"SVOD_{year}_{month}.csv",
        earnings_dir / f"SVOD_{year}-{month}.csv",
        earnings_dir / f"SVOD_{month}_{year}.csv",
        earnings_dir / f"SVOD_{month}-{year}.csv",
        earnings_dir / f"earnings_{year}_{month}.csv",
        earnings_dir / f"earnings_{year}-{month}.csv",
        earnings_dir / f"earnings_{month}_{year}.csv",
        earnings_dir / f"earnings_{month}-{year}.csv",
    ]
    svod_file = None
    for cand in candidate_svod:
        if cand.exists():
            svod_file = cand
            print(f"   Usando archivo SVOD mensual: {svod_file.name}")
            break
    if not svod_file:
        for p in sorted(earnings_dir.glob("*SVOD*.csv")):
            svod_file = p
            print(f"   Usando archivo SVOD acumulado: {svod_file.name}")
            break
    if not svod_file and (earnings_dir / "earnings_09_2024_09_2026.csv").exists():
        svod_file = earnings_dir / "earnings_09_2024_09_2026.csv"
        print(f"   Usando archivo SVOD histórico: {svod_file.name}")
    if not svod_file and detailed_dir.exists():
        for p in sorted(detailed_dir.glob("*SVOD*.csv")):
            svod_file = p
            print(f"   Usando archivo SVOD detailed: {svod_file.name}")
            break

    # --- 2. Detección de archivos TVOD ---
    candidate_tvod = [
        earnings_dir / f"TVOD_{year}_{month}.csv",
        earnings_dir / f"TVOD_{year}-{month}.csv",
        earnings_dir / f"TVOD_{month}_{year}.csv",
        earnings_dir / f"TVOD_{month}-{year}.csv",
    ]
    tvod_file = None
    for cand in candidate_tvod:
        if cand.exists():
            tvod_file = cand
            print(f"   Usando archivo TVOD mensual: {tvod_file.name}")
            break
    if not tvod_file:
        for p in sorted(earnings_dir.glob("*TVOD*.csv")):
            tvod_file = p
            print(f"   Usando archivo TVOD acumulado: {tvod_file.name}")
            break
    if not tvod_file and detailed_dir.exists():
        for p in sorted(detailed_dir.glob("*TVOD*.csv")):
            tvod_file = p
            print(f"   Usando archivo TVOD detailed: {tvod_file.name}")
            break
    
    if not mappings_file.exists():
        print("Falta production_mappings.csv. Ejecuta run_production.py primero.")
        return
        
    print("0. Obteniendo títulos en inglés de la base de datos...")
    english_titles = {}
    try:
        from dotenv import load_dotenv
        load_dotenv()
        db_host = os.getenv('DB_HOST')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('BK_DB_NAME') or os.getenv('DB_NAME') or 'broadkast_production'
        db_user = os.getenv('DB_USER')
        db_password = os.getenv('DB_PASSWORD') or os.getenv('DB_PASSWD')

        if not db_host or not db_user or not db_password:
            raise ValueError("[ERROR] Missing required database configuration in environment (DB_HOST, DB_USER, DB_PASSWORD).")

        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Seleccionamos el primer título en inglés que encontremos por cada episodio
            cursor.execute("""
                SELECT ev.episode_id, mt.title
                FROM metadata_titles mt
                JOIN episode_versions ev ON ev.id = mt.episode_version_id
                WHERE ev.language_code = 'en' AND mt.title IS NOT NULL AND mt.title != ''
            """)
            for row in cursor.fetchall():
                ep_id_str = f"EP_{row['episode_id']}"
                if ep_id_str not in english_titles:
                    title_raw = row['title'] if row['title'] else ""
                    english_titles[ep_id_str] = title_raw.strip()
        conn.close()
    except Exception as e:
        print(f"Error al conectar con BD: {e}")
        
    print(f"1. Cargando mapeos desde {mappings_file.name}...")
    # Title -> Dict of Broadkast metadata
    mappings = {}
    with mappings_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row["Amazon Original Title"]
            bk_id = row["Broadkast ID"]
            bk_ep_num = row.get("Broadkast Episode Number", "N/A")
            
            id_episode = "N/A"
            if bk_ep_num != "N/A":
                id_episode = bk_ep_num if bk_ep_num == "UNMATCHED" else f"EP_{bk_ep_num}"
                
            if bk_id == "UNMATCHED":
                english_titles["UNMATCHED"] = title

            mappings[title] = {
                "id_global": bk_id,
                "id_episode": id_episode,
                "project_id": row.get("Broadkast Project ID", "N/A"),
                "serie_id": row.get("Broadkast Series ID", "N/A"),
                "season_id": row.get("Broadkast Season ID", "N/A"),
                "project_name_broadkast": row.get("Broadkast Project Name", "N/A"),
                "serie_name_broadkast": row["Broadkast Series"],
                "serie_name_amazon": row.get("Amazon Series", "N/A"),
                "season_name_broadkast": row["Broadkast Season"],
                "season_name_amazon": row.get("Amazon Season", "N/A"),
                "episode_name_broadkast": row["Broadkast Assigned Title"],
                "episode_name_amazon": title,
                "status": row["Match Status"],
                "performance_score": row.get("Performance Score", "N/A"),
                "no_dialog": row.get("No Dialog", "N/A"),
                "youtube_id": row.get("YouTube ID", "N/A")
            }
            
    print("2. Cargando datos de ganancias (SVOD y TVOD)...")
    rates = {
        "USD": 1.0,
        "EUR": 1.0870,
        "GBP": 1.2717,
        "JPY": 0.006739,
        "INR": 0.012065,
        "CAD": 0.7391,
        "AUD": 0.6630,
        "BRL": 0.1739,
        "MXN": 0.0500,
        "SEK": 0.0957,
        "PLN": 0.2500,
        "TRY": 0.0293,
    }

    # SVOD Royalties: (normalize_title(season/title), territory) -> total_royalty_usd
    season_royalties = defaultdict(float)
    season_cph = {}
    season_currency = {}

    if svod_file and svod_file.exists():
        with svod_file.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                statement_period = row.get("Statement period", "").strip()
                if statement_period and statement_period != target_month:
                    continue
                
                royalty = parse_numeric_float(row.get("Total accrued royalty"), 0.0)
                cph = parse_numeric_float(row.get("CPH rate"), 0.0)
                    
                raw_currency = row.get("Royalty currency", "USD").strip()
                rate = rates.get(raw_currency, 1.0)
                
                royalty = royalty * rate
                cph = cph * rate
                currency = "USD"
                
                title_name = row.get("Title name", "").strip()
                territory = row.get("Territory", "").strip()
                if title_name and territory:
                    norm_key = (normalize_title(title_name), territory)
                    season_royalties[norm_key] += royalty
                    season_cph[norm_key] = cph
                    season_currency[norm_key] = currency
        print(f"   -> Regalías SVOD cargadas: {len(season_royalties)} combinaciones (Total: {sum(season_royalties.values()):.2f} USD)")
    else:
        print("   No se encontró archivo SVOD. El revenue SVOD será 0.")

    # TVOD Transactions: (normalize_title(title), territory) -> dict with fee_eur, tx_count, metadata
    tvod_by_title_terr = defaultdict(lambda: {"fee_eur": 0.0, "tx_count": 0, "rows": []})

    if tvod_file and tvod_file.exists():
        with tvod_file.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                earned_p = row.get("Royalty earned period", "").strip()
                if not earned_p:
                    earned_p = row.get("Customer transaction date", "").strip()[:7]
                if not earned_p:
                    earned_p = row.get("Statement period", "").strip()[:7]
                if earned_p != target_month:
                    continue

                fee = parse_numeric_float(row.get("License fee"), 0.0)
                tx_count = parse_numeric_int(row.get("Transaction count"), 0)

                fee_curr = row.get("License fee currency", "USD").strip()
                fee_rate = rates.get(fee_curr, 1.0)
                fee_eur = fee * fee_rate

                t_name = row.get("Title name", "").strip()
                ep_title = row.get("Episode title", "").strip()
                seas_title = row.get("Season title", "").strip()
                ser_title = row.get("Series title", "").strip()
                category = row.get("Title category", "").strip()
                territory = row.get("Territory", "").strip() or "Global"

                primary_title = ep_title if (category == "TV Episode" and ep_title) else (t_name or seas_title or ep_title)

                entry = tvod_by_title_terr[(normalize_title(primary_title), territory)]
                entry["fee_eur"] += fee_eur
                entry["tx_count"] += tx_count
                entry["rows"].append({
                    "title": primary_title,
                    "season_title": seas_title or t_name,
                    "series_title": ser_title or seas_title or t_name,
                    "category": category,
                    "fee_eur": fee_eur,
                    "tx_count": tx_count
                })
        tot_tvod_eur = sum(v["fee_eur"] for v in tvod_by_title_terr.values())
        print(f"   -> Transacciones TVOD cargadas: {len(tvod_by_title_terr)} combinaciones (Total: {tot_tvod_eur:.2f} EUR)")
    else:
        print("   No se encontró archivo TVOD. El revenue TVOD será 0.")

    print(f"3. Procesando el archivo de performance ({raw_csv_path.name}) y agregando métricas...")
    # Agregaciones normales (views, minutes)
    aggregations = defaultdict(lambda: [0.0, 0])
    
    # Para repartir el revenue SVOD, acumulamos minutos por territorio en 3 niveles
    # (Season Name -> Series Name -> Title Name) sin riesgo de doble conteo.
    season_territory_minutes = defaultdict(float)
    series_territory_minutes = defaultdict(float)
    title_territory_minutes = defaultdict(float)
    agg_alt_names = {}
    
    unmatched_count = 0
    total_raw_rows = 0
    
    if raw_csv_path.exists():
        with raw_csv_path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_raw_rows += 1
                title = row.get("Title Name")
                if not title:
                    continue
                    
                map_data = mappings.get(title)
                # Procesamos MATCH, REVIEW, AMBIGUOUS y también UNMATCHED para que salgan en el dashboard
                if not map_data or map_data["id_global"] == "N/A":
                    continue
                    
                if map_data["status"] == "UNMATCHED":
                    unmatched_count += 1
                    
                minutes = parse_numeric_float(row.get("Minutes Streamed"), 0.0)
                streams = parse_numeric_int(row.get("Unique Streams"), 0)
                    
                offer_type = row.get("Offer Type", "PRIME")
                territory = row.get("Territory", "Global")
                
                season_name = row.get("Season Name", "").strip()
                series_name_raw = row.get("Series Name", "").strip()
                if not season_name:
                    season_name = series_name_raw or title.strip()

                norm_season_k = (normalize_title(season_name), territory)
                norm_series_k = (normalize_title(series_name_raw or season_name), territory)
                norm_title_k = (normalize_title(title), territory)
                if offer_type == "PRIME":
                    season_territory_minutes[norm_season_k] += minutes
                    series_territory_minutes[norm_series_k] += minutes
                    title_territory_minutes[norm_title_k] += minutes
                
                key = (
                    map_data["id_global"],
                    map_data["id_episode"],
                    map_data["project_id"],
                    map_data["serie_id"],
                    map_data["season_id"],
                    map_data["project_name_broadkast"],
                    map_data["serie_name_broadkast"],
                    map_data["serie_name_amazon"],
                    map_data["season_name_amazon"],
                    map_data["episode_name_broadkast"],
                    map_data["episode_name_amazon"],
                    map_data["no_dialog"],
                    map_data["performance_score"],
                    map_data["youtube_id"],
                    offer_type,
                    territory,
                    season_name # Necesario para cruzar el revenue después
                )
                aggregations[key][0] += minutes
                aggregations[key][1] += streams
                if key not in agg_alt_names:
                    agg_alt_names[key] = (
                        normalize_title(series_name_raw or season_name),
                        normalize_title(title),
                    )

    # 3.5 Integrar compras transaccionales TVOD en aggregations
    tvod_assigned_fees = defaultdict(float)
    purchase_keys = {}
    for k in aggregations.keys():
        if k[14] == "PURCHASE":
            norm_t = normalize_title(k[10]) # episode_name_amazon
            terr = k[15]
            purchase_keys[(norm_t, terr)] = k

    norm_mappings = {normalize_title(orig): data for orig, data in mappings.items()}

    for (norm_t, terr), tvod_data in tvod_by_title_terr.items():
        fee_eur = tvod_data["fee_eur"]
        tx_count = tvod_data["tx_count"]
        
        if (norm_t, terr) in purchase_keys:
            existing_key = purchase_keys[(norm_t, terr)]
            tvod_assigned_fees[existing_key] += fee_eur
            aggregations[existing_key][1] = max(aggregations[existing_key][1], tx_count)
        else:
            orig_title = tvod_data["rows"][0]["title"]
            map_data = mappings.get(orig_title) or norm_mappings.get(norm_t)
            
            if not map_data:
                unmatched_count += 1
                english_titles["UNMATCHED"] = orig_title
                map_data = {
                    "id_global": "UNMATCHED",
                    "id_episode": "UNMATCHED",
                    "project_id": "N/A",
                    "serie_id": "N/A",
                    "season_id": "N/A",
                    "project_name_broadkast": "N/A",
                    "serie_name_broadkast": "UNMATCHED",
                    "serie_name_amazon": tvod_data["rows"][0]["series_title"],
                    "season_name_broadkast": "N/A",
                    "season_name_amazon": tvod_data["rows"][0]["season_title"],
                    "episode_name_broadkast": orig_title,
                    "episode_name_amazon": orig_title,
                    "status": "UNMATCHED",
                    "performance_score": "0",
                    "no_dialog": "N/A",
                    "youtube_id": "N/A"
                }
                
            new_key = (
                map_data["id_global"],
                map_data["id_episode"],
                map_data["project_id"],
                map_data["serie_id"],
                map_data["season_id"],
                map_data["project_name_broadkast"],
                map_data["serie_name_broadkast"],
                map_data["serie_name_amazon"],
                map_data["season_name_amazon"],
                map_data["episode_name_broadkast"],
                map_data["episode_name_amazon"],
                map_data["no_dialog"],
                map_data["performance_score"],
                map_data["youtube_id"],
                "PURCHASE",
                terr,
                tvod_data["rows"][0]["season_title"]
            )
            aggregations[new_key][0] += 0.0
            aggregations[new_key][1] += tx_count
            tvod_assigned_fees[new_key] += fee_eur
            purchase_keys[(norm_t, terr)] = new_key

    print(f"4. Calculando y escribiendo reporte final en {analytics_output.name}...")

    # Resolver un único nivel de asignación por clave SVOD (Season > Series > Title)
    svod_tier_by_key = {}
    for svod_k, royalty_val in season_royalties.items():
        if royalty_val <= 0:
            continue
        if season_territory_minutes.get(svod_k, 0.0) > 0:
            svod_tier_by_key[svod_k] = ("season", season_territory_minutes[svod_k])
        elif series_territory_minutes.get(svod_k, 0.0) > 0:
            svod_tier_by_key[svod_k] = ("series", series_territory_minutes[svod_k])
        elif title_territory_minutes.get(svod_k, 0.0) > 0:
            svod_tier_by_key[svod_k] = ("title", title_territory_minutes[svod_k])
    
    # Variables for Global aggregation
    global_aggregations = defaultdict(lambda: [0.0, 0, 0.0, 0.0, 0.0]) # minutes, streams, revenue, rev_svod, rev_tvod
    
    with analytics_output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "id_episode", "id_project", "id_serie", "id_season",
            "project_name_broadkast", 
            "serie_name_broadkast", "serie_name_amazon",
            "season_name_amazon",
            "episode_name_broadkast", "episode_name_amazon",
            "no_dialog", "performance_score", "youtube_url",
            "offer_type", "platform", "region", 
            "views", "minutes_streamed", "avg_view_minutes",
            "revenue", "revenue_svod", "revenue_tvod", "cph_rate", "currency"
        ])
        
        for key, metrics in aggregations.items():
            id_global, id_ep, proj_id, ser_id, seas_id, proj_bk, ser_bk, ser_amz, seas_amz, ep_bk, ep_amz, no_dialog, perf_score, yt_id, offer_type, territory, season_name = key
            minutes, streams = metrics
            
            revenue_svod = 0.0
            revenue_tvod = 0.0
            cph = 0.0
            currency = "USD"
            
            if offer_type == "PURCHASE":
                revenue_tvod = tvod_assigned_fees.get(key, 0.0)
                revenue = revenue_tvod
                hours = minutes / 60.0
                cph = (revenue / hours) if hours > 0 else 0.0
            elif offer_type == "PRIME":
                norm_season_key = (normalize_title(season_name), territory)
                norm_ser_only, norm_title_only = agg_alt_names.get(key, ("", ""))
                candidate_tiers = [
                    ("season", norm_season_key),
                    ("series", (norm_ser_only, territory)),
                    ("title", (norm_title_only, territory)),
                ]
                revenue_svod = 0.0
                for tier_name, tier_key in candidate_tiers:
                    tier_info = svod_tier_by_key.get(tier_key)
                    if tier_info and tier_info[0] == tier_name and tier_info[1] > 0:
                        season_revenue = season_royalties.get(tier_key, 0.0)
                        cph = season_cph.get(tier_key, 0.0)
                        currency = season_currency.get(tier_key, "USD")
                        revenue_svod += (minutes / tier_info[1]) * season_revenue
                        break
                revenue = revenue_svod
            else:
                revenue = 0.0
                
            avg_view = (minutes / streams) if streams > 0 else 0.0
            yt_url = f"https://youtube.com/watch?v={yt_id}" if yt_id and yt_id != "N/A" else ""
            
            writer.writerow([
                id_global, id_ep, proj_id, ser_id, seas_id,
                proj_bk, ser_bk, ser_amz, seas_amz, ep_bk, ep_amz,
                no_dialog, perf_score, yt_url,
                offer_type, "Amazon", territory, 
                streams, f"{minutes:.2f}", f"{avg_view:.2f}", f"{revenue:.4f}",
                f"{revenue_svod:.4f}", f"{revenue_tvod:.4f}",
                f"{cph:.4f}", currency
            ])
            
            # Acumular para el global
            english_title = english_titles.get(id_global, "Múltiple")
            
            if id_global == "UNMATCHED":
                g_ep_bk = f"{ep_amz} (UNMATCHED Global)"
                g_ep_amz = ep_amz
            else:
                g_ep_bk = f"{english_title} (Global)"
                g_ep_amz = "Múltiple (Global)"
                
            global_key = (
                id_global,
                id_ep,
                proj_id,
                ser_id,
                seas_id,
                proj_bk,
                ser_bk,
                "Múltiple (Global)", # serie_name_amazon
                "Múltiple (Global)", # season_name_amazon
                g_ep_bk,             # episode_name_broadkast
                g_ep_amz,            # episode_name_amazon
                no_dialog,
                perf_score,
                yt_id,
                offer_type,
                "Global"
            )
            global_aggregations[global_key][0] += minutes
            global_aggregations[global_key][1] += streams
            global_aggregations[global_key][2] += revenue
            global_aggregations[global_key][3] += revenue_svod
            global_aggregations[global_key][4] += revenue_tvod

        # Escribir filas globales
        for g_key, g_metrics in global_aggregations.items():
            id_global, id_ep, proj_id, ser_id, seas_id, proj_bk, ser_bk, ser_amz, seas_amz, ep_bk, ep_amz, no_dialog, perf_score, yt_id, offer_type, territory = g_key
            minutes, streams, revenue, revenue_svod, revenue_tvod = g_metrics
            
            avg_view = (minutes / streams) if streams > 0 else 0.0
            yt_url = f"https://youtube.com/watch?v={yt_id}" if yt_id and yt_id != "N/A" else ""
            
            effective_cph = (revenue / (minutes / 60)) if minutes > 0 else 0.0
            
            writer.writerow([
                id_global, id_ep, proj_id, ser_id, seas_id,
                proj_bk, ser_bk, ser_amz, seas_amz, ep_bk, ep_amz,
                no_dialog, perf_score, yt_url,
                offer_type, "Amazon", territory, 
                streams, f"{minutes:.2f}", f"{avg_view:.2f}", f"{revenue:.4f}",
                f"{revenue_svod:.4f}", f"{revenue_tvod:.4f}",
                f"{effective_cph:.4f}", "USD"
            ])
            
    elapsed = time.time() - start_time
    print(f"\n=== Resumen Analytics ===")
    print(f"Filas procesadas:   {total_raw_rows}")
    print(f"Filas sin mapear:   {unmatched_count} (se ignoran en el reporte de ingresos)")
    print(f"Agrupaciones final: {len(aggregations)} filas locales + {len(global_aggregations)} filas globales")
    print(f"Tiempo total:       {elapsed:.2f} segundos")

if __name__ == "__main__":
    main()
