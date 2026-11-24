import os
import sys
import urllib.parse
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from src.run_youtube_structural_consumer import run_youtube_structural_sync as start_performance_runner
from src.run_diffusion_consumer import run_diffusion_consumer as start_diffusion_runner

def main(config_performance, config_diffusion):
    print("=" * 60)
    print("      SEQUENTIAL EVENT CONSUMERS ORCHESTRATOR      ")
    print("=" * 60)
    
    print("[Step 1/2] - Starting YouTube performance sync...")
    try:
        start_performance_runner(**config_performance)
        print("[Success] - Phase 1 (YouTube Performance) completed successfully.")
    except Exception as e:
        print(f"[Fatal] - YouTube performance sync failed: {e}")
        print("[System] - Aborting execution. Structural sync will not be processed.")
        sys.exit(1)

    print("-" * 60)

    print("[Step 2/2] - Starting structural sync (Diffusions)...")
    try:
        start_diffusion_runner(**config_diffusion)
        print("[Success] - Phase 2 (Structural Sync) completed successfully.")
    except Exception as e:
        print(f"[Fatal] - Structural sync failed: {e}")
        sys.exit(1)

    print("=" * 60)
    print("[System] - Entire sequential workflow finished successfully.")
    print("=" * 60)


if __name__ == "__main__":
    load_dotenv()

    raw_mongo_uri = os.getenv("MONGODB_URI")
    if not raw_mongo_uri:
        print("[Error] - MONGODB_URI variable is not defined in .env.")
        sys.exit(1)

    try:
        parsed_url = urllib.parse.urlparse(raw_mongo_uri)
        mongo_host = parsed_url.hostname
        mongo_port = str(parsed_url.port or 27017)
    except Exception as e:
        print(f"[Error] - Could not parse MONGODB_URI: {e}")
        sys.exit(1)

    params_performance = {
        "db_user": os.getenv("DB_USER"),
        "db_pass": os.getenv("DB_PASSWD") or os.getenv("DB_PASSWORD"),
        "db_host": os.getenv("DB_HOST"),
        "db_port": os.getenv("DB_PORT", "5432"),
        "db_name": os.getenv("DB_NAME"),
        "mongo_user": os.getenv("MONGODB_WRITER_USER"),
        "mongo_pass": os.getenv("MONGODB_WRITER_PASSWD"),
        "mongo_host": mongo_host,
        "mongo_port": mongo_port,
        "mongo_db": os.getenv("MONGODB_DB_NAME"),
        "mongo_auth_db": "admin",
        "coll_channels": os.getenv("MONGODB_CHANNEL_EVENTS_COLLECTION"),
        "coll_videos": os.getenv("MONGODB_VIDEO_EVENTS_COLLECTION") 
    }

    params_diffusion = {
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

    configs_to_validate = [("Performance", params_performance), ("Diffusion", params_diffusion)]
    for name, cfg in configs_to_validate:
        missing = [k for k, v in cfg.items() if v is None]
        if missing:
            print(f"[Error] - Missing environment variables for {name}: {', '.join(missing)}")
            sys.exit(1)

    main(config_performance=params_performance, config_diffusion=params_diffusion)