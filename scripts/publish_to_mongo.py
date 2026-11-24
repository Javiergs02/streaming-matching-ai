import os
import sys
import csv
import uuid
import hashlib
from datetime import datetime, timezone
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
import re

def build_mongo_uri(base_uri, user, password):
    if not base_uri:
        raise ValueError("MONGODB_URI no está definido en el .env")
    parsed = urllib.parse.urlparse(base_uri)
    return f"mongodb://{user}:{password}@{parsed.hostname}:{parsed.port}/"

def process_csv_file(csv_file, year, month, collection):
    target_month = f"{year}-{month}"
    aggregated_events = {}
    
    print(f"\n📖 Leyendo CSV de analíticas: {csv_file.name}...")
    with csv_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            broadkast_id = row.get("id")
            
            # Usamos estrictamente el ID de Amazon para que no se mezcle con YouTube
            ep_id = broadkast_id
            
            # Ignoramos filas globales combinadas o vacías
            if not ep_id or ep_id == "N/A" or ep_id == "Múltiple (Global)":
                continue
                
            is_unmatched = ("UNMATCHED" in ep_id)
            if is_unmatched:
                title_raw = (row.get("episode_name_amazon") or "").strip()
                series_raw = (row.get("serie_name_amazon") or "").strip()
                id_hash = hashlib.md5(f"{series_raw}_{title_raw}".encode('utf-8')).hexdigest()[:12]
                ep_id = f"UNMATCHED_AMZ_{id_hash}"
                
            region = row.get("region", "Global")
            if region == "Global":
                continue
                
            try:
                views = int(float(row.get("views", 0) or 0))
                minutes = float(row.get("minutes_streamed", 0) or 0.0)
                revenue = float(row.get("revenue", 0) or 0.0)
            except ValueError:
                continue
                
            offer = row.get("offer_type", "UNKNOWN")
            
            raw_rev_svod = row.get("revenue_svod")
            raw_rev_tvod = row.get("revenue_tvod")
            try:
                if raw_rev_svod is not None and str(raw_rev_svod).strip() != "":
                    rev_svod = float(raw_rev_svod)
                else:
                    rev_svod = revenue if offer in ("PRIME", "SVOD") else 0.0
            except ValueError:
                rev_svod = revenue if offer in ("PRIME", "SVOD") else 0.0

            try:
                if raw_rev_tvod is not None and str(raw_rev_tvod).strip() != "":
                    rev_tvod = float(raw_rev_tvod)
                else:
                    rev_tvod = revenue if offer in ("PURCHASE", "TVOD") else 0.0
            except ValueError:
                rev_tvod = revenue if offer in ("PURCHASE", "TVOD") else 0.0
            
            key = (ep_id, region)
            title = row.get("episode_name_broadkast") or row.get("episode_name_amazon") or ""
            series = row.get("serie_name_broadkast") or row.get("serie_name_amazon") or "UNMATCHED"
            curr = row.get("currency", "USD")

            if key not in aggregated_events:
                aggregated_events[key] = {
                    "ep_id": ep_id,
                    "region": region,
                    "title": title,
                    "series": series,
                    "currency": curr,
                    "offer_type": offer,
                    "revenue": revenue,
                    "views": views,
                    "minutes": minutes,
                    "revenue_svod": rev_svod,
                    "revenue_tvod": rev_tvod,
                }
            else:
                entry = aggregated_events[key]
                entry["revenue"] += revenue
                entry["views"] += views
                entry["minutes"] += minutes
                entry["revenue_svod"] += rev_svod
                entry["revenue_tvod"] += rev_tvod
                if entry["revenue_svod"] > 0 and entry["revenue_tvod"] > 0:
                    entry["offer_type"] = "MIXED"
                elif entry["revenue_tvod"] > 0:
                    entry["offer_type"] = "PURCHASE"
                if not entry["title"] and title:
                    entry["title"] = title

    events = []
    event_date = f"{year}-{month}-01"
    for entry in aggregated_events.values():
        event = {
            "metadata": {
                "event_id": str(uuid.uuid4()),
                "event_type": "amazon.video.performance_recorded", 
                "resource_id": entry["ep_id"],
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "cms_id": "AMAZON_PRIME",
                "offer_type": entry["offer_type"],
                "currency": entry["currency"],
            },
            "payload": {
                "video_id": entry["ep_id"],
                "platform": "amazon",
                "geography": entry["region"],
                "date": event_date,
                "currency": entry["currency"],
                "estimated_revenue": round(entry["revenue"], 4),
                "title": entry["title"],
                "amazon_series": entry["series"],
                "extra_metrics": {
                    "views": entry["views"],
                    "estimated_minutes_watched": round(entry["minutes"], 2),
                    "revenue_svod": round(entry["revenue_svod"], 4),
                    "revenue_tvod": round(entry["revenue_tvod"], 4)
                }
            }
        }
        events.append(event)
            
    if events:
        print(f"🧹 Limpiando eventos previos de Amazon para {target_month} para evitar duplicados huérfanos...")
        del_res = collection.delete_many({
            "metadata.event_type": "amazon.video.performance_recorded",
            "payload.platform": "amazon",
            "payload.date": event_date
        })
        if del_res.deleted_count > 0:
            print(f"   -> Eliminados {del_res.deleted_count} registros previos.")

        print(f"🚀 Inyectando/actualizando {len(events)} eventos de rendimiento en MongoDB...")
        operations = [
            UpdateOne(
                {
                    "metadata.event_type": "amazon.video.performance_recorded",
                    "payload.platform": "amazon",
                    "payload.video_id": ev["payload"]["video_id"],
                    "payload.date": ev["payload"]["date"],
                    "payload.geography": ev["payload"]["geography"]
                },
                {"$set": ev},
                upsert=True
            )
            for ev in events
        ]
        batch_size = 2000
        total_upserted = 0
        total_modified = 0
        for i in range(0, len(operations), batch_size):
            batch = operations[i:i + batch_size]
            res = collection.bulk_write(batch, ordered=False)
            total_upserted += len(res.upserted_ids) if res.upserted_ids else 0
            total_modified += res.modified_count
        print(f"✅ ¡Inyección completada para {target_month}! ({total_upserted} insertados, {total_modified} actualizados)")
    else:
        print(f"⚠️ No hay eventos válidos mapeados para inyectar en {target_month}.")

