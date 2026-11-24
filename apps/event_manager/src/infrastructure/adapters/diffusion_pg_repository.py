from typing import List, Tuple
from sqlalchemy import text
from domain.ports import DiffusionRepository
from domain.models import EpisodeDetail

class PostgresDiffusionRepository(DiffusionRepository):
    def __init__(self, engine):
        self.engine = engine

    def get_succeeded_diffusions(self) -> list[dict]:
        query = text("""
            SELECT id, video_id, release_date, updated_at 
            FROM public.youtube_contents 
            WHERE status = 'uploaded' 
              AND error_status = 'no_errors' 
              AND video_id IS NOT NULL
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query).fetchall()
        
        return [
            {
                "diffusion_id": str(row.id),
                "video_id": row.video_id,
                "release_date": str(row.release_date) if row.release_date else None,
                "occurred_at": row.updated_at.isoformat() if row.updated_at else None
            }
            for row in result
        ]

    def get_failed_diffusions(self) -> list[dict]:
        query = text("""
            SELECT id, error_status, updated_at 
            FROM public.youtube_contents 
            WHERE error_status IS NOT NULL 
              AND error_status != 'no_errors'
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query).fetchall()
            
        return [
            {
                "diffusion_id": str(row.id),
                "error_reason": row.error_status,
                "occurred_at": row.updated_at.isoformat() if row.updated_at else None
            }
            for row in result
        ]

    def get_diffusion_context(self, diffusion_id: str) -> Tuple[str, List[EpisodeDetail]]:
        query = text("""
            SELECT 
                evc.content_type AS platform,
                s.code AS series_code,
                s.name AS series_name,
                p.code AS project_code,
                p.name AS project_name,
                e.season_id AS season_number,
                e.number AS episode_number,
                e.number_in_season AS episode_in_season,
                ev.language_code,
                evc.position
            FROM public.episode_version_contents evc
            JOIN public.episode_versions ev ON evc.episode_version_id = ev.id
            JOIN public.episodes e ON ev.episode_id = e.id
            JOIN public.series s ON e.series_id = s.id
            JOIN public.projects p ON s.project_id = p.id
            WHERE evc.content_id = :diffusion_id
            ORDER BY evc.position ASC
        """)

        with self.engine.connect() as conn:
            result = conn.execute(query, {"diffusion_id": diffusion_id}).fetchall()

        if not result:
            return "", []

        platform = result[0].platform
        episodes = []

        for row in result:
            episode = EpisodeDetail(
                series_code=str(row.series_code or "").strip(),
                series_name=str(row.series_name or "").strip(),
                project_code=str(row.project_code or "").strip(),
                project_name=str(row.project_name or "").strip(),
                season_number=str(row.season_number or "").strip(),
                episode_number=str(row.episode_number or "").strip(),
                episode_in_season=str(row.episode_in_season or "").strip(),
                language_code=str(row.language_code or "").strip(),
                position=str(row.position or "").strip(),
            )
            episodes.append(episode)

        print(f"[Info] - Repository mapped {len(episodes)} episodes with clean text codes for diffusion {diffusion_id}")

        return platform, episodes