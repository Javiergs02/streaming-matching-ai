import os
import psycopg2
from typing import List

from core.domain.broadkast import BroadkastContent
from core.repositories.broadkast import BroadkastRepository


class PostgresBroadkastRepository(BroadkastRepository):
    """Repository implementation that connects to the real PostgreSQL database.
    
    Reads from the `metadata_titles` table as the canonical source of truth,
    joined with `episode_versions` if needed, but primary focus is `metadata_titles`.
    """
    def __init__(self, dsn: str | None = None):
        if not dsn:
            dsn = (
                f"host={os.getenv('DB_HOST')} "
                f"port={os.getenv('DB_PORT')} "
                f"dbname={os.getenv('BK_DB_NAME') or 'broadkast_production'} "
                f"user={os.getenv('DB_USER')} "
                f"password={os.getenv('DB_PASSWD') or os.getenv('DB_PASSWORD')}"
            )
        self.dsn = dsn
        self._cache: list[BroadkastContent] | None = None

    def _get_connection(self):
        conn = psycopg2.connect(self.dsn)
        conn.set_session(readonly=True)
        return conn

    def get_contents(self) -> List[BroadkastContent]:
        """Fetch all canonical titles from metadata_titles into memory and cache them."""
        if self._cache is not None:
            return self._cache

        query = """
            SELECT 
                ev.episode_id AS content_id, 
                mt.title AS title_name,
                ev.language_code,
                s.name AS series_name,
                seasons.number AS season_number,
                ep.performance_score,
                s.no_dialog,
                p.id AS project_id,
                p.name AS project_name,
                s.id AS series_id,
                seasons.id AS season_id,
                ep.video_id,
                ep.number AS episode_number
            FROM metadata_titles mt
            JOIN episode_versions ev ON ev.id = mt.episode_version_id
            JOIN episodes ep ON ep.id = ev.episode_id
            LEFT JOIN series s ON s.id = ep.series_id
            LEFT JOIN seasons ON seasons.id = ep.season_id
            LEFT JOIN projects p ON p.id = s.project_id
            WHERE mt.title IS NOT NULL AND mt.title != ''
              AND ep.number NOT IN (1111, 9999)
              AND UPPER(TRIM(mt.title)) NOT IN ('INTRO', 'OUTRO')
        """
        
        contents = []
        # Using context manager for safe cleanup
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                for row in cursor.fetchall():
                    content_id = f"EP_{row[0]}"
                    title_name = row[1].strip() if row[1] else ""
                    lang_code = row[2] or ""
                    series_name = row[3] or ""
                    season_number = str(row[4]) if row[4] is not None else ""
                    perf_score = f"{row[5]:.2f}" if row[5] is not None else ""
                    no_dialog = str(row[6]) if row[6] is not None else ""
                    project_id = str(row[7]) if row[7] is not None else ""
                    project_name = row[8] or ""
                    series_id = str(row[9]) if row[9] is not None else ""
                    season_id = str(row[10]) if row[10] is not None else ""
                    video_id = row[11] or ""
                    episode_number = str(row[12]) if row[12] is not None else ""
                    
                    contents.append(BroadkastContent(
                        content_id=content_id, 
                        title_name=title_name,
                        language_code=lang_code,
                        series_name=series_name,
                        season_number=season_number,
                        performance_score=perf_score,
                        no_dialog=no_dialog,
                        project_id=project_id,
                        project_name=project_name,
                        series_id=series_id,
                        season_id=season_id,
                        video_id=video_id,
                        episode_number=episode_number
                    ))

        self._cache = contents
        return contents

    def get_all(self) -> List[BroadkastContent]:
        return self.get_contents()

    def search(self, query: str) -> List[BroadkastContent]:
        """Since the logic is now fully in-memory via HybridMatcher reading all contents,
        this method is optional, but we can implement it as a filter on cache."""
        all_contents = self.get_contents()
        q = query.lower()
        return [c for c in all_contents if q in c.title_name.lower()]
