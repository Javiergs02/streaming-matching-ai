#!/usr/bin/env python3
"""
Reconciles historical YouTube territorial revenue in MongoDB (monthly_performance_summaries).

Applies CPM-weighted allocation to existing monthly territorial summaries that were ingested
with 0 revenue due to YouTube Analytics API dimensional restrictions (dimensions='video,country').
Conserves exact cents of global video revenue while reflecting realistic geographic economic value.
"""

import os
import sys
import calendar
import argparse
import urllib.parse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

_root_dir = str(Path(__file__).resolve().parent.parent)
_em_src = str(Path(__file__).resolve().parent.parent / "apps" / "event_manager" / "src")
for p in [_root_dir, _em_src]:
    if p not in sys.path:
        sys.path.insert(0, p)

TIER_BENCHMARK_CPMS = {
    "US": 18.0, "CA": 14.0, "GB": 15.0, "AU": 16.0, "DE": 14.0, "CH": 19.0, "AT": 13.0,
    "FR": 8.5, "ES": 6.5, "IT": 6.0, "NL": 12.0, "BE": 10.0, "SE": 13.0, "NO": 15.0,
    "DK": 14.0, "FI": 12.0, "IE": 12.0, "NZ": 13.0, "JP": 9.0, "KR": 8.0,
    "MX": 2.2, "BR": 1.8, "AR": 1.5, "CL": 2.5, "CO": 1.6, "PE": 1.4,
    "PL": 4.5, "CZ": 4.0, "RO": 2.5, "TR": 1.2, "RU": 1.5,
    "IN": 0.9, "PH": 1.0, "ID": 0.9, "VN": 0.8, "TH": 1.5, "MY": 2.2,
    "ZA": 2.5, "EG": 0.8, "SA": 6.0, "AE": 8.0
}
DEFAULT_CPM = 2.0


