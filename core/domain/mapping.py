"""Domain entities for content mapping results.

ContentMapping represents the outcome of matching an Amazon performance
record against one or more Broadkast content items.  It is designed for
auditability — every result carries enough context to explain why a
particular status was assigned.

Match scores
------------
For exact matches, ``score`` is always 1.0.  For semantic AI matches,
``score`` is the cosine similarity percentage (0-100) between the
Amazon title embedding and the best Broadkast candidate embedding.
``None`` for misses (UNMATCHED).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MatchStatus(Enum):
    MATCH = "MATCH"
    REVIEW = "REVIEW"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


@dataclass(frozen=True)
class MappingCandidate:
    """A Broadkast content item that matched an Amazon normalized title."""

    content_id: str
    title_name: str
    normalized_title: str


@dataclass(frozen=True)
class ContentMapping:
    """Result of matching one AmazonPerformanceRecord against Broadkast.

    Required fields (no defaults):
        amazon_title_id        -- from the Amazon record
        amazon_title_name      -- original Amazon title
        amazon_normalized_title -- normalized Amazon title (audit trail)
        match_status           -- MATCH / AMBIGUOUS / UNMATCHED / REVIEW

    Optional fields (defaulted):
        broadkast_content_id   -- the matched Broadkast ID (empty if not 1-to-1)
        broadkast_title_name   -- the matched Broadkast title (empty if not 1-to-1)
        broadkast_normalized_title -- normalized Broadkast title (for MATCH only)
        score                  -- 1.0 for any textual hit, None for UNMATCHED
        match_method           -- e.g. "exact_title"
        candidates             -- all matching Broadkast items (for AMBIGUOUS)
    """

    # Required — set for every mapping
    amazon_title_id: str
    amazon_title_name: str
    amazon_normalized_title: str
    match_status: MatchStatus

    # Populated only when a single Broadkast candidate matched
    broadkast_content_id: str = ""
    broadkast_title_name: str = ""
    broadkast_normalized_title: str = ""
    broadkast_series: str = ""
    broadkast_season: str = ""
    broadkast_performance_score: str = ""
    broadkast_no_dialog: str = ""
    broadkast_project_id: str = ""
    broadkast_project_name: str = ""
    broadkast_series_id: str = ""
    broadkast_season_id: str = ""
    broadkast_video_id: str = ""
    broadkast_episode_number: str = ""

    # score = 1.0 means "exact textual match on normalized title",
    # NOT a confidence probability.  None when no candidate matched.
    score: float | None = None
    match_method: str = ""

    # AMBIGUOUS: all candidate Broadkast items that shared the
    # normalized title.  MATCH: contains the single matched candidate.
    # UNMATCHED: empty.
    candidates: list[MappingCandidate] = field(default_factory=list)
