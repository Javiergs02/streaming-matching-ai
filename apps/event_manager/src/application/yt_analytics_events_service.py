import uuid
from datetime import datetime, timedelta, timezone, date
from dataclasses import asdict
from typing import Set, Tuple, List
from domain.ports import VideoFetcher, VideoRepository, EventRepository

class YtAnalyticsEventsService:
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

    @staticmethod
    def resolve_target_end_date(
        by_country: bool,
        end_date_override: str = None,
        today_utc: date = None,
    ) -> date:
        """Resolves the safe inclusive upper date bound for YouTube analytics sync.

        In monthly territorial mode (`by_country=True`), never spills into the current
        unclosed calendar month, because partial day-1 events would advance `last_date`
        to `YYYY-MM-01` and cause the rest of the month to be skipped on subsequent runs.
        """
        ref_today = today_utc or datetime.now(timezone.utc).date()
        max_allowed_end = (
            ref_today.replace(day=1) - timedelta(days=1)
            if by_country
            else ref_today - timedelta(days=1)
        )
        if end_date_override:
            override_end = datetime.strptime(end_date_override, "%Y-%m-%d").date()
            return min(override_end, max_allowed_end)
        return max_allowed_end

    def execute(self, channel_id: str, mongo_collection: str, by_country: bool = False, 
                start_date_override: str = None, end_date_override: str = None) -> None:
        videos = self.repository.get_all_by_channel(channel_id)
        if not videos:
            print(f"   -> No videos found for channel {channel_id}.")
            return
        
        print(f"   -> Analyzing the state of {len(videos)} videos in the database...")

        override_date = datetime.strptime(start_date_override, "%Y-%m-%d").date() if start_date_override else None
        target_end_date = self.resolve_target_end_date(
            by_country=by_country,
            end_date_override=end_date_override,
        )

        if override_date and override_date > target_end_date:
            print(f"   -> Configured start date ({override_date}) is after target end date ({target_end_date}). No sync needed.")
            return

        video_ids = [v.video_id for v in videos]
        last_dates_dict = self.publisher.get_last_stats_date(
            video_ids, 
            mongo_collection, 
            by_country=by_country, 
            max_date=target_end_date,
            only_monetized=True
        )
        
        videos_to_sync = []
        for video in videos:
            pub_date = None
            if video.published_at:
                pub_str = video.published_at.replace('Z', '+00:00')
                pub_date = datetime.fromisoformat(pub_str).date()

            # If video was published strictly after target_end_date, it did not exist in this timeframe
            if pub_date and pub_date > target_end_date:
                continue

            last_date = last_dates_dict.get(video.video_id)
            
            if last_date:
                if by_country:
                    # In monthly territory mode, last_date is YYYY-MM-01 representing the entire month.
                    # Advance to the 1st of the next month.
                    next_year = last_date.year + (1 if last_date.month == 12 else 0)
                    next_month = 1 if last_date.month == 12 else last_date.month + 1
                    start_date = date(next_year, next_month, 1)
                else:
                    start_date = last_date + timedelta(days=1)
            else:
                if not pub_date:
                    if override_date:
                        start_date = override_date
                    else:
                        continue
                else:
                    start_date = max(pub_date, override_date) if override_date else pub_date

            if override_date and start_date < override_date:
                start_date = override_date

            if start_date <= target_end_date:
                videos_to_sync.append((video.video_id, start_date))

        if not videos_to_sync:
            print("   -> All videos are up to date for this timeframe. No new analytics to fetch.")
            return

        print(f"   -> Found {len(videos_to_sync)} videos that need analytics updates.")

        end_date_str = target_end_date.strftime('%Y-%m-%d')
        total_events = 0

        batches = self._build_video_batches(videos_to_sync, target_end_date)

        for batch_slice in batches:
            batch_video_ids = [v[0] for v in batch_slice]
            
            oldest_start_date = min(v[1] for v in batch_slice)
            start_date_str = oldest_start_date.strftime('%Y-%m-%d')

            sync_mode = "Monthly Territories" if by_country else "Daily Global"
            print(f"   -> Fetching {sync_mode} data from YouTube: Batch of {len(batch_video_ids)} videos (From {start_date_str} to {end_date_str})...")
            
            try:
                if by_country:
                    performance_events = self.fetcher.fetch_monthly_analysis_by_country(
                        video_ids=batch_video_ids,
                        start_date=start_date_str,
                        end_date=end_date_str
                    )
                else:
                    performance_events = self.fetcher.fetch_historical_analysis(
                        video_ids=batch_video_ids,
                        start_date=start_date_str,
                        end_date=end_date_str,
                        by_country=False
                    )

                if not performance_events:
                    print(f"   ℹ️ YouTube respondió 0 filas (sin actividad/reproducciones para este lote de {len(batch_video_ids)} vídeos entre {start_date_str} y {end_date_str}).")
                    continue
                
                unique_dates_in_batch = list({
                    e.date.strftime("%Y-%m-%d") if hasattr(e.date, "strftime") else str(e.date)
                    for e in performance_events
                })

                existing_records: Set[Tuple] = self.publisher.get_existing_combinations(
                    platform="youtube", 
                    dates=unique_dates_in_batch,
                    collection_name=mongo_collection,
                    video_ids=batch_video_ids,
                    exclude_zero_revenue=True,
                    by_country=by_country
                )

                new_events_to_publish: List[dict] = []
                ignored_count = 0

                for event_domain_model in performance_events:
                    event_date_str = event_domain_model.date.strftime("%Y-%m-%d") if hasattr(event_domain_model.date, "strftime") else str(event_domain_model.date)
                    event_video_id_str = str(event_domain_model.video_id)
                    event_geo_str = str(getattr(event_domain_model, 'geography', 'Global'))

                    is_duplicate = (
                        (event_video_id_str, event_date_str, event_geo_str) in existing_records
                        if event_geo_str not in ("Global", "Unknown Geo")
                        else (event_video_id_str, event_date_str) in existing_records
                    )

                    if is_duplicate:
                        ignored_count += 1
                    else:
                        event_payload = self._create_analytics_event(event_domain_model)
                        new_events_to_publish.append(event_payload)

                print(f"   -> Batch Results: Parsed={len(performance_events)} | Already in DB={ignored_count} | New to upload={len(new_events_to_publish)}")

                if new_events_to_publish:
                    self.publisher.publish(new_events_to_publish, mongo_collection)
                    total_events += len(new_events_to_publish)
                    print(f"   -> Successfully saved {len(new_events_to_publish)} events.")
                else:
                    print("   -> All events in this batch already existed in MongoDB. Database untouched.")
                    
            except Exception as e:
                print(f"   -> Error orchestrating batch starting {start_date_str}: {e}")
                continue

        if hasattr(self.fetcher, 'failed_queries') and self.fetcher.failed_queries:
            print(f"\n   ⚠️ [ADVERTENCIA] Se registraron {len(self.fetcher.failed_queries)} peticiones con error persistente de YouTube en este canal:")
            for fq in self.fetcher.failed_queries:
                print(f"      - Periodo [{fq.get('start_date')} a {fq.get('end_date')}], Vídeos ({len(fq.get('video_ids', []))}): {fq.get('video_ids')}")
                print(f"        Detalle del error: {fq.get('error')}")

        print(f"   -> Synchronization completed. Total new events published to Mongo: {total_events}")

    @staticmethod
    def _build_video_batches(videos_to_sync: List[Tuple[str, date]], reference_date: date = None, yesterday: date = None) -> List[List[Tuple[str, date]]]:
        """
        Groups videos into date-coherent batches to eliminate 'batch date skew'.
        Recent videos (within 60 days of reference_date) are queried together in batches of up to 500.
        Historical videos needing backfill (> 60 days before reference_date) are isolated and grouped in small batches
        of 50, preventing a single old video from forcing multi-year downloads for hundreds of up-to-date videos.
        """
        ref = reference_date or yesterday or datetime.now(timezone.utc).date()
        recent_threshold = ref - timedelta(days=60)
        
        recent_videos = [v for v in videos_to_sync if v[1] >= recent_threshold]
        historical_videos = [v for v in videos_to_sync if v[1] < recent_threshold]
        
        batches: List[List[Tuple[str, date]]] = []
        
        # 1. Recent videos: safe to batch up to 500 since window is <= 14 days
        BATCH_SIZE_RECENT = 500
        for i in range(0, len(recent_videos), BATCH_SIZE_RECENT):
            batches.append(recent_videos[i:i + BATCH_SIZE_RECENT])
            
        # 2. Historical videos: sort by start date and chunk into smaller batches of 50
        if historical_videos:
            historical_videos.sort(key=lambda x: x[1])
            BATCH_SIZE_HISTORICAL = 50
            for i in range(0, len(historical_videos), BATCH_SIZE_HISTORICAL):
                batches.append(historical_videos[i:i + BATCH_SIZE_HISTORICAL])
                
        return batches

    def _create_analytics_event(self, event_model) -> dict:
        return {
            "metadata": self._build_metadata("youtube.video.performance_recorded", event_model.video_id),
            "payload": asdict(event_model) 
        }

    def _build_metadata(self, event_type: str, resource_id: str) -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "resource_id": resource_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "cms_id": self.cms_id
        }