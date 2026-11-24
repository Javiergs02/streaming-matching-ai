import os
import sys
import logging
import urllib.parse
import argparse
from pathlib import Path
from datetime import datetime, timezone
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

def build_yearly_aggregations(run_all=False, from_events=False, year=None, platform=None):
    root = _PROJECT_ROOT
    dotenv_path = root / ".env"
    load_dotenv(dotenv_path)
    
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
    
    pipeline = []
    
    if from_events:
        # Build directly from raw daily events collection
        source_coll_name = os.getenv("MONGODB_ANALYTICS_COLLECTION", 'video_performance_events')
        source_coll = db[source_coll_name]
        logging.info(f"Source: Raw daily events ('{source_coll_name}')")

        match_query = build_events_match_query(
            platform=platform,
            year=year,
            run_all=run_all,
            incremental_window="2y",
        )

        if year:
            logging.info(f"Running for target year: {year} (platform: {platform or 'all'}).")
        elif not run_all:
            logging.info(
                f"Running in incremental mode. Processing from {match_query['payload.date']['$gte']} onwards (platform: {platform or 'all'})."
            )
        else:
            logging.info(f"Running in full mode. Processing ALL historical events (platform: {platform or 'all'}).")

        if match_query:
            pipeline.append({"$match": match_query})
            
        pipeline.extend([
            {
                "$project": {
                    "video_id": "$payload.video_id",
                    "platform": "$payload.platform",
                    "event_type": "$metadata.event_type",
                    "year": { "$substr": ["$payload.date", 0, 4] },
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
                        "year": "$year",
                        "platform": "$platform",
                        "geography": "$geography",
                        "event_type": "$event_type"
                    },
                    "title": { "$first": "$title" },
                    "ip_name": { "$first": "$ip_name" },
                    "series_name": { "$first": "$series_name" },
                    "currency": { "$first": "$currency" },
                    "yearly_revenue": { "$sum": "$revenue" },
                    "yearly_revenue_cny": { "$sum": "$revenue_cny" },
                    "yearly_revenue_svod": { "$sum": "$revenue_svod" },
                    "yearly_revenue_tvod": { "$sum": "$revenue_tvod" },
                    "yearly_revenue_avod": { "$sum": "$revenue_avod" },
                    "yearly_views": { "$sum": "$views" },
                    "yearly_watch_time": { "$sum": "$watch_time" },
                    "yearly_likes": { "$sum": "$likes" },
                    "yearly_comments": { "$sum": "$comments" },
                    "yearly_ad_impressions": { "$sum": "$ad_impressions" },
                    "yearly_ad_revenue": { "$sum": "$ad_revenue" }
                }
            },
            {
                "$merge": {
                    "into": "yearly_performance_summaries",
                    "whenMatched": "replace",
                    "whenNotMatched": "insert"
                }
            }
        ])
    else:
        # Build from pre-aggregated monthly summaries (fastest and consistent)
        source_coll_name = "monthly_performance_summaries"
        source_coll = db[source_coll_name]
        logging.info(f"Source: Pre-aggregated monthly summaries ('{source_coll_name}')")
        
        match_query = {}
        if platform:
            match_query["_id.platform"] = platform.strip().lower()

        if year:
            logging.info(f"Running for target year: {year} (platform: {platform or 'all'}).")
            match_query["_id.month"] = { "$regex": f"^{year}" }
        elif not run_all:
            current_year = datetime.now(timezone.utc).strftime("%Y")
            prev_year = str(int(current_year) - 1)
            logging.info(f"Running in incremental mode. Processing months from {prev_year}-01 onwards.")
            match_query["_id.month"] = { "$gte": f"{prev_year}-01" }
        else:
            logging.info(f"Running in full mode. Processing ALL monthly summaries (platform: {platform or 'all'}).")

        if match_query:
            pipeline.append({"$match": match_query})
            
        pipeline.extend([
            {
                "$project": {
                    "video_id": "$_id.video_id",
                    "year": { "$substr": ["$_id.month", 0, 4] },
                    "platform": "$_id.platform",
                    "geography": "$_id.geography",
                    "event_type": "$_id.event_type",
                    "title": { "$ifNull": ["$title", ""] },
                    "ip_name": { "$ifNull": ["$ip_name", ""] },
                    "series_name": { "$ifNull": ["$series_name", ""] },
                    "currency": { "$ifNull": ["$currency", "USD"] },
                    "revenue": { "$ifNull": ["$monthly_revenue", 0] },
                    "revenue_cny": { "$ifNull": ["$monthly_revenue_cny", 0] },
                    "revenue_svod": { "$ifNull": ["$monthly_revenue_svod", 0] },
                    "revenue_tvod": { "$ifNull": ["$monthly_revenue_tvod", 0] },
                    "revenue_avod": { "$ifNull": ["$monthly_revenue_avod", 0] },
                    "views": { "$ifNull": ["$monthly_views", 0] },
                    "watch_time": { "$ifNull": ["$monthly_watch_time", 0] },
                    "likes": { "$ifNull": ["$monthly_likes", 0] },
                    "comments": { "$ifNull": ["$monthly_comments", 0] },
                    "ad_impressions": { "$ifNull": ["$monthly_ad_impressions", 0] },
                    "ad_revenue": { "$ifNull": ["$monthly_ad_revenue", 0] }
                }
            },
            {
                "$group": {
                    "_id": {
                        "video_id": "$video_id",
                        "year": "$year",
                        "platform": "$platform",
                        "geography": "$geography",
                        "event_type": "$event_type"
                    },
                    "title": { "$first": "$title" },
                    "ip_name": { "$first": "$ip_name" },
                    "series_name": { "$first": "$series_name" },
                    "currency": { "$first": "$currency" },
                    "yearly_revenue": { "$sum": "$revenue" },
                    "yearly_revenue_cny": { "$sum": "$revenue_cny" },
                    "yearly_revenue_svod": { "$sum": "$revenue_svod" },
                    "yearly_revenue_tvod": { "$sum": "$revenue_tvod" },
                    "yearly_revenue_avod": { "$sum": "$revenue_avod" },
                    "yearly_views": { "$sum": "$views" },
                    "yearly_watch_time": { "$sum": "$watch_time" },
                    "yearly_likes": { "$sum": "$likes" },
                    "yearly_comments": { "$sum": "$comments" },
                    "yearly_ad_impressions": { "$sum": "$ad_impressions" },
                    "yearly_ad_revenue": { "$sum": "$ad_revenue" }
                }
            },
            {
                "$merge": {
                    "into": "yearly_performance_summaries",
                    "whenMatched": "replace",
                    "whenNotMatched": "insert"
                }
            }
        ])

    try:
        dest_coll = db["yearly_performance_summaries"]
        cleanup_filter = build_summary_cleanup_filter(
            platform=platform,
            year=year,
            run_all=run_all,
            time_field="_id.year",
        )
        if cleanup_filter and source_coll.count_documents(match_query, limit=1) > 0:
            del_res = dest_coll.delete_many(cleanup_filter)
            logging.info(
                f"Purged {del_res.deleted_count} stale Amazon yearly summary docs before rebuild ({cleanup_filter})."
            )

        logging.info("Executing aggregation pipeline...")
        source_coll.aggregate(pipeline, allowDiskUse=True)
        logging.info("Aggregation completed successfully. Data saved to 'yearly_performance_summaries'.")
        
        # Ensure indexes on target collection for optimal querying
        dest_coll.create_index([("_id.platform", 1), ("_id.year", 1)], background=True, name="idx_platform_year")
        dest_coll.create_index([("_id.event_type", 1), ("_id.year", 1)], background=True)
        dest_coll.create_index([("_id.video_id", 1)], background=True)
        logging.info("Indexes verified on 'yearly_performance_summaries'.")

        # Enrich YouTube documents with PostgreSQL catalog metadata (IP, Series, Title)
        if platform in (None, "youtube"):
            try:
                logging.info("Enriching YouTube documents with PostgreSQL IP and Series metadata...")
                enrich_youtube_collection(db, "yearly_performance_summaries")
            except Exception as enrich_err:
                logging.warning(f"YouTube catalog enrichment skipped or failed: {enrich_err}")
    except Exception as e:
        logging.error(f"Error during aggregation: {e}")
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build yearly aggregations for video performance in MongoDB.')
    parser.add_argument('--all', action='store_true', help='Process all historical data instead of current and previous year.')
    parser.add_argument('--year', type=int, default=None, help='Process specific calendar year (e.g. 2025).')
    parser.add_argument('--platform', type=str, default=None, help='Specific platform (amazon, youtube, tencent).')
    parser.add_argument('--from-events', action='store_true', help='Aggregate directly from raw daily events instead of monthly summaries.')
    args = parser.parse_args()
    
    build_yearly_aggregations(run_all=args.all, from_events=args.from_events, year=args.year, platform=args.platform)

