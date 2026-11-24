"""Hybrid matcher: Exact -> Semantic AI.

Pipeline optimized for speed:
1. Exact: Instant normalized string match
2. Semantic AI: Cross-language matching using cached embeddings
"""

from __future__ import annotations

import logging
import re
import time
from typing import Sequence
from collections import defaultdict

from core.domain.amazon import AmazonPerformanceRecord
from core.domain.mapping import ContentMapping, MatchStatus, MappingCandidate
from core.matching.exact import ExactTitleMatcher
from core.normalization.title import normalize_title
from core.normalization.series_alias import (
    extract_title_and_series,
    is_alien_series,
    resolve_canonical_series,
    resolve_constraint,
    resolve_franchise_project,
)
from core.matching.semantic import SemanticMatcher
from core.repositories.broadkast import BroadkastRepository


log = logging.getLogger(__name__)


class HybridTitleMatcher:
    """Matches records using Exact -> Semantic AI pipeline."""

    BLACKLIST_KEYWORDS = (
        "molang",
        "mouk",
        "louie",
        "superzoo",
        "zoológico 64",
        "zoo lane",
        "didou",
        "groovy"
    )

    def __init__(
        self,
        repository: BroadkastRepository,
        lazy_semantic: bool = True,
    ) -> None:
        self._repository = repository
        self._exact_matcher = ExactTitleMatcher(repository)
        self._semantic_matcher: SemanticMatcher | None = None
        self._lazy_semantic = lazy_semantic

    def _get_semantic_matcher(self) -> SemanticMatcher:
        """Lazy-load the Semantic matcher only when needed."""
        if self._semantic_matcher is None:
            print("  Cargando modelo de IA Semántica (y embeddings desde caché si existen)...")
            self._semantic_matcher = SemanticMatcher(self._repository)
        return self._semantic_matcher

    def match(self, records: Sequence[AmazonPerformanceRecord]) -> list[ContentMapping]:
        records_list = list(records)
        mappings: list[ContentMapping] = [None] * len(records_list)
        
        t0 = time.time()
        
        # === PHASE 0: Blacklist Filter ===
        # Reject known alien series immediately to avoid cross-series false positives
        active_records = []
        active_indices = []
        
        blacklisted_count = 0
        movie_count = 0
        for i, record in enumerate(records_list):
            series_lower = (record.series_name or "").lower()
            title_lower = (record.title_name or "").lower()
            if (
                any(kw in series_lower or kw in title_lower for kw in self.BLACKLIST_KEYWORDS)
                or is_alien_series(record.series_name)
                or is_alien_series(record.title_name)
            ):
                mappings[i] = ContentMapping(
                    amazon_title_id=record.title_id,
                    amazon_title_name=record.title_name,
                    amazon_normalized_title=normalize_title(record.title_name),
                    match_status=MatchStatus.UNMATCHED,
                    score=None,
                    match_method="blacklist",
                    candidates=[]
                )
                blacklisted_count += 1
            elif record.is_movie:
                mappings[i] = ContentMapping(
                    amazon_title_id=record.title_id,
                    amazon_title_name=record.title_name,
                    amazon_normalized_title=normalize_title(record.title_name),
                    match_status=MatchStatus.UNMATCHED,
                    score=None,
                    match_method="movie",
                    candidates=[]
                )
                movie_count += 1
            else:
                active_records.append(record)
                active_indices.append(i)
                
        if blacklisted_count > 0:
            print(f"  [Blacklist] Bloqueados {blacklisted_count} registros ajenos (Molang, Mouk, etc.)")
            
        if movie_count > 0:
            print(f"  [Movies] Descartes automáticos de {movie_count} películas (is_movie=True)")
            
        if not active_records:
            return mappings

        # === PHASE 0.5: Series Discovery via Episode Voting ===
        amz_series_groups = defaultdict(list)
        for idx, record in enumerate(active_records):
            if record.series_name:
                amz_series_groups[record.series_name].append(idx)
                
        series_mapping = {}
        if amz_series_groups:
            # Exact series string match fallback
            bk_series_names = list(set(c.series_name for c in self._repository.get_contents() if c.series_name))
            bk_series_norm = {normalize_title(s): s for s in bk_series_names}
            
            vote_titles = []
            vote_territories = []
            vote_series = []
            
            for amz_series, indices in amz_series_groups.items():
                # 1. Check canonical alias rules directly (instant, accurate)
                canon_series = resolve_canonical_series(amz_series)
                if canon_series:
                    series_mapping[amz_series] = canon_series
                    continue

                # 2. Check exact normalized string match against Broadkast series
                norm_amz = normalize_title(amz_series)
                if norm_amz in bk_series_norm:
                    series_mapping[amz_series] = bk_series_norm[norm_amz]
                    continue
                    
                # 3. Take up to 5 samples for voting if truly unknown
                sample_indices = indices[:5]
                for idx in sample_indices:
                    record = active_records[idx]
                    _, clean_title = extract_title_and_series(record.title_name, amz_series)
                    clean_title = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', clean_title).strip()
                    for marker in ["/", "|", " - ", "&", " + ", " そして", " ＆"]:
                        if marker in clean_title:
                            clean_title = clean_title.split(marker, 1)[0].strip()
                            
                    if clean_title:
                        vote_titles.append(clean_title)
                        vote_territories.append(record.territory)
                        vote_series.append(amz_series)
                        
            if vote_titles:
                print(f"  [Series Mapping] Votando para descubrir el mapeo de {len(set(vote_series))} series de Amazon localizadas...")
                semantic_matcher = self._get_semantic_matcher()
                vote_results = semantic_matcher.match_batch(vote_titles, vote_territories, series_constraints=None)
                
                # Tally votes (sum of scores for matches >= 55%)
                votes = defaultdict(lambda: defaultdict(float))
                for j, (status, score, bks) in enumerate(vote_results):
                    if status in [MatchStatus.MATCH, MatchStatus.REVIEW] and bks:
                        amz_s = vote_series[j]
                        votes[amz_s][bks[0].series_name] += score
                        
                for amz_s, tally in votes.items():
                    if tally:
                        best_bk_series, total_score = max(tally.items(), key=lambda x: x[1])
                        
                        # Find the highest single vote for this specific amz_s that voted for best_bk_series (Fix BUG-07)
                        max_single_vote = 0.0
                        for j, (status, score, bks) in enumerate(vote_results):
                            if vote_series[j] == amz_s and status in [MatchStatus.MATCH, MatchStatus.REVIEW] and bks:
                                if bks[0].series_name == best_bk_series and score > max_single_vote:
                                    max_single_vote = score
                                    
                        # Prevent alien movies (1 episode) with mediocre similarity from locking a series
                        # Require either a high accumulated score (>= 120) or a single very strong match (>= 82.0)
                        if total_score >= 120.0 or max_single_vote >= 82.0:
                            series_mapping[amz_s] = best_bk_series
            
        series_constraints = []
        for r in active_records:
            s_cons = resolve_constraint(r.series_name, r.title_name)
            if not s_cons and r.series_name:
                s_cons = series_mapping.get(r.series_name)
            series_constraints.append(s_cons)
        
        # === PHASE 1: Exact Match (instant) ===
        # Evaluate exact matching across ALL active records first so valid exact matches
        # are never prematurely discarded by unresolved series names (Fix C5)
        exact_results = self._exact_matcher.match(active_records, series_constraints)
        
        unmatched_indices = []
        unmatched_constraints = []
        alien_rejected_count = 0
        
        for j, exact_mapping in enumerate(exact_results):
            original_idx = active_indices[j]
            record = active_records[j]
            constraint = series_constraints[j]
            
            if exact_mapping.match_status != MatchStatus.UNMATCHED:
                mappings[original_idx] = exact_mapping
            else:
                # If exact match failed and the series cannot be resolved to Broadkast, reject as alien series
                if record.series_name and not constraint:
                    mappings[original_idx] = ContentMapping(
                        amazon_title_id=record.title_id,
                        amazon_title_name=record.title_name,
                        amazon_normalized_title=normalize_title(record.title_name),
                        match_status=MatchStatus.UNMATCHED,
                        score=None,
                        match_method="alien_series_rejected",
                        candidates=[]
                    )
                    alien_rejected_count += 1
                else:
                    unmatched_indices.append(original_idx)
                    unmatched_constraints.append(constraint)

        if alien_rejected_count > 0:
            log.info(f"  [Series Mapping] Rechazadas {alien_rejected_count} reproducciones de series ajenas a Broadkast.")

        t1 = time.time()
        log.info(f"  [Exact]    {len(active_records) - len(unmatched_indices) - alien_rejected_count} matched | {len(unmatched_indices)} remaining | {t1-t0:.1f}s")
        
        if not unmatched_indices:
            return mappings
            
        # === PHASE 2: Semantic AI ===
        semantic_matcher = self._get_semantic_matcher()
        
        sem_titles = []
        for idx in unmatched_indices:
            raw_title = records_list[idx].title_name
            # Extract title and strip series/thematic prefix safely
            _, clean_title = extract_title_and_series(raw_title, records_list[idx].series_name)
            # 1. Clean typical Amazon noise: tags like 【...】, [...], (...)
            clean_title = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', clean_title).strip()
            # 2. Truncate compilation markers (take the left side)
            for marker in ["/", "|", " - ", "&", " + ", " そして", " ＆"]:
                if marker in clean_title:
                    clean_title = clean_title.split(marker, 1)[0].strip()
            if not clean_title:
                clean_title = raw_title.strip()
            sem_titles.append(clean_title)
            
        sem_territories = [records_list[idx].territory for idx in unmatched_indices]
        sem_results = semantic_matcher.match_batch(sem_titles, sem_territories, unmatched_constraints)
        
        for j, (sem_status, sem_score, sem_bks) in enumerate(sem_results):
            original_idx = unmatched_indices[j]
            record = records_list[original_idx]
            
            if sem_status != MatchStatus.UNMATCHED:
                bk = sem_bks[0]
                mappings[original_idx] = ContentMapping(
                    amazon_title_id=record.title_id,
                    amazon_title_name=record.title_name,
                    amazon_normalized_title=normalize_title(record.title_name),
                    match_status=sem_status,
                    broadkast_content_id=bk.content_id,
                    broadkast_title_name=bk.title_name,
                    broadkast_normalized_title=normalize_title(bk.title_name),
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
                    score=sem_score,
                    match_method="semantic_ai",
                    candidates=[MappingCandidate(bk.content_id, bk.title_name, normalize_title(bk.title_name))]
                )
            else:
                # Final UNMATCHED
                mappings[original_idx] = ContentMapping(
                    amazon_title_id=record.title_id,
                    amazon_title_name=record.title_name,
                    amazon_normalized_title=normalize_title(record.title_name),
                    match_status=MatchStatus.UNMATCHED,
                    score=None,
                    match_method="unmatched",
                    candidates=[]
                )
                
        t2 = time.time()
        sem_matched = sum(1 for j in range(len(unmatched_indices)) if sem_results[j][0] != MatchStatus.UNMATCHED)
        final_unmatched = len(unmatched_indices) - sem_matched
        log.info(f"  [Semantic] {sem_matched} matched | {final_unmatched} unmatched | {t2-t1:.1f}s")
        log.info(f"  [Total]    {t2-t0:.1f}s")
                
        return mappings