def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/publish_to_mongo.py YYYY-MM | --all")
        print("Ejemplo: python scripts/publish_to_mongo.py 2025-01")
        print("         python scripts/publish_to_mongo.py --all")
        sys.exit(1)
        
    arg = sys.argv[1].strip()
    root = Path(__file__).resolve().parent.parent
    reports_dir = root / "data" / "output" / "analytics_reports"
    
    load_dotenv()
    base_uri = os.getenv("MONGODB_URI")
    user = os.getenv("MONGODB_WRITER_USER")
    password = os.getenv("MONGODB_WRITER_PASSWD")
    db_name = os.getenv("MONGODB_DB_NAME")
    coll_name = os.getenv("MONGODB_ANALYTICS_COLLECTION", "video_performance_events")
    
    try:
        uri = build_mongo_uri(base_uri, user, password)
    except Exception as e:
        print(f"❌ Error de configuración: {e}")
        sys.exit(1)
    
    print(f"🔌 Conectando a MongoDB en base de datos: {db_name}, colección: {coll_name}...")
    client = MongoClient(uri)
    db = client[db_name]
    collection = db[coll_name]
    
    start_from = None
    if arg in ("--all", "--resume"):
        pass
    elif arg in ("--from", "--start-from"):
        if len(sys.argv) < 3:
            print("❌ Error: Especifica el mes inicial. Ejemplo: --from 2019-09")
            sys.exit(1)
        start_from = sys.argv[2].strip()
    elif arg.startswith("--from="):
        start_from = arg.split("=", 1)[1].strip()
    elif not re.search(r"(\d{4})-(\d{2})", arg):
        print("Uso: python scripts/publish_to_mongo.py YYYY-MM | --all | --from YYYY-MM")
        print("Ejemplo: python scripts/publish_to_mongo.py --from 2019-09")
        sys.exit(1)

    if arg in ("--all", "--resume") or start_from:
        files = list(reports_dir.glob("analytics_reports_*.csv"))
        file_items = []
        for f in files:
            m = re.search(r"analytics_reports_(\d{2})_(\d{4})\.csv", f.name)
            if m:
                month, year = m.groups()
                period_key = f"{year}-{month}"
                if start_from and period_key < start_from:
                    continue
                file_items.append((year, month, f))
        file_items.sort(key=lambda x: (x[0], x[1]))
        
        print(f"📋 Encontrados {len(file_items)} archivos de analíticas para procesar (desde {start_from or 'el inicio'}).")
        for year, month, f in file_items:
            process_csv_file(f, year, month, collection)
        print("\n🎉 ¡Todos los meses seleccionados han sido procesados y publicados en MongoDB exitosamente!")
    else:
        match = re.search(r"(\d{4})-(\d{2})", arg)
        if not match:
            print("❌ Error: Formato de mes inválido. Usa YYYY-MM o --all")
            sys.exit(1)
        
        year, month = match.groups()
        period_suffix = f"_{month}_{year}"
        csv_file = reports_dir / f"analytics_reports{period_suffix}.csv"
        
        if not csv_file.exists():
            print(f"❌ Error: No se encontró el archivo {csv_file.name}. Ejecuta run_incremental.py primero.")
            sys.exit(1)
            
        process_csv_file(csv_file, year, month, collection)

if __name__ == "__main__":
    main()

