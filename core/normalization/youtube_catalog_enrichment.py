"""Enriches YouTube summary collections in MongoDB with PostgreSQL catalog metadata.

Adds 'ip_name', 'series_name', and 'title' to YouTube documents in:
  - monthly_performance_summaries
  - yearly_performance_summaries
"""

from __future__ import annotations

import logging
import os
import psycopg2
from typing import Dict, Optional, Tuple, Any
from pymongo import UpdateMany
from pymongo.database import Database

log = logging.getLogger(__name__)


def get_postgres_connection():
    """Builds a psycopg2 connection using environment configuration."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "amuseplatforms_db"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWD") or os.getenv("DB_PASSWORD"),
        connect_timeout=10,
    )


def fetch_youtube_catalog_map() -> Dict[str, Tuple[str, str, str]]:
    """Loads all YouTube video mappings from PostgreSQL and enriches unlinked videos with channel catalog.

    Returns:
        dict: video_id -> (ip_name, series_name, title)
    """
    conn = get_postgres_connection()
    cur = conn.cursor()
    query = """
        SELECT 
            yv.video_id,
            COALESCE(NULLIF(p.project_name, ''), 'UNMATCHED') AS ip_name,
            COALESCE(NULLIF(s.series_name, ''), NULLIF(yc.serie_name, ''), 'UNMATCHED_YT') AS series_name,
            COALESCE(NULLIF(yv.title, ''), 'Unknown Video') AS title,
            yc.channel_id
        FROM amuseplatforms_db.youtube_videos yv
        LEFT JOIN amuseplatforms_db.youtube_channels yc ON yv.channel_id = yc.channel_id
        LEFT JOIN amuseplatforms_db.episode_youtube_video eyv ON yv.video_id = eyv.video_id
        LEFT JOIN amuseplatforms_db.series s ON eyv.series_code = s.series_code
        LEFT JOIN amuseplatforms_db.projects p ON s.project_code = p.project_code;
    """
    cur.execute(query)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    from core.domain.youtube_channels import enrich_youtube_video_metadata

    mapping = {}
    for r in rows:
        vid, ip, series, title, cid = r[0], r[1], r[2], r[3], r[4]
        if ip == "UNMATCHED" or series == "UNMATCHED_YT":
            series, ip = enrich_youtube_video_metadata(cid, current_series=series, current_ip=ip)
        mapping[vid] = (ip, series, title)

    log.info(f"Loaded {len(mapping):,} YouTube video catalog mappings from PostgreSQL (enriched with channel fallback).")
    return mapping


def enrich_youtube_collection(
    db: Database,
    collection_name: str,
    catalog_map: Optional[Dict[str, Tuple[str, str, str]]] = None,
    target_video_ids: Optional[list[str]] = None,
    batch_size: int = 2000,
    progress_callback: Optional[callable] = None,
) -> dict[str, int]:
    """Enriches YouTube documents in the specified MongoDB collection with IP, Series, and Title.

    Args:
        db: MongoDB database instance
        collection_name: 'monthly_performance_summaries' or 'yearly_performance_summaries'
        catalog_map: Optional pre-loaded mapping of video_id -> (ip_name, series_name, title)
        target_video_ids: Optional list of video IDs to restrict enrichment (e.g. for incremental runs)
        batch_size: Number of UpdateMany requests per bulk_write batch
        progress_callback: Optional callback(current, total, modified)

    Returns:
        dict: Summary with 'matched' and 'modified' counts
    """
    coll = db[collection_name]
    
    if catalog_map is None:
        catalog_map = fetch_youtube_catalog_map()

    # Determine which video IDs need enrichment
    if target_video_ids is not None:
        vids_to_process = [v for v in target_video_ids if v in catalog_map]
    else:
        # Use known catalog videos directly to avoid slow distinct() full collection scans
        vids_to_process = list(catalog_map.keys())

    total_to_update = len(vids_to_process)
    if total_to_update == 0:
        log.info(f"Collection '{collection_name}' has 0 YouTube videos requiring metadata enrichment.")
        return {"matched": 0, "modified": 0}

    log.info(f"Enriching {total_to_update:,} distinct YouTube videos in '{collection_name}'...")

    total_matched = 0
    total_modified = 0

    # Process in batches
    for i in range(0, total_to_update, batch_size):
        chunk = vids_to_process[i : i + batch_size]
        updates = []
        for vid in chunk:
            ip, series, title = catalog_map[vid]
            updates.append(
                UpdateMany(
                    {"_id.video_id": vid, "_id.platform": "youtube"},
                    {"$set": {"ip_name": ip, "series_name": series, "title": title}},
                )
            )

        if updates:
            res = coll.bulk_write(updates, ordered=False)
            total_matched += res.matched_count
            total_modified += res.modified_count
            
        processed_count = min(i + len(chunk), total_to_update)
        if progress_callback:
            progress_callback(processed_count, total_to_update, total_modified)

    log.info(
        f"✓ Finished enriching '{collection_name}': "
        f"{total_matched:,} docs matched, {total_modified:,} docs updated with IP and Series."
    )
    return {"matched": total_matched, "modified": total_modified}
