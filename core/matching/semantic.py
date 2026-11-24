"""Semantic multilingual matching using sentence embeddings.

Pre-computes and caches Broadkast catalog embeddings to disk so that
subsequent runs load in milliseconds instead of minutes.
Upgraded to a larger, more accurate model.
"""

import hashlib
import torch
import logging
from pathlib import Path
from sentence_transformers import SentenceTransformer
from core.domain.mapping import MatchStatus
from core.repositories.broadkast import BroadkastRepository

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache"

TERRITORY_TO_LANG = {
    "JP": ["ja", "en"], 
    "US": ["en"],
    "UK": ["en"],
    "GB": ["en"],
    "IE": ["en"],
    "AU": ["en"],
    "NZ": ["en"],
    "CA": ["en", "fr"],
    "DE": ["de", "en"],
    "AT": ["de", "en"],
    "CH": ["de", "fr", "it", "en"],
    "ES": ["es", "es-las", "en"],
    "MX": ["es-las", "es", "en"],
    "AR": ["es-las", "es", "en"],
    "CO": ["es-las", "es", "en"],
    "CL": ["es-las", "es", "en"],
    "BR": ["pt-br", "pt", "en"],
    "PT": ["pt", "pt-br", "en"],
    "IT": ["it", "en"],
    "FR": ["fr", "en"],
    "BE": ["fr", "nl", "en"],
    "PL": ["pl", "en"],
    "RO": ["ro", "en"],
    "NL": ["nl", "en"],
    "SE": ["sv", "en"],
    "FI": ["fi", "en"],
    "DK": ["da", "en"],
    "CZ": ["cs", "en"],
    "TR": ["tr", "en"],
    "RU": ["ru", "en"],
    "TH": ["th", "en"],
    "ID": ["id", "en"],
    "KR": ["ko", "en"],
    "TW": ["zh", "en"],
    "CN": ["zh", "en"],
    "IN": ["hi", "en"]
}

