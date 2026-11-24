from typing import List, Optional
from domain.ports import SQLStateRepository
from domain.ports import EventConsumerRepository

INTRO_EPISODE_NUMBERS = ("1111", "9999", "None")


class ProcessDiffusionEventsUseCase:
    def __init__(self, consumer_repo: EventConsumerRepository, sql_repo: SQLStateRepository):
        self.consumer_repo = consumer_repo
        self.sql_repo = sql_repo

    def execute(self, collection_name: str, event_types: Optional[List[str]] = None):

        print(f"[Info] - Preloading already-mapped videos from PostgreSQL...")
        mapped_rows = self.sql_repo.fetch_all(
            "SELECT video_id, episode_number, language_code, series_code "
            "FROM amuseplatforms_db.episode_youtube_video;"
        )
        self._mapped_videos = {
            row["video_id"]: (row["episode_number"], row["language_code"], row["series_code"])
            for row in mapped_rows
        }
        print(f"[Info] - {len(self._mapped_videos)} videos already mapped, preloaded for fast lookup.")

        cursor_events = self.consumer_repo.get_unprocessed_events(collection_name, event_types)

        events_to_mark = []
        processed_count = 0

        BATCH_SIZE = 200

        print(f"\n[Info] - [{collection_name}] Processing diffusion stream...")

        for event in cursor_events:
            event_id = event["_id"]
            metadata = event.get("metadata", {})
            payload = event.get("payload", {})
            event_type = metadata.get("event_type")
            diffusion_id = payload.get("diffusion_id")

            if not diffusion_id:
                print(f"[Warning] - Event {event_id} has no diffusion_id in payload. Discarding.")
                events_to_mark.append(event_id)
                continue

            try:
                if event_type == "diffusion.succeeded":
                    handled = self._handle_succeeded(payload, diffusion_id, collection_name, event_id)
                    if handled:
                        events_to_mark.append(event_id)

                elif event_type == "diffusion.failed":
                    self._handle_failed(payload, diffusion_id)
                    events_to_mark.append(event_id)
                    print(f"[Info] - Diffusion {diffusion_id} failed at source. "
                          f"Structure pre-created from its episode data; no mapping attempted.")

                else:
                    print(f"[Info] - Event {event_id} has unrecognized event_type "
                          f"'{event_type}'. Discarding.")
                    events_to_mark.append(event_id)

            except Exception as e:
                print(f"[Error] - Unexpected failure processing diffusion {diffusion_id}: {str(e)}")
                self.consumer_repo.mark_as_failed(collection_name, event_id, str(e))

            if len(events_to_mark) >= BATCH_SIZE:
                self.consumer_repo.mark_as_processed(collection_name, events_to_mark)
                processed_count += len(events_to_mark)
                print(f"[Progress] - {processed_count} events marked as processed so far...")
                events_to_mark = []

        if events_to_mark:
            self.consumer_repo.mark_as_processed(collection_name, events_to_mark)
            processed_count += len(events_to_mark)

        if processed_count == 0:
            print(f"[Info] - [{collection_name}] No events processed successfully in this batch.")
            return

        print(f"[Success] - [{collection_name}] {processed_count} diffusion events processed and marked as completed.")

    def _handle_succeeded(self, payload: dict, diffusion_id: str, collection_name: str, event_id: str) -> bool:
        """Devuelve True si el evento debe marcarse como procesado, False si debe reintentarse."""
        video_id = payload.get("platform_video_id")
        episodes = payload.get("episodes", [])

        if not video_id or not episodes:
            print(f"[Warning] - Missing video_id or episodes in succeeded event {diffusion_id}. Skipping.")
            return True

        if video_id in self._mapped_videos:
            existing_ep, existing_lang, existing_series = self._mapped_videos[video_id]

            claimed_ep = None
            for ep in episodes:
                ep_num_str = str(ep.get("episode_number", "")).strip()
                sea_num_str = str(ep.get("season_number", "")).strip()
                if sea_num_str == "None" or ep_num_str in INTRO_EPISODE_NUMBERS:
                    continue
                claimed_ep = ep
                break

            if claimed_ep is not None:
                claimed_ep_num = int(str(claimed_ep["episode_number"]).strip())
                claimed_lang = str(claimed_ep["language_code"]).strip()
                claimed_series = str(claimed_ep["series_code"]).strip()

                if (claimed_ep_num, claimed_lang, claimed_series) == (existing_ep, existing_lang, existing_series):
                    print(f"[Skip] - Video {video_id} already mapped to Episode "
                          f"{existing_ep} [{existing_series}, {existing_lang}]. No changes needed.")
                else:
                    print(f"[Warning] - Video {video_id} already mapped to Episode "
                          f"{existing_ep} [{existing_series}, {existing_lang}], but this diffusion "
                          f"claims Episode {claimed_ep_num} [{claimed_series}, {claimed_lang}]. "
                          f"Keeping the existing mapping. Review this discrepancy manually.")
            else:
                print(f"[Skip] - Video {video_id} already mapped to Episode "
                      f"{existing_ep} [{existing_series}, {existing_lang}]. No changes needed.")

            return True

        real_episodes = []
        had_structural_failures = False
        for ep in episodes:
            ep_num_str = str(ep.get("episode_number", "")).strip()
            sea_num_str = str(ep.get("season_number", "")).strip()

            if sea_num_str == "None" or ep_num_str in INTRO_EPISODE_NUMBERS:
                continue

            try:
                self._ensure_structural_integrity(ep)
                real_episodes.append(ep)
            except Exception as e:
                had_structural_failures = True
                print(f"[Error] - Structure failed for episode {ep_num_str} "
                      f"in diffusion {diffusion_id}: {str(e)}")

        if not real_episodes:
            if had_structural_failures:
                print(f"[Error] - Diffusion {diffusion_id} failed: all candidate episodes failed structural integrity.")
                return False
            print(f"[Info] - Diffusion {diffusion_id} contains only intros. No mapping needed.")
            return True

        first_real_ep = real_episodes[0]
        ep_data = {
            "episode_number": int(first_real_ep["episode_number"]),
            "language_code": str(first_real_ep["language_code"]).strip(),
            "series_code": str(first_real_ep["series_code"]).strip(),
        }

        try:
            self._insert_episode_video_mapping(video_id, ep_data)
            self._mapped_videos[video_id] = (
                ep_data["episode_number"], ep_data["language_code"], ep_data["series_code"]
            )
            return True
        except Exception as e:
            error_str = str(e).lower()

            if "fk_youtube_metadata" in error_str:
                print(f"[Warning] - Video {video_id} not yet synced into youtube_videos "
                      f"(sincronización estructural diaria pendiente). Mapping postponed.")
                return False

            if "fk_episode_parent" in error_str:
                print(f"[Error] - Episode for diffusion {diffusion_id} does not exist "
                      f"despite the structural step just having run. Investigate.")
                return False

            raise

    def _handle_failed(self, payload: dict, diffusion_id: str) -> None:
        episodes = payload.get("episodes", [])
        if not episodes:
            print(f"[Info] - Diffusion {diffusion_id} failed with no episode data attached. "
                  f"Nothing to pre-create.")
            return

        for ep in episodes:
            ep_num_str = str(ep.get("episode_number", "")).strip()
            sea_num_str = str(ep.get("season_number", "")).strip()

            if sea_num_str == "None" or ep_num_str in INTRO_EPISODE_NUMBERS:
                continue

            try:
                self._ensure_structural_integrity(ep)
            except Exception as e:
                print(f"[Error] - Could not pre-create structure for episode {ep_num_str} "
                      f"in failed diffusion {diffusion_id}: {str(e)}")

    def _ensure_structural_integrity(self, ep: dict):
        project_code = str(ep.get("project_code", "")).strip()
        project_name = str(ep.get("project_name", "")).strip() or f"Project {project_code}"

        series_code = str(ep.get("series_code", "")).strip()
        series_name = str(ep.get("series_name", "")).strip() or f"Series {series_code}"

        episode_number = int(str(ep.get("episode_number", "")).strip())
        language_code = str(ep.get("language_code", "")).strip()
        season = int(str(ep.get("season_number", "")).strip())

        episode_in_season_str = str(ep.get("episode_in_season", "")).strip()
        episode_in_season = int(episode_in_season_str) if episode_in_season_str.isdigit() else episode_number

        sql_project = """
            INSERT INTO amuseplatforms_db.projects (project_code, project_name)
            VALUES (:project_code, :project_name) 
            ON CONFLICT (project_code) DO NOTHING;
        """
        self.sql_repo.execute_update(sql_project, {
            "project_code": project_code,
            "project_name": project_name
        })

        sql_series = """
            INSERT INTO amuseplatforms_db.series (series_code, project_code, series_name)
            VALUES (:series_code, :project_code, :series_name) 
            ON CONFLICT (series_code) DO NOTHING;
        """
        self.sql_repo.execute_update(sql_series, {
            "series_code": series_code,
            "project_code": project_code,
            "series_name": series_name
        })

        sql_episode = """
            INSERT INTO amuseplatforms_db.episodes (
                episode_number, language_code, series_code, season, episode_in_season, title
            ) VALUES (
                :episode_number, :language_code, :series_code, :season, :episode_in_season, :title
            ) 
            ON CONFLICT (episode_number, language_code, series_code) DO NOTHING;
        """
        self.sql_repo.execute_update(sql_episode, {
            "episode_number": episode_number,
            "language_code": language_code,
            "series_code": series_code,
            "season": season,
            "episode_in_season": episode_in_season,
            "title": f"Episode {episode_number} ({language_code})"
        })

    def _insert_episode_video_mapping(self, video_id: str, ep_data: dict):
        sql_mapping = """
            INSERT INTO amuseplatforms_db.episode_youtube_video (
                video_id, episode_number, language_code, series_code
            ) VALUES (
                :video_id, :episode_number, :language_code, :series_code
            ) 
            ON CONFLICT (video_id) DO NOTHING;
        """
        params = {
            "video_id": video_id,
            "episode_number": ep_data["episode_number"],
            "language_code": ep_data["language_code"],
            "series_code": ep_data["series_code"]
        }
        self.sql_repo.execute_update(sql_mapping, params)
        print(f"[Success] - Mapped: Video {video_id} -> Episode "
              f"{ep_data['episode_number']} [{ep_data['series_code']}, {ep_data['language_code']}]")