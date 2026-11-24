"""Synchronize MongoDB Aggregations with Canonical Production Mappings.

Updates `monthly_performance_summaries` and `yearly_performance_summaries`
in MongoDB to ensure that all Amazon Prime Video performance documents
strictly reference the canonical Broadkast IDs and series determined by
the audited `data/output/production_mappings.csv`.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
import sys
import time
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MAPPINGS_PATH = PROJECT_ROOT / "data" / "output" / "production_mappings.csv"


def get_mongo_db():
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    user = os.getenv("MONGODB_WRITER_USER")
    passwd = os.getenv("MONGODB_WRITER_PASSWD")
    db_name = os.getenv("MONGODB_DB_NAME", "PlatformEventsDB")

    if user and passwd and "@" not in uri:
        auth_uri = uri.replace("mongodb://", f"mongodb://{user}:{passwd}@")
    else:
        auth_uri = uri

    client = MongoClient(auth_uri, serverSelectionTimeoutMS=10000)
    return client[db_name]


def load_mappings():
    log.info(f"Cargando mapeos canónicos desde {MAPPINGS_PATH}...")
    title_to_mapping = {}
    with open(MAPPINGS_PATH, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            orig = (row.get("Amazon Original Title") or "").strip()
            status = (row.get("Match Status") or "").strip()
            bkid = (row.get("Broadkast ID") or "").strip()
            series = (row.get("Broadkast Series") or "").strip()
            proj = (row.get("Broadkast Project Name") or "").strip()

            if orig:
                if status == "UNMATCHED" or bkid in ("UNMATCHED", "", "N/A"):
                    id_hash = hashlib.md5(orig.encode("utf-8")).hexdigest()[:12]
                    exp_vid = f"UNMATCHED_AMZ_{id_hash}"
                else:
                    exp_vid = bkid

                title_to_mapping[orig] = (status, exp_vid, series, proj)

    log.info(f"  {len(title_to_mapping)} títulos únicos cargados.")
    return title_to_mapping


def sync_collection(db, coll_name: str, title_to_mapping: dict):
    coll = db[coll_name]
    log.info(f"▶ Sincronizando colección '{coll_name}'...")

    total_amz = coll.count_documents({"_id.event_type": "amazon.video.performance_recorded"})
    log.info(f"  Total documentos de Amazon en {coll_name}: {total_amz}")

    cursor = coll.find(
        {"_id.event_type": "amazon.video.performance_recorded"},
        {"_id": 1, "title": 1, "monthly_revenue": 1, "yearly_revenue": 1, "monthly_views": 1, "yearly_views": 1, "monthly_watch_time": 1, "yearly_watch_time": 1}
    )

    migrated_count = 0
    scanned_count = 0
    start_time = time.time()

    for doc in cursor:
        scanned_count += 1
        t = doc.get("title")
        curr_vid = doc["_id"].get("video_id")

        if t in title_to_mapping:
            status, exp_vid, series, proj = title_to_mapping[t]
            if curr_vid != exp_vid:
                old_id = doc["_id"]
                new_id = dict(old_id)
                new_id["video_id"] = exp_vid

                # Check if target doc already exists
                target = coll.find_one({"_id": new_id})
                if target:
                    # Accumulate all metric fields into existing doc and delete old (Fix C29)
                    METRIC_FIELDS = [
                        "monthly_revenue", "yearly_revenue",
                        "monthly_revenue_svod", "yearly_revenue_svod",
                        "monthly_revenue_tvod", "yearly_revenue_tvod",
                        "monthly_revenue_avod", "yearly_revenue_avod",
                        "monthly_views", "yearly_views",
                        "monthly_watch_time", "yearly_watch_time",
                        "monthly_likes", "yearly_likes",
                        "monthly_comments", "yearly_comments",
                        "monthly_ad_revenue", "yearly_ad_revenue",
                        "monthly_ad_impressions", "yearly_ad_impressions",
                    ]
                    inc_fields = {f: doc[f] for f in METRIC_FIELDS if f in doc and doc[f] is not None}

                    if inc_fields:
                        coll.update_one({"_id": new_id}, {"$inc": inc_fields})
                    coll.delete_one({"_id": old_id})
                else:
                    # Update doc _id safely: insert new before deleting old to prevent data loss (Fix C28)
                    full_doc = coll.find_one({"_id": old_id})
                    if full_doc:
                        full_doc["_id"] = new_id
                        if status == "UNMATCHED":
                            full_doc["series_name"] = "UNMATCHED_AMZ"
                            full_doc["project_name"] = "UNMATCHED"
                        else:
                            full_doc["series_name"] = series
                            full_doc["project_name"] = proj

                        coll.insert_one(full_doc)
                        coll.delete_one({"_id": old_id})

                migrated_count += 1

        if scanned_count % 25000 == 0:
            elapsed = time.time() - start_time
            log.info(f"    Progreso {coll_name}: {scanned_count}/{total_amz} escaneados ({migrated_count} migrados) en {elapsed:.1f}s")

    elapsed = time.time() - start_time
    log.info(f"✓ Finalizado '{coll_name}': {migrated_count} documentos migrados en {elapsed:.1f}s.")


def main():
    db = get_mongo_db()
    title_to_mapping = load_mappings()

    sync_collection(db, "monthly_performance_summaries", title_to_mapping)
    sync_collection(db, "yearly_performance_summaries", title_to_mapping)

    log.info("🎉 ¡Sincronización de MongoDB completada con éxito!")


if __name__ == "__main__":
    main()

