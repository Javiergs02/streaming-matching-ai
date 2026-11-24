import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_current_dir = str(Path(__file__).resolve().parent)
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

# Infrastructure technical setups
from infrastructure.google_setup import load_yt_credentials, get_youtube_client, get_youtube_analytics_client
from infrastructure.db_engine import get_db_engine, build_mongo_uri

# Infrastructure adapters
from infrastructure.adapters.youtube_video_fetcher import YoutubeVideoFetcher
from infrastructure.adapters.youtube_video_pg_repository import YoutubeVideoPostgresRepository
from infrastructure.adapters.youtube_channel_pg_repository import YoutubeChannelPostgresRepository
from infrastructure.adapters.mongo_publisher import MongoRepository

# Application layer
from application.yt_analytics_events_service import YtAnalyticsEventsService

def run_analytics_sync(yt_creds_path, cms_id, db_user, db_pass, db_host, db_port, db_name, 
                       channels_table, videos_table, stats_table, channel_cols, video_cols,
                       mongo_uri, mongo_db, coll_analytics, by_country=False, 
                       start_date=None, end_date=None):
    
    sync_mode_label = "Monthly Territories" if by_country else "Daily Global Analytics"
    print(f"--- Initializing Video {sync_mode_label} Synchronization Process ---")
    if start_date:
        print(f"--- Start Date Override: {start_date} ---")
    if end_date:
        print(f"--- End Date Override: {end_date} ---")
    
    creds_model = load_yt_credentials(yt_creds_path)
    yt_data_client = get_youtube_client(creds_model)
    yt_analytics_client = get_youtube_analytics_client(creds_model)
    sql_engine = get_db_engine(db_user, db_pass, db_host, db_port, db_name)

    channel_repo = YoutubeChannelPostgresRepository(sql_engine, channels_table, channel_cols)
    
    video_fetcher = YoutubeVideoFetcher(yt_data_client, yt_analytics_client, cms_id)
    video_repo = YoutubeVideoPostgresRepository(sql_engine, videos_table, video_cols, stats_table)
    publisher = MongoRepository(mongo_uri, mongo_db)

    analytics_service = YtAnalyticsEventsService(video_fetcher, video_repo, publisher, cms_id)

    try:
        channels = channel_repo.get_all_channels()
        print(f"Found {len(channels)} channels in database to sync analytics.")
        failed_channels = []

        for channel in channels:
            print(f"\n--- Processing Analytics for: {channel.title} ({channel.channel_id}) ---")
            try:
                analytics_service.execute(
                    channel.channel_id, 
                    coll_analytics, 
                    by_country=by_country, 
                    start_date_override=start_date,
                    end_date_override=end_date
                )
                print(f"--- Analytics synchronization for {channel.title} finished successfully ---")
            except Exception as e:
                print(f"Error processing channel {channel.title}: {e}")
                failed_channels.append((channel.channel_id, channel.title, str(e)))
                continue

        if channels and len(failed_channels) > len(channels) * 0.2:
            print(f"\n[CRITICAL] Massive failure detected: {len(failed_channels)}/{len(channels)} channels failed analytics sync.")
            sys.exit(1)
        elif failed_channels:
            print(f"\n[WARNING] Finished with {len(failed_channels)}/{len(channels)} channel errors.")
                
    except Exception as e:
        print(f"[CRITICAL] Error in synchronization process: {e}")
        sys.exit(1)
    finally:
        publisher.close()
        print("\n--- Analytics synchronization process finished ---")


if __name__ == "__main__":
    load_dotenv()

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
        "coll_analytics": os.getenv("MONGODB_ANALYTICS_COLLECTION") or "video_performance_events"
    }

    missing = [k for k, v in config_params.items() if v is None]
    missing_channel_cols = [k for k, v in channel_column_config.items() if v is None]
    missing_video_cols = [k for k, v in video_column_config.items() if v is None]
    
    if missing or missing_channel_cols or missing_video_cols:
        print(f"Error: Missing environment variables.")
        if missing: print(f"General: {', '.join(missing)}")
        if missing_channel_cols: print(f"Channel Columns: {', '.join(missing_channel_cols)}")
        if missing_video_cols: print(f"Video Columns: {', '.join(missing_video_cols)}")
        sys.exit(1)

    is_monthly = any(arg in sys.argv for arg in ("--monthly", "--monthly-territory", "--territories"))
    config_params["by_country"] = is_monthly

    run_analytics_sync(**config_params)