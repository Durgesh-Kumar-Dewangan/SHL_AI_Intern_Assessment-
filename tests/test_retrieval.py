from __future__ import annotations

from app.config import get_settings
from app.data.catalog_loader import load_catalog
from app.retrieval.retriever import MetadataFilter, Retriever


def _retriever() -> Retriever:
    settings = get_settings()
    return Retriever(load_catalog(settings.catalog_path))


def test_catalog_loads_and_has_expected_size():
    settings = get_settings()
    items = load_catalog(settings.catalog_path)
    assert len(items) > 300
    for item in items[:5]:
        assert item.name
        assert item.url.startswith("https://www.shl.com/")
        assert item.test_type


def test_search_returns_relevant_results_for_java():
    r = _retriever()
    results = r.search("java developer backend spring", top_k=10)
    names = [s.item.name.lower() for s in results]
    assert any("java" in n for n in names)


def test_search_handles_empty_query_gracefully():
    r = _retriever()
    results = r.search("", top_k=5)
    assert len(results) <= 5


def test_metadata_filter_duration():
    r = _retriever()
    filt = MetadataFilter(max_duration_minutes=10)
    results = r.search("knowledge test", top_k=50, metadata_filter=filt)
    for s in results:
        if s.item.duration_minutes:
            assert s.item.duration_minutes <= 10


def test_get_by_name_fuzzy_match():
    r = _retriever()
    matches = r.get_by_name("OPQ32r")
    assert matches
    assert any("OPQ32r" in m.name or "Occupational Personality" in m.name for m in matches)


def test_get_by_url_roundtrip():
    r = _retriever()
    item = r.items[0]
    found = r.get_by_url(item.url)
    assert found is not None
    assert found.name == item.name


def test_no_duplicate_urls_in_catalog():
    r = _retriever()
    urls = [i.url for i in r.items]
    assert len(urls) == len(set(urls))
