"""Unit tests for HybridTitleMatcher blacklist logic."""

import pytest
from datetime import date
from core.matching.hybrid import HybridTitleMatcher
from core.domain.amazon import AmazonPerformanceRecord
from core.domain.mapping import MatchStatus
from core.repositories.broadkast import BroadkastRepository


class DummyRepository(BroadkastRepository):
    """Mock repository that returns empty contents to isolate blacklist tests."""
    def get_canonical_contents(self):
        return []


def test_blacklist_keywords_triggers_unmatched():
    repo = DummyRepository()
    matcher = HybridTitleMatcher(repo)

    blacklist_titles = [
        "Groovy el Marciano Episodio 1",
        "Groovy The Martian Season 2",
        "O Marciano Groovy e amigos",
        "Molang - The Rainbow",
        "Mouk Travels to Japan",
        "Superzoo Animals Save the Day",
        "Louie Draw me a house",
    ]

    for title in blacklist_titles:
        record = AmazonPerformanceRecord(
            date=date(2025, 5, 1),
            title_id="B000TEST",
            title_name=title,
            season_id="S01",
            season_name="Season 1",
            series_id="SER_01",
            series_name="External",
            offer_type="PRIME",
            region="Europe",
            territory="ES",
            minutes_streamed=100.0,
            unique_streams=10,
            is_movie=False
        )
        results = matcher.match([record])
        assert len(results) == 1
        result = results[0]
        assert result.match_status == MatchStatus.UNMATCHED
        assert result.match_method == "blacklist"


def test_unresolved_series_with_exact_title_matches():
    """Verify Fix C5: Valid exact title matches are not rejected if series name is unknown."""
    from core.domain.broadkast import BroadkastContent

    class MockCatalogRepo(BroadkastRepository):
        def get_contents(self):
            return [
                BroadkastContent(
                    content_id="BK_101",
                    title_name="Speedy Car Adventures Episode 1",
                    series_name="Car City",
                    season_number="1",
                    episode_number="1",
                    project_name="CARCITY",
                    language_code="en"
                )
            ]

    matcher = HybridTitleMatcher(MockCatalogRepo())
    # Record has an unknown localized series name not found in Broadkast aliases
    record = AmazonPerformanceRecord(
        date=date(2025, 5, 1),
        title_id="B000TEST_EXACT",
        title_name="Speedy Car Adventures Episode 1",
        season_id="S01",
        season_name="Season 1",
        series_id="SER_UNKNOWN",
        series_name="Unknown Unresolvable German Series Name",
        offer_type="PRIME",
        region="Europe",
        territory="DE",
        minutes_streamed=100.0,
        unique_streams=10,
        is_movie=False
    )
    results = matcher.match([record])
    assert len(results) == 1
    assert results[0].match_status == MatchStatus.MATCH
    assert results[0].broadkast_content_id == "BK_101"
    assert results[0].match_method == "exact_title"


