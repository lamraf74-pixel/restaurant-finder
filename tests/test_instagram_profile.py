"""Tests du client de profil Instagram (nom, bio, followers) et du filtre associé."""

from __future__ import annotations

import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.instagram_profile import InstagramProfileClient
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.services.restaurant_finder_service import RestaurantFinderService
from restaurant_finder.sources.base import RestaurantSource


class _StubSource(RestaurantSource):
    def find_restaurants(self, city: str, categories):  # type: ignore[no-untyped-def]
        return []

    def find_restaurants_near_points(self, points, categories):  # type: ignore[no-untyped-def]
        return []


class _StubSearchProvider(SearchProvider):
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        return self._results[:max_results]


class _StubFollowerClient:
    def __init__(self, counts: dict[str, int | None]) -> None:
        self._counts = counts

    def get_follower_count(self, instagram_url_or_handle: str) -> int | None:
        handle = instagram_url_or_handle.rstrip("/").split("/")[-1]
        return self._counts.get(handle)


_PROFILE_HTML = (
    '{{"full_name":"{full_name}","biography":"{biography}",'
    '"is_private":{is_private},"follower_count":{followers},"username":"{handle}"}}'
)


@responses.activate
def test_get_profile_parses_full_name_biography_and_followers() -> None:
    settings = Settings(instagram_followers_delay_seconds=0)
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/petitbistrot/",
        body=_PROFILE_HTML.format(
            full_name="Le Petit Bistrot",
            biography="Restaurant familial a Lyon",
            is_private="false",
            followers=420,
            handle="petitbistrot",
        ),
        status=200,
    )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    profile = client.get_profile("https://www.instagram.com/petitbistrot/")

    assert profile is not None
    assert profile.full_name == "Le Petit Bistrot"
    assert profile.biography == "Restaurant familial a Lyon"
    assert profile.follower_count == 420
    assert profile.is_private is False


@responses.activate
def test_get_follower_count_delegates_to_get_profile() -> None:
    settings = Settings(instagram_followers_delay_seconds=0)
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/petitbistrot/",
        body='{"follower_count":420}',
        status=200,
    )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    assert client.get_follower_count("https://www.instagram.com/petitbistrot/") == 420


@responses.activate
def test_get_profile_returns_none_when_page_unreadable() -> None:
    settings = Settings(instagram_followers_delay_seconds=0)
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/inconnu/",
        body="<html>login wall</html>",
        status=200,
    )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    assert client.get_profile("inconnu") is None


def test_service_excludes_instagram_with_too_many_followers() -> None:
    settings = Settings(
        instagram_search_delay_seconds=0,
        instagram_max_followers=1000,
        instagram_filter_by_followers=True,
        instagram_exclude_unknown_followers=True,
    )
    restaurant = Restaurant(
        osm_id="node/1",
        name="Le Petit Bistrot",
        category="Restaurant",
        city="Lyon",
    )
    finder = InstagramFinder(
        _StubSearchProvider(
            [
                SearchResult(
                    title="Le Petit Bistrot",
                    url="https://www.instagram.com/lepetitbistrot/",
                )
            ]
        ),
        settings,
    )
    service = RestaurantFinderService(
        source=_StubSource(),
        settings=settings,
        instagram_finder=finder,
        follower_client=_StubFollowerClient({"lepetitbistrot": 2500}),  # type: ignore[arg-type]
    )

    enriched = service.enrich_with_instagram([restaurant])
    assert enriched[0].instagram_url is None
    assert enriched[0].instagram_followers == 2500


def test_service_keeps_instagram_below_follower_threshold() -> None:
    settings = Settings(
        instagram_search_delay_seconds=0,
        instagram_max_followers=1000,
        instagram_filter_by_followers=True,
        instagram_exclude_unknown_followers=True,
    )
    restaurant = Restaurant(
        osm_id="node/1",
        name="Le Petit Bistrot",
        category="Restaurant",
        city="Lyon",
    )
    finder = InstagramFinder(
        _StubSearchProvider(
            [
                SearchResult(
                    title="Le Petit Bistrot",
                    url="https://www.instagram.com/lepetitbistrot/",
                )
            ]
        ),
        settings,
    )
    service = RestaurantFinderService(
        source=_StubSource(),
        settings=settings,
        instagram_finder=finder,
        follower_client=_StubFollowerClient({"lepetitbistrot": 420}),  # type: ignore[arg-type]
    )

    enriched = service.enrich_with_instagram([restaurant])
    assert enriched[0].instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert enriched[0].instagram_followers == 420


def test_service_excludes_unknown_followers_by_default() -> None:
    settings = Settings(
        instagram_search_delay_seconds=0,
        instagram_max_followers=1000,
        instagram_filter_by_followers=True,
        instagram_exclude_unknown_followers=True,
    )
    restaurant = Restaurant(
        osm_id="node/1",
        name="Le Petit Bistrot",
        category="Restaurant",
        city="Lyon",
    )
    finder = InstagramFinder(
        _StubSearchProvider(
            [
                SearchResult(
                    title="Le Petit Bistrot",
                    url="https://www.instagram.com/lepetitbistrot/",
                )
            ]
        ),
        settings,
    )
    service = RestaurantFinderService(
        source=_StubSource(),
        settings=settings,
        instagram_finder=finder,
        follower_client=_StubFollowerClient({"lepetitbistrot": None}),  # type: ignore[arg-type]
    )

    enriched = service.enrich_with_instagram([restaurant])
    assert enriched[0].instagram_url is None
