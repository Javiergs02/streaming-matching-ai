"""
core/domain/youtube_channels.py

Fast, in-memory reference catalog resolver for YouTube Channels.
Provides O(1) lookups for:
1. Channel ID -> Main Series IP, Universe, IP Code, Global IP, Global Universe
2. Channel ID -> Canonical Title, Audio Language

Enables automatic fallback enrichment for unlinked YouTube videos (compilations,
music, new clips) that would otherwise be classified as UNMATCHED in dashboards.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger("youtube_channels")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_JSON_PATH = PROJECT_ROOT / "data" / "reference" / "youtube_channel_catalog.json"
EXCEL_PATH = PROJECT_ROOT / "data" / "reference" / "Mapping Youtube Channels.xlsx"


class YouTubeChannelCatalog:
    """Singleton-style in-memory catalog for YouTube channel metadata lookups."""

    _instance: Optional[YouTubeChannelCatalog] = None

    def __init__(self, catalog_path: Path = CATALOG_JSON_PATH) -> None:
        self.catalog_path = Path(catalog_path)
        self._channels: Dict[str, Dict[str, Any]] = {}
        self._ip_to_channels: Dict[str, List[str]] = {}
        self._universe_to_channels: Dict[str, List[str]] = {}
        self._loaded: bool = False
        self._load()

    @classmethod
    def get_instance(cls) -> YouTubeChannelCatalog:
        """Returns the global singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        """Loads JSON catalog into memory, or builds on the fly from Excel if missing."""
        if not self.catalog_path.exists():
            log.warning("YouTube channel catalog JSON not found at: %s. Attempting to build from Excel...", self.catalog_path)
            try:
                from scripts.build_youtube_channel_catalog import build_channel_catalog
                build_channel_catalog()
            except Exception as e:
                log.error("Failed to auto-generate youtube_channel_catalog.json: %s", e)
                return

        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._channels = data.get("channels", {})
            self._loaded = True
            log.info("Loaded %d YouTube channels into memory catalog.", len(self._channels))

            # Build reverse indices
            self._ip_to_channels = {}
            self._universe_to_channels = {}
            for cid, info in self._channels.items():
                ip = info.get("main_series_ip")
                univ = info.get("universe")
                if ip:
                    self._ip_to_channels.setdefault(ip, []).append(cid)
                if univ:
                    self._universe_to_channels.setdefault(univ, []).append(cid)

        except Exception as e:
            log.error("Failed to load YouTube channel catalog from %s: %s", self.catalog_path, e)

    @property
    def is_loaded(self) -> bool:
        return self._loaded and len(self._channels) > 0

    def get_channel(self, channel_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """O(1) lookup of channel information by YouTube channel ID (e.g. 'UC...')."""
        if not channel_id:
            return None
        # Support raw ID or 'Title (UC...)' format commonly used in dashboards
        clean_id = str(channel_id).strip()
        if "(" in clean_id and clean_id.endswith(")"):
            clean_id = clean_id.split("(")[-1].rstrip(")")
        return self._channels.get(clean_id)

    def resolve_ip(self, channel_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Returns (main_series_ip, universe) for a channel ID, or (None, None) if unknown."""
        info = self.get_channel(channel_id)
        if not info:
            return None, None
        return info.get("main_series_ip"), info.get("universe")

    def get_all_channels(self) -> Dict[str, Dict[str, Any]]:
        """Returns the full dictionary of channel mappings."""
        return self._channels

    def get_channels_for_ip(self, ip_name: str) -> List[str]:
        """Returns list of channel IDs attributed to a given IP."""
        return self._ip_to_channels.get(ip_name, [])

    def get_channels_for_universe(self, universe: str) -> List[str]:
        """Returns list of channel IDs attributed to a given Universe."""
        return self._universe_to_channels.get(universe, [])


# Convenience global module functions

def get_youtube_channel_info(channel_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """O(1) lookup of YouTube channel metadata."""
    return YouTubeChannelCatalog.get_instance().get_channel(channel_id)


def resolve_youtube_channel_ip(channel_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Resolves (main_series_ip, universe) for a given channel ID."""
    return YouTubeChannelCatalog.get_instance().resolve_ip(channel_id)


def enrich_youtube_video_metadata(
    channel_id: Optional[str],
    current_series: Optional[str] = None,
    current_ip: Optional[str] = None
) -> Tuple[str, str]:
    """
    Enriches YouTube video metadata with channel-level fallback.
    If current_ip is 'UNMATCHED', empty, or None, resolves from channel catalog.
    Returns (series_name, ip_name).
    """
    cur_ip_clean = str(current_ip or "").strip()
    cur_series_clean = str(current_series or "").strip()

    is_unmatched_ip = (
        not cur_ip_clean
        or cur_ip_clean.upper() in ("UNMATCHED", "UNKNOWN", "UNKNOWN IP", "NONE", "NAN")
    )
    is_unmatched_series = (
        not cur_series_clean
        or cur_series_clean.upper() in ("UNMATCHED", "UNMATCHED_YT", "UNKNOWN", "UNKNOWN SERIES", "NONE", "NAN")
    )

    if not is_unmatched_ip and not is_unmatched_series:
        return cur_series_clean, cur_ip_clean

    channel_info = get_youtube_channel_info(channel_id)
    if not channel_info:
        return (
            cur_series_clean or "UNMATCHED_YT",
            cur_ip_clean or "UNMATCHED"
        )

    res_ip = channel_info.get("main_series_ip") or "Others"
    res_series = channel_info.get("main_series_ip") or channel_info.get("channel_title") or "UNMATCHED_YT"

    final_ip = cur_ip_clean if not is_unmatched_ip else res_ip
    final_series = cur_series_clean if not is_unmatched_series else res_series

    return final_series, final_ip


def enrich_youtube_dataframe(
    df: pd.DataFrame,
    channel_col: str = "channel_id",
    ip_col: str = "ip_name",
    series_col: str = "series_name",
    universe_col: Optional[str] = "universe"
) -> pd.DataFrame:
    """
    Applies channel-level IP fallback enrichment to a pandas DataFrame in-place.
    Only updates rows where ip_name is 'UNMATCHED' or missing.
    """
    if df.empty or channel_col not in df.columns:
        return df

    catalog = YouTubeChannelCatalog.get_instance()
    if not catalog.is_loaded:
        return df

    # Vectorized / map-based lookup for performance
    channel_map = catalog.get_all_channels()

    def _resolve_row(row):
        c_id = row.get(channel_col)
        cur_ip = row.get(ip_col)
        cur_series = row.get(series_col)

        # Check if already matched
        cur_ip_str = str(cur_ip or "").strip().upper()
        if cur_ip_str and cur_ip_str not in ("UNMATCHED", "UNKNOWN", "UNKNOWN IP", "NONE", "NAN"):
            return cur_series, cur_ip, row.get(universe_col, "")

        # Look up channel
        clean_cid = str(c_id or "").strip()
        if "(" in clean_cid and clean_cid.endswith(")"):
            clean_cid = clean_cid.split("(")[-1].rstrip(")")

        info = channel_map.get(clean_cid)
        if not info:
            return cur_series, cur_ip, row.get(universe_col, "")

        new_ip = info.get("main_series_ip", "Others")
        new_series = cur_series if (cur_series and str(cur_series).strip().upper() not in ("UNMATCHED_YT", "UNKNOWN SERIES", "NONE", "NAN")) else new_ip
        new_univ = info.get("universe", "Others")

        return new_series, new_ip, new_univ

    results = df.apply(_resolve_row, axis=1)
    df[series_col] = [r[0] for r in results]
    df[ip_col] = [r[1] for r in results]
    if universe_col:
        df[universe_col] = [r[2] for r in results]

    return df
