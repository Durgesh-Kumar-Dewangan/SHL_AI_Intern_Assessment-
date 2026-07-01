"""Loads the cleaned SHL Individual Test Solutions catalog into memory.

The catalog was scraped once (see `scripts/build_catalog.py` for the cleaning
pipeline that produced shl_catalog.json from the raw scrape) and is shipped as
a static JSON file so the service has zero external dependencies at request
time -- no network calls, no scraping, no flaky third-party downtime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class CatalogItem:
    id: str
    name: str
    url: str
    description: str
    duration_minutes: int | None
    duration_display: str
    adaptive: bool
    remote_testing: bool
    languages: tuple[str, ...] = field(default_factory=tuple)
    job_levels: tuple[str, ...] = field(default_factory=tuple)
    keys: tuple[str, ...] = field(default_factory=tuple)
    test_type: str = ""
    test_type_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_search_document(self) -> str:
        """Flattened text used for keyword / BM25 retrieval."""
        parts = [
            self.name,
            self.description,
            " ".join(self.keys),
            " ".join(self.job_levels),
            self.test_type,
        ]
        return " ".join(p for p in parts if p)

    def to_llm_context(self) -> dict:
        """Compact dict handed to the LLM as grounding context."""
        return {
            "name": self.name,
            "url": self.url,
            "test_type": self.test_type,
            "duration": self.duration_display,
            "adaptive": self.adaptive,
            "remote_testing": self.remote_testing,
            "languages": list(self.languages[:6]),
            "job_levels": list(self.job_levels),
            "description": self.description[:400],
        }


def _load_raw(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def load_catalog(path: Path) -> list[CatalogItem]:
    raw_items = _load_raw(Path(path))
    items: list[CatalogItem] = []
    for r in raw_items:
        items.append(
            CatalogItem(
                id=str(r["id"]),
                name=r["name"],
                url=r["url"],
                description=r.get("description", ""),
                duration_minutes=r.get("duration_minutes"),
                duration_display=r.get("duration_display", ""),
                adaptive=bool(r.get("adaptive")),
                remote_testing=bool(r.get("remote_testing")),
                languages=tuple(r.get("languages", [])),
                job_levels=tuple(r.get("job_levels", [])),
                keys=tuple(r.get("keys", [])),
                test_type=r.get("test_type", ""),
                test_type_codes=tuple(r.get("test_type_codes", [])),
            )
        )
    return items


def catalog_by_url(items: list[CatalogItem]) -> dict[str, CatalogItem]:
    return {item.url: item for item in items}
