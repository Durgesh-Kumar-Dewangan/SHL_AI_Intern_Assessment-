"""Hybrid retrieval over the SHL catalog.

Design choice: rather than pulling in sentence-transformers + FAISS (heavy,
needs a model download, slow cold start on free-tier hosting), we use BM25
keyword search as the primary signal combined with lightweight metadata-aware
boosting (test-type keywords, job-level keywords, explicit product-name
matches). For a catalog of ~400 well-described short documents, BM25 is a
strong, fast, dependency-light baseline that keeps the service well inside the
30s per-call budget with zero cold-start latency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.data.catalog_loader import CatalogItem

_TOKEN_RE = re.compile(r"[a-zA-Z0-9+#.]+")

# Recruiter / hiring-manager vocabulary → catalog terminology.
# Expands recall for queries phrased in business language rather than SHL taxonomy.
SYNONYM_EXPANSIONS: dict[str, list[str]] = {
    "personality": ["opq32r", "occupational personality questionnaire", "behavior", "behaviour", "opq"],
    "cognitive": ["verify", "ability", "aptitude", "reasoning", "numerical", "verbal", "inductive"],
    "aptitude": ["verify", "ability", "reasoning", "g+"],
    "leadership": ["opq leadership", "executive", "manager", "director"],
    "sales": ["sales transformation", "opq mq sales", "selling"],
    "safety": ["dependability", "safety instrument", "dsi", "reliability"],
    "coding": ["programming", "developer", "live coding", "software"],
    "java": ["core java", "java advanced", "java programming"],
    "python": ["core java", "programming", "developer"],
    "excel": ["microsoft excel", "ms excel", "spreadsheet"],
    "word": ["microsoft word", "ms word"],
    "sjt": ["situational judgment", "situational judgement", "biodata", "scenarios"],
    "situational": ["scenarios", "situational judgment", "situational judgement", "biodata"],
    "grad": ["graduate", "entry-level"],
    "graduate": ["graduate scenarios", "entry-level", "graduate level"],
    "customer service": ["contact center", "contact centre", "call simulation", "phone simulation"],
    "contact centre": ["contact center", "call simulation", "customer service"],
    "contact center": ["contact centre", "call simulation", "customer service"],
    "numerical": ["verify numerical", "numerical reasoning", "math"],
    "verbal": ["verify verbal", "verbal reasoning"],
    "inductive": ["verify inductive", "inductive reasoning"],
    "deductive": ["verify deductive", "deductive reasoning"],
    "g+": ["verify g+", "general ability", "cognitive"],
    "iq": ["verify g+", "cognitive", "ability"],
    "typescript": ["javascript", "programming", "developer"],
    "react": ["javascript", "programming", "developer", "angular"],
    "aws": ["amazon web services", "cloud", "devops"],
    "docker": ["devops", "kubernetes", "cloud"],
    "devops": ["docker", "kubernetes", "aws", "cloud"],
    "nurse": ["medical", "healthcare", "nursing"],
    "healthcare": ["medical", "nursing", "hipaa"],
    "manufacturing": ["industrial", "safety", "dependability"],
    "plant": ["industrial", "manufacturing", "safety"],
    "finance": ["financial", "accounting", "numerical"],
    "accounting": ["financial accounting", "accounts payable", "accounts receivable"],
    "admin": ["administrative", "excel", "word", "data entry"],
    "administrative": ["excel", "word", "microsoft", "data entry"],
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def expand_query(text: str) -> str:
    lowered = text.lower()
    extra: list[str] = []
    for trigger, expansions in SYNONYM_EXPANSIONS.items():
        if trigger in lowered:
            extra.extend(expansions)
    if extra:
        return text + " " + " ".join(extra)
    return text


@dataclass
class ScoredItem:
    item: CatalogItem
    score: float


class MetadataFilter:
    """Optional structured filters extracted from the conversation."""

    def __init__(
        self,
        test_type_codes: set[str] | None = None,
        max_duration_minutes: int | None = None,
        require_remote: bool | None = None,
        require_adaptive: bool | None = None,
        language: str | None = None,
    ) -> None:
        self.test_type_codes = test_type_codes or set()
        self.max_duration_minutes = max_duration_minutes
        self.require_remote = require_remote
        self.require_adaptive = require_adaptive
        self.language = language.lower() if language else None

    def matches(self, item: CatalogItem) -> bool:
        if self.test_type_codes and not (self.test_type_codes & set(item.test_type_codes)):
            return False
        if self.max_duration_minutes is not None and item.duration_minutes:
            if item.duration_minutes > self.max_duration_minutes:
                return False
        if self.require_remote is True and not item.remote_testing:
            return False
        if self.require_adaptive is True and not item.adaptive:
            return False
        if self.language:
            langs = [lang.lower() for lang in item.languages]
            if langs and not any(self.language in lang for lang in langs):
                return False
        return True


class Retriever:
    """BM25-based hybrid retriever with metadata filtering and name-match boosting."""

    def __init__(self, items: list[CatalogItem]) -> None:
        self.items = items
        self._corpus_tokens = [tokenize(item.to_search_document()) for item in items]
        self._bm25 = BM25Okapi(self._corpus_tokens)
        # Build a lookup for fast URL-based access
        self._url_index: dict[str, CatalogItem] = {item.url: item for item in items}

    def search(
        self,
        query: str,
        top_k: int = 20,
        metadata_filter: MetadataFilter | None = None,
    ) -> list[ScoredItem]:
        if not query.strip():
            query = "assessment"

        expanded = expand_query(query)
        query_tokens = tokenize(expanded)
        bm25_scores = self._bm25.get_scores(query_tokens)

        query_lower = query.lower()
        scored: list[ScoredItem] = []
        for item, bm25_score in zip(self.items, bm25_scores):
            if metadata_filter and not metadata_filter.matches(item):
                continue
            score = float(bm25_score)

            # Strong boost for exact / near-exact product-name matches
            name_lower = item.name.lower()
            if name_lower in query_lower or query_lower in name_lower:
                score += 10.0
            elif len(name_lower) > 4 and name_lower[:6] in query_lower:
                score += 5.0

            # Word-level partial matches
            for word in name_lower.split():
                if len(word) > 3 and word in query_lower:
                    score += 2.0

            if score > 0:
                scored.append(ScoredItem(item=item, score=score))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def get_by_name(self, name: str) -> list[CatalogItem]:
        """Fuzzy name lookup, used by the comparison engine."""
        name_lower = name.lower().strip()
        exact = [i for i in self.items if i.name.lower() == name_lower]
        if exact:
            return exact
        contains = [i for i in self.items if name_lower in i.name.lower() or i.name.lower() in name_lower]
        if contains:
            return contains
        # token-overlap fallback
        name_tokens = set(tokenize(name))
        scored = []
        for item in self.items:
            overlap = len(name_tokens & set(tokenize(item.name)))
            if overlap:
                scored.append((overlap, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [i for _, i in scored[:3]]

    def get_by_url(self, url: str) -> CatalogItem | None:
        return self._url_index.get(url)
