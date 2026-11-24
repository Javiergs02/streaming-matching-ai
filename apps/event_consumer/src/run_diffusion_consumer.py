import os
import sys
import urllib.parse
from dotenv import load_dotenv

# Infrastructure technical setups
from infrastructure.psql_engine import create_postgres_engine
from infrastructure.mongo_engine import create_mongo_client

# Infrastructure adapters
from infrastructure.adapters.mongo_consumer_adapter import MongoConsumerRepository
from infrastructure.adapters.postgres_updater_adapter import PostgresStateRepository

# Application layer
from application.process_diffusion_events_service import ProcessDiffusionEventsUseCase


def run_diffusion_consumer(
    db_user, db_pass, db_host, db_port, db_name,
    mongo_user, mongo_pass, mongo_host, mongo_port, mongo_db, mongo_auth_db,
    coll_diffusion
):
    print("--- Initializing Diffusion Structural Ingestion Process ---")

    sql_engine = create_postgres_engine(
        user=db_user, 
        password=db_pass, 
        host=db_host, 
        port=db_port, 
        db_name=db_name
    )
    
    mongo_client = create_mongo_client(
        user=mongo_user,
        password=mongo_pass,
        host=mongo_host,
        port=mongo_port,
        auth_db=mongo_auth_db
    )
    
    consumer_repo = MongoConsumerRepository(client=mongo_client, db_name=mongo_db)
    postgres_repo = PostgresStateRepository(sql_engine)

    diffusion_use_case = ProcessDiffusionEventsUseCase(consumer_repo, postgres_repo)

    try:
        tipos_eventos_difusion = [
            "diffusion.succeeded",
            "diffusion.failed"
        ]

        print(f"\n[Phase 1] Reading diffusion events from collection: '{coll_diffusion}'...")
        diffusion_use_case.execute(
            collection_name=coll_diffusion,
            event_types=tipos_eventos_difusion
        )
        
        print("\n--- Diffusion synchronization batch finished successfully ---")

    except Exception as e:
        print(f"[CRITICAL] Error in diffusion synchronization process: {e}")
        sys.exit(1)
    finally:
        if hasattr(consumer_repo, "close"):
            consumer_repo.close()
        print("\n--- Diffusion synchronization process finished ---")


if __name__ == "__main__":
    load_dotenv()

    raw_mongo_uri = os.getenv("MONGODB_URI")
    parsed_url = urllib.parse.urlparse(raw_mongo_uri)
    
    mongo_host = parsed_url.hostname
    mongo_port = str(parsed_url.port)

    config_params = {
        "db_user": os.getenv("DB_USER"),
        "db_pass": os.getenv("DB_PASSWD") or os.getenv("DB_PASSWORD"),
        "db_host": os.getenv("DB_HOST"),
        "db_port": os.getenv("DB_PORT"),
        "db_name": os.getenv("DB_NAME"),
        "mongo_user": os.getenv("MONGODB_WRITER_USER"),
        "mongo_pass": os.getenv("MONGODB_WRITER_PASSWD"),
        "mongo_host": mongo_host,
        "mongo_port": mongo_port,
        "mongo_db": os.getenv("MONGODB_DB_NAME"),
        "mongo_auth_db": "admin", 
        "coll_diffusion": os.getenv("MONGODB_DIFFUSION_EVENTS_COLLECTION")
    }

    missing = [k for k, v in config_params.items() if v is None]
    
    if missing:
        print("[Error] Missing environment variables for Diffusion Consumer.")
        print(f"General Configuration Missing: {', '.join(missing)}")
        sys.exit(1)

    run_diffusion_consumer(**config_params)