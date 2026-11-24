from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Set, Tuple
from domain.models import Channel, EpisodeDetail, Video, VideoPerformanceEvent

class EventRepository(ABC):
    """
    Port representing the Event Store. Responsible for persisting domain events into the unified event log.
    """
    @abstractmethod
    def publish(self, event: List[Dict], collection_name: str):
        """Persists a list of enveloped events (metadata + payload) into the specified collection."""
        pass

    @abstractmethod
    def get_last_stats_date(self, video_ids: list[str], collection_name: str, by_country: bool = False, max_date: str = None, only_monetized: bool = False) -> dict[str, date]:
        """Queries the event store to find the maximum payload.date for each video_id (optionally bounded by max_date and monetization)."""
        pass

    @abstractmethod
    def get_existing_combinations(self, platform: str, dates: List[str], collection_name: str, video_ids: list = None, exclude_zero_revenue: bool = False, by_country: bool = False) -> Set[Tuple]:
        """
        Queries the event store to find already ingested combinations of (video_id, date) or (video_id, date, geo) to guarantee idempotency during batch processing.
        """
        pass

class ChannelFetcher(ABC):
    """
    Port to retrieve channel metadata from external APIs or third-party services. Acts as an anti-corruption layer against external platform changes.
    """
    @abstractmethod
    def fetch_all(self, cms_id: str) -> list:
        """Retrieves a list of all channels managed under a specific Content Management System."""
        pass

class ChannelRepository(ABC):
    """
    Port for the read database (e.g., PostgreSQL). Handles queries related to the current known state of Channels in the system.
    """
    @abstractmethod
    def get_existing_ids(self) -> set:
        """Returns a set of all channel identifiers currently tracked in the database."""
        pass

    @abstractmethod
    def get_all_channels(self) -> list[Channel]:
        """Retrieves the full list of tracked channels mapped to domain models."""
        pass

class VideoFetcher(ABC):
    """
    Port to retrieve video catalog data and performance metrics from external sources (APIs, Web Scrapers, etc.).
    """
    @abstractmethod
    def fetch_all_by_channel(self, channel_id: str) -> List[Video]:
        """Retrieves all videos associated with a specific channel or container"""
        pass

    @abstractmethod
    def fetch_historical_analysis(self, video_ids: list[str], start_date: str, end_date: str, by_country: bool = False) -> list[VideoPerformanceEvent]:
        """Fetches performance metrics (views, revenue, etc.) for a batch of videos within a date range."""
        pass

    @abstractmethod
    def fetch_monthly_analysis_by_country(self, video_ids: list[str], start_date: str, end_date: str) -> list[VideoPerformanceEvent]:
        """Fetches monthly performance metrics grouped by video and viewer country."""
        pass

class VideoRepository(ABC):
    """
    Port for the read database. Handles queries related to the current known state of Videos and their ingestion history.
    """
    @abstractmethod
    def get_all_by_channel(self, channel_id: str) -> List[Video]:
        """Retrieves all videos currently tracked under a specific channel."""
        pass

    @abstractmethod
    def get_existing_ids_by_channel(self, channel_id: str) -> Set[str]:
        """Returns a set of video identifiers already tracked for a specific channel."""
        pass

class DiffusionRepository(ABC):
    """
    Port for the read database handling the distribution workflows. 
    Manages the queries to extract the state of video uploads and publishing tasks across platforms.
    """
    
    @abstractmethod
    def get_succeeded_diffusions(self) -> list[dict]:
        """Retrieves a list of diffusions that have been successfully uploaded."""
        pass

    @abstractmethod
    def get_failed_diffusions(self) -> list[dict]:
        """Retrieves a list of diffusions that failed during the upload process."""
        pass
    
    @abstractmethod
    def get_diffusion_context(self, diffusion_id: str) -> Tuple[str, List[EpisodeDetail]]:
        """Retrieves the destination platform and the list of episodes associated with a specific diffusion task"""
        pass
