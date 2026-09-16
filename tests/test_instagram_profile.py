"""Tests du client de profil Instagram (nom, bio, followers, activité) et du filtre associé."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import InstagramConfidence, Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.instagram_profile import InstagramProfile, InstagramProfileClient
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
    def __init__(
        self,
        counts: dict[str, int | None],
        *,
        last_posts: dict[str, datetime | None] | None = None,
        media_counts: dict[str, int | None] | None = None,
    ) -> None:
        self._counts = counts
        self._last_posts = last_posts or {}
        self._media_counts = media_counts or {}

    def get_profile(self, instagram_url_or_handle: str) -> InstagramProfile | None:
        handle = instagram_url_or_handle.rstrip("/").split("/")[-1]
        if handle not in self._counts:
            return None
        followers = self._counts[handle]
        if (
            followers is None
            and handle not in self._last_posts
            and handle not in self._media_counts
        ):
            return None
        return InstagramProfile(
            username=handle,
            full_name="",
            biography="",
            follower_count=followers,
            is_private=False,
            last_post_at=self._last_posts.get(handle),
            media_count=self._media_counts.get(handle),
        )

    def get_follower_count(self, instagram_url_or_handle: str) -> int | None:
        profile = self.get_profile(instagram_url_or_handle)
        return profile.follower_count if profile else None


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
def test_get_profile_retries_on_transient_connection_error_then_succeeds() -> None:
    settings = Settings(
        instagram_followers_delay_seconds=0, retry_base_delay_seconds=0, retry_max_attempts=2
    )
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/petitbistrot/",
        body=requests.exceptions.ConnectionError(),
    )
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
    assert profile.follower_count == 420


@responses.activate
def test_get_profile_returns_none_after_persistent_connection_errors() -> None:
    settings = Settings(
        instagram_followers_delay_seconds=0, retry_base_delay_seconds=0, retry_max_attempts=2
    )
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    for _ in range(2):
        responses.add(
            responses.GET,
            "https://www.instagram.com/introuvable/",
            body=requests.exceptions.ConnectionError(),
        )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    assert client.get_profile("introuvable") is None


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


def _make_profile_html(
    *,
    full_name: str = "Le Petit Bistrot",
    biography: str = "Restaurant familial a Lyon",
    is_private: str = "false",
    followers: int = 420,
    handle: str = "petitbistrot",
    taken_at: int | None = None,
    extra_taken_at: int | None = None,
    latest_reel: int | None = None,
    media_count: int | None = None,
) -> str:
    parts = [
        f'"full_name":"{full_name}"',
        f'"biography":"{biography}"',
        f'"is_private":{is_private}',
        f'"follower_count":{followers}',
        f'"username":"{handle}"',
    ]
    if media_count is not None:
        parts.append(f'"media_count":{media_count}')
    if taken_at is not None:
        parts.append(f'"taken_at_timestamp":{taken_at}')
    if extra_taken_at is not None:
        parts.append(f'"taken_at_timestamp":{extra_taken_at}')
    if latest_reel is not None:
        parts.append(f'"latest_reel_media":{latest_reel}')
    return "{" + ",".join(parts) + "}"


def _utc_days_ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@responses.activate
def test_get_profile_parses_taken_at_timestamp_as_last_post() -> None:
    taken_at = int(_utc_days_ago(3).timestamp())
    settings = Settings(instagram_followers_delay_seconds=0)
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/petitbistrot/",
        body=_make_profile_html(taken_at=taken_at, extra_taken_at=taken_at - 86_400),
        status=200,
    )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    profile = client.get_profile("https://www.instagram.com/petitbistrot/")

    assert profile is not None
    assert profile.last_post_at is not None
    assert abs(profile.last_post_at.timestamp() - taken_at) < 1


@responses.activate
def test_get_profile_falls_back_to_latest_reel_media() -> None:
    reel_at = int(_utc_days_ago(2).timestamp())
    settings = Settings(instagram_followers_delay_seconds=0)
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/petitbistrot/",
        body=_make_profile_html(latest_reel=reel_at, media_count=4),
        status=200,
    )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    profile = client.get_profile("https://www.instagram.com/petitbistrot/")

    assert profile is not None
    assert profile.last_post_at is not None
    assert abs(profile.last_post_at.timestamp() - reel_at) < 1
    assert profile.media_count == 4


@responses.activate
def test_get_profile_parses_polaris_media_id_as_last_post() -> None:
    # Snowflake Instagram : (id >> 23) + epoch ≈ 2026-07-25.
    polaris_id = 3949203694732785370
    settings = Settings(instagram_followers_delay_seconds=0)
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/petitbistrot/",
        body=(
            '{"full_name":"Le Petit Bistrot","biography":"Lyon","is_private":false,'
            f'"follower_count":420,"username":"petitbistrot","latest_reel_media":0,'
            f'"id":"POLARIS_{polaris_id}","id":"POLARIS_100"'
            "}"
        ),
        status=200,
    )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    profile = client.get_profile("https://www.instagram.com/petitbistrot/")

    assert profile is not None
    assert profile.last_post_at is not None
    assert profile.last_post_at.date().isoformat() == "2026-07-25"
    assert profile.media_count == 2


@responses.activate
def test_get_profile_prefers_taken_at_over_polaris_and_reel() -> None:
    taken_at = int(_utc_days_ago(1).timestamp())
    polaris_id = 3949203694732785370
    settings = Settings(instagram_followers_delay_seconds=0)
    responses.add(responses.GET, "https://www.instagram.com/", body="ok", status=200)
    responses.add(
        responses.GET,
        "https://www.instagram.com/petitbistrot/",
        body=_make_profile_html(taken_at=taken_at, latest_reel=100)
        + f',"id":"POLARIS_{polaris_id}"',
        status=200,
    )

    client = InstagramProfileClient(settings=settings, session=requests.Session())
    profile = client.get_profile("https://www.instagram.com/petitbistrot/")

    assert profile is not None
    assert profile.last_post_at is not None
    assert abs(profile.last_post_at.timestamp() - taken_at) < 1


def _enrich_activity(
    *,
    last_post: datetime | None,
    media_count: int | None = None,
    max_post_age_days: int | None,
    followers: int | None = 420,
) -> Restaurant:
    settings = Settings(
        instagram_search_delay_seconds=0,
        instagram_max_followers=1000,
        instagram_filter_by_followers=True,
        instagram_exclude_unknown_followers=True,
        instagram_max_post_age_days=max_post_age_days,
    )
    restaurant = Restaurant(
        osm_id="node/1",
        name="Le Petit Bistrot",
        category="Restaurant",
        city="Lyon",
    )
    last_posts = {"lepetitbistrot": last_post} if last_post is not None else {}
    media_counts = {"lepetitbistrot": media_count} if media_count is not None else {}
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
        follower_client=_StubFollowerClient(  # type: ignore[arg-type]
            {"lepetitbistrot": followers},
            last_posts=last_posts,
            media_counts=media_counts,
        ),
    )
    return service.enrich_with_instagram([restaurant])[0]


def test_service_keeps_instagram_when_last_post_is_recent() -> None:
    restaurant = _enrich_activity(last_post=_utc_days_ago(5), max_post_age_days=30)

    assert restaurant.instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert restaurant.instagram_confidence == InstagramConfidence.ELEVE


def test_service_marks_instagram_inactive_when_last_post_is_old() -> None:
    restaurant = _enrich_activity(last_post=_utc_days_ago(60), max_post_age_days=30)

    assert restaurant.instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert restaurant.instagram_confidence == InstagramConfidence.INACTIF

    sorted_rows = RestaurantFinderService.prepare_export_list([restaurant])
    assert sorted_rows[0].instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert sorted_rows[0].instagram_confidence == InstagramConfidence.INACTIF


def test_service_marks_instagram_unreadable_when_last_post_missing() -> None:
    restaurant = _enrich_activity(last_post=None, max_post_age_days=30)

    assert restaurant.instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert restaurant.instagram_confidence == InstagramConfidence.DATE_ILLISIBLE

    sorted_rows = RestaurantFinderService.prepare_export_list([restaurant])
    assert sorted_rows[0].instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert sorted_rows[0].instagram_confidence == InstagramConfidence.DATE_ILLISIBLE


def test_service_treats_account_without_posts_as_inactive() -> None:
    restaurant = _enrich_activity(last_post=None, media_count=0, max_post_age_days=30)

    assert restaurant.instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert restaurant.instagram_confidence == InstagramConfidence.INACTIF


def test_service_ignores_old_last_post_when_activity_filter_disabled() -> None:
    restaurant = _enrich_activity(last_post=_utc_days_ago(400), max_post_age_days=None)

    assert restaurant.instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert restaurant.instagram_confidence == InstagramConfidence.ELEVE


def test_instagram_profile_cache_roundtrip_preserves_last_post_and_media_count() -> None:
    posted = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    profile = InstagramProfile(
        username="petitbistrot",
        full_name="Le Petit Bistrot",
        biography="Lyon",
        follower_count=420,
        is_private=False,
        last_post_at=posted,
        media_count=12,
    )

    restored = InstagramProfile.from_cache_dict(profile.to_cache_dict())

    assert restored.last_post_at == posted
    assert restored.media_count == 12
    assert restored.follower_count == 420
