"""
Script to synchronize monthly YouTube Analytics metrics with viewer country breakdown (Option 4).
Runs independently to generate monthly territory events for business reporting and Amazon comparison.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure the event_manager src directory is in sys.path
_current_dir = str(Path(__file__).resolve().parent)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from run_yt_analytics_events import (
    run_analytics_sync,
    load_yt_credentials,
    get_db_engine,
    build_mongo_uri
)

if __name__ == "__main__":
    load_dotenv()

    import argparse
    parser = argparse.ArgumentParser(
        description="Synchronize monthly YouTube Analytics metrics with viewer country breakdown (Option 4)."
    )
    parser.add_argument("--year", type=int, default=None, help="Target single calendar year to backfill (e.g. 2025).")
    parser.add_argument("--full-history", action="store_true", help="Backfill complete history from 2016-01-01 to present.")
    parser.add_argument("--from-year", type=int, default=None, help="Start year for backfill to present (e.g. 2016).")
    parser.add_argument("--start-date", type=str, default=None, help="Specific start date YYYY-MM-DD for backfill.")
    parser.add_argument("--end-date", type=str, default=None, help="Specific end date YYYY-MM-DD for backfill.")
    args, _ = parser.parse_known_args()

    start_date = None
    end_date = None

    if args.year:
        start_date = f"{args.year:04d}-01-01"
        end_date = f"{args.year:04d}-12-31"
    elif args.full_history:
        start_date = "2016-01-01"
    elif args.from_year:
        start_date = f"{args.from_year:04d}-01-01"

    if args.start_date:
        start_date = args.start_date
    if args.end_date:
        end_date = args.end_date

    channel_column_config = {
        "id": os.getenv("DB_CHANNELS_ID_COLUMN"),
        "title": os.getenv("DB_CHANNELS_TITLE_COLUMN"),
        "country": os.getenv("DB_CHANNELS_COUNTRY_COLUMN"),
        "monetization": os.getenv("DB_CHANNELS_MONETIZATION_COLUMN")
    }

    video_column_config = {
        "video_id": os.getenv("DB_VIDEOS_ID_COLUMN"),
        "channel_id": os.getenv("DB_VIDEOS_CHANNEL_ID_COLUMN"),
        "title": os.getenv("DB_VIDEOS_TITLE_COLUMN"),
        "description": os.getenv("DB_VIDEOS_DESC_COLUMN"),
        "published_at": os.getenv("DB_VIDEOS_PUBDATE_COLUMN"),
        "duration": os.getenv("DB_VIDEOS_DURATION_COLUMN"),
        "privacy_status": os.getenv("DB_VIDEOS_PRIVACY_COLUMN"),
        "category_id": os.getenv("DB_VIDEOS_CAT_COLUMN"),
        "tags": os.getenv("DB_VIDEOS_TAGS_COLUMN"),
        "default_audio_language": os.getenv("DB_VIDEOS_LANG_COLUMN")
    }

    mongo_uri = build_mongo_uri(
        base_uri=os.getenv("MONGODB_URI"),
        user=os.getenv("MONGODB_WRITER_USER"),
        password=os.getenv("MONGODB_WRITER_PASSWD"),
    )

    config_params = {
        "yt_creds_path": os.getenv("CREDS_FILE"),
        "cms_id": os.getenv("CMS_ID"),
        "db_user": os.getenv("DB_USER"),
        "db_pass": os.getenv("DB_PASSWD") or os.getenv("DB_PASSWORD"),
        "db_host": os.getenv("DB_HOST"),
        "db_port": os.getenv("DB_PORT"),
        "db_name": os.getenv("DB_NAME"),
        "channels_table": os.getenv("DB_CHANNELS_TABLE"),
        "videos_table": os.getenv("DB_VIDEOS_TABLE"),
        "stats_table": os.getenv("DB_STATS_TABLE"),
        "channel_cols": channel_column_config,
        "video_cols": video_column_config,
        "mongo_uri": mongo_uri,
        "mongo_db": os.getenv("MONGODB_DB_NAME"),
        "coll_analytics": os.getenv("MONGODB_ANALYTICS_COLLECTION") or "video_performance_events",
        "by_country": True,
        "start_date": start_date,
        "end_date": end_date
    }

    missing = [k for k, v in config_params.items() if v is None and k not in ("start_date", "end_date")]
    missing_channel_cols = [k for k, v in channel_column_config.items() if v is None]
    missing_video_cols = [k for k, v in video_column_config.items() if v is None]

    if missing or missing_channel_cols or missing_video_cols:
        print(f"Error: Missing environment variables for YouTube Event Manager.")
        if missing: print(f"General: {', '.join(missing)}")
        if missing_channel_cols: print(f"Channel Columns: {', '.join(missing_channel_cols)}")
        if missing_video_cols: print(f"Video Columns: {', '.join(missing_video_cols)}")
        print("\nPlease check your .env file or deployment environment variables.")
        sys.exit(1)

    print(">>> Launching YouTube Monthly Territory Analytics Sync (by_country=True) <<<")
    if args.year:
        print(f">>> Target Calendar Year: {args.year} (From {start_date} to {end_date}) <<<")
    else:
        if start_date:
            print(f">>> Start date configured: {start_date} <<<")
        if end_date:
            print(f">>> End date configured: {end_date} <<<")
    run_analytics_sync(**config_params)


