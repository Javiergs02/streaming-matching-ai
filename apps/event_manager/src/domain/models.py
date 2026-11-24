from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

@dataclass(frozen=True)
class EpisodeDetail:
    series_code: str
    series_name: str
    project_code: str
    project_name: str
    season_number: str
    episode_number: str
    episode_in_season: str
    language_code: str
    position: str

@dataclass(frozen=True)
class DiffusionUploadSucceededEvent:
    diffusion_id: str
    platform_video_id: str
    release_date: datetime
    platform: str
    episodes: List[EpisodeDetail]

@dataclass(frozen=True)
class DiffusionUploadFailedEvent:
    diffusion_id: str
    platform: str
    episodes: List[EpisodeDetail]
    error_reason: Optional[str] = None

@dataclass(frozen=True)
class Channel:
    channel_id: str
    platform: str
    title: str = ""
    description: str = ""
    country_code: str = ""
    extra_data: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Video:
    video_id: str
    channel_id: str
    platform: str
    title: str
    published_at: str
    extra_data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class VideoPerformanceEvent:
    video_id: str
    platform: str
    date: str
    estimated_revenue: float
    geography: str = "Unknown Geo"
    extra_metrics: Dict[str, Any] = field(default_factory=dict)