"""Tests d'orchestration de `RestaurantFinderService` (villes + points GPS)."""

from __future__ import annotations

import pytest

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.exceptions import GeocodingError
from restaurant_finder.geocoding.geo_math import PointQuery
from restaurant_finder.progress import SearchProgress, compute_run_id, progress_dir_for
from restaurant_finder.services.restaurant_finder_service import RestaurantFinderService
from restaurant_finder.sources.base import RestaurantSource


def _restaurant(osm_id: str, name: str, cuisine: str | None = None) -> Restaurant:
    return Restaurant(
        osm_id=osm_id, name=name, category="Restaurant", city="Nice", cuisine=cuisine
    )

class _PartiallyFailingSource(RestaurantSource):
    """Simule une ville qui échoue (réseau/géocodage) parmi plusieurs demandées."""

    def __init__(
        self,
        by_city: dict[str, list[Restaurant]] | None = None,
        failing_cities: set[str] | None = None,
    ) -> None:
        self._by_city = by_city or {}
        self._failing_cities = failing_cities or set()

    def find_restaurants(self, city, categories):  # type: ignore[no-untyped-def]
        if city in self._failing_cities:
            raise GeocodingError(f"Ville introuvable : {city!r}.")
        return list(self._by_city.get(city, []))

    def find_restaurants_near_points(self, points, categories):  # type: ignore[no-untyped-def]
        return []


