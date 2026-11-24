"""Backfills historical YouTube analytics for target channels.

Queries YouTube Analytics API year-by-year from 2016 to 2024 for:
  - Daily Global analytics (by_country=False, geography='Global')
  - Monthly Territory analytics (by_country=True)
Uses YtAnalyticsEventsService with built-in deduplication and date bounding.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "apps" / "event_manager" / "src"))

from infrastructure.google_setup import load_yt_credentials, get_youtube_client, get_youtube_analytics_client
from infrastructure.db_engine import get_db_engine, build_mongo_uri
from infrastructure.adapters.youtube_video_fetcher import YoutubeVideoFetcher
from infrastructure.adapters.youtube_video_pg_repository import YoutubeVideoPostgresRepository
from infrastructure.adapters.youtube_channel_pg_repository import YoutubeChannelPostgresRepository
from infrastructure.adapters.mongo_publisher import MongoRepository
from application.yt_analytics_events_service import YtAnalyticsEventsService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# 12 Newly registered Amuse production channels
AMUSE_12_CHANNELS = [
    "UCLYjKjBOoeAreTYe1YBeYhA",  # Action Mini-Trucks ! - English
    "UCiuh9hIOVKdDBGMzj0ISfMA",  # Action Mini Trucks ! - 中文
    "UCP2A5WQS1KWweYgYmT34dLg",  # Action Mini Trucks ! - Polski
    "UCGnIh0IsPMe2KL5pw00YKEw",  # Truck Games - Português
    "UC4yatxQOSwg4OCClRADm5vg",  # Truck Games - русский
    "UCHoJflbNWBkIAOr5usMRbvw",  # Truck Games - Español
    "UCpo-pGmh-mARMnPyxaQqOdQ",  # Truck Games - Français
    "UCg_Szk-KpybUQvTxDTT7anw",  # Luluś - Polski
    "UCdBpCISTA-2xbzPhHmDQ53A",  # Louie - Português
    "UCxnMi_c2sbLWoO-9lQtUUog",  # Louie - Deutsche
    "UCY0lk6nYK5cYXqkmdcVvGqA",  # Louie - Español
    "UCQre6kV21tQK6udMSkolivw",  # Louie, dibújame - Español castellano
]

# 52 Newly registered partner / CMS channels
CMS_PARTNER_52_CHANNELS = [
    "UCUkslTRrWDdmZmncHpb9sLQ",  # Molang
    "UCV8KtydNYvlvY7KEcRkm9kQ",  # Pitchoun Toons
    "UCetJ_lGSdB1N2Vwcn9A-plg",  # Lévanah SOLOMON's Family
    "UCZFD9wtWj10uaN21bPac0dA",  # Didou dessine-moi | Officiel
    "UC_gBxLrw0A0IamAEMZ7umtw",  # Brèves de classe
    "UCaIcgxGFjyfZgoIaJT0s0hQ",  # Gulli
    "UCvAT5J1nwF2xM1kZuSGTi8A",  # Gu'Live
    "UCW9KPpAY22Nqdw-1heAh5Cw",  # Mouk en Français | Officiel (HD)
    "UCYR83xZ5fKf671Lj5NwafDw",  # Corneil & Bernie | Officiel
    "UCp5ebGI3ime0kOji9IkkRgg",  # 64 Zoo Lane | Official *HD*
    "UCnwAH5gWfPhvebdvHyrUlIg",  # Mimi Cracra
    "UCtd8rTI1AuH_WnWovQhXB7A",  # Lascars
    "UCBKb_63uzfJiAI-83LT62Ag",  # Mouk in English | Official (HD)
    "UCHUPhHa9v3Qz6eP753QfdLg",  # TiJi
    "UCh80KBGM53Mkj0gMlByc3NA",  # la récré des ptits loups
    "UCdgoEccc_SJhokwGHTO7mcg",  # Pirata & Capitano
    "UC33PlKn3qqJjDU-s3bHs2tA",  # Watch my Chops - Corneil & Bernie
    "UC4iFDFajIpyiphD2LY6-2sQ",  # Canal J
    "UCE-F_wKDd904nzRnOOcRQyQ",  # Saturnin | Officiel
    "UCfFMFpVn5uGNeTmkSkp9zqA",  # Caroline et ses amis | Officiel
    "UCOEFyvaMZ1HapM8-2CNzNXg",  # Rainbow Chicks
    "UCyx0viuF3BqE3lQmXEnoMQw",  # Mouk der Weltreisebär
    "UCm6XN2PW_9AX6Gdf1QPyIaQ",  # Рисунки Тёмы
    "UCCWdlUv_U199trb1Vt7bStA",  # Kung Fu Bunny | Official
    "UC_TexWsZqW4uhgcsQQp94pw",  # Les Aventures de Nasredine
    "UCNbZJLl1Emt1O_JVk5NYjFA",  # Pirata y Capitano en español
    "UCwpJu2jGyzc0qJUW9odzg8A",  # ELLE Girl
    "UC5MnNmovbjCs59wah8tt_0A",  # Мук
    "UCJYxx6mRCi7UrJCyETytZHA",  # MCM la chaîne
    "UC9O-2oNbR8Yb18VoADyRwDA",  # Pirata and Capitano in english !
    "UCZINSK9JJudGNDkhUNOko9g",  # Homiez (Round da Way) - Official
    "UCn4NoIZ7wTn3xZPJdsjAL4A",  # Nasreddin Hocanin Maceralari
    "UCov_OXS-ciEWNxIJo-g7Y4Q",  # 安妮海盗和阿诺机长 - Pirata & Capitano
    "UC_KeYFJIIA-f50vTbvUiiuw",  # Les Tutos de Gulli (Gulli Officiel)
    "UC-oU9-TC8JkO8D2CXKGBp0w",  # Gulli'Vert (Gulli Officiel)
    "UCT6zqwvo01_QxVR_QvWtnPg",  # Signe tes clips (Gulli Officiel)
    "UC3f9Cg9P5iJu3atCJFpmf7Q",  # The adventures of Nasredin
    "UCK5CN-IoM7HIkmmQFIyINRg",  # Les Tactiques d'Emma (Gulli Officiel)
    "UCvhpFgoaUzgBhAiZkwkMDDA",  # June TV
    "UC6f61gsIBOpNjfIuZPbxqrw",  # Kit i Kate - bajki dla dzieci
    "UCCOtSbNJofm3LAWYx5QLLKA",  # ムークのせかいりょこう
    "UCGUanvI5NoLyXKUqRrZZ3AA",  # Mon Robot Et Moi | Officiel
    "UCCkFxjuTsrXiwv_nEql1bmg",  # Arthur Autour du Monde
    "UCRPSok4AvA3J5ysqHKVs6jw",  # The Valentines
    "UCIcPnM75PzJTxLQYwxtrFuA",  # 阿凡提
    "UCcFJJ9bkaKt5u6Mk9c0ys-Q",  # Nico - Funny Cartoon for Kids
    "UCno_7UZ4Z7HzD9MrSA9KLjg",  # ماجراهای نصرالدین
    "UCAwWRk3GJuXrUYHawetNKVA",  # Le Gu'Live en fait toute une montagne
    "UC9ASp4HQrMVf05oLkWDnSSw",  # Tahiti Quest (Gulli Officiel)
    "UC23p8dHapv9cS0vA7szu5-Q",  # Safari Go
    "UCNFrqwo6JZIdblGF-HpkW2Q",  # Ruben & Les P'tites Toques (Gulli Officiel)
    "UCbsgszfTnKWHpq6aCgbtPvQ",  # Pirata e Capitano
]

ALL_NEW_64_CHANNELS = AMUSE_12_CHANNELS + CMS_PARTNER_52_CHANNELS

# Priority target channels with verified historical gaps or newly added
DEFAULT_TARGET_CHANNELS = [
    # Top Discrepancy channels already in DB
    "UCxiOfWB9GnMxjm9pfKbqx1w",  # Shark Academy - Songs for kids ($216k diff)
    "UCN37xOOHwd0WvXmcN8nUwGA",  # Shark Academy - Canciones infantiles ($209k diff)
    "UCvqCQVDDj-8EyaeCCya21ag",  # Learn Colors TV ($84k diff)
    "UCbGsJIfd66LLdvDae9lJvMg",  # Kids Learning with Trucks & Toys ($73k diff)
    "UC-PrBbBlScO9CmH_51fXqhQ",  # Super Truck - Car City Universe ($34k diff)
    "UCz0PK40XmqRqIzKU4hWweZw",  # Lily's Song ($15k diff)
    "UC8fFnCr4q_wYYpD4dXxyrtw",  # Tom the Tow Truck - Polskie ($14k diff)
    "UCyfirAu65XJjRTKL0O9gP7w",  # Tom the Tow Truck - Español ($12k diff)
    "UC2NuYkLGdw_no6Yccn7ROlg",  # Kick! ($6k diff)
    # Newly registered Amuse channels
    *AMUSE_12_CHANNELS
]


def run_backfill(channel_ids=None, start_year=2016, end_year=2024, sync_territories=True):
    load_dotenv(str(BASE_DIR / ".env"))

    channels_to_sync = channel_ids or DEFAULT_TARGET_CHANNELS

    yt_creds_path = os.getenv("CREDS_FILE")
    cms_id = os.getenv("CMS_ID")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWD") or os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")
    channels_table = os.getenv("DB_CHANNELS_TABLE", "amuseplatforms_db.youtube_channels")
    videos_table = os.getenv("DB_VIDEOS_TABLE", "amuseplatforms_db.youtube_videos")
    coll_analytics = os.getenv("MONGODB_ANALYTICS_COLLECTION", "video_performance_events")

    channel_column_config = {
        "id": os.getenv("DB_CHANNELS_ID_COLUMN", "channel_id"),
        "title": os.getenv("DB_CHANNELS_TITLE_COLUMN", "serie_name"),
        "country": os.getenv("DB_CHANNELS_COUNTRY_COLUMN", "country_code"),
        "monetization": os.getenv("DB_CHANNELS_MONETIZATION_COLUMN", "is_monetization_enabled")
    }

    video_column_config = {
        "video_id": os.getenv("DB_VIDEOS_ID_COLUMN", "video_id"),
        "channel_id": os.getenv("DB_VIDEOS_CHANNEL_ID_COLUMN", "channel_id"),
        "title": os.getenv("DB_VIDEOS_TITLE_COLUMN", "title"),
        "description": os.getenv("DB_VIDEOS_DESC_COLUMN", "description"),
        "published_at": os.getenv("DB_VIDEOS_PUBDATE_COLUMN", "published_at"),
        "duration": os.getenv("DB_VIDEOS_DURATION_COLUMN", "duration"),
        "privacy_status": os.getenv("DB_VIDEOS_PRIVACY_COLUMN", "privacy_status"),
        "category_id": os.getenv("DB_VIDEOS_CAT_COLUMN", "category_id"),
        "tags": os.getenv("DB_VIDEOS_TAGS_COLUMN", "tags"),
        "default_audio_language": os.getenv("DB_VIDEOS_LANG_COLUMN", "default_audio_language")
    }

    mongo_uri = build_mongo_uri(
        base_uri=os.getenv("MONGODB_URI"),
        user=os.getenv("MONGODB_WRITER_USER"),
        password=os.getenv("MONGODB_WRITER_PASSWD"),
    )

    creds_model = load_yt_credentials(yt_creds_path)
    yt_data_client = get_youtube_client(creds_model)
    yt_analytics_client = get_youtube_analytics_client(creds_model)
    sql_engine = get_db_engine(db_user, db_pass, db_host, db_port, db_name)

    video_fetcher = YoutubeVideoFetcher(yt_data_client, yt_analytics_client, cms_id)
    video_repo = YoutubeVideoPostgresRepository(sql_engine, videos_table, video_column_config)
    publisher = MongoRepository(mongo_uri, os.getenv("MONGODB_DB_NAME"))
    analytics_service = YtAnalyticsEventsService(video_fetcher, video_repo, publisher, cms_id)

    log.info(f"Starting historical backfill for {len(channels_to_sync)} channels ({start_year} - {end_year})...")

    try:
        for idx, ch_id in enumerate(channels_to_sync, 1):
            log.info(f"\n========================================================")
            log.info(f"[{idx}/{len(channels_to_sync)}] Processing Channel ID: {ch_id}")
            log.info(f"========================================================")

            for year in range(start_year, end_year + 1):
                start_d = f"{year}-01-01"
                end_d = f"{year}-12-31"

                # 1. Daily Global Analytics
                log.info(f"--- [Global] Channel {ch_id} | Year {year} ({start_d} to {end_d}) ---")
                try:
                    analytics_service.execute(
                        channel_id=ch_id,
                        mongo_collection=coll_analytics,
                        by_country=False,
                        start_date_override=start_d,
                        end_date_override=end_d
                    )
                except Exception as e:
                    log.error(f"Error syncing global analytics for channel {ch_id} year {year}: {e}")

                # 2. Monthly Territories Analytics
                if sync_territories:
                    log.info(f"--- [Territories] Channel {ch_id} | Year {year} ({start_d} to {end_d}) ---")
                    try:
                        analytics_service.execute(
                            channel_id=ch_id,
                            mongo_collection=coll_analytics,
                            by_country=True,
                            start_date_override=start_d,
                            end_date_override=end_d
                        )
                    except Exception as e:
                        log.error(f"Error syncing territory analytics for channel {ch_id} year {year}: {e}")

    finally:
        publisher.close()
        log.info("\nBackfill process finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical YouTube analytics.")
    parser.add_argument("--channels", nargs="+", help="Specific channel IDs to sync.")
    parser.add_argument("--new-64", "--new-cms", action="store_true", help="Sync all 64 newly added channels (12 Amuse + 52 partner channels).")
    parser.add_argument("--amuse-new", action="store_true", help="Sync only the 12 newly registered Amuse channels (2017-2025).")
    parser.add_argument("--partners-52", action="store_true", help="Sync only the 52 newly registered partner channels (2016-2024).")
    parser.add_argument("--all-cms", action="store_true", help="Sync all channels registered in amuseplatforms_db.youtube_channels (full historical CMS backfill).")
    parser.add_argument("--start-year", type=int, default=None, help="Start year (default: 2017 for --amuse-new, else 2016).")
    parser.add_argument("--end-year", type=int, default=None, help="End year (default: 2025 for --amuse-new, else 2024).")
    parser.add_argument("--no-territories", action="store_true", help="Skip monthly territorial breakdown (syncs only daily global analytics much faster).")
    args = parser.parse_args()

    if args.new_64:
        selected_channels = ALL_NEW_64_CHANNELS
        s_year = args.start_year or 2016
        e_year = args.end_year or 2024
    elif args.partners_52:
        selected_channels = CMS_PARTNER_52_CHANNELS
        s_year = args.start_year or 2016
        e_year = args.end_year or 2024
    elif args.amuse_new:
        selected_channels = AMUSE_12_CHANNELS
        s_year = args.start_year or 2017
        e_year = args.end_year or 2025
    elif args.all_cms:
        # Load all channels from database
        load_dotenv(str(BASE_DIR / ".env"))
        eng = get_db_engine(os.getenv("DB_USER"), os.getenv("DB_PASSWD") or os.getenv("DB_PASSWORD"), os.getenv("DB_HOST"), os.getenv("DB_PORT"), os.getenv("DB_NAME"))
        ch_repo = YoutubeChannelPostgresRepository(eng, os.getenv("DB_CHANNELS_TABLE", "amuseplatforms_db.youtube_channels"), {"id": "channel_id", "title": "serie_name", "country": "country_code", "monetization": "is_monetization_enabled"})
        selected_channels = [c.channel_id for c in ch_repo.get_all_channels()]
        s_year = args.start_year or 2016
        e_year = args.end_year or 2024
    else:
        selected_channels = args.channels
        s_year = args.start_year or 2016
        e_year = args.end_year or 2024

    run_backfill(
        channel_ids=selected_channels,
        start_year=s_year,
        end_year=e_year,
        sync_territories=not args.no_territories
    )
