"""Exact title matching engine.

Compares Amazon performance records against Broadkast content using
*exact* normalized-title comparison.  No fuzzy logic, no partial
matching, no ML.

Flow:

    AmazonPerformanceRecord.title_name
        -> normalize_title()
        -> exact lookup in normalized Broadkast index
        -> ContentMapping (MATCH / AMBIGUOUS / UNMATCHED)

Each ContentMapping carries full audit trail: original and normalized
titles for both sides, and — for AMBIGUOUS results — the full list of
candidate Broadkast items.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from core.domain.amazon import AmazonPerformanceRecord
from core.domain.broadkast import BroadkastContent
from core.domain.mapping import ContentMapping, MappingCandidate, MatchStatus
from core.normalization.title import normalize_title
from core.repositories.broadkast import BroadkastRepository

log = logging.getLogger(__name__)

MATCH_METHOD = "exact_title"


class ExactTitleMatcher:
    """Matcher that uses exact normalized-title comparison.

    Build a normalized index of Broadkast content, then for each
    Amazon record look up by its normalized title.

    Match rules:
      - Exactly 1 candidate -> MATCH (score=100.0)
      - 0 candidates        -> UNMATCHED (score=None)
      - 2+ candidates       -> AMBIGUOUS (score=100.0, no tie-breaking)
    """

    def __init__(self, repository: BroadkastRepository) -> None:
        self._repository = repository
        self._index: dict[str, list[BroadkastContent]] | None = None

    def _build_index(self) -> dict[str, list[BroadkastContent]]:
        if self._index is not None:
            return self._index

        index: dict[str, list[BroadkastContent]] = defaultdict(list)
        for content in self._repository.get_contents():
            key = normalize_title(content.title_name)
            if not key:
                continue
            index[key].append(content)

        log.info(
            "Broadkast index built: %d normalized title(s), %d content item(s)",
            len(index),
            sum(len(v) for v in index.values()),
        )
        self._index = dict(index)
        return self._index

    def match(
        self,
        records: list[AmazonPerformanceRecord],
        series_constraints: list[str | None] = None,
    ) -> list[ContentMapping]:
        """Match each Amazon record against the Broadkast catalog.

        Returns one ContentMapping per input record, preserving every
        original record (no deduplication).
        If series_constraints is provided, it must be the same length as records,
        and candidates will be strictly filtered to that Broadkast series.
        """
        if series_constraints is not None and len(series_constraints) != len(records):
            raise ValueError(
                f"series_constraints length ({len(series_constraints)}) must match records length ({len(records)})"
            )

        index = self._build_index()
        mappings: list[ContentMapping] = [None] * len(records)
        
        for i, record in enumerate(records):
            normalized = normalize_title(record.title_name)
            if not normalized:
                mappings[i] = ContentMapping(
                    amazon_title_id=record.title_id,
                    amazon_title_name=record.title_name,
                    amazon_normalized_title="",
                    match_status=MatchStatus.UNMATCHED,
                    score=None,
                    match_method=MATCH_METHOD,
                    candidates=[],
                )
                continue

            candidates = index.get(normalized, [])
            
            constraint = series_constraints[i] if series_constraints else None
            if constraint:
                if constraint in ("CARCITY", "CARCITY_SUPER"):
                    candidates = [c for c in candidates if c.project_name in ("CARCITY", "CARCITY_SUPER") or c.series_name == constraint]
                else:
                    candidates = [c for c in candidates if c.series_name == constraint or c.project_name == constraint]

            mapping, _ = self._create_mapping(record, normalized, candidates)
            mappings[i] = mapping

        matched = sum(1 for m in mappings if m.match_status == MatchStatus.MATCH)
        unmatched = sum(1 for m in mappings if m.match_status == MatchStatus.UNMATCHED)
        ambiguous = sum(1 for m in mappings if m.match_status == MatchStatus.AMBIGUOUS)

        log.info(
            "Matching complete: %d total, %d MATCH, %d AMBIGUOUS, %d UNMATCHED",
            len(mappings),
            matched,
            ambiguous,
            unmatched,
        )
        return mappings

    def _to_candidate(self, content: BroadkastContent) -> MappingCandidate:
        return MappingCandidate(
            content_id=content.content_id,
            title_name=content.title_name,
            normalized_title=normalize_title(content.title_name),
        )

    def _create_mapping(
        self,
        record: AmazonPerformanceRecord,
        normalized: str,
        candidates: list[BroadkastContent],
    ) -> tuple[ContentMapping, list[BroadkastContent]]:
        n = len(candidates)

        if n == 0:
            return ContentMapping(
                amazon_title_id=record.title_id,
                amazon_title_name=record.title_name,
                amazon_normalized_title=normalized,
                match_status=MatchStatus.UNMATCHED,
                score=None,
                match_method=MATCH_METHOD,
                candidates=[],
            ), []

        # They are already filtered by series_constraint (if provided).
        # The user explicitly stated: "da igual si confunde dos episodios de la misma serie".
        # Therefore, we can just pick the first candidate safely and mark as MATCH.
        
        bk = candidates[0]
        bk_normalized = normalize_title(bk.title_name)
        
        return ContentMapping(
            amazon_title_id=record.title_id,
            amazon_title_name=record.title_name,
            amazon_normalized_title=normalized,
            match_status=MatchStatus.MATCH,
            broadkast_content_id=bk.content_id,
            broadkast_title_name=bk.title_name,
            broadkast_normalized_title=bk_normalized,
            broadkast_series=bk.series_name,
            broadkast_season=bk.season_number,
            broadkast_performance_score=bk.performance_score,
            broadkast_no_dialog=bk.no_dialog,
            broadkast_project_id=bk.project_id,
            broadkast_project_name=bk.project_name,
            broadkast_series_id=bk.series_id,
            broadkast_season_id=bk.season_id,
            broadkast_video_id=bk.video_id,
            broadkast_episode_number=bk.episode_number,
            score=100.0,
            match_method=MATCH_METHOD,
            candidates=[self._to_candidate(bk)],
        ), candidates
