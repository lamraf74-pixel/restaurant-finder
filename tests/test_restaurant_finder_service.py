"""Tests d'orchestration de `RestaurantFinderService` (villes + points GPS)."""

from __future__ import annotations

import pytest

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.geocoding.geo_math import PointQuery
from restaurant_finder.services.restaurant_finder_service import RestaurantFinderService
from restaurant_finder.sources.base import RestaurantSource


def _restaurant(osm_id: str, name: str, cuisine: str = "bistro") -> Restaurant:
    return Restaurant(
        osm_id=osm_id, name=name, category="Restaurant", city="Nice", cuisine=cuisine
    )

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


def test_find_restaurants_filters_by_cuisine() -> None:
    source = _RecordingSource(
        by_city={
            "Nice": [
                _restaurant("node/1", "Pizza", cuisine="pizza"),
                _restaurant("node/2", "Sushi", cuisine="sushi"),
                Restaurant(
                    osm_id="node/3",
                    name="Sans tag",
                    category="Restaurant",
                    city="Nice",
                    cuisine=None,
                ),
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


def test_split_by_instagram_confidence_moves_faible_aside() -> None:
    from restaurant_finder.domain.models import InstagramConfidence

    eleve = Restaurant(
        osm_id="node/1",
        name="A",
        category="Restaurant",
        instagram_url="https://www.instagram.com/a/",
        instagram_confidence=InstagramConfidence.ELEVE,
    )
    faible = Restaurant(
        osm_id="node/2",
        name="B",
        category="Restaurant",
        instagram_url="https://www.instagram.com/b/",
        instagram_confidence=InstagramConfidence.FAIBLE,
    )

    trusted, to_review = RestaurantFinderService.split_by_instagram_confidence([eleve, faible])

    assert [r.name for r in trusted] == ["A", "B"]
    assert trusted[1].instagram_url is None
    assert trusted[1].instagram_confidence is None
    assert len(to_review) == 1
    assert to_review[0].instagram_url == "https://www.instagram.com/b/"
    assert to_review[0].instagram_confidence == InstagramConfidence.FAIBLE