class SemanticMatcher:
    """Matches titles using global embeddings against the full catalog."""
    
    def __init__(self, repository: BroadkastRepository, model_name: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"):
        self.repository = repository
        # Use GPU if available, fallback gracefully to CPU (Fix C2)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        log.info(f"  Inicializando modelo SOTA en {self.device}: {model_name}")
        try:
            self.model = SentenceTransformer(model_name, device=self.device, local_files_only=True)
        except Exception:
            self.model = SentenceTransformer(model_name, device=self.device)
        
        # We don't deduplicate here anymore because we need to filter by language!
        # Different languages of the same title name should be preserved.
        # Deterministic ordering to ensure cached embeddings strictly align with self.all_bk indices (Fix C1)
        self.all_bk = list(self.repository.get_contents())
        self.all_bk.sort(key=lambda x: (str(x.content_id), str(x.language_code or ""), str(x.title_name or "")))
        
        # Load or compute embeddings
        self.embs_bk_norm = self._load_or_compute_embeddings(model_name)

    def _cache_key(self, model_name: str) -> str:
        """Generate a hash based on the catalog ids, languages, titles, and model name."""
        lines = [model_name]
        for bk in self.all_bk:
            lines.append(f"{bk.content_id}|{bk.language_code or ''}|{bk.title_name or ''}")
        content = "\n".join(lines)
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _load_or_compute_embeddings(self, model_name: str) -> torch.Tensor:
        """Load cached embeddings from disk, or compute and save them."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"bk_embeddings_{self._cache_key(model_name)}.pt"
        
        if cache_file.exists():
            log.info(f"  ⚡ Cargando embeddings cacheados desde {cache_file.name}")
            try:
                embs = torch.load(cache_file, map_location=self.device, weights_only=True)
                return embs.to(self.device)
            except Exception as e:
                log.warning(f"  ⚠️ Error cargando caché de embeddings ({e}). Recalculando...")
        
        log.info(f"  Calculando embeddings para {len(self.all_bk)} títulos (tardará unos minutos)...")
        bk_titles = [bk.title_name for bk in self.all_bk]
        embs = self.model.encode(bk_titles, convert_to_tensor=True, show_progress_bar=True)
        embs_norm = torch.nn.functional.normalize(embs, p=2, dim=1)
        
        # Atomic cache write using temporary file to avoid truncated/corrupt cache files (Fix C3)
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(dir=CACHE_DIR, delete=False, suffix=".tmp") as tmp:
                temp_path = Path(tmp.name)
                torch.save(embs_norm, temp_path)
            temp_path.replace(cache_file)
            log.info(f"  ✅ Embeddings guardados en caché atómicamente: {cache_file.name}")
        except Exception as e:
            log.warning(f"  ⚠️ No se pudo guardar el archivo de caché atómicamente: {e}")
            if 'temp_path' in locals() and temp_path.exists():
                temp_path.unlink()
        return embs_norm

    def _compute_series_embeddings(self) -> tuple[dict[str, torch.Tensor], dict[str, str]]:
        """Compute embeddings for all unique Broadkast series names on the fly.
        Returns:
            embs_dict: dict of normalized_series -> tensor
            orig_name_map: dict of normalized_series -> original_series_name
        """
        unique_orig = list(set(bk.series_name for bk in self.all_bk if bk.series_name))
        normalized = [s.lower().replace("_", " ") for s in unique_orig]
        
        embs = self.model.encode(normalized, convert_to_tensor=True, show_progress_bar=False)
        embs_norm = torch.nn.functional.normalize(embs, p=2, dim=1)
        
        embs_dict = {normalized[i]: embs_norm[i] for i in range(len(normalized))}
        orig_name_map = {normalized[i]: unique_orig[i] for i in range(len(normalized))}
        
        return embs_dict, orig_name_map

    def match_series_batch(self, amz_series_list: list[str], threshold: float = 70.0) -> list[str | None]:
        """Map Amazon series names to the exact Broadkast series name."""
        if not hasattr(self, 'bk_series_embeddings'):
            self.bk_series_embeddings, self.bk_series_orig = self._compute_series_embeddings()
            
        bk_norm_names = list(self.bk_series_embeddings.keys())
        if not bk_norm_names or not amz_series_list:
            return [None] * len(amz_series_list)
            
        bk_embs = torch.stack([self.bk_series_embeddings[s] for s in bk_norm_names])
        
        unique_amz = list(set(s for s in amz_series_list if s))
        if not unique_amz:
            return [None] * len(amz_series_list)
            
        log.info("  Codificando nombres de series...")
        amz_embs = self.model.encode(unique_amz, convert_to_tensor=True, show_progress_bar=False)
        amz_embs_norm = torch.nn.functional.normalize(amz_embs, p=2, dim=1)
        
        scores_matrix = torch.matmul(amz_embs_norm, bk_embs.transpose(0, 1))
        
        mapping = {}
        for i, amz_s in enumerate(unique_amz):
            from core.normalization.title import normalize_title
            amz_clean = normalize_title(amz_s)
            
            # Step 1: Exact normalization match
            exact_match = None
            for bk_norm in bk_norm_names:
                if normalize_title(bk_norm) == amz_clean:
                    exact_match = self.bk_series_orig[bk_norm]
                    break
                    
            if exact_match:
                mapping[amz_s] = exact_match
                continue
                
            # Step 2: Semantic match
            top_score, top_idx = torch.max(scores_matrix[i], dim=0)
            score = top_score.item() * 100
            if score >= threshold:
                mapping[amz_s] = self.bk_series_orig[bk_norm_names[top_idx.item()]]
            else:
                mapping[amz_s] = None
                
        return [mapping.get(s) for s in amz_series_list]

    def match_batch(
        self, 
        title_names: list[str], 
        territories: list[str], 
        series_constraints: list[str | None] = None
    ) -> list[tuple[MatchStatus, float, list]]:
        """Vectorized batch matching with territory filtering and strict series constraint."""
        if not self.all_bk or self.embs_bk_norm is None or not title_names:
            return [(MatchStatus.UNMATCHED, 0.0, [])] * len(title_names)
            
        log.info("  Codificando títulos de Amazon...")
        embs_amz = self.model.encode(title_names, convert_to_tensor=True, show_progress_bar=True)
        embs_amz_norm = torch.nn.functional.normalize(embs_amz, p=2, dim=1)
        
        log.info("  Multiplicando matriz de similitud semántica...")
        scores_matrix = torch.matmul(embs_amz_norm, self.embs_bk_norm.transpose(0, 1))
        
        # Pre-calculate masks
        bk_langs = [bk.language_code for bk in self.all_bk]
        bk_series = [bk.series_name for bk in self.all_bk]
        bk_projects = [bk.project_name for bk in self.all_bk]
        all_series_set = set(bk_series)
        all_projects_set = set(bk_projects)
        device = scores_matrix.device
        
        territory_masks = {}
        for t in set(territories):
            allowed_langs = TERRITORY_TO_LANG.get(t, None)
            if allowed_langs is not None:
                mask = torch.tensor([
                    (lang in allowed_langs) or (lang == "") 
                    for lang in bk_langs
                ], dtype=torch.bool, device=device)
                territory_masks[t] = mask
            else:
                territory_masks[t] = None
                
        active_constraints = set(c for c in (series_constraints or []) if c)
        constraint_masks = {}
        for c in active_constraints:
            if c in ("CARCITY", "CARCITY_SUPER"):
                mask = torch.tensor([
                    (p in ("CARCITY", "CARCITY_SUPER"))
                    for p in bk_projects
                ], dtype=torch.bool, device=device)
            elif c in all_projects_set:
                mask = torch.tensor([
                    (p == c)
                    for p in bk_projects
                ], dtype=torch.bool, device=device)
            elif c in all_series_set:
                mask = torch.tensor([
                    (s == c)
                    for s in bk_series
                ], dtype=torch.bool, device=device)
            else:
                mask = torch.tensor([
                    (s == c or p == c)
                    for s, p in zip(bk_series, bk_projects)
                ], dtype=torch.bool, device=device)
            constraint_masks[c] = mask

        results = []
        
        for i in range(len(title_names)):
            territory = territories[i]
            constraint = series_constraints[i] if series_constraints else None
            
            row_scores = scores_matrix[i].clone()
            
            # Apply language penalty
            mask = territory_masks.get(territory)
            if mask is not None:
                row_scores[~mask] = -1e9
                
            # Apply strict series constraint if present
            if constraint:
                series_mask = constraint_masks.get(constraint)
                if series_mask is not None:
                    row_scores[~series_mask] = -1e9
                
            # Get top score
            top_scores, top_indices = torch.topk(row_scores, k=1)
            raw_top_score = top_scores[0].item()
            if raw_top_score <= -1e8:
                results.append((MatchStatus.UNMATCHED, 0.0, []))
                continue
            score = raw_top_score * 100
            bk_cand = self.all_bk[top_indices[0].item()]
            
            if constraint:
                # If within constrained series/franchise, ensure candidate matches constraint
                matches_constraint = False
                if constraint in ("CARCITY", "CARCITY_SUPER"):
                    matches_constraint = (bk_cand.project_name in ("CARCITY", "CARCITY_SUPER"))
                elif constraint in all_projects_set:
                    matches_constraint = (bk_cand.project_name == constraint)
                elif constraint in all_series_set:
                    matches_constraint = (bk_cand.series_name == constraint)
                else:
                    matches_constraint = (bk_cand.series_name == constraint or bk_cand.project_name == constraint)

                if not matches_constraint or score < 15.0:
                    results.append((MatchStatus.UNMATCHED, 0.0, []))
                else:
                    results.append((MatchStatus.MATCH, score, [bk_cand]))
            else:
                # Global semantic matching (when no constraint exists)
                if score >= 82.0:
                    results.append((MatchStatus.MATCH, score, [bk_cand]))
                elif score >= 55.0:
                    results.append((MatchStatus.REVIEW, score, [bk_cand]))
                else:
                    results.append((MatchStatus.UNMATCHED, 0.0, []))
                
        return results
