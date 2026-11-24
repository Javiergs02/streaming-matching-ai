"""
core/domain/amazon_catalog.py

Fast, in-memory reference catalog resolver for Amazon Video Direct metadata.
Provides O(1) lookups for:
1. Amazon IDs (Title ID / ASIN, Season ID, Series ID)
2. Localized Series Names

Implements deterministic cascade resolution:
Title ID -> Season ID -> Series ID -> Series Name (exact) -> Series Name (normalized).
"""

from __future__ import annotations

import json
import logging
import re
import string
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("amazon_catalog")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ID_CATALOG_PATH = PROJECT_ROOT / "data" / "reference" / "amazon_id_catalog.json"
SERIES_CATALOG_PATH = PROJECT_ROOT / "data" / "reference" / "amazon_series_catalog.json"


def normalize_series_key(s: Optional[str]) -> str:
    """Normalizes series name for fuzzy/insensitive lookup: lowercase, stripped punctuation, single spaces."""
    if not s:
        return ""
    # Normalize unicode accents
    norm = unicodedata.normalize("NFKD", str(s))
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = norm.lower().translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", norm).strip()


class AmazonReferenceCatalog:
    """Singleton-style in-memory catalog for Amazon metadata lookups."""

    _instance: Optional[AmazonReferenceCatalog] = None

    def __init__(
        self,
        id_catalog_path: Path = ID_CATALOG_PATH,
        series_catalog_path: Path = SERIES_CATALOG_PATH,
    ) -> None:
        self.id_catalog_path = Path(id_catalog_path)
        self.series_catalog_path = Path(series_catalog_path)
        self._ids: Dict[str, Dict[str, Any]] = {}
        self._series: Dict[str, Dict[str, Any]] = {}
        self._series_normalized: Dict[str, Dict[str, Any]] = {}
        self._loaded: bool = False
        self._load()

    @classmethod
    def get_instance(cls) -> AmazonReferenceCatalog:
        """Returns the global singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        """Loads JSON catalogs into memory if they exist."""
        if not self.id_catalog_path.exists():
            log.warning("Amazon ID catalog not found at: %s", self.id_catalog_path)
            return
        if not self.series_catalog_path.exists():
            log.warning("Amazon series catalog not found at: %s", self.series_catalog_path)
            return

        try:
            with open(self.id_catalog_path, "r", encoding="utf-8") as f:
                self._ids = json.load(f)

            with open(self.series_catalog_path, "r", encoding="utf-8") as f:
                self._series = json.load(f)

            # Build normalized index for series names
            for s_name, data in self._series.items():
                norm_key = normalize_series_key(s_name)
                if norm_key:
                    self._series_normalized[norm_key] = data

            self._loaded = True
            log.info(
                "AmazonReferenceCatalog loaded %d IDs and %d Series Names successfully.",
                len(self._ids),
                len(self._series),
            )
        except Exception as e:
            log.error("Failed to load Amazon Reference Catalog: %s", e, exc_info=True)
            self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_id(self, amazon_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """O(1) lookup by any Amazon identifier (Title ID, Season ID, Series ID)."""
        if not amazon_id:
            return None
        cleaned = str(amazon_id).strip()
        return self._ids.get(cleaned)

    def get_series(self, series_name: Optional[str]) -> Optional[Dict[str, Any]]:
        """Lookup by series name: exact first, then normalized."""
        if not series_name:
            return None
        cleaned = str(series_name).strip()
        # 1. Exact match
        if cleaned in self._series:
            return self._series[cleaned]

        # 2. Normalized match
        norm = normalize_series_key(cleaned)
        return self._series_normalized.get(norm)

    def resolve(
        self,
        amazon_id: Optional[str] = None,
        season_id: Optional[str] = None,
        series_id: Optional[str] = None,
        series_name: Optional[str] = None,
        title_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Cascade resolver that checks:
        1. amazon_id directly (Title ID / ASIN / SKU)
        2. season_id directly
        3. series_id directly
        4. series_name (exact match)
        5. series_name (normalized match)

        Returns standardized metadata dict or None if no match found.
        """
        # Step 1: Direct ID Match
        if amazon_id:
            match = self.get_id(amazon_id)
            if match:
                res = dict(match)
                res["match_level"] = f"id_{match.get('id_type', 'unknown')}"
                return res

        # Step 2: Season ID Match
        if season_id:
            match = self.get_id(season_id)
            if match:
                res = dict(match)
                res["match_level"] = "season_id"
                return res

        # Step 3: Series ID Match
        if series_id:
            match = self.get_id(series_id)
            if match:
                res = dict(match)
                res["match_level"] = "series_id"
                return res

        # Step 4: Series Name Match
        if series_name:
            s_match = self.get_series(series_name)
            if s_match:
                return {
                    "id": None,
                    "id_type": "series_name",
                    "title_name": title_name,
                    "season_id": season_id,
                    "series_id": series_id,
                    "series_name": series_name,
                    "season_number": None,
                    "episode_number": None,
                    "ip": s_match.get("ip"),
                    "global_ip": s_match.get("global_ip"),
                    "universe": s_match.get("universe"),
                    "global_universe": s_match.get("global_universe"),
                    "language_code": None,
                    "match_level": "series_name",
                }

        return None
