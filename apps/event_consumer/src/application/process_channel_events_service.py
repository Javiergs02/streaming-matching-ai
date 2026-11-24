from typing import List, Optional
from domain.ports import EventConsumerRepository, SQLStateRepository

class ProcessChannelEventsUseCase:
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
            channel_id = metadata.get("resource_id")

            if not channel_id:
                error_msg = f"Event {event_id} does not contain 'resource_id' in metadata."
                print(f"[Error] - {error_msg}")
                self.consumer_repo.mark_as_failed(collection_name, event_id, error_msg)
                continue

            if channel_id not in final_states:
                final_states[channel_id] = {
                    "type": event_type,
                    "payload": payload,
                    "event_ids": [event_id],
                }
            else:
                final_states[channel_id]["event_ids"].append(event_id)

                if event_type == "youtube.channel.removed":
                    final_states[channel_id]["type"] = "youtube.channel.removed"
                    final_states[channel_id]["payload"] = {}

                elif event_type in ["youtube.channel.linked", "youtube.channel.created"]:
                    final_states[channel_id]["type"] = "youtube.channel.linked"
                    final_states[channel_id]["payload"] = payload

                elif event_type == "youtube.channel.metadata_updated":
                    if final_states[channel_id]["type"] == "youtube.channel.removed":
                        continue

                    if final_states[channel_id]["type"] in ["youtube.channel.linked", "youtube.channel.created"]:
                        changes = payload.get("changes", {})
                        for k, v in changes.items():
                            final_states[channel_id]["payload"][k] = v.get("after")
                    else:
                        if "changes" not in final_states[channel_id]["payload"]:
                            final_states[channel_id]["payload"]["changes"] = {}
                        changes = payload.get("changes", {})
                        for k, v in changes.items():
                            final_states[channel_id]["payload"]["changes"][k] = v

        if not final_states:
            print(f"[{collection_name}] No events left to process.")
            return

        total_events = sum(len(s["event_ids"]) for s in final_states.values())
        print(f"Summary of channels: {total_events} events reduced to {len(final_states)} SQL queries.")

        events_to_mark = []
        processed_count = 0
        BATCH_SIZE = 200

        for c_id, state in final_states.items():
            try:
                if state["type"] == "youtube.channel.removed":
                    self._handle_channel_removed(c_id)
                elif state["type"] == "youtube.channel.metadata_updated":
                    self._handle_channel_metadata_updated(c_id, state["payload"])
                elif state["type"] in ["youtube.channel.linked", "youtube.channel.created"]:
                    self._handle_channel_linked(c_id, state["payload"])
                else:
                    print(f"[Ignored] Event ignored (Unmapped type): {state['type']}")

                events_to_mark.extend(state["event_ids"])

            except Exception as e:
                error_msg = f"Error processing final state of channel {c_id}: {str(e)}"
                print(f"[Error] - {error_msg}")
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

        print(f"[Success] - [{collection_name}] {processed_count} channel events processed and marked as completed.")

    def _handle_channel_removed(self, channel_id: str):
        query_sql = """
            UPDATE amuseplatforms_db.youtube_channels 
            SET is_active = false
            WHERE channel_id = :channel_id;
        """
        self.sql_repo.execute_update(query_sql, {"channel_id": channel_id})
        print(f"[Removed] Channel marked as inactive: {channel_id}")

    def _handle_channel_metadata_updated(self, channel_id: str, payload: dict):
        changes = payload.get("changes", {})
        if not changes:
            return

        updates = []
        params = {"channel_id": channel_id}

        if "title" in changes:
            updates.append("serie_name = :serie_name")
            params["serie_name"] = changes["title"].get("after")

        if "country_code" in changes:
            updates.append("country_code = :country_code")
            params["country_code"] = changes["country_code"].get("after")

        if "is_monetization_enabled" in changes:
            updates.append("is_monetization_enabled = :is_monetization_enabled")
            params["is_monetization_enabled"] = changes["is_monetization_enabled"].get("after")

        if updates:
            query_sql = f"""
                UPDATE amuseplatforms_db.youtube_channels 
                SET {', '.join(updates)}
                WHERE channel_id = :channel_id;
            """
            self.sql_repo.execute_update(query_sql, params)
            print(f"[Metadata Updated] Fields updated {list(changes.keys())} for: {channel_id}")

    def _handle_channel_linked(self, channel_id: str, payload: dict):
        query_sql = """
            INSERT INTO amuseplatforms_db.youtube_channels (
                channel_id, serie_name, is_monetization_enabled, language, linked_date, is_active, country_code
            ) 
            VALUES (
                :channel_id, :serie_name, :is_monetization_enabled, :language, :linked_date, true, :country_code
            )
            ON CONFLICT (channel_id) 
            DO UPDATE SET 
                serie_name = EXCLUDED.serie_name,
                is_monetization_enabled = EXCLUDED.is_monetization_enabled,
                language = EXCLUDED.language,
                country_code = EXCLUDED.country_code,
                is_active = true;
        """
        
        extra_data = payload.get("extra_data") or {}
        is_monetization = payload.get("is_monetization_enabled", extra_data.get("is_monetization_enabled", False))

        params = {
            "channel_id": channel_id,
            "serie_name": payload.get("title", "Sin Nombre"),
            "is_monetization_enabled": is_monetization,
            "language": payload.get("language"),
            "linked_date": payload.get("linked_date"),
            "country_code": payload.get("country_code")
        }
        
        self.sql_repo.execute_update(query_sql, params)
        print(f"[Linked] Channel impacted (UPSERT) in Postgres: {channel_id}")