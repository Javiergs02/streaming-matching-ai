import uuid
from datetime import datetime, timezone
from dataclasses import asdict
from domain.ports import ChannelFetcher, ChannelRepository, EventRepository

class YtChannelEventsService:
    def __init__(
        self, 
        fetcher: ChannelFetcher, 
        repository: ChannelRepository, 
        publisher: EventRepository, 
        cms_id: str
    ):
        self.fetcher = fetcher
        self.repository = repository
        self.publisher = publisher
        self.cms_id = cms_id.strip()

    def execute(self, collection_name: str):
        print(f"[{collection_name}] Fetching channels from API and DB...")
        
        current_channels = self.fetcher.fetch_all()
        db_channels = self.repository.get_all_channels()
        
        if not current_channels and not db_channels:
            print(f"[{collection_name}] No channels found in API or DB. Aborting sync.")
            return

        self._sync_linked_channels(current_channels, db_channels, collection_name)
        self._sync_removed_channels(current_channels, db_channels, collection_name)
        self._sync_metadata_changes(current_channels, db_channels, collection_name)
        
        print(f"[{collection_name}] Channel sync complete.")

    def _sync_linked_channels(self, current_channels, db_channels, collection_name: str):
        existing_ids = {c.channel_id for c in db_channels}
        api_ids = {ch.channel_id for ch in current_channels}
        new_ids = api_ids - existing_ids

        if not new_ids:
            print(f"[{collection_name}] No new channels found.")
            return

        for channel in current_channels:
            if channel.channel_id in new_ids:
                event = self._create_linked_event(channel)
                self.publisher.publish([event], collection_name)
                print(f"[{collection_name}] Event persisted (Linked): {channel.title}")

    def _sync_removed_channels(self, current_channels, db_channels, collection_name: str):
        existing_ids = {c.channel_id for c in db_channels}
        api_ids = {ch.channel_id for ch in current_channels}
        removed_ids = existing_ids - api_ids

        if not removed_ids:
            print(f"[{collection_name}] No removed channels detected.")
            return

        # SAFETY THRESHOLD: If more than 20% of channels seem to have disappeared at once,
        # or if api_ids is empty while db_channels exists, abort removal sync to protect catalog.
        if len(db_channels) > 10 and len(removed_ids) > 0.2 * len(db_channels):
            print(f"[{collection_name}] [CRITICAL SAFETY ABORT] Attempted to remove {len(removed_ids)} channels "
                  f"out of {len(db_channels)} ({len(removed_ids)/len(db_channels):.1%}). "
                  f"Aborting channel deactivation to prevent catastrophic catalog loss.")
            return

        for res_id in removed_ids:
            event = self._create_removed_event(res_id)
            self.publisher.publish([event], collection_name)
            print(f"[{collection_name}] Event persisted (Removed): ID {res_id}")

    def _sync_metadata_changes(self, current_channels, db_channels, collection_name: str):
        db_dict = {c.channel_id: c for c in db_channels}
        existing_ids = set(db_dict.keys())
        
        api_ids = {ch.channel_id for ch in current_channels}
        intersection = api_ids & existing_ids

        for channel in current_channels:
            if channel.channel_id in intersection:
                old_data = db_dict[channel.channel_id]
                changes = self._detect_diff(channel, old_data)

                if changes:
                    event = self._create_metadata_change_event(channel.channel_id, changes)
                    self.publisher.publish([event], collection_name)
                    print(f"[{collection_name}] Event persisted (Updated): {channel.title}")

    def _create_linked_event(self, channel):
        return {
            "metadata": self._build_metadata("youtube.channel.linked", channel.channel_id),
            "payload": asdict(channel) 
        }

    def _create_removed_event(self, resource_id):
        return {
            "metadata": self._build_metadata("youtube.channel.removed", resource_id),
            "payload": {"status": "unlinked", "reason": "Not found in YouTube API fetch"}
        }

    def _create_metadata_change_event(self, resource_id, changes):
        return {
            "metadata": self._build_metadata("youtube.channel.metadata_updated", resource_id),
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
        if new.title != old.title:
            diff["title"] = {"before": old.title, "after": new.title}
        if new.description != old.description:
            diff["description"] = {"before": old.description, "after": new.description}
        if new.country_code != old.country_code:
            diff["country_code"] = {"before": old.country_code, "after": new.country_code}
        
        new_monetization = new.extra_data.get("is_monetization_enabled") if new.extra_data else None
        old_monetization = old.extra_data.get("is_monetization_enabled") if old.extra_data else None
        
        if new_monetization != old_monetization:
            diff["is_monetization_enabled"] = {"before": old_monetization, "after": new_monetization}
            
        return diff