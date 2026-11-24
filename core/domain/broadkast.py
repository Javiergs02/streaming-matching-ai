from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BroadkastContent:
    content_id: str
    title_name: str
    language_code: str = ""
    series_name: str = ""
    season_number: str = ""
    performance_score: str = ""
    no_dialog: str = ""
    project_id: str = ""
    project_name: str = ""
    series_id: str = ""
    season_id: str = ""
    video_id: str = ""
    episode_number: str = ""
