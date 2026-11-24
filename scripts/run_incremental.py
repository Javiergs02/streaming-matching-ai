"""Incremental processing script for Amazon performance data.

Processes a single new month of data by loading previously mapped titles from 
the global cache to skip the AI matching step for already known titles.
"""

import sys
import os
import csv
import re
import subprocess
from pathlib import Path
from dotenv import load_dotenv

def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/run_incremental.py YYYY-MM")
        print("Ejemplo: python scripts/run_incremental.py 2026-10")
        sys.exit(1)
        
    target_month = sys.argv[1]
    
    print("\n==============================================")
    print(f"🚀 EJECUCIÓN INCREMENTAL: {target_month}")
    print("==============================================")
    
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    amazon_dirs = [root / "data" / "amazon" / "streaming_reports", root / "data" / "amazon" / "performance"]
    output_dir = root / "data" / "output"
    
    mappings_csv = output_dir / "production_mappings.csv"
    
    # Derivar sufijo (2026-10 -> 10_2026)
    match = re.search(r"(\d{4})-(\d{2})", target_month)
    if not match:
        print("❌ Error: Formato de mes inválido. Usa YYYY-MM")
        sys.exit(1)
    year, month = match.groups()
    period_suffix = f"_{month}_{year}"
    
    cleaned_csv = output_dir / "cleaned_data" / f"cleaned_amazon{period_suffix}.csv"
    analytics_csv = output_dir / "analytics_reports" / f"analytics_reports{period_suffix}.csv"
    
    # Asegurar que los directorios existen
    cleaned_csv.parent.mkdir(parents=True, exist_ok=True)
    analytics_csv.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Encontrar archivo de streaming / performance original
    raw_csv = None
    for a_dir in amazon_dirs:
        if a_dir.exists():
            candidate = next(a_dir.rglob(f"*{target_month}*.csv"), None)
            if candidate and candidate.is_file():
                raw_csv = candidate
                break

    if not raw_csv:
        print(f"❌ Error: No se encontró archivo de telemetría para {target_month}")
        sys.exit(1)
        
    print(f"✓ Archivo detectado: {raw_csv.name}")
    
    # 2. Cargar memoria
    print("\n▶ Paso 1: Cargando memoria de mapeos (caché global)...")
    global_mapping_cache = {}
    if mappings_csv.exists():
        with mappings_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                global_mapping_cache[row["Amazon Original Title"].strip()] = row
    print(f"   -> {len(global_mapping_cache)} títulos conocidos en memoria.")
    
    # 3. Limpieza
    print("\n▶ Paso 2: Limpiando archivo del mes...")
    subprocess.run([sys.executable, str(root / "scripts" / "clean_amazon_csv.py"), str(raw_csv), str(cleaned_csv), "--unique-titles"], cwd=str(root), check=True)
    
    # 4. Leer CSV limpio
    print("\n▶ Paso 3: Buscando títulos nuevos...")
    sys.path.append(str(root))
    from core.ingestion.amazon_csv import AmazonPerformanceCsvParser
    
    parser = AmazonPerformanceCsvParser(cleaned_csv)
    records = parser.parse()
    
    monthly_unique_records = {}
    new_records_to_match = []
    
    for record in records:
        if record.title_name not in monthly_unique_records:
            monthly_unique_records[record.title_name] = record
            if record.title_name not in global_mapping_cache:
                new_records_to_match.append(record)
                
    print(f"   -> Títulos únicos en {target_month}: {len(monthly_unique_records)}")
    
    # 5. Matching IA si hay nuevos
    if new_records_to_match:
        print(f"   -> ¡NUEVOS TÍTULOS DETECTADOS! Enviando {len(new_records_to_match)} títulos a la IA...")
        from core.repositories.postgres_broadkast import PostgresBroadkastRepository
        from core.matching.hybrid import HybridTitleMatcher
        
        load_dotenv()
        repo = PostgresBroadkastRepository()
        matcher = HybridTitleMatcher(repo)
        
        new_results = matcher.match(new_records_to_match)
        
        # Anexar a production_mappings.csv
        with mappings_csv.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for record, mapping in zip(new_records_to_match, new_results):
                status = mapping.match_status.name
                
                truncated_target = record.title_name
                for marker in ["/", "|", " - ", "&", " + ", " そして", " ＆"]:
                    if marker in truncated_target:
                        truncated_target = truncated_target.split(marker, 1)[0].strip()
                        break
                        
                if status == "UNMATCHED" or "Jasper" in record.title_name:
                    bk_title = record.title_name
                    bk_id = "UNMATCHED"
                    bk_series = "UNMATCHED"
                    bk_season = "UNMATCHED"
                    bk_perf = "UNMATCHED"
                    bk_no_dialog = "UNMATCHED"
                    bk_proj_id = "UNMATCHED"
                    bk_proj_name = "UNMATCHED"
                    bk_ser_id = "UNMATCHED"
                    bk_seas_id = "UNMATCHED"
                    yt_id = "UNMATCHED"
                    bk_ep_num = "UNMATCHED"
                    status = "UNMATCHED"
                else:
                    bk_title = mapping.broadkast_title_name if mapping.broadkast_title_name else "N/A"
                    bk_id = mapping.broadkast_content_id if mapping.broadkast_content_id else "N/A"
                    bk_series = mapping.broadkast_series if mapping.broadkast_series else "N/A"
                    bk_season = mapping.broadkast_season if mapping.broadkast_season else "N/A"
                    bk_perf = mapping.broadkast_performance_score if mapping.broadkast_performance_score else "N/A"
                    bk_no_dialog = mapping.broadkast_no_dialog if mapping.broadkast_no_dialog else "N/A"
                    bk_proj_id = mapping.broadkast_project_id if mapping.broadkast_project_id else "N/A"
                    bk_proj_name = mapping.broadkast_project_name if mapping.broadkast_project_name else "N/A"
                    bk_ser_id = mapping.broadkast_series_id if mapping.broadkast_series_id else "N/A"
                    bk_seas_id = mapping.broadkast_season_id if mapping.broadkast_season_id else "N/A"
                    yt_id = mapping.broadkast_video_id if mapping.broadkast_video_id else "N/A"
                    bk_ep_num = mapping.broadkast_episode_number if mapping.broadkast_episode_number else "N/A"
                    
                amz_series = record.series_name if record.series_name else "N/A"
                amz_season = record.season_name if record.season_name else "N/A"
                score = f"{mapping.score:.1f}" if mapping.score else "N/A"
                method = mapping.match_method
                
                writer.writerow([
                    record.title_name,
                    truncated_target,
                    status,
                    amz_series,
                    amz_season,
                    bk_title,
                    bk_id,
                    bk_ep_num,
                    bk_series,
                    bk_season,
                    bk_perf,
                    bk_no_dialog,
                    bk_proj_id,
                    bk_proj_name,
                    bk_ser_id,
                    bk_seas_id,
                    yt_id,
                    method,
                    score
                ])
        print("   -> IA completada. production_mappings.csv actualizado.")
    else:
        print(f"   -> Todos los títulos de {target_month} ya estaban en memoria. (Ahorro del 100% en IA)")
        
    # 6. Analytics
    print("\n▶ Paso 4: Generando Analytics del mes...")
    env = os.environ.copy()
    subprocess.run([
        sys.executable, str(root / "scripts" / "generate_analytics_report.py"),
        str(mappings_csv), str(raw_csv), str(analytics_csv), target_month
    ], env=env, cwd=str(root), check=True)
    
    # 7. Dashboard
    
    # 8. Inyectar a MongoDB
    print("\n▶ Paso 6: Inyectando eventos de Amazon a MongoDB...")
    subprocess.run([sys.executable, str(root / "scripts" / "publish_to_mongo.py"), target_month], env=env, cwd=str(root), check=True)
    
    print(f"\n✅ Proceso completado exitosamente para {target_month}.")

if __name__ == "__main__":
    main()
