import os
import sys
import logging
import urllib.parse
import argparse
from pathlib import Path
from pymongo import MongoClient
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.domain.aggregation_filters import (
    build_events_match_query,
    build_summary_cleanup_filter,
)
from core.normalization.youtube_catalog_enrichment import enrich_youtube_collection

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def build_monthly_aggregations(run_all=False, year=None, platform=None):
    load_dotenv(_PROJECT_ROOT / ".env")
    
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
    
    events_coll = db[os.getenv("MONGODB_ANALYTICS_COLLECTION", 'video_performance_events')]
    
    logging.info("Starting aggregation process...")
    
    pipeline = []
    match_query = build_events_match_query(
        platform=platform,
        year=year,
        run_all=run_all,
        incremental_window="60d",
    )

    if year:
        logging.info(f"Running for target year: {year} (platform: {platform or 'all'}).")
    elif not run_all:
        logging.info(
            f"Running in incremental mode. Processing data from {match_query['payload.date']['$gte']} onwards (platform: {platform or 'all'})."
        )
    else:
        logging.info(f"Running in full mode. Processing ALL data (platform: {platform or 'all'}).")

    if match_query:
        pipeline.append({"$match": match_query})

    pipeline.extend([
        {
            "$project": {
                "video_id": "$payload.video_id",
                "platform": "$payload.platform",
                "event_type": "$metadata.event_type",
                "month": { "$substr": ["$payload.date", 0, 7] },
                "geography": { "$ifNull": ["$payload.geography", "Global"] },
                "title": { "$ifNull": ["$payload.title", ""] },
                "ip_name": { "$ifNull": ["$payload.ip_name", ""] },
                "series_name": { "$ifNull": ["$payload.series_name", { "$ifNull": ["$payload.amazon_series", ""] }] },
                "currency": { "$ifNull": ["$payload.currency", { "$ifNull": ["$metadata.currency", "USD"] }] },
                "revenue": { "$ifNull": ["$payload.estimated_revenue", 0] },
                "revenue_cny": { "$ifNull": ["$payload.extra_metrics.revenue_cny", 0] },
                "revenue_svod": {
                    "$cond": [
                        { "$ne": ["$payload.platform", "amazon"] },
                        { "$ifNull": ["$payload.extra_metrics.revenue_svod", 0] },
                        {
                            "$ifNull": [
                                "$payload.extra_metrics.revenue_svod",
                                {
                                    "$cond": [
                                        { "$eq": ["$metadata.offer_type", "PURCHASE"] },
                                        0,
                                        { "$ifNull": ["$payload.estimated_revenue", 0] }
                                    ]
                                }
                            ]
                        }
                    ]
                },
                "revenue_tvod": {
                    "$cond": [
                        { "$ne": ["$payload.platform", "amazon"] },
                        { "$ifNull": ["$payload.extra_metrics.revenue_tvod", 0] },
                        {
                            "$ifNull": [
                                "$payload.extra_metrics.revenue_tvod",
                                {
                                    "$cond": [
                                        { "$eq": ["$metadata.offer_type", "PURCHASE"] },
                                        { "$ifNull": ["$payload.estimated_revenue", 0] },
                                        0
                                    ]
                                }
                            ]
                        }
                    ]
                },
                "revenue_avod": { "$ifNull": ["$payload.extra_metrics.revenue_avod", 0] },
                "views": { "$ifNull": ["$payload.extra_metrics.views", { "$ifNull": ["$payload.views", 0] }] },
                "watch_time": { "$ifNull": ["$payload.extra_metrics.estimated_minutes_watched", { "$ifNull": ["$payload.watch_time", 0] }] },
                "likes": { "$ifNull": ["$payload.extra_metrics.likes", 0] },
                "comments": { "$ifNull": ["$payload.extra_metrics.comments", 0] },
                "ad_impressions": { "$ifNull": ["$payload.extra_metrics.ad_impressions", 0] },
                "ad_revenue": { "$ifNull": ["$payload.extra_metrics.estimated_ad_revenue", 0] }
            }
        },
        {
            "$group": {
                "_id": {
                    "video_id": "$video_id",
                    "month": "$month",
                    "platform": "$platform",
                    "geography": "$geography",
                    "event_type": "$event_type"
                },
                "title": { "$first": "$title" },
                "ip_name": { "$first": "$ip_name" },
                "series_name": { "$first": "$series_name" },
                "currency": { "$first": "$currency" },
                "monthly_revenue": { "$sum": "$revenue" },
                "monthly_revenue_cny": { "$sum": "$revenue_cny" },
                "monthly_revenue_svod": { "$sum": "$revenue_svod" },
                "monthly_revenue_tvod": { "$sum": "$revenue_tvod" },
                "monthly_revenue_avod": { "$sum": "$revenue_avod" },
                "monthly_views": { "$sum": "$views" },
                "monthly_watch_time": { "$sum": "$watch_time" },
                "monthly_likes": { "$sum": "$likes" },
                "monthly_comments": { "$sum": "$comments" },
                "monthly_ad_impressions": { "$sum": "$ad_impressions" },
                "monthly_ad_revenue": { "$sum": "$ad_revenue" }
            }
        },
        {
            "$merge": {
                "into": "monthly_performance_summaries",
                "whenMatched": "replace",
                "whenNotMatched": "insert"
            }
        }
    ])

    try:
        cleanup_filter = build_summary_cleanup_filter(
            platform=platform,
            year=year,
            run_all=run_all,
            time_field="_id.month",
        )
        if cleanup_filter and events_coll.count_documents(match_query, limit=1) > 0:
            del_res = db["monthly_performance_summaries"].delete_many(cleanup_filter)
            logging.info(
                f"Purged {del_res.deleted_count} stale Amazon monthly summary docs before rebuild ({cleanup_filter})."
            )
        events_coll.aggregate(pipeline, allowDiskUse=True)
        logging.info("Aggregation completed successfully. Data saved to monthly_performance_summaries.")

        # Ensure high-performance composite index for dashboard platform filtering
        monthly_coll = db["monthly_performance_summaries"]
        monthly_coll.create_index([("_id.platform", 1), ("_id.month", 1)], background=True, name="idx_platform_month")
        monthly_coll.create_index([("_id.month", 1), ("_id.platform", 1), ("_id.geography", 1)], background=True, name="idx_month_platform_geo")
        monthly_coll.create_index([("_id.video_id", 1)], background=True, name="idx_monthly_video_id")

        # Enrich YouTube documents with PostgreSQL catalog metadata (IP, Series, Title)
        if platform in (None, "youtube"):
            try:
                logging.info("Enriching YouTube documents with PostgreSQL IP and Series metadata...")
                enrich_youtube_collection(db, "monthly_performance_summaries")
            except Exception as enrich_err:
                logging.warning(f"YouTube catalog enrichment skipped or failed: {enrich_err}")
    except Exception as e:
        logging.error(f"Error during aggregation: {e}")
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build monthly aggregations for video performance.')
    parser.add_argument('--all', action='store_true', help='Process all historical data instead of just the last 60 days.')
    parser.add_argument('--year', type=int, default=None, help='Process specific calendar year (e.g. 2025).')
    parser.add_argument('--platform', type=str, default=None, help='Specific platform (amazon, youtube).')
    args = parser.parse_args()
    
    build_monthly_aggregations(run_all=args.all, year=args.year, platform=args.platform)
