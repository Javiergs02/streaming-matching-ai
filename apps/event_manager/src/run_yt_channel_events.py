import os
import sys
from dotenv import load_dotenv

# Infrastructure technical setups
from infrastructure.google_setup import load_yt_credentials, get_youtube_client
from infrastructure.db_engine import get_db_engine, build_mongo_uri

# Infrastructure adapters
from infrastructure.adapters.youtube_channel_fetcher import YoutubeChannelFetcher
from infrastructure.adapters.youtube_channel_pg_repository import YoutubeChannelPostgresRepository
from infrastructure.adapters.mongo_publisher import MongoRepository

# Application layer
from application.yt_channel_events_service import YtChannelEventsService

def run_sync(yt_creds_path, cms_id, db_user, db_pass, db_host, db_port, db_name, 
             channels_table, column_config, mongo_uri, mongo_db, mongo_collection):
    
    print("--- Initializing Channel Synchronization Process ---")
    
    creds_model = load_yt_credentials(yt_creds_path)
    yt_client = get_youtube_client(creds_model)
    sql_engine = get_db_engine(db_user, db_pass, db_host, db_port, db_name)

    fetcher = YoutubeChannelFetcher(yt_client, cms_id)
    repository = YoutubeChannelPostgresRepository(sql_engine, channels_table, column_config)
    
    publisher = MongoRepository(mongo_uri, mongo_db)

    sync_service = YtChannelEventsService(fetcher, repository, publisher, cms_id)

    print(f"Target CMS: {cms_id}")
    try:
        print("Starting: Channels Sync Process...")
        
        sync_service.execute(mongo_collection)
        
        print("--- Synchronization finished successfully ---")
    except ValueError as mongo_err:
        print(f"Aborting execution due to infrastructure constraints: {mongo_err}")
        sys.exit(1)
    except Exception as e:
        print(f"Critical execution error: {e}")
        sys.exit(1)
    finally:
        publisher.close()

if __name__ == "__main__":
    load_dotenv()

    column_config = {
        "id": os.getenv("DB_CHANNELS_ID_COLUMN"),
        "title": os.getenv("DB_CHANNELS_TITLE_COLUMN"),
        "country": os.getenv("DB_CHANNELS_COUNTRY_COLUMN"),
        "monetization": os.getenv("DB_CHANNELS_MONETIZATION_COLUMN")
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
        "column_config": column_config,
        "mongo_uri": mongo_uri,
        "mongo_db": os.getenv("MONGODB_DB_NAME"),
        "mongo_collection": os.getenv("MONGODB_CHANNEL_EVENTS_COLLECTION")
    }

    missing = [k for k, v in config_params.items() if v is None]
    missing_cols = [k for k, v in column_config.items() if v is None]
    
    if missing or missing_cols:
        print(f"Error: Missing environment variables.")
        if missing: print(f"General: {', '.join(missing)}")
        if missing_cols: print(f"Columns: {', '.join(missing_cols)}")
        sys.exit(1)

    run_sync(**config_params)