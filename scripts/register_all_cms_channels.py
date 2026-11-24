"""Registers all missing YouTube CMS channels and their videos into PostgreSQL.

Reads channels from the CMS export (or YouTube Data API) and cross-references
against amuseplatforms_db.youtube_channels to insert any missing channels
and sync all their video metadata into amuseplatforms_db.youtube_videos.
"""

import os
import sys
import re
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "apps" / "event_manager" / "src"))

from infrastructure.google_setup import load_yt_credentials, get_youtube_client, get_youtube_analytics_client
from infrastructure.adapters.youtube_video_fetcher import YoutubeVideoFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CSV_EXPORT_PATH = BASE_DIR / "scratch" / "yt_cms_export" / "Table data.csv"
FALLBACK_CSV = Path("/home/jgarcia/.gemini/antigravity/brain/1520d422-53eb-44c4-afb3-34d30d7f267e/scratch/yt_cms_export/Table data.csv")


def parse_iso8601_duration(duration_str: str) -> int:
    """Parses ISO 8601 duration string like 'PT48M22S' into seconds."""
    if not duration_str or not isinstance(duration_str, str):
        return 0
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', str(duration_str))
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def get_cms_channel_ids() -> dict[str, str]:
    """Retrieves all channel IDs and titles from CMS CSV export."""
    csv_file = CSV_EXPORT_PATH if CSV_EXPORT_PATH.exists() else FALLBACK_CSV
    if not csv_file.exists():
        log.warning(f"CSV export not found at {csv_file}. Will query YouTube API directly.")
        return {}

    df = pd.read_csv(csv_file)
    df = df[df["Canal"] != "Total"].dropna(subset=["Canal"]).copy()
    channels = {}
    for _, row in df.iterrows():
        c_id = str(row["Canal"]).strip()
        c_title = str(row.get("Título del canal", "")).strip()
        if c_id:
            channels[c_id] = c_title
    log.info(f"Loaded {len(channels)} channels from CMS CSV export: {csv_file}")
    return channels