def reconcile_summaries(db, fetcher=None, year: str = None, month: str = None, dry_run: bool = False):
    summaries_coll = db["monthly_performance_summaries"]

    match_stage = {
        "_id.platform": "youtube",
        "_id.geography": "Global",
        "monthly_revenue": {"$gt": 0}
    }

    if month:
        match_stage["_id.month"] = month
    elif year:
        match_stage["_id.month"] = {"$regex": f"^{year}"}

    print(f"\n🔍 Searching for global YouTube performance summaries...")
    cursor = summaries_coll.find(match_stage, {
        "_id.video_id": 1,
        "_id.month": 1,
        "monthly_revenue": 1,
        "monthly_ad_revenue": 1,
        "monthly_ad_impressions": 1
    })

    global_vids = list(cursor)
    print(f"   Found {len(global_vids)} global video-month entries with revenue.")

    if not global_vids:
        print("   No entries found to reconcile.")
        return

    # Group by month for structured execution
    by_month = {}
    for g in global_vids:
        m = g["_id"]["month"]
        by_month.setdefault(m, []).append(g)

    total_updated = 0
    total_reconciled_rev = 0.0

    for m, g_list in sorted(by_month.items()):
        print(f"\n▶ Processing Month: {m} ({len(g_list)} videos)...")

        # Fetch real country CPMs from YouTube Analytics API for this month
        cpm_profile = TIER_BENCHMARK_CPMS
        default_cpm = DEFAULT_CPM
        if fetcher:
            try:
                y, mon = int(m.split("-")[0]), int(m.split("-")[1])
                last_day = calendar.monthrange(y, mon)[1]
                p_start = f"{m}-01"
                p_end = f"{m}-{last_day:02d}"
                cpm_profile, default_cpm = fetcher.fetch_monthly_country_cpm_profile(p_start, p_end)
                print(f"   📡 Obtenido perfil de CPM real de YouTube para {m}: {len(cpm_profile)} países (CPM mediano: ${default_cpm:.2f})")
            except Exception as e:
                print(f"   ⚠️ No se pudo obtener el perfil de CPM de YouTube para {m}: {e}. Usando benchmarks.")

        video_ids = [g["_id"]["video_id"] for g in g_list]
        global_map = {
            g["_id"]["video_id"]: {
                "revenue": float(g.get("monthly_revenue", 0.0) or 0.0),
                "ad_revenue": float(g.get("monthly_ad_revenue", 0.0) or 0.0),
                "ad_impressions": int(g.get("monthly_ad_impressions", 0) or 0),
            }
            for g in g_list
        }

        # Query all territorial summaries for these videos in this month
        BATCH_SIZE = 500
        bulk_ops = []

        for i in range(0, len(video_ids), BATCH_SIZE):
            v_batch = video_ids[i:i + BATCH_SIZE]
            t_docs = list(summaries_coll.find({
                "_id.platform": "youtube",
                "_id.month": m,
                "_id.video_id": {"$in": v_batch},
                "_id.geography": {"$nin": ["Global", "Unknown Geo", None]}
            }))

            # Group territorial docs by video_id
            t_by_vid = {}
            for doc in t_docs:
                vid = doc["_id"]["video_id"]
                t_by_vid.setdefault(vid, []).append(doc)

            for vid, docs in t_by_vid.items():
                g_data = global_map.get(vid)
                if not g_data or g_data["revenue"] <= 0:
                    continue

                # Only reconcile if territorial docs currently have zero revenue
                curr_rev = sum(d.get("monthly_revenue", 0.0) or 0.0 for d in docs)
                if curr_rev > 0.0:
                    continue

                # Calculate CPM weights
                weights = {}
                for d in docs:
                    geo = d["_id"].get("geography", "Unknown Geo")
                    views = int(d.get("monthly_views", 0) or 0)
                    cpm_val = cpm_profile.get(geo, default_cpm)
                    weights[d["_id"]["video_id"], geo] = views * cpm_val

                tot_weight = sum(weights.values())
                tot_views = sum(int(d.get("monthly_views", 0) or 0) for d in docs)

                if tot_weight <= 0 and tot_views <= 0:
                    continue

                allocated_updates = []
                running_rev = 0.0
                running_ad_rev = 0.0
                running_ad_imp = 0

                for d in docs:
                    geo = d["_id"].get("geography", "Unknown Geo")
                    views = int(d.get("monthly_views", 0) or 0)

                    if tot_weight > 0:
                        ratio = weights[d["_id"]["video_id"], geo] / tot_weight
                    elif tot_views > 0:
                        ratio = views / tot_views
                    else:
                        ratio = 0.0

                    alloc_rev = round(g_data["revenue"] * ratio, 4)
                    alloc_ad_rev = round(g_data["ad_revenue"] * ratio, 4)
                    alloc_ad_imp = int(round(g_data["ad_impressions"] * ratio))

                    running_rev += alloc_rev
                    running_ad_rev += alloc_ad_rev
                    running_ad_imp += alloc_ad_imp

                    allocated_updates.append((d["_id"], alloc_rev, alloc_ad_rev, alloc_ad_imp, views))

                # Exact conservation of cents on top country
                if allocated_updates and g_data["revenue"] > 0:
                    diff_rev = round(g_data["revenue"] - running_rev, 4)
                    diff_ad_rev = round(g_data["ad_revenue"] - running_ad_rev, 4)
                    diff_imp = g_data["ad_impressions"] - running_ad_imp
                    if abs(diff_rev) > 0 or abs(diff_ad_rev) > 0 or diff_imp != 0:
                        top_idx = max(range(len(allocated_updates)), key=lambda idx: allocated_updates[idx][4])
                        _id, _r, _ar, _ai, _v = allocated_updates[top_idx]
                        allocated_updates[top_idx] = (
                            _id,
                            round(_r + diff_rev, 4),
                            round(_ar + diff_ad_rev, 4),
                            _ai + diff_imp,
                            _v
                        )

                for _id, _r, _ar, _ai, _ in allocated_updates:
                    bulk_ops.append(UpdateOne(
                        {"_id": _id},
                        {"$set": {
                            "monthly_revenue": _r,
                            "monthly_ad_revenue": _ar,
                            "monthly_ad_impressions": _ai
                        }}
                    ))
                    total_reconciled_rev += _r

            if len(bulk_ops) >= 1000 and not dry_run:
                res = summaries_coll.bulk_write(bulk_ops, ordered=False)
                total_updated += res.modified_count
                bulk_ops = []

        if bulk_ops and not dry_run:
            res = summaries_coll.bulk_write(bulk_ops, ordered=False)
            total_updated += res.modified_count

    print(f"\n=======================================================")
    print(f"✅ Reconciliación completada exitosamente:")
    print(f"   - Documentos territoriales actualizados: {total_updated}")
    print(f"   - Facturación territorial distribuida:   ${total_reconciled_rev:,.2f}")
    if dry_run:
        print("   (MODO SIMULACIÓN / DRY-RUN: No se escribieron cambios en la base de datos)")
    print(f"=======================================================\n")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Reconcile historical YouTube territorial revenue with CPM weighting.")
    parser.add_argument("--year", type=str, default=None, help="Target year to reconcile (e.g. 2024)")
    parser.add_argument("--month", type=str, default=None, help="Target specific month (e.g. 2024-05)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without modifying database")
    parser.add_argument("--offline", action="store_true", help="Do not query YouTube Analytics API for monthly country CPMs; use static benchmarks")
    args = parser.parse_args()

    # Set up YouTube Fetcher if credentials are available
    fetcher = None
    creds_path = os.getenv("CREDS_FILE")
    cms_id = os.getenv("CMS_ID")
    if not args.offline and creds_path and cms_id and os.path.exists(creds_path):
        try:
            from apps.event_manager.src.infrastructure.google_setup import load_yt_credentials, get_youtube_client, get_youtube_analytics_client
            from apps.event_manager.src.infrastructure.adapters.youtube_video_fetcher import YoutubeVideoFetcher
            creds = load_yt_credentials(creds_path)
            yt_data = get_youtube_client(creds)
            yt_analytics = get_youtube_analytics_client(creds)
            fetcher = YoutubeVideoFetcher(yt_data, yt_analytics, cms_id)
            print("🔑 Conexión a YouTube Analytics establecida para consulta de CPMs reales por país.")
        except Exception as e:
            print(f"⚠️ Aviso: No se pudo inicializar cliente de YouTube ({e}). Se usarán benchmarks de CPM.")

    raw_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    parsed_url = urllib.parse.urlparse(raw_uri)
    mongo_user = os.getenv("MONGODB_WRITER_USER")
    mongo_pass = os.getenv("MONGODB_WRITER_PASSWD")
    db_name = os.getenv("MONGODB_DB_NAME", "PlatformEventsDB")

    if mongo_user and mongo_pass:
        mongo_uri = f"mongodb://{mongo_user}:{mongo_pass}@{parsed_url.hostname}:{parsed_url.port}/"
    else:
        mongo_uri = raw_uri

    client = MongoClient(mongo_uri)
    db = client[db_name]

    reconcile_summaries(db, fetcher=fetcher, year=args.year, month=args.month, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

