"""Tests du service de recherche du profil Instagram."""

from __future__ import annotations

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult


class _StubSearchProvider(SearchProvider):
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.call_count = 0

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.call_count += 1
        return self._results[:max_results]


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self.store.get(key)

    def set(self, key: str, value: object) -> None:
        self.store[key] = value


def _settings(**overrides: object) -> Settings:
    return Settings(instagram_search_delay_seconds=0, **overrides)  # type: ignore[arg-type]


def test_find_returns_best_matching_instagram_profile(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(title="Pharmacie du Centre", url="https://pharmacieducentre.fr"),
        SearchResult(
            title="Le Petit Bistrot (@lepetitbistrot_officiel) • Instagram",
            url="https://www.instagram.com/lepetitbistrot_officiel/",
        ),
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings())

    assert finder.find(sample_restaurant) == "https://www.instagram.com/lepetitbistrot_officiel/"


def test_find_returns_none_when_no_result_meets_threshold(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(
            title="Pharmacie du Centre", url="https://www.instagram.com/pharmacieducentre/"
        )
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings(instagram_match_threshold=90))

    assert finder.find(sample_restaurant) is None


def test_find_ignores_non_profile_instagram_urls(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(title="Publication", url="https://www.instagram.com/p/ABC123/"),
        SearchResult(title="Le Petit Bistrot", url="https://www.instagram.com/lepetitbistrot/"),
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings())

    assert finder.find(sample_restaurant) == "https://www.instagram.com/lepetitbistrot/"


def test_find_ignores_urls_from_other_domains(sample_restaurant: Restaurant) -> None:
    results = [SearchResult(title="Le Petit Bistrot", url="https://www.facebook.com/lepetitbistrot/")]
    finder = InstagramFinder(_StubSearchProvider(results), _settings())

    assert finder.find(sample_restaurant) is None


def test_find_uses_cache_and_avoids_second_search(sample_restaurant: Restaurant) -> None:
    provider = _StubSearchProvider([])
    cache = _FakeCache()
    finder = InstagramFinder(provider, _settings(), cache=cache)

    first = finder.find(sample_restaurant)
    second = finder.find(sample_restaurant)

    assert first is None
    assert second is None
    assert provider.call_count == 1