def run_registration(limit=None):
    load_dotenv(str(BASE_DIR / ".env"))

    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWD") or os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")
    creds_file = os.getenv("CREDS_FILE")
    cms_id = os.getenv("CMS_ID")

    engine = create_engine(f"postgresql+psycopg2://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}")

    creds = load_yt_credentials(creds_file)
    data_client = get_youtube_client(creds)
    analytics_client = get_youtube_analytics_client(creds)
    fetcher = YoutubeVideoFetcher(data_client, analytics_client, cms_id)

    # 1. Identify missing channels
    cms_channels = get_cms_channel_ids()
    with engine.connect() as conn:
        existing_db_channels = set(
            pd.read_sql("SELECT channel_id FROM amuseplatforms_db.youtube_channels", conn)["channel_id"].dropna().unique()
        )

    if cms_channels:
        missing_ids = [cid for cid in cms_channels if cid not in existing_db_channels]
    else:
        # Fallback to API list
        log.info("Fetching all channels via YouTube Data API...")
        request = data_client.channels().list(
            part="snippet,contentOwnerDetails",
            managedByMe=True,
            onBehalfOfContentOwner=cms_id,
            maxResults=50
        )
        api_channels = {}
        while request:
            resp = request.execute()
            for it in resp.get("items", []):
                api_channels[it["id"]] = it.get("snippet", {}).get("title", "")
            request = data_client.channels().list_next(request, resp)
        missing_ids = [cid for cid in api_channels if cid not in existing_db_channels]

    log.info(f"Total existing channels in DB: {len(existing_db_channels)}")
    log.info(f"Total channels needing registration: {len(missing_ids)}")

    if not missing_ids:
        log.info("All CMS channels are already registered in PostgreSQL! Nothing to do.")
        return

    if limit:
        missing_ids = missing_ids[:limit]
        log.info(f"Limiting execution to first {limit} channels.")

    # 2. Fetch channel snippet metadata from API in chunks of 50
    log.info(f"Fetching metadata from YouTube API for {len(missing_ids)} channels...")
    channel_metadata = {}
    for i in range(0, len(missing_ids), 50):
        chunk = missing_ids[i:i + 50]
        resp = data_client.channels().list(
            part="snippet,contentOwnerDetails",
            id=",".join(chunk)
        ).execute()
        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            co = item.get("contentOwnerDetails", {})
            channel_metadata[item["id"]] = {
                "title": snippet.get("title", cms_channels.get(item["id"], "Sin Nombre")),
                "country_code": snippet.get("country", ""),
                "language": snippet.get("defaultLanguage", ""),
                "monetized": co.get("isMonetized", True)
            }

    # 3. Upsert channels into amuseplatforms_db.youtube_channels
    upsert_channel_query = text("""
        INSERT INTO amuseplatforms_db.youtube_channels (
            channel_id, serie_name, is_monetization_enabled, language, linked_date, is_active, country_code
        ) 
        VALUES (
            :channel_id, :serie_name, :is_monetization_enabled, :language, :linked_date, true, :country_code
        )
        ON CONFLICT (channel_id) 
        DO UPDATE SET 
            serie_name = EXCLUDED.serie_name,
            is_monetization_enabled = EXCLUDED.is_monetization_enabled,
            language = EXCLUDED.language,
            country_code = EXCLUDED.country_code,
            is_active = true;
    """)

    now_utc = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for cid in missing_ids:
            meta = channel_metadata.get(cid, {
                "title": cms_channels.get(cid, "Sin Nombre"),
                "country_code": "",
                "language": "",
                "monetized": True
            })
            conn.execute(upsert_channel_query, {
                "channel_id": cid,
                "serie_name": meta["title"],
                "is_monetization_enabled": meta["monetized"],
                "language": meta["language"] or None,
                "linked_date": now_utc,
                "country_code": meta["country_code"] or None
            })
            log.info(f"Upserted channel into DB: {meta['title']} ({cid})")

    # 4. Fetch and upsert all videos for these channels
    upsert_video_query = text("""
        INSERT INTO amuseplatforms_db.youtube_videos (
            video_id, channel_id, title, description, published_at, 
            duration, is_short, privacy_status, category_id, tags, default_audio_language, is_active
        ) VALUES (
            :video_id, :channel_id, :title, :description, :published_at, 
            :duration, :is_short, :privacy_status, :category_id, :tags, :default_audio_language, :is_active
        )
        ON CONFLICT (video_id) DO UPDATE SET 
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            duration = EXCLUDED.duration,
            is_short = EXCLUDED.is_short,
            privacy_status = EXCLUDED.privacy_status,
            category_id = EXCLUDED.category_id,
            tags = EXCLUDED.tags,
            default_audio_language = EXCLUDED.default_audio_language,
            is_active = true;
    """)

    total_videos_upserted = 0
    for idx, cid in enumerate(missing_ids, 1):
        ch_title = channel_metadata.get(cid, {}).get("title", cms_channels.get(cid, cid))
        log.info(f"[{idx}/{len(missing_ids)}] Fetching videos for channel '{ch_title}' ({cid})...")
        try:
            videos = fetcher.fetch_all_by_channel(cid)
            log.info(f"  -> Found {len(videos)} videos from API.")

            if not videos:
                continue

            with engine.begin() as conn:
                for v in videos:
                    extra = v.extra_data or {}
                    raw_tags = extra.get("tags")
                    tags_str = json.dumps(raw_tags) if isinstance(raw_tags, (list, dict)) else raw_tags
                    duration_secs = parse_iso8601_duration(extra.get("duration", ""))
                    is_short = 0 < duration_secs <= 60

                    conn.execute(upsert_video_query, {
                        "video_id": v.video_id,
                        "channel_id": cid,
                        "title": v.title or "Sin Título",
                        "description": extra.get("description", ""),
                        "published_at": v.published_at,
                        "duration": duration_secs,
                        "is_short": is_short,
                        "privacy_status": extra.get("privacy_status", "public"),
                        "category_id": extra.get("category_id") or None,
                        "tags": tags_str,
                        "default_audio_language": extra.get("default_audio_language"),
                        "is_active": True
                    })
            total_videos_upserted += len(videos)
            log.info(f"  -> Successfully upserted {len(videos)} videos.")
        except Exception as e:
            log.error(f"  -> Error fetching/upserting videos for channel {cid}: {e}")

    log.info(f"\nAll Done! Successfully registered {len(missing_ids)} channels and {total_videos_upserted} videos into PostgreSQL.")


if __name__ == "__main__":
    limit_arg = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    run_registration(limit=limit_arg)
