import os
from dotenv import load_dotenv
import datetime as dt

# Infrastructure technical setups
from infrastructure.db_engine import get_db_engine, build_mongo_uri

# Infrastructure adapters
from infrastructure.adapters.diffusion_pg_repository import PostgresDiffusionRepository
from infrastructure.adapters.mongo_publisher import MongoRepository

# Application layer
from application.diffusion_events_service import DiffusionUseCase

def run_diffusion_results_generation(db_user, db_pass, db_host, db_port, db_name,
                                     mongo_uri, mongo_db, mongo_collection):
    
    print("--- Initializing Diffusion Results Event Generation ---")
    
    sql_engine = get_db_engine(db_user, db_pass, db_host, db_port, db_name)
    diffusion_repo = PostgresDiffusionRepository(sql_engine)
    publisher = MongoRepository(mongo_uri, mongo_db)
    diffusion_service = DiffusionUseCase(diffusion_repo, publisher)

    print("\nFetching SUCCEEDED diffusions from database...")
    succeeded_data = diffusion_repo.get_succeeded_diffusions()
    print(f"Found {len(succeeded_data)} successful diffusions to process.")

    for data in succeeded_data:
        diff_id = data['diffusion_id']
        video_id = data['video_id']
        release_date = data['release_date']
        
        occurred_at = data.get('occurred_at') or dt.datetime.now(dt.timezone.utc).isoformat()
        
        print(f"--- Processing SUCCEEDED Event for ID: {diff_id} ---")
        try:
            diffusion_service.mark_diffusion_succeeded(
                diffusion_id=str(diff_id),
                video_id=str(video_id),
                release_date=str(release_date),
                occurred_at=str(occurred_at),
                collection_name=str(mongo_collection)
            )
        except Exception as e:
            print(f"Error processing success event for {diff_id}: {e}")
            continue

    print("\nFetching FAILED diffusions from database...")
    failed_data = diffusion_repo.get_failed_diffusions()
    print(f"Found {len(failed_data)} failed diffusions to process.")

    for data in failed_data:
        diff_id = data['diffusion_id']
        error_reason = data.get('error_reason')
        occurred_at = data.get('occurred_at') or dt.datetime.now(dt.timezone.utc).isoformat()
        
        print(f"--- Processing FAILED Event for ID: {diff_id} ---")
        try:
            diffusion_service.mark_diffusion_failed(
                diffusion_id=str(diff_id), 
                collection_name=str(mongo_collection),
                error_reason=error_reason,
                occurred_at=str(occurred_at)
            )
        except Exception as e:
            print(f"Error processing failed event for {diff_id}: {e}")
            continue

    publisher.close()
    print("\n--- Diffusion results event generation process completed ---")

if __name__ == "__main__":
    load_dotenv()

    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("BK_DB_NAME")

    mongo_base_uri = os.getenv("MONGODB_URI")
    mongo_db = os.getenv("MONGODB_DB_NAME")
    mongo_collection = os.getenv("MONGODB_DIFFUSION_EVENTS_COLLECTION")

    mongo_uri = build_mongo_uri(
        base_uri=mongo_base_uri,
        user=os.getenv("MONGODB_WRITER_USER"),
        password=os.getenv("MONGODB_WRITER_PASSWD"),
    )

    run_diffusion_results_generation(
        db_user, db_pass, db_host, db_port, db_name,
        mongo_uri, mongo_db, mongo_collection
    )