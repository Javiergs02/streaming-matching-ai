import calendar
import time
import random
from collections import defaultdict
from datetime import date, datetime
from googleapiclient.errors import HttpError
from domain.ports import VideoFetcher
from domain.models import Video, VideoPerformanceEvent

class YoutubeVideoFetcher(VideoFetcher):
    def __init__(self, youtube_data_client, youtube_analytics_client, cms_id: str):
        self.data_client = youtube_data_client
        self.analytics_client = youtube_analytics_client
        self.cms_id = cms_id.strip()
        self.failed_queries: list[dict] = []
        self._monthly_cpm_cache: dict[str, tuple[dict[str, float], float]] = {}

    def fetch_all_by_channel(self, channel_id: str) -> list[Video]:
        uploads_playlist_id = self._get_uploads_playlist_id(channel_id)
        if not uploads_playlist_id:
            return []

        video_ids = self._get_all_video_ids(uploads_playlist_id)
        return self._get_enriched_videos(video_ids, channel_id)

    def _get_uploads_playlist_id(self, channel_id: str) -> str:
        try:
            res = self.data_client.channels().list(
                part="contentDetails",
                id=channel_id,
                onBehalfOfContentOwner=self.cms_id
            ).execute()
            items = res.get('items', [])
            return items[0]['contentDetails']['relatedPlaylists']['uploads'] if items else ""
        except Exception as e:
            print(f"[ERROR] Failed to get uploads playlist for channel {channel_id}: {e}")
            raise

    def _get_all_video_ids(self, playlist_id: str) -> list[str]:
        if not playlist_id:
            return []
        video_ids = []
        next_page_token = None
        while True:
            res = self.data_client.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token,
                onBehalfOfContentOwner=self.cms_id
            ).execute()
            for item in res.get('items', []):
                vid = item.get('contentDetails', {}).get('videoId')
                if vid:
                    video_ids.append(vid)
            next_page_token = res.get('nextPageToken')
            if not next_page_token: break
        return video_ids

    def _get_enriched_videos(self, video_ids: list[str], channel_id: str) -> list[Video]:
        videos = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            res = self.data_client.videos().list(
                part="snippet,contentDetails,status",
                id=",".join(batch),
                onBehalfOfContentOwner=self.cms_id
            ).execute()
            
            for item in res.get('items', []):
                snippet = item.get('snippet', {})
                content_details = item.get('contentDetails', {})
                status = item.get('status', {})
                
                youtube_video_extras = {
                    "description": snippet.get('description', ''),
                    "duration": content_details.get('duration', ''),
                    "privacy_status": status.get('privacyStatus', ''),
                    "category_id": snippet.get('categoryId', ''),
                    "tags": snippet.get('tags', []),
                    "default_audio_language": snippet.get('defaultAudioLanguage', None),
                    "raw_metadata": item
                }
                
                videos.append(Video(
                    video_id=item['id'],
                    channel_id=channel_id,
                    platform="youtube",
                    title=snippet.get('title', ''),
                    published_at=snippet.get('publishedAt'),
                    extra_data=youtube_video_extras
                ))
        return videos
    
    @staticmethod
    def _get_monthly_intervals(start_date_str: str, end_date_str: str) -> list[tuple[str, str, str]]:
        """
        Calculates all monthly windows between start_date and end_date.
        Returns tuples: (event_date, period_start, period_end)
        where event_date is formatted as 'YYYY-MM-01'.
        """
        s_date = datetime.strptime(start_date_str[:10], "%Y-%m-%d").date()
        e_date = datetime.strptime(end_date_str[:10], "%Y-%m-%d").date()

        intervals = []
        cur_year = s_date.year
        cur_month = s_date.month

        while (cur_year < e_date.year) or (cur_year == e_date.year and cur_month <= e_date.month):
            last_day = calendar.monthrange(cur_year, cur_month)[1]
            m_first = date(cur_year, cur_month, 1)
            m_last = date(cur_year, cur_month, last_day)

            p_start = max(s_date, m_first)
            p_end = min(e_date, m_last)

            event_date = f"{cur_year:04d}-{cur_month:02d}-01"
            intervals.append((event_date, p_start.strftime("%Y-%m-%d"), p_end.strftime("%Y-%m-%d")))

            cur_month += 1
            if cur_month > 12:
                cur_month = 1
                cur_year += 1

        return intervals

    def _query_reports_with_retry_and_split(
        self,
        start_date: str,
        end_date: str,
        metrics: str,
        dimensions: str,
        video_batch: list[str],
        max_retries: int = 3,
        base_delay: float = 1.0
    ) -> list[dict]:
        """
        Executes a YouTube Analytics query with exponential backoff retry for transient errors (500, 502, 503, 504, 429).
        If an HTTP 500/503/backendError persists on a batch of multiple videos, recursively splits the batch in half
        to prevent overwhelming YouTube Analytics API calculation limits with high-dimensional data (e.g. video,country).
        """
        if not video_batch:
            return []

        attempt = 0
        last_exception = None

        while attempt < max_retries:
            attempt += 1
            try:
                res = self.analytics_client.reports().query(
                    ids=f'contentOwner=={self.cms_id}',
                    startDate=start_date,
                    endDate=end_date,
                    metrics=metrics,
                    dimensions=dimensions,
                    filters=f'video=={",".join(video_batch)}'
                ).execute()

                column_headers = [h['name'] for h in res.get('columnHeaders', [])]
                rows = res.get('rows', []) or []
                return [dict(zip(column_headers, row)) for row in rows]

            except HttpError as e:
                last_exception = e
                status_code = getattr(e.resp, 'status', None) or getattr(e, 'status_code', None)
                is_server_error = status_code in (500, 502, 503, 504) or "backendError" in str(e)
                is_rate_limit = status_code == 429 or "rateLimitExceeded" in str(e) or "userRateLimitExceeded" in str(e)

                if (is_server_error or is_rate_limit) and attempt < max_retries:
                    sleep_time = (base_delay * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    print(f"   ⚠️ API query returned HTTP {status_code} [{start_date} to {end_date}] for {len(video_batch)} videos. Retrying ({attempt}/{max_retries}) in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    continue
                else:
                    break

            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    sleep_time = (base_delay * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    print(f"   ⚠️ API/network query error [{start_date} to {end_date}] for {len(video_batch)} videos ({e}). Retrying ({attempt}/{max_retries}) in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    continue
                else:
                    break

        # If retries exhausted and batch has more than 1 video, split it in half
        if len(video_batch) > 1:
            mid = len(video_batch) // 2
            batch_a = video_batch[:mid]
            batch_b = video_batch[mid:]
            print(f"   🔀 Batch of {len(video_batch)} videos failed ({last_exception}). Splitting into 2 sub-batches ({len(batch_a)} and {len(batch_b)} videos) to reduce API calculation load...")
            rows_a = self._query_reports_with_retry_and_split(
                start_date, end_date, metrics, dimensions, batch_a, max_retries=max_retries, base_delay=base_delay
            )
            rows_b = self._query_reports_with_retry_and_split(
                start_date, end_date, metrics, dimensions, batch_b, max_retries=max_retries, base_delay=base_delay
            )
            return rows_a + rows_b

        # If a single video failed after all retries and cannot be split further
        print(f"   ❌ [CRITICAL] Failed to fetch analytics for video {video_batch[0]} [{start_date} to {end_date}] after {max_retries} retries: {last_exception}")
        self.failed_queries.append({
            "video_ids": video_batch,
            "start_date": start_date,
            "end_date": end_date,
            "error": str(last_exception)
        })
        return []

    def fetch_monthly_country_cpm_profile(self, start_date: str, end_date: str) -> tuple[dict[str, float], float]:
        """
        Fetches the official country-level CPM profile from YouTube Analytics for the Content Owner.
        Requires only 1 query per month for all channels combined.
        Returns a tuple of (cpm_by_country_dict, default_fallback_cpm).
        """
        cache_key = f"{start_date[:7]}"
        if hasattr(self, '_monthly_cpm_cache') and cache_key in self._monthly_cpm_cache:
            return self._monthly_cpm_cache[cache_key]

        cpm_dict = {}
        default_cpm = 2.0

        # Standard market CPM benchmarks as base fallback for unmonetized/small territories
        tier_benchmarks = {
            "US": 18.0, "CA": 14.0, "GB": 15.0, "AU": 16.0, "DE": 14.0, "CH": 19.0, "AT": 13.0,
            "FR": 8.5, "ES": 6.5, "IT": 6.0, "NL": 12.0, "BE": 10.0, "SE": 13.0, "NO": 15.0,
            "DK": 14.0, "FI": 12.0, "IE": 12.0, "NZ": 13.0, "JP": 9.0, "KR": 8.0,
            "MX": 2.2, "BR": 1.8, "AR": 1.5, "CL": 2.5, "CO": 1.6, "PE": 1.4,
            "PL": 4.5, "CZ": 4.0, "RO": 2.5, "TR": 1.2, "RU": 1.5,
            "IN": 0.9, "PH": 1.0, "ID": 0.9, "VN": 0.8, "TH": 1.5, "MY": 2.2,
            "ZA": 2.5, "EG": 0.8, "SA": 6.0, "AE": 8.0
        }

        try:
            res = self.analytics_client.reports().query(
                ids=f'contentOwner=={self.cms_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedRevenue,cpm',
                dimensions='country'
            ).execute()

            column_headers = [h['name'] for h in res.get('columnHeaders', [])]
            rows = res.get('rows', []) or []
            valid_cpms = []

            for row in rows:
                data = dict(zip(column_headers, row))
                country = str(data.get('country', '')).strip().upper()
                if not country or country in ('ZZ', 'UNKNOWN GEO'):
                    continue
                cpm = float(data.get('cpm', 0.0) or 0.0)
                views = int(data.get('views', 0) or 0)
                rev = float(data.get('estimatedRevenue', 0.0) or 0.0)

                if cpm <= 0.0 and views > 0 and rev > 0.0:
                    cpm = (rev / views) * 1000.0

                if cpm > 0.0:
                    cpm_dict[country] = round(cpm, 2)
                    valid_cpms.append(cpm)

            if valid_cpms:
                valid_cpms.sort()
                default_cpm = round(valid_cpms[len(valid_cpms) // 2], 2)
            else:
                default_cpm = 2.0

        except Exception as e:
            print(f"   ℹ️ Notice: Country CPM profile query for [{start_date} to {end_date}] ({e}). Using benchmark profile.")
            default_cpm = 2.0

        # Fill any missing countries from standard market benchmarks
        for c, b_cpm in tier_benchmarks.items():
            if c not in cpm_dict:
                cpm_dict[c] = b_cpm

        if not hasattr(self, '_monthly_cpm_cache'):
            self._monthly_cpm_cache = {}
        self._monthly_cpm_cache[cache_key] = (cpm_dict, default_cpm)
        return cpm_dict, default_cpm

    def fetch_monthly_analysis_by_country(self, video_ids: list[str], start_date: str, end_date: str) -> list[VideoPerformanceEvent]:
        """
        Fetches YouTube Analytics metrics aggregated monthly by video and viewer country.
        Uses dimensions='video,country' for views/minutes, and weights video global revenue
        by the country's real CPM profile to accurately allocate revenue and impressions.
        """
        all_performance_events = []
        BATCH_SIZE = 50
        intervals = self._get_monthly_intervals(start_date, end_date)

        for event_date, p_start, p_end in intervals:
            cpm_profile, default_cpm = self.fetch_monthly_country_cpm_profile(p_start, p_end)

            for i in range(0, len(video_ids), BATCH_SIZE):
                batch = video_ids[i:i + BATCH_SIZE]

                # 1. Fetch global financial metrics per video for this month
                global_rows = self._query_reports_with_retry_and_split(
                    start_date=p_start,
                    end_date=p_end,
                    metrics='views,estimatedRevenue,estimatedAdRevenue,adImpressions',
                    dimensions='video',
                    video_batch=batch
                )
                global_map = {r.get('video'): r for r in global_rows if r.get('video')}

                # 2. Fetch country breakdown for videos in this batch
                rows_data = self._query_reports_with_retry_and_split(
                    start_date=p_start,
                    end_date=p_end,
                    metrics='views,likes,comments,estimatedMinutesWatched,estimatedRevenue,estimatedAdRevenue,cpm,adImpressions',
                    dimensions='video,country',
                    video_batch=batch
                )

                # Group country rows by video
                video_country_rows = defaultdict(list)
                for r in rows_data:
                    vid = r.get('video')
                    if vid:
                        video_country_rows[vid].append(r)

                for vid, c_rows in video_country_rows.items():
                    has_direct_revenue = any(float(r.get('estimatedRevenue', 0.0) or 0.0) > 0.0 for r in c_rows)

                    if has_direct_revenue:
                        # Direct revenue already present in country rows (e.g. from tests or full reporting)
                        for r in c_rows:
                            country_code = str(r.get('country', 'Unknown Geo')).strip().upper()
                            if not country_code:
                                country_code = 'Unknown Geo'

                            alloc_rev = float(r.get('estimatedRevenue', 0.0) or 0.0)
                            alloc_ad_rev = float(r.get('estimatedAdRevenue', 0.0) or 0.0)
                            alloc_ad_imp = int(r.get('adImpressions', 0) or 0)
                            country_cpm = float(r.get('cpm', 0.0) or 0.0) or round(cpm_profile.get(country_code, default_cpm), 2)

                            all_performance_events.append(VideoPerformanceEvent(
                                video_id=vid,
                                platform="youtube",
                                date=event_date,
                                estimated_revenue=alloc_rev,
                                geography=country_code,
                                extra_metrics={
                                    "views": int(r.get('views', 0) or 0),
                                    "likes": int(r.get('likes', 0) or 0),
                                    "comments": int(r.get('comments', 0) or 0),
                                    "estimated_minutes_watched": int(r.get('estimatedMinutesWatched', 0) or 0),
                                    "estimated_ad_revenue": alloc_ad_rev,
                                    "cpm": country_cpm,
                                    "ad_impressions": alloc_ad_imp
                                }
                            ))
                        continue

                    # If no direct revenue in country rows, weight global metrics by country CPM profile
                    g_info = global_map.get(vid, {})
                    if g_info:
                        g_rev = float(g_info.get('estimatedRevenue', 0.0) or 0.0)
                        g_ad_rev = float(g_info.get('estimatedAdRevenue', 0.0) or 0.0)
                        g_ad_imp = int(g_info.get('adImpressions', 0) or 0)
                    else:
                        g_rev = sum(float(r.get('estimatedRevenue', 0.0) or 0.0) for r in c_rows)
                        g_ad_rev = sum(float(r.get('estimatedAdRevenue', 0.0) or 0.0) for r in c_rows)
                        g_ad_imp = sum(int(r.get('adImpressions', 0) or 0) for r in c_rows)

                    # Calculate economic weights = Views * Country CPM
                    weights = {}
                    for r in c_rows:
                        country_code = str(r.get('country', 'Unknown Geo')).strip().upper()
                        if not country_code:
                            country_code = 'Unknown Geo'
                        v_views = int(r.get('views', 0) or 0)
                        cpm_val = cpm_profile.get(country_code, default_cpm)
                        if cpm_val <= 0:
                            cpm_val = default_cpm
                        weights[country_code] = v_views * cpm_val

                    total_weight = sum(weights.values())
                    total_vid_views = sum(int(r.get('views', 0) or 0) for r in c_rows)

                    allocated_events = []
                    running_rev = 0.0
                    running_ad_rev = 0.0
                    running_ad_imp = 0

                    for r in c_rows:
                        country_code = str(r.get('country', 'Unknown Geo')).strip().upper()
                        if not country_code:
                            country_code = 'Unknown Geo'

                        v_views = int(r.get('views', 0) or 0)
                        v_likes = int(r.get('likes', 0) or 0)
                        v_comments = int(r.get('comments', 0) or 0)
                        v_minutes = int(r.get('estimatedMinutesWatched', 0) or 0)

                        if total_weight > 0:
                            ratio = weights[country_code] / total_weight
                        elif total_vid_views > 0:
                            ratio = v_views / total_vid_views
                        else:
                            ratio = 0.0

                        alloc_rev = round(g_rev * ratio, 4)
                        alloc_ad_rev = round(g_ad_rev * ratio, 4)
                        alloc_ad_imp = int(round(g_ad_imp * ratio))

                        # Effective CPM for this country
                        if alloc_ad_imp > 0 and alloc_ad_rev > 0:
                            country_cpm = round((alloc_ad_rev / alloc_ad_imp) * 1000.0, 2)
                        else:
                            country_cpm = round(cpm_profile.get(country_code, default_cpm), 2)

                        running_rev += alloc_rev
                        running_ad_rev += alloc_ad_rev
                        running_ad_imp += alloc_ad_imp

                        allocated_events.append(VideoPerformanceEvent(
                            video_id=vid,
                            platform="youtube",
                            date=event_date,
                            estimated_revenue=alloc_rev,
                            geography=country_code,
                            extra_metrics={
                                "views": v_views,
                                "likes": v_likes,
                                "comments": v_comments,
                                "estimated_minutes_watched": v_minutes,
                                "estimated_ad_revenue": alloc_ad_rev,
                                "cpm": country_cpm,
                                "ad_impressions": alloc_ad_imp
                            }
                        ))

                    # Exact cent conservation check
                    if allocated_events and g_rev > 0:
                        rev_diff = round(g_rev - running_rev, 4)
                        if abs(rev_diff) > 0.0:
                            top_ev = max(allocated_events, key=lambda e: e.extra_metrics.get("views", 0))
                            object.__setattr__(top_ev, 'estimated_revenue', round(top_ev.estimated_revenue + rev_diff, 4))

                    if allocated_events and g_ad_imp > 0:
                        imp_diff = g_ad_imp - running_ad_imp
                        if imp_diff != 0:
                            top_ev = max(allocated_events, key=lambda e: e.extra_metrics.get("views", 0))
                            top_ev.extra_metrics["ad_impressions"] += imp_diff

                    all_performance_events.extend(allocated_events)

        return all_performance_events

    def fetch_historical_analysis(self, video_ids: list[str], start_date: str, end_date: str, by_country: bool = False) -> list[VideoPerformanceEvent]:
        if by_country:
            return self.fetch_monthly_analysis_by_country(video_ids, start_date, end_date)

        all_performance_events = []
        BATCH_SIZE = 100

        for i in range(0, len(video_ids), BATCH_SIZE):
            batch = video_ids[i:i + BATCH_SIZE]
            rows_data = self._query_reports_with_retry_and_split(
                start_date=start_date,
                end_date=end_date,
                metrics='views,likes,comments,estimatedMinutesWatched,estimatedRevenue,estimatedAdRevenue,cpm,adImpressions',
                dimensions='day,video',
                video_batch=batch
            )

            for data in rows_data:
                youtube_metrics_extras = {
                    "views": int(data.get('views', 0) or 0),
                    "likes": int(data.get('likes', 0) or 0),
                    "comments": int(data.get('comments', 0) or 0),
                    "estimated_minutes_watched": int(data.get('estimatedMinutesWatched', 0) or 0),
                    "estimated_ad_revenue": float(data.get('estimatedAdRevenue', 0.0) or 0.0),
                    "cpm": float(data.get('cpm', 0.0) or 0.0),
                    "ad_impressions": int(data.get('adImpressions', 0) or 0)
                }

                all_performance_events.append(VideoPerformanceEvent(
                    video_id=data.get('video'),
                    platform="youtube",
                    date=data.get('day'),
                    estimated_revenue=float(data.get('estimatedRevenue', 0.0) or 0.0),
                    geography='Global',
                    extra_metrics=youtube_metrics_extras
                ))

        return all_performance_events