class _CountingSearchProvider(SearchProvider):
    """Recense les requêtes reçues, pour vérifier qu'un restaurant a (ou non) été recherché."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.queries.append(query)
        return []


class _RecordingSource(RestaurantSource):
    def __init__(
        self,
        by_city: dict[str, list[Restaurant]] | None = None,
        by_points: list[Restaurant] | None = None,
    ) -> None:
        self._by_city = by_city or {}
        self._by_points = by_points or []
        self.city_calls: list[str] = []
        self.point_calls: list[tuple] = []

    def find_restaurants(self, city, categories):  # type: ignore[no-untyped-def]
        self.city_calls.append(city)
        return list(self._by_city.get(city, []))

    def find_restaurants_near_points(self, points, categories):  # type: ignore[no-untyped-def]
        self.point_calls.append(tuple(points))
        return list(self._by_points)


def test_find_restaurants_requires_city_or_points() -> None:
    service = RestaurantFinderService(source=_RecordingSource(), settings=Settings())

    with pytest.raises(ValueError):
        service.find_restaurants()


def test_find_restaurants_by_single_city() -> None:
    source = _RecordingSource(by_city={"Nice": [_restaurant("node/1", "Le Petit Bistrot")]})
    service = RestaurantFinderService(source=source, settings=Settings())

    restaurants = service.find_restaurants(cities=["Nice"], enrich_instagram=False)

    assert [r.name for r in restaurants] == ["Le Petit Bistrot"]
    assert source.city_calls == ["Nice"]
    assert source.point_calls == []


def test_find_restaurants_merges_multiple_cities() -> None:
    source = _RecordingSource(
        by_city={
            "Nice": [_restaurant("node/1", "Le Safari")],
            "Lyon": [_restaurant("node/2", "Le Petit Bistrot")],
        }
    )
    service = RestaurantFinderService(source=source, settings=Settings())

    restaurants = service.find_restaurants(cities=["Nice", "Lyon"], enrich_instagram=False)

    assert source.city_calls == ["Nice", "Lyon"]
    assert sorted(r.name for r in restaurants) == ["Le Petit Bistrot", "Le Safari"]


def test_find_restaurants_by_points_only() -> None:
    source = _RecordingSource(by_points=[_restaurant("node/2", "Le Safari")])
    service = RestaurantFinderService(source=source, settings=Settings())

    point = PointQuery(43.7, 7.27, 500)
    restaurants = service.find_restaurants(near_points=[point], enrich_instagram=False)

    assert [r.name for r in restaurants] == ["Le Safari"]
    assert source.point_calls == [(point,)]


def test_find_restaurants_merges_and_dedupes_cities_and_points() -> None:
    shared = _restaurant("node/1", "Doublon")
    source = _RecordingSource(
        by_city={"Nice": [shared, _restaurant("node/2", "Uniquement ville")]},
        by_points=[shared, _restaurant("node/3", "Uniquement point")],
    )
    service = RestaurantFinderService(source=source, settings=Settings())

    restaurants = service.find_restaurants(
        cities=["Nice"], near_points=[PointQuery(43.7, 7.27, 500)], enrich_instagram=False
    )

    names = sorted(r.name for r in restaurants)
    assert names == ["Doublon", "Uniquement point", "Uniquement ville"]


def test_find_restaurants_does_not_filter_cuisine_by_default() -> None:
    source = _RecordingSource(
        by_city={
            "Nice": [
                _restaurant("node/1", "Pizza", cuisine="pizza"),
                _restaurant("node/2", "Sushi", cuisine="sushi"),
                _restaurant("node/3", "Sans tag", cuisine=None),
            ]
        }
    )
    service = RestaurantFinderService(source=source, settings=Settings())

    restaurants = service.find_restaurants(cities=["Nice"], enrich_instagram=False)

    assert [r.name for r in restaurants] == ["Pizza", "Sushi", "Sans tag"]


def test_find_restaurants_filters_by_cuisine_when_requested() -> None:
    source = _RecordingSource(
        by_city={
            "Nice": [
                _restaurant("node/1", "Pizza", cuisine="pizza"),
                _restaurant("node/2", "Sushi", cuisine="sushi"),
                _restaurant("node/3", "Sans tag", cuisine=None),
            ]
        }
    )
    service = RestaurantFinderService(source=source, settings=Settings())

    restaurants = service.find_restaurants(
        cities=["Nice"], enrich_instagram=False, cuisines=("pizza",)
    )

    assert [r.name for r in restaurants] == ["Pizza"]


def test_find_restaurants_excludes_non_empty_brand_by_default() -> None:
    source = _RecordingSource(
        by_city={
            "Nice": [
                _restaurant("node/1", "Indépendant"),
                Restaurant(
                    osm_id="node/2",
                    name="Chaîne locale",
                    category="Restaurant",
                    city="Nice",
                    cuisine="pizza",
                    brand="Ma Franchise",
                ),
            ]
        }
    )
    service = RestaurantFinderService(source=source, settings=Settings())

    restaurants = service.find_restaurants(cities=["Nice"], enrich_instagram=False)

    assert [r.name for r in restaurants] == ["Indépendant"]


def test_prepare_export_list_keeps_all_confidences_and_sorts_best_first() -> None:
    from restaurant_finder.domain.models import InstagramConfidence

    sans_ig = Restaurant(osm_id="node/4", name="D", category="Restaurant")
    faible = Restaurant(
        osm_id="node/3",
        name="C",
        category="Restaurant",
        instagram_url="https://www.instagram.com/c/",
        instagram_confidence=InstagramConfidence.FAIBLE,
    )
    eleve = Restaurant(
        osm_id="node/1",
        name="A",
        category="Restaurant",
        instagram_url="https://www.instagram.com/a/",
        instagram_confidence=InstagramConfidence.ELEVE,
    )
    moyen = Restaurant(
        osm_id="node/2",
        name="B",
        category="Restaurant",
        instagram_url="https://www.instagram.com/b/",
        instagram_confidence=InstagramConfidence.MOYEN,
    )

    sorted_rows = RestaurantFinderService.prepare_export_list(
        [sans_ig, faible, eleve, moyen]
    )

    assert [r.name for r in sorted_rows] == ["A", "B", "C", "D"]
    assert sorted_rows[0].instagram_confidence == InstagramConfidence.ELEVE
    assert sorted_rows[0].instagram_url == "https://www.instagram.com/a/"
    assert sorted_rows[1].instagram_confidence == InstagramConfidence.MOYEN
    assert sorted_rows[1].instagram_url == "https://www.instagram.com/b/"
    assert sorted_rows[2].instagram_confidence == InstagramConfidence.FAIBLE
    assert sorted_rows[3].instagram_url is None


def test_prepare_export_list_orders_inactive_and_unreadable_after_faible() -> None:
    from restaurant_finder.domain.models import InstagramConfidence

    illisible = Restaurant(
        osm_id="node/2",
        name="B",
        category="Restaurant",
        instagram_url="https://www.instagram.com/b/",
        instagram_confidence=InstagramConfidence.DATE_ILLISIBLE,
    )
    inactif = Restaurant(
        osm_id="node/1",
        name="A",
        category="Restaurant",
        instagram_url="https://www.instagram.com/a/",
        instagram_confidence=InstagramConfidence.INACTIF,
    )
    faible = Restaurant(
        osm_id="node/3",
        name="C",
        category="Restaurant",
        instagram_url="https://www.instagram.com/c/",
        instagram_confidence=InstagramConfidence.FAIBLE,
    )

    sorted_rows = RestaurantFinderService.prepare_export_list(
        [illisible, inactif, faible]
    )

    assert [r.name for r in sorted_rows] == ["C", "A", "B"]
    assert sorted_rows[0].instagram_confidence == InstagramConfidence.FAIBLE
    assert sorted_rows[1].instagram_confidence == InstagramConfidence.INACTIF
    assert sorted_rows[2].instagram_confidence == InstagramConfidence.DATE_ILLISIBLE
    assert sorted_rows[1].instagram_url == "https://www.instagram.com/a/"
    assert sorted_rows[2].instagram_url == "https://www.instagram.com/b/"


def test_keep_active_accounts_drops_inactive_and_unreadable() -> None:
    from restaurant_finder.domain.models import InstagramConfidence

    eleve = Restaurant(
        osm_id="node/1",
        name="A",
        category="Restaurant",
        instagram_url="https://www.instagram.com/a/",
        instagram_confidence=InstagramConfidence.ELEVE,
    )
    inactif = Restaurant(
        osm_id="node/2",
        name="B",
        category="Restaurant",
        instagram_url="https://www.instagram.com/b/",
        instagram_confidence=InstagramConfidence.INACTIF,
    )
    illisible = Restaurant(
        osm_id="node/3",
        name="C",
        category="Restaurant",
        instagram_url="https://www.instagram.com/c/",
        instagram_confidence=InstagramConfidence.DATE_ILLISIBLE,
    )
    sans_ig = Restaurant(osm_id="node/4", name="D", category="Restaurant")
    moyen = Restaurant(
        osm_id="node/5",
        name="E",
        category="Restaurant",
        instagram_url="https://www.instagram.com/e/",
        instagram_confidence=InstagramConfidence.MOYEN,
    )

    kept = RestaurantFinderService.keep_active_accounts(
        [eleve, inactif, illisible, sans_ig, moyen]
    )

    assert [r.name for r in kept] == ["A", "E"]
    assert all(r.activity_status == "Actifs" for r in kept)


# --- Résilience multi-villes / multi-points ---------------------------------


def test_find_restaurants_continues_when_one_city_fails_among_several() -> None:
    source = _PartiallyFailingSource(
        by_city={"Lyon": [_restaurant("node/1", "Le Petit Bistrot")]},
        failing_cities={"VilleInconnue"},
    )
    service = RestaurantFinderService(source=source, settings=Settings())

    restaurants = service.find_restaurants(
        cities=["Lyon", "VilleInconnue"], enrich_instagram=False
    )

    assert [r.name for r in restaurants] == ["Le Petit Bistrot"]


def test_find_restaurants_raises_original_error_when_single_city_fails() -> None:
    source = _PartiallyFailingSource(failing_cities={"VilleInconnue"})
    service = RestaurantFinderService(source=source, settings=Settings())

    with pytest.raises(GeocodingError, match="VilleInconnue"):
        service.find_restaurants(cities=["VilleInconnue"], enrich_instagram=False)


def test_find_restaurants_raises_when_every_city_fails() -> None:
    source = _PartiallyFailingSource(failing_cities={"A", "B"})
    service = RestaurantFinderService(source=source, settings=Settings())

    with pytest.raises(GeocodingError):
        service.find_restaurants(cities=["A", "B"], enrich_instagram=False)


# --- Reprise après interruption (progression Instagram) ----------------------


def _build_instagram_service(
    settings: Settings, search_provider: SearchProvider
) -> RestaurantFinderService:
    finder = InstagramFinder(search_provider, settings)
    return RestaurantFinderService(
        source=_RecordingSource(), settings=settings, instagram_finder=finder
    )


def _run_id_for(settings: Settings, restaurants: list[Restaurant]) -> str:
    return compute_run_id(
        (r.osm_id for r in restaurants),
        settings.instagram_max_followers,
        settings.instagram_filter_by_followers,
        settings.instagram_exclude_unknown_followers,
        settings.instagram_match_threshold,
        settings.instagram_max_post_age_days,
    )


def test_enrich_with_instagram_skips_restaurants_already_in_progress_file() -> None:
    settings = Settings(instagram_search_delay_seconds=0)
    restaurant_a = _restaurant("node/1", "Déjà Traité")
    restaurant_b = _restaurant("node/2", "En Attente")

    run_id = _run_id_for(settings, [restaurant_a, restaurant_b])
    progress = SearchProgress(progress_dir_for(settings.cache_dir), run_id)
    progress.mark_done(
        "node/1",
        {
            "instagram_url": "https://www.instagram.com/deja_traite/",
            "instagram_followers": 42,
            "instagram_confidence": "Élevé",
        },
    )

    search_provider = _CountingSearchProvider()
    service = _build_instagram_service(settings, search_provider)

    enriched = service.enrich_with_instagram([restaurant_a, restaurant_b])

    by_name = {r.name: r for r in enriched}
    assert by_name["Déjà Traité"].instagram_url == "https://www.instagram.com/deja_traite/"
    assert by_name["Déjà Traité"].instagram_followers == 42
    # Le restaurant déjà traité ne doit jamais avoir été recherché à nouveau.
    assert all("Déjà Traité" not in query for query in search_provider.queries)


def test_enrich_with_instagram_fresh_ignores_saved_progress() -> None:
    settings = Settings(instagram_search_delay_seconds=0)
    restaurant_a = _restaurant("node/1", "Déjà Traité")

    run_id = _run_id_for(settings, [restaurant_a])
    progress = SearchProgress(progress_dir_for(settings.cache_dir), run_id)
    progress.mark_done(
        "node/1", {"instagram_url": None, "instagram_followers": None, "instagram_confidence": None}
    )

    search_provider = _CountingSearchProvider()
    service = _build_instagram_service(settings, search_provider)

    service.enrich_with_instagram([restaurant_a], resume=False)

    assert any("Déjà Traité" in query for query in search_provider.queries)


def test_enrich_with_instagram_clears_progress_file_after_full_completion() -> None:
    settings = Settings(instagram_search_delay_seconds=0)
    restaurant = _restaurant("node/1", "Terminé")
    run_id = _run_id_for(settings, [restaurant])
    progress = SearchProgress(progress_dir_for(settings.cache_dir), run_id)

    service = _build_instagram_service(settings, _CountingSearchProvider())
    service.enrich_with_instagram([restaurant])

    assert progress.load() == {}
    assert not progress.path.exists()


def test_enrich_with_instagram_saves_progress_and_reraises_on_keyboard_interrupt() -> None:
    settings = Settings(instagram_search_delay_seconds=0, instagram_search_max_workers=1)
    restaurant_a = _restaurant("node/1", "Premier")
    restaurant_b = _restaurant("node/2", "Second")
    run_id = _run_id_for(settings, [restaurant_a, restaurant_b])

    service = _build_instagram_service(settings, _CountingSearchProvider())

    def on_progress(done: int, total: int) -> None:
        if done == 1:
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        service.enrich_with_instagram(
            [restaurant_a, restaurant_b], on_progress=on_progress
        )

    saved = SearchProgress(progress_dir_for(settings.cache_dir), run_id).load()
    assert len(saved) == 1
    assert "node/1" in saved
