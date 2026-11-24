import hashlib
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional
from domain.ports import DiffusionRepository, EventRepository
from domain.models import DiffusionUploadSucceededEvent, DiffusionUploadFailedEvent

class DiffusionUseCase:
    def __init__(self, repository: DiffusionRepository, publisher: EventRepository):
        self.repository = repository
        self.publisher = publisher

    def mark_diffusion_succeeded(self, diffusion_id: str, video_id: str, release_date: str, occurred_at: str, collection_name: str):
        platform, episodes_list = self.repository.get_diffusion_context(diffusion_id)

        if not episodes_list:
            print(f"[Warning] - [{collection_name}] Structural data missing for diffusion_id: {diffusion_id}. Event ignored.")
            return

        success_event = DiffusionUploadSucceededEvent(
            diffusion_id=diffusion_id,
            platform_video_id=video_id,
            release_date=release_date,
            platform=platform,
            episodes=episodes_list
        )
        
        enveloped = self._envelope("diffusion.succeeded", diffusion_id, asdict(success_event), source_timestamp=occurred_at)
        enveloped["_id"] = enveloped["metadata"]["event_id"]
        
        result = self.publisher.publish([enveloped], collection_name)
        
        if result.get("published_news", 0) > 0:
            print(f"[Success] - [{collection_name}] Event persisted (Succeeded FAT): ID {diffusion_id} -> Video {video_id}")
        else:
            print(f"[Info] - [{collection_name}] Event ignored (Succeeded state already exists): ID {diffusion_id}")

    def mark_diffusion_failed(self, diffusion_id: str, collection_name: str, error_reason: Optional[str] = None, occurred_at: Optional[str] = None):
        platform, episodes_list = self.repository.get_diffusion_context(diffusion_id)

        if not episodes_list:
            print(f"[Warning] - [{collection_name}] Structural data missing for diffusion_id: {diffusion_id}. Event ignored.")
            return

        failed_event = DiffusionUploadFailedEvent(
            diffusion_id=diffusion_id,
            error_reason=error_reason,
            platform=platform,
            episodes=episodes_list
        )
        
        enveloped = self._envelope("diffusion.failed", diffusion_id, asdict(failed_event), source_timestamp=occurred_at)
        enveloped["_id"] = enveloped["metadata"]["event_id"]
        
        result = self.publisher.publish([enveloped], collection_name)
        
        if result.get("published_news", 0) > 0:
            print(f"[Error] - [{collection_name}] Event persisted (Failed FAT): ID {diffusion_id} | Reason: {error_reason}")
        else:
            print(f"[Info] - [{collection_name}] Event ignored (Duplicate failure signature via timestamp): ID {diffusion_id}")

    def _envelope(self, event_type: str, resource_id: str, payload: dict, source_timestamp: Optional[str] = None) -> dict:
        timestamp = source_timestamp if source_timestamp else datetime.now(timezone.utc).isoformat()

        deterministic_string = f"{event_type}_{resource_id}_{timestamp}"
        deterministic_id = hashlib.sha256(deterministic_string.encode('utf-8')).hexdigest()

        return {
            "metadata": {
                "event_id": deterministic_id,
                "event_type": event_type,
                "resource_id": resource_id,
                "occurred_at": timestamp
            },
            "payload": payload
        }