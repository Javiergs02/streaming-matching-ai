import json
from typing import List, Optional
from domain.ports import EventConsumerRepository, SQLStateRepository

class ProcessVideoEventsUseCase:
    def __init__(self, consumer_repo: EventConsumerRepository, sql_repo: SQLStateRepository):
        self.consumer_repo = consumer_repo
        self.sql_repo = sql_repo

    def execute(self, collection_name: str, event_types: Optional[List[str]] = None):
        cursor_events = self.consumer_repo.get_unprocessed_events(collection_name, event_types)

        final_states = {}

        print(f"\n[{collection_name}] Reading and compacting the complete event stream...")

        for event in cursor_events:
            event_id = event["_id"]
            metadata = event.get("metadata", {})
            payload = event.get("payload", {})

            event_type = metadata.get("event_type")
            video_id = metadata.get("resource_id")

            if not video_id:
                self.consumer_repo.mark_as_failed(collection_name, event_id, "Missing resource_id")
                continue

            if video_id not in final_states:
                final_states[video_id] = {
                    "type": event_type,
                    "payload": payload,
                    "is_dead": False,
                    "event_ids": [],
                }

            final_states[video_id]["event_ids"].append(event_id)

            if event_type == "youtube.video.removed":
                final_states[video_id]["is_dead"] = True
                final_states[video_id]["type"] = "youtube.video.removed"
                
            elif event_type in ["youtube.video.linked", "youtube.video.created"]:
                final_states[video_id]["type"] = "youtube.video.linked"
                final_states[video_id]["payload"] = payload
                final_states[video_id]["is_dead"] = False
                
            elif event_type == "youtube.video.metadata_updated":
                if final_states[video_id]["is_dead"]:
                    continue
                
                if final_states[video_id]["type"] in ["youtube.video.linked", "youtube.video.created"]:
                    changes = payload.get("changes", {})
                    for k, v in changes.items():
                        final_states[video_id]["payload"][k] = v.get("after")
                else:
                    if "changes" not in final_states[video_id]["payload"]:
                        final_states[video_id]["payload"]["changes"] = {}
                    changes = payload.get("changes", {})
                    for k, v in changes.items():
                        final_states[video_id]["payload"]["changes"][k] = v

        if not final_states:
            print(f"[{collection_name}] No events left to process. Exiting.")
            return

        total_events = sum(len(s["event_ids"]) for s in final_states.values())
        print(f"Summary of videos: {total_events} events reduced to {len(final_states)} unique SQL operations.")

        events_to_mark = []
        processed_count = 0
        BATCH_SIZE = 200

        for v_id, state in final_states.items():
            try:
                if state["is_dead"]:
                    if state["type"] == "youtube.video.linked":
                        self._handle_video_linked(v_id, state["payload"], is_active=False)
                    else:
                        self._handle_video_removed(v_id)
                elif state["type"] == "youtube.video.metadata_updated":
                    self._handle_video_metadata_updated(v_id, state["payload"])
                elif state["type"] in ["youtube.video.linked", "youtube.video.created"]:
                    self._handle_video_linked(v_id, state["payload"], is_active=True)

                events_to_mark.extend(state["event_ids"])

            except Exception as e:
                error_msg = f"Video {v_id}: {str(e)}"
                print(f"[Error SQL] - {error_msg}")
                for failed_event_id in state["event_ids"]:
                    self.consumer_repo.mark_as_failed(collection_name, failed_event_id, error_msg)

            if len(events_to_mark) >= BATCH_SIZE:
                self.consumer_repo.mark_as_processed(collection_name, events_to_mark)
                processed_count += len(events_to_mark)
                print(f"[Progress] - {processed_count} events marked as processed so far...")
                events_to_mark = []

        if events_to_mark:
            self.consumer_repo.mark_as_processed(collection_name, events_to_mark)
            processed_count += len(events_to_mark)

        if processed_count == 0:
            print(f"[{collection_name}] No events could be marked as processed this run.")
            return

        print(f"[Success] - [{collection_name}] {processed_count} video events processed and marked as completed.")

    def _handle_video_removed(self, video_id: str):
        query_sql = "UPDATE amuseplatforms_db.youtube_videos SET is_active = false WHERE video_id = :video_id;"
        self.sql_repo.execute_update(query_sql, {"video_id": video_id})
        print(f"[Video Removed] is_active = FALSE for video: {video_id}")

    def _handle_video_metadata_updated(self, video_id: str, payload: dict):
        changes = payload.get("changes", {})
        if not changes: return
        updates = []
        params = {"video_id": video_id}
        for field in ["title", "description", "privacy_status", "category_id"]:
            if field in changes:
                column_name = "title" if field == "title" else field
                updates.append(f"{column_name} = :{field}")
                params[field] = changes[field].get("after")
        if updates:
            query_sql = f"UPDATE amuseplatforms_db.youtube_videos SET {', '.join(updates)} WHERE video_id = :video_id;"
            self.sql_repo.execute_update(query_sql, params)
            print(f"[Video Metadata Updated] Fields updated {list(changes.keys())} for: {video_id}")

    def _handle_video_linked(self, video_id: str, payload: dict, is_active: bool = True):
        query_sql = """
            INSERT INTO amuseplatforms_db.youtube_videos (
                video_id, channel_id, title, description, published_at, 
                duration, is_short, privacy_status, category_id, tags, default_audio_language, is_active
            ) VALUES (
                :video_id, :channel_id, :title, :description, :published_at, 
                :duration, :is_short, :privacy_status, :category_id, :tags, :default_audio_language, :is_active
            )
            ON CONFLICT (video_id) DO UPDATE SET 
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                privacy_status = EXCLUDED.privacy_status,
                category_id = EXCLUDED.category_id,
                tags = EXCLUDED.tags,
                is_short = EXCLUDED.is_short,
                default_audio_language = EXCLUDED.default_audio_language,
                is_active = :is_active;
        """
        raw_tags = payload.get("tags")
        params = {
            "video_id": video_id,
            "channel_id": payload.get("channel_id"),
            "title": payload.get("title", "Sin Título"),
            "description": payload.get("description"),
            "published_at": payload.get("published_at"),
            "duration": payload.get("duration"),
            "is_short": payload.get("is_short", False),
            "privacy_status": payload.get("privacy_status", "public"),
            "category_id": payload.get("category_id"),
            "tags": json.dumps(raw_tags) if isinstance(raw_tags, (list, dict)) else raw_tags,
            "default_audio_language": payload.get("default_audio_language"),
            "is_active": is_active
        }
        self.sql_repo.execute_update(query_sql, params)
        print(f"[Video Linked] Video registered (UPSERT, is_active={is_active}) in Postgres: {video_id}")