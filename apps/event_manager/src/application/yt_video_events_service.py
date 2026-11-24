import uuid
from datetime import datetime, timezone
from dataclasses import asdict
from domain.ports import VideoFetcher, VideoRepository, EventRepository

class YtVideoEventsService:
    def __init__(
        self, 
        fetcher: VideoFetcher, 
        repository: VideoRepository, 
        publisher: EventRepository, 
        cms_id: str
    ):
        self.fetcher = fetcher
        self.repository = repository
        self.publisher = publisher
        self.cms_id = cms_id.strip()

    def execute(self, channel_id: str, collection_name: str):
        print(f"[{collection_name}] Fetching videos from API and DB for channel {channel_id}...")
        
        current_videos = self.fetcher.fetch_all_by_channel(channel_id)
        db_videos = self.repository.get_all_by_channel(channel_id)
        
        if not current_videos and not db_videos:
            print(f"[{collection_name}] No videos found in API or DB for channel {channel_id}. Aborting sync.")
            return

        self._sync_linked_videos(current_videos, db_videos, channel_id, collection_name)
        self._sync_removed_videos(current_videos, db_videos, channel_id, collection_name)
        self._sync_metadata_changes(current_videos, db_videos, collection_name)
        
        print(f"[{collection_name}] Video sync complete for channel {channel_id}.")

    def _sync_linked_videos(self, current_videos, db_videos, channel_id: str, collection_name: str):
        existing_ids = {v.video_id for v in db_videos}
        api_ids = {v.video_id for v in current_videos}
        new_ids = api_ids - existing_ids

        if not new_ids:
            print(f"[{collection_name}] No new videos found for channel {channel_id}.")
            return

        for video in current_videos:
            if video.video_id in new_ids:
                event = self._create_linked_event(video)
                self.publisher.publish([event], collection_name)
                print(f"[{collection_name}] Event persisted (Linked): {video.title}")

    def _sync_removed_videos(self, current_videos, db_videos, channel_id: str, collection_name: str):
        existing_ids = {v.video_id for v in db_videos}
        api_ids = {v.video_id for v in current_videos}
        removed_ids = existing_ids - api_ids

        if not removed_ids:
            print(f"[{collection_name}] No removed videos detected for channel {channel_id}.")
            return

        # SAFETY THRESHOLD: Never mass-deactivate a channel's videos if API returned 0 videos while DB has videos
        if len(db_videos) > 0 and len(current_videos) == 0:
            print(f"[{collection_name}] [CRITICAL SAFETY ABORT] Channel {channel_id} returned 0 videos from API "
                  f"but has {len(db_videos)} in DB. Aborting video removal sync to prevent wiping channel catalog.")
            return

        if len(db_videos) > 10 and len(removed_ids) > 0.5 * len(db_videos):
            print(f"[{collection_name}] [CRITICAL SAFETY ABORT] Channel {channel_id}: attempted to remove {len(removed_ids)} "
                  f"out of {len(db_videos)} videos (>50%). Aborting removal sync for safety.")
            return

        for res_id in removed_ids:
            event = self._create_removed_event(res_id)
            self.publisher.publish([event], collection_name)
            print(f"[{collection_name}] Event persisted (Removed): ID {res_id}")

    def _sync_metadata_changes(self, current_videos, db_videos, collection_name: str):
        db_dict = {v.video_id: v for v in db_videos}
        existing_ids = set(db_dict.keys())
        
        api_ids = {v.video_id for v in current_videos}
        intersection = api_ids & existing_ids

        for video in current_videos:
            if video.video_id in intersection:
                old_data = db_dict[video.video_id]
                changes = self._detect_diff(video, old_data)

                if changes:
                    event = self._create_metadata_change_event(video.video_id, changes)
                    self.publisher.publish([event], collection_name)
                    print(f"[{collection_name}] Event persisted (Updated): {video.title}")

    def _create_linked_event(self, video):
        return {
            "metadata": self._build_metadata("youtube.video.linked", video.video_id),
            "payload": asdict(video)
        }

    def _create_removed_event(self, resource_id):
        return {
            "metadata": self._build_metadata("youtube.video.removed", resource_id),
            "payload": {"status": "unlinked", "reason": "Not found in channel uploads fetch"}
        }

    def _create_metadata_change_event(self, resource_id, changes):
        return {
            "metadata": self._build_metadata("youtube.video.metadata_updated", resource_id),
            "payload": {"changes": changes}
        }

    def _build_metadata(self, event_type, resource_id):
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "resource_id": resource_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "cms_id": self.cms_id
        }

    def _detect_diff(self, new, old):
        diff = {}
        
        new_extra = new.extra_data or {}
        old_extra = old.extra_data or {}
        
        if new.title != old.title:
            diff["title"] = {"before": old.title, "after": new.title}
            
        new_desc = new_extra.get("description", "")
        old_desc = old_extra.get("description", "")
        if new_desc != old_desc:
            diff["description"] = {"before": old_desc, "after": new_desc}

        new_privacy = new_extra.get("privacy_status")
        old_privacy = old_extra.get("privacy_status")
        if new_privacy != old_privacy:
            diff["privacy_status"] = {"before": old_privacy, "after": new_privacy}

        new_duration = new_extra.get("duration")
        old_duration = old_extra.get("duration")
        if new_duration != old_duration:
            diff["duration"] = {"before": old_duration, "after": new_duration}

        new_tags = new_extra.get("tags", [])
        old_tags = old_extra.get("tags", [])
        if set(new_tags) != set(old_tags):
            diff["tags"] = {"before": old_tags, "after": new_tags}

        return diff