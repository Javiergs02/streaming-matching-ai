import re
from sqlalchemy import text
from typing import Optional
from datetime import date
from domain.ports import VideoRepository
from domain.models import Video


def _validate_identifier(ident: str) -> str:
    if not ident or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$", str(ident).strip()):
        raise ValueError(f"Invalid SQL identifier: {ident}")
    return str(ident).strip()


class YoutubeVideoPostgresRepository(VideoRepository):
    def __init__(self, engine, table_name: str, column_mapping: dict, stats_table_name: str = None):
        self.engine = engine
        self.table_name = _validate_identifier(table_name)
        self.cols = {k: _validate_identifier(v) for k, v in column_mapping.items()}
        self.stats_table_name = _validate_identifier(stats_table_name) if stats_table_name else None

    def get_all_by_channel(self, channel_id: str) -> list[Video]:
        query = text(f"""
            SELECT 
                {self.cols['video_id']}, 
                {self.cols['channel_id']}, 
                {self.cols['title']}, 
                {self.cols['description']}, 
                {self.cols['published_at']}, 
                {self.cols['duration']}, 
                {self.cols['privacy_status']}, 
                {self.cols['category_id']}, 
                {self.cols['tags']}, 
                {self.cols['default_audio_language']}
            FROM {self.table_name}
            WHERE {self.cols['channel_id']} = :channel_id
        """)

        with self.engine.connect() as conn:
            result = conn.execute(query, {"channel_id": channel_id}).fetchall()
            
            videos = []
            for row in result:
                pg_extra_data = {
                    "description": row[3] if row[3] else "",
                    "duration": row[5] if row[5] else "",
                    "privacy_status": row[6] if row[6] else "",
                    "category_id": str(row[7]) if row[7] else "",
                    "tags": row[8] if row[8] else [],
                    "default_audio_language": row[9]
                }

                videos.append(Video(
                    video_id=row[0],
                    channel_id=row[1],
                    platform="youtube",
                    title=row[2] if row[2] else "",
                    published_at=str(row[4]) if row[4] else "",
                    extra_data=pg_extra_data
                ))
            return videos

    def get_existing_ids_by_channel(self, channel_id: str) -> set[str]:
        query = text(f"""
            SELECT {self.cols['video_id']} 
            FROM {self.table_name}
            WHERE {self.cols['channel_id']} = :channel_id
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {"channel_id": channel_id}).fetchall()
            return {row[0] for row in result}