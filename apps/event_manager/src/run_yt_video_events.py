import os
import sys
from dotenv import load_dotenv

# Infrastructure technical setups
from infrastructure.google_setup import load_yt_credentials, get_youtube_client, get_youtube_analytics_client
from infrastructure.db_engine import get_db_engine, build_mongo_uri

# Infrastructure adapters
from infrastructure.adapters.youtube_video_fetcher import YoutubeVideoFetcher
from infrastructure.adapters.youtube_video_pg_repository import YoutubeVideoPostgresRepository
from infrastructure.adapters.youtube_channel_pg_repository import YoutubeChannelPostgresRepository
from infrastructure.adapters.mongo_publisher import MongoRepository

# Application layer
from application.yt_video_events_service import YtVideoEventsService

def run_sync(yt_creds_path, cms_id, db_user, db_pass, db_host, db_port, db_name, 
             channels_table, videos_table, channel_cols, video_cols,
             mongo_uri, mongo_db, mongo_collection):
    
    print("--- Initializing Video Synchronization Process ---")
    
    creds_model = load_yt_credentials(yt_creds_path)
    yt_data_client = get_youtube_client(creds_model)
    yt_analytics_client = get_youtube_analytics_client(creds_model)
    sql_engine = get_db_engine(db_user, db_pass, db_host, db_port, db_name)

    channel_repo = YoutubeChannelPostgresRepository(sql_engine, channels_table, channel_cols)
    
    video_fetcher = YoutubeVideoFetcher(yt_data_client, yt_analytics_client, cms_id)
    video_repo = YoutubeVideoPostgresRepository(sql_engine, videos_table, video_cols)
    publisher = MongoRepository(mongo_uri, mongo_db)

    sync_service = YtVideoEventsService(video_fetcher, video_repo, publisher, cms_id)

    try:
        channels = channel_repo.get_all_channels()
        print(f"Found {len(channels)} channels in database to sync.")

        for channel in channels:
            print(f"\n--- Processing Channel: {channel.title} ({channel.channel_id}) ---")
            try:
                sync_service.execute(channel.channel_id, mongo_collection)
                print(f"--- Video synchronization finished successfully for channel: {channel.title} ---")
            except ValueError as mongo_err:
                print(f"Aborting execution due to infrastructure error: {mongo_err}")
                sys.exit(1)
            except Exception as e:
                print(f"Execution error on channel {channel.channel_id}: {e}")
                continue

    except SystemExit:
        raise
    except Exception as e:
        print(f"[CRITICAL] Unhandled error during video sync: {e}")
        sys.exit(1)
    finally:
        publisher.close()
        print("\n--- Video synchronization process finished ---")


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
        "db_pass": os.getenv("DB_PASSWD"),
        "db_host": os.getenv("DB_HOST"),
        "db_port": os.getenv("DB_PORT"),
        "db_name": os.getenv("DB_NAME"),
        "channels_table": os.getenv("DB_CHANNELS_TABLE"),
        "videos_table": os.getenv("DB_VIDEOS_TABLE"),
        "channel_cols": channel_column_config,
        "video_cols": video_column_config,
        "mongo_uri": mongo_uri,
        "mongo_db": os.getenv("MONGODB_DB_NAME"),
        "mongo_collection": os.getenv("MONGODB_VIDEO_EVENTS_COLLECTION") 
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

    run_sync(**config_params